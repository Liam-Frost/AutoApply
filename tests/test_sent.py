"""An application that has been sent - however the program learns of it - leaves nothing waiting; and a Workday session
the applicant signed in to is recognised."""
from __future__ import annotations

from datetime import datetime

import pytest


def _application(s, *, status="failed", url="https://x.test/apply", company="Acme"):
    from autoapply.models import Application, Draft, Job

    job = Job(source="manual", source_id=url, company=company, title="Engineer Intern", apply_url=url, channel="employer site", jd_text="x" * 300)
    s.add(job)
    s.flush()
    app = Application(job_id=job.id, status=status)
    s.add(app)
    s.flush()
    d = Draft(application_id=app.id, review_status="pending", answers=[], notes=[], schema={"ats": "generic", "tenant": "x.test", "url": url, "questions": [], "pages": ["Application"]})
    s.add(d)
    s.flush()
    return job, app, d


def test_a_confirmation_for_an_application_the_program_took_for_failed_settles_everything(app_env, monkeypatch):
    """The program filled the form, the applicant submitted, the window went away before a confirmation page was seen, and
    a second run ended in an error. Then the employer's confirmation arrives. The mail is right: the application is
    confirmed, its "failed" card, the sign-in card raised for it and its waiting draft are closed, its queued work is
    cancelled - and asking to fill it again is answered in plain words instead of starting anything."""
    from fastapi.testclient import TestClient

    from autoapply import db, llm, mail, mailbox, notify
    from autoapply.api.main import app as api
    from autoapply.models import Application, Draft, Run, Task, Todo

    with db.session() as s:
        job, a, d = _application(s, status="failed")
        d.review_status = "approved"
        d2 = Draft(application_id=a.id, review_status="pending", version=2, answers=[], notes=[], schema=dict(d.schema))     # sent back with a new question
        s.add(d2)
        s.add(Run(kind="execute", ref=f"application:{a.id}", ats="generic", ok=0, steps=[], dir="", created_at=datetime(2026, 11, 15, 7, 13)))
        s.flush()
        aid, did, did2, jid = a.id, d.id, d2.id, job.id
        s.add(Todo(kind="failed", title="Acme: failed", ref=f"application:{aid}", payload={"draft_id": did}))
        s.add(Todo(kind="takeover", title="Acme", ref="account:generic:x.test", payload={"job_url": "https://x.test/apply", "draft_id": did}))
        s.add(Todo(kind="answer", title="Acme", ref=f"draft:{did2}", payload={"draft_id": did2}))
        s.add(Todo(kind="takeover", title="Other", ref="account:generic:other.test", payload={"job_url": "https://other.test/apply"}))       # someone else's
        s.add(Task(kind="execute", ref=f"application:{aid}", status="queued", payload={"draft_id": did}))
        s.add(Task(kind="scout", ref=f"draft:{did2}", status="queued", payload={"draft_id": did2}))
    msg = mailbox.Message(id="m1", sender="noreply@x.test", subject="Thank you for Applying to Acme!", body="Acme received", date=datetime(2026, 11, 15, 7, 14))
    monkeypatch.setattr(llm, "json", lambda prompt, schema, **kw: {"category": "confirmation", "company": "Acme", "job_title": "Engineer Intern", "received": True, "summary": "received"})
    monkeypatch.setattr(mailbox, "fetch", lambda since, limit=50, job_related=False: [msg])
    monkeypatch.setattr(notify, "send", lambda *a, **k: True)

    assert mail.track()["status_updates"] == 1
    with db.session() as s:
        a = s.get(Application, aid)
        assert a.status == "confirmed" and a.submitted_at == datetime(2026, 11, 15, 7, 14) and a.evidence["mail_id"] == "m1" and a.job.status == "applied"
        assert {t.title: t.status for t in s.query(Todo)} == {"Acme: failed": "done", "Acme": "done", "Other": "open"}
        assert s.get(Draft, did).review_status == "approved" and s.get(Draft, did2).review_status == "closed"
        assert {t.kind: t.status for t in s.query(Task)} == {"execute": "cancelled", "scout": "cancelled"}

    c = TestClient(api)
    r = c.post(f"/api/drafts/{did}/execute")
    assert r.status_code == 409 and "已确认收到" in r.json()["detail"] and "already" not in r.json()["detail"]
    assert c.post(f"/api/applications/{aid}/mark-submitted").status_code == 409 and c.post(f"/api/jobs/{jid}/mark-submitted").status_code == 409


