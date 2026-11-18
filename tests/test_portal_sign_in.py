"""The co-op portal's sign-in: the portal -> the university's login (CWL) -> Duo -> back.

The program used to hand every expired session to the applicant ("CWL + Duo: never automated"), although the only step
that needs a person is the approval on the phone. The fake below is built from the live pages' make-up as far as it
could be read without signing in: the portal's entry address, the university login's address and its three controls.
What Duo's pages look like is NOT known here; the program is written not to depend on it, and the fake's Duo page is
just a page on a Duo address that leads back when "approved".
"""
import pytest

from autoapply import db

PORTAL, IDP, DUO = "pdportal.apsc.ubc.ca", "authentication.ubc.ca", "api-1a2b3c.duosecurity.com"
KEY = "pdportal:ubc"


class Campus:
    def __init__(self):
        self.portal_in = self.idp_in = False
        self.duo, self.approve_after, self.polls, self.pushes = True, 8, 0, 0      # approved after about three seconds
        self.right = ("cwlname", "right-pw")
        self.typed: list[tuple[str, str, str]] = []      # (host, user, password) of every sign-in form that was sent
        self.browser_remembers: tuple[str, str] | None = None      # the login the browser's own password manager puts in the form
        self.idp_host = IDP

    def answer(self, route):
        from urllib.parse import parse_qs, urlparse

        u = urlparse(route.request.url)
        host, path, q = u.netloc, u.path, parse_qs(u.query)

        def html(body):
            route.fulfill(content_type="text/html", body=f"<html><body>{body}</body></html>")

        def to(url):
            route.fulfill(content_type="text/html", body=f"<html><body><script>location.replace({url!r})</script></body></html>")

        def onward():
            if self.duo:
                self.pushes += 1
                self.polls = 0
                return to(f"https://{DUO}/frame/v4/auth/prompt")
            return to(f"https://{PORTAL}/secure/sso-student.htm")

        if host == PORTAL:
            if path == "/Shibboleth.sso/Login":
                return onward() if self.idp_in else to(f"https://{self.idp_host}/idp/profile/SAML2/Redirect/SSO?execution=e1s1")
            if path == "/secure/sso-student.htm":
                self.portal_in = True
                return to(f"https://{PORTAL}/myAccount/dashboard.htm")
            if path.startswith("/myAccount/"):
                return html('<h1>Dashboard</h1><form id="widgetSearch"><input name="widget1Keyword"></form>' if self.portal_in else "<h1>Not Logged In</h1>")
            return html("<a href='/students/student-login.htm'>STUDENT LOGIN</a>")
        if host == self.idp_host:
            if path == "/send":
                self.typed.append((host, q.get("u", [""])[0], q.get("p", [""])[0]))
                if (q.get("u", [""])[0], q.get("p", [""])[0]) == self.right:
                    self.idp_in = True
                    return onward()
                return to(f"https://{host}/idp/profile/SAML2/Redirect/SSO?execution=e1s2")
            failed = '<p class="form-error">Login Failed. Please try again.</p>' if "e1s2" in u.query else ""
            name, word = self.browser_remembers or ("", "")
            return html(f'''<h1>CWL Authentication</h1>{failed}<div class="alert">Recover your CWL login</div>
                <form onsubmit="location.href='/send?u='+encodeURIComponent(username.value)+'&p='+encodeURIComponent(password.value);return false">
                <input type="text" id="username" name="j_username" value="{name}"><input type="password" id="password" name="j_password" value="{word}">
                <button type="submit" name="_eventId_proceed">Login</button></form>''')
        if host == DUO:
            if path == "/status":
                self.polls += 1
                return route.fulfill(content_type="application/json", body='{"ok": %s}' % ("true" if self.approve_after is not None and self.polls >= self.approve_after else "false"))
            return html(f'''<h1>Check your phone</h1><script>setInterval(() => fetch('/status').then(r => r.json()).then(j => {{
                if (j.ok) location.href = 'https://{PORTAL}/secure/sso-student.htm' }}), 400)</script>''')
        return html("")


