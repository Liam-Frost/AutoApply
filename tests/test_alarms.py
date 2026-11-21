"""Reminders of dated items (alarms.py) and the calendar as a file (ics.py)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from autoapply import db

# a day well ahead of whenever the tests run (reminders that would already have gone off are not given)
DAY = date.today() + timedelta(days=10)
AT = lambda h, m=0, days=0: datetime.combine(DAY + timedelta(days=days), datetime.min.time()).replace(hour=h, minute=m)  # noqa: E731


def _told(monkeypatch):
    from autoapply import notify

    told = []
    monkeypatch.setattr(notify, "send", lambda category, card, **k: told.append((card.heading, card.fields[2][1] if len(card.fields) > 2 else "", k.get("through_quiet"), card.open_url)) or True)
    return told


def test_an_interview_and_an_assessment_are_reminded_of_as_their_kinds_say_and_follow_a_new_date(app_env, monkeypatch):
    from autoapply import alarms, reminders
    from autoapply.models import Todo

    told = _told(monkeypatch)
    iv = reminders.from_mail(1, "Acme", "interview", "new", "", {"due": AT(10).isoformat(timespec="minutes")}, "m1")
    reminders.from_mail(1, "Acme", "assessment", "new", "", {"due": DAY.isoformat()}, "m2")
    assert [a["before"] for a in alarms.of(f"todo:{iv}")] == [1440, 30]
    with db.session() as s:
        s.get(Todo, iv).payload = {**s.get(Todo, iv).payload, "link": "https://meet.example/acme"}
    assert alarms.tick(AT(8, 59, days=-1)) == 0
    assert alarms.tick(AT(9, 0, days=-1)) == 1                   # the assessment, a whole day: the morning before (2 hours = 1 day = one reminder)
    assert alarms.tick(AT(10, 0, days=-1)) == 1                  # the interview, a day before
    assert alarms.tick(AT(10, 5, days=-1)) == 0                  # once
    assert alarms.tick(AT(9, 30)) == 1                           # 30 minutes before
    assert [(h, ahead, quiet) for h, ahead, quiet, _ in told] == [("提醒：测评", "1 天前", True), ("提醒：面试", "1 天前", True), ("提醒：面试", "30 分钟前", True)]
    assert told[1][3] == "https://meet.example/acme"             # the way to it, as a button
    # the employer moves the interview: its reminders move with it and are said again
    reminders.from_mail(1, "Acme", "interview", "changed", "", {"due": AT(14, days=2).isoformat(timespec="minutes")}, "m3")
    assert alarms.tick(AT(14, days=1)) == 1 and alarms.tick(AT(13, 30, days=2)) == 1
    # done: no more; a quiet hour kept when the applicant says so
    reminders.from_mail(1, "Acme", "offer", "new", "", {"due": AT(17, days=5).isoformat(timespec="minutes")}, "m4")
    db.set_setting("calendar.reminders_quiet", True)
    assert alarms.tick(AT(17, days=4)) == 1 and told[-1][2] is False
    with db.session() as s:
        for t in s.query(Todo):
            t.status = "done"
    alarms.add(f"todo:{iv}", 5)
    assert alarms.tick(AT(13, 55, days=2)) == 0


def test_a_reminder_of_ones_own_on_a_deadline_and_the_calendar_file(app_env, monkeypatch):
    from autoapply import access, alarms, ics
    from autoapply.api.main import calendar_feed
    from autoapply.models import Job

    told = _told(monkeypatch)
    with db.session() as s:
        s.add(Job(source="manual", source_id="x", company="Acme, Inc.", title="Analyst; Data", apply_url="https://jobs.example/1", jd_text="x" * 300, status="queued",
                  online=1, score=8.0, deadline=DAY.isoformat()))
    alarms.add("job:1", 2 * 1440)
    assert alarms.tick(AT(8, 59, days=-2)) == 0 and alarms.tick(AT(9, 0, days=-2)) == 1
    assert told[0][0] == "提醒：截止"
    from autoapply import agenda

    text = ics.build(agenda.items(DAY - timedelta(days=1), DAY + timedelta(days=1)))
    assert "BEGIN:VEVENT" in text and f"DTSTART;VALUE=DATE:{DAY:%Y%m%d}" in text and "UID:job:1@autoapply" in text
    assert "Acme\\, Inc. · Analyst\\; Data" in text                       # escaped
    assert "TRIGGER:-PT2340M" in text                                      # two days before midnight, at 09:00
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))   # folded
    # the address to subscribe to: outside the login, by its token alone
    url = ics.address()["url"]
    token = url.rsplit("/", 1)[1][:-4]
    assert calendar_feed(token).body.decode().startswith("BEGIN:VCALENDAR")
    monkeypatch.setattr(access, "enforced", lambda: True)              # (the tests run without the login)
    assert access.allowed(f"/api/calendar/feed/{token}.ics", None, {"local": False}, None) is True
    assert not access.allowed("/api/calendar/feed", None, {"local": False}, None)          # the address itself: only signed in
    assert not access.allowed("/api/calendar", None, {"local": False}, None)
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        calendar_feed("wrong")
    ics.token(new=True)
    with pytest.raises(HTTPException):
        calendar_feed(token)                                               # the old address stops working