def test_a_confirmation_read_while_the_form_was_being_filled_again_is_applied_afterwards(app_env):
    """The mail arrived while a second run had the application "executing"; the run then ended as failed and the mail had
    changed nothing. Looking at the mail again puts it right. A mail for an application whose form was never filled
    still confirms nothing."""
    from autoapply import db, mail
    from autoapply.models import Application, MailEvent, Run, Todo

    with db.session() as s:
        _, a, _ = _application(s, status="failed")
        _, b, _ = _application(s, status="needs_input", url="https://y.test/apply", company="Beta")
        s.add(Run(kind="execute", ref=f"application:{a.id}", ats="generic", ok=0, steps=[], dir="", created_at=datetime(2026, 11, 15, 7, 13)))
        for app_ in (a, b):
            s.add(MailEvent(message_id=f"m{app_.id}", sender="x", subject="Thank you for applying", received_at=datetime(2026, 11, 15, 7, 14), category="confirmation",
                            application_id=app_.id, company_guess="x", summary="received"))
        s.add(Todo(kind="failed", title="t", ref=f"application:{a.id}"))
        aid, bid = a.id, b.id
    assert mail.reconcile() == 1 and mail.reconcile() == 0
    with db.session() as s:
        assert (s.get(Application, aid).status, s.get(Application, bid).status) == ("confirmed", "needs_input")
        assert s.query(Todo).one().status == "done"


def test_pressing_submit_loads_another_page_and_that_is_not_a_closed_window(app_env, monkeypatch):
    """Between the review page and the page after it there is a moment with nothing to read. It was taken for the window
    having been closed: the run ended, the window was closed on the applicant, and the submission went unnoticed."""
    from autoapply import executor, notify

    monkeypatch.setattr(notify, "add_todo", lambda *a, **k: 1)

    class Page:
        url = "https://x.test/apply"
        calls = 0
        closed_by_program = False

        def is_closed(self):
            return False

        def evaluate(self, js, *a):
            Page.calls += 1
            if Page.calls in (2, 3, 4):
                raise RuntimeError("Execution context was destroyed, most likely because of a navigation")
            if Page.calls > 4:      # the page after Submit: it says so in its title only
                Page.url = "https://x.test/applicant/jobs/1/summary"
                return {"title": "Thank you for your application", "text": "Next steps\nWe will review your application."}
            return {"title": "Apply", "text": "Review & submit"}

        def wait_for_timeout(self, ms):
            if 2 <= Page.calls <= 4:
                raise RuntimeError("Target navigated")

    class Driver:
        def confirmation(self, page):
            return {"url": page.url, "text": "Thank you for your application"} if "summary" in page.url else None

    monkeypatch.setattr(executor.time, "sleep", lambda s: None)
    out = executor.wait_for_the_applicant(Driver(), Page(), "Acme", 1)
    assert out == {"status": "submitted", "evidence": {"url": "https://x.test/applicant/jobs/1/summary", "text": "Thank you for your application"}}


def test_a_site_that_says_already_applied_is_a_sent_application_not_a_sign_in_problem(app_env, tmp_path, monkeypatch):
    """Filling again a form whose submission went unnoticed opens a page that says "You have already applied for this
    position". That was read as "the sign-in has expired". It is the answer: the application is sent."""
    from autoapply import db, drafts, executor, llm
    from autoapply.ats.base import FormSchema, JobRef, Question
    from autoapply.models import Application, Draft, Job, Todo

    page = tmp_path / "dup.html"
    page.write_text("<title>Thank you for your application</title><main><h1>Summary</h1><h2>You have already applied for this position</h2>"
                    "<p>Your application will be processed shortly.</p><a href='#'>View my applications</a></main>", encoding="utf-8")
    schema = FormSchema(ats="generic", tenant="dup.example.test", url=page.as_uri(), source="agent", pages=["Questions", "Review & submit"],
                        questions=[Question(id="#a", label="City", type="text", required=True, page=0, locator={"selector": "#a"})])
    ref = JobRef(ats="generic", tenant="dup.example.test", job_id="", url=page.as_uri(), host="dup.example.test")
    with db.session() as s:
        job = Job(source="manual", source_id="dup1", company="Acme", title="Analyst", apply_url=page.as_uri(), channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        app = Application(job_id=job.id, status="draft_ready")
        s.add(app)
        s.flush()
        d = Draft(application_id=app.id, schema={**schema.to_dict(), "_ref": ref.__dict__}, review_status="pending", notes=[],
                  answers=[{"id": "#a", "label": "City", "type": "text", "options": [], "required": True, "page": 0, "value": "Vancouver", "basis": "profile",
                            "confidence": "high", "source": "profile", "sensitive": "", "sensitive_confirmed": False}])
        s.add(d)
        s.flush()
        app_id, did = app.id, d.id
        s.add(Todo(kind="failed", title="Acme: failed", ref=f"application:{app_id}", payload={"draft_id": did}))
    monkeypatch.setattr(llm, "agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no agent has anything to do here")))
    monkeypatch.setattr(executor, "_wait_for_manual_submit", lambda *a, **k: (_ for _ in ()).throw(AssertionError("there is no form to hand over")))
    drafts.approve(did)
    out = executor.execute(app_id, did)
    assert out["status"] == "submitted"
    with db.session() as s:
        a = s.get(Application, app_id)
        assert a.status == "submitted" and a.submitted_at is not None and "already applied" in a.evidence["text"].lower() and "已经申请过" in a.last_event
        assert [t.status for t in s.query(Todo).filter(Todo.kind.in_(("failed", "takeover", "submit")))] == ["done"]