@pytest.fixture()
def campus(app_env, monkeypatch):
    from playwright.sync_api import sync_playwright

    from autoapply import browser, notify
    from autoapply.ats.pdportal import PDPortalDriver

    monkeypatch.setattr(browser, "save_state", lambda *a, **k: None)
    told: list = []
    real = notify.send
    monkeypatch.setattr(notify, "send", lambda category, card, **kw: (told.append(getattr(card, "heading", card)) if getattr(card, "icon", "") == "📱" else None,
                                                                    real(category, card, **kw))[1])      # told: what reached the applicant's phone about a second factor
    driver = PDPortalDriver()
    ref = driver.detect(f"https://{PORTAL}/myAccount/co-op/postings.htm#posting=150971")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        site = Campus()
        page.route("**/*", site.answer)
        yield type("C", (), {"page": page, "site": site, "driver": driver, "ref": ref, "told": told})()
        b.close()


def _cards():
    from autoapply.models import Todo

    with db.session() as s:
        return [(t.body, t.payload) for t in s.query(Todo).filter_by(kind="takeover", status="open")]


def _save_login(pw="right-pw"):
    from autoapply import auth

    auth.upsert_account(KEY, ats="pdportal", host=PORTAL, email="cwlname", password=pw, status="unknown", created_by="manual")


def test_the_portal_is_signed_in_to_with_the_saved_login_and_only_the_phone_is_the_applicants(campus):
    from autoapply import auth

    _save_login()
    assert auth.ensure_session(campus.page, campus.driver, campus.ref) == "logged_in"
    assert campus.site.typed == [(IDP, "cwlname", "right-pw")]                  # once, on the university's own address
    assert campus.told == ["请在手机上批准 Duo"] and campus.site.pushes == 1 and _cards() == []
    assert auth.account(KEY)["status"] == "ok"

    # an hour later the portal's session is gone, the university's is not: nothing is typed; Duo, if asked, is waited for
    campus.site.portal_in, campus.site.duo = False, False
    assert auth.ensure_session(campus.page, campus.driver, campus.ref) == "logged_in"
    assert len(campus.site.typed) == 1 and len(campus.told) == 1


def test_without_a_saved_login_nothing_is_typed_and_the_card_says_how_to_have_it_done(campus, monkeypatch):
    from contextvars import ContextVar

    from autoapply import auth, browser_policy
    from autoapply.ats.base import NeedsHuman

    monkeypatch.setattr(browser_policy, "_override", ContextVar("browser_backend", default=None))      # nothing chooses for this test
    auth.upsert_account(KEY, ats="pdportal", host=PORTAL, status="unknown", created_by="takeover")
    db.set_setting("account.email", "me@example.test")          # the applicant's e-mail is not a CWL name: it is not tried
    with pytest.raises(NeedsHuman) as e:
        auth.ensure_session(campus.page, campus.driver, campus.ref)
    (body, payload), = _cards()
    assert e.value.waits_for == f"account:{KEY}" and campus.site.typed == [] and campus.told == []
    assert "保存登录名和密码" in body and payload["can_register"] is False       # (the plain window cannot remember: the Accounts page can)
    # where the portal's sign-in is made in the ordinary browser, its window remembers: the card says so
    from autoapply import notify

    notify.close_todos("takeover", f"account:{KEY}")
    db.set_setting("browser.nodriver_enabled", True)
    db.set_setting("browser.rules", [{"tenant": KEY, "backend": "nodriver"}])
    with pytest.raises(NeedsHuman):
        auth.ensure_session(campus.page, campus.driver, campus.ref)
    assert "记住我输入的密码" in _cards()[0][0] and campus.site.typed == []


def test_a_password_the_university_refuses_is_not_sent_a_third_time(campus):
    from autoapply import auth
    from autoapply.ats.base import NeedsHuman

    _save_login("wrong-pw")
    for n in (1, 2, 2):       # the third time it is not even tried: an account is not locked by the program
        with pytest.raises(NeedsHuman):
            auth.ensure_session(campus.page, campus.driver, campus.ref)
        assert len(campus.site.typed) == n and auth.account(KEY)["fail_count"] == n
    assert "rejected" in auth.account(KEY)["last_error"] and "wrong-pw" not in auth.account(KEY)["last_error"]
    assert campus.told == []


