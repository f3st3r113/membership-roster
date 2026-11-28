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


def _call(method, url, *, data=None, headers=None, form=None):
    """One HTTP request. Returns (status, parsed JSON or None). Never raises for HTTP status codes."""
    hdrs = dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            status, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SharePointError(f"Could not reach Microsoft 365 ({getattr(e, 'reason', e)}). "
                              "The server needs outbound HTTPS to login.microsoftonline.com and graph.microsoft.com.")
    try:
        return status, json.loads(body) if body else None
    except ValueError:
        return status, None


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
