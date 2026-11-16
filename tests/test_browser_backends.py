"""Routing and native browser regressions (all pages are local fixtures)."""

import importlib.util
from pathlib import Path
from urllib.parse import quote

import pytest


@pytest.fixture
def as_configured(app_env, monkeypatch):
    """These tests are about which browser is chosen: nothing chooses for them (see AUTOAPPLY_TEST_BROWSER in conftest)."""
    from contextvars import ContextVar

    from autoapply import browser_policy, db

    monkeypatch.setattr(browser_policy, "_override", ContextVar("browser_backend", default=None))
    db.set_setting("browser.nodriver_enabled", False)


def test_routing_precedence_and_domain_boundaries(as_configured):
    from autoapply import browser_policy, db

    assert browser_policy.select("pdportal:ubc").backend == "playwright"
    db.set_setting("browser.nodriver_enabled", True)
    assert browser_policy.select("pdportal:ubc").backend == "nodriver"
    assert browser_policy.select(None, "https://accounts.google.com", "login").backend == "nodriver"
    assert browser_policy.select(None, "https://accounts.google.com.evil.example", "login").backend == "playwright"
    assert browser_policy.select(None, "https://example.com/?url=accounts.google.com", "login").backend == "playwright"
    assert browser_policy.select(None, "https://accounts.google.com", "scan").backend == "playwright"
    assert browser_policy.select("pdportal:ubc", override="playwright").backend == "playwright"
    # a rule saved when the portal's entry said "login" only: reading and applying there still need the ordinary browser
    db.set_setting("browser.rules", [{"tenant": "pdportal:ubc", "backend": "nodriver", "operations": ["login"]}])
    assert {browser_policy.select("pdportal:ubc", operation=op).backend for op in ("login", "scan", "read", "apply")} == {"nodriver"}
    db.set_setting("browser.rules", [{"tenant": "a", "backend": "playwright"}, {"domain": "example.com", "backend": "nodriver"}])
    assert browser_policy.select("a", "https://example.com").backend == "playwright"
    assert browser_policy.select(None, "https://jobs.example.com").backend == "nodriver"


@pytest.mark.parametrize("rule", [
    {"domain": "https://example.com", "backend": "nodriver"},
    {"domain": "example.com", "backend": "unknown"},
    {"domain": "example.com", "tenant": "a", "backend": "nodriver"},
    {"domain": "example.com", "backend": "nodriver", "operations": ["unknown"]},
])
def test_invalid_rules(rule):
    from autoapply.browser_policy import validate

    with pytest.raises(ValueError):
        validate({"browser.rules": [rule]})


@pytest.fixture
def native_page():
    if importlib.util.find_spec("nodriver") is None:
        pytest.skip("Install the nodriver extra to run native integration tests")
    from autoapply.browser import find_chrome
    from autoapply.nodriver_backend import open_page

    executable = find_chrome()
    if not executable:
        pytest.skip("Chrome or Edge is required")
    with open_page(None, headless=True, executable=executable, args=["--no-proxy-server"]) as page:
        yield page


def test_native_form_operations(native_page, tmp_path):
    page = native_page
    html = """<title>Native fixture</title><label for='name'>Full name</label><input id='name'>
    <label><input type='checkbox' id='check'>Agree</label>
    <select id='choice'><option value='a'>Alpha</option><option value='b'>Beta</option></select>
    <input type='file' id='file'><button onclick="document.querySelector('#result').textContent='done'">Continue</button>
    <div id='result'></div><div id='later'></div>
    <script>setTimeout(()=>document.querySelector('#later').textContent='ready',300)</script>"""
    page.goto("data:text/html," + quote(html))
    assert page.title() == "Native fixture"
    assert page.evaluate("() => false") is False
    assert page.evaluate("arg => arg", {"a": [0, False, None]}) == {"a": [0, False, None]}
    page.get_by_label("Full name", exact=True).fill("Liam")
    assert page.locator("#name").input_value() == "Liam"
    page.locator("#name").fill("Frost")
    assert page.locator("#name").input_value() == "Frost"
    page.get_by_role("checkbox", name="Agree").set_checked(True)
    assert page.locator("#check").is_checked()
    page.locator("#choice").select_option(label="Beta")
    assert page.locator("#choice").input_value() == "b"
    upload = tmp_path / "resume.txt"
    upload.write_text("fixture")
    page.locator("#file").set_input_files(upload)
    assert page.locator("#file").evaluate("e => e.files[0].name") == "resume.txt"
    page.get_by_role("button", name="Continue", exact=True).click()
    page.wait_for_function("() => document.querySelector('#result').textContent === 'done'")
    page.get_by_text("ready", exact=True).wait_for()
    assert page.screenshot().startswith(b"\x89PNG")


