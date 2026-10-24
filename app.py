"""Cicero Volunteer Fire Department - membership roster (Flask + SQLite)."""
import base64
import csv
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import date
from functools import wraps
from itertools import groupby
from pathlib import Path
from urllib.parse import urlparse

import click
from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("CFD_DB", BASE_DIR / "data" / "cfd.db"))

DEFAULT_STATUSES = [
    "01-Active Members",
    "02-Junior Members",
    "03-In-Active Life Members",
    "05-Fire Chiefs",
    "06-Commissioners",
    "07-Auxiliary Members",
    "08-Honorary Members",
    "09-Line of Duty Family",
    "10-Hall Coordinator",
]

# (column, label, max length)
TEXT_FIELDS = [
    ("last_name", "Last Name", 100),
    ("first_name", "First Name", 100),
    ("member_id", "ID #", 30),
    ("status", "Membership Status", 100),
    ("job_title", "Job Title", 200),
    ("address", "Street", 200),
    ("city", "City", 100),
    ("state", "State", 50),
    ("zip", "Zip/Postal Code", 20),
    ("emergency_contact", "Emergency Contact", 200),
    ("home_phone", "Home Phone", 40),
    ("mobile_phone", "Mobile Phone", 40),
    ("email", "E-mail", 200),
    ("fire_station", "Fire Station", 20),
    ("notes", "Notes", 5000),
]
FIELD_MAX = {c: m for c, _, m in TEXT_FIELDS}

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    last_name         TEXT NOT NULL DEFAULT '',
    first_name        TEXT NOT NULL DEFAULT '',
    member_id         TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT '01-Active Members',
    job_title         TEXT NOT NULL DEFAULT '',
    address           TEXT NOT NULL DEFAULT '',
    city              TEXT NOT NULL DEFAULT '',
    state             TEXT NOT NULL DEFAULT '',
    zip               TEXT NOT NULL DEFAULT '',
    emergency_contact TEXT NOT NULL DEFAULT '',
    home_phone        TEXT NOT NULL DEFAULT '',
    mobile_phone      TEXT NOT NULL DEFAULT '',
    email             TEXT NOT NULL DEFAULT '',
    fire_station      TEXT NOT NULL DEFAULT '',
    notes             TEXT NOT NULL DEFAULT '',
    active            INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_members_name ON members(last_name COLLATE NOCASE, first_name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    can_edit      INTEGER NOT NULL DEFAULT 1,
    is_admin      INTEGER NOT NULL DEFAULT 0
);
"""


# --------------------------------------------------------------------------
# setup
# --------------------------------------------------------------------------
def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        # upgrade older databases: the first user ever created becomes the administrator
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        if "is_admin" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE users SET is_admin = 1, can_edit = 1 "
                         "WHERE id = (SELECT MIN(id) FROM users)")
        admin_pw = os.environ.get("CFD_ADMIN_PASSWORD")
        if admin_pw and not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            conn.execute(
                "INSERT INTO users (username, password_hash, can_edit, is_admin) VALUES (?, ?, 1, 1)",
                (os.environ.get("CFD_ADMIN_USER", "admin"), generate_password_hash(admin_pw)),
            )
        conn.commit()
    finally:
        conn.close()


def load_secret_key():
    env = os.environ.get("CFD_SECRET_KEY")
    if env:
        return env
    path = DB_PATH.parent / ".secret_key"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    for _ in range(20):  # tolerate another worker that is still writing it
        key = path.read_text().strip()
        if key:
            return key
        time.sleep(0.1)
    raise RuntimeError("could not load secret key")


init_db()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=load_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("CFD_COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
    MAX_CONTENT_LENGTH=256 * 1024,
)


def get_db():
    if "db" not in g:
        g.db = _connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# --------------------------------------------------------------------------
# auth / csrf / headers
# --------------------------------------------------------------------------
def pw_fingerprint(password_hash):
    """Ties a session to the current password, so a reset signs the user out everywhere."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


