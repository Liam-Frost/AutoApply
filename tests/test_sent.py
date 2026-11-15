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
    out = executor._wait_for_manual_submit(Driver(), Page(), "Acme", 1)
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
