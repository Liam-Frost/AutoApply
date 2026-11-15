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