@app.before_request
def load_user():
    g.user = None
    uid = session.get("uid")
    if uid:
        user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if user is None or session.get("pv") != pw_fingerprint(user["password_hash"]):
            session.clear()
        else:
            g.user = user


@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = session.get("_csrf", "")
        sent = request.form.get("_csrf", "")
        if not token or not secrets.compare_digest(token, sent):
            abort(400, "Invalid or missing form token. Go back, reload the page and try again.")


@app.after_request
def security_headers(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if not request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store"  # pages contain personal data
    return resp


@app.context_processor
def inject_helpers():
    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return session["_csrf"]

    return {"csrf_token": csrf_token, "current_user": g.get("user")}


@app.template_filter("oneline")
def oneline(value):
    return " ".join((value or "").split())


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def edit_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not g.user["can_edit"]:
            abort(403, "Your account is view-only.")
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not g.user["is_admin"]:
            abort(403, "Only administrators can manage users.")
        return view(*args, **kwargs)

    return wrapped


def safe_next(target):
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            next_url = safe_next(request.args.get("next"))
            session.clear()
            session.permanent = True
            session["uid"] = user["id"]
            session["pv"] = pw_fingerprint(user["password_hash"])
            session["_csrf"] = secrets.token_hex(16)
            return redirect(next_url or url_for("members"))
        time.sleep(1)  # slow down password guessing
        flash("Incorrect username or password.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------------------
# user management (administrators) and own password
# --------------------------------------------------------------------------
ROLES = {  # role -> (is_admin, can_edit)
    "admin": (1, 1),
    "editor": (0, 1),
    "viewer": (0, 0),
}
ROLE_LABELS = {"admin": "Administrator", "editor": "Editor", "viewer": "Viewer (read-only)"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,40}$")
MIN_PASSWORD = 10


def role_of(user):
    return "admin" if user["is_admin"] else ("editor" if user["can_edit"] else "viewer")


def admin_count(db):
    return db.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0]


def password_error(password, confirm):
    if password != confirm:
        return "The two passwords don't match."
    if len(password) < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters."
    if len(password) > 200:
        return "Password is too long."
    return None


def all_users():
    return get_db().execute("SELECT * FROM users ORDER BY username COLLATE NOCASE").fetchall()


@app.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    form = {"username": "", "role": "editor"}
    if request.method == "POST":  # add a user
        username = request.form.get("username", "").strip()
        role = request.form.get("role", "")
        form = {"username": username, "role": role if role in ROLES else "editor"}
        error = None
        if not USERNAME_RE.match(username):
            error = "Username must be 3-40 characters: letters, numbers, dot, dash or underscore."
        elif role not in ROLES:
            error = "Choose a role."
        else:
            error = password_error(request.form.get("password", ""), request.form.get("password2", ""))
        if error is None:
            is_admin, can_edit = ROLES[role]
            try:
                get_db().execute(
                    "INSERT INTO users (username, password_hash, can_edit, is_admin) VALUES (?, ?, ?, ?)",
                    (username, generate_password_hash(request.form["password"]), can_edit, is_admin))
                get_db().commit()
            except sqlite3.IntegrityError:
                error = f"The username '{username}' is already taken."
        if error:
            flash(error, "error")
        else:
            flash(f"User '{username}' added.", "ok")
            return redirect(url_for("users"))
    return render_template("users.html", users=all_users(), roles=ROLE_LABELS, role_of=role_of, form=form)


def _get_user_or_404(user_id):
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        abort(404)
    return user


@app.route("/users/<int:user_id>/role", methods=["POST"])
@admin_required
def user_role(user_id):
    user = _get_user_or_404(user_id)
    role = request.form.get("role", "")
    if role not in ROLES:
        abort(400)
    is_admin, can_edit = ROLES[role]
    db = get_db()
    if user["is_admin"] and not is_admin and admin_count(db) <= 1:
        flash("There must be at least one administrator.", "error")
    else:
        db.execute("UPDATE users SET is_admin = ?, can_edit = ? WHERE id = ?", (is_admin, can_edit, user_id))
        db.commit()
        flash(f"{user['username']} is now {ROLE_LABELS[role].lower()}.", "ok")
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/password", methods=["POST"])
@admin_required
def user_password(user_id):
    user = _get_user_or_404(user_id)
    error = password_error(request.form.get("password", ""), request.form.get("password2", ""))
    if error:
        flash(error, "error")
    else:
        new_hash = generate_password_hash(request.form["password"])
        get_db().execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
        get_db().commit()
        if user_id == g.user["id"]:
            session["pv"] = pw_fingerprint(new_hash)  # keep the current session signed in
        flash(f"Password for {user['username']} changed. Their other sessions were signed out.", "ok")
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def user_delete(user_id):
    user = _get_user_or_404(user_id)
    db = get_db()
    if user_id == g.user["id"]:
        flash("You can't delete your own account.", "error")
    elif user["is_admin"] and admin_count(db) <= 1:
        flash("There must be at least one administrator.", "error")
    else:
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
        flash(f"User '{user['username']}' deleted.", "ok")
    return redirect(url_for("users"))


@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        if not check_password_hash(g.user["password_hash"], request.form.get("current", "")):
            time.sleep(1)
            flash("Current password is incorrect.", "error")
        else:
            error = password_error(request.form.get("password", ""), request.form.get("password2", ""))
            if error:
                flash(error, "error")
            else:
                new_hash = generate_password_hash(request.form["password"])
                get_db().execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, g.user["id"]))
                get_db().commit()
                session["pv"] = pw_fingerprint(new_hash)
                flash("Password changed.", "ok")
                return redirect(url_for("account"))
    return render_template("account.html", role=ROLE_LABELS[role_of(g.user)], min_password=MIN_PASSWORD)