def test_the_page_route_serves_only_the_built_interface(app_env):
    from fastapi.testclient import TestClient

    from autoapply import config
    from autoapply.api.main import app as api

    if not (config.FRONTEND_DIST / "index.html").exists():
        pytest.skip("the interface is not built here")
    c = TestClient(api)
    index = c.get("/").text
    for path in ("/..%2Fpackage.json", "/..%2F..%2Fpyproject.toml", "/assets/..%2F..%2F..%2Fpyproject.toml"):
        r = c.get(path)
        assert "autoapply-frontend" not in r.text and "[project]" not in r.text, path
        assert r.status_code == 404 or r.text == index, path


# Workday draws the header signed out first and changes it once it knows who is there; the page's content comes after that.
WD_HOME = """<header data-automation-id="header"><div data-automation-id="utilityButtonBar"><button data-automation-id="utilityMenuButton">Menu</button>
  <button data-automation-id="utilityButtonSignIn">Sign In</button></div>
  <nav data-automation-id="navigationContainer"><a data-automation-id="navigationItem-Search for Jobs">Search for Jobs</a></nav></header>
  <main data-automation-id="CandidateHomePage"></main>
  <script>const signedIn = %s;
    setTimeout(() => { if (signedIn) document.querySelector('[data-automation-id=utilityButtonSignIn]').outerHTML = '<button data-automation-id="utilityButtonAccountTasksMenu">me</button>'; }, 1200);
    setTimeout(() => { document.querySelector('main').innerHTML = '<h1 data-automation-id="welcomeMsgHeader">Welcome</h1>'; }, signedIn ? 1500 : 900);</script>"""
WD_HOME_IN, WD_HOME_OUT = WD_HOME % "true", WD_HOME % "false"
WD_LOGIN = """<header data-automation-id="header"><div data-automation-id="utilityButtonBar"></div></header><main data-automation-id="signInContent">
  <input data-automation-id="email"><input data-automation-id="password" type="password"><button data-automation-id="signInSubmitButton">Sign In</button></main>"""


def test_a_workday_session_is_told_by_what_the_page_shows_and_a_failed_page_is_not_a_failed_password(app_env, monkeypatch):
    """The candidate home shows "Sign In" for a moment before it shows the account menu. The program looked at the first
    of the two, so a session the applicant had just signed in to looked signed out; the sign-in page then sent the
    program on to the candidate home, where it waited for an e-mail field until it gave up - and counted that against
    the stored password."""
    from playwright.sync_api import sync_playwright

    from autoapply import auth, browser, secrets
    from autoapply.ats.base import JobRef, NeedsHuman
    from autoapply.ats.workday import WorkdayDriver

    ref = JobRef("workday", "acme", "R1", "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/x_R1", "acme.wd5.myworkdayjobs.com", extra={"site": "Careers", "job_path": "x_R1"})
    drv = WorkdayDriver()
    state = {"signed_in": True}

    def serve(route):
        url = route.request.url
        if url.endswith("/userHome"):
            route.fulfill(body=WD_HOME_IN if state["signed_in"] else WD_HOME_OUT, content_type="text/html")
        elif url.endswith("/login"):
            body = "<script>location.replace('/en-US/Careers/userHome')</script>" if state["signed_in"] else WD_LOGIN
            route.fulfill(body=body, content_type="text/html")
        else:
            route.fulfill(body="", content_type="text/html")

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.route("**/*", serve)
        assert drv.is_logged_in(page, ref) is True
        drv.login(page, ref, "me@example.test", "not-used")       # the sign-in page sends a signed-in session on: nothing to type, no error
        assert page.url.endswith("/userHome")
        state["signed_in"] = False
        assert drv.is_logged_in(page, ref) is False

        # the sign-in page cannot be worked (here: it never shows its fields): a card for the applicant, the password not blamed
        auth.upsert_account(ref.tenant_key, ats="workday", host=ref.host, email="me@example.test", status="ok")
        secrets.set_password(ref.tenant_key, "pw") if hasattr(secrets, "set_password") else auth.upsert_account(ref.tenant_key, password="pw")
        monkeypatch.setattr(drv, "login", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("Locator.wait_for: Timeout 20000ms exceeded")))
        monkeypatch.setattr(browser, "save_state", lambda *a, **k: None)
        for _ in range(3):
            with pytest.raises(NeedsHuman):
                auth.ensure_session(page, drv, ref)
        assert auth.account(ref.tenant_key)["fail_count"] == 0 and "Timeout" in auth.account(ref.tenant_key)["last_error"]
        b.close()


