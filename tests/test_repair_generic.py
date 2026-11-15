"""Agent takeover of a page the driver failed on, the selector-replay driver for
agent-mapped forms, and DOM fixture regression. Real browser, model stubbed."""

import json

import pytest

from fakes import FORM
from test_pipeline import _status, pipeline  # noqa: F401 - fixture


def _agent_that_fixes(log):
    """A stand-in model: tries to submit (must be refused), then sets the approved values with the tools."""

    def agent(goal, tools, *, system, max_steps=60, on_step=None):
        from autoapply import llm

        t = {x.name: x for x in tools}
        log["tools"] = sorted(t)
        log["goal"] = goal
        try:
            t["click"].fn(text="Submit application")
            log["submit_refused"] = False
        except PermissionError:
            log["submit_refused"] = True
        try:
            t["upload"].fn(selector="#resume", file_name="../../secrets.txt")
            log["foreign_upload_refused"] = False
        except PermissionError:
            log["foreign_upload_refused"] = True
        t["fill"].fn(selector="#first_name", value="Liam")
        t["fill"].fn(selector="#email", value="liam@example.com")
        t["select"].fn(selector="#auth", option="Yes")
        t["select"].fn(selector="#sponsor", option="Yes")
        t["upload"].fn(selector="#resume", file_name="Liam_Resume.pdf")
        t["check"].fn(selector="#consent", checked=True)
        t["done"].fn(fixed=["first_name", "email", "auth", "sponsor", "resume", "consent"], unfixed=[],
                     cause="The authorization dropdown is a native select, not a custom listbox.", suggestion="Use select_native for #auth.")
        return llm.AgentResult(final_text="done", steps=[{"tool": "done"}])

    return agent


def test_repair_completes_page_and_proposes_patch(pipeline, monkeypatch):  # noqa: F811
    from autoapply import db, drafts, executor, fixtures, llm, tasks
    from autoapply.models import Run, Todo

    log = {}
    monkeypatch.setattr(llm, "agent", _agent_that_fixes(log))
    waits = []

    def user_clicks_submit(driver, page, title, app_id, draft_id=None, **kw):  # the visible window; the user checks and submits
        waits.append(title)
        driver.submit(page)
        return {"status": "submitted", "evidence": driver.confirmation(page)}

    monkeypatch.setattr(executor, "_wait_for_manual_submit", user_clicks_submit)
    did = drafts.build(pipeline["job_id"])
    drafts.approve(did)
    pipeline["driver"].break_field = "auth"  # the driver now fails on this control
    tasks.drain()
    status, evidence, _ = _status(pipeline["job_id"])
    assert status == "submitted" and "REF-123" in evidence["text"]
    # a run the agent had to rescue is never auto-submitted: it is repeated in a visible window for the user
    assert len(waits) == 1 and pipeline["driver"].submits == 1
    assert log["submit_refused"] and log["foreign_upload_refused"]
    assert "goto" not in log["tools"] and "finish" not in log["tools"]  # cannot leave the page or redefine the form
    assert "approved value='Yes'" in log["goal"]
    with db.session() as s:
        first, second = s.query(Run).filter_by(kind="execute").order_by(Run.id).all()
        assert "submit" not in [x["op"] for x in first.steps]
        ops = [x["op"] for x in second.steps]
        assert ops.index("repair") < ops.index("read_back")
        t = s.query(Todo).filter_by(kind="driver_patch", status="open").one()
        assert "native select" in t.body and t.payload["report"]["suggestion"]
        assert t.payload["fixture"].endswith(".html")
    # the repaired page and the verified page are both kept as regression fixtures
    res = fixtures.run_all()
    assert res["fixtures"] >= 2 and res["failed"] == 0, res


def test_repair_cannot_rescue_a_wrong_value(pipeline, monkeypatch):  # noqa: F811
    """If the agent says it fixed the page but the values still differ from the draft, its word does not count:
    nothing is submitted, and the difference goes to the user in the visible window."""
    from autoapply import drafts, executor, llm, tasks

    def lazy_agent(goal, tools, *, system, max_steps=60, on_step=None):
        t = {x.name: x for x in tools}
        t["done"].fn(fixed=["email"], unfixed=[], cause="c", suggestion="s")
        return llm.AgentResult(final_text="done")

    handed = {}

    def window_closed_without_submitting(driver, page, title, app_id, draft_id=None, **kw):
        handed.update(kw)
        return {"status": "ready_to_submit", "error": "window closed"}

    monkeypatch.setattr(llm, "agent", lazy_agent)
    monkeypatch.setattr(executor, "_wait_for_manual_submit", window_closed_without_submitting)
    did = drafts.build(pipeline["job_id"])
    drafts.approve(did)
    pipeline["driver"].corrupt = "email"
    tasks.drain()
    status, _, _ = _status(pipeline["job_id"])
    assert status == "ready_to_submit" and pipeline["driver"].submits == 0
    assert any(x["kind"] == "fix" and "mail" in x["label"].lower() for x in handed["leftovers"])


def test_repair_off_or_no_model_keeps_the_driver_error(pipeline):  # noqa: F811
    from autoapply import drafts, tasks

    did = drafts.build(pipeline["job_id"])
    drafts.approve(did)
    pipeline["driver"].break_field = "auth"
    tasks.drain()  # no model in tests -> repair unavailable
    status, _, event = _status(pipeline["job_id"])
    assert status == "failed" and "unexpected widget" in event and pipeline["driver"].submits == 0


def _agent_schema():
    from autoapply.ats.base import FormSchema, Question

    def q(sel, label, typ, req=True, opts=None):
        return Question(id=sel, label=label, type=typ, required=req, options=opts or [], locator={"selector": sel})

    return FormSchema(ats="someats", tenant="acme", url=FORM.as_uri(), source="agent", pages=["Application"], questions=[
        q("#first_name", "First Name", "text"), q("#email", "Email", "text"),
        q("#auth", "Are you legally authorized to work in Canada?", "select", opts=["Yes", "No"]),
        q("#resume", "Resume/CV", "file"), q("#consent", "I agree to the privacy policy", "checkbox", False),
    ])


def test_generic_driver_replays_selectors(app_env, tmp_path):
    from autoapply import browser
    from autoapply.ats.base import JobRef, Question
    from autoapply.ats.generic_driver import FieldFailures, GenericDriver

    resume = tmp_path / "R.pdf"
    resume.write_bytes(b"%PDF-1.4")
    schema = _agent_schema()
    drv = GenericDriver(schema)
    fill = {"#first_name": "Liam", "#email": "liam@example.com", "#auth": "Yes", "#resume": str(resume), "#consent": True}
    with browser.open_page() as page:
        drv.open_application(page, JobRef("someats", "acme", "", FORM.as_uri()))
        assert len(drv.live_questions(page, 0)) == 5
        drv.fill_page(page, schema, 0, fill)
        back = drv.read_back(page, schema, 0)
        assert back == {"#first_name": "Liam", "#email": "liam@example.com", "#auth": "Yes", "#resume": "R.pdf", "#consent": True}
        assert drv.confirmation(page) is None
        with pytest.raises(PermissionError):
            drv.submit(page)  # driverless forms are submitted by the user
        assert not drv.next_page(page)  # the only button is Submit, which is never clicked
        assert page.evaluate("() => window.submitCount || 0") == 0

        schema.questions.append(Question(id="#gone", label="Vanished", type="text", required=True, locator={"selector": "#gone"}))
        with pytest.raises(FieldFailures) as e:
            drv.fill_page(page, schema, 0, {**fill, "#gone": "x"})
        assert [f["id"] for f in e.value.failures] == ["#gone"]  # the rest were still filled


def test_fixture_regression_detects_a_lost_field(app_env):
    from autoapply import browser, fixtures

    schema = _agent_schema()
    with browser.open_page() as page:
        page.goto(FORM.as_uri())
        path = fixtures.save(schema, page, 0, reason="test")
    assert "<script" not in open(path, encoding="utf-8").read()
    assert fixtures.run_all()["failed"] == 0
    meta = path.replace(".html", ".json")
    data = json.loads(open(meta, encoding="utf-8").read())
    data["questions"].append({**data["questions"][0], "id": "#phone", "label": "Phone", "locator": {"selector": "#phone"}})
    open(meta, "w", encoding="utf-8").write(json.dumps(data))
    res = fixtures.run_all("someats")
    assert res["failed"] == 1 and res["results"][0]["missing"] == ["Phone"]


def test_data_privacy_notice_is_acknowledged_and_nothing_else(app_env):
    from playwright.sync_api import sync_playwright

    from autoapply import db
    from autoapply.ats.generic_driver import acknowledge_notice

    notice = '<div role="dialog"><h2>Data Privacy Notice</h2><p>We process your personal data to assess your application.</p><button id="c">Cancel</button><button id="ok">I understand</button></div>'
    final = '<div role="dialog"><h2>Review and submit your application</h2><p>See our privacy policy.</p><button id="ok">Confirm</button></div>'
    other = '<div role="dialog"><h2>Leave this page?</h2><button id="ok">OK</button></div>'
    js = "<script>window.clicked='';document.addEventListener('click',e=>{window.clicked=e.target.id;if(e.target.id)e.target.closest('[role=dialog]').remove()})</script>"
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_content(notice + js)
        assert acknowledge_notice(pg) is True and pg.evaluate("clicked") == "ok" and pg.locator("[role=dialog]").count() == 0
        for html in (final, other):  # a submit confirmation, and a dialog that is not about data: both left alone
            pg.set_content(html + js)
            assert acknowledge_notice(pg) is False and pg.evaluate("clicked") == ""
        db.set_setting("consent.acknowledge_notices", False)
        pg.set_content(notice + js)
        assert acknowledge_notice(pg) is False and pg.locator("[role=dialog]").count() == 1
        b.close()


