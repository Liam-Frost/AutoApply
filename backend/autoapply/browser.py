"""Browser lifecycle and per-tenant session persistence (Playwright sync API).

Storage states (cookies + localStorage) are saved encrypted per tenant so a
login survives between runs. A headed window is used only for human takeover.
"""

from __future__ import annotations

import logging
import os
import re
import threading

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from playwright.sync_api import BrowserContext, Page, sync_playwright

from . import config, secrets


def _state_path(tenant_key: str) -> Path:
    from . import db

    # a site whose sign-in is another site's keeps no session of its own: it reads and writes that site's
    tenant_key = str((db.get_setting("accounts.alias") or {}).get(tenant_key) or tenant_key)
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
    write_state(tenant_key, context.storage_state())


_now = threading.local()        # .backend: the browser the page of this thread was opened in (open_page)


def write_state(tenant_key: str, state: dict, *, made_in: str | None = None) -> None:
    """Save a site's sign-in. Where it was made is kept with it: the browser of the page this thread has open, or
    ``made_in`` ("nodriver" for the ordinary browser; "" when that is not known - a sign-in carried over from another
    computer). From then on everything for the site is done in that browser (browser_policy)."""
    import os
    import tempfile

    made = made_in if made_in is not None else getattr(_now, "backend", None)
    if made is not None:
        from . import browser_policy, db

        key, record = browser_policy.canonical(tenant_key), dict(db.get_setting("browser.session_made_in") or {})
        if made_in is None and record.get(key) in browser_policy.BACKENDS and record[key] != made:
            # a run in the other browser (the applicant's choice for one task) does not replace the site's sign-in
            return
        if made in browser_policy.BACKENDS and record.get(key) != made:
            db.set_setting("browser.session_made_in", {**record, key: made})
        elif made not in browser_policy.BACKENDS and key in record:
            record.pop(key)
            db.set_setting("browser.session_made_in", record)

    target = _state_path(tenant_key)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(secrets.encrypt_json(state))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


# Sign-in providers that career sites offer as "Sign in with ...". The user signs in to one once (Accounts page);
# the cookies of that provider are then present in every window this program opens, so the button just works.
# Built in: the ones career sites and applicant systems offer most often. Google and Apple are what Workday supports;
# Microsoft / LinkedIn / Google / Facebook is the Eightfold set (Microsoft Careers); Google / Facebook / Indeed appear on
# Oracle Recruiting sites; LinkedIn is near-universal; GitHub on developer-focused boards; SEEK and XING regionally.
def _at(url: str, domain: str, path: str = "") -> bool:
    """Is the window on that site (and, if given, under that path)? Decided by the address's host, not by finding the
    name somewhere in the address: "https://evil.example/?next=myaccount.google.com" is not Google."""
    from urllib.parse import urlparse

    from .ats.base import host_is

    try:
        u = urlparse(url)
    except ValueError:
        return False
    return u.scheme == "https" and host_is(u.hostname or "", domain) and (not path or u.path.startswith(path))