def test_rows_the_site_already_holds_are_left_alone_and_one_bad_field_does_not_end_the_reading(app_env):
    """Three website rows carried over from the last application, in another order than the draft lists them: retyping
    them makes two rows equal for a moment, and the form refuses the step. And a field that cannot be worked while a
    form is being read is reported, not fatal."""
    from playwright.sync_api import sync_playwright

    from autoapply.ats.base import DriverError, FormSchema, Question
    from autoapply.ats.workday import WorkdayDriver

    html = """<main><input id="webAddress-4--url" value="https://github.com/me"><input id="webAddress-5--url" value="https://me.example/">
      <input id="webAddress-6--url" value="https://www.linkedin.com/in/me"><input id="city" value=""></main>
      <script>window.typed = 0; document.querySelectorAll('input').forEach((e) => e.addEventListener('input', () => window.typed++));</script>"""
    qs = [Question(id=f"webAddress-{i}--url", label="URL", type="text", page=0) for i in (4, 5, 6)] + [Question(id="city", label="City", type="text", page=0),
                                                                                                      Question(id="gone", label="Gone", type="text", page=0)]
    schema = FormSchema(ats="workday", tenant="acme", questions=qs)
    fill = {"webAddress-4--url": "https://www.linkedin.com/in/me", "webAddress-5--url": "https://github.com/me", "webAddress-6--url": "https://me.example", "city": "Richmond", "gone": "x"}
    drv = WorkdayDriver()
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.set_content(html)
        failed = drv.fill_page(page, schema, 0, fill, tolerant=True)
        assert [(q.id, why) for q, why in failed] == [("gone", "field not found on page")]
        assert page.locator("#city").input_value() == "Richmond"
        assert [page.locator(f"[id='webAddress-{i}--url']").input_value() for i in (4, 5, 6)] == ["https://github.com/me", "https://me.example/", "https://www.linkedin.com/in/me"]
        assert page.evaluate("window.typed") == 1                          # only the city was typed
        with pytest.raises(DriverError):                                   # filling an approved draft stays strict
            drv.fill_page(page, schema, 0, fill)
        # one entry really is new: the rows are emptied first, then filled, so no entry meets its own copy
        fill["webAddress-6--url"] = "https://new.example"
        drv.fill_page(page, FormSchema(ats="workday", tenant="acme", questions=qs[:3]), 0, fill)
        assert [page.locator(f"[id='webAddress-{i}--url']").input_value() for i in (4, 5, 6)] == ["https://www.linkedin.com/in/me", "https://github.com/me", "https://new.example"]
        b.close()


def test_answering_a_form_that_stopped_while_being_read_reads_on_with_that_answer(app_env):
    """A Workday form is read by filling it. It stopped at a step with a question only the applicant can answer. Their
    answer starts the reading again by itself - before any approval - and is used there, and in the draft that follows."""
    from autoapply import db, drafts
    from autoapply.models import Application, Draft, Task

    q = {"id": "source--source", "label": "How Did You Hear About Us?", "type": "select", "options": [], "required": True, "page": 0}
    row = {**q, "value": "", "basis": "", "confidence": "low", "source": "unresolved", "sensitive": "", "sensitive_confirmed": False}
    with db.session() as s:
        job, a, d = _application(s, status="needs_input")
        d.schema = {"ats": "workday", "tenant": "acme", "source": "walk", "pages": ["My Information"], "questions": [q],
                    "extra": {"stopped_at": {"page": 0, "errors": ["required"]}, "steps": ["My Information", "My Experience", "Review"]}}
        d.answers, d.unresolved = [row], [row]
        aid, did, jid = a.id, d.id, job.id
    drafts.edit_answer(did, "source--source", "LinkedIn")
    with db.session() as s:
        t = s.query(Task).filter_by(kind="recon").one()
        assert (t.ref, t.status, t.payload["read_on"]) == (f"job:{jid}", "queued", did) and s.get(Application, aid).status == "recon"
    given = drafts._given(aid)
    fresh = {"answers": [{**row}, {"id": "x", "label": "City", "type": "text", "options": [], "required": True, "value": "", "source": "unresolved", "sensitive": ""}], "unresolved": []}
    assert drafts._use_given(fresh, given) == 1
    assert fresh["answers"][0]["value"] == "LinkedIn" and fresh["answers"][0]["source"] == "profile" and [u["label"] for u in fresh["unresolved"]] == ["City"]


def test_saving_the_settings_page_is_not_refused_over_the_programs_own_bookkeeping(app_env):
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app as api

    db.set_setting("migrated.page_ids", True)
    c = TestClient(api)
    got = c.get("/api/settings").json()["settings"]
    assert "migrated.page_ids" not in got and "draft.min_score" in got or "migrated.page_ids" not in got
    assert c.put("/api/settings", json={"settings": {**got, "migrated.page_ids": True}}).status_code == 200


