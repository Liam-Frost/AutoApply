"""Routing and native browser regressions (all pages are local fixtures)."""

import importlib.util
from pathlib import Path
from urllib.parse import quote

import pytest


def test_routing_precedence_and_domain_boundaries(app_env):
    from autoapply import browser_policy, db

    assert browser_policy.select("pdportal:ubc").backend == "playwright"
    db.set_setting("browser.nodriver_enabled", True)
    assert browser_policy.select("pdportal:ubc").backend == "nodriver"
    assert browser_policy.select(None, "https://accounts.google.com", "login").backend == "nodriver"
    assert browser_policy.select(None, "https://accounts.google.com.evil.example", "login").backend == "playwright"
    assert browser_policy.select(None, "https://example.com/?url=accounts.google.com", "login").backend == "playwright"
    assert browser_policy.select(None, "https://accounts.google.com", "scan").backend == "playwright"
    assert browser_policy.select("pdportal:ubc", override="playwright").backend == "playwright"
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