IDENTITIES = {
    "google": {"name": "Google", "url": "https://accounts.google.com/", "domains": ("google.com",), "done": lambda u: _at(u, "myaccount.google.com"),
               "note": "用 passkey 或两步验证登录都可以，在打开的窗口里照常完成就行；登录不上时，把上面的浏览器换成 nodriver 再试。"},
    "linkedin": {"name": "LinkedIn", "url": "https://www.linkedin.com/login", "domains": ("linkedin.com",), "done": lambda u: _at(u, "linkedin.com", "/feed")},
    "microsoft": {"name": "Microsoft", "url": "https://login.live.com/", "domains": ("live.com", "microsoftonline.com", "microsoft.com"),
                  "done": lambda u: _at(u, "account.microsoft.com") or _at(u, "account.live.com")},
    "apple": {"name": "Apple", "url": "https://account.apple.com/sign-in", "domains": ("apple.com", "icloud.com"), "done": lambda u: _at(u, "account.apple.com", "/account"),
              "note": "Apple 每次在新浏览器里登录都要双重认证，验证码请你自己输入。"},
    "facebook": {"name": "Facebook", "url": "https://www.facebook.com/login", "domains": ("facebook.com",),
                 "done": lambda u: re.match(r"https://www\.facebook\.com/(\?.*)?$", u) is not None},
    "indeed": {"name": "Indeed", "url": "https://secure.indeed.com/auth", "domains": ("indeed.com",),
               "done": lambda u: _at(u, "indeed.com") and not _at(u, "secure.indeed.com")},
    "github": {"name": "GitHub", "url": "https://github.com/login", "domains": ("github.com",), "done": lambda u: u.rstrip("/") == "https://github.com"},
    "seek": {"name": "SEEK", "url": "https://www.seek.com.au/oauth/login/", "domains": ("seek.com.au", "seek.com"),
             "done": lambda u: (_at(u, "seek.com") or _at(u, "seek.com.au")) and "login" not in u and "oauth" not in u, "region": "澳大利亚、新西兰"},
    "xing": {"name": "XING", "url": "https://login.xing.com/", "domains": ("xing.com",), "done": lambda u: _at(u, "www.xing.com"), "region": "德语区"},
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


def with_identities(state: dict | None, tenant_key: str | None, backend: str = "playwright") -> dict | None:
    """Add the saved provider sign-ins to a site's own session - those that live in the browser being opened
    (``backend``). A provider's sign-in is not carried into the other browser: there it is no sign-in, and showing it
    there is what makes the provider sign the real one out."""
    from . import browser_policy, db

    if (tenant_key or "").startswith("idp:") or not db.get_setting("identity.share"):
        return state
    extra = []
    for key, spec in identities().items():
        if browser_policy.session_browser(f"idp:{key}") != backend:
            continue
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
    import shutil
    from .nodriver_backend import profile_lock

    profile = _native_profile(tenant_key)
    with profile_lock(profile):
        _state_path(tenant_key).unlink(missing_ok=True)
        if profile.exists():
            shutil.rmtree(profile)


def _native_profile(tenant_key: str) -> Path:
    import hashlib

    key = _state_path(tenant_key).name
    return config.DATA / "profiles" / "nodriver" / hashlib.sha256(key.encode()).hexdigest()


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


class _Place:
    """Where a browser's window goes, decided once per page (see _window_place)."""

    def __init__(self) -> None:
        self.headless = True
        self.pictures = False                 # the page is shown to a person as pictures (remote.attach)
        self.env: dict[str, str] = {}
        self.args: list[str] = []
        self.title = ""
        self.screen: Any = None               # a virtual screen of its own, stopped when the page closes
        self.window: Any = None

    def __enter__(self) -> "_Place":
        return self

    def __exit__(self, *exc: Any) -> None:
        from . import remote

        remote.detach(self.window)
        self.window = None
        if self.screen is not None:
            self.screen.stop()
            self.screen = None


def _window_place(for_person: bool, headless: bool, tenant_key: str | None, url: str, operation: str, *, needs_window: bool) -> _Place:
    """Decide where the window of a page goes.

                                   a screen here        no screen (a server)
    hidden page                    hidden               hidden
    a person must use it           a window             pictures in the web page (remote.py)
    the site refuses hidden,       a window             a window on a virtual screen (vscreen.py) - shown in the
    or an ordinary Chrome                               web page when a person must use it; without a virtual
                                                        screen: hidden, and pictures for the person

    `needs_window`: the browser must be a real window whoever looks (the site refuses the hidden one; an ordinary Chrome).
    """
    from urllib.parse import urlparse

    from . import db, remote, vscreen

    place = _Place()
    place.title = urlparse(url).netloc or str(tenant_key or "")
    place.headless = headless
    if headless or not no_screen():
        return place                                    # hidden as asked, or there is a screen for the window
    canonical = str((db.get_setting("accounts.alias") or {}).get(tenant_key) or tenant_key or "")
    refused = canonical in (db.get_setting("browser.visible_sites") or [])
    if (needs_window or refused) and (vscreen.can_view() if for_person else vscreen.available()):
        try:
            place.screen = vscreen.private() if for_person else None
            screen = place.screen or vscreen.shared()
        except (OSError, RuntimeError) as e:
            logging.getLogger("autoapply.browser").warning("no virtual screen (%s): the page stays hidden", e)
        else:
            place.env = screen.env()
            place.args = ["--window-position=0,0", f"--window-size={vscreen.SIZE[0]},{vscreen.SIZE[1]}"]
            place.headless = False
            if for_person:
                place.window = remote.attach_screen(screen, title=place.title, purpose=operation, tenant=str(tenant_key or ""))
                remote.announce(place.window)
            return place
    place.headless = True                               # nowhere to open a window
    place.pictures = for_person
    return place


_env_lock = threading.RLock()


def no_screen() -> bool:
    """remote.no_screen(), asked while no browser is being started with a borrowed screen in the process environment
    (_environment): a second window opened at that moment would otherwise take the first one's private screen for a
    real one, and go onto it without a remote window of its own."""
    from . import remote

    with _env_lock:
        return remote.no_screen()


@contextmanager
def _environment(extra: dict[str, str]) -> Iterator[None]:
    """Start a program with these variables added to its environment (for one that takes them from the process)."""
    if not extra:
        yield
        return
    with _env_lock:
        before = {k: os.environ.get(k) for k in extra}
        os.environ.update(extra)
        try:
            yield
        finally:
            for k, v in before.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def idle(page: Any, seconds: float) -> None:
    """Wait on a page for a person: through the page, so that a remote window is served while waiting."""
    from . import remote

    remote.idle(page, seconds)


@contextmanager
def open_page(tenant_key: str | None = None, *, headless: bool = True, downloads: Path | None = None,
              url: str = "", operation: str = "apply", backend: str | None = None) -> Iterator[Page]:
    """Yield a page in a fresh context, restoring the tenant's saved session if any.

    headless=False asks for a window a person can see and use. Where there is a screen that is a browser window on
    it. Where there is none (a server), the page stays in the hidden browser and is shown to the person in the
    program's web page instead (remote.py); the caller does not have to know which.
    """
    from . import browser_policy, db, net, remote
    import logging

    for_person = not headless          # as asked for, before a site that refuses the hidden window changes it

    selected = browser_policy.select(tenant_key, url, operation, backend)
    from . import metering
    metering.stage(f"browser:{selected.backend} ({selected.reason})")
    logging.getLogger("autoapply.browser").info("Browser backend %s (%s)", selected.backend, selected.reason)
    canonical = str((db.get_setting("accounts.alias") or {}).get(tenant_key) or tenant_key or "")
    if headless and canonical in (db.get_setting("browser.visible_sites") or []):
        headless = False
    if selected.backend == "nodriver":
        from . import nodriver_backend

        executable = db.get_setting("browser.executable") or find_chrome()
        if not executable:
            raise RuntimeError("nodriver requires Chrome or Edge; set its executable in browser settings")
        if net.mode() == "custom" and db.get_setting("proxy.username"):
            raise RuntimeError("Authenticated proxy support is not yet available for nodriver")
        profile = _native_profile(tenant_key) if tenant_key else None
        with nodriver_backend.profile_lock(profile):
            state = with_identities(load_state(tenant_key) if tenant_key else None, tenant_key, "nodriver")
            with _window_place(for_person, headless, tenant_key, url, operation, needs_window=not headless) as place:
                if place.pictures:
                    raise RuntimeError("这个网站要在普通的浏览器窗口里操作，而这台电脑没有屏幕，也没有虚拟屏幕。请安装 xvfb 和 x11vnc（sudo apt-get install -y xvfb x11vnc），或者改用容器镜像。")
                with _environment(place.env):          # an ordinary Chrome takes its screen from the environment it is started in
                    opened = nodriver_backend.open_page(state, headless=headless and place.headless, executable=executable, args=net.chrome_args() + place.args, profile=profile)
                    page = opened.__enter__()
                before, _now.backend = getattr(_now, "backend", None), "nodriver"
                try:
                    yield page
                finally:
                    _now.backend = before
                    opened.__exit__(None, None, None)
        return
    with sync_playwright() as p:
        from . import db, net

        if tenant_key:      # a site whose sign-in is another site's: that site's saved session
            tenant_key = str((db.get_setting("accounts.alias") or {}).get(tenant_key) or tenant_key)

        if headless and tenant_key and tenant_key in (db.get_setting("browser.visible_sites") or []):
            headless = False  # this site was seen refusing the hidden window
        place = _window_place(for_person, headless, tenant_key, url, operation, needs_window=not headless and not for_person).__enter__()
        options = net.browser_options()
        if place.args:
            options = {**options, "args": [*options.get("args", []), *place.args]}
        if place.env:
            options["env"] = {**os.environ, **place.env}
        shown_remotely = place.pictures
        headless = place.headless
        try:
            browser = p.chromium.launch(headless=headless, **options)
        except Exception:
            place.__exit__(None, None, None)
            raise
        try:
            state = with_identities(load_state(tenant_key) if tenant_key else None, tenant_key, "playwright")
            # on a virtual screen the page is as large as its window, which is as large as that screen
            size: dict[str, Any] = {"no_viewport": True} if place.env else {"viewport": remote.VIEWPORT if shown_remotely else {"width": 1366, "height": 900}}
            ctx = browser.new_context(storage_state=state, locale="en-US", accept_downloads=bool(downloads), **size)
            ctx.set_default_timeout(15000)
            ctx.set_default_navigation_timeout(75000)  # large career sites take 30-45 s to load over a slow link; 15 s gave up on them
            page = ctx.new_page()
            window = None
            if shown_remotely:
                window = remote.attach(page, title=place.title, purpose=operation, tenant=str(tenant_key or ""))
                remote.announce(window)
            before, _now.backend = getattr(_now, "backend", None), "playwright"
            try:
                yield page
            finally:
                _now.backend = before
                remote.detach(window)
                try:
                    ctx.close()
                except Exception:  # noqa: BLE001 - the user closed the window themselves
                    pass
        finally:
            place.__exit__(None, None, None)
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