def test_a_confirmation_link_from_an_e_mail_is_opened_only_when_it_is_the_sites_own(app_env, monkeypatch):
    """Signing up often ends with "click the link we sent you". The program opens it - when it leads to the very site it
    is signing up on, over https. A link to another domain, a mail service's redirect, a look-alike host: not opened, and
    the applicant is told to do it. The site's password is typed on the site's own pages only."""
    from datetime import datetime, timezone

    from autoapply import mail, mailbox

    ok = [("https://www.metacareers.com/confirm?token=abc", "www.metacareers.com"), ("https://auth.metacareers.com/v/1", "www.metacareers.com"),
          ("https://ciena.wd5.myworkdayjobs.com/activate/1", "ciena.wd5.myworkdayjobs.com"), ("https://jobs.acme.co.uk/verify", "careers.acme.co.uk")]
    bad = [("http://www.metacareers.com/confirm", "www.metacareers.com"), ("https://metacareers.com.evil.io/confirm", "www.metacareers.com"),
           ("https://click.mailservice.net/ls/click?upn=1", "www.metacareers.com"), ("https://other.wd5.myworkdayjobs.com/activate", "ciena.wd5.myworkdayjobs.com"),
           ("https://user:pw@www.metacareers.com/confirm", "www.metacareers.com"), ("https://10.0.0.5/confirm", "www.metacareers.com"),
           ("https://www.metacareers.com:8443/confirm", "www.metacareers.com"), ("https://evil.co.uk/verify", "careers.acme.co.uk")]
    assert [mail.link_refusal(u, h) for u, h in ok] == [""] * len(ok)
    assert all(mail.link_refusal(u, h) for u, h in bad)

    now = datetime.now(timezone.utc)
    box = {"msgs": [mailbox.Message(id="1", sender="Meta Careers <no-reply@metacareers.com>", subject="Confirm your Career Profile email address",
                                    body="Hi, confirm here: https://click.mailservice.net/ls/click?upn=1 thanks", date=now)]}
    monkeypatch.setattr(mailbox, "fetch", lambda since, limit=50, job_related=False: box["msgs"])
    monkeypatch.setattr(mail.time, "sleep", lambda s: None)
    got = mail.wait_for_verification(sender_hint="www.metacareers.com", timeout=1, since=now, site_host="www.metacareers.com")
    assert got.startswith("refused: leads to click.mailservice.net")
    box["msgs"][0].body = "Hi, confirm here: https://www.metacareers.com/confirm?token=abc thanks"
    assert mail.wait_for_verification(sender_hint="www.metacareers.com", timeout=1, since=now, site_host="www.metacareers.com") == "https://www.metacareers.com/confirm?token=abc"


def test_what_should_happen_by_itself_does(app_env, monkeypatch):
    """Every site is read by the agent. A posting that comes to qualify for a draft after it was scored gets one (the
    threshold was lowered); a draft whose form still has unread steps is read on without anyone pressing a button; and a
    regular job counts its interval from its last run, not from the start of the program."""
    from datetime import timedelta

    from fastapi.testclient import TestClient

    from autoapply import config, db, drafts, generic, scoring, tasks
    from autoapply.api.main import app as api
    from autoapply.models import Application, Draft, Job, Task, now

    assert config.DEFAULT_SETTINGS["agent.reads"] == ["*"]
    db.set_setting("agent.reads", ["*"])
    seen = []
    monkeypatch.setattr(generic, "recon", lambda job, ref, run_dir: seen.append(ref.ats) or (_ for _ in ()).throw(RuntimeError("the agent was asked")))
    with db.session() as s:
        gh = Job(source="greenhouse", source_id="g1", company="Acme", title="Intern", apply_url="https://boards.greenhouse.io/acme/jobs/123", channel="employer site", jd_text="x" * 300, score=7.5, status="scored")
        low = Job(source="manual", source_id="l1", company="Beta", title="Intern", apply_url="https://beta.example/apply", channel="employer site", jd_text="x" * 300, score=6.0, status="scored")
        s.add_all([gh, low])
        s.flush()
        gid, lid = gh.id, low.id
    with pytest.raises(RuntimeError, match="the agent was asked"):
        with db.session() as s:
            j = s.get(Job, gid)
            s.expunge(j)
        drafts.recon(j, None)
    assert seen == ["greenhouse"]

    # the threshold: 8 by default - nothing qualifies; lowered to 7 through the settings page - the 7.5 gets its draft
    assert scoring.queue_qualifying() == 0
    c = TestClient(api)
    assert c.put("/api/settings", json={"settings": {"queue.min_score_for_draft": 7}}).status_code == 200
    with db.session() as s:
        assert [(t.kind, t.ref) for t in s.query(Task).filter_by(kind="recon")] == [("recon", f"job:{gid}")] and s.get(Job, gid).status == "queued" and s.get(Job, lid).status == "scored"
    assert scoring.queue_qualifying() == 0      # not twice

    # a draft with unread steps: its reading is queued by itself
    with db.session() as s:
        for i, unresolved in enumerate(([], [{"id": "x", "label": "Why us?"}])):
            _, a, d = _application(s, status="draft_ready", url=f"https://w{i}.example/apply", company=f"W{i}")
            d.schema = {"ats": "generic", "tenant": f"w{i}.example", "source": "agent", "pages": ["One", "Two (not yet visible)", "Review"],
                        "questions": [{"id": "#a", "label": "City", "type": "text", "page": 0, "locator": {"selector": "#a"}}], "extra": {"read": ["One"]}}
            d.unresolved = unresolved
        s.flush()
        ready = s.query(Draft).order_by(Draft.id).all()[-2].id
    db.set_setting("recon.provisional", False)      # without stand-ins a form cannot be walked past an open question
    assert drafts.walk_pending() == 1
    with db.session() as s:
        assert [(t.kind, t.ref) for t in s.query(Task).filter_by(kind="scout")] == [("scout", f"draft:{ready}")]
    assert drafts.walk_pending() == 0
    db.set_setting("recon.provisional", True)       # with them (the default) it is walked to its end first, and the applicant is asked once
    assert drafts.walk_pending() == 1
    with db.session() as s:
        assert s.query(Task).filter_by(kind="scout").count() == 2

    # a scan that last ran eleven hours ago, every twelve hours: due in one hour, whenever the program was started
    with db.session() as s:
        s.add(Task(kind="discover", ref="schedule", status="done", created_at=now() - timedelta(hours=11), finished_at=now() - timedelta(hours=11)))
    assert abs((now() - tasks.last_run("discover")).total_seconds() - 11 * 3600) < 5
    rows = {r["kind"]: r for r in c.get("/api/schedule").json()}
    assert rows["discover"]["minutes"] == 720 and rows["discover"]["last"] and rows["mail"]["last"] is None