def test_controls_are_found_by_label_when_generated_ids_changed_and_locked_fields_are_respected(app_env):
    import pytest
    from playwright.sync_api import sync_playwright

    from autoapply.ats.base import DriverError, Question
    from autoapply.ats.generic_driver import get_value, set_value

    html = """<form>
      <label for="input-77">Country/region of residence</label><select id="input-77"><option></option><option>Canada</option><option>United States</option></select>
      <fieldset><legend>Is your legal name the same as your preferred name?</legend>
        <label><input type="radio" name="g9" value="y"> Yes</label><label><input type="radio" name="g9" value="n"> No</label></fieldset>
      <label for="em">Email</label><input id="em" value="me@example.com" readonly>
      <label for="ph">Phone</label><input id="ph" value="" readonly>
    </form>"""
    q = lambda sel, label, typ, **kw: Question(id=sel, label=label, type=typ, required=True, options=kw.get("options", []), page=0, locator={"selector": sel})  # noqa: E731
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_content(html)
        country = q("#input-8", "Country/region of residence", "select")       # recorded id no longer exists
        set_value(pg, country, "Canada")
        assert get_value(pg, country) == "Canada"
        same = q("#input-16", "Is your legal name the same as your preferred name?", "radio", options=["Yes", "No"])
        set_value(pg, same, "No")
        assert pg.locator("input[value=n]").is_checked()
        set_value(pg, q("#em", "Email", "text"), "ME@example.com")            # locked to the same value: fine, nothing typed
        with pytest.raises(DriverError, match="locked"):
            set_value(pg, q("#em", "Email", "text"), "other@example.com")
        with pytest.raises(DriverError, match="locked"):
            set_value(pg, q("#ph", "Phone", "text"), "6045550142")
        with pytest.raises(DriverError, match="control not found"):
            set_value(pg, q("#nope", "A question that is not on the page", "text"), "x")
        b.close()


def test_files_uploaded_after_the_draft_fill_its_empty_upload_fields(app_env, tmp_path):
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app
    from autoapply.models import Application, Document, Draft, Job

    resume, transcript = tmp_path / "r.pdf", tmp_path / "t.pdf"
    for f in (resume, transcript):
        f.write_bytes(b"%PDF-1.4")
    qs = [{"id": "#cv", "label": "Resume", "type": "file", "required": True, "options": [], "page": 0, "locator": {"selector": "#cv"}},
          {"id": "#tr", "label": "Please attach your most recent transcript (if available)", "type": "file", "required": True, "options": [], "page": 0, "locator": {"selector": "#tr"}}]
    with db.session() as s:
        j = Job(source="manual", source_id="1", company="CET", title="Co-op", status="scored", online=1, apply_url="https://x.example/1")
        s.add(j)
        s.flush()
        a = Application(job_id=j.id, status="draft_ready")
        s.add(a)
        s.flush()
        s.add(Document(kind="resume_site", name="r.pdf", path=str(resume)))
        d = Draft(application_id=a.id, version=1, schema={"ats": "generic", "tenant": "x", "url": "https://x.example/1", "source": "agent", "pages": ["Application"], "questions": qs, "extra": {},
                          "_ref": {"ats": "generic", "tenant": "x", "job_id": "", "url": "https://x.example/1", "host": "x.example", "extra": {}}},
                  answers=[{**q, "value": str(resume) if q["id"] == "#cv" else "", "basis": "", "confidence": "high", "source": "materials", "sensitive": False, "sensitive_confirmed": False} for q in qs],
                  unresolved=[], materials=[{"slot": "#cv", "slot_label": "Resume", "document_id": 1, "name": "r.pdf", "kind": "resume_site", "path": str(resume)}],
                  plan=[], notes=["Required file 'Please attach your most recent transcript (if available)' has no matching document."], auto_approve_check={})
        s.add(d)
        s.flush()
        did = d.id
    c = TestClient(app)
    before = c.get(f"/api/drafts/{did}").json()
    assert [a["value"] for a in before["answers"]] == [str(resume), ""] and len(before["notes"]) == 1
    with db.session() as s:
        s.add(Document(kind="transcript", name="t.pdf", path=str(transcript)))   # uploaded after the draft was prepared
    after = c.get(f"/api/drafts/{did}").json()                                    # opening the draft is enough
    assert [a["value"] for a in after["answers"]] == [str(resume), str(transcript)]
    assert [m["kind"] for m in after["materials"]] == ["resume_site", "transcript"] and after["notes"] == []


def test_a_value_shown_next_to_a_control_counts_even_if_the_control_reads_empty(app_env):
    from playwright.sync_api import sync_playwright

    from autoapply.ats.base import Question
    from autoapply.ats.generic_driver import get_value, value_visible

    html = """<div class="field"><label for="c1">Country code</label><div class="combo"><span class="chip">(+1 604) Canada</span><input id="c1" role="combobox" value=""></div></div>
              <div class="field"><label for="c2">Gender</label><div class="combo"><input id="c2" role="combobox" value=""></div></div>
              <div><button id="up">Upload your resume</button><span>Resume_Acme.pdf (uploaded)</span></div>"""
    q = lambda sel, label, typ: Question(id=sel, label=label, type=typ, required=True, options=[], page=0, locator={"selector": sel})  # noqa: E731
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_content(html)
        code, gender = q("#c1", "Country code", "text"), q("#c2", "Gender", "text")
        assert get_value(pg, code) == ""                                   # the widget gives nothing back
        assert value_visible(pg, code, "(+1 604) Canada") is True          # but the page shows the choice
        assert value_visible(pg, gender, "Male") is False                  # nothing shown: this one really needs a look
        assert value_visible(pg, q("#up", "Upload your resume", "file"), "C:/x/Resume_Acme.pdf") is True
        assert value_visible(pg, q("#up", "Upload your resume", "file"), "C:/x/Other.pdf") is False
        # a combobox that is a plain text input carrying the chosen option (Microsoft's careers form)
        pg.set_content('<label id="l">Gender</label><input id="g" role="combobox" aria-labelledby="l" type="text" value="Male">'
                       '<input role="combobox" type="text" value="Resume_Acme.pdf">')
        assert get_value(pg, q("#g", "Gender", "select")) == "Male"
        assert get_value(pg, q("#gone-7", "Gender", "select")) == "Male"       # the id changed: found by its label
        assert value_visible(pg, q("input[type=file]", "Upload your resume", "file"), "C:/x/Resume_Acme.pdf") is True
        b.close()


TAKEOVER_FORM = """<form onsubmit="return false">
  <label for="pf">Preferred First Name</label><input id="pf" required>
  <label for="same">Is your legal name the same as your preferred name?</label>
  <select id="same" required onchange="document.getElementById('legal').style.display = this.value === 'No' ? 'block' : 'none'">
    <option value=""></option><option>Yes</option><option>No</option></select>
  <div id="legal" style="display:none">
    <label for="lf">Legal First Name</label><input id="lf" required aria-required="true">
    <label for="salary">Expected salary</label><input id="salary" required>
  </div>
  <label for="phone">Phone number</label>
  <input id="phone" required oninput="const bad = this.value.startsWith('+'); this.setAttribute('aria-invalid', bad);
                                       document.getElementById('perr').textContent = bad ? 'Enter a valid phone number without the country code.' : ''"
         aria-describedby="perr"><div id="perr" role="alert"></div>
  <button type="submit">Submit application</button>
</form>"""


