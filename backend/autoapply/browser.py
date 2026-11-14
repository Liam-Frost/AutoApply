"""Browser lifecycle and per-tenant session persistence (Playwright sync API).

Storage states (cookies + localStorage) are saved encrypted per tenant so a
login survives between runs. A headed window is used only for human takeover.
"""

from __future__ import annotations

import re

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import BrowserContext, Page, sync_playwright

from . import config, secrets


def _state_path(tenant_key: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in tenant_key)
    return config.SESSIONS / f"{safe}.bin"


def load_state(tenant_key: str) -> dict | None:
    p = _state_path(tenant_key)
    if not p.exists():
        return None
    try:
        return secrets.decrypt_json(p.read_bytes())  # type: ignore[return-value]
    except Exception:  # noqa: BLE001 - corrupt or key rotated: start clean
        return None


def save_state(tenant_key: str, context: BrowserContext) -> None:
    _state_path(tenant_key).write_bytes(secrets.encrypt_json(context.storage_state()))


def write_state(tenant_key: str, state: dict) -> None:
    _state_path(tenant_key).write_bytes(secrets.encrypt_json(state))


# Sign-in providers that career sites offer as "Sign in with ...". The user signs in to one once (Accounts page);
# the cookies of that provider are then present in every window this program opens, so the button just works.
# Built in: the ones career sites and applicant systems offer most often. Google and Apple are what Workday supports;
# Microsoft / LinkedIn / Google / Facebook is the Eightfold set (Microsoft Careers); Google / Facebook / Indeed appear on
# Oracle Recruiting sites; LinkedIn is near-universal; GitHub on developer-focused boards; SEEK and XING regionally.
IDENTITIES = {
    "google": {"name": "Google", "url": "https://accounts.google.com/", "domains": ("google.com",), "done": lambda u: "myaccount.google.com" in u,
               "note": "Google 有时会拒绝在程序控制的浏览器里登录（提示“此浏览器或应用可能不安全”）。遇到这种情况就是用不了，程序不会去绕过它。"},
    "linkedin": {"name": "LinkedIn", "url": "https://www.linkedin.com/login", "domains": ("linkedin.com",), "done": lambda u: "linkedin.com/feed" in u},
    "microsoft": {"name": "Microsoft", "url": "https://login.live.com/", "domains": ("live.com", "microsoftonline.com", "microsoft.com"),
                  "done": lambda u: "account.microsoft.com" in u or "account.live.com" in u},
    "apple": {"name": "Apple", "url": "https://account.apple.com/sign-in", "domains": ("apple.com", "icloud.com"), "done": lambda u: "account.apple.com/account" in u,
              "note": "Apple 每次在新浏览器里登录都要双重认证，验证码请你自己输入。"},
    "facebook": {"name": "Facebook", "url": "https://www.facebook.com/login", "domains": ("facebook.com",),
                 "done": lambda u: re.match(r"https://www\.facebook\.com/(\?.*)?$", u) is not None},
    "indeed": {"name": "Indeed", "url": "https://secure.indeed.com/auth", "domains": ("indeed.com",),
               "done": lambda u: re.match(r"https://([a-z]+\.)?indeed\.com/", u) is not None and "secure.indeed.com" not in u},
    "github": {"name": "GitHub", "url": "https://github.com/login", "domains": ("github.com",), "done": lambda u: u.rstrip("/") == "https://github.com"},
    "seek": {"name": "SEEK", "url": "https://www.seek.com.au/oauth/login/", "domains": ("seek.com.au", "seek.com"),
             "done": lambda u: "seek.com" in u and "login" not in u and "oauth" not in u, "region": "澳大利亚、新西兰"},
    "xing": {"name": "XING", "url": "https://login.xing.com/", "domains": ("xing.com",), "done": lambda u: "www.xing.com" in u, "region": "德语区"},
}


def identities() -> dict[str, dict]:
    """Built-in providers plus the ones the user added (settings: identity.custom). For a user-added one there is no way to
    tell when sign-in has finished, so closing the window is taken as done."""
    from . import db

    out = dict(IDENTITIES)
    for c in db.get_setting("identity.custom") or []:
        key = re.sub(r"[^a-z0-9]+", "", str(c.get("name", "")).lower())
        doms = tuple(d.strip().lower().lstrip(".") for d in c.get("domains") or [] if d.strip())
        if key and key not in out and c.get("url") and doms:
            out[key] = {"name": str(c["name"]).strip(), "url": str(c["url"]).strip(), "domains": doms, "done": None, "custom": True}
    return out


def with_identities(state: dict | None, tenant_key: str | None) -> dict | None:
    """Add the saved provider sign-ins to a site's own session."""
    from . import db

    if (tenant_key or "").startswith("idp:") or not db.get_setting("identity.share"):
        return state
    extra = []
    for key, spec in identities().items():
        st = load_state(f"idp:{key}")
        for c in (st or {}).get("cookies", []):
            if any(c.get("domain", "").lstrip(".").endswith(d) for d in spec["domains"]):
                extra.append(c)
    if not extra:
        return state
    state = dict(state or {"cookies": [], "origins": []})
    have = {(c["name"], c.get("domain"), c.get("path")) for c in state.get("cookies", [])}
    state["cookies"] = list(state.get("cookies", [])) + [c for c in extra if (c["name"], c.get("domain"), c.get("path")) not in have]
    return state


