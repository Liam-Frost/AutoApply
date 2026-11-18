"""The two browsers do the same thing with the same input.

A site's work is done in the browser its sign-in lives in (browser_policy): the automated one (Playwright) or the
ordinary one (the adapter in nodriver_backend.py, which answers to the same names). Answering to the same names is not
doing the same thing - how a selector is read, what counts as visible, which events a page hears when a box is filled.
So each test here is one piece of what the program's own code asks of a page - the selector shapes it writes, the
frames it looks for, boxes the page itself is in charge of, files, windows, the mouse - written once and run in both,
against the same expected answer. (Not the whole of Playwright: what is used. A way of asking that the program starts
to use belongs here, in both columns, before it is relied on in the ordinary browser.)
"""

import importlib.util
import json
from pathlib import Path

import pytest

CONTRACT = Path(__file__).parent / "fixtures" / "contract.html"


@pytest.fixture(params=["playwright", "nodriver"])
def page(request, app_env, monkeypatch):
    from autoapply import browser, db
    from autoapply.browser import find_chrome

    if request.param == "nodriver":
        if importlib.util.find_spec("nodriver") is None:
            pytest.skip("nodriver is not installed")
        if not find_chrome():
            pytest.skip("Chrome or Edge is required")
        db.set_setting("browser.nodriver_enabled", True)
        monkeypatch.setenv("AUTOAPPLY_ORDINARY_HIDDEN", "1")
    with browser.open_page(backend=request.param) as p:
        p.goto(CONTRACT.as_uri())
        p.wait_for_selector("#later", state="attached")
        yield p


def _state(page, out):
    return page.locator(f"#{out}").inner_text()


def test_the_selector_shapes_the_program_writes(page):
    n = lambda sel: page.locator(sel).count()  # noqa: E731
    # what is shown, and what is merely there
    assert (n(".opt"), n(".opt:visible"), n(".msg"), n(".msg:visible"), n(".btn:visible")) == (3, 2, 2, 1, 2)
    assert page.locator(".opt").locator("visible=true").count() == 2
    assert page.locator(".opt:visible").all_inner_texts() == ["Canada", "Cape Verde"]
    # a list of selectors, attributes by a part of their value
    assert n("#city, #combo, #nothing") == 2 and n("[data-automation-id*='city']") == 1 and n("a[data-ui^='apply'], a[href$='#x']") == 1
    assert n("button:has-text('Save and continue')") == 1 and n("button:has-text('save')") == 2      # (case does not matter; the hidden one counts until :visible is asked)
    assert n("button:has-text('save'):visible") == 1
    # from a control to what is around it
    city = page.locator("#city")
    assert city.locator("xpath=ancestor::*[contains(@class,'fieldEntry') or contains(@class,'_field')][1]").get_attribute("id") == "fe1"
    assert page.locator("#combo").locator("xpath=ancestor::*[contains(@class,'fieldEntry') or contains(@class,'_field')][1]").get_attribute("id") == "fe2"
    assert page.locator("#fe1 label").locator("xpath=following::input[@role='combobox'][1]").get_attribute("id") == "combo"
    assert page.locator("#auth_no").locator("xpath=ancestor::fieldset[1]").get_attribute("id") == "fs"
    assert city.locator("xpath=ancestor::*[.//button][1]").get_attribute("id") == "fe1"
    # text
    assert n("text=/no longer (open|accepting)/i") == 1 and page.locator("text=/no longer (open|accepting)/i").first.is_visible()
    assert page.get_by_text("Hidden message", exact=True).count() == 1 and not page.get_by_text("Hidden message", exact=True).first.is_visible()
    # by what a control is, and what it is called
    assert page.get_by_role("button", name="Save and continue", exact=True).count() == 1
    assert page.get_by_role("button", name="Close dialog").count() == 1                 # an aria-label is its name
    assert page.locator("#opts").get_by_role("option").count() == 2                      # roles are of what is shown
    assert page.get_by_role("combobox", name="Country search").get_attribute("id") == "combo"
    assert page.get_by_label("City", exact=True).input_value() == "Vancouver"
    # narrowing, either-or, one of several
    opts = page.locator(".opt")
    assert opts.filter(has_text="Cape").count() == 1 and opts.filter(has_text="ca").count() == 2
    assert page.locator("div").filter(has=page.locator("#combo")).last.get_attribute("id") == "fe2"
    assert page.locator("#nothing").or_(page.locator("#pick")).first.inner_text() == "Pick"
    assert (opts.nth(1).inner_text(), opts.first.inner_text(), opts.last.text_content().strip()) == ("Cape Verde", "Canada", "Chad")
    assert [o.inner_text() for o in page.locator(".opt:visible").all()] == ["Canada", "Cape Verde"]
    assert page.locator(".opt").evaluate_all("els => els.map(e => e.className)") == ["opt", "opt", "opt hidden"]
    assert page.locator("#lnk").get_attribute("data-ui") == "apply-button" and page.locator("#lnk").get_attribute("nothing") is None
    # waiting for what comes later
    page.locator("#later").wait_for(state="visible", timeout=5000)
    assert page.locator("#later").is_visible() and page.locator("#later").inner_text() == "ready"
    page.wait_for_function("() => document.getElementById('later').textContent === 'ready'")