def test_native_popup_and_file_chooser(native_page, tmp_path):
    page = native_page
    page.goto("data:text/html," + quote("<input type=file id=f hidden><button onclick=\"document.querySelector('#f').click()\">Upload</button><button onclick=\"window.open('about:blank')\">Open</button>"))
    file = tmp_path / "document.txt"
    file.write_text("fixture")
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name="Upload").click()
    chooser.value.set_files(file)
    assert page.locator("#f").evaluate("e => e.files.length") == 1
    with page.context.expect_page() as popup:
        page.get_by_role("button", name="Open").click()
    assert popup.value.url == "about:blank"


def test_session_roundtrip_and_profile_lock(native_page, tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    from autoapply.nodriver_backend import open_page, profile_lock
    from autoapply.browser import find_chrome

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<title>Session fixture</title><body>OK</body>")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    state = {"cookies": [{"name": "session", "value": "test", "domain": "127.0.0.1", "path": "/", "expires": -1,
                          "httpOnly": True, "secure": False, "sameSite": "Lax"}],
             "origins": [{"origin": origin, "localStorage": [{"name": "example", "value": "before"}]}]}
    try:
        with open_page(state, headless=True, executable=find_chrome(), args=["--no-proxy-server"]) as page:
            response = page.goto(origin)
            assert response.status == 200
            assert page.evaluate("localStorage.getItem('example')") == "before"
            page.evaluate("localStorage.setItem('example', 'after')")
            page.goto(origin)
            assert page.evaluate("localStorage.getItem('example')") == "after"
            saved = page.context.storage_state()
            assert saved["cookies"][0]["httpOnly"] is True
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(storage_state=saved)
                page = context.new_page()
                page.goto(origin)
                assert page.evaluate("localStorage.getItem('example')") == "after"
                assert context.cookies()[0]["value"] == "test"
            finally:
                browser.close()
        profile = tmp_path / "profile"
        with profile_lock(profile):
            with pytest.raises(RuntimeError, match="already in use"):
                with profile_lock(profile):
                    pass
        with profile_lock(profile):
            pass
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_native_generic_schema(native_page):
    from autoapply.ats.generic_driver import GenericDriver
    from autoapply.ats.base import FormSchema, Question

    native_page.goto(Path("tests/fixtures/form.html").resolve().as_uri())
    schema = FormSchema(ats="generic", url=native_page.url, questions=[
        Question("first_name", "First Name", "text", locator={"selector": "#first_name"}),
        Question("auth", "Are you legally authorized to work in Canada?", "select", options=["Yes", "No"], locator={"selector": "#auth"}),
        Question("consent", "I agree to the privacy policy", "checkbox", locator={"selector": "#consent"}),
    ])
    driver = GenericDriver(schema)
    answers = {"first_name": "Test", "auth": "Yes", "consent": True}
    driver.fill_page(native_page, schema, 0, answers)
    result = driver.read_back(native_page, schema, 0)
    assert result["first_name"] == "Test"
    assert result["auth"] == "Yes"
    assert result["consent"] is True