# --------------------------------------------------------------------------
# members
# --------------------------------------------------------------------------
def all_statuses():
    rows = get_db().execute("SELECT DISTINCT status FROM members WHERE status <> ''").fetchall()
    return sorted(set(DEFAULT_STATUSES) | {r["status"] for r in rows})


def distinct_stations():
    rows = get_db().execute(
        "SELECT DISTINCT fire_station FROM members WHERE fire_station <> '' ORDER BY fire_station"
    ).fetchall()
    return [r["fire_station"] for r in rows]


@app.route("/")
@login_required
def members():
    q = request.args.get("q", "").strip()
    active = request.args.get("active", "1")
    status = request.args.get("status", "")
    station = request.args.get("station", "")

    sql = "SELECT * FROM members WHERE 1=1"
    params = []
    if q:
        like = f"%{q}%"
        cols = ["last_name", "first_name", "member_id", "email", "mobile_phone",
                "home_phone", "job_title", "city", "address"]
        sql += " AND (" + " OR ".join(f"{c} LIKE ?" for c in cols) + ")"
        params += [like] * len(cols)
    if active in ("0", "1"):
        sql += " AND active = ?"
        params.append(int(active))
    if status:
        sql += " AND status = ?"
        params.append(status)
    if station:
        sql += " AND fire_station = ?"
        params.append(station)
    sql += " ORDER BY last_name COLLATE NOCASE, first_name COLLATE NOCASE"
    rows = get_db().execute(sql, params).fetchall()
    return render_template(
        "members.html", rows=rows, q=q, active=active, status=status, station=station,
        statuses=all_statuses(), stations=distinct_stations(),
    )


def jump_list():
    return get_db().execute(
        "SELECT id, last_name, first_name FROM members "
        "ORDER BY last_name COLLATE NOCASE, first_name COLLATE NOCASE"
    ).fetchall()


def form_values(member=None):
    if member is not None:
        return {c: member[c] for c, _, _ in TEXT_FIELDS} | {"active": bool(member["active"])}
    return {c: "" for c, _, _ in TEXT_FIELDS} | {"status": DEFAULT_STATUSES[0], "active": True}