TWO_STEPS = r"""<main><h1 id="t"></h1><div id="pane"></div>
<script>
  window.sent = 0; const saved = {};
  const steps = {
    contact: () => ['Contact information', '<label for="a">City</label><input id="a" required><button onclick="if (document.getElementById(\'a\').value) { saved.city = document.getElementById(\'a\').value; go(\'work\') }">Continue</button>'],
    work: () => ['Work Eligibility', '<label for="visa">Visa status</label><input id="visa" name="visa" required><button onclick="if (document.getElementById(\'visa\').value) { saved.visa = document.getElementById(\'visa\').value; go(\'review\') }">Continue</button>'],
    review: () => ['Review & submit', '<p>City: ' + saved.city + '</p><p>Visa status: ' + saved.visa + '</p><button onclick="window.sent++; go(\'done\')">Submit application</button>'],
    done: () => ['Thank you for applying', '<p>Thank you for applying. We have received your application for Analyst.</p>'],
  };
  function go(name) { const [t, html] = steps[name](); document.getElementById('t').textContent = t; document.getElementById('pane').innerHTML = html; }
  go('contact');
</script></main>"""


def _explored(s, form, host, *, status="recon"):
    from autoapply.ats.base import FormSchema, JobRef, Question
    from autoapply.models import Application, Draft, Job

    schema = FormSchema(ats="generic", tenant=host, url=form.as_uri(), source="agent", pages=["Contact information", "Work Eligibility (not yet visible)", "Review & submit"],
                        questions=[Question(id="#a", label="City", type="text", required=True, page=0, locator={"selector": "#a"})])
    schema.extra["read"] = ["Contact information"]
    ref = JobRef(ats="generic", tenant=host, job_id="", url=form.as_uri(), host=host)
    job = Job(source="manual", source_id=form.name, company="Acme", title="Analyst", apply_url=form.as_uri(), channel="employer site", jd_text="x" * 300)
    s.add(job)
    s.flush()
    app = Application(job_id=job.id, status=status)
    s.add(app)
    s.flush()
    d = Draft(application_id=app.id, schema={**schema.to_dict(), "_ref": ref.__dict__}, review_status="pending", notes=[],
              answers=[{"id": "#a", "label": "City", "type": "text", "options": [], "required": True, "page": 0, "value": "Vancouver", "basis": "profile",
                        "confidence": "high", "source": "profile", "sensitive": "", "sensitive_confirmed": False}])
    s.add(d)
    s.flush()
    return app.id, d.id