def test_a_sites_work_is_done_in_the_browser_its_sign_in_lives_in_whatever_the_work_is(as_configured):
    """Google's careers site signs in on Google. The applicant signed in to Google in the ordinary browser; the rule
    saved for Google said "login" only, so filling the form went to the automated browser with Google's cookies - where
    Google shows the account as signed out - and the applicant was asked to sign in again, for a session they had."""
    from autoapply import browser_policy as bp, db

    db.set_setting("browser.nodriver_enabled", True)
    db.set_setting("accounts.alias", {"generic:www.google.com": "idp:google"})
    db.set_setting("browser.rules", [{"tenant": "pdportal:ubc", "backend": "nodriver", "operations": ["login"]},          # as saved by earlier versions
                                     {"tenant": "idp:google", "backend": "nodriver", "operations": ["login"]},
                                     {"domain": "accounts.google.com", "backend": "nodriver", "operations": ["login"]}])
    ops = ("login", "scan", "read", "apply")
    for tenant in ("idp:google", "generic:www.google.com", "pdportal:ubc"):
        assert {bp.select(tenant, operation=op).backend for op in ops} == {"nodriver"}, tenant
    assert {bp.select("workday:acme.wd1", operation=op).backend for op in ops} == {"playwright"}       # nothing says otherwise
    # a site that signs in through a provider follows the provider - any provider, not Google by name
    db.set_setting("sso.sites", {"generic:jobs.example.com": "google", "generic:careers.example.org": "microsoft"})
    assert bp.select("generic:jobs.example.com", operation="apply").backend == "nodriver"
    assert bp.select("generic:careers.example.org", operation="apply").backend == "playwright"
    # where a sign-in was made is remembered with it, and decides from then on - with no rule at all
    db.set_setting("browser.rules", [])
    db.set_setting("browser.session_made_in", {"idp:microsoft": "nodriver", "idp:google": "nodriver"})
    assert bp.select("generic:careers.example.org", operation="read").backend == "nodriver"
    assert bp.select("generic:www.google.com", operation="apply").reason == "where the sign-in for idp:google was made"
    assert bp.select("generic:www.google.com", operation="apply", override="playwright").backend == "playwright"      # the applicant's choice for one task
    db.set_setting("browser.nodriver_enabled", False)
    assert bp.select("generic:www.google.com", operation="apply").backend == "playwright"


def test_where_a_sign_in_was_made_is_kept_with_it_and_it_is_not_carried_into_the_other_browser(app_env):
    from autoapply import browser, db

    db.set_setting("browser.nodriver_enabled", True)
    db.set_setting("browser.rules", [])
    db.set_setting("identity.share", True)
    google = {"cookies": [{"name": "SID", "value": "x", "domain": ".google.com", "path": "/"}], "origins": []}
    browser._now.backend = "nodriver"                    # as inside open_page() in the ordinary browser
    try:
        browser.write_state("idp:google", google)
    finally:
        browser._now.backend = None
    assert db.get_setting("browser.session_made_in") == {"idp:google": "nodriver"}
    # the automated browser is not shown Google's cookies; the ordinary browser is
    assert browser.with_identities(None, "generic:jobs.example.com", "playwright") is None
    assert [c["name"] for c in browser.with_identities(None, "generic:jobs.example.com", "nodriver")["cookies"]] == ["SID"]
    # a run the applicant sent to the other browser does not replace the sign-in
    browser._now.backend = "playwright"
    try:
        browser.write_state("idp:google", {"cookies": [], "origins": []})
    finally:
        browser._now.backend = None
    assert browser.load_state("idp:google") == google and db.get_setting("browser.session_made_in") == {"idp:google": "nodriver"}
    browser.write_state("idp:google", google, made_in="")          # carried over from another computer: not known any more
    assert db.get_setting("browser.session_made_in") == {}


