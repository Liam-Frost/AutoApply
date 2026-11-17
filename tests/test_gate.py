"""No tool of an agent sends an application.

The reading agent's click tool refused a button whose text says "Submit" - and that was all. A button named by an
``aria-label`` passed; the tools that open a list or type clicked whatever selector they were given; the key tool
pressed Space on a focused Submit button, and Enter in a field as long as some list was open somewhere on the page.

These run in whichever browser the test run uses (AUTOAPPLY_TEST_BROWSER): the gate asks the page, and both pages
have to answer alike.
"""
import pytest

from autoapply import db

from test_pipeline import pipeline  # noqa: F401  (the fixture: a real form in a real browser)

FORM = """<main><h1>Application</h1>
<form id="f">
  <label for="n">Name</label><input id="n">
  <label for="e">E-mail</label><input id="e" type="email">
  <label for="c">City</label><input id="c" role="combobox" aria-expanded="false" aria-controls="lb" autocomplete="off">
  <ul id="lb" role="listbox" hidden><li role="option" id="o1">Vancouver</li><li role="option" id="o2">Victoria</li></ul>
  <label for="t">Why us</label><textarea id="t"></textarea>
  <label for="k">I agree</label><input type="checkbox" id="k">
  <button type="button" id="open">Show cities</button>
  <button type="submit" id="next">Save and continue</button>
  <button type="submit" id="go"><span id="inner">Submit application</span></button>
  <button type="submit" id="icon" aria-label="Submit application"><svg width="10" height="10"></svg></button>
  <button type="submit" id="lbld" aria-labelledby="cap"><span>&rarr;</span></button><span id="cap">Finish</span>
  <div role="button" id="pic" tabindex="0"><img alt="Send application" src="data:image/gif;base64,R0lGODlhAQABAAAAACw="></div>
</form>
<p id="state">open</p>
<div id="elsewhere" role="listbox"><div role="option">a list that is open somewhere else on the page</div></div>
<form id="search"><input id="q" name="q"><button type="submit" id="find">Submit</button></form>
</main>
<script>
window.sent = 0; window.nexts = 0; window.found = 0;
const f = document.getElementById('f');
f.addEventListener('submit', (ev) => {
  ev.preventDefault();
  if (ev.submitter && ev.submitter.id === 'next') { window.nexts++; return; }
  window.sent++; document.getElementById('state').textContent = 'SENT';
});
document.getElementById('pic').addEventListener('click', () => f.requestSubmit(document.getElementById('go')));
document.getElementById('search').addEventListener('submit', (ev) => { ev.preventDefault(); window.found++; });
document.getElementById('open').addEventListener('click', () => {
  document.getElementById('lb').hidden = false; document.getElementById('c').setAttribute('aria-expanded', 'true'); document.getElementById('c').focus();
});
document.getElementById('c').addEventListener('keydown', (ev) => {
  if (ev.key === 'Enter' && !document.getElementById('lb').hidden) { ev.preventDefault(); ev.target.value = 'Vancouver'; document.getElementById('lb').hidden = true; ev.target.setAttribute('aria-expanded', 'false'); }
});
</script>"""


@pytest.fixture()
def form(app_env, tmp_path):
    from autoapply import browser, generic, submitwatch

    html = tmp_path / "form.html"
    html.write_text("<!doctype html><html><body>" + FORM + "</body></html>", encoding="utf-8")
    with browser.open_page() as page:
        page.goto(html.as_uri())
        submitwatch.install(page)
        tools = {t.name: t.fn for t in generic.l0_tools(page, tmp_path, {}, files={"cv.pdf": str(tmp_path / "cv.pdf")})}
        yield page, tools


def _counts(page):
    return page.evaluate("() => [window.sent, window.nexts]")


def test_the_control_that_sends_is_refused_whatever_it_is_called_by_and_whichever_tool_would_press_it(form):
    from autoapply import gate, submitwatch

    page, tools = form
    for sel in ("#go", "#inner", "#icon", "#lbld", "#pic"):      # by its text, from inside it, by aria-label, by aria-labelledby, by an image's alt
        with pytest.raises(gate.Refused, match="sends the application"):
            tools["click"](selector=sel)
    with pytest.raises(gate.Refused):
        tools["click"](text="Submit application")
    # the other tools that begin with a click on what they are given
    for name, kw in (("options", {"selector": "#go"}), ("select", {"selector": "#icon", "option": "x"}), ("type_keys", {"text": "x", "selector": "#go"}),
                     ("check", {"selector": "#go"}), ("upload", {"selector": "#icon", "file_name": "cv.pdf"})):
        with pytest.raises(gate.Refused):
            tools[name](**kw)
    # keys: Space and Enter on it, named or merely focused
    for key in ("Space", "Enter"):
        with pytest.raises(gate.Refused, match="sends the application"):
            tools["press"](key=key, selector="#icon")
    page.locator("#go").focus()
    with pytest.raises(gate.Refused, match="sends the application"):
        tools["press"](key="Space")
    # Enter in a field sends its form - a list that is open somewhere else on the page is no licence
    for kw in ({"key": "Enter", "selector": "#n"}, {"key": "Enter", "selector": "#e"}):
        with pytest.raises(gate.Refused, match="Enter in a field sends the form"):
            tools["press"](**kw)
    page.locator("#n").focus()
    with pytest.raises(gate.Refused):
        tools["press"](key="Enter")
    with pytest.raises(gate.Refused):
        tools["type_keys"](text="Liam\n", selector="#n")       # a line break typed into a field is an Enter
    assert _counts(page) == [0, 0] and page.inner_text("#state") == "open" and submitwatch.sent(page) is None