def test_the_form_has_the_last_word_and_the_agent_finishes_what_the_draft_did_not_know(app_env, tmp_path, monkeypatch):
    """The driver fills every approved value without an error, and the page is still not done: a required field appeared
    after an answer, and the form rejects the phone number. The program must notice by itself (no driver error, no
    read-back difference), hand the page to the agent with the applicant's profile, refuse the agent's 'done' while the
    form still complains, and keep what was learned in the draft and in the notes for the site."""
    from autoapply import config, db, executor, knowledge, llm
    from autoapply.ats.base import FormSchema, JobRef, Question
    from autoapply.models import Application, Draft, Job, Run

    form = tmp_path / "takeover.html"
    form.write_text(TAKEOVER_FORM, encoding="utf-8")
    knowledge.write("profile", "# Profile\n\n- Legal name: **Alexander Chen**\n- Preferred name: Alex Chen\n- Phone: +1 604-555-0142 (Canada)\n")
    q = lambda sel, label, typ, opts=None: Question(id=sel, label=label, type=typ, required=True, options=opts or [], locator={"selector": sel})  # noqa: E731
    schema = FormSchema(ats="generic", tenant="jobs.example.test", url=form.as_uri(), source="agent", pages=["Application"], questions=[
        q("#pf", "Preferred First Name", "text"), q("#same", "Is your legal name the same as your preferred name?", "select", ["Yes", "No"]), q("#phone", "Phone number", "text")])
    ref = JobRef(ats="generic", tenant="jobs.example.test", job_id="", url=form.as_uri(), host="jobs.example.test")
    row = lambda qq, v: {"id": qq.id, "label": qq.label, "type": qq.type, "options": qq.options, "required": True, "page": 0, "value": v, "basis": "profile",  # noqa: E731
                         "confidence": "high", "source": "profile", "sensitive": "", "sensitive_confirmed": False}
    with db.session() as s:
        job = Job(source="manual", source_id="tk1", company="Acme", title="Engineer", apply_url=form.as_uri(), channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        app = Application(job_id=job.id, status="approved")
        s.add(app)
        s.flush()
        d = Draft(application_id=app.id, schema={**schema.to_dict(), "_ref": ref.__dict__}, review_status="approved",
                  answers=[row(schema.questions[0], "Liam"), row(schema.questions[1], "No"), row(schema.questions[2], "+1 604-555-0142")])
        s.add(d)
        s.flush()
        app_id, did = app.id, d.id
    db.set_setting("repair.enabled", True)
    log = {"refused": 0}

    def agent(goal, tools, *, system, max_steps=60, on_step=None):
        t = {x.name: x for x in tools}
        log["goal"] = goal
        log["first_check"] = t["check_form"].fn()
        log["early_done"] = t["done"].fn(fixed=[], unfixed=[], cause="c", suggestion="s")          # claims to be finished straight away
        t["fill"].fn(selector="#lf", value="Alexander")                                              # from the profile
        t["fill"].fn(selector="#phone", value="604-555-0142")                                      # what the form accepts
        log["second_check"] = t["check_form"].fn()
        log["final"] = t["done"].fn(fixed=["#phone"], unfixed=[], cause="Two fields appear only after the legal-name answer.",
                                    suggestion="After answering the legal-name question, fill Legal First Name; the phone goes without +1.",
                                    added=[{"label": "Legal First Name", "value": "Alexander", "basis": "Legal name: Alexander Chen", "type": "text"}],
                                    needs_user=[{"label": "Expected salary", "why": "not in the profile"}])
        return llm.AgentResult(final_text="done", steps=[{"tool": "done"}])

    handed = {}

    def user_window(driver, page, title, application_id, draft_id=None, **kw):
        handed.update(kw)
        handed["lf"] = page.locator("#lf").input_value()
        return {"status": "ready_to_submit", "error": "window closed"}

    monkeypatch.setattr(llm, "agent", agent)
    monkeypatch.setattr(executor, "_wait_for_manual_submit", user_window)
    executor.execute(app_id, did)

    # the program found the problems itself and told the agent, together with the profile
    assert "Legal First Name: required, still empty" in log["goal"] and "Expected salary" in log["goal"] and "valid phone number" in log["goal"]
    assert "Alexander Chen" in log["goal"]
    # 'done' while the form still complains is refused; afterwards only what was handed to the user is left
    assert log["early_done"].startswith("NOT ACCEPTED") and "Legal First Name" in log["early_done"]
    assert "Expected salary" in log["second_check"] and "Legal First Name" not in log["second_check"] and "phone" not in log["second_check"].lower()
    assert log["final"] == "recorded" and handed["lf"] == "Alexander"
    # the user is told exactly what is open and what was added: nothing is called filled that is not
    assert [(x["kind"], x["label"]) for x in handed["leftovers"]] == [("fix", "Expected salary")]
    assert handed["added"][0]["label"] == "Legal First Name" and handed["added"][0]["value"] == "Alexander"
    with db.session() as s:
        d = s.get(Draft, did)
        new = [a for a in d.answers if a["source"] == "agent_added"]
        assert [(a["id"], a["value"]) for a in new] == [("@label:Legal First Name", "Alexander")]
        assert any(qq["id"] == "@label:Legal First Name" for qq in d.schema["questions"])
        steps = s.query(Run).filter_by(kind="execute").order_by(Run.id.desc()).first().steps
        ops = [x["op"] for x in steps]
        assert ops.index("form_reports") < ops.index("repair") < ops.index("handed_over")
    # the site note is there for the next exploration and the next take-over
    note = (config.PLAYBOOKS / "site-jobs.example.test.md").read_text(encoding="utf-8")
    assert "fill Legal First Name" in note and "appear after an answer" in note

    # second run of the same draft: the driver now fills the discovered field by its label, no agent needed for it
    calls = []
    monkeypatch.setattr(llm, "agent", lambda goal, tools, **kw: (calls.append(goal), {x.name: x for x in tools}["done"].fn(
        fixed=[], unfixed=[], cause="", suggestion="", needs_user=[{"label": "Expected salary", "why": "not in the profile"}]), llm.AgentResult(final_text="done"))[-1])
    with db.session() as s:
        s.get(Application, app_id).status = "approved"
    handed.clear()
    executor.execute(app_id, did)
    assert handed["lf"] == "Alexander"
    assert calls and "Legal First Name: required" not in calls[0] and "Expected salary" in calls[0]


def test_a_form_behind_an_apply_button_is_opened_not_reported_as_a_login_problem(app_env, tmp_path, monkeypatch):
    """The recorded address shows the posting; the form appears after "Apply for This Job". The driver clicks it."""
    from playwright.sync_api import sync_playwright

    from autoapply.ats.base import FormSchema, JobRef, Question
    from autoapply.ats.generic_driver import GenericDriver

    html = tmp_path / "posting.html"
    html.write_text("""<h1>Computer Science Co-Op</h1><button onclick="document.getElementById('f').style.display='block'">Apply for This Job</button>
        <button>Submit application</button>
        <form id="f" style="display:none"><label for="fn">First Name</label><input id="fn"></form>""", encoding="utf-8")
    schema = FormSchema(ats="generic", tenant="x.test", url=html.as_uri(), source="agent", pages=["Application"],
                        questions=[Question(id="#fn", label="First Name", type="text", required=True, locator={"selector": "#fn"})])
    ref = JobRef(ats="generic", tenant="x.test", job_id="", url=html.as_uri(), host="x.test")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        d = GenericDriver(schema)
        d.open_application(pg, ref)
        assert pg.locator("#fn").is_visible()
        assert d.reveal_form(pg) is False          # the form is there: nothing more is clicked
        # Submit is never the button chosen, even when it is the first one on the page
        pg.set_content("""<button onclick="document.title='submitted'">Submit application</button><a href="#" onclick="document.title='applied'">Apply now</a>""")
        assert d.reveal_form(pg) is True and pg.title() == "applied"
        b.close()


WIZARD = r"""<main>
<h1 id="t"></h1><div id="body"></div>
<script>
  window.sms = false; window.submitted = false;
  const saved = {first: 'Alex'};           // an earlier attempt already saved the contact step
  const steps = {
    sms: () => ['SMS Notifications (Optional)', '<p>Get SMS updates on your job applications</p><button onclick="window.sms = true; go(\'work\')">Enable SMS updates</button> <button onclick="go(\'work\')">Skip &amp; continue</button>'],
    work: () => ['Work Eligibility', '<label for="auth">Are you legally authorized to work in Canada?</label><select id="auth" required><option value=""></option><option>Yes</option><option>No</option></select>'
        + '<label for="legal">Legal First Name</label><input id="legal" required>'
        + '<button onclick="if (auth.value &amp;&amp; legal.value) { saved.auth = auth.value; saved.legal = legal.value; go(\'review\') } else document.getElementById(\'err\').textContent = \'Please complete the required fields.\'">Go on to the summary</button><div id="err" role="alert"></div>'],
    review: () => ['Review & submit', '<p>First Name: ' + saved.first + '</p><p>Are you legally authorized to work in Canada?: ' + saved.auth + '</p><p>Legal First Name: ' + saved.legal + '</p>'
        + '<div style="height:0; overflow:hidden"><label for="first">First Name</label><input id="first" oninput="window.touched = true"></div>'
        + '<button onclick="window.submitted = true">Submit application</button>'],
  };
  function go(name) { const [t, html] = steps[name](); document.getElementById('t').textContent = t; document.getElementById('body').innerHTML = html; }
  go('sms');                                // the form resumes at the step after the last one it saved
</script></main>"""


def test_a_form_with_several_steps_is_walked_by_what_is_on_screen(app_env, tmp_path, monkeypatch):
    """A wizard that resumes at an optional step, shows a required field the draft never saw, uses a forward button with an
    unusual name and ends on a review page. The steps are not the pages the draft recorded: the run must still get to the
    review page, decline the optional offer, and hand the form to the user there - not fail with "could not advance"."""
    from autoapply import config, db, executor, knowledge, llm
    from autoapply.ats.base import FormSchema, JobRef, Question
    from autoapply.models import Application, Draft, Job, Run

    form = tmp_path / "wizard.html"
    form.write_text(WIZARD, encoding="utf-8")
    knowledge.write("profile", "# Profile\n\n- Name on documents: Alexander Chen\n")
    q = lambda sel, label, typ, page, opts=None: Question(id=sel, label=label, type=typ, required=True, options=opts or [], page=page, locator={"selector": sel})  # noqa: E731
    # the draft was read on an earlier visit: "contact" first, then work eligibility; the form now starts elsewhere
    schema = FormSchema(ats="generic", tenant="wizard.example.test", url=form.as_uri(), source="agent", pages=["Contact information", "Work Eligibility", "Review & submit"], questions=[
        q("#first", "First Name", "text", 0), q("#auth", "Are you legally authorized to work in Canada?", "select", 1, ["Yes", "No"])])
    ref = JobRef(ats="generic", tenant="wizard.example.test", job_id="", url=form.as_uri(), host="wizard.example.test")
    row = lambda qq, v: {"id": qq.id, "label": qq.label, "type": qq.type, "options": qq.options, "required": True, "page": qq.page, "value": v, "basis": "profile",  # noqa: E731
                         "confidence": "high", "source": "profile", "sensitive": "", "sensitive_confirmed": False}
    with db.session() as s:
        job = Job(source="manual", source_id="wz1", company="Acme", title="Analyst", apply_url=form.as_uri(), channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        app = Application(job_id=job.id, status="approved")
        s.add(app)
        s.flush()
        d = Draft(application_id=app.id, schema={**schema.to_dict(), "_ref": ref.__dict__}, review_status="approved",
                  answers=[row(schema.questions[0], "Alex"), row(schema.questions[1], "Yes")])
        s.add(d)
        s.flush()
        app_id, did = app.id, d.id
    db.set_setting("repair.enabled", True)
    calls = {"fix": 0, "nav": 0}

    def agent(goal, tools, *, system, max_steps=60, on_step=None):
        t = {x.name: x for x in tools}
        if "check_form" in t:                      # finishing a step: the field the draft did not know, from the profile
            calls["fix"] += 1
            assert "Legal First Name: required, still empty" in goal and "Alexander Chen" in goal
            t["fill"].fn(selector="#legal", value="Alexander")
            t["done"].fn(fixed=[], unfixed=[], cause="A required field the draft did not list.", suggestion="Fill Legal First Name on the Work Eligibility step.",
                         added=[{"label": "Legal First Name", "value": "Alexander", "basis": "Name on documents: Alexander Chen", "type": "text"}])
        else:                                      # finding the way forward: it can look and click, it cannot answer or submit
            calls["nav"] += 1
            assert set(t) == {"read_page", "list_controls", "screenshot", "click", "press", "done"}
            t["click"].fn(text="Go on to the summary")
            t["done"].fn(state="moved", note="the forward button on Work Eligibility is called 'Go on to the summary'")
        return llm.AgentResult(final_text="done", steps=[{"tool": "done"}])

    handed = {}

    def user_window(driver, page, title, application_id, draft_id=None, **kw):
        handed.update(kw)
        handed["state"] = page.evaluate("({title: document.getElementById('t').textContent, sms: window.sms, submitted: window.submitted, auth: saved.auth, legal: saved.legal})")
        handed["touched"] = page.evaluate("window.touched || null")
        return {"status": "ready_to_submit", "error": "window closed"}

    monkeypatch.setattr(llm, "agent", agent)
    monkeypatch.setattr(executor, "_wait_for_manual_submit", user_window)
    executor.execute(app_id, did)

    # at the review page, with the optional offer declined, nothing submitted, and the field the draft did not know filled
    assert handed["state"] == {"title": "Review & submit", "sms": False, "submitted": False, "auth": "Yes", "legal": "Alexander"}
    assert calls == {"fix": 1, "nav": 1}
    assert handed["leftovers"] == [], handed["leftovers"]             # "First Name" was not asked again, and the review page confirms it
    assert handed["added"][0]["label"] == "Legal First Name"
    with db.session() as s:
        steps = s.query(Run).filter_by(kind="execute").order_by(Run.id.desc()).first().steps
    ops = [(x["op"], x.get("how") or x.get("title") or "") for x in steps if x["op"] in ("walk", "fill_step", "advance", "review_step", "cannot_advance", "stuck")]
    # the review page is recognised before anything is filled in: its collapsed sections still carry controls of earlier steps
    assert ops == [("walk", ""), ("fill_step", "SMS Notifications (Optional)"), ("advance", "button"), ("fill_step", "Work Eligibility"), ("advance", "agent"),
                   ("review_step", "Review & submit")], ops
    assert handed["touched"] is None
    assert next(x for x in steps if x["op"] == "not_asked")["shown_on_review"] == 1
    # what the navigator found is kept for the next run on this site
    assert "Go on to the summary" in (config.PLAYBOOKS / "site-wizard.example.test.md").read_text(encoding="utf-8")


def test_a_step_that_will_not_go_on_is_handed_to_the_user_with_the_reason(app_env, tmp_path, monkeypatch):
    """No forward button the program knows, and the navigator reports that the form is blocked: the run does not fail and
    does not pretend - the window goes to the user with the reason on the list."""
    from autoapply import db, executor, llm
    from autoapply.ats.base import FormSchema, JobRef, Question
    from autoapply.models import Application, Draft, Job

    form = tmp_path / "stuck.html"
    form.write_text("""<main><h1>Assessment</h1><label for="a">City</label><input id="a"><p>Complete the online assessment sent to your e-mail to continue.</p></main>""", encoding="utf-8")
    qq = Question(id="#a", label="City", type="text", required=True, page=0, locator={"selector": "#a"})
    schema = FormSchema(ats="generic", tenant="stuck.example.test", url=form.as_uri(), source="agent", pages=["Assessment", "Review"], questions=[qq])
    ref = JobRef(ats="generic", tenant="stuck.example.test", job_id="", url=form.as_uri(), host="stuck.example.test")
    with db.session() as s:
        job = Job(source="manual", source_id="st1", company="Acme", title="Analyst", apply_url=form.as_uri(), channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        app = Application(job_id=job.id, status="approved")
        s.add(app)
        s.flush()
        d = Draft(application_id=app.id, schema={**schema.to_dict(), "_ref": ref.__dict__}, review_status="approved",
                  answers=[{"id": "#a", "label": "City", "type": "text", "options": [], "required": True, "page": 0, "value": "Vancouver", "basis": "profile",
                            "confidence": "high", "source": "profile", "sensitive": "", "sensitive_confirmed": False}])
        s.add(d)
        s.flush()
        app_id, did = app.id, d.id
    db.set_setting("repair.enabled", True)
    calls = {"fix": 0, "nav": 0}

    def agent(goal, tools, *, system, max_steps=60, on_step=None):
        t = {x.name: x for x in tools}
        if "check_form" in t:      # asked once to finish the step, with what the navigator saw: there is nothing it can fill
            calls["fix"] += 1
            assert "online assessment" in goal
            t["done"].fn(fixed=[], unfixed=[], cause="The step waits for an assessment outside the form.", suggestion="")
        else:
            calls["nav"] += 1
            t["done"].fn(state="blocked", why="the page asks for an online assessment first")
        return llm.AgentResult(final_text="done", steps=[{"tool": "done"}])

    monkeypatch.setattr(llm, "agent", agent)
    handed = {}

    def user_window(driver, page, title, application_id, draft_id=None, **kw):
        handed.update(kw)
        handed["city"] = page.locator("#a").input_value()
        return {"status": "ready_to_submit", "error": "window closed"}

    monkeypatch.setattr(executor, "_wait_for_manual_submit", user_window)
    executor.execute(app_id, did)
    assert handed["city"] == "Vancouver"
    assert [x["kind"] for x in handed["leftovers"]] == ["form"] and "online assessment" in handed["leftovers"][0]["label"]
    assert calls == {"fix": 1, "nav": 2}       # the way forward, one round of finishing the step, the way forward again - then the user


LATE_ERRORS = """<main><h1 id="t">Work Eligibility</h1><div id="pane">
  <label for="a">City *</label><input id="a">
  <label for="b">Country of residence *</label><input id="b">
  <div id="err" role="alert"></div><button onclick="next()">Continue</button></div>
<script>
  function next() {
    const a = document.getElementById('a').value, b = document.getElementById('b').value;
    if (!a || !b) { document.getElementById('err').textContent = 'Country of residence is required.'; return; }
    document.getElementById('t').textContent = 'Review';
    document.getElementById('pane').innerHTML = '<p>City: ' + a + '</p><p>Country of residence: ' + b + '</p><button>Submit application</button>';
  }
</script></main>"""


def test_a_form_that_names_a_missing_answer_only_after_continue_is_finished_and_goes_on(app_env, tmp_path, monkeypatch):
    """Nothing marks the second field as required until "Continue" is pressed. The refusal is not the end of the run: the
    form now says what is missing, the take-over fills it from the profile, and the form goes on to its review page."""
    from autoapply import db, executor, knowledge, llm
    from autoapply.ats.base import FormSchema, JobRef, Question
    from autoapply.models import Application, Draft, Job

    form = tmp_path / "late.html"
    form.write_text(LATE_ERRORS, encoding="utf-8")
    knowledge.write("profile", "# Profile\n\n- Lives in: Vancouver, Canada\n")
    qq = Question(id="#a", label="City", type="text", required=True, page=0, locator={"selector": "#a"})
    schema = FormSchema(ats="generic", tenant="late.example.test", url=form.as_uri(), source="agent", pages=["Work Eligibility", "Review"], questions=[qq])
    ref = JobRef(ats="generic", tenant="late.example.test", job_id="", url=form.as_uri(), host="late.example.test")
    with db.session() as s:
        job = Job(source="manual", source_id="lt1", company="Acme", title="Analyst", apply_url=form.as_uri(), channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        app = Application(job_id=job.id, status="approved")
        s.add(app)
        s.flush()
        d = Draft(application_id=app.id, schema={**schema.to_dict(), "_ref": ref.__dict__}, review_status="approved",
                  answers=[{"id": "#a", "label": "City", "type": "text", "options": [], "required": True, "page": 0, "value": "Vancouver", "basis": "profile",
                            "confidence": "high", "source": "profile", "sensitive": "", "sensitive_confirmed": False}])
        s.add(d)
        s.flush()
        app_id, did = app.id, d.id
    db.set_setting("repair.enabled", True)
    goals = []

    def agent(goal, tools, *, system, max_steps=60, on_step=None):
        t = {x.name: x for x in tools}
        assert "check_form" in t, "the navigator is not needed: the form has a Continue button"
        goals.append(goal)
        t["fill"].fn(selector="#b", value="Canada")
        t["done"].fn(fixed=[], unfixed=[], cause="The form asks for the country only after Continue.", suggestion="Fill Country of residence on Work Eligibility.",
                     added=[{"label": "Country of residence", "value": "Canada", "basis": "Lives in: Vancouver, Canada", "type": "text"}])
        return llm.AgentResult(final_text="done", steps=[{"tool": "done"}])

    handed = {}

    def user_window(driver, page, title, application_id, draft_id=None, **kw):
        handed.update(kw)
        handed["title"], handed["text"] = page.locator("#t").inner_text(), page.locator("#pane").inner_text()
        return {"status": "ready_to_submit", "error": "window closed"}

    monkeypatch.setattr(llm, "agent", agent)
    monkeypatch.setattr(executor, "_wait_for_manual_submit", user_window)
    executor.execute(app_id, did)
    assert len(goals) == 1 and "Country of residence is required" in goals[0]
    assert handed["title"] == "Review" and "City: Vancouver" in handed["text"] and "Country of residence: Canada" in handed["text"]
    assert handed["leftovers"] == [] and handed["added"][0]["label"] == "Country of residence"


def test_forward_buttons_are_recognised_and_submit_never_is(app_env):
    from autoapply.ats.generic_driver import FORWARD_RE, SUBMIT_RE

    for t in ("Next", "Continue", "Save and continue", "Save & Continue", "Skip & continue", "Skip for now", "Next step", "下一步", "跳过", "Continue ›"):
        assert FORWARD_RE.match(t), t
    for t in ("Submit application", "Enable SMS updates", "Continue with Google", "Save draft", "Back", "Cancel", "Skip to main content"):
        assert not FORWARD_RE.match(t), t
    assert SUBMIT_RE.search("Submit application") and SUBMIT_RE.search("Review and Submit") and not SUBMIT_RE.search("Skip & continue")


def test_a_label_that_only_contains_the_question_is_another_question(app_env):
    """The recorded control is not on this step. Its label must not be 'found' in a longer label of another field."""
    from playwright.sync_api import sync_playwright

    from autoapply.ats.base import Question
    from autoapply.ats.generic_driver import _loc

    q = lambda label, typ="text": Question(id="#gone", label=label, type=typ, locator={"selector": "#gone"})  # noqa: E731
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        pg.set_content("""<form>
          <label for="l">Legal First Name</label><input id="l">
          <label for="pt">Phone type</label><select id="pt"><option>Mobile</option></select>
          <label for="e">Email address *</label><input id="e">
          <label for="c">City (required)</label><input id="c">
          <fieldset><legend>Do you need sponsorship?</legend><label><input type="radio" name="s">Yes</label><label><input type="radio" name="s">No</label></fieldset>
          <fieldset><legend>Have you worked here before, or at a subsidiary?</legend><label><input type="radio" name="w">Yes</label></fieldset>
        </form>""")
        assert _loc(pg, q("First Name")).count() == 0
        assert _loc(pg, q("Phone")).count() == 0
        assert _loc(pg, q("Have you worked here before", "radio")).count() == 0
        assert _loc(pg, q("Email address")).get_attribute("id") == "e"        # decoration after the label is still the same question
        assert _loc(pg, q("email address *")).get_attribute("id") == "e"
        assert _loc(pg, q("City")).get_attribute("id") == "c"
        assert _loc(pg, q("Do you need sponsorship?", "radio")).count() == 1
        b.close()


def test_a_pick_list_that_shows_its_choices_as_chips_is_not_called_empty(app_env):
    """Multi-select widgets keep a hidden <select> and an empty search box, and show what was chosen as chips in a
    group marked required. The audit reads what the group shows."""
    from playwright.sync_api import sync_playwright

    from autoapply.ats import audit

    chips = """<label id="l{n}">{label}</label>
      <span role="group" aria-required="true" aria-label="{label}" tabindex="0"><ul>{items}
        <li><input type="text" role="textbox" aria-autocomplete="list" placeholder=""></li></ul></span>"""
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        pg.set_content("<form>" + chips.format(n=1, label="Area of specialization", items='<li><span role="button">×</span>Machine Learning</li>')
                       + chips.format(n=2, label="Availability", items="")
                       + """<fieldset role="group" aria-required="true" aria-label="Sponsorship"><label><input type="radio" name="s">Yes</label><label><input type="radio" name="s">No</label></fieldset></form>""")
        found = [(i["kind"], i["label"]) for i in audit.page_issues(pg)]
        assert ("empty_required", "Availability") in found and ("empty_required", "Sponsorship") in found
        assert not any("specialization" in label for _, label in found)
        b.close()


def test_what_a_site_taught_is_given_to_the_next_draft_and_no_patch_card_is_made_for_it(app_env, monkeypatch):
    from autoapply import answers, db, knowledge, llm, repair
    from autoapply.ats.base import FormSchema, Question
    from autoapply.models import Job, Todo

    knowledge.write("profile", "# Profile\n\n- Skills: C++, Linux\n")
    knowledge.add_site_note("site-jobs.example.test", "The skills description takes at most 200 characters.")
    schema = FormSchema(ats="generic", tenant="jobs.example.test", url="https://jobs.example.test/apply", source="agent", pages=["Application"],
                        questions=[Question(id="#s", label="Describe your skills", type="text", required=True, locator={"selector": "#s"})])
    seen = {}

    def fake_json(prompt, schema_, *, system="", **kw):
        seen["prompt"] = prompt
        return {"answers": [{"id": "k1", "resolved": True, "value": "C++ and Linux", "basis": "Skills", "confidence": "high", "source": "profile"}], "new_rules": []}

    monkeypatch.setattr(llm, "json", fake_json)
    with db.session() as s:
        job = Job(source="manual", source_id="sn1", company="Acme", title="Engineer", apply_url=schema.url, jd_text="x" * 300)
        s.add(job)
        s.flush()
        s.expunge(job)
    answers.resolve(schema, job, cover_letter=None, resume=None)
    assert "<site_notes>" in seen["prompt"] and "at most 200 characters" in seen["prompt"]
    # a take-over on such a form leaves no "driver patch" card: there is no driver, and the note above is where the finding lives
    repair._propose(schema, None, 0, {"message": "x"}, {"cause": "c", "suggestion": "s"}, title="Acme", ref="application:1")
    with db.session() as s:
        assert s.query(Todo).filter_by(kind="driver_patch").count() == 0


USER_IS_FASTER = """<main><h1 id="t">Work Eligibility</h1><div id="pane">
  <label for="a">City</label><input id="a">
  <label for="b">Country of residence</label><input id="b" required>
  <button onclick="document.getElementById('t').textContent = 'Review'">Continue</button>
  <a href="#" id="user" onclick="document.querySelector('main').innerHTML = '<h1>Thank you for applying!</h1><p>Your application has been submitted.</p>'; return false">.</a>
</div></main>"""


def _one_question_draft(tmp_path, html, name):
    from autoapply import db
    from autoapply.ats.base import FormSchema, JobRef, Question
    from autoapply.models import Application, Draft, Job

    form = tmp_path / f"{name}.html"
    form.write_text(html, encoding="utf-8")
    qq = Question(id="#a", label="City", type="text", required=True, page=0, locator={"selector": "#a"})
    schema = FormSchema(ats="generic", tenant=f"{name}.example.test", url=form.as_uri(), source="agent", pages=["Work Eligibility", "Review"], questions=[qq])
    ref = JobRef(ats="generic", tenant=f"{name}.example.test", job_id="", url=form.as_uri(), host=f"{name}.example.test")
    with db.session() as s:
        job = Job(source="manual", source_id=name, company="Acme", title="Analyst", apply_url=form.as_uri(), channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        app = Application(job_id=job.id, status="approved")
        s.add(app)
        s.flush()
        d = Draft(application_id=app.id, schema={**schema.to_dict(), "_ref": ref.__dict__}, review_status="approved",
                  answers=[{"id": "#a", "label": "City", "type": "text", "options": [], "required": True, "page": 0, "value": "Vancouver", "basis": "profile",
                            "confidence": "high", "source": "profile", "sensitive": "", "sensitive_confirmed": False}])
        s.add(d)
        s.flush()
        return app.id, d.id


def test_the_user_submits_in_the_window_while_the_program_is_still_on_the_form(app_env, tmp_path, monkeypatch):
    """The user sits at the same window and does not wait for the program: while a take-over is still working on a step,
    they finish the form and submit it. The confirmation page is the end of the run - it is not treated as another step,
    and the application is recorded as submitted with what the page showed."""
    from autoapply import db, executor, llm
    from autoapply.models import Application, Run

    app_id, did = _one_question_draft(tmp_path, USER_IS_FASTER, "faster")
    db.set_setting("repair.enabled", True)
    calls = []

    def agent(goal, tools, *, system, max_steps=60, on_step=None):
        t = {x.name: x for x in tools}
        calls.append("fix" if "check_form" in t else "nav")
        t["click"].fn(selector="#user")           # meanwhile, in the same window, the user sends the application
        t["done"].fn(fixed=[], unfixed=[], cause="", suggestion="")
        return llm.AgentResult(final_text="done", steps=[{"tool": "done"}])

    monkeypatch.setattr(llm, "agent", agent)
    monkeypatch.setattr(executor, "_wait_for_manual_submit", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("there is no form left to hand over")))
    out = executor.execute(app_id, did)
    assert out["status"] == "submitted" and "Thank you for applying" in str(out["evidence"])
    assert calls == ["fix"]                         # nothing more is tried on the confirmation page
    with db.session() as s:
        assert s.get(Application, app_id).status == "submitted"
        ops = [x["op"] for x in s.query(Run).filter_by(kind="execute").order_by(Run.id.desc()).first().steps]
    assert "submitted_in_window" in ops and "cannot_advance" not in ops and "not_asked" not in ops


def test_words_of_thanks_on_a_step_of_the_form_are_not_a_submission(app_env, tmp_path, monkeypatch):
    """"Thank you for your interest" above a form that is still there says nothing about a submission."""
    from autoapply import executor

    html = """<main><h1>Thank you for your interest in Acme</h1><label for="a">City</label><input id="a"><button>Submit application</button></main>"""
    app_id, did = _one_question_draft(tmp_path, html, "thanks")
    handed = {}
    monkeypatch.setattr(executor, "_wait_for_manual_submit", lambda driver, page, *a, **kw: (handed.update(city=page.locator("#a").input_value()), {"status": "ready_to_submit", "error": "window closed"})[-1])
    out = executor.execute(app_id, did)
    assert out["status"] == "ready_to_submit" and handed["city"] == "Vancouver"


LIMITED = """<form onsubmit="return false">
  <label for="city">City</label><input id="city" required>
  <label for="skills">Describe your skills</label>
  <input id="skills" required aria-describedby="serr" oninput="const bad = this.value.length > 200; this.setAttribute('aria-invalid', bad);
        document.getElementById('serr').textContent = bad ? 'Text length should be between 0 and 200' : ''"><div id="serr" role="alert"></div>
  <button type="submit">Submit application</button>
</form>"""


def test_an_answer_the_form_refuses_for_its_length_is_adapted_by_the_take_over_and_remembered(app_env, tmp_path, monkeypatch):
    """The approved answer is 600 characters and the field takes 200. That is not the applicant's problem: the take-over
    rewrites it to fit, the applicant is shown both versions, and the draft and the notes for the site keep what was
    learned - so the same draft goes through without any agent the second time."""
    from autoapply import config, db, executor, knowledge, llm
    from autoapply.ats.base import FormSchema, JobRef, Question
    from autoapply.models import Application, Draft, Job

    form = tmp_path / "limited.html"
    form.write_text(LIMITED, encoding="utf-8")
    knowledge.write("profile", "# Profile\n\n- Skills: C++ at an internship; Linux services; algorithms coursework\n")
    long = "i) C/C++: built a key storage provider at my internship. " * 11          # about 620 characters
    q = lambda sel, label: Question(id=sel, label=label, type="text", required=True, locator={"selector": sel})  # noqa: E731
    schema = FormSchema(ats="generic", tenant="limited.example.test", url=form.as_uri(), source="agent", pages=["Application"], questions=[q("#city", "City"), q("#skills", "Describe your skills")])
    ref = JobRef(ats="generic", tenant="limited.example.test", job_id="", url=form.as_uri(), host="limited.example.test")
    row = lambda qq, v: {"id": qq.id, "label": qq.label, "type": "text", "options": [], "required": True, "page": 0, "value": v, "basis": "profile",  # noqa: E731
                         "confidence": "high", "source": "profile", "sensitive": "", "sensitive_confirmed": False}
    with db.session() as s:
        job = Job(source="manual", source_id="lim1", company="Acme", title="Engineer", apply_url=form.as_uri(), channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        app = Application(job_id=job.id, status="approved")
        s.add(app)
        s.flush()
        d = Draft(application_id=app.id, schema={**schema.to_dict(), "_ref": ref.__dict__}, review_status="approved", answers=[row(schema.questions[0], "Vancouver"), row(schema.questions[1], long)])
        s.add(d)
        s.flush()
        app_id, did = app.id, d.id
    db.set_setting("repair.enabled", True)
    short = "C/C++ at an internship (a Windows key storage provider); Linux services; algorithms and complexity from coursework."
    log = {}

    def agent(goal, tools, *, system, max_steps=60, on_step=None):
        t = {x.name: x for x in tools}
        log["goal"], log["system"] = goal, system
        log["too_long"] = t["done"].fn(fixed=[], unfixed=[], cause="c", suggestion="s", adapted=[{"id": "#skills", "value": long[:300], "max_chars": 200}])   # still over the limit
        t["fill"].fn(selector="#skills", value=short)
        log["check"] = t["check_form"].fn()
        log["final"] = t["done"].fn(fixed=["#skills"], unfixed=[], cause="The skills field takes at most 200 characters.", suggestion="Write the skills answer within 200 characters.",
                                    adapted=[{"id": "#skills", "value": short, "max_chars": 200, "why": "Text length should be between 0 and 200"}])
        return llm.AgentResult(final_text="done", steps=[{"tool": "done"}])

    handed = {}

    def user_window(driver, page, title, application_id, draft_id=None, **kw):
        handed.update(kw)
        handed["skills"] = page.locator("#skills").input_value()
        return {"status": "ready_to_submit", "error": "window closed"}

    monkeypatch.setattr(llm, "agent", agent)
    monkeypatch.setattr(executor, "_wait_for_manual_submit", user_window)
    executor.execute(app_id, did)

    # the agent was told what the form says, and its rules make the rewrite its job
    assert "Text length should be between 0 and 200" in log["goal"] and "LENGTH or FORMAT" in log["system"] and "Never invent or alter" not in log["system"]
    assert log["too_long"].startswith("NOT ACCEPTED") and "300 characters" in log["too_long"]      # an "adapted" answer that does not fit is not accepted
    assert log["check"] == "The form reports no problem." and log["final"] == "recorded"
    # nothing is left for the applicant to fill; they are shown what was changed, old and new
    assert handed["skills"] == short and [x for x in handed["leftovers"] if x["kind"] in ("fix", "form")] == []
    assert [(a["label"], a["entered"], a["max_chars"]) for a in handed["adapted"]] == [("Describe your skills", short, 200)] and handed["adapted"][0]["approved"].startswith("i) C/C++")
    # what was learned is kept: in the draft (answer and limit) and in the notes for the site
    with db.session() as s:
        d = s.get(Draft, did)
        ans = {a["id"]: a for a in d.answers}
        assert ans["#skills"]["value"] == short and "200" in ans["#skills"]["basis"] and ans["#city"]["value"] == "Vancouver"
        assert {qq["id"]: qq.get("max_length", 0) for qq in d.schema["questions"]} == {"#city": 0, "#skills": 200}
    assert "at most 200 characters" in (config.PLAYBOOKS / "site-limited.example.test.md").read_text(encoding="utf-8")

    # the same draft again: the driver fills the adapted answer, the form accepts it, no agent is needed
    monkeypatch.setattr(llm, "agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no take-over should be needed the second time")))
    with db.session() as s:
        s.get(Application, app_id).status = "approved"
    handed.clear()
    executor.execute(app_id, did)
    assert handed["skills"] == short and not handed.get("adapted") and [x for x in handed["leftovers"] if x["kind"] in ("fix", "form")] == []


def test_a_question_with_a_known_limit_is_answered_within_it(app_env, monkeypatch):
    from autoapply import answers, db, knowledge, llm
    from autoapply.ats.base import FormSchema, Question
    from autoapply.models import Job

    knowledge.write("profile", "# Profile\n\n- Skills: C++, Linux\n")
    schema = FormSchema(ats="generic", tenant="jobs.example.test", url="https://jobs.example.test/apply", source="agent", pages=["Application"],
                        questions=[Question(id="#s", label="Describe your skills", type="text", required=True, locator={"selector": "#s"}, max_length=60)])
    prompts_seen = []

    def fake_json(prompt, schema_, *, system="", **kw):
        prompts_seen.append(prompt)
        value = "C++ and Linux, " * 10 if len(prompts_seen) == 1 else "C++ at an internship; Linux services."       # the first answer ignores the limit
        return {"answers": [{"id": "k1", "resolved": True, "value": value, "basis": "Skills", "confidence": "high", "source": "profile"}], "new_rules": []}

    monkeypatch.setattr(llm, "json", fake_json)
    with db.session() as s:
        job = Job(source="manual", source_id="lim2", company="Acme", title="Engineer", apply_url=schema.url, jd_text="x" * 300)
        s.add(job)
        s.flush()
        s.expunge(job)
    out = answers.resolve(schema, job, cover_letter=None, resume=None)
    assert "at most 60 characters" in prompts_seen[0] and len(prompts_seen) == 2 and "YOUR ANSWER HAD 150 CHARACTERS" in prompts_seen[1]
    assert out["answers"][0]["value"] == "C++ at an internship; Linux services."
    # a draft stored before limits were kept still loads: the field is optional
    assert Question(**{"id": "#x", "label": "X"}).max_length == 0


UNKNOWN_QUESTION = """<main><h1 id="t">Work Eligibility</h1><div id="pane">
  <label for="a">City</label><input id="a" required>
  <fieldset role="radiogroup" aria-required="true"><legend>Have you been a government employee in the past three years?</legend>
    <label><input type="radio" name="gov" value="no">No, never</label> <label><input type="radio" name="gov" value="yes">Yes</label></fieldset>
  <div id="err" role="alert"></div><button onclick="next()">Continue</button></div>
<script>
  function next() {
    const g = document.querySelector('input[name=gov]:checked');
    if (!document.getElementById('a').value || !g) { document.getElementById('err').textContent = 'This field is required'; return; }
    document.getElementById('t').textContent = 'Review';
    document.getElementById('pane').innerHTML = '<p>City: ' + document.getElementById('a').value + '</p><p>Government employee: ' + g.value + '</p><button>Submit application</button>';
  }
</script></main>"""


def test_a_question_nobody_can_answer_but_the_applicant_is_asked_once_and_then_known(app_env, tmp_path, monkeypatch):
    """A required question the draft does not have and the profile does not answer. The take-over hands it over - once:
    the step is not given to an agent again and no navigator is sent to a step that waits for the applicant. The question
    joins the draft as an open question; answered there, the next run fills it and goes on without any agent."""
    from autoapply import db, drafts, executor, llm
    from autoapply.models import Application, Draft, Todo

    app_id, did = _one_question_draft(tmp_path, UNKNOWN_QUESTION, "unknown")
    db.set_setting("repair.enabled", True)
    calls = []
    label = "Have you been a government employee in the past three years?"

    def agent(goal, tools, *, system, max_steps=60, on_step=None):
        t = {x.name: x for x in tools}
        calls.append("fix" if "check_form" in t else "nav")
        if "check_form" in t:
            t["done"].fn(fixed=[], unfixed=[], cause="A required question that is not in the profile.", suggestion="",
                         needs_user=[{"label": label, "why": "The profile does not say.", "type": "radio", "options": ["No, never", "Yes"]}])
        else:
            t["done"].fn(state="blocked", why="a required answer is missing")
        return llm.AgentResult(final_text="done", steps=[{"tool": "done"}])

    handed = {}

    def user_window(driver, page, title, application_id, draft_id=None, **kw):
        handed.update(kw)
        handed["title"], handed["text"] = page.locator("#t").inner_text(), page.locator("#pane").inner_text()
        return {"status": "ready_to_submit", "error": "window closed"}

    monkeypatch.setattr(llm, "agent", agent)
    monkeypatch.setattr(executor, "_wait_for_manual_submit", user_window)
    executor.execute(app_id, did)

    assert calls == ["fix"]                                                    # asked once; not again, and no navigator
    # the applicant is told the question by its name, once - not the form's raw marks for the same thing
    assert [(x["kind"], x["label"]) for x in handed["leftovers"] if x["kind"] == "fix"] == [("fix", label)]
    assert len([x for x in handed["leftovers"] if x["kind"] == "form"]) == 1 and handed["title"] == "Work Eligibility"
    # the question is in the draft now, open, with its choices; and there is a card pointing at it
    with db.session() as s:
        d = s.get(Draft, did)
        new = next(a for a in d.answers if a["source"] == "unresolved")
        assert (new["id"], new["type"], new["options"], new["value"]) == ("@label:" + label, "radio", ["No, never", "Yes"], "")
        assert [u["label"] for u in d.unresolved] == [label] and any(q["id"] == new["id"] and q["options"] == ["No, never", "Yes"] for q in d.schema["questions"])
        assert s.query(Todo).filter_by(kind="answer", ref=f"draft:{did}", status="open").count() == 1
        # the draft is back with the applicant: pending again, and the application says it needs their answer
        assert d.review_status == "pending" and s.get(Application, app_id).status == "needs_input" and "草案里没有" in s.get(Application, app_id).last_event

    # the applicant answers it in the program and approves; the next run needs no agent at all and reaches the review page
    drafts.edit_answer(did, "@label:" + label, "No, never")
    with db.session() as s:
        assert s.get(Draft, did).unresolved == [] and s.get(Application, app_id).status == "draft_ready"
    drafts.approve(did)
    with db.session() as s:
        assert s.get(Application, app_id).status == "approved"
    monkeypatch.setattr(llm, "agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no agent should be needed once the question is answered")))
    handed.clear()
    executor.execute(app_id, did)
    assert handed["title"] == "Review" and "Government employee: no" in handed["text"] and [x for x in handed["leftovers"] if x["kind"] in ("fix", "form")] == []


def test_what_the_applicant_answers_in_the_window_is_kept_and_remembered(app_env, tmp_path, monkeypatch):
    """The question is handed over, and this time the applicant answers it right there in the window and submits. The
    answer is read from the page while the field is still on it, written into the draft, and remembered in the profile -
    the next form that asks the same thing does not need them."""
    from autoapply import db, executor, knowledge, llm
    from autoapply.models import Application, Draft, Todo

    html = UNKNOWN_QUESTION.replace("<button>Submit application</button>", "<button onclick=\"document.querySelector(\\'main\\').innerHTML = \\'<h1>Thank you for applying!</h1>\\'\">Submit application</button>")
    app_id, did = _one_question_draft(tmp_path, html, "typed")
    knowledge.write("profile", "# Profile\n\n## Standard answers\n\n- Lives in Vancouver.\n")
    db.set_setting("repair.enabled", True)
    label = "Have you been a government employee in the past three years?"

    def agent(goal, tools, *, system, max_steps=60, on_step=None):
        {x.name: x for x in tools}["done"].fn(fixed=[], unfixed=[], cause="Not in the profile.", suggestion="",
                                              needs_user=[{"label": label, "why": "The profile does not say.", "type": "radio", "options": ["No, never", "Yes"]}])
        return llm.AgentResult(final_text="done", steps=[{"tool": "done"}])

    real_wait = executor._wait_for_manual_submit

    def applicant(driver, page, *a, **kw):
        page.check("input[name=gov][value=no]")                    # they answer the question ...
        page.evaluate("setTimeout(() => { next(); document.querySelector('main button').click() }, 2600)")     # ... go on, and submit
        return real_wait(driver, page, *a, **kw)

    monkeypatch.setattr(llm, "agent", agent)
    monkeypatch.setattr(executor, "_wait_for_manual_submit", applicant)
    out = executor.execute(app_id, did)
    assert out["status"] == "submitted"
    with db.session() as s:
        d = s.get(Draft, did)
        row = next(a for a in d.answers if a["label"] == label)
        assert (row["value"], row["source"], row["basis"]) == ("No, never", "profile", "你在申请窗口里填的") and d.unresolved == [] and d.review_status == "approved"
        assert s.get(Application, app_id).status == "submitted" and s.query(Todo).filter_by(kind="answer", status="open").count() == 0
    assert f'Form question "{label}": answer "No, never".' in knowledge.read("profile")


def test_a_draft_names_the_steps_that_could_not_be_read(app_env):
    from autoapply import humanize

    note = ("Steps of this form that could not be read yet: Work Eligibility (not yet visible); Acknowledgement. The form shows them only after the earlier steps are filled; "
            "they are read the first time the form is filled, and what they ask is added to this draft.")
    zh = humanize.notes([note])[0] if hasattr(humanize, "notes") else humanize.note(note)
    assert "Work Eligibility (not yet visible); Acknowledgement" in zh and "读不到" in zh


LOCKED_STEPS = r"""<main><h1 id="t"></h1><div id="pane"></div>
<script>
  window.submitted = false; const saved = {};
  const steps = {
    contact: () => ['Contact information', '<label for="a">City</label><input id="a" required><button onclick="if (document.getElementById(\'a\').value) { saved.city = document.getElementById(\'a\').value; go(\'work\') }">Continue</button>'],
    work: () => ['Work Eligibility', '<label for="legal">Legal First Name</label><input id="legal" required>'
        + '<fieldset role="radiogroup" data-q="applied"><legend>Have you applied here before?</legend>'
        + '<label><input type="radio" name="applied" value="yes" checked>Yes</label> <label><input type="radio" name="applied" value="no">No</label></fieldset>'
        + '<fieldset role="radiogroup" aria-required="true" data-q="gov"><legend>Have you been a government employee in the past three years?</legend>'
        + '<label><input type="radio" name="gov" value="no">No, never</label> <label><input type="radio" name="gov" value="yes">Yes</label></fieldset>'
        + '<div id="err" role="alert"></div><button onclick="nextw()">Continue</button>'],
    review: () => ['Review & submit', '<p>City: ' + saved.city + '</p><p>Legal First Name: ' + saved.legal + '</p><p>Government employee: ' + saved.gov + '</p><button onclick="window.submitted = true">Submit application</button>'],
  };
  function nextw() {
    const g = document.querySelector('input[name=gov]:checked'), l = document.getElementById('legal').value;
    if (!l || !g) { document.getElementById('err').textContent = 'This field is required'; return; }
    saved.legal = l; saved.gov = g.value; go('review');
  }
  function go(name) { const [t, html] = steps[name](); document.getElementById('t').textContent = t; document.getElementById('pane').innerHTML = html; }
  go('contact');
</script></main>"""


def test_the_later_steps_of_a_form_are_read_by_walking_it_with_the_drafts_answers(app_env, tmp_path, monkeypatch):
    """The second step of this form opens only once the first is filled, so reading the form without filling anything saw
    one step. Before the applicant approves anything, the form is walked with the draft's own answers: the next step is
    read, what the profile answers is added, what only the applicant can answer comes back as an open question - and when
    they answer it, the walk goes on to the review page. Nothing is submitted and no window is handed to anyone.
    A step the walk stands on is read completely: a question the site already holds an answer to joins the draft as it
    stands, and every question read comes with where it is, so the next walk needs no agent."""
    from autoapply import db, drafts, executor, knowledge, llm
    from autoapply.ats.base import FormSchema, JobRef, Question
    from autoapply.models import Application, Draft, Job, Run, Task, Todo

    form = tmp_path / "locked.html"
    form.write_text(LOCKED_STEPS, encoding="utf-8")
    knowledge.write("profile", "# Profile\n\n- Name on documents: Alexander Chen\n")
    schema = FormSchema(ats="generic", tenant="locked.example.test", url=form.as_uri(), source="agent", pages=["Contact information", "Work Eligibility (not yet visible)", "Review & submit"],
                        questions=[Question(id="#a", label="City", type="text", required=True, page=0, locator={"selector": "#a"})])
    assert drafts.unseen_steps(schema) == ["Work Eligibility (not yet visible)"]
    schema.extra["unseen"] = drafts.unseen_steps(schema)
    ref = JobRef(ats="generic", tenant="locked.example.test", job_id="", url=form.as_uri(), host="locked.example.test")
    with db.session() as s:
        job = Job(source="manual", source_id="lock1", company="Acme", title="Analyst", apply_url=form.as_uri(), channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        app = Application(job_id=job.id, status="recon")
        s.add(app)
        s.flush()
        d = Draft(application_id=app.id, schema={**schema.to_dict(), "_ref": ref.__dict__}, review_status="pending", notes=["Steps of this form that could not be read yet: Work Eligibility (not yet visible). x"],
                  answers=[{"id": "#a", "label": "City", "type": "text", "options": [], "required": True, "page": 0, "value": "Vancouver", "basis": "profile",
                            "confidence": "high", "source": "profile", "sensitive": "", "sensitive_confirmed": False}])
        s.add(d)
        s.flush()
        app_id, did = app.id, d.id
    db.set_setting("repair.enabled", True)
    label = "Have you been a government employee in the past three years?"
    calls = []

    def agent(goal, tools, *, system, max_steps=60, on_step=None):
        t = {x.name: x for x in tools}
        calls.append("fix" if "check_form" in t else "nav")
        assert "THIS STEP HAS NOT BEEN READ BEFORE" in goal
        t["fill"].fn(selector="#legal", value="Alexander")
        report = dict(fixed=[], unfixed=[], cause="A step the draft had not seen.", suggestion="",
                      added=[{"label": "Legal First Name", "value": "Alexander", "basis": "Name on documents: Alexander Chen", "type": "text", "selector": "#legal"}],
                      held=[{"label": "Have you applied here before?", "value": "Yes", "type": "radio", "options": ["Yes", "No"], "selector": "[data-q=applied]"}])
        # a label that is not the form's wording is sent back: the driver could never find the question by it
        short = t["done"].fn(**report, needs_user=[{"label": "Government employee in the past three years...?", "why": "x", "type": "radio", "options": ["No, never", "Yes"]}])
        assert short.startswith("NOT ACCEPTED: these labels are not the form's own wording")
        out = t["done"].fn(**report, needs_user=[{"label": label, "why": "The profile does not say.", "type": "radio", "options": ["No, never", "Yes"],
                                                 "selector": "#radio-3f2a9c1e-77aa-4b1c-9d2e-0a1b2c3d4e5f"}])      # an id the form generates is not kept
        assert out == "recorded"
        return llm.AgentResult(final_text="done", steps=[{"tool": "done"}])

    monkeypatch.setattr(llm, "agent", agent)
    monkeypatch.setattr(executor, "_wait_for_manual_submit", lambda *a, **k: (_ for _ in ()).throw(AssertionError("a scouting walk never hands a window to the applicant")))
    out = drafts.scout(did)

    assert (out["status"], out["reached_review"], out["stopped_at"], out["added"], out["asked"]) == ("scouted", False, "Work Eligibility", 1, 1) and calls == ["fix"]
    with db.session() as s:
        d = s.get(Draft, did)
        by = {a["label"]: a for a in d.answers}
        assert by["Legal First Name"]["value"] == "Alexander" and by["Legal First Name"]["source"] == "agent_added"      # read from the step and answered from the profile
        assert by[label]["source"] == "unresolved" and [u["label"] for u in d.unresolved] == [label]                   # only the applicant can answer this one
        assert d.review_status == "pending" and s.get(Application, app_id).status == "needs_input"                     # the draft is shown with its open question, not as ready
        assert any(n.startswith('Reading the later steps stopped at "Work Eligibility"') for n in d.notes) and not any(n.startswith("Steps of this form that could not") for n in d.notes)
        assert drafts.needs_walk(d) and s.query(Todo).filter_by(kind="answer", ref=f"draft:{did}", status="open").count() == 1
        # the site's own answer is in the draft as it stands, and each question is known by where it is
        assert (by["Have you applied here before?"]["value"], by["Have you applied here before?"]["held"], by["Have you applied here before?"]["source"]) == ("Yes", True, "site")
        where = {q["label"]: q["locator"]["selector"] for q in d.schema["questions"]}
        assert where["Have you applied here before?"] == "[data-q=applied]" and where["Legal First Name"] == "#legal" and where[label] == "@label:" + label
        assert d.schema["extra"]["read"] == ["Contact information", "Work Eligibility"] and drafts.unseen_steps(drafts._schema_of(d)) == []
        assert s.query(Run).filter_by(kind="scout").count() == 1 and s.query(Run).filter_by(kind="execute").count() == 0

    # the applicant answers: the walk is queued again by itself and now reaches the review page without any agent
    drafts.edit_answer(did, "@label:" + label, "No, never")
    with db.session() as s:
        assert s.query(Task).filter_by(kind="scout", ref=f"draft:{did}", status="queued").count() == 1 and s.get(Application, app_id).status == "recon"
    monkeypatch.setattr(llm, "agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no agent is needed once every question has an answer")))
    out = drafts.scout(did)
    assert (out["status"], out["reached_review"]) == ("scouted", True)
    with db.session() as s:
        d = s.get(Draft, did)
        assert not drafts.needs_walk(d) and d.unresolved == [] and s.get(Application, app_id).status == "draft_ready"
        assert any(n.startswith("The later steps of this form were read") for n in d.notes)

    # approved, the form is filled without an agent and the applicant gets it at the review page - still not submitted by the program
    drafts.approve(did)
    handed = {}

    def user_window(driver, page, title, application_id, draft_id=None, **kw):
        handed.update(kw)
        handed["state"] = page.evaluate("({title: document.getElementById('t').textContent, submitted: window.submitted, gov: saved.gov, legal: saved.legal})")
        return {"status": "ready_to_submit", "error": "window closed"}

    monkeypatch.setattr(executor, "_wait_for_manual_submit", user_window)
    executor.execute(app_id, did)
    assert handed["state"] == {"title": "Review & submit", "submitted": False, "gov": "no", "legal": "Alexander"} and [x for x in handed["leftovers"] if x["kind"] in ("fix", "form")] == []