def test_the_card_names_whose_sign_in_is_missing(app_env):
    """For Google's own careers site the card said "this site supports signing in with Google, where you are signed
    in" and offered "use my Google account" - for Google. What is missing there is Google's session: one card, Google's."""
    from fastapi.testclient import TestClient

    from autoapply import auth, db
    from autoapply.api.main import app
    from autoapply.ats.base import JobRef
    from autoapply.models import Todo

    db.set_setting("accounts.alias", {"generic:www.google.com": "idp:google"})
    db.set_setting("sso.offered", {"generic:www.google.com": ["google"], "generic:jobs.example.com": ["google"]})
    careers = JobRef(ats="generic", tenant="www.google.com", job_id="", url="https://www.google.com/about/careers/applications/jobs/results/1", host="www.google.com")
    other = JobRef(ats="generic", tenant="jobs.example.com", job_id="", url="https://jobs.example.com/p/1", host="jobs.example.com")
    auth.ask_to_sign_in(careers, "Google · Intern", "blocked=login", url="https://accounts.google.com/v3/signin/accountchooser?continue=x", draft_id=45)
    auth.ask_to_sign_in(careers, "Google · Another posting", "blocked=login", url="https://accounts.google.com/v3/signin/accountchooser", draft_id=46)       # the same missing thing: one card
    auth.ask_to_sign_in(other, "Example", "the site asks for an account", url="https://jobs.example.com/login", can_register=True)
    auth.ask_to_sign_in(other.__class__(**{**other.__dict__, "tenant": "apply.example.net", "host": "apply.example.net"}), "Example Net",
                        "The Sign in with Google button led to accounts.google.com, which shows the account as signed out.", url="https://apply.example.net/sso")
    with db.session() as s:
        cards = {t.ref: t.payload for t in s.query(Todo).filter_by(kind="takeover", status="open")}
    assert set(cards) == {"account:idp:google", "account:generic:jobs.example.com"}
    g = cards["account:idp:google"]
    assert (g["tenant_key"], g["provider"], g["can_register"], g["url"]) == ("idp:google", "Google", False, "https://accounts.google.com/")
    assert cards["account:generic:jobs.example.com"]["can_register"] is True
    c = TestClient(app)
    shown = {t["ref"]: t for t in c.get("/api/todos").json() if t["kind"] == "takeover"}
    assert "sso" not in shown["account:idp:google"]                # Google is not offered as a way to sign in to Google


def test_a_site_whose_sign_in_is_a_providers_own_has_nothing_to_choose_or_register(app_env):
    from autoapply import auth, db
    from autoapply.ats.base import JobRef

    db.set_setting("accounts.alias", {"generic:www.google.com": "idp:google"})
    db.set_setting("sso.mode", "auto")
    careers = JobRef(ats="generic", tenant="www.google.com", job_id="", url="https://www.google.com/about/careers/applications/jobs/results/1", host="www.google.com")
    plan = auth.sign_in_plan(careers, ["google", "linkedin"])
    assert (plan["do"], plan["may_register"], plan["offered"]) == ("ask_user", False, []) and "Google's own" in plan["why"]
    # ... and the same when the agent stands on the provider's page working for that site
    at_google = JobRef(ats="generic", tenant="accounts.google.com", job_id="", url="https://accounts.google.com/signin", host="accounts.google.com")
    assert auth.sign_in_plan(at_google, [], also="generic:www.google.com")["do"] == "ask_user"


def test_the_ordinary_browser_knows_when_its_window_is_gone_and_presses_every_key(native_page):
    """Filling a form in the ordinary browser stopped with: "Tab" has no attribute "closed". The question "is the window
    still there" had never been asked of it - reading a form does not ask; waiting for the applicant does."""
    page = native_page
    page.goto("data:text/html," + quote("<title>k</title><input id='a'><input id='b' type='checkbox'><label><input type='radio' name='r' value='x'>X</label>"))
    assert page.is_closed() is False
    page.locator("#a").fill("Vancouver")
    page.locator("#a").press("Backspace")
    page.locator("#a").press("x")                                  # a character key types its character
    page.locator("#a").press("Space")
    assert page.locator("#a").input_value() == "Vancouvex "
    page.locator("#a").clear()
    assert page.input_value("#a") == ""
    with pytest.raises(ValueError, match="Unsupported key"):
        page.keyboard.press("F13")
    # the page's own short forms of what a locator does
    page.fill("#a", "by selector")
    page.check("#b")
    page.check("input[name=r][value=x]")
    assert page.input_value("#a") == "by selector" and page.is_checked("#b") and page.locator("input[name=r]").is_checked()
    page.uncheck("#b")
    assert not page.is_checked("#b") and page.is_visible("#a") and page.locator("#a").is_hidden() is False
    page.close()
    assert page.is_closed() is True


