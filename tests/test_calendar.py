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


def test_a_mail_gives_its_card_the_link_it_has_and_never_one_it_does_not(app_env):
    from autoapply import agenda, mail, reminders
    from autoapply.models import Todo

    body = "Join here: https://meet.example/abc-def or reschedule at https://cal.example/r/9 . Unsubscribe https://acme.example/u"
    found = [{"url": "https://meet.example/abc-def", "what": "面试会议链接"}, {"url": "https://meet.example/made-up", "what": "x"},
             {"url": "javascript:alert(1)", "what": "x"}, {"url": "https://meet.example/abc-def", "what": "again"}]
    assert mail.mail_links(found, body) == [{"url": "https://meet.example/abc-def", "what": "面试会议链接"}]
    one = reminders.from_mail(3, "Acme", "interview", "new", "", {"due": "2026-11-26T10:00", "links": mail.mail_links(found, body)}, "m1")
    two = reminders.from_mail(4, "Globex", "assessment", "new", "", {"due": "2026-11-27", "links": [{"url": "https://a.example/1", "what": "测评入口"},
                                                                                                  {"url": "https://a.example/help", "what": "帮助"}]}, "m2")
    with db.session() as s:
        assert s.get(Todo, one).payload["link"] == "https://meet.example/abc-def"          # one link: that is where it leads
        assert "link" not in s.get(Todo, two).payload and len(s.get(Todo, two).payload["links"]) == 2      # several: the applicant chooses
    got = {x["about"]["todo_id"]: x for x in agenda.items(date(2026, 11, 23), date(2026, 11, 30))}
    assert [link["what"] for link in got[two]["links"]] == ["测评入口", "帮助"]
    # the applicant's own choice stays when a later mail of the same thing comes with another link
    agenda.set_link(one, "https://meet.example/mine")
    reminders.from_mail(3, "Acme", "interview", "changed", "", {"due": "2026-11-26T11:00", "links": [{"url": "https://meet.example/new", "what": ""}]}, "m3")
    with db.session() as s:
        assert s.get(Todo, one).payload["link"] == "https://meet.example/mine"


def test_an_item_says_whether_its_employer_is_a_priority_one_and_how_the_mail_wrote_its_time(app_env):
    from autoapply import agenda
    from autoapply.models import Todo

    _job("Acme Robotics", "2026-11-25 23:59")
    _, app = _job("Kestrel", "", "interview")
    with db.session() as s:
        s.add(Todo(kind="followup", ref=f"followup:{app}:interview", title="Kestrel", due_at=datetime(2026, 11, 26, 10, 0),
                   payload={"application_id": app, "category": "interview", "due_text": "Thursday 10am PT"}))
    db.set_setting("employers", [{"name": "Acme Robotics", "url": "https://acme.example/careers", "priority": True}])
    got = {x["kind"]: x for x in agenda.items(MON, MON + timedelta(days=7))}
    assert got["deadline"]["priority"] is True and got["interview"]["priority"] is False
    assert got["interview"]["due_text"] == "Thursday 10am PT" and got["deadline"]["due_text"] == ""


def test_a_company_with_the_postings_fields_glued_to_it_is_read_as_its_name(app_env):
    from autoapply import agenda
    from autoapply.api.main import calendar_items
    from autoapply.discover import company_name
    from autoapply.models import Job

    glued = ("Ballard Power SystemsDepartment: Research - Electrodes TeamWork Term: 8 months January 2027 - August 2027Contact: A. PersonWork Type: Full-time"
             "Title: Research Co-op")
    assert company_name(glued) == "Ballard Power Systems"
    assert company_name("Title Nine Outfitters") == "Title Nine Outfitters"          # (a label is a word followed by ':')
    assert company_name("  Acme   Corp ") == "Acme Corp"
    _job(glued, "2026-11-25 23:59")
    got = agenda.items(MON, MON + timedelta(days=7))
    assert [(x["company"], x["subject"]) for x in got] == [("Ballard Power Systems", "Ballard Power Systems · Analyst")]
    with db.session() as s:
        assert s.query(Job).one().company == glued                                     # what was kept is not changed
    assert isinstance(calendar_items("2026-11-23", "2026-11-30")["utc_offset"], int)


def test_the_portal_posting_the_agent_saved_keeps_only_the_companys_name():
    from autoapply.sources import pdportal

    row, _ = pdportal.row_of({"id": "149001", "company": "Ballard Power SystemsDepartment: ResearchWork Term: 8 months", "title": "Research Co-op",
                              "deadline": "2026-11-18 23:59", "how_to_apply": "portal"})
    assert row["company"] == "Ballard Power Systems"
