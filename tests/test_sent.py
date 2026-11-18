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
    app = Application(job_id=job.id, status=status, created_at=datetime(2026, 11, 1))      # (it was there before the mails about it)
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
    monkeypatch.setattr(mailbox, "fetch", lambda since, limit=50, job_related=False, **kw: [msg])
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


def test_the_page_route_serves_only_the_built_interface(app_env):
    from fastapi.testclient import TestClient

    from autoapply import config
    from autoapply.api.main import app as api

    if not (config.FRONTEND_DIST / "index.html").exists():
        pytest.skip("the interface is not built here")
    c = TestClient(api)
    index = c.get("/").text
    # a file of the interface is served as itself; an address the interface routes by itself gets the page
    other = next((f for f in config.FRONTEND_DIST.iterdir() if f.is_file() and f.name != "index.html"), None)
    if other is not None:
        assert c.get("/" + other.name).content == other.read_bytes()
    assert c.get("/drafts/12").text == index and c.get("/no-such-file.png").text == index
    for path in ("/..%2Fpackage.json", "/..%2F..%2Fpyproject.toml", "/assets/..%2F..%2F..%2Fpyproject.toml", "/%2e%2e/%2e%2e/pyproject.toml", "/..%5C..%5Cpyproject.toml"):
        r = c.get(path)
        assert "autoapply-frontend" not in r.text and "[project]" not in r.text, path
        assert r.status_code == 404 or r.text == index, path


def test_a_link_out_of_the_interface_folder_is_not_served(app_env, tmp_path, monkeypatch):
    from autoapply import config
    from autoapply.api import main

    if not hasattr(main, "_interface_files"):
        pytest.skip("the interface is not built here")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<div id=app></div>", encoding="utf-8")
    (tmp_path / "private.txt").write_text("secret", encoding="utf-8")
    try:
        (dist / "linked.txt").symlink_to(tmp_path / "private.txt")
    except OSError:
        pytest.skip("links cannot be made here")
    monkeypatch.setattr(config, "FRONTEND_DIST", dist)
    assert sorted(main._interface_files()) == ["index.html"]


# Workday draws the header signed out first and changes it once it knows who is there; the page's content comes after that.
def test_saving_the_settings_page_is_not_refused_over_the_programs_own_bookkeeping(app_env):
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app as api

    db.set_setting("migrated.page_ids", True)
    c = TestClient(api)
    got = c.get("/api/settings").json()["settings"]
    assert "migrated.page_ids" not in got and "draft.min_score" in got or "migrated.page_ids" not in got
    assert c.put("/api/settings", json={"settings": {**got, "migrated.page_ids": True}}).status_code == 200


def test_only_a_date_tied_to_applying_is_when_it_was_sent_and_an_account_that_exists_is_not_an_application():
    from autoapply import lifecycle

    on = lifecycle.applied_on
    assert on("You applied on Nov 3, 2026.").day == 3 and on("Application submitted: 2026-10-28").month == 10
    assert on("You have already applied. Application deadline: 2026-11-10.") is None
    assert on("Posted 1 Nov 2026. You have already applied for this position.") is None
    assert on("You have already applied for this position.") is None


def test_a_task_is_resumed_by_what_it_waited_for_and_not_by_something_else(app_env):
    """Signing in to Google put every waiting task back in the queue - the ones waiting for the university portal too,
    which then failed once more and asked once more."""
    from autoapply import db, handlers
    from autoapply.models import Application, Job, Task

    with db.session() as s:
        jobs = [Job(source="manual", source_id=f"w{i}", company="Acme", title="Analyst", apply_url=f"https://x.example/{i}", channel="employer site", jd_text="x" * 300) for i in range(3)]
        s.add_all(jobs)
        s.flush()
        apps = [Application(job_id=j.id, status="needs_human") for j in jobs]
        s.add_all(apps)
        s.flush()
        s.add(Task(kind="execute", ref=f"application:{apps[0].id}", status="waiting_human", payload={"draft_id": 1, "waits_for": "account:idp:google"}))
        s.add(Task(kind="recon", ref=f"job:{jobs[1].id}", status="waiting_human", payload={"job_id": jobs[1].id, "waits_for": "account:pdportal:ubc"}))
        s.add(Task(kind="recon", ref=f"job:{jobs[2].id}", status="waiting_human", payload={"job_id": jobs[2].id}))        # from before it was recorded
        ids = [a.id for a in apps]

    def state():
        with db.session() as s:
            return [t.status for t in s.query(Task).order_by(Task.id)], [s.get(Application, i).status for i in ids]

    assert handlers.resume_waiting("account:idp:google") == 2
    assert state() == (["queued", "waiting_human", "queued"], ["recon", "needs_human", "recon"])
    assert handlers.resume_waiting("account:generic:other.example") == 0
    assert handlers.resume_waiting() == 1 and state()[0] == ["queued", "queued", "queued"]          # "try them all again"