def test_what_a_form_is_worked_with_still_works(form):
    from autoapply import submitwatch

    page, tools = form
    assert "clicked" in tools["click"](selector="#next") and _counts(page) == [0, 1]       # a submit-type button that goes on a step
    tools["press"](key="Space", selector="#next")
    assert _counts(page) == [0, 2]
    tools["type_keys"](text="Liam", selector="#n")
    tools["press"](key="Tab", selector="#n")
    assert page.input_value("#n") == "Liam"
    tools["click"](selector="#open")                                  # the list of the box is open, the focus is in the box: Enter takes the entry
    tools["press"](key="Enter")
    assert page.input_value("#c") == "Vancouver"
    tools["type_keys"](text="line one\nline two", selector="#t")       # in a text area a line break is a line break
    assert page.input_value("#t") == "line one\nline two"
    tools["check"](selector="#k")
    assert page.locator("#k").is_checked()
    # going on a step sends a form too; the watcher tells it from the application going out
    seen = submitwatch.seen(page)
    assert seen and seen["how"] == "form" and seen["sends"] is False and submitwatch.sent(page) is None and _counts(page)[0] == 0


def test_the_page_a_learned_plugin_gets_asks_before_it_acts(form):
    from autoapply import gate, learned

    page, _ = form
    g = gate.guarded(page)
    for press in (lambda: g.locator("#go").click(), lambda: g.locator("#icon").first.click(), lambda: g.locator("button").nth(3).click(),
                  lambda: g.get_by_role("button", name="Submit application").first.click(), lambda: g.click("#pic"),
                  lambda: g.locator("#n").press("Enter"), lambda: g.locator("#go").press("Space"), lambda: g.locator("#f").locator("#lbld").click()):
        with pytest.raises(gate.Refused):
            press()
    page.locator("#n").focus()
    with pytest.raises(gate.Refused):
        g.keyboard.press("Enter")
    with pytest.raises(gate.Refused):
        g.keyboard.type("a\nb")
    # everything else is the page's own
    g.locator("#n").fill("Liam")
    g.locator("#next").click()
    assert g.locator("#n").input_value() == "Liam" and g.inner_text("#state") == "open" and _counts(page) == [0, 1]
    assert gate.guarded(g) is g and gate.real(g) is page
    # script inside the page cannot be asked what it lands on: a plugin that carries such script is not learned
    ok = "def set_value(page, q, value, w):\n    page.locator(q.locator['selector']).click()\n    return True\n"
    learned.check_code(ok)
    for script in ("document.querySelector('form').submit()", "document.getElementById('go').click()", "f.requestSubmit()", "b.dispatchEvent(new MouseEvent('click'))"):
        bad = f"def set_value(page, q, value, w):\n    page.evaluate(\"() => {script}\")\n    return True\n"
        with pytest.raises(learned.Refused, match="script inside the page"):
            learned.check_code(bad)
    assert learned._guarded(page) is not page


def test_what_gets_past_is_seen_and_told_from_a_step_or_a_search(form):
    """The net under all of the above: the page itself says when the application was sent."""
    from autoapply import submitwatch

    page, _ = form
    page.locator("#q").fill("intern")
    page.locator("#find").click()                 # a search box whose button is called "Submit": a form of one field
    assert page.evaluate("() => window.found") == 1 and submitwatch.seen(page)["sends"] is True and submitwatch.sent(page) is None
    page.locator("#next").click()
    assert submitwatch.sent(page) is None
    page.locator("#icon").click()                 # (as a person, or something that got past the gate, would)
    got = submitwatch.sent(page)
    assert got and got["how"] == "form" and got["by"] == "Submit application" and _counts(page)[0] == 1
    page.locator("#next").click()                 # what came after does not write over it
    assert submitwatch.sent(page)["by"] == "Submit application"


def test_an_application_sent_while_it_was_being_filled_is_not_sent_again_and_not_called_a_failure(pipeline, monkeypatch):  # noqa: F811
    """Something got past the gate in the middle of a run. The run then failed on whatever that broke - "the fields are
    not there" - and the card offered to fill the form in again."""
    from autoapply import drafts, executor, tasks
    from autoapply.models import UNKNOWN, Job, Run, Todo

    monkeypatch.setattr(executor, "_judge", lambda seen: None)
    real = pipeline["driver"].fill_page

    def fill_and_send(page, schema, i, answers):
        out = real(page, schema, i, answers)
        page.evaluate("() => document.getElementById('f').requestSubmit(document.querySelector('button[type=submit]'))")      # not through any tool
        return out

    monkeypatch.setattr(pipeline["driver"], "fill_page", fill_and_send)
    did = drafts.build(pipeline["job_id"])
    drafts.approve(did)
    tasks.drain()
    with db.session() as s:
        a = s.get(Job, pipeline["job_id"]).application
        cards = [(t.kind, t.title.split("：")[1]) for t in s.query(Todo).filter_by(status="open")]
        steps = [st["op"] for st in s.query(Run).filter_by(kind="execute").order_by(Run.id.desc()).first().steps]
        assert a.status == UNKNOWN and "填写过程中被提交" in a.last_event
    assert cards == [("submit", "提交结果待确认")] and "sent_early" in steps
    assert pipeline["driver"].submits == 0                      # the program did not press Submit after that