def test_an_approval_that_does_not_come_is_asked_for_in_a_card_and_not_pushed_again(campus, monkeypatch):
    from autoapply import auth, notify
    from autoapply.ats.base import NeedsHuman

    _save_login()
    monkeypatch.setattr(campus.driver, "second_factor_wait", 3, raising=False)
    campus.site.approve_after = None           # the phone is not at hand
    with pytest.raises(NeedsHuman) as e:
        auth.ensure_session(campus.page, campus.driver, campus.ref)
    (body, payload), = _cards()
    assert e.value.waits_for == f"account:{KEY}" and "Duo" in body and payload["second_factor"] is True and payload["can_register"] is False
    assert campus.site.pushes == 1 and auth.account(KEY)["fail_count"] == 0          # the password was fine
    with pytest.raises(NeedsHuman):            # the next scan, hours later: no second request on the phone at 3 a.m.
        auth.ensure_session(campus.page, campus.driver, campus.ref)
    assert campus.site.pushes == 1
    notify.close_todos("takeover", f"account:{KEY}")       # the applicant says: now
    campus.site.approve_after = 1
    assert auth.ensure_session(campus.page, campus.driver, campus.ref) == "logged_in" and campus.site.pushes == 2


def test_the_password_is_typed_on_the_universitys_address_and_nowhere_else(campus):
    from autoapply import auth
    from autoapply.ats.base import NeedsHuman

    _save_login()
    campus.site.idp_host = "authentication.ubc.ca.sign-in.example"       # the sign-in leads to a look-alike
    with pytest.raises(NeedsHuman):
        auth.ensure_session(campus.page, campus.driver, campus.ref)
    assert campus.site.typed == [] and campus.page.input_value("#password") == ""
    assert auth.account(KEY)["fail_count"] == 0             # nothing was refused: nothing was sent


def test_the_scan_signs_in_the_same_way(campus):
    """An expired session at scan time made a card at once - the scan never went near the sign-in."""
    from autoapply.sources import pdportal

    _save_login()
    campus.page.goto(pdportal.POSTINGS)
    assert "Not Logged In" in campus.page.inner_text("body")
    pdportal.sign_in(campus.page)
    assert campus.page.url == pdportal.POSTINGS and campus.page.locator("#widgetSearch").count() == 1 and _cards() == []


def test_a_form_the_browser_has_filled_in_is_sent_and_only_the_phone_is_the_applicants(campus):
    """No login was saved with the program; the browser had its own, and the university's form stood filled in. The
    program looked at it, closed the window and asked the applicant to sign in - for the press of one button."""
    from autoapply import auth, secrets

    auth.upsert_account(KEY, ats="pdportal", host=PORTAL, status="unknown", created_by="takeover")
    campus.site.browser_remembers = ("cwlname", "right-pw")
    assert auth.ensure_session(campus.page, campus.driver, campus.ref) == "logged_in"
    assert campus.site.typed == [(IDP, "cwlname", "right-pw")]                  # sent once, as it stood
    assert campus.told == ["请在手机上批准 Duo"] and campus.site.pushes == 1 and _cards() == []
    acct = auth.account(KEY)
    assert acct["status"] == "ok" and not acct["has_password"] and secrets.get_password(KEY) is None      # the browser's is the browser's: nothing was taken


def test_a_password_the_browser_remembers_and_the_university_refuses_is_not_sent_a_third_time(campus):
    from autoapply import auth
    from autoapply.ats.base import NeedsHuman

    campus.site.browser_remembers = ("cwlname", "an-old-pw")       # the password was changed since the browser saved it
    for n in (1, 2, 2):
        with pytest.raises(NeedsHuman):
            auth.ensure_session(campus.page, campus.driver, campus.ref)
        assert len(campus.site.typed) == n and auth.account(KEY)["fail_count"] == n
    assert all("浏览器里保存的密码" in body for body, _ in _cards()) and "an-old-pw" not in auth.account(KEY)["last_error"]
    assert campus.told == []


def test_a_form_the_browser_filled_in_is_not_sent_anywhere_but_at_the_university_and_not_in_the_quiet_hours(campus, monkeypatch):
    from autoapply import auth, notify
    from autoapply.ats.base import NeedsHuman

    campus.site.browser_remembers = ("cwlname", "right-pw")
    monkeypatch.setattr(notify, "quiet_now", lambda: True)         # 3 a.m., a scan of the program's own: the phone is not rung
    with pytest.raises(NeedsHuman):
        auth.ensure_session(campus.page, campus.driver, campus.ref)
    (body, payload), = _cards()
    assert campus.site.typed == [] and "静默时段" in body and payload["second_factor"] is True
    notify.close_todos("takeover", f"account:{KEY}")
    monkeypatch.setattr(notify, "quiet_now", lambda: False)
    campus.site.idp_host = "authentication.ubc.ca.sign-in.example"       # the sign-in leads to a look-alike that shows a filled-in form
    with pytest.raises(NeedsHuman):
        auth.ensure_session(campus.page, campus.driver, campus.ref)
    assert campus.site.typed == []


