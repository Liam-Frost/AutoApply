"""Why work did not get done, counted where it was one number or put under the wrong name; and work on the clock that
keeps failing says so (2026-11-25: mail could not be read for a day - 48 checks in a row - and nothing said so; its
errors were counted as "an error in the program"; the runs that stopped for the applicant were one number)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta


def test_no_connection_is_its_own_reason_and_a_page_timeout_is_not_it(app_env):
    from autoapply import analytics

    key = lambda raw: analytics.failure("mail", "failed", {}, raw)["key"]  # noqa: E731
    assert key("TransportError: HTTPSConnectionPool(host='oauth2.googleapis.com', port=443): Max retries exceeded (Caused by ConnectTimeoutError(..., "
               "'Connection to oauth2.googleapis.com timed out. (connect timeout=20)'))") == "network"
    assert key("TimeoutError: timed out") == "network"
    assert key("GmailUnreachable: cannot reach Gmail through http://127.0.0.1:7890: TimeoutError: _ssl.c:1063: The handshake operation timed out") == "network"
    assert key("TimeoutError: Locator.click: Timeout 30000ms exceeded.") != "network"         # (a page that did not answer a click)
    assert key("Page.goto: Timeout 30000ms exceeded") == "site_down"


def test_what_a_run_that_stopped_for_the_applicant_waited_for_is_counted(app_env):
    from autoapply import analytics, db
    from autoapply.agent import work
    from autoapply.models import Application, Job

    with db.session() as s:
        j = Job(source="manual", source_id="w1", company="Acme", title="Co-op", apply_url="https://careers.acme.example/jobs/1", jd_text="x" * 300)
        s.add(j)
        s.flush()
        a = Application(job_id=j.id, status="needs_human")
        s.add(a)
        s.flush()
        app_id = a.id
    now = datetime.now().replace(microsecond=0)
    rows = []
    for i, (stop, out) in enumerate([({"kind": "needs_applicant", "why": "sign in"}, "needs_you"),
                                     ({"kind": "needs_applicant", "need": "code", "why": "a code"}, "needs_you"),
                                     ({"kind": "needs_applicant", "need": "window", "why": "a puzzle"}, "needs_you"),
                                     ({"kind": "ask", "question": "Notice period?"}, "needs_you"),
                                     ({"kind": "log", "text": "nothing"}, "needs_you"),
                                     ({"kind": "needs_applicant", "need": "code", "why": "a code"}, "needs_you"),
                                     ({"kind": "log", "text": "done"}, "submitted")]):
        if i == 4:      # (a code asked and given earlier in the run, then a question left open: it waited for the answer)
            stop = None
        at = (now - timedelta(minutes=60 - i * 5)).isoformat()
        steps = [{"at": at, **stop}] if stop else [{"at": at, "kind": "needs_applicant", "need": "code"}, {"at": at, "kind": "code_given"}, {"at": at, "kind": "ask", "question": "Start date?"}]
        rows += [{"at": at, "kind": "run", "mode": "auto"}, {"at": at, "kind": "tool", "tool": "goto"}, *steps, {"at": at, "kind": "report", "outcome": out}]
    folder = work.folder_of(app_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "journal.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    got = analytics.agent_runs(analytics.window(7))
    assert {w["key"]: w["n"] for w in got["waits"]} == {"sign_in": 1, "code": 2, "window": 1, "question": 2}
    assert sum(w["n"] for w in got["waits"]) == next(e["n"] for e in got["ends"] if e["key"] == "needs_you")


def test_work_on_the_clock_that_keeps_failing_is_a_card_that_closes_when_it_works_again(app_env):
    from fastapi.testclient import TestClient

    from autoapply import db, i18n, tasks
    from autoapply.api.main import app
    from autoapply.models import Task, now

    err = "GmailUnreachable: cannot reach Gmail through http://127.0.0.1:7890: TimeoutError: timed out"

    def ended(kind: str, status: str, error: str = "", result: dict | None = None) -> None:
        with db.session() as s:
            s.add(Task(kind=kind, ref="schedule", status=status, error=error, result=result or {}, finished_at=now()))
        tasks.keeps_failing(kind, status, error, result)

    c = TestClient(app)
    cards = lambda: [t for t in c.get("/api/todos").json() if t["ref"].startswith("failing:")]  # noqa: E731
    ended("mail", "failed", err)
    ended("mail", "done", result={"skipped": "the application is confirmed already"})      # (skipped: neither)
    ended("mail", "failed", err)
    assert cards() == []                                                                     # (twice: a moment's trouble)
    ended("mail", "failed", err)
    got = cards()
    assert len(got) == 1 and got[0]["kind"] == "config" and got[0]["ref"] == "failing:mail"
    assert "3" in i18n.tr(got[0]["title"], "en") and "Gmail" in i18n.tr(got[0]["explained"]["message"], "en")
    ended("mail", "failed", err)
    assert len(cards()) == 1                                                                 # (one card, not one a failure)
    ended("mail", "done", result={"skipped": "the application is confirmed already"})
    assert len(cards()) == 1                                                                 # (a skipped look is not "it works again")
    ended("mail", "done")
    assert cards() == []                                                                     # it works again: the card closes
    for _ in range(3):
        ended("apply", "failed", "anything")
    assert cards() == []                                                                     # (an application has cards of its own)
