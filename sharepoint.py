"""Upload new member folders / PDFs to a SharePoint document library through Microsoft Graph.

Uses an Entra (Azure AD) app registration with the client-credentials flow. Secrets come from the
environment (SP_TENANT_ID, SP_CLIENT_ID, SP_CLIENT_SECRET); site, library and folder come from config.yaml.
Only the standard library is used.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

LOGIN_URL = os.environ.get("SP_LOGIN_URL", "https://login.microsoftonline.com").rstrip("/")
GRAPH_URL = os.environ.get("SP_GRAPH_URL", "https://graph.microsoft.com/v1.0").rstrip("/")
TIMEOUT = 30

_lock = threading.Lock()
_state = {"token": None, "expires": 0, "drive": None}


class SharePointError(Exception):
    """Something the user can act on (bad settings, no permission, SharePoint not reachable)."""


def _get(cfg, key, default=None):
    """Setting from a dict or from the app's settings object."""
    return cfg.get(key, default) if isinstance(cfg, dict) else getattr(cfg, key, default)


def credentials():
    return tuple(os.environ.get(k, "").strip() for k in ("SP_TENANT_ID", "SP_CLIENT_ID", "SP_CLIENT_SECRET"))


def is_configured(cfg):
    return bool(_get(cfg, "sharepoint_site_url") and all(credentials()))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _call(method, url, *, data=None, headers=None, form=None):
    """One HTTP request. Returns (status, parsed JSON or None). Never raises for HTTP status codes."""
    status, payload, _ = _call_h(method, url, data=data, headers=headers, form=form)
    return status, payload


def _call_h(method, url, *, data=None, headers=None, form=None, follow=True):
    """Like _call but returns (status, parsed JSON or None, response headers)."""
    hdrs = dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            status, body, rh = r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        status, body, rh = e.code, e.read(), e.headers
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SharePointError(f"Could not reach Microsoft 365 ({getattr(e, 'reason', e)}). "
                              "The server needs outbound HTTPS to login.microsoftonline.com and graph.microsoft.com.")
    try:
        return status, json.loads(body) if body else None, rh
    except ValueError:
        return status, None, rh


def _err(payload):
    if isinstance(payload, dict):
        e = payload.get("error")
        if isinstance(e, dict):
            return f"{e.get('code', '')}: {e.get('message', '')}".strip(": ")
        if e:
            return f"{e}: {payload.get('error_description', '')}".strip(": ")[:300]
    return ""


def _token():
    with _lock:
        if _state["token"] and time.time() < _state["expires"] - 60:
            return _state["token"]
    tenant, client, secret = credentials()
    status, p = _call("POST", f"{LOGIN_URL}/{urllib.parse.quote(tenant)}/oauth2/v2.0/token", form={
        "client_id": client, "client_secret": secret, "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default"})
    if status != 200 or not p or "access_token" not in p:
        raise SharePointError(f"Microsoft 365 sign-in failed ({status}). Check SP_TENANT_ID, SP_CLIENT_ID and "
                              f"SP_CLIENT_SECRET (the secret may have expired). {_err(p)}")
    with _lock:
        _state.update(token=p["access_token"], expires=time.time() + int(p.get("expires_in", 3600)))
    return p["access_token"]


def _graph(method, path, *, body=None, raw=None, content_type=None):
    headers = {"Authorization": f"Bearer {_token()}"}
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        content_type = "application/json"
    if content_type:
        headers["Content-Type"] = content_type
    return _call(method, GRAPH_URL + path, data=data, headers=headers)


def _drive_id(cfg):
    """Drive (document library) id for the configured site + library, cached per setting."""
    site_url = _get(cfg, "sharepoint_site_url")
    library = (_get(cfg, "sharepoint_library") or "Documents").strip()
    key = (site_url, library)
    if _state["drive"] and _state["drive"][0] == key:
        return _state["drive"][1]
    u = urllib.parse.urlparse(site_url)
    if not u.netloc or not u.path.strip("/"):
        raise SharePointError("sharepoint_site_url should look like https://yourtenant.sharepoint.com/sites/SiteName")
    site_path = urllib.parse.quote(u.path.rstrip("/"), safe="/")
    status, site = _graph("GET", f"/sites/{u.netloc}:{site_path}")
    if status in (401, 403):
        raise SharePointError("The app is not allowed to use this SharePoint site (403). Grant it access to the site "
                              f"(see README, SharePoint). {_err(site)}")
    if status != 200 or not site:
        raise SharePointError(f"SharePoint site not found ({status}). Check sharepoint_site_url. {_err(site)}")
    status, drives = _graph("GET", f"/sites/{site['id']}/drives")
    if status != 200 or not drives:
        raise SharePointError(f"Could not list the site's libraries ({status}). {_err(drives)}")
    want = library.lower()
    for d in drives.get("value", []):
        last = urllib.parse.unquote(d.get("webUrl", "")).rstrip("/").rsplit("/", 1)[-1]
        if want in (d.get("name", "").lower(), last.lower()):
            _state["drive"] = (key, d["id"])
            return d["id"]
    names = ", ".join(sorted(d.get("name", "?") for d in drives.get("value", [])))
    raise SharePointError(f"Library '{library}' not found on the site. Available: {names}. "
                          "Set sharepoint_library in config.yaml.")


