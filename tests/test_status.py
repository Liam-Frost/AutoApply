"""Where an application stands has one way in (lifecycle.move), and one rule kept at the attribute itself:
an application that has gone out only moves forward.

Before, the status was assigned in some thirty places. The executor refused to run again for "submitted" and
"confirmed" but not for "interview"; when it ended it wrote its own outcome over whatever a mail had put there
meanwhile; a mail was recorded in one write and applied to its application in another.
"""
import re
from pathlib import Path

import pytest

from autoapply import db

from test_pipeline import pipeline  # noqa: F401  (the fixture: a real form in a real browser)


def _app(status="submitted", **kw):
    from autoapply.models import Application, Job

    with db.session() as s:
        j = Job(source="manual", source_id=f"s{status}", company="Acme", title="Engineer", apply_url="https://acme.test/1", channel="employer site", jd_text="x" * 300)
        s.add(j)
        s.flush()
        a = Application(job_id=j.id, status=status, **kw)
        s.add(a)
        s.flush()
        return a.id


def _now(app_id):
    from autoapply.models import Application

    with db.session() as s:
        a = s.get(Application, app_id)
        return a.status, dict(a.evidence or {}), a.submitted_at


def test_a_sent_application_only_moves_forward_whoever_writes(app_env):
    from datetime import datetime

    from autoapply import lifecycle
    from autoapply.models import Application, ApplicationEvent

    app_id = _app("draft_ready")
    assert lifecycle.move(app_id, "approved", source="user") and lifecycle.move(app_id, "recon", source="draft")       # before it goes out: any way
    sent_at = datetime(2026, 11, 3, 9, 0)
    assert lifecycle.move(app_id, "submitted", source="run", evidence={"text": "Thank you", "url": "https://acme.test/done"}, at=sent_at)
    assert lifecycle.move(app_id, "interview", source="mail", evidence={"mail_id": "m1"})
    # what would take it back is not done - and is said to the caller, who then does not report its old news
    for stale in ("failed", "recon", "needs_input", "executing", "submitted", "confirmed", "withdrawn"):
        assert lifecycle.move(app_id, stale, source="run") is False
    status, evidence, at = _now(app_id)
    assert status == "interview" and at == sent_at
    # evidence is added to, never replaced - also by a caller whose status was not taken
    assert lifecycle.move(app_id, "submitted", source="run", evidence={"text": "Thank you again", "screenshot": "x.png"}) is False
    lifecycle.move(app_id, "interview", source="mail", evidence={"mail_id": "m2"})
    assert _now(app_id)[1] == {"text": "Thank you again", "url": "https://acme.test/done", "screenshot": "x.png", "mail_id": "m2", "mail_ids": ["m1", "m2"]}
    # the two that may go back say so
    assert lifecycle.move(app_id, "submitted", source="mail", back=True) and _now(app_id)[0] == "submitted"
    assert lifecycle.move(app_id, "rejected", source="mail") and not lifecycle.move(app_id, "offer", source="mail")
    assert lifecycle.move(app_id, "interview", source="user", back=True)
    # the rule is the attribute's: a write that does not go through move() is held to it as well
    with db.session() as s:
        a = s.get(Application, app_id)
        a.status = "failed"
        assert a.status == "interview"
    with db.session() as s:
        said = [(e.old, e.new, e.source) for e in s.query(ApplicationEvent).filter_by(application_id=app_id).order_by(ApplicationEvent.id)]
    assert said == [("draft_ready", "approved", "user"), ("approved", "recon", "draft"), ("recon", "submitted", "run"), ("submitted", "interview", "mail"),
                    ("interview", "submitted", "mail"), ("submitted", "rejected", "mail"), ("rejected", "interview", "user")]


def test_the_programs_own_code_writes_a_status_only_through_move(app_env, monkeypatch):
    """In the tests a status written directly by the program's code stops the run (conftest: AUTOAPPLY_STRICT_STATUS);
    and no such line is in the source."""
    from autoapply import models

    app_id = _app("draft_ready")
    code = compile("def write(a):\n    a.status = 'recon'\n", str(Path(models.__file__).parent / "somewhere.py"), "exec")
    scope: dict = {}
    exec(code, scope)
    with db.session() as s:
        with pytest.raises(AssertionError, match="somewhere.py:2 writes an application's status directly"):
            scope["write"](s.get(models.Application, app_id))
        s.rollback()
    root = Path(models.__file__).parent
    found = []
    for f in root.rglob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            # an assignment whose target (or one of its targets) is an application's status: "app.status = ...", "a.status, a.x = ..."
            if re.match(r"\s*(?:[\w.]+\s*,\s*)*(?:\w+\.)*(app|application|a)\.status\s*(?:,[^=\n]*)?=(?!=)", line) and not (
                    f.name == "auth.py" or (f.name == "lifecycle.py" and "app.status = to" in line)):
                found.append(f"{f.relative_to(root)}:{n}: {line.strip()}")
    assert found == []          # (auth.py's "a" is an account)


