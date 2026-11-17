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
            return html(f'''<h1>CWL Authentication</h1>{failed}<div class="alert">Recover your CWL login</div>
                <form onsubmit="location.href='/send?u='+encodeURIComponent(username.value)+'&p='+encodeURIComponent(password.value);return false">
                <input type="text" id="username" name="j_username"><input type="password" id="password" name="j_password">
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


def test_without_a_saved_login_nothing_is_typed_and_the_card_says_how_to_have_it_done(campus):
    from autoapply import auth
    from autoapply.ats.base import NeedsHuman

    auth.upsert_account(KEY, ats="pdportal", host=PORTAL, status="unknown", created_by="takeover")
    db.set_setting("account.email", "me@example.test")          # the applicant's e-mail is not a CWL name: it is not tried
    with pytest.raises(NeedsHuman) as e:
        auth.ensure_session(campus.page, campus.driver, campus.ref)
    (body, payload), = _cards()
    assert e.value.waits_for == f"account:{KEY}" and campus.site.typed == [] and campus.told == []
    assert "保存登录名和密码" in body and payload["can_register"] is False


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