def _clean_path(path):
    parts = [p for p in str(path).replace("\\", "/").split("/") if p.strip()]
    if any(p in (".", "..") for p in parts):
        raise SharePointError("The SharePoint folder setting may not contain '..'.")
    return parts


def _enc(parts):
    return urllib.parse.quote("/".join(parts), safe="/")


def make_folders(cfg, rel):
    """Create <sharepoint_folder>/<rel> level by level (existing levels are fine). Returns the full path."""
    drive = _drive_id(cfg)
    parts = _clean_path(_get(cfg, "sharepoint_folder") or "") + _clean_path(rel)
    for i, name in enumerate(parts):
        parent = parts[:i]
        path = f"/drives/{drive}/root:/{_enc(parent)}:/children" if parent else f"/drives/{drive}/root/children"
        status, p = _graph("POST", path, body={"name": name, "folder": {},
                                               "@microsoft.graph.conflictBehavior": "fail"})
        if status not in (200, 201, 409):
            raise SharePointError(f"Could not create the SharePoint folder '{name}' ({status}). {_err(p)}")
    return "/".join(parts)


def upload(cfg, rel, filename, data):
    """Upload bytes as <sharepoint_folder>/<rel>/<filename>, replacing a file of the same name.
    Folders are created automatically. Returns (file name, link to the file in SharePoint or '')."""
    drive = _drive_id(cfg)
    base = _clean_path(_get(cfg, "sharepoint_folder") or "") + _clean_path(rel)
    status, p = _graph("PUT", f"/drives/{drive}/root:/{_enc(base + [filename])}:/content"
                               "?@microsoft.graph.conflictBehavior=replace",
                       raw=data, content_type="application/pdf")
    if status not in (200, 201):
        raise SharePointError(f"SharePoint upload failed ({status}). {_err(p)}")
    return filename, (p.get("webUrl", "") if isinstance(p, dict) else "")


def _folder_id(drive, parts):
    status, p = _graph("GET", f"/drives/{drive}/root:/{_enc(parts)}")
    if status != 200 or not p or "id" not in p:
        raise SharePointError(f"Could not find the SharePoint folder '{'/'.join(parts)}' ({status}). {_err(p)}")
    return p["id"]


def _norm(text):
    """Letters and digits only, lower case: 'De La Cruz' -> 'delacruz'."""
    return "".join(ch for ch in str(text).casefold() if ch.isalnum())


def _wait_for_copy(monitor_url):
    """Poll the copy job for a few seconds. Returns 'done', 'failed' or 'pending'."""
    for _ in range(10):
        status, p, rh = _call_h("GET", monitor_url, follow=False)
        state = (p or {}).get("status", "") if isinstance(p, dict) else ""
        if status == 303 or state == "completed":
            return "done"
        if state == "failed":
            return "failed"
        time.sleep(1)
    return "pending"