def test_an_application_that_has_gone_out_is_not_filled_again(app_env, monkeypatch):
    """An application at "interview" with an approved draft, and a retry of its old task: the form was opened again."""
    from fastapi.testclient import TestClient

    from autoapply import executor, tasks
    from autoapply.api.main import app
    from autoapply.ats.base import FormSchema
    from autoapply.models import Draft, Task

    app_id = _app("interview")
    schema = FormSchema(ats="generic").to_dict()
    schema["_ref"] = {"ats": "generic", "tenant": "audit", "job_id": "1", "url": "https://example.test"}
    with db.session() as s:
        d = Draft(application_id=app_id, version=1, review_status="approved", schema=schema, answers=[])
        s.add(d)
        s.add(Task(kind="execute", ref=f"application:{app_id}", status="failed", payload={"draft_id": 1}))
        s.add(Task(kind="recon", ref="job:1", status="failed", payload={}))
        s.add(Task(kind="mail", ref="schedule", status="failed", payload={}))
        s.flush()
        did = d.id

    def no_browser(*a):
        raise AssertionError("the form was about to be opened")

    monkeypatch.setattr(executor.registry, "get", no_browser)
    assert executor.execute(app_id, did) == {"status": "interview", "note": "already submitted"}
    assert _now(app_id)[0] == "interview"
    with pytest.raises(tasks.NothingToRetry, match="面试中"):
        tasks.retry(1)
    c = TestClient(app)
    assert c.post("/api/tasks/1/retry", json={}).status_code == 409
    assert c.post("/api/tasks/2/retry", json={"browser_backend": "playwright"}).status_code == 409        # the same door, by its other handle
    assert c.post("/api/tasks/3/retry", json={}).status_code == 200                                       # not work on a form
    with db.session() as s:
        assert [t.status for t in s.query(Task).order_by(Task.id)] == ["failed", "failed", "queued"]


def test_a_run_that_ends_late_does_not_write_over_what_a_mail_said(pipeline, monkeypatch):  # noqa: F811
    """While the window waited for Submit, the employer's confirmation - or an invitation - arrived. The run then wrote
    its own outcome over it, and with "submitted" replaced the evidence whole."""
    from autoapply import drafts, lifecycle, mail, tasks
    from autoapply.models import Job

    did = drafts.build(pipeline["job_id"])
    drafts.approve(did)
    with db.session() as s:
        app_id = s.get(Job, pipeline["job_id"]).application.id
    real = pipeline["driver"].submit

    def submit(page):
        real(page)
        # (the applicant had applied on the employer's site before; the employer answers while the program's run ends)
        lifecycle.move(app_id, "confirmed", source="mail", evidence={"mail_id": "m-confirm"})
        mail._record(app_id, "interview", "invited for Thursday", None, "m-invite")

    monkeypatch.setattr(pipeline["driver"], "submit", submit)
    tasks.drain()
    status, evidence, _ = _now(app_id)
    assert status == "interview"                                             # not back to "submitted"
    assert "Thank you for applying" in evidence["text"] and evidence["mail_ids"] == ["m-confirm"]     # the page and the mail, both
    assert any("已提交" in t for t in pipeline["sent"])                      # the run did submit, and says so


def test_a_run_that_fails_after_the_application_went_out_says_nothing_about_failure(pipeline, monkeypatch):  # noqa: F811
    from autoapply import drafts, executor, lifecycle, tasks
    from autoapply.models import Job, Run, Todo

    did = drafts.build(pipeline["job_id"])
    drafts.approve(did)
    with db.session() as s:
        app_id = s.get(Job, pipeline["job_id"]).application.id

    def window_closed(driver, page, title, application_id, draft_id=None, **kw):
        # the applicant submitted on the employer's site in another tab; the confirmation mail is in before the window closes
        lifecycle.move(app_id, "confirmed", source="mail", evidence={"mail_id": "m-confirm"})
        return {"status": "ready_to_submit", "error": "window closed"}

    monkeypatch.setattr(executor, "_wait_for_manual_submit", window_closed)
    pipeline["driver"].corrupt = "email"        # something to look at: the run hands the window over
    tasks.drain()
    status, evidence, _ = _now(app_id)
    assert status == "confirmed" and evidence["mail_id"] == "m-confirm"
    with db.session() as s:
        assert s.query(Todo).filter(Todo.status == "open", Todo.kind.in_(("failed", "submit"))).count() == 0      # nothing is asked about a sent application
        steps = s.query(Run).filter_by(kind="execute").order_by(Run.id.desc()).first().steps
    assert any(st["op"] == "superseded" and st["told"] == "ready_to_submit" for st in steps)
    assert not any("没有确认提交成功" in t or "执行失败" in t for t in pipeline["sent"])


def test_a_mail_and_what_it_does_to_its_application_are_written_together(app_env, monkeypatch):
    """The mail was stored, then the application was to be updated: a failure in between left the mail "read" for good
    and the application where it was."""
    from types import SimpleNamespace

    from autoapply import mail, mailbox, notify
    from autoapply.models import MailEvent, now

    app_id = _app("submitted", submitted_at=now())
    msg = SimpleNamespace(id="audit-mail", sender="hr@example.test", subject="Interview", date=now(), body="Invitation")
    monkeypatch.setattr(mailbox, "fetch", lambda *a, **k: [msg])
    monkeypatch.setattr(mail, "triage", lambda *a: {"category": "interview", "company": "Acme", "job_title": "Engineer", "summary": "Invite"})
    real = mail._record

    def fail(*a, **k):
        raise RuntimeError("interrupted")

    monkeypatch.setattr(mail, "_record", fail)
    with pytest.raises(RuntimeError):
        mail.track()
    with db.session() as s:
        assert s.query(MailEvent).count() == 0 and _now(app_id)[0] == "submitted"       # neither
    monkeypatch.setattr(mail, "_record", real)
    # the notice failing afterwards undoes nothing and stops nothing
    monkeypatch.setattr(notify, "send", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("telegram is down")))
    out = mail.track()
    with db.session() as s:
        assert out["new_mail"] == 1 and out["status_updates"] == 1
        assert s.query(MailEvent).filter_by(message_id="audit-mail").one().application_id == app_id and _now(app_id)[0] == "interview"      # both
