"""Settings file (config.yaml) for branding and membership groups.

The file lives next to the database (or at $CFD_CONFIG), is created from config.default.yaml on first
use, and is re-read whenever it changes. Bad values fall back to the built-in defaults.
"""
import logging
import os
import re
import shutil
from pathlib import Path

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
    "groups": [
        "01-Active Members", "02-Junior Members", "03-In-Active Life Members", "05-Fire Chiefs",
        "06-Commissioners", "07-Auxiliary Members", "08-Honorary Members", "09-Line of Duty Family",
        "10-Hall Coordinator",
    ],
}

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
    if "groups" in raw:
        g = raw["groups"]
        if isinstance(g, str):  # allow a comma-separated line too
            g = [p.strip() for p in g.split(",")]
        if isinstance(g, list) and g and all(isinstance(x, (str, int)) and str(x).strip() for x in g):
            seen, groups = set(), []
            for x in g:
                x = str(x).strip()
                if x.lower() not in seen:
                    seen.add(x.lower())
                    groups.append(x)
            cfg["groups"] = groups
        else:
            problems.append("groups: expected a list of group names")

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