def test_the_login_the_window_remembered_is_what_the_next_sign_in_uses(campus):
    """The applicant signs in by hand once, with "remember" ticked; the university's login is on another address than
    the portal. What the window kept signs the portal in the next time its session has run out."""
    from autoapply import auth, sites

    assert auth._this_sites_password(IDP, auth._site(PORTAL)) and not auth._this_sites_password("accounts.google.com", auth._site(PORTAL))
    assert auth._signed_in_by_hand(KEY, PORTAL, {"user": "cwlname", "pw": "right-pw", "host": IDP}) is True
    acct = auth.account(KEY)
    assert acct["login_email"] == "cwlname" and acct["has_password"] and acct["status"] == "ok"
    assert auth.ensure_session(campus.page, campus.driver, campus.ref) == "logged_in"
    assert campus.site.typed == [(IDP, "cwlname", "right-pw")] and _cards() == []
    # a login seen without its name is not given the applicant's e-mail for a name (a CWL name is not an e-mail address)
    db.set_setting("account.email", "me@example.test")
    auth._signed_in_by_hand(KEY, PORTAL, {"user": "", "pw": "right-pw", "host": IDP})
    assert auth.account(KEY)["login_email"] == ""
    assert sites.fact(KEY, "sign_in_hosts") == [IDP]             # where this site takes its password is known from now on


def test_what_a_sign_in_form_sends_is_told_from_what_other_forms_send():
    from autoapply.auth import credentials_sent

    assert credentials_sent("j_username=cwlname&j_password=p%40ss+word&_eventId_proceed=") == ("cwlname", "p@ss word")
    assert credentials_sent('{"email": "a@b.example", "password": "pw1", "remember": true}') == ("a@b.example", "pw1")
    assert credentials_sent('{"data": {"identifier": "someone", "credentials": {"passwd": "pw2"}}}') == ("someone", "pw2")
    assert credentials_sent("who=a%40b.example&pwd=pw3") == ("a@b.example", "pw3")              # a name the pattern does not know: the address is taken
    assert credentials_sent("q=backend+intern&page=2") is None and credentials_sent("") is None and credentials_sent("{not json") is None
    assert credentials_sent("new_password=x&confirm_password=x") is None                          # a change of password is not a sign-in


def test_a_card_offers_to_remember_the_login_only_where_its_window_can(app_env, monkeypatch):
    from contextvars import ContextVar

    from fastapi.testclient import TestClient

    from autoapply import auth, browser_policy, notify
    from autoapply.api.main import app

    monkeypatch.setattr(browser_policy, "_override", ContextVar("browser_backend", default=None))      # nothing chooses for this test
    assert auth.remembers_login("someats:acme", "https://acme.example/login") is True          # the automated browser's window sees what is typed
    assert auth.remembers_login("idp:google") is False                                           # a provider's password is never stored
    assert auth.remembers_login(KEY, f"https://{PORTAL}/home.htm") is False                      # a window the program does not look into
    db.set_setting("browser.nodriver_enabled", True)
    db.set_setting("browser.rules", [{"tenant": KEY, "backend": "nodriver"}])
    assert auth.remembers_login(KEY, f"https://{PORTAL}/home.htm") is True                       # the ordinary browser's window hears what is sent
    notify.add_todo("takeover", KEY, body="x", ref=f"account:{KEY}", payload={"tenant_key": KEY, "url": f"https://{PORTAL}/home.htm"})
    notify.add_todo("takeover", "Google", body="x", ref="account:idp:google", payload={"tenant_key": "idp:google", "url": "https://accounts.google.com/"})
    cards = {c["ref"]: c for c in TestClient(app).get("/api/todos").json()}
    assert cards[f"account:{KEY}"]["remembers"] is True and cards["account:idp:google"]["remembers"] is False
