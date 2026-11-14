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
