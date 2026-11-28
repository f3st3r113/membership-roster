"""Read a New Member Application PDF (typed text, one 'Label: value' per line) into member form fields."""
import io
import re

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
ABBREVIATIONS = set(STATES.values())
STREET_TYPES = {
    "st", "street", "rd", "road", "ave", "avenue", "av", "dr", "drive", "ln", "lane", "ct", "court", "cir",
    "circle", "blvd", "boulevard", "way", "pl", "place", "ter", "terrace", "trl", "trail", "pkwy", "parkway",
    "hwy", "highway", "loop", "alley", "aly", "xing", "crossing", "pike", "turnpike",
}
ROUTE_WORDS = {"route", "rt", "rte", "hwy", "highway", "sr", "cr"}
DIRECTIONS = {"n", "s", "e", "w", "ne", "nw", "se", "sw", "north", "south", "east", "west"}
UNIT_WORDS = {"apt", "apartment", "unit", "suite", "ste", "lot", "fl", "floor", "bldg", "building", "rm", "room"}
HEADINGS = {"personal information", "employment information", "violations", "previous experience",
            "membership category"}


KEEP_UPPER = {"PO", "NE", "NW", "SE", "SW", "II", "III", "IV", "RR"}


def _title_word(w):
    if not w:
        return w
    if w.upper() in KEEP_UPPER:
        return w.upper()
    if re.fullmatch(r"\d+(st|nd|rd|th)", w, re.I):
        return w.lower()
    letters = [ch for ch in w if ch.isalpha()]
    if letters and not (all(ch.isupper() for ch in letters) or all(ch.islower() for ch in letters)):
        return w  # already mixed case (McDonald, DeWitt): leave it alone
    return w[:1].upper() + w[1:].lower() if w[:1].isalpha() else w[:1] + _title_word(w[1:])


def smart_title(text):
    """'evan' / 'EVAN' -> 'Evan'; '7960 JOSS FARM WAY' -> '7960 Joss Farm Way'; keeps McDonald, PO, NE, 2nd."""
    def word(token):
        def one(m):
            head, _, tail = m.group(0).partition("'")
            if not tail:
                return _title_word(head)
            # O'Brien, D'Angelo: capitalise after a one-letter prefix; otherwise it is a contraction (Smith's)
            return _title_word(head) + "'" + (_title_word(tail) if len(head) == 1 else tail.lower())
        return re.sub(r"[^\W_]+(?:'[^\W_]+)?", one, token)
    return " ".join(word(t) for t in str(text).split())


def state_code(text):
    """'New York' / 'N.Y.' / 'ny' -> 'NY'; anything else is returned unchanged."""
    s = re.sub(r"[.\s]+", " ", str(text)).strip()
    if s.lower() in STATES:
        return STATES[s.lower()]
    if re.fullmatch(r"[A-Za-z] ?[A-Za-z]", s) and s.replace(" ", "").upper() in ABBREVIATIONS:
        return s.replace(" ", "").upper()
    return str(text).strip()