def test_a_profile_keeps_its_own_cookies_over_a_saved_copy(tmp_path):
    """The profile of the ordinary browser carries its cookies from one start to the next. The saved copy of the
    sign-in was written over them at every start - an older session put back over the current one."""
    if importlib.util.find_spec("nodriver") is None:
        pytest.skip("Install the nodriver extra to run native integration tests")
    from autoapply.browser import find_chrome
    from autoapply.nodriver_backend import open_page

    executable = find_chrome()
    if not executable:
        pytest.skip("Chrome or Edge is required")
    profile = tmp_path / "profile"
    cookie = {"name": "SID", "domain": ".example.test", "path": "/", "secure": True, "httpOnly": True, "expires": 4102444800, "sameSite": "Lax"}
    with open_page({"cookies": [{**cookie, "value": "first"}], "origins": []}, headless=True, executable=executable, args=["--no-proxy-server"], profile=profile) as page:
        assert [c["value"] for c in page.context.cookies() if c["name"] == "SID"] == ["first"]          # a new profile takes what was saved
        page.context.add_cookies([{**cookie, "value": "current"}])                                      # ... and the site moves the session on
    saved = {"cookies": [{**cookie, "value": "first"}, {**cookie, "name": "OTHER", "value": "added"}], "origins": []}
    with open_page(saved, headless=True, executable=executable, args=["--no-proxy-server"], profile=profile) as page:
        got = {c["name"]: c["value"] for c in page.context.cookies()}
    assert got.get("SID") == "current" and got.get("OTHER") == "added"


def test_the_ordinary_browser_is_opened_as_a_window_even_where_nobody_looks(app_env, monkeypatch):
    """Hidden, the ordinary browser calls itself HeadlessChrome - not the browser the applicant signed in with. The
    university portal's firewall let the window in and turned every hidden scan away."""
    from contextlib import contextmanager

    from autoapply import browser, db, nodriver_backend

    db.set_setting("browser.nodriver_enabled", True)
    db.set_setting("browser.rules", [{"tenant": "pdportal:ubc", "backend": "nodriver", "operations": ["login"]}])
    monkeypatch.setattr(browser, "find_chrome", lambda: "chrome")
    asked = []

    @contextmanager
    def opened(state, *, headless, executable, args, profile=None):
        asked.append(headless)
        yield object()

    monkeypatch.setattr(nodriver_backend, "open_page", opened)
    monkeypatch.delenv("AUTOAPPLY_ORDINARY_HIDDEN", raising=False)
    with browser.real_open_page("pdportal:ubc", headless=True, url="https://pdportal.apsc.ubc.ca/x", operation="scan"):
        pass
    monkeypatch.setenv("AUTOAPPLY_ORDINARY_HIDDEN", "1")
    with browser.real_open_page("pdportal:ubc", headless=True, url="https://pdportal.apsc.ubc.ca/x", operation="scan"):
        pass
    assert asked == [False, True]


def test_a_scan_the_portals_firewall_turns_away_is_tried_in_a_window_and_then_asks_for_a_sign_in(app_env, monkeypatch):
    from contextlib import contextmanager

    from autoapply import browser, db
    from autoapply.ats.base import NeedsHuman
    from autoapply.models import Todo
    from autoapply.sources import pdportal

    db.set_setting("browser.nodriver_enabled", True)
    pages = []

    class Page:
        def __init__(self, blocked):
            self.blocked, self.url, self.context = blocked, pdportal.POSTINGS, None

        def goto(self, *a, **k): ...

        def title(self):
            return "Just a moment..." if self.blocked else "Co-op postings"

        def inner_text(self, sel, **k):
            return "Verifying you are human" if self.blocked else "Postings"

        def wait_for_timeout(self, ms): ...

        def wait_for_selector(self, sel, **k):
            raise TimeoutError(sel)         # (not signed in: the scan ends there - what matters here is how far it got)

    @contextmanager
    def open_page(tenant, **kw):
        page = Page(blocked=bool(order.pop(0)))
        pages.append(page)
        yield page

    monkeypatch.setattr(browser, "open_page", open_page)
    order = [True, False]                    # hidden: turned away; in a window: let in
    with pytest.raises(NeedsHuman, match="session expired"):
        list(pdportal.scan(set()))
    assert len(pages) == 2 and db.get_setting("browser.visible_sites") == ["pdportal:ubc"]
    order = [True]                           # turned away in a window as well: its pass has run out
    with pytest.raises(NeedsHuman, match="firewall"):
        list(pdportal.scan(set()))
    with db.session() as s:
        cards = [(t.kind, t.ref) for t in s.query(Todo).filter_by(status="open")]
    assert ("takeover", "account:pdportal:ubc") in cards and not any(k == "config" for k, _ in cards)      # not "switch the ordinary browser on": it is on
