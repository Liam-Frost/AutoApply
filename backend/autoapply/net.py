"""How this program reaches the internet: through the system's proxy, a proxy of its own, or directly.

One setting (``proxy.mode``) is applied to everything that makes connections:
* Python HTTP clients (httpx, requests, the Google and Anthropic libraries) and the bundled Claude
  CLI read the standard environment variables, which ``apply()`` sets;
* the program's browser and the plain sign-in window get it as launch options.
Connections to this computer itself never go through a proxy.
"""

from __future__ import annotations

from .say import say as T

import os
import time
from typing import Any
from urllib.parse import quote, unquote, urlparse

from . import db, secrets

LOCAL = "localhost,127.0.0.1,::1"
_VARS = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy", "NO_PROXY", "no_proxy")
_ORIGINAL = {k: os.environ[k] for k in _VARS if k in os.environ}  # what the process started with ("system" mode restores it)
PROXY_PASSWORD = "proxy_password"


def mode() -> str:
    m = db.get_setting("proxy.mode") or "system"
    return m if m in ("system", "none", "custom") else "system"


def _system_url() -> str:
    """The proxy the operating system is set to use (what the user's own browser uses), or ''."""
    for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        if _ORIGINAL.get(k):
            return _ORIGINAL[k]
    import urllib.request

    reg = getattr(urllib.request, "getproxies_registry", None)
    try:
        px = reg() if reg else urllib.request.getproxies()
    except Exception:  # noqa: BLE001
        px = {}
    url = px.get("https") or px.get("http") or ""
    if url.startswith("https://"):
        url = "http://" + url[len("https://"):]  # the registry entry names a plain HTTP proxy
    return url


