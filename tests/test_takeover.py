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


def test_the_login_used_in_the_window_is_remembered_when_that_is_ticked(window, site):
    """"Remember the password I type" is on every sign-in card. In the ordinary browser's window nothing was ever
    remembered, whatever was ticked: the applicant signed in, and was asked to again when the session ran out."""
    from autoapply import auth, secrets

    which, played_by = window
    played_by([_signs_in, None, None, lambda page: page.close()])
    got = auth.takeover(KEY, site + "/login", save_credentials=True, timeout_s=30)
    assert got["ok"] is True and got["credentials_saved"] is True
    acct = auth.account(KEY)
    assert acct["login_email"] == "liam@example.com" and acct["has_password"] and acct["status"] == "ok"
    assert secrets.get_password(KEY) == "a password made up for this test"
    assert _kept(site)


def test_a_login_is_not_remembered_when_that_is_not_ticked(window, site):
    from autoapply import auth, secrets

    which, played_by = window
    played_by([_signs_in, None, None, lambda page: page.close()])
    got = auth.takeover(KEY, site + "/login", save_credentials=False, timeout_s=30)
    assert got["ok"] is True and got["credentials_saved"] is False
    assert not auth.account(KEY)["has_password"] and secrets.get_password(KEY) is None


PORTAL, PORTAL_KEY = "pdportal.apsc.ubc.ca", "pdportal:ubc"


def test_what_a_sign_in_form_sends_is_told_from_what_other_forms_send():
    from autoapply.auth import credentials_sent

    assert credentials_sent("j_username=cwlname&j_password=p%40ss+word&_eventId_proceed=") == ("cwlname", "p@ss word")
    assert credentials_sent('{"email": "a@b.example", "password": "pw1", "remember": true}') == ("a@b.example", "pw1")
    assert credentials_sent('{"data": {"identifier": "someone", "credentials": {"passwd": "pw2"}}}') == ("someone", "pw2")
    assert credentials_sent("who=a%40b.example&pwd=pw3") == ("a@b.example", "pw3")              # a name the pattern does not know: the address is taken
    assert credentials_sent("q=backend+intern&page=2") is None and credentials_sent("") is None and credentials_sent("{not json") is None
    assert credentials_sent("new_password=x&confirm_password=x") is None                          # a change of password is not a sign-in
    # a second factor is sent in a field with "pass" in its name: it is used once and is not the account's password
    assert credentials_sent("passcode=123456") is None and credentials_sent('{"passcode": "123456", "device": "phone1"}') is None
    assert credentials_sent("j_username=cwlname&j_password=pw&otp_code=123456") == ("cwlname", "pw")


def test_a_card_offers_to_remember_the_login_only_where_its_window_can(app_env, monkeypatch):
    from contextvars import ContextVar

    from fastapi.testclient import TestClient

    from autoapply import auth, browser_policy, notify
    from autoapply.api.main import app

    monkeypatch.setattr(browser_policy, "_override", ContextVar("browser_backend", default=None))      # nothing chooses for this test
    db.set_setting("browser.nodriver_enabled", False)                                                   # (the round that runs everything in the ordinary browser switches it on)
    assert auth.remembers_login("someats:acme", "https://acme.example/login") is True          # the automated browser's window sees what is typed
    assert auth.remembers_login("idp:google") is False                                           # a provider's password is never stored
    assert auth.remembers_login(PORTAL_KEY, f"https://{PORTAL}/home.htm") is False                      # a window the program does not look into
    db.set_setting("browser.nodriver_enabled", True)
    db.set_setting("browser.rules", [{"tenant": PORTAL_KEY, "backend": "nodriver"}])
    assert auth.remembers_login(PORTAL_KEY, f"https://{PORTAL}/home.htm") is True                       # the ordinary browser's window hears what is sent
    notify.add_todo("takeover", PORTAL_KEY, body="x", ref=f"account:{PORTAL_KEY}", payload={"tenant_key": PORTAL_KEY, "url": f"https://{PORTAL}/home.htm"})
    notify.add_todo("takeover", "Google", body="x", ref="account:idp:google", payload={"tenant_key": "idp:google", "url": "https://accounts.google.com/"})
    cards = {c["ref"]: c for c in TestClient(app).get("/api/todos").json()}
    assert cards[f"account:{PORTAL_KEY}"]["remembers"] is True and cards["account:idp:google"]["remembers"] is False
