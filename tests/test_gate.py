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
<form id="signin" class="o"><input id="su" name="email"><input id="sp" type="password"><button type="submit" id="sgo">Submit</button></form>
<form id="otp" class="o"><input id="code" name="otp" autocomplete="one-time-code"><button type="submit" id="cgo">Submit</button></form>
<form id="last" class="o"><label for="agree">I agree to the terms</label><input type="checkbox" id="agree"><button type="submit" id="lgo">Submit</button></form>
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
document.querySelectorAll('form.o').forEach((x) => x.addEventListener('submit', (ev) => ev.preventDefault()));
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
    page.locator("#find").click()                 # a search box whose button is called "Submit"
    assert page.evaluate("() => window.found") == 1 and submitwatch.seen(page)["form"] == "search" and submitwatch.sent(page) is None
    page.locator("#next").click()
    assert submitwatch.sent(page) is None
    page.locator("#icon").click()                 # (as a person, or something that got past the gate, would)
    got = submitwatch.sent(page)
    assert got and got["how"] == "form" and got["by"] == "Submit application" and _counts(page)[0] == 1
    page.locator("#next").click()                 # what came after does not write over it
    assert submitwatch.sent(page)["by"] == "Submit application"


def test_the_last_step_is_told_by_what_the_form_is_for_not_by_how_many_fields_it_has(form):
    """"A search box is a form of one field" - so a form of fewer than three fields was never the application. The last
    step of many applications is one checkbox and Submit: pressed there, nothing was seen, the run ended "filled, not
    submitted" and offered to do it again."""
    from autoapply import submitwatch

    page, _ = form
    page.locator("#su").fill("a@example.com")
    page.locator("#sp").fill("not-a-real-one")
    page.locator("#sgo").click()                  # signing in, by a button called "Submit"
    assert submitwatch.seen(page)["form"] == "sign-in" and submitwatch.sent(page) is None
    page.locator("#code").fill("123456")
    page.locator("#cgo").click()                  # a code from a mail
    assert submitwatch.seen(page)["form"] == "code" and submitwatch.sent(page) is None
    page.locator("#agree").check()
    page.locator("#lgo").click()                  # one checkbox and "Submit": the application
    got = submitwatch.sent(page)
    assert got and got["how"] == "form" and got["by"] == "Submit" and got["form"] == ""


def test_the_plugins_page_asks_however_the_call_is_written_and_whatever_it_was_handed(form):
    """``press(key="Enter")`` was read as ``press("")`` and let through; a page-level ``dispatch_event`` took the
    selector for the event; an element handle, the mouse, the page a locator belongs to were the real ones."""
    from autoapply import gate, submitwatch

    page, _ = form
    g = gate.guarded(page)
    page.locator("#go").scroll_into_view_if_needed()
    at = lambda sel: page.locator(sel).evaluate("(el) => { const r = el.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }")  # noqa: E731
    go = at("#go")
    ways = [lambda: g.locator("#go").press(key="Space"), lambda: g.locator("#n").press(key="Enter"), lambda: g.press("#n", key="Enter"),
            lambda: g.press(selector="#n", key="Enter"), lambda: g.click(selector="#go"), lambda: g.locator("#n").type(text="a\nb"),
            lambda: g.type("#n", text="a\n"), lambda: g.locator("#go").dispatch_event("click"), lambda: g.locator("#f").dispatch_event("submit"),
            lambda: g.locator("#n").page.click("#go"), lambda: [p for p in g.context.pages if p.url == page.url][0].locator("#go").click(),
            lambda: g.locator("button").all()[2].click(), lambda: g.mouse.click(go[0], go[1]), lambda: g.mouse.click(x=go[0], y=go[1])]
    if hasattr(page, "query_selector"):        # what only the program's own browser has
        ways += [lambda: g.query_selector("#go").click(), lambda: g.locator("#go").element_handle().click(), lambda: g.main_frame.click("#go"),
                 lambda: g.dispatch_event("#go", "click"), lambda: g.dispatch_event(selector="#go", type="click"), lambda: g.locator("#go").dispatch_event(type="click"),
                 lambda: g.wait_for_selector("#icon").press("Enter"), lambda: g.mouse.down(), lambda: (g.mouse.move(go[0], go[1]), g.mouse.down())]
    page.locator("#n").focus()
    ways += [lambda: g.keyboard.press(key="Enter"), lambda: g.keyboard.type(text="a\nb")]
    for i, press in enumerate(ways):
        with pytest.raises(gate.Refused):
            press()
            raise AssertionError(f"way {i} was let through")
    assert _counts(page) == [0, 0] and page.inner_text("#state") == "open" and submitwatch.sent(page) is None
    # and what is not the control that sends is pressed as before, written either way
    g.locator("#next").press(key="Space")
    nxt = at("#next")
    g.mouse.click(nxt[0], nxt[1])
    g.locator("#n").fill(value="Liam")
    assert _counts(page) == [0, 2] and g.locator("#n").input_value() == "Liam"