def custom_url(*, with_auth: bool = True) -> str:
    url = (db.get_setting("proxy.url") or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    user = (db.get_setting("proxy.username") or "").strip()
    if with_auth and user:
        u = urlparse(url)
        pw = secrets.get(PROXY_PASSWORD) or ""
        url = f"{u.scheme}://{quote(user, safe='')}:{quote(pw, safe='')}@{u.hostname}" + (f":{u.port}" if u.port else "")
    return url


def proxy_url() -> str:
    """The proxy in effect right now ('' = direct)."""
    m = mode()
    return "" if m == "none" else custom_url() if m == "custom" else _system_url()


def httplib2_proxy(method: str = "https") -> Any:
    """The proxy for httplib2 - what the Gmail API is read with - looked up for each connection it opens (it is given
    as ``proxy_info``). httplib2 by itself takes a proxy only from HTTPS_PROXY / HTTP_PROXY, never from the system's proxy
    setting that the other libraries read - and uses one only with PySocks installed: without it, it drops the proxy
    without a word. Gmail had always been read straight from Google while everything else went through the proxy; where
    Google is reached only through one, no mail was read for a day (2026-11-25)."""
    url = proxy_url()
    if not url:
        return None
    import httplib2

    pi = httplib2.proxy_info_from_url(url, method, noproxy=bypass())
    # (httplib2 hands on the name and password as they are written in the address - percent-encoded there, custom_url:
    # "p@ss" would reach the proxy as "p%40ss")
    pi.proxy_user = unquote(pi.proxy_user) if pi.proxy_user else pi.proxy_user
    pi.proxy_pass = unquote(pi.proxy_pass) if pi.proxy_pass else pi.proxy_pass
    return pi


def bypassed(host: str) -> bool:
    """Does the setting say to reach this host directly - this computer, and the addresses the applicant listed
    (``proxy.bypass``: "example.com" and ".example.com" both mean the site and its subdomains, "*" everything)?"""
    host = (host or "").lower().rstrip(".")
    for entry in bypass().split(","):
        e = entry.strip().lower()
        if e == "*":
            return True
        e = e.lstrip("*").lstrip(".")
        if e and (host == e or host.endswith("." + e)):
            return True
    return False


def requests_session(url: str = "") -> Any:
    """A `requests` session for ``url`` that goes the way the setting says, not the way this process's environment
    happens to say: with a NO_PROXY and no HTTPS_PROXY in it, requests does not look at the system's proxy at all.
    (Not trusting the environment also leaves out its bypass list: the setting's own is applied here.)"""
    import requests

    s = requests.Session()
    s.trust_env = False
    proxy = proxy_url()
    if proxy and not (url and bypassed(urlparse(url).hostname or "")):
        s.proxies = {"http": proxy, "https": proxy}
    return s


def bypass() -> str:
    extra = ",".join(x.strip() for x in (db.get_setting("proxy.bypass") or "").replace("，", ",").split(",") if x.strip())
    return LOCAL + ("," + extra if extra else "")


def env() -> dict[str, str]:
    """Environment for child processes (the Claude CLI) and for this process's HTTP libraries."""
    m, url = mode(), proxy_url()
    if m == "none" or not url:
        return {"NO_PROXY": "*", "no_proxy": "*"} if m == "none" else {}
    return {"HTTPS_PROXY": url, "HTTP_PROXY": url, "ALL_PROXY": url, "https_proxy": url, "http_proxy": url, "all_proxy": url, "NO_PROXY": bypass(), "no_proxy": bypass()}


def apply() -> None:
    """Make the setting take effect for this process. Called at start-up and after the setting changes."""
    for k in _VARS:
        os.environ.pop(k, None)
    if mode() == "system":
        os.environ.update(_ORIGINAL)
        return
    os.environ.update(env())


def browser_options() -> dict[str, Any]:
    """Keyword arguments for Playwright's ``chromium.launch``."""
    m = mode()
    if m == "none":
        return {"args": ["--no-proxy-server"]}
    if m == "custom" and (url := custom_url(with_auth=False)):
        px: dict[str, Any] = {"server": url, "bypass": bypass()}
        if user := (db.get_setting("proxy.username") or "").strip():
            px["username"], px["password"] = user, secrets.get(PROXY_PASSWORD) or ""
        return {"proxy": px}
    return {}


def chrome_args() -> list[str]:
    """Command-line switches for the plain (not automated) sign-in window."""
    m = mode()
    if m == "none":
        return ["--no-proxy-server"]
    if m == "custom" and (url := custom_url(with_auth=False)):
        return [f"--proxy-server={url}", f"--proxy-bypass-list={bypass().replace(',', ';')}"]
    return []


def describe() -> dict[str, Any]:
    url = proxy_url()
    shown = url
    if "@" in url:  # never show the password
        u = urlparse(url)
        shown = f"{u.scheme}://{u.username}:***@{u.hostname}" + (f":{u.port}" if u.port else "")
    return {"mode": mode(), "in_effect": shown, "system": _system_url()}


TEST_SITES = [(T("server.net.claudeAiModel"), "https://api.anthropic.com/"), (T("server.net.telegramNotifications"), "https://api.telegram.org/"), ("Gmail", "https://gmail.googleapis.com/"),
              (T("server.net.amazonJobs"), "https://www.amazon.jobs/"), (T("server.net.microsoftCareers"), "https://apply.careers.microsoft.com/careers"), ("Greenhouse", "https://boards-api.greenhouse.io/")]


def test() -> list[dict[str, Any]]:
    """Reach a few sites the program depends on with the current setting. Only a plain GET of each front page."""
    import httpx

    url = proxy_url()
    out = []
    kw: dict[str, Any] = {"timeout": 20, "follow_redirects": True, "trust_env": False}
    if url:
        kw["proxy"] = url
    with httpx.Client(**kw) as c:
        for name, site in TEST_SITES:
            t = time.time()
            try:
                r = c.get(site)
                out.append({"name": name, "ok": r.status_code < 500, "ms": int((time.time() - t) * 1000), "detail": f"HTTP {r.status_code}"})
            except Exception as e:  # noqa: BLE001
                out.append({"name": name, "ok": False, "ms": int((time.time() - t) * 1000), "detail": type(e).__name__})
    return out
