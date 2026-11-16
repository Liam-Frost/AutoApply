"""Who may use this server, and where it listens.

The program holds its user's private data - their profile, their documents, the sign-ins to employers' sites - and is
used through a web page. So the page asks for a login, on this computer as well as from anywhere else: one account,
the administrator's, set by the user the first time the page is opened on the computer itself. There is no initial
password to show or to find: nothing is generated, written to a screen or to a log.

    data/access.json    where the server listens (host, port, URL prefix, the reverse proxy in front of it), the
                        administrator (a salted scrypt hash, never the password) and the open sessions (hashes of
                        their cookies). A file, not a setting in the database: the server reads it before it can
                        serve the page that edits it, and a wrong value must be repairable with a text editor.
    data/local.token    what this computer's own programs (the tray icon, the command line) show instead of a login.
                        Whoever can read it can read the database beside it.

Forgotten password: ``autoapply reset-admin`` (or the tray menu) removes the administrator and every session; the next
visit from this computer sets a new one. Being able to run that already means being able to read everything.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets as _secrets
import threading
import time
from pathlib import Path
from typing import Any

from . import config

COOKIE = "aa_session"
LOCAL_HEADER = "x-autoapply-local"
DEFAULTS: dict[str, Any] = {
    "host": "127.0.0.1",        # 127.0.0.1: this computer only | an address of this computer | 0.0.0.0: every network it is on
    "port": 8000,
    "root_path": "",            # "/autoapply" when a reverse proxy serves the program under that path
    "https_by_proxy": False,    # a reverse proxy in front of the server speaks HTTPS to the browser
    "trusted_proxies": [],      # addresses of that proxy (it is believed about who is calling and whether it was HTTPS)
    "allowed_hosts": [],        # further names the server may be called by (its DNS name behind the proxy)
    "session_days": 30,
}
MAX_FAILS, LOCK_SECONDS = 5, 15 * 60
_lock = threading.RLock()
_fails: list[float] = []


def _path() -> Path:
    return config.DATA / "access.json"


def _read() -> dict[str, Any]:
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(d: dict[str, Any]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


# --- where the server listens ---------------------------------------------------------------------------------------------

def conf() -> dict[str, Any]:
    return {**DEFAULTS, **{k: v for k, v in (_read().get("server") or {}).items() if k in DEFAULTS}}


def clean(patch: dict[str, Any]) -> dict[str, Any]:
    """Check what the settings page (or a person with a text editor) asks for. Raises ValueError with the reason."""
    out: dict[str, Any] = {}
    for k, v in patch.items():
        if k not in DEFAULTS:
            raise ValueError(f"unknown setting {k}")
        if k == "host":
            v = str(v).strip() or "127.0.0.1"
            if v != "localhost":
                try:
                    ipaddress.ip_address(v)
                except ValueError:
                    raise ValueError("监听地址要填 IP 地址：127.0.0.1（只有这台电脑）、这台电脑的某个地址，或 0.0.0.0（所有网络）") from None
        elif k == "port":
            v = int(v)
            if not 1 <= v <= 65535:
                raise ValueError("端口要在 1 到 65535 之间")
        elif k == "root_path":
            v = "/" + str(v).strip().strip("/") if str(v).strip().strip("/") else ""
            if any(c in v for c in " ?#\\\"'<>") or "//" in v or ".." in v:
                raise ValueError("路径前缀只能是像 /autoapply 这样的路径")
        elif k in ("trusted_proxies", "allowed_hosts"):
            v = [str(x).strip().lower() for x in (v or []) if str(x).strip()]
            if k == "trusted_proxies":
                for x in v:
                    try:
                        ipaddress.ip_address(x)
                    except ValueError:
                        raise ValueError(f"反向代理的地址要填 IP 地址：{x}") from None
            elif any(not all(c.isalnum() or c in "-." for c in x) for x in v):
                raise ValueError("访问用的域名只填主机名，例如 jobs.example.com")
        elif k == "https_by_proxy":
            v = bool(v)
        elif k == "session_days":
            v = int(v)
            if not 1 <= v <= 365:
                raise ValueError("登录保持天数要在 1 到 365 之间")
        out[k] = v
    return out


def save_conf(patch: dict[str, Any]) -> dict[str, Any]:
    new = clean(patch)
    with _lock:
        d = _read()
        d["server"] = {**(d.get("server") or {}), **new}
        _write(d)
    return conf()


def exposed(c: dict[str, Any] | None = None) -> bool:
    """Does the server listen for other computers?"""
    h = (c or conf())["host"]
    return h not in ("127.0.0.1", "localhost", "::1")


# --- the administrator -------------------------------------------------------------------------------------------------------

def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32).hex()


def admin_name() -> str:
    return str((_read().get("admin") or {}).get("user") or "")


def has_admin() -> bool:
    return bool((_read().get("admin") or {}).get("hash"))


def password_problem(password: str) -> str:
    if len(password) < 8:
        return "密码至少 8 个字符"
    if len(password) > 200:
        return "密码太长了"
    return ""


def set_admin(user: str, password: str) -> None:
    user = user.strip()
    if not user or len(user) > 60:
        raise ValueError("请填用户名")
    why = password_problem(password)
    if why:
        raise ValueError(why)
    salt = os.urandom(16)
    with _lock:
        d = _read()
        d["admin"] = {"user": user, "salt": salt.hex(), "hash": _hash(password, salt), "set_at": int(time.time())}
        d["sessions"] = {}      # a new password ends every login made with the old one
        _write(d)


def verify(user: str, password: str) -> bool:
    a = _read().get("admin") or {}
    if not a.get("hash"):
        return False
    try:
        good = hmac.compare_digest(_hash(password, bytes.fromhex(a["salt"])), a["hash"])
    except (ValueError, KeyError):
        return False
    return good and hmac.compare_digest(user.strip().lower().encode(), str(a.get("user", "")).lower().encode())


def reset_admin() -> None:
    with _lock:
        d = _read()
        d.pop("admin", None)
        d["sessions"] = {}
        _write(d)


# --- logins ----------------------------------------------------------------------------------------------------------------

def locked_for() -> int:
    """Seconds until another password may be tried (0: now). Five wrong ones in a row close the door for a quarter of an hour."""
    now = time.time()
    with _lock:
        _fails[:] = [t for t in _fails if now - t < LOCK_SECONDS]
        return int(LOCK_SECONDS - (now - _fails[0])) + 1 if len(_fails) >= MAX_FAILS else 0


def note_login(ok: bool) -> None:
    with _lock:
        if ok:
            _fails.clear()
        else:
            _fails.append(time.time())


def _key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session() -> str:
    token = _secrets.token_urlsafe(32)
    now = int(time.time())
    with _lock:
        d = _read()
        live = {k: v for k, v in (d.get("sessions") or {}).items() if v > now}
        live[_key(token)] = now + int(conf()["session_days"]) * 86400
        d["sessions"] = dict(sorted(live.items(), key=lambda kv: kv[1])[-20:])      # twenty devices are plenty for one person
        _write(d)
    return token


def session_ok(token: str | None) -> bool:
    if not token:
        return False
    return int((_read().get("sessions") or {}).get(_key(token), 0)) > time.time()


def end_session(token: str | None) -> None:
    if not token:
        return
    with _lock:
        d = _read()
        if (d.get("sessions") or {}).pop(_key(token), None) is not None:
            _write(d)


def end_all_sessions() -> None:
    with _lock:
        d = _read()
        d["sessions"] = {}
        _write(d)


# --- this computer's own programs ------------------------------------------------------------------------------------------

def local_token() -> str:
    p = config.DATA / "local.token"
    try:
        t = p.read_text(encoding="utf-8").strip()
        if len(t) >= 32:
            return t
    except OSError:
        pass
    t = _secrets.token_urlsafe(32)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(t, encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return t


# --- a request ---------------------------------------------------------------------------------------------------------------

def _loopback(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return ip in ("localhost", "testclient")


def caller(peer: str, headers: Any) -> dict[str, Any]:
    """Who is calling: the address, whether it reached the browser over HTTPS, and whether it is this computer itself.

    Behind a reverse proxy the connection always comes from the proxy; the proxy says who it is forwarding for. It is
    believed only when it is one of the proxies named in the settings (or, with "a proxy does the HTTPS", one on this
    computer). A request that carries a forwarding header is never "this computer itself", whoever sent it."""
    c = conf()
    fwd = headers.get("x-forwarded-for") or headers.get("forwarded") or ""
    trusted = peer.lower() in c["trusted_proxies"] or (c["https_by_proxy"] and _loopback(peer))
    ip, https = peer, False
    if trusted and fwd:
        ip = (headers.get("x-forwarded-for") or "").split(",")[-1].strip() or peer
        https = (headers.get("x-forwarded-proto") or "").split(",")[-1].strip().lower() == "https"
    return {"ip": ip, "https": https, "local": _loopback(peer) and not fwd}


def enforced() -> bool:
    """Is the login in force? Always - the tests and the demo copy turn it off by replacing this."""
    return True


def allowed(path: str, cookie: str | None, who: dict[str, Any], local_header: str | None) -> bool:
    """May this request use the API? The page and its files are always served: the login page has to load."""
    if not enforced():
        return True
    if not (path.startswith("/api/") or path.startswith("/mcp/")):
        return True
    if path.startswith("/api/auth/") or path.startswith("/mcp/run/"):      # the login itself; an agent run's one-off token
        return True
    if who["local"] and local_header and hmac.compare_digest(local_header, local_token()):
        return True
    return session_ok(cookie)
