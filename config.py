"""Settings file (config.yaml) for branding and membership groups.

The file lives next to the database (or at $CFD_CONFIG), is created from config.default.yaml on first
use, and is re-read whenever it changes. Bad values fall back to the built-in defaults.
"""
import logging
import os
import re
import shutil
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

log = logging.getLogger("cfd.config")
BASE_DIR = Path(__file__).resolve().parent
TEMPLATE = BASE_DIR / "config.default.yaml"
BUILTIN_LOGO = BASE_DIR / "static" / "logo.png"
LOGO_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
              ".svg": "image/svg+xml", ".webp": "image/webp"}
MAX_LOGO_BYTES = 2 * 1024 * 1024

DEFAULTS = {
    "department_name": "Cicero Fire Department",
    "formal_name": None,  # falls back to department_name
    "logo_file": "logo.png",
    "theme_color": "#1d9a45",
    "roster_banner_color": "#cbd4e4",
    "timezone": "UTC",
    "response_types": ["Normal", "Duty Hours"],
    "membership_classes": ["Interior", "Exterior", "Junior", "EMS", "Driver", "Fire Police", "Associate"],
    "storage": "auto",
    "sharepoint_site_url": None,
    "sharepoint_library": "Documents",
    "sharepoint_folder": None,
    "interviewers": ["Scarano", "Mayers", "Hoffman", "Carlin", "Germain", "Benjamin"],
    "groups": [
        "01-Active Members", "02-Junior Members", "03-In-Active Life Members", "05-Fire Chiefs",
        "06-Commissioners", "07-Auxiliary Members", "08-Honorary Members", "09-Line of Duty Family",
        "10-Hall Coordinator",
    ],
}

STORAGE_MODES = ("auto", "local", "sharepoint", "both")

_cache = {"key": None, "cfg": None}


def _hex(value):
    """'#1d9a45' / '1D9A45' / '#1a4' -> '#1d9a45', or None if it isn't a color."""
    s = str(value).strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{3}", s):
        s = "".join(ch * 2 for ch in s)
    return "#" + s.lower() if re.fullmatch(r"[0-9a-fA-F]{6}", s) else None


def _mix(color, other, amount):
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def _text(raw, key, problems, max_len=200):
    v = raw.get(key)
    if v is None:
        return None
    if isinstance(v, (str, int, float)) and str(v).strip() and len(str(v).strip()) <= max_len:
        return str(v).strip()
    problems.append(f"{key}: expected a short piece of text")
    return None


def _names(value, allow_empty=False):
    """A YAML list (or one comma-separated line) of names -> cleaned unique list, or None if invalid."""
    if isinstance(value, str):
        value = [p.strip() for p in value.split(",")]
    if not isinstance(value, list) or (not value and not allow_empty):
        return None
    if not all(isinstance(x, (str, int)) and str(x).strip() for x in value):
        return None
    seen, out = set(), []
    for x in value:
        x = str(x).strip()
        if x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out


def _parse(path):
    problems, raw = [], {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if loaded is None:
            loaded = {}
        if isinstance(loaded, dict):
            raw = {str(k).strip().lower(): v for k, v in loaded.items()}
        else:
            problems.append("the file must contain 'key: value' settings")
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as exc:
        problems.append(f"could not read the file ({exc.__class__.__name__}): {exc}")

    cfg = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    name = _text(raw, "department_name", problems)
    if name:
        cfg["department_name"] = name
    cfg["formal_name"] = _text(raw, "formal_name", problems) or cfg["department_name"]
    logo = _text(raw, "logo_file", problems, 300)
    if logo:
        cfg["logo_file"] = logo
    for key in ("theme_color", "roster_banner_color"):
        if key in raw:
            color = _hex(raw[key])
            if color:
                cfg[key] = color
            else:
                problems.append(f"{key}: '{raw[key]}' is not a hex color like #1d9a45")
    if "storage" in raw:
        mode = str(raw["storage"]).strip().lower()
        if mode in STORAGE_MODES:
            cfg["storage"] = mode
        else:
            problems.append(f"storage: '{raw['storage']}' must be one of {', '.join(STORAGE_MODES)}")
    for key in ("sharepoint_site_url", "sharepoint_library", "sharepoint_folder"):
        v = _text(raw, key, problems, 300)
        if v:
            cfg[key] = v
    if cfg["sharepoint_site_url"] and not re.match(r"https://[^/]+/.+", cfg["sharepoint_site_url"]):
        problems.append("sharepoint_site_url: expected something like https://yourtenant.sharepoint.com/sites/SiteName")
        cfg["sharepoint_site_url"] = None
    for key in ("groups", "response_types", "membership_classes", "interviewers"):
        if key in raw:
            items = _names(raw[key])
            if items is not None:
                cfg[key] = items
            else:
                problems.append(f"{key}: expected a list of names")
    if "timezone" in raw:
        tz = _text(raw, "timezone", problems, 60)
        try:
            ZoneInfo(tz or "UTC")
            cfg["timezone"] = tz or cfg["timezone"]
        except (ZoneInfoNotFoundError, ValueError):
            problems.append(f"timezone: '{raw['timezone']}' is not a known time zone (for example America/New_York)")

    theme = cfg["theme_color"]
    cfg["css_vars"] = {
        "light": {"--green": theme, "--green-dark": _mix(theme, "#000000", 0.30),
                  "--focus": _mix(theme, "#ffffff", 0.55)},
        "dark": {"--green": _mix(theme, "#ffffff", 0.09), "--green-dark": _mix(theme, "#ffffff", 0.35),
                 "--focus": _mix(theme, "#000000", 0.10)},
    }
    cfg["problems"] = problems
    cfg["config_dir"] = path.parent
    return cfg


def get_config(path):
    """Current settings; re-parsed only when the file changes."""
    path = Path(path)
    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(TEMPLATE, path)
        except OSError as exc:
            log.warning("could not create %s: %s", path, exc)
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        key = (str(path), None, None)
    if _cache["key"] != key:
        cfg = _parse(path) if key[1] is not None else _parse_defaults(path)
        for p in cfg["problems"]:
            log.warning("config %s: %s", path, p)
        _cache.update(key=key, cfg=cfg)
    return _cache["cfg"]


def now_local(tz_name):
    """Current date/time in the given time zone (the timezone setting)."""
    from datetime import datetime
    return datetime.now(ZoneInfo(tz_name))


def _parse_defaults(path):
    cfg = _parse(Path(os.devnull))
    cfg["problems"] = []
    cfg["config_dir"] = Path(path).parent
    return cfg


def logo(cfg):
    """(bytes, mimetype) of the configured logo, or of the built-in one if it can't be used."""
    name = Path(cfg["logo_file"])
    for cand in (Path(cfg["config_dir"]) / name, BUILTIN_LOGO):  # an absolute logo_file wins over the folder
        try:
            real = cand.resolve()
            if real.suffix.lower() in LOGO_TYPES and real.is_file() and real.stat().st_size <= MAX_LOGO_BYTES:
                return real.read_bytes(), LOGO_TYPES[real.suffix.lower()]
        except OSError:
            continue
    return BUILTIN_LOGO.read_bytes(), "image/png"