def test_the_walk_can_be_started_by_hand_for_a_draft_made_before_it_existed(app_env):
    """A draft from before unread steps were kept says which steps are unread (worked out from its pages), and the walk
    can be asked for on it - only while it waits for approval and has an answer for every question."""
    from fastapi.testclient import TestClient

    from autoapply import db, drafts
    from autoapply.api.main import app
    from autoapply.models import Application, Draft, Job, Task

    pages = ["Job-specific questions", "Work Eligibility (not yet visible)", "Voluntary Self-Identification (not yet visible)", "Review & submit"]
    q = {"id": "#a", "label": "City", "type": "text", "required": True, "options": [], "page": 0, "locator": {"selector": "#a"}}
    answer = {**q, "value": "Vancouver", "basis": "profile", "confidence": "high", "source": "profile", "sensitive": "", "sensitive_confirmed": False}
    with db.session() as s:
        job = Job(source="manual", source_id="old1", company="Acme", title="Analyst", apply_url="https://old.example.test/apply", channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        a = Application(job_id=job.id, status="draft_ready")
        s.add(a)
        s.flush()
        d = Draft(application_id=a.id, review_status="pending", answers=[answer], notes=[],
                  schema={"ats": "generic", "tenant": "old.example.test", "url": "https://old.example.test/apply", "source": "agent", "pages": pages, "questions": [q], "extra": {"notes": "x"}})
        s.add(d)
        s.flush()
        app_id, did = a.id, d.id
    c = TestClient(app)
    assert c.get(f"/api/drafts/{did}").json()["unseen"] == pages[1:3]            # the review page is not a step to read

    with db.session() as s:      # an open question first: there is nothing to walk the form with
        s.get(Draft, did).unresolved = [{"id": "@label:Why us?", "label": "Why us?"}]
    assert c.post(f"/api/drafts/{did}/scout").status_code == 400
    with db.session() as s:
        s.get(Draft, did).unresolved = []
    out = c.post(f"/api/drafts/{did}/scout")
    assert out.status_code == 200
    with db.session() as s:
        t = s.get(Task, out.json()["task_id"])
        assert (t.kind, t.ref, t.status) == ("scout", f"draft:{did}", "queued") and s.get(Application, app_id).status == "recon"

    with db.session() as s:      # six automatic rounds are the end of walking by itself; the draft does not stay "being read"
        d = s.get(Draft, did)
        d.schema = {**d.schema, "extra": {**d.schema["extra"], "scouted": 6}}
    assert drafts.scout(did) == {"skipped": "walked six times already"}
    with db.session() as s:
        assert s.get(Application, app_id).status == "draft_ready"
        s.get(Draft, did).review_status = "approved"
    assert c.post(f"/api/drafts/{did}/scout").status_code == 400                    # an approved draft is filled, not read


SKIPPED_STEP = r"""<main><h1 id="t"></h1><div id="pane"></div>
<script>
  window.submitted = false; const saved = {};
  const steps = {
    contact: () => ['Contact information', '<label for="a">City</label><input id="a" required><button onclick="if (document.getElementById(\'a\').value) { saved.city = document.getElementById(\'a\').value; go(\'review\') }">Continue</button>'],
    review: () => ['Review & submit', '<p>City: ' + saved.city + '</p><h2>Diversity</h2><p>Gender: Prefer not to say</p><button onclick="window.submitted = true">Submit application</button>'],
  };
  function go(name) { const [t, html] = steps[name](); document.getElementById('t').textContent = t; document.getElementById('pane').innerHTML = html; }
  go('contact');
</script></main>"""


def test_a_step_the_site_does_not_show_again_is_read_from_the_review_page(app_env, tmp_path, monkeypatch):
    """The site has a step complete from an earlier application and never opens it again, so no walk can stand on it.
    What the review page shows of it is read into the draft: the applicant sees the answer the site will send. Such an
    answer is the site's own - the program does not set it again and does not ask the applicant to confirm it later."""
    from autoapply import db, drafts, executor, llm
    from autoapply.ats.base import FormSchema, JobRef, Question
    from autoapply.models import Application, Draft, Job

    form = tmp_path / "skipped.html"
    form.write_text(SKIPPED_STEP, encoding="utf-8")
    schema = FormSchema(ats="generic", tenant="skipped.example.test", url=form.as_uri(), source="agent", pages=["Contact information", "Diversity (not yet visible)", "Review & submit"],
                        questions=[Question(id="#a", label="City", type="text", required=True, page=0, locator={"selector": "#a"})])
    schema.extra["read"] = ["Contact information"]
    ref = JobRef(ats="generic", tenant="skipped.example.test", job_id="", url=form.as_uri(), host="skipped.example.test")
    with db.session() as s:
        job = Job(source="manual", source_id="skip1", company="Acme", title="Analyst", apply_url=form.as_uri(), channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        app = Application(job_id=job.id, status="recon")
        s.add(app)
        s.flush()
        d = Draft(application_id=app.id, schema={**schema.to_dict(), "_ref": ref.__dict__}, review_status="pending", notes=[],
                  answers=[{"id": "#a", "label": "City", "type": "text", "options": [], "required": True, "page": 0, "value": "Vancouver", "basis": "profile",
                            "confidence": "high", "source": "profile", "sensitive": "", "sensitive_confirmed": False}])
        s.add(d)
        s.flush()
        app_id, did = app.id, d.id
    db.set_setting("repair.enabled", True)
    seen = []

    def agent(goal, tools, *, system, max_steps=60, on_step=None):
        t = {x.name: x for x in tools}
        seen.append("review" if "THIS IS THE REVIEW PAGE" in goal else "other")
        assert "Diversity (not yet visible)" in goal
        assert t["done"].fn(fixed=[], unfixed=[], cause="", suggestion="", held=[{"label": "Gender", "value": "Prefer not to say", "section": "Diversity"}]) == "recorded"
        return llm.AgentResult(final_text="done", steps=[{"tool": "done"}])

    monkeypatch.setattr(llm, "agent", agent)
    out = drafts.scout(did)
    assert (out["status"], out["reached_review"], out["held"], out["all_read"]) == ("scouted", True, 1, True) and seen == ["review"]
    with db.session() as s:
        d = s.get(Draft, did)
        row = next(a for a in d.answers if a["label"] == "Gender")
        assert (row["value"], row["held"], row["page"], row["required"]) == ("Prefer not to say", True, 1, False)       # filed under the step it belongs to
        assert not drafts.needs_walk(d) and s.get(Application, app_id).status == "draft_ready"
        assert any("1 answer(s) the employer's site already holds were read into the draft" in n for n in d.notes)

    # approved and filled: no agent, and the site's own answer is neither set again nor listed as "could not be confirmed"
    monkeypatch.setattr(llm, "agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError("nothing is left for an agent")))
    drafts.approve(did)
    handed = {}
    monkeypatch.setattr(executor, "_wait_for_manual_submit", lambda driver, page, title, application_id, draft_id=None, **kw: handed.update(kw) or {"status": "ready_to_submit", "error": "window closed"})
    executor.execute(app_id, did)
    assert handed["leftovers"] == []

    # the applicant changes it in the draft: it is theirs now, and filled like any other answer
    drafts.edit_answer(did, row["id"], "Woman")
    with db.session() as s:
        assert next(a for a in s.get(Draft, did).answers if a["label"] == "Gender")["held"] is False


def test_a_radio_question_known_by_the_label_of_one_choice_is_set_and_read_as_the_whole_group(app_env):
    """A take-over reports where a question is; for custom radio buttons that is often the label of one choice, because
    the input itself is covered by it and has an id that changes on every visit. The driver takes the group from it."""
    from playwright.sync_api import sync_playwright

    from autoapply.ats import generic_driver as g
    from autoapply.ats.base import FormSchema, Question

    html = """<div class="question"><label id="SPONSOR-label">Will you need sponsorship?</label>
      <div role="radiogroup" aria-labelledby="SPONSOR-label">
        <div class="c"><input type="radio" name="SPONSOR" id="radio-1a2b" value="YES"><label id="SPONSOR-option-0-label" for="radio-1a2b">Yes</label></div>
        <div class="c"><input type="radio" name="SPONSOR" id="radio-3c4d" value="NO"><label id="SPONSOR-option-1-label" for="radio-3c4d">No</label></div></div></div>
      <div class="question"><label id="VET-label">Are you a veteran?</label><div role="radiogroup" aria-labelledby="VET-label">
        <div class="c"><input type="radio" name="VET" id="radio-5e6f" value="YES"><label for="radio-5e6f">Yes</label></div>
        <div class="c"><input type="radio" name="VET" id="radio-7a8b" value="NO"><label for="radio-7a8b">No</label></div></div></div>"""
    q = Question(id="@label:Sponsorship", label="Sponsorship", type="radio", locator={"selector": "label#SPONSOR-option-0-label"})   # the label of "Yes"; the answer is "No"
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.set_content(html)
        assert g.get_value(page, q) == ""
        g.GenericDriver(FormSchema(ats="generic", tenant="radio.example.test", url="", source="agent", questions=[q])).fill_questions(page, [q], {q.id: "No"})
        assert g.get_value(page, q) == "No"
        assert page.evaluate("[...document.querySelectorAll('input:checked')].map(e => e.name + '=' + e.value)") == ["SPONSOR=NO"]      # the other question is untouched
        b.close()


def test_folded_answers_on_a_review_page_are_unfolded_and_nothing_else_is_clicked(app_env):
    from playwright.sync_api import sync_playwright

    from autoapply.ats import generic_driver as g

    html = """<h1>Review &amp; submit</h1>
      <section><h2>Work Eligibility</h2><a href="#" onclick="this.nextElementSibling.hidden = false; this.textContent = 'Hide answers'; return false">Show all answers</a><div hidden>Sponsorship: Yes</div></section>
      <section><h2>Education</h2><button class="display-all-link" aria-expanded="false" aria-label="Show all answers Education"
        onclick="this.nextElementSibling.hidden = false; this.setAttribute('aria-expanded', 'true')">Show all answers<i class="fa"></i></button><div hidden>Degree: BASc</div></section>
      <a href="https://elsewhere.example.test/job">View details</a>
      <button type="submit" onclick="window.sent = true">Submit application</button>"""
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.set_content(html)
        assert "Sponsorship: Yes" not in page.inner_text("body")
        assert g.GenericDriver.open_summaries(page) == 2
        text = page.inner_text("body")
        assert "Sponsorship: Yes" in text and "Degree: BASc" in text
        assert page.evaluate("window.sent") is None and page.url == "about:blank"      # no submission, no leaving the page
        b.close()