def test_what_the_agent_learns_on_a_site_is_used_on_its_next_posting_and_an_approved_draft_is_submitted(app_env, tmp_path, monkeypatch):
    """First posting on a site: the agent reads the second step (once) and the walk reaches the review. What it found
    there - which question, what kind of control, where - is kept as the site's plan. The applicant approves; the
    program fills the form and submits it, because that is their setting and nothing was left for them: the agent having
    worked on the form is no reason to hold it back. Second posting on the same site: the step is taken from the plan,
    answered from the profile and filled by the driver - no agent at all."""
    from autoapply import answers, db, drafts, executor, knowledge, llm, siteplan
    from autoapply.models import Application, Draft, Todo

    knowledge.write("profile", "# Profile\n\n- Visa status: study permit with co-op work permit\n")
    monkeypatch.setattr(executor, "_wait_for_manual_submit", lambda *a, **k: (_ for _ in ()).throw(AssertionError("nothing here is the applicant's to do")))
    calls = []

    def agent(goal, tools, *, system, max_steps=60, on_step=None):
        t = {x.name: x for x in tools}
        calls.append("read" if "THIS STEP HAS NOT BEEN READ BEFORE" in goal else "other")
        t["fill"].fn(selector="#visa", value="Study permit with co-op work permit")
        assert t["done"].fn(fixed=[], unfixed=[], cause="", suggestion="", added=[{"label": "Visa status", "value": "Study permit with co-op work permit",
                                                                                  "basis": "Visa status: study permit with co-op work permit", "type": "text", "selector": "[name=visa]"}]) == "recorded"
        return llm.AgentResult(final_text="done", steps=[{"tool": "done"}])

    monkeypatch.setattr(llm, "agent", agent)
    first = tmp_path / "first.html"
    first.write_text(TWO_STEPS, encoding="utf-8")
    with db.session() as s:
        app1, d1 = _explored(s, first, "plan.example.test")
    out = drafts.scout(d1)
    assert (out["reached_review"], out["added"], calls) == (True, 1, ["read"])
    plan = siteplan.step("site-plan.example.test", "Work Eligibility")
    assert [(q["label"], q["type"], q["selector"]) for q in plan] == [("Visa status", "text", "[name=visa]")]
    assert "Study permit" not in siteplan._path("site-plan.example.test").read_text(encoding="utf-8")      # structure only, never an answer

    # approved: filled and submitted by the program; the confirmation page is the evidence
    monkeypatch.setattr(llm, "agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no agent is needed for a form that was walked once")))
    drafts.approve(d1)
    res = executor.execute(app1, d1)
    assert res["status"] == "submitted"
    with db.session() as s:
        a = s.get(Application, app1)
        assert a.status == "submitted" and "thank you for applying" in a.evidence["text"].lower() and s.query(Todo).filter_by(status="open").count() == 0

    # the next posting on the same site: the plan stands in for the agent
    monkeypatch.setattr(answers, "resolve", lambda schema, job, **kw: {"answers": [
        {"id": q.id, "label": q.label, "type": q.type, "options": q.options, "required": q.required, "page": q.page, "value": "Study permit with co-op work permit",
         "basis": "Visa status: study permit with co-op work permit", "confidence": "high", "source": "profile", "sensitive": "", "sensitive_confirmed": False} for q in schema.questions],
        "unresolved": [], "materials": [], "notes": [], "new_rules": []})
    second = tmp_path / "second.html"
    second.write_text(TWO_STEPS, encoding="utf-8")
    with db.session() as s:
        app2, d2 = _explored(s, second, "plan.example.test")
    out = drafts.scout(d2)
    assert (out["status"], out["reached_review"]) == ("scouted", True)
    with db.session() as s:
        d = s.get(Draft, d2)
        row = next(a for a in d.answers if a["label"] == "Visa status")
        assert row["value"] == "Study permit with co-op work permit" and not d.unresolved
        assert next(q for q in d.schema["questions"] if q["label"] == "Visa status")["locator"]["selector"] == "[name=visa]"

    # a site that has changed its form: the plan's place is gone - counted, the agent reads again, and the second miss drops the entry
    siteplan.missed("site-plan.example.test", "Work Eligibility", ["Visa status"])
    assert siteplan.step("site-plan.example.test", "Work Eligibility")
    siteplan.missed("site-plan.example.test", "Work Eligibility", ["Visa status"])
    assert siteplan.step("site-plan.example.test", "Work Eligibility") == []


def test_a_run_that_leaves_something_for_the_applicant_is_not_submitted_by_the_program(app_env, tmp_path, monkeypatch):
    """The same form, but the second step asks something the draft does not have and the profile does not say. The
    program does not submit: it stops and gives the window to the applicant."""
    from autoapply import db, drafts, executor, llm
    from autoapply.models import Application

    form = tmp_path / "left.html"
    form.write_text(TWO_STEPS, encoding="utf-8")
    with db.session() as s:
        app_id, did = _explored(s, form, "left.example.test", status="draft_ready")

    def agent(goal, tools, *, system, max_steps=60, on_step=None):
        t = {x.name: x for x in tools}
        t["done"].fn(fixed=[], unfixed=[], cause="", suggestion="", needs_user=[{"label": "Visa status", "why": "The profile does not say.", "type": "text"}])
        return llm.AgentResult(final_text="done", steps=[{"tool": "done"}])

    monkeypatch.setattr(llm, "agent", agent)
    handed = []
    monkeypatch.setattr(executor, "_wait_for_manual_submit", lambda driver, page, title, application_id, draft_id=None, **kw:
                        handed.append(page.evaluate("window.sent")) or {"status": "ready_to_submit", "error": "window closed"})
    drafts.approve(did)
    out = executor.execute(app_id, did)
    # not submitted: the run is given back, to be done again in a window the applicant sees, with the reason
    from autoapply.models import Task

    assert out["status"] != "submitted" and handed == []
    with db.session() as s:
        assert s.get(Application, app_id).status != "submitted"
        ts = s.query(Task).filter_by(kind="execute").order_by(Task.id).all()
        assert ts[-1].status == "queued" and "Visa status" in str(ts[-1].payload)


