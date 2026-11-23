"""What the applicant decided about employers' mails (2026-11-23):

- an interview keeps the end time its mail gives ("10:00 to 10:45"), converted like its start;
- an assessment's period ("complete it within two weeks") is counted from the invitation: a reminder that comes in the
  middle and repeats the period does not start it again;
- the files written for a posting the applicant is not applying for are archived with it (and come back when it is
  taken up again).
"""
from __future__ import annotations

from datetime import datetime

import pytest

from autoapply import db


@pytest.fixture()
def shanghai(app_env):
    db.set_setting("time.zone", "Asia/Shanghai")
    return app_env


def _application(company="Northfield Power Labs", status="interview"):
    from autoapply.models import Application, Job

    with db.session() as s:
        j = Job(source="manual", source_id=company, company=company, title="Software Developer Co-op", location="Surrey, BC, Canada",
                apply_url="https://jobs.example/" + company, jd_text="x" * 300, status="applied", online=1)
        s.add(j)
        s.flush()
        a = Application(job_id=j.id, status=status)
        s.add(a)
        s.flush()
        return a.id


def test_an_interview_keeps_the_end_its_mail_gives_converted_like_its_start(shanghai):
    from autoapply import agenda, ics, reminders
    from autoapply.models import Todo

    due, facts = reminders.due_of({"due": "2026-11-24T10:00", "due_end": "2026-11-24T10:45", "due_zone": "America/Vancouver"})
    assert due == datetime(2026, 11, 25, 1, 0) and facts["end_at"] == "2026-11-25T01:45"      # (Vancouver is UTC-7 all year since 2026)
    # no end said, an end before the start, or one a day later (a misread): none kept
    for end in ("", "2026-11-24T09:00", "2026-11-25T10:45", "2026-11-24"):
        assert reminders.due_of({"due": "2026-11-24T10:00", "due_end": end, "due_zone": "America/Vancouver"})[1]["end_at"] == "", end
    # a whole day has no end
    assert reminders.due_of({"due": "2026-11-24", "due_end": "2026-11-24T10:45"})[1]["end_at"] == ""

    app_id = _application()
    tid = reminders.from_mail(app_id, "Northfield", "interview", "new", "an interview", {"due": "2026-11-24T10:00", "due_end": "2026-11-24T10:45",
                                                                                         "due_zone": "America/Vancouver"}, "m1")
    item = next(x for x in agenda.items(datetime(2026, 11, 23).date(), datetime(2026, 11, 30).date()) if x["kind"] == "interview")
    assert item["start"] == "2026-11-25T01:00" and item["end"] == "2026-11-25T01:45"
    assert "DTEND:20261125T014500" in ics.build([item])
    # moved to another time without an end: the old end does not stay behind
    reminders.from_mail(app_id, "Northfield", "interview", "changed", "moved", {"due": "2026-11-26T14:00", "due_zone": "America/Vancouver"}, "m2")
    with db.session() as s:
        t = s.get(Todo, tid)
        assert t.due_at == datetime(2026, 11, 27, 5, 0) and t.payload["end_at"] == ""


def test_an_assessments_period_runs_from_the_invitation_not_from_a_reminder(shanghai):
    from autoapply import reminders
    from autoapply.models import Todo

    app_id = _application(status="assessment")
    # the invitation, sent on the 10th: "please complete it within two weeks"
    tid = reminders.from_mail(app_id, "Amazon", "assessment", "new", "online assessment", {"action": "complete the assessment", "due": "2026-11-24",
                                                                                          "due_from": "period", "due_text": "within two weeks"}, "m1")
    # a reminder on the 17th repeats it: the reader counts two weeks from the 17th - the card keeps the 24th
    reminders.from_mail(app_id, "Amazon", "assessment", "reminder", "reminder", {"due": "2026-12-01", "due_from": "period", "due_text": "within two weeks"}, "m2")
    with db.session() as s:
        t = s.get(Todo, tid)
        assert t.due_at == datetime(2026, 11, 24) and t.payload["due_text"] == "within two weeks" and t.payload["message_id"] == "m2"
    # the same mail read as "new" (sent again) does not start it again either
    reminders.from_mail(app_id, "Amazon", "assessment", "new", "online assessment", {"due": "2026-12-01", "due_from": "period"}, "m3")
    with db.session() as s:
        assert s.get(Todo, tid).due_at == datetime(2026, 11, 24)
    # an extension the employer announces, or a date stated outright, does move it
    reminders.from_mail(app_id, "Amazon", "assessment", "changed", "deadline extended", {"due": "2026-11-28", "due_from": "period"}, "m4")
    with db.session() as s:
        assert s.get(Todo, tid).due_at == datetime(2026, 11, 28)
    reminders.from_mail(app_id, "Amazon", "assessment", "reminder", "due on the 30th", {"due": "2026-11-30", "due_from": "stated"}, "m5")
    with db.session() as s:
        assert s.get(Todo, tid).due_at == datetime(2026, 11, 30)


def test_the_mail_reader_is_asked_where_a_date_comes_from_and_when_it_ends():
    from autoapply import mail

    props = mail.TRIAGE_SCHEMA["properties"]
    assert props["due_from"]["enum"] == ["stated", "period", ""] and "reminder" in props["due_from"]["description"]
    assert "10:45" in props["due_end"]["description"]
    assert "INVITATION" in mail.WHEN_SCHEMA["properties"]["due"]["description"] and "due_end" in mail.WHEN_SCHEMA["properties"]


def test_the_files_of_a_posting_not_applied_for_are_archived_and_come_back_with_it(app_env, tmp_path):
    from autoapply import lifecycle
    from autoapply.api.main import bulk_jobs, list_documents
    from autoapply.models import Document, Job

    with db.session() as s:
        j = Job(source="manual", source_id="skip", company="Skipped Co", title="Analyst", apply_url="https://jobs.example/skip", jd_text="x" * 300, status="scored",
                score=7.0, online=1)
        s.add(j)
        s.flush()
        jid = j.id
        for name, kind, meta in (("letter.pdf", "cover_letter", {}), ("cv.pdf", "tailored_resume", {}), ("own.pdf", "resume", {}),
                                 ("old.pdf", "cover_letter", {"archived": True})):
            f = tmp_path / name
            f.write_bytes(b"%PDF-1.4")
            s.add(Document(kind=kind, name=name, path=str(f), job_id=jid, meta=meta))
    bulk_jobs({"action": "skip", "ids": [jid]})
    rows = {r["name"]: r for r in list_documents()}
    assert rows["letter.pdf"]["archived"] and rows["cv.pdf"]["archived"]
    assert not rows["own.pdf"]["archived"]                       # (the applicant's own file is theirs, whatever it is filed under)
    assert rows["old.pdf"]["archived"]
    bulk_jobs({"action": "restore", "ids": [jid]})
    rows = {r["name"]: r for r in list_documents()}
    assert not rows["letter.pdf"]["archived"] and not rows["cv.pdf"]["archived"]
    assert rows["old.pdf"]["archived"]                           # put away by the applicant before: stays put away
    with db.session() as s:
        assert lifecycle.put_away_files(s.get(Job, jid)) == 2