def _application_items(cfg, drive, last, first):
    """Files in the applications folder named <Last>_<First>_... -> list of (item, modified datetime), newest first."""
    from datetime import datetime
    src = _clean_path(_get(cfg, "sharepoint_applications_folder") or "")
    want_last, want_first = _norm(last), _norm(first)
    if not src or not want_last:
        return []
    path = f"/drives/{drive}/root:/{_enc(src)}:/children?$select=id,name,file,lastModifiedDateTime&$top=200"
    found = []
    while path:
        status, p = _graph("GET", path)
        if status == 404:
            raise SharePointError(f"The applications folder '{'/'.join(src)}' was not found in the library.")
        if status != 200 or not p:
            raise SharePointError(f"Could not read the applications folder ({status}). {_err(p)}")
        for it in p.get("value", []):
            if "file" not in it:
                continue
            tokens = it["name"].rsplit(".", 1)[0].split("_")
            if len(tokens) < 2 or _norm(tokens[0]) != want_last or (want_first and _norm(tokens[1]) != want_first):
                continue
            try:
                modified = datetime.fromisoformat(it["lastModifiedDateTime"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            found.append((it, modified))
        nxt = (p.get("@odata.nextLink") or "")
        path = nxt.replace(GRAPH_URL, "", 1) if nxt.startswith(GRAPH_URL) else None
    return sorted(found, key=lambda x: x[1], reverse=True)


def find_applications(cfg, last, first, limit=25):
    """Application files for this name, any age, newest first: [{id, name, modified}]."""
    if not _get(cfg, "sharepoint_applications_folder"):
        raise SharePointError("sharepoint_applications_folder is not set in config.yaml.")
    drive = _drive_id(cfg)
    return [{"id": it["id"], "name": it["name"], "modified": m.date().isoformat()}
            for it, m in _application_items(cfg, drive, last, first)[:limit]]


MAX_PDF_BYTES = 10 * 1024 * 1024


def get_application(cfg, item_id):
    """Bytes of one file from the applications folder (refuses anything outside that folder)."""
    drive = _drive_id(cfg)
    src = "/".join(_clean_path(_get(cfg, "sharepoint_applications_folder") or ""))
    item = f"/drives/{drive}/items/{urllib.parse.quote(item_id, safe='')}"
    status, p = _graph("GET", item)
    if status != 200 or not p or "file" not in p:
        raise SharePointError(f"The application file could not be found ({status}). {_err(p)}")
    parent = urllib.parse.unquote((p.get("parentReference") or {}).get("path", ""))
    if not src or parent.split("root:", 1)[-1].strip("/").lower() != src.lower():
        raise SharePointError("That file is not in the applications folder.")
    if int(p.get("size", 0)) > MAX_PDF_BYTES:
        raise SharePointError("The application file is too large to read.")
    url = p.get("@microsoft.graph.downloadUrl")
    if not url:  # ask for the file itself: Graph answers with a redirect to a ready-to-use download address
        st, _, rh = _call_h("GET", GRAPH_URL + item + "/content", headers={"Authorization": f"Bearer {_token()}"},
                            follow=False)
        url = rh.get("Location") if rh and st in (301, 302, 303, 307, 308) else None
        if not url:
            raise SharePointError(f"SharePoint did not give a download link for that file ({st}).")
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=TIMEOUT) as r:
            return p["name"], r.read(MAX_PDF_BYTES + 1)[:MAX_PDF_BYTES]
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SharePointError(f"Could not download the application file ({getattr(e, 'reason', e)}).")


def copy_applications(cfg, rel, last, first, days):
    """Copy files named <Last>_<First>_... that were modified in the last `days` days from the applications
    folder (sharepoint_applications_folder) into <sharepoint_folder>/<rel>. Returns (copied names, notes).
    A file with the same name already in the member's folder is replaced. Subfolders are ignored."""
    from datetime import datetime, timedelta, timezone
    if not _clean_path(_get(cfg, "sharepoint_applications_folder") or ""):
        return [], []
    drive = _drive_id(cfg)
    dest = _clean_path(_get(cfg, "sharepoint_folder") or "") + _clean_path(rel)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    matches = [it for it, m in _application_items(cfg, drive, last, first) if m >= cutoff]
    if not matches:
        return [], []
    target = _folder_id(drive, dest)
    copied, notes = [], []
    for it in matches:
        status, p, rh = _call_h("POST", GRAPH_URL + f"/drives/{drive}/items/{it['id']}/copy"
                                "?@microsoft.graph.conflictBehavior=replace",
                                data=json.dumps({"parentReference": {"driveId": drive, "id": target}}).encode(),
                                headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"})
        if status not in (200, 202):
            raise SharePointError(f"Could not copy '{it['name']}' ({status}). {_err(p)}")
        monitor = rh.get("Location") if rh else None
        outcome = _wait_for_copy(monitor) if monitor else "done"
        if outcome == "failed":
            raise SharePointError(f"SharePoint could not copy '{it['name']}'.")
        copied.append(it["name"])
        if outcome == "pending":
            notes.append(it["name"])
    return copied, notes
