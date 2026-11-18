"""The sign-in window: the applicant signs in, the program keeps the session - in either browser.

A site's sign-in is made in the automated browser or in the ordinary one (browser_policy), and the window is two
pieces of code (auth.takeover). The same site, the same applicant, the same outcome: each test here runs in both.
The applicant is played by what the window waits with (browser.idle); the site is a local one.
"""

import importlib.util
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from autoapply import db

KEY = "someats:acme"
LOGIN = b"""<!doctype html><title>Sign in</title><form method="post" action="/login">
<label for="user">E-mail</label><input id="user" name="user" type="email">
<label for="pw">Password</label><input id="pw" name="pw" type="password">
<button id="go" type="submit">Sign in</button></form>"""


@pytest.fixture
def site():
    """A site with an account: /login takes any e-mail and password and gives a session; /account needs one."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body=b"", headers=()):
            self.send_response(code)
            for k, v in headers:
                self.send_header(k, v)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            signed_in = "session=ok" in (self.headers.get("Cookie") or "")
            if self.path.startswith("/account"):
                if signed_in:
                    return self._send(200, b"<!doctype html><title>Account</title><h1 id='who'>Signed in</h1>")
                return self._send(302, headers=[("Location", "/login")])
            return self._send(200, LOGIN)

        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self._send(302, headers=[("Location", "/account"), ("Set-Cookie", "session=ok; Path=/; Max-Age=3600")])

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(params=["playwright", "nodriver"])
def window(request, app_env, monkeypatch):
    """Which browser the site's sign-in is made in - laid down the way the applicant lays it down, by a rule."""
    from contextvars import ContextVar

    from autoapply import browser, browser_policy
    from autoapply.browser import find_chrome

    monkeypatch.setattr(browser_policy, "_override", ContextVar("browser_backend", default=None))      # nothing chooses for these tests
    if request.param == "nodriver":
        if importlib.util.find_spec("nodriver") is None:
            pytest.skip("nodriver is not installed")
        if not find_chrome():
            pytest.skip("Chrome or Edge is required")
        monkeypatch.setenv("AUTOAPPLY_ORDINARY_HIDDEN", "1")
    db.set_setting("browser.nodriver_enabled", True)
    db.set_setting("browser.rules", [{"tenant": KEY, "backend": request.param}])
    real_idle = browser.idle

    def played_by(script):
        """``script``: what the applicant does at each look at the window, in order (a function of the page, or None)."""
        steps = list(script)

        def idle(page, seconds):
            if steps:
                act = steps.pop(0)
                if act is not None:
                    act(page)
            real_idle(page, 0.2)

        monkeypatch.setattr(browser, "idle", idle)

    return request.param, played_by


def _signs_in(page):
    page.locator("#user").fill("liam@example.com")
    page.locator("#pw").fill("a password made up for this test")
    page.locator("#go").click()


def _kept(site):
    """Is the site's session kept - asked the way the next run asks: a new page for the site, at an address that needs one."""
    from autoapply import browser

    with browser.open_page(KEY) as page:
        page.goto(site + "/account")
        return page.title() == "Account"


def test_a_sign_in_the_site_can_be_asked_about_is_kept_when_it_is_done(window, site):
    from autoapply import auth, browser_policy, notify
    from autoapply.models import Account, Todo

    which, played_by = window
    notify.add_todo("takeover", "Acme", body="please sign in", ref=f"account:{KEY}")
    played_by([_signs_in])
    got = auth.takeover(KEY, site + "/login", save_credentials=False, timeout_s=30, done=lambda url: "/account" in url)
    assert got["ok"] is True and got["credentials_saved"] is False
    assert _kept(site)
    # the session lives in the browser it was made in: the site's work goes there from now on
    db.set_setting("browser.rules", [])
    assert browser_policy.select(KEY).backend == which
    with db.session() as s:
        # the card that asked for it is answered; a sign-in told by the caller's own check (a provider's) is a session, not a site account
        assert [t.status for t in s.query(Todo).filter_by(ref=f"account:{KEY}")] == ["done"] and s.query(Account).count() == 0


def test_a_sign_in_nothing_can_check_is_kept_when_the_applicant_closes_the_window(window, site):
    """A site with no driver and no check: there is nothing to tell a finished sign-in by, so closing the window says
    "done". In the ordinary browser it said "window closed before sign-in was verified" - every time."""
    from autoapply import auth, notify
    from autoapply.models import Account, Todo

    which, played_by = window
    notify.add_todo("takeover", "Acme", body="please sign in", ref=f"account:{KEY}")
    played_by([_signs_in, None, None, lambda page: page.close()])
    got = auth.takeover(KEY, site + "/login", save_credentials=False, timeout_s=30)
    assert got["ok"] is True and got.get("unverified") is True and got["credentials_saved"] is False
    assert _kept(site)
    with db.session() as s:
        acct = s.query(Account).filter_by(tenant_key=KEY).one()
        assert acct.status == "ok" and acct.created_by == "takeover"
        assert [t.status for t in s.query(Todo).filter_by(ref=f"account:{KEY}")] == ["done"]


def test_a_window_closed_before_anything_was_done_keeps_nothing(window, site):
    from autoapply import auth, browser

    which, played_by = window
    played_by([None, lambda page: page.close()])
    got = auth.takeover(KEY, site + "/login", save_credentials=False, timeout_s=30, done=lambda url: "/account" in url)
    assert got["ok"] is False and got["reason"]
    assert browser.load_state(KEY) is None and not _kept(site)
