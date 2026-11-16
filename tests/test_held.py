"""A control that shows less than it holds: a list of phone codes whose button reads "+1" for every "+1" country."""

from __future__ import annotations

import pytest

from autoapply.ats import widgets as w
from autoapply.ats.base import DriverError

# The control as Meta's application form has it: a button that opens a list; each entry is a code and a country on
# two lines; once one is chosen the button shows the code alone.
FORM = """<label for="b">Code</label>
<button id="b" role="combobox" aria-label="Code" type="button" onclick="document.getElementById('l').hidden = !document.getElementById('l').hidden">Select</button>
<div id="l" role="listbox" hidden>
  <div role="option" __MARK_US__ onclick="pick(this)"><span>+1</span><br><span>United States</span></div>
  <div role="option" onclick="pick(this)"><span>+1</span><br><span>Canada</span></div>
  <div role="option" onclick="pick(this)"><span>+1</span><br><span>Bahamas</span></div>
  <div role="option" onclick="pick(this)"><span>+44</span><br><span>United Kingdom</span></div>
</div>
<script>
window.MARKS = __MARKS__;
window.pick = function (o) {
  if (MARKS) { document.querySelectorAll('[role=option]').forEach(x => x.removeAttribute('aria-selected')); o.setAttribute('aria-selected', 'true'); }
  document.getElementById('b').innerText = o.querySelector('span').innerText;
  document.getElementById('l').hidden = true;
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') document.getElementById('l').hidden = true; });
</script>"""


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_default_timeout(5000)
        yield pg
        b.close()


def form(page, marks=True, us_chosen=False):
    page.set_content(FORM.replace("__MARKS__", "true" if marks else "false").replace("__MARK_US__", 'aria-selected="true"' if us_chosen else ""))
    if us_chosen:
        page.evaluate("document.getElementById('b').innerText = '+1'")
    return page.locator("#b")


def test_what_showing_a_part_means():
    assert w.shows_part("+1", "+1 Canada") and w.shows_part("+1", "+1\nCanada") and w.shows_part("Canada", "+1 / Canada")
    assert not w.shows_part("+44", "+1 Canada")             # something else
    assert not w.shows_part("+1 Canada", "+1 Canada")       # all of it: that is equal, not a part
    assert not w.shows_part("", "+1 Canada") and not w.shows_part("Select", "+1 Canada")


def test_choosing_an_entry_whose_button_shows_only_its_code_is_not_a_failure(page):
    button = form(page)
    assert w.values_equal(w.workday_listbox(page, button, "+1 Canada"), "+1 Canada")       # it used to raise "dropdown did not change"
    assert button.inner_text() == "+1"
    assert w.values_equal(w.held_choice(page, button), "+1 Canada")                         # the list says which "+1"
    assert page.locator("#l").is_hidden()                                                   # asked, and closed again
    assert w.values_equal(w.workday_listbox(page, button, "+44 United Kingdom"), "+44 United Kingdom")


def test_a_list_that_marks_another_entry_did_not_take_the_choice(page):
    button = form(page)
    page.evaluate("window.pick = (o) => { document.getElementById('b').innerText = '+1'; document.getElementById('l').hidden = true; "
                  "document.querySelectorAll('[role=option]')[0].setAttribute('aria-selected', 'true'); }")      # whatever is clicked, it takes the first
    with pytest.raises(DriverError, match="another entry"):
        w.workday_listbox(page, button, "+1 Canada")


def test_a_list_that_marks_nothing_is_taken_at_the_click(page):
    button = form(page, marks=False)
    assert w.held_choice(page, button) is None
    assert w.values_equal(w.workday_listbox(page, button, "+1 Canada"), "+1 Canada")


def test_the_read_back_asks_the_list_instead_of_calling_it_a_difference(page):
    from autoapply.ats.base import FormSchema, Question
    from autoapply.ats.generic_driver import GenericDriver
    from autoapply.executor import _held, _not_vouched

    schema = FormSchema(ats="generic", url="https://x", pages=["p"], questions=[Question(id="#b", label="Code", type="select", options=["+1 United States", "+1 Canada"], page=0)])
    driver = GenericDriver(schema)
    button = form(page)
    w.workday_listbox(page, button, "+1 Canada")
    bad = [{"id": "#b", "label": "Code", "expected": "+1 Canada", "actual": "+1"}]
    assert _held(driver, page, schema, bad) == []                                           # the list holds the approved entry

    form(page, us_chosen=True)                                                              # "+1" as well - of another country
    (still,) = _held(driver, page, schema, bad)
    assert w.values_equal(still["actual"], "+1 United States") and still["expected"] == "+1 Canada"      # a difference, and now it says which

    form(page, marks=False)
    page.locator("#b").click()
    page.locator("[role=option]").nth(1).click()
    assert _held(driver, page, schema, bad) == bad                                          # the list does not say: not settled here
    assert _not_vouched(bad, ["#b"]) == [] and _not_vouched(bad, []) == bad                 # the agent's word, for exactly that field
    other = [{"id": "#b", "label": "Code", "expected": "+1 Canada", "actual": "+44"}]
    assert _held(driver, page, schema, other) == other and _not_vouched(other, ["#b"]) == other