def test_frames_as_the_program_looks_for_them(page):
    """A challenge that is shown is one the applicant has to deal with; one that is only in the page is not."""
    n = lambda sel: page.locator(sel).count()  # noqa: E731
    assert (n("iframe"), n("iframe[src*=recaptcha]"), n("iframe[src*=recaptcha]:visible"), n("iframe[src*=hcaptcha]:visible")) == (2, 1, 0, 1)
    assert n("iframe[src*=recaptcha]:visible, iframe[src*=hcaptcha]:visible, iframe[title*=challenge]:visible") == 1
    assert page.locator("iframe[src*=recaptcha], iframe[src*=hcaptcha]").locator("visible=true").count() == 1
    assert page.evaluate("() => [...document.querySelectorAll('iframe')].map(i => i.src).find(s => /hcaptcha/.test(s))") == "about:blank?hcaptcha=1"


def test_a_box_the_page_is_in_charge_of_hears_what_is_put_into_it(page):
    """Setting a box's value behind the page's back fills nothing: the page puts its own state back."""
    name = page.locator("#name")
    name.fill("Liam Frost")
    page.wait_for_timeout(150)                                # a few renders
    assert (name.input_value(), _state(page, "name_state")) == ("LIAM FROST", "LIAM FROST")
    name.fill("")
    page.wait_for_timeout(150)
    assert (name.input_value(), _state(page, "name_state")) == ("", "")
    name.press_sequentially("ab")
    page.wait_for_timeout(150)
    assert (name.input_value(), _state(page, "name_state")) == ("AB", "AB")
    name.clear()
    page.wait_for_timeout(150)
    assert name.input_value() == ""
    # typing is keys, one by one; filling is not
    code = page.locator("#code")
    code.press_sequentially("AB12")
    heard = json.loads(_state(page, "code_log"))
    assert (heard["keydown"], heard["keyup"], heard["input"], code.input_value()) == (4, 4, 4, "AB12")
    code.press("Enter")
    assert json.loads(_state(page, "code_log"))["enter"] == 1
    code.fill("XY")
    heard2 = json.loads(_state(page, "code_log"))
    assert code.input_value() == "XY" and heard2["input"] > heard["input"] and heard2["keydown"] == heard["keydown"] + 1
    code.blur()
    assert json.loads(_state(page, "code_log"))["change"] >= 1
    # the keyboard goes to whatever has the focus
    name.focus()
    page.keyboard.press("Tab")
    assert page.evaluate("() => document.activeElement.id") == "code"
    code.fill("")
    page.keyboard.type("Q7")
    assert code.input_value() == "Q7"
    page.keyboard.insert_text("zz")
    assert code.input_value() == "Q7zz"
    # a tick box and a list tell the page
    box = page.locator("#agree")
    box.set_checked(True)
    assert box.is_checked() and _state(page, "agree_state") == "yes"
    box.set_checked(True)                                     # already so: nothing happens
    assert box.is_checked() and _state(page, "agree_state") == "yes"
    box.uncheck()
    assert not box.is_checked() and _state(page, "agree_state") == "no"
    page.get_by_role("checkbox", name="I agree").check()
    assert _state(page, "agree_state") == "yes"
    level = page.locator("#level")
    level.select_option(label="Senior")
    assert (level.input_value(), _state(page, "level_state")) == ("sr", "sr")
    level.select_option("jr")
    assert (level.input_value(), _state(page, "level_state")) == ("jr", "jr")
    page.locator("#bio").fill("line one\nline two")
    assert (page.locator("#bio").input_value(), _state(page, "bio_state")) == ("line one\nline two", "17")
    page.locator("#auth_no").check()
    assert page.locator("#auth_no").is_checked() and not page.locator("#auth_yes").is_checked()


def test_a_file_is_given_to_a_field_and_through_the_window_that_asks_for_one(page, tmp_path):
    cv = tmp_path / "Resume Liam.pdf"
    cv.write_bytes(b"%PDF-1.4 contract")
    page.locator("#file").set_input_files(str(cv))
    assert _state(page, "file_state") == "Resume Liam.pdf:17" and page.locator("#file").evaluate("e => e.files.length") == 1
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name="Choose a file").click()
    chooser.value.set_files(str(cv))
    page.wait_for_function("() => document.getElementById('hidden_state').textContent !== ''")
    assert _state(page, "hidden_state") == "Resume Liam.pdf:17"


def test_a_window_the_page_opens_is_another_page(page):
    with page.context.expect_page() as opened:
        page.get_by_role("button", name="Open window").click()
    assert opened.value.url == "about:blank"
    with page.context.expect_page() as tab:
        page.locator("#blank").click()
    assert tab.value.url == "about:blank"
    assert page.title() == "Contract page" and page.locator("#city").input_value() == "Vancouver"      # the page that opened them is still the page


def test_the_mouse_events_and_what_is_far_down_the_page(page):
    page.locator("#count").click()
    page.locator("#count").dispatch_event("click")
    assert _state(page, "count_state") == "2"
    at = page.evaluate("() => { const r = document.getElementById('count').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2] }")
    page.mouse.click(at[0], at[1])
    assert _state(page, "count_state") == "3"
    page.locator("#hover").hover()
    assert int(_state(page, "hover_state")) >= 1
    far = page.locator("#far")
    assert page.evaluate("() => document.getElementById('far').getBoundingClientRect().top > innerHeight")      # not on the screen yet
    far.scroll_into_view_if_needed()
    assert page.evaluate("() => { const r = document.getElementById('far').getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight }")
    far.click()
    assert _state(page, "far_state") == "1"
    page.locator("#pick").click()
    assert page.locator("#city").input_value() == "Picked"
    assert page.content().count("<h1>Contract page</h1>") == 1 and page.title() == "Contract page"