def test_a_form_sent_while_it_was_only_being_read_is_not_read_again_on_a_card(pipeline, monkeypatch):  # noqa: F811
    """It was put where it belongs - "outcome not known" - and then handed to the branch for pages that do not work: a
    card "let the program try again", whose button read the form again, moved the application back to "being read" and
    left nothing between it and a second submission."""
    from fastapi.testclient import TestClient

    from autoapply import drafts, lifecycle, tasks
    from autoapply.api.main import app
    from autoapply.ats.base import SentEarly
    from autoapply.models import UNKNOWN, Job, Task, Todo

    did = drafts.build(pipeline["job_id"])      # a draft is there, and work on it waits in the queue
    with db.session() as s:
        app_id = s.get(Job, pipeline["job_id"]).application.id
    waiting = tasks.enqueue_later("scout", ref=f"draft:{did}", payload={"draft_id": did}, minutes=60)
    real = drafts.recon

    def sent_while_reading(*a, **k):
        raise SentEarly({"how": "form", "sends": True, "by": "Submit application"})

    monkeypatch.setattr(drafts, "recon", sent_while_reading)
    tid = tasks.enqueue("recon", ref=f"job:{pipeline['job_id']}", payload={"job_id": pipeline["job_id"], "instructions": "again"})
    tasks.drain()
    monkeypatch.setattr(drafts, "recon", real)
    with db.session() as s:
        a = s.get(Job, pipeline["job_id"]).application
        cards = [(t.kind, t.title.split("：")[-1], (t.payload or {}).get("retry_task")) for t in s.query(Todo).filter_by(status="open")]
        t = s.get(Task, tid)
        assert a.status == UNKNOWN and "读取过程中被提交" in a.last_event
        assert (t.status, t.result["status"]) == ("done", UNKNOWN)                        # not "waiting for you" with a way to run it again
        assert s.get(Task, waiting).status == "cancelled"                              # what waited in the queue does not run on it either
    assert cards == [("submit", "提交结果待确认", None)]
    c = TestClient(app)
    assert c.post(f"/api/tasks/{tid}/retry").status_code == 409
    # whatever else asks: reading it again, a comment, an answer changed, an approval - it stays where it is
    with pytest.raises(drafts.OutcomeUnknown):
        drafts.build(pipeline["job_id"])
    for to in ("recon", "revising", "draft_ready", "approved", "failed", "needs_human"):
        assert lifecycle.move(app_id, to, source="draft") is False
    tasks.enqueue("recon", ref=f"job:{pipeline['job_id']}", payload={"job_id": pipeline["job_id"]})
    tasks.drain()
    with db.session() as s:
        assert s.get(Job, pipeline["job_id"]).application.status == UNKNOWN and pipeline["driver"].submits == 0
    # the applicant's word that it was not sent is what takes it on
    with db.session() as s:
        s.get(Job, pipeline["job_id"]).application.drafts[-1].review_status = "approved"
    assert c.post(f"/api/drafts/{did}/execute", json={}).status_code == 409
    assert c.post(f"/api/drafts/{did}/execute", json={"not_submitted": True}).status_code == 200
    with db.session() as s:
        assert s.get(Job, pipeline["job_id"]).application.status == "approved"


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
