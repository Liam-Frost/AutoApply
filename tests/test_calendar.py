"""The calendar: everything with a time, from the program's own data, in one shape (agenda.py)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from autoapply import db

MON = date(2026, 11, 23)


def _job(company, deadline, status=None, *, score=8.0, online=1):
    from autoapply.models import Application, Job

    with db.session() as s:
        j = Job(source="manual", source_id=company, company=company, title="Analyst", apply_url="https://jobs.example/" + company, jd_text="x" * 300,
                status="queued", online=online, score=score, deadline=deadline)
        s.add(j)
        s.flush()
        a = None
        if status:
            a = Application(job_id=j.id, status=status, submitted_at=datetime(2026, 11, 24, 18, 0) if status in ("submitted", "interview") else None)
            s.add(a)
            s.flush()
        return j.id, a.id if a else None


def test_deadlines_interviews_contacts_and_own_items_in_one_shape(app_env):
    from autoapply import agenda
    from autoapply.models import Contact, Todo

    _job("Acme", "2026-11-25 23:59")                          # not applied: shown
    _job("Globex", "2026-11-26", "draft_ready")                # in progress: shown, a whole day
    _job("Initech", "2026-11-27", "submitted")                 # sent: only with all deadlines
    _job("Umbrella", "2026-11-28", score=5.0)
    _, app = _job("Kestrel", "", "interview")
    with db.session() as s:
        s.add(Todo(kind="followup", ref=f"followup:{app}:interview", title="Kestrel：面试", payload={"application_id": app, "category": "interview", "link": "https://meet.example/k"},
                   due_at=datetime(2026, 11, 26, 10, 0)))
        s.add(Contact(name="Dana", company="Hooli", follow_up="2026-11-27"))
    own = agenda.add_own("Call the recruiter back", datetime(2026, 11, 27), all_day=True, link="https://example.com/x")
    got = agenda.items(MON, MON + timedelta(days=7))
    assert [(x["kind"], x["start"], x["all_day"]) for x in got] == [
        ("deadline", "2026-11-25T23:59", False), ("deadline", "2026-11-26T00:00", True), ("interview", "2026-11-26T10:00", False),
        ("contact", "2026-11-27T00:00", True), ("own", "2026-11-27T00:00", True), ("deadline", "2026-11-28T00:00", True)]
    iv = next(x for x in got if x["kind"] == "interview")
    assert iv["link"] == "https://meet.example/k" and iv["about"]["application_id"] == app and iv["state"] == "progressed" and iv["subject"] == "Kestrel · Analyst"
    assert next(x for x in got if x["kind"] == "own")["about"]["todo_id"] == own
    # filters: a score, a company, the state of the application, every deadline
    assert [x["company"] for x in agenda.items(MON, MON + timedelta(days=7), kinds=("deadline",), min_score=7)] == ["Acme", "Globex"]
    assert [x["company"] for x in agenda.items(MON, MON + timedelta(days=7), company="glob")] == ["Globex"]
    assert [x["company"] for x in agenda.items(MON, MON + timedelta(days=7), states=("in_progress",))] == ["Globex"]
    assert "Initech" in [x["company"] for x in agenda.items(MON, MON + timedelta(days=7), kinds=("deadline",), all_deadlines=True)]
    # what went out, only when asked for - at the local time of the moment recorded
    sent = agenda.items(MON, MON + timedelta(days=7), kinds=("sent",))
    local = datetime(2026, 11, 24, 18, 0).replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    assert [x["start"] for x in sent] == [local.isoformat(timespec="minutes")] * 2


def test_a_contact_with_its_card_is_one_item(app_env):
    from autoapply import agenda, reminders
    from autoapply.models import Contact

    with db.session() as s:
        s.add(Contact(name="Dana", company="Hooli", follow_up="2026-11-24"))
    reminders.check(datetime(2026, 11, 24, 9, 0))              # the day has come: a card for it
    got = agenda.items(MON, MON + timedelta(days=7))
    assert [(x["kind"], x["id"].split(":")[0]) for x in got] == [("contact", "todo")]


def test_the_page_adds_an_item_and_gives_it_a_link(app_env):
    from fastapi import HTTPException

    from autoapply.api.main import calendar_add, calendar_items, calendar_link
    from autoapply.models import Todo

    tid = calendar_add({"title": "  Kestrel  interview ", "day": "2026-11-26", "time": "10:00"})["id"]
    with db.session() as s:
        t = s.get(Todo, tid)
        assert (t.kind, t.title, t.due_at, t.payload["all_day"], t.ref) == ("note", "Kestrel interview", datetime(2026, 11, 26, 10, 0), False, f"note:{tid}")
    calendar_link(tid, {"link": "https://meet.example/abc"})
    with pytest.raises(HTTPException):
        calendar_link(tid, {"link": "javascript:alert(1)"})
    with pytest.raises(HTTPException):
        calendar_add({"title": "x", "day": "2026-11-26", "link": "ftp://x"})
    got = calendar_items("2026-11-23", "2026-11-30")["items"]
    assert [(x["kind"], x["link"]) for x in got] == [("own", "https://meet.example/abc")]
    with pytest.raises(HTTPException):
        calendar_items("2026-11-23", "2027-11-30")          # too long a span