def pdf_text(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def _lines(text):
    return [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines() if ln.strip()]


def _value(lines, label, multi=False):
    """Text after 'Label:' on its line. With multi, following lines that are not another 'Label:' or a heading are joined."""
    pat = re.compile(rf"^{re.escape(label)}\s*:\s*(.*)$", re.I)
    for i, ln in enumerate(lines):
        m = pat.match(ln)
        if not m:
            continue
        val = m.group(1).strip()
        if multi:
            for nxt in lines[i + 1:]:
                if re.match(r"^[A-Za-z][A-Za-z .'/#()-]{0,40}:", nxt) or nxt.lower() in HEADINGS:
                    break
                val += " " + nxt
        return val.strip()
    return ""


def _tok(t):
    return t.strip(".,").lower()


def split_address(text):
    """'7960 Joss Farm Way Cicero New York , 13039' -> (street, city, state, zip, problem or None)."""
    s = re.sub(r"\s+", " ", text).strip().strip(",")
    if not s:
        return "", "", "", "", None
    zip_code = ""
    m = re.search(r"[\s,]+(\d{5})(?:-\d{4})?$", s)
    if m:
        zip_code, s = m.group(1), s[:m.start()].rstrip(" ,")
    state = ""
    low = s.lower()
    for name in sorted(STATES, key=len, reverse=True):
        if low == name or low.endswith((" " + name, "," + name)):
            state, s = STATES[name], s[:len(s) - len(name)].rstrip(" ,")
            break
    else:
        m = re.search(r"[\s,]+([A-Za-z]{2})$", s)
        if m and m.group(1).upper() in ABBREVIATIONS:
            state, s = m.group(1).upper(), s[:m.start()].rstrip(" ,")
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) >= 2:  # '123 Main St, Cicero'
        return ", ".join(parts[:-1]), parts[-1], state, zip_code, None
    tokens = s.split()
    cut = None
    for i, t in enumerate(tokens):
        if i == 0:
            continue
        if _tok(t) in STREET_TYPES:
            cut = i + 1
        elif _tok(t) in ROUTE_WORDS and i + 1 < len(tokens):
            cut = i + 2
    if cut is not None:
        while cut < len(tokens) - 1 and _tok(tokens[cut]) in DIRECTIONS:
            cut += 1
        if cut < len(tokens) - 1 and (_tok(tokens[cut]) in UNIT_WORDS):
            cut += 2
        elif cut < len(tokens) and tokens[cut].startswith("#"):
            cut += 1
        return " ".join(tokens[:cut]), " ".join(tokens[cut:]), state, zip_code, None
    return s, "", state, zip_code, "Could not tell where the street ends and the city starts; check Street and City."


def _class(text, allowed):
    t = text.lower()
    for key, name in (("fire police", "Fire Police"), ("associate", "Associate"), ("junior", "Junior"),
                      ("exterior", "Exterior"), ("interior", "Interior"), ("driver", "Driver"),
                      ("ems", "EMS")):
        if key in t:
            return name if name in allowed else ""
    return ""


def _response(text, allowed):
    t = text.lower()
    name = "Duty Hours" if "duty" in t else ("Normal" if "home" in t else "")
    return name if name in allowed else ""


def parse(data, typed_last="", typed_first="", classes=(), responses=()):
    """-> (fields dict, list of notes for the user). Only fields that were found are returned."""
    lines = _lines(pdf_text(data))
    notes, out = [], {}
    name = _value(lines, "Name", multi=False)
    tokens = [t for t in name.replace(",", " ").split() if t]
    suffixes = {"jr", "sr", "ii", "iii", "iv"}
    core = [t for t in tokens if _tok(t) not in suffixes]
    if typed_last:
        out["last_name"] = typed_last
    if typed_first:
        out["first_name"] = typed_first
    if tokens and not (typed_last and typed_first) and core:
        out.setdefault("first_name", core[0])
        out.setdefault("last_name", " ".join(tokens[len(core) - 1:]) if len(core) > 1 else core[0])
    street, city, state, zip_code, problem = split_address(_value(lines, "Address", multi=True))
    for key, val in (("address", street), ("city", city), ("state", state), ("zip", zip_code)):
        if val:
            out[key] = val
    if problem:
        notes.append(problem)
    phone = _value(lines, "Phone Number") or _value(lines, "Phone")
    if phone:
        out["mobile_phone"] = phone
    email = _value(lines, "Email Address") or _value(lines, "Email")
    if email and "@" in email:
        out["email"] = email.replace(" ", "")
    cat = _value(lines, "Category selection") or _value(lines, "Category")
    if cat:
        cls = _class(cat, classes)
        if cls:
            out["membership_class"] = cls
        else:
            notes.append(f"Membership category '{cat}' does not match a Membership Class.")
    resp = _value(lines, "Response Type")
    if resp:
        r = _response(resp, responses)
        if r:
            out["response_type"] = r
        else:
            notes.append(f"Response type '{resp}' does not match a Response Type.")
    for key in ("first_name", "last_name", "address", "city"):
        if key in out:
            out[key] = smart_title(out[key])
    if "state" in out:
        out["state"] = state_code(out["state"])
    return out, notes