def session_info(tenant_key: str) -> dict | None:
    """What is saved for a site: when, how many cookies, and until when the longest-lived one is valid."""
    import time
    from datetime import datetime, timezone

    p = _state_path(tenant_key)
    st = load_state(tenant_key)
    if st is None:
        return None
    cookies = st.get("cookies", [])
    exp = [c["expires"] for c in cookies if c.get("expires", -1) and c.get("expires", -1) > 0]
    alive = [e for e in exp if e > time.time()]
    return {"saved_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(), "cookies": len(cookies),
            "valid_until": datetime.fromtimestamp(max(alive), timezone.utc).isoformat() if alive else None,
            "expired": bool(exp) and not alive, "session_only": sum(1 for c in cookies if not c.get("expires") or c.get("expires", -1) <= 0)}


def clear_state(tenant_key: str) -> None:
    _state_path(tenant_key).unlink(missing_ok=True)


def find_chrome() -> str | None:
    """The user's installed Chrome (or Edge), for sign-ins that reject automated browsers."""
    import os
    import shutil

    roots = [os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    for rel in (r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe"):
        for r in roots:
            if r and (Path(r) / rel).exists():
                return str(Path(r) / rel)
    for name in ("google-chrome", "chrome", "chromium", "msedge"):
        if shutil.which(name):
            return shutil.which(name)
    mac = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return str(mac) if mac.exists() else None


def plain_login(tenant_key: str, url: str, is_logged_in_url, *, timeout_s: int = 900) -> dict:  # noqa: ANN001
    """Human sign-in in an ordinary browser window that this program does not drive.

    Some sites (PD Portal behind Cloudflare) refuse the sign-in page to a browser under
    automation. Nothing is disguised here: the window is the user's own Chrome with a
    separate profile, the user signs in by hand, and only once a tab reaches a signed-in
    URL does the program connect to read the session cookies and save them.
    """
    import json as _json
    import socket
    import subprocess
    import time
    import urllib.request

    exe = find_chrome()
    if not exe:
        return {"ok": False, "reason": "Chrome or Edge is not installed; this site only accepts sign-in from a regular browser"}
    safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in tenant_key)
    profile = config.DATA / "profiles" / safe
    profile.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    from . import net

    proc = subprocess.Popen([exe, f"--user-data-dir={profile}", f"--remote-debugging-port={port}", "--no-first-run", "--no-default-browser-check", *net.chrome_args(), "--new-window", url])
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # local endpoint: never through the system proxy
    ok, t0 = False, time.time()
    try:
        while time.time() - t0 < timeout_s and proc.poll() is None:
            time.sleep(2)
            try:
                tabs = _json.loads(opener.open(f"http://127.0.0.1:{port}/json/list", timeout=3).read())
            except Exception:  # noqa: BLE001 - browser still starting, or closed
                continue
            if any(t.get("type") == "page" and is_logged_in_url(t.get("url", "")) for t in tabs):
                ok = True
                break
        if not ok:
            return {"ok": False, "reason": "timed out or window closed before sign-in was detected"}
        time.sleep(2)  # let the landing page finish setting cookies
        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = b.contexts[0]
            _state_path(tenant_key).write_bytes(secrets.encrypt_json(ctx.storage_state()))
            try:
                b.new_browser_cdp_session().send("Browser.close")
            except Exception:  # noqa: BLE001
                pass
        return {"ok": True}
    finally:
        try:
            proc.wait(timeout=8)
        except Exception:  # noqa: BLE001
            proc.terminate()


@contextmanager
def open_page(tenant_key: str | None = None, *, headless: bool = True, downloads: Path | None = None) -> Iterator[Page]:
    """Yield a page in a fresh context, restoring the tenant's saved session if any."""
    with sync_playwright() as p:
        from . import db, net

        if headless and tenant_key and tenant_key in (db.get_setting("browser.visible_sites") or []):
            headless = False  # this site was seen refusing the hidden window
        browser = p.chromium.launch(headless=headless, **net.browser_options())
        try:
            state = with_identities(load_state(tenant_key) if tenant_key else None, tenant_key)
            ctx = browser.new_context(
                storage_state=state,
                locale="en-US",
                viewport={"width": 1366, "height": 900},
                accept_downloads=bool(downloads),
            )
            ctx.set_default_timeout(15000)
            ctx.set_default_navigation_timeout(75000)  # large career sites take 30-45 s to load over a slow link; 15 s gave up on them
            page = ctx.new_page()
            try:
                yield page
            finally:
                try:
                    ctx.close()
                except Exception:  # noqa: BLE001 - the user closed the window themselves
                    pass
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass


def snapshot(page: Page, run_dir: Path, name: str) -> dict[str, str]:
    """Save a screenshot and the DOM (the DOM doubles as a driver regression fixture)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    shot, dom = run_dir / f"{name}.png", run_dir / f"{name}.html"
    try:
        page.screenshot(path=str(shot), full_page=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        html = page.content()
        # never persist typed secrets
        html = __import__("re").sub(r'(<input[^>]*type="password"[^>]*value=")[^"]*', r"\1", html)
        dom.write_text(html, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return {"screenshot": str(shot), "dom": str(dom)}