def test_a_correct_form_is_not_sent_to_the_applicant_over_how_a_control_reads(app_env, tmp_path, monkeypatch):
    """Three things that reached the applicant as "not filled in" on a form that was right: a search box whose choice is a
    pill beside it ("required, still empty"), a ticked box that reads True against the draft's "checked", and a group of
    tick boxes that reads "on". The first two are settled by the program; the third by the agent looking at the page."""
    from playwright.sync_api import sync_playwright

    from autoapply import db, executor, llm, repair
    from autoapply.ats import audit
    from autoapply.ats.base import FormSchema, Question

    html = """<main><div data-automation-id="formField-code"><label for="code">Country Phone Code</label>
        <ul><li data-automation-id="selectedItem">Canada (+1)</li></ul><input id="code" required></div>
      <div class="form-group"><label for="city">City</label><input id="city" required></div></main>"""
    qs = [Question(id="#terms", label="I consent", type="checkbox", locator={"selector": "#terms"}), Question(id="#len", label="How long?", type="multiselect", locator={"selector": "#len"}),
          Question(id="#gpa", label="GPA", type="select", locator={"selector": "#gpa"})]
    schema = FormSchema(ats="generic", tenant="x.test", source="agent", questions=qs)
    bad = [{"id": "#terms", "label": "I consent", "expected": "checked", "actual": True}, {"id": "#len", "label": "How long?", "expected": ["4 months", "8 months"], "actual": "on"},
           {"id": "#gpa", "label": "GPA", "expected": "75-79%", "actual": "80-84%"}]
    db.set_setting("repair.enabled", True)
    asked = []

    def agent(goal, tools, *, system, max_steps=20, on_step=None):
        t = {x.name: x for x in tools}
        assert sorted(t) == ["list_controls", "options", "read_page", "screenshot", "verdict"]      # it looks; it cannot change anything
        asked.append(goal)
        t["verdict"].fn(fields=[{"id": "#len", "same": True, "seen": "4 months and 8 months are ticked"}, {"id": "#gpa", "same": False, "seen": "80-84% is selected"}])
        return llm.AgentResult(final_text="done", steps=[])

    monkeypatch.setattr(llm, "agent", agent)
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.set_content(html)
        assert audit.texts(audit.page_issues(page)) == ["City: required, still empty"]      # the pill counts; a really empty field still does not
        left = executor._really_different(page, schema, bad)
        b.close()
    assert [(x["id"], x["actual"]) for x in left] == [("#gpa", "80-84% is selected")] and "#terms" not in asked[0] and "#len" in asked[0]
    assert "shows" in repair.SHOWS and "Work Experience" in repair.OPTIONAL_FILL


def test_a_document_the_form_already_shows_is_not_uploaded_again(app_env, tmp_path):
    """Every visit to a form that keeps its uploads added another copy of the transcript - four in the end."""
    from playwright.sync_api import sync_playwright

    from autoapply import generic
    from autoapply.ats import generic_driver as g
    from autoapply.ats.base import FormSchema, Question

    doc = tmp_path / "Student_Transcript.pdf"
    doc.write_bytes(b"%PDF-1.4")
    q = Question(id="#tr", label="Please upload your most recent transcript.", type="file", locator={"selector": "#tr"})
    schema = FormSchema(ats="generic", tenant="x.test", source="agent", questions=[q])
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.set_content('<main><label for="tr">Please upload your most recent transcript.</label><input type="file" id="tr"><ul id="have"></ul></main>')
        files = "document.getElementById('tr').files.length"
        tools = {t.name: t for t in generic.l0_tools(page, tmp_path, {}, files={doc.name: str(doc)})}
        assert tools["upload"].fn(selector="#tr", file_name=doc.name) == "uploaded" and page.evaluate(files) == 1
        # the next visit: the form shows the file it kept, and its file box is empty again
        page.set_content('<main><label for="tr">Please upload your most recent transcript.</label><input type="file" id="tr"><ul><li>Student_Transcript.pdf 24 KB</li></ul></main>')
        g.GenericDriver(schema).fill_questions(page, [q], {q.id: str(doc)})
        assert page.evaluate(files) == 0
        assert tools["upload"].fn(selector="#tr", file_name=doc.name).startswith("not uploaded: the form already shows") and page.evaluate(files) == 0
        b.close()


def test_a_saved_sign_in_is_found_when_the_same_site_is_reached_from_another_address(app_env):
    """An employer's postings appear under two addresses (a careers site and its own domain), and both send the applicant
    to the same sign-in page. The sign-in saved for one is the account for the other: found by the host of the sign-in
    page - exactly that host, and only an account that has something saved."""
    from autoapply import auth, browser, db, secrets

    auth.upsert_account("eightfold:acme", ats="eightfold", host="acme.wd5.myworkdayjobs.com", email="me@example.test", password="pw", status="ok")
    auth.upsert_account("workday:other", ats="workday", host="other.wd5.myworkdayjobs.com", email="me@example.test", status="ok")       # nothing saved for it
    assert auth.adopt("generic:jobs.acme.com", "evil.wd5.myworkdayjobs.com") is None
    assert auth.adopt("generic:jobs.acme.com", "other.wd5.myworkdayjobs.com") is None
    assert auth.adopt("generic:jobs.acme.com", "acme.wd5.myworkdayjobs.com") == "eightfold:acme"
    assert auth.key_for("generic:jobs.acme.com") == "eightfold:acme" and auth.key_for("generic:elsewhere.example") == "generic:elsewhere.example"
    assert browser._state_path("generic:jobs.acme.com") == browser._state_path("eightfold:acme")       # one session for both
    assert secrets.get_password(auth.key_for("generic:jobs.acme.com")) == "pw"
    assert auth.adopt("generic:jobs.acme.com", "acme.wd5.myworkdayjobs.com") is None       # already linked