def format_phone(raw):
    """10-digit US numbers become (315) 555-0100; anything else is left as typed."""
    raw = (raw or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10 and re.fullmatch(r"[\d\s().+\-]*", raw):
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return raw


def read_form():
    values = {}
    errors = []
    for col, label, maxlen in TEXT_FIELDS:
        raw = request.form.get(col, "").replace("\r\n", "\n").strip()
        if col in ("home_phone", "mobile_phone"):
            raw = format_phone(raw)
        if len(raw) > maxlen:
            errors.append(f"{label} is too long (max {maxlen} characters).")
        values[col] = raw
    values["active"] = request.form.get("active") == "1"
    if not values["last_name"]:
        errors.append("Last Name is required.")
    return values, errors


@app.route("/members/new", methods=["GET", "POST"])
@edit_required
def member_new():
    values = form_values()
    if request.method == "POST":
        values, errors = read_form()
        if not errors:
            cols = [c for c, _, _ in TEXT_FIELDS] + ["active"]
            cur = get_db().execute(
                f"INSERT INTO members ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [values[c] if c != "active" else int(values[c]) for c in cols],
            )
            get_db().commit()
            flash("Member added.", "ok")
            if request.form.get("action") == "save_new":
                return redirect(url_for("member_new"))
            return redirect(url_for("member_edit", member_id=cur.lastrowid))
        for e in errors:
            flash(e, "error")
    return render_template("member_form.html", m=None, v=values, statuses=all_statuses(),
                           people=jump_list())


@app.route("/members/<int:member_id>", methods=["GET", "POST"])
@login_required
def member_edit(member_id):
    row = get_db().execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
    if row is None:
        abort(404)
    values = form_values(row)
    if request.method == "POST":
        if not g.user["can_edit"]:
            abort(403, "Your account is view-only.")
        values, errors = read_form()
        if not errors:
            cols = [c for c, _, _ in TEXT_FIELDS] + ["active"]
            get_db().execute(
                f"UPDATE members SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
                [values[c] if c != "active" else int(values[c]) for c in cols] + [member_id],
            )
            get_db().commit()
            flash("Saved.", "ok")
            if request.form.get("action") == "save_new":
                return redirect(url_for("member_new"))
            return redirect(url_for("member_edit", member_id=member_id))
        for e in errors:
            flash(e, "error")
    return render_template("member_form.html", m=row, v=values, statuses=all_statuses(),
                           people=jump_list())


@app.route("/members/<int:member_id>/delete", methods=["POST"])
@edit_required
def member_delete(member_id):
    cur = get_db().execute("DELETE FROM members WHERE id = ?", (member_id,))
    get_db().commit()
    if cur.rowcount:
        flash("Member deleted.", "ok")
    return redirect(url_for("members"))


def _vcard_escape(text):
    return (text or "").replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


@app.route("/members/<int:member_id>.vcf")
@login_required
def member_vcard(member_id):
    m = get_db().execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
    if m is None:
        abort(404)
    e = _vcard_escape
    lines = [
        "BEGIN:VCARD", "VERSION:3.0",
        f"N:{e(m['last_name'])};{e(m['first_name'])};;;",
        f"FN:{e((m['first_name'] + ' ' + m['last_name']).strip())}",
        "ORG:Cicero Volunteer Fire Department",
    ]
    if m["job_title"]:
        lines.append(f"TITLE:{e(oneline(m['job_title']))}")
    if m["mobile_phone"]:
        lines.append(f"TEL;TYPE=CELL:{e(m['mobile_phone'])}")
    if m["home_phone"]:
        lines.append(f"TEL;TYPE=HOME:{e(m['home_phone'])}")
    if m["email"]:
        lines.append(f"EMAIL;TYPE=INTERNET:{e(m['email'])}")
    if m["address"] or m["city"]:
        lines.append(f"ADR;TYPE=HOME:;;{e(oneline(m['address']))};{e(m['city'])};{e(m['state'])};{e(m['zip'])};")
    lines.append("END:VCARD")
    name = "".join(ch for ch in f"{m['first_name']}_{m['last_name']}" if ch.isalnum() or ch == "_") or "member"
    return Response("\r\n".join(lines) + "\r\n", mimetype="text/vcard",
                    headers={"Content-Disposition": f'attachment; filename="{name}.vcf"'})


# --------------------------------------------------------------------------
# roster report
# --------------------------------------------------------------------------
@app.template_filter("group_name")
def group_name(status):
    """'03-In-Active Life Members' -> 'In-Active Life Members' (the number only sorts the groups)."""
    return re.sub(r"^\d+\s*-\s*", "", status or "").strip() or "Other"


def render_roster(inline):
    rows = get_db().execute(
        "SELECT * FROM members WHERE active = 1 "
        "ORDER BY status, last_name COLLATE NOCASE, first_name COLLATE NOCASE"
    ).fetchall()
    groups = [(status, list(items)) for status, items in groupby(rows, key=lambda r: r["status"])]
    today = date.today()
    css = logo = None
    if inline:  # self-contained page for PDF / saved HTML
        css = (BASE_DIR / "static" / "roster.css").read_text()
        logo = "data:image/png;base64," + base64.b64encode(
            (BASE_DIR / "static" / "logo.png").read_bytes()).decode()
    return render_template("roster.html", groups=groups, total=len(rows), inline=inline, css=css,
                           logo=logo, date_str=f"{today.month}/{today.day}/{today.year}")


@app.route("/roster.pdf")
@login_required
def roster_pdf():
    from weasyprint import HTML  # imported lazily so the rest works without it

    pdf = HTML(string=render_roster(inline=True), base_url=str(BASE_DIR)).write_pdf()
    name = f"CFD_Membership_Roster_{date.today():%Y%m%d}.pdf"
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


# --------------------------------------------------------------------------
# Mobile Info export (mi.json) - replaces MobileInfo.xlsx + CreateKBMemberForm.ps1
# --------------------------------------------------------------------------
def contact_name(first, last):
    """Access 'Contact Name': First + ' ' + Last (either part may be missing)."""
    return " ".join(p for p in ((first or "").strip(), (last or "").strip()) if p)


def mobile_info_json(db):
    rows = db.execute("SELECT * FROM members WHERE active = 1").fetchall()
    rows = sorted(rows, key=lambda r: (contact_name(r["first_name"], r["last_name"]).lower(), r["id"]))
    records = [{
        "name": contact_name(r["first_name"], r["last_name"]),
        "id": r["member_id"] or "",
        "phone": r["mobile_phone"] or "",
        "email": r["email"] or "",
        # multi-line titles keep Windows-style line breaks, as the old export did
        "title": (r["job_title"] or "").replace("\r\n", "\n").replace("\n", "\r\n"),
    } for r in rows]
    # CRLF between lines like the old PowerShell output; newlines inside values stay escaped
    return json.dumps(records, indent=4, ensure_ascii=False).replace("\n", "\r\n") + "\r\n"


@app.route("/export/mi.json")
@admin_required
def export_mi_json():
    return Response(mobile_info_json(get_db()), mimetype="application/json",
                    headers={"Content-Disposition": 'attachment; filename="mi.json"'})


# --------------------------------------------------------------------------
# command line helpers:  flask --app app <command>
# --------------------------------------------------------------------------
@app.cli.command("create-user")
@click.argument("username")
@click.option("--viewer", is_flag=True, help="View-only account (cannot add/edit/delete).")
@click.option("--admin", is_flag=True, help="Administrator (can also manage users).")
@click.password_option()
def create_user(username, viewer, admin, password):
    """Create a login."""
    if viewer and admin:
        raise click.ClickException("Choose either --viewer or --admin.")
    conn = _connect()
    try:
        conn.execute("INSERT INTO users (username, password_hash, can_edit, is_admin) VALUES (?, ?, ?, ?)",
                     (username, generate_password_hash(password), 0 if viewer else 1, 1 if admin else 0))
        conn.commit()
    except sqlite3.IntegrityError:
        raise click.ClickException(f"User '{username}' already exists (use set-password).")
    finally:
        conn.close()
    click.echo(f"Created {'administrator' if admin else 'view-only' if viewer else 'editor'} user '{username}'.")


@app.cli.command("set-password")
@click.argument("username")
@click.password_option()
def set_password(username, password):
    """Change a user's password."""
    conn = _connect()
    cur = conn.execute("UPDATE users SET password_hash = ? WHERE username = ?",
                       (generate_password_hash(password), username))
    conn.commit()
    conn.close()
    if not cur.rowcount:
        raise click.ClickException(f"No such user '{username}'.")
    click.echo("Password updated.")


@app.cli.command("list-users")
def list_users():
    """List logins."""
    conn = _connect()
    for r in conn.execute("SELECT username, can_edit, is_admin FROM users ORDER BY username"):
        click.echo(f"{r['username']}\t{role_of(r)}")
    conn.close()


@app.cli.command("delete-user")
@click.argument("username")
def delete_user(username):
    """Remove a login."""
    conn = _connect()
    cur = conn.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    click.echo("Deleted." if cur.rowcount else "No such user.")


ACCESS_COLUMNS = {
    "Unique_ID": "id", "Last Name": "last_name", "First Name": "first_name",
    "Emergency Contact": "emergency_contact", "ID #": "member_id", "Address": "address",
    "City": "city", "State": "state", "ZIP/Postal Code": "zip", "Fire Station": "fire_station",
    "Job Title": "job_title", "Home Phone": "home_phone", "Mobile Phone": "mobile_phone",
    "E-mail Address": "email", "Membership Status": "status", "Notes": "notes", "Active": "active",
}
STATE_FIXES = {"new york": "NY"}


@app.cli.command("import-csv")
@click.argument("csv_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--replace", is_flag=True, help="Delete existing members first.")
def import_csv(csv_path, replace):
    """Load the Access Contacts table exported as CSV (header row required)."""
    canonical = {s.lower(): s for s in DEFAULT_STATUSES}
    conn = _connect()
    try:
        if conn.execute("SELECT 1 FROM members LIMIT 1").fetchone():
            if not replace:
                raise click.ClickException("members table is not empty; use --replace to overwrite.")
            conn.execute("DELETE FROM members")
        count = 0
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            for raw in csv.DictReader(f):
                rec = {new: (raw.get(old) or "").replace("\r\n", "\n").strip()
                       for old, new in ACCESS_COLUMNS.items()}
                rec["state"] = STATE_FIXES.get(rec["state"].lower(), rec["state"])
                rec["home_phone"] = format_phone(rec["home_phone"])
                rec["mobile_phone"] = format_phone(rec["mobile_phone"])
                rec["status"] = canonical.get(rec["status"].lower(), rec["status"])
                rec["active"] = 1 if rec["active"].lower() in ("1", "-1", "true", "yes", "y") else 0
                rec["id"] = int(rec["id"]) if rec["id"].isdigit() else None
                cols = list(rec)
                conn.execute(
                    f"INSERT INTO members ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                    [rec[c] for c in cols])
                count += 1
        conn.commit()
    finally:
        conn.close()
    click.echo(f"Imported {count} members.")


@app.cli.command("export-mi")
@click.argument("out", type=click.Path(dir_okay=False))
def export_mi(out):
    """Write mi.json to OUT (e.g. a mounted share)."""
    target = out
    conn = _connect()
    try:
        data = mobile_info_json(conn)
    finally:
        conn.close()
    with open(target, "wb") as f:
        f.write(data.encode("utf-8"))
    click.echo(f"Wrote {target}")


if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", 8000)))
