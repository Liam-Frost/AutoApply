"""An interview from an employer's mail is an event on the calendar, not a task (2026-11-24, the owner: "only on the
calendar; a notice when it first arrives and when it is time") - and so is an assessment with its deadline (2026-11-25:
one was a card with "Done", "didn't I ask for this already?"). One with no date yet stays a task until it has one; an
offer to answer stays a task."""
from __future__ import annotations

from datetime import date, timedelta

from autoapply import db


def _application(n: int = 1) -> int:
    from autoapply.models import Application, Job

    with db.session() as s:
        job = Job(source="manual", source_id=f"i{n}", company="Acme", title="Firmware Co-op", apply_url=f"https://acme.example/jobs/{n}", jd_text="x" * 300)
        s.add(job)
        s.flush()
        a = Application(job_id=job.id, status="confirmed")
        s.add(a)
        s.flush()
        return a.id


def test_an_interview_and_an_assessment_are_on_the_calendar_once_they_have_a_date_and_their_arrival_is_a_notice(app_env):
    from fastapi.testclient import TestClient

    from autoapply import reminders
    from autoapply.api.main import app, overview

    db.set_setting("time.zone", "UTC")
    app_id = _application()
    day = date.today() + timedelta(days=9)
    tid = reminders.from_mail(app_id, "Acme · Firmware Co-op", "interview", "new", "A first interview, by video",
                              {"due": f"{day}T10:00", "due_text": f"{day:%B} {day.day}, 10:00"}, "m1")
    c = TestClient(app)
    # not a task: not on the to-do page, not counted
    assert c.get("/api/todos").json() == [] and overview()["open_todos"] == 0
    # on the calendar, as an interview
    items = c.get("/api/calendar", params={"start": day.isoformat(), "end": (day + timedelta(days=1)).isoformat()}).json()["items"]
    assert [x["kind"] for x in items if x["id"] == f"todo:{tid}"] == ["interview"]
    # its arrival: a notice at the top of the to-do page, put away with "Got it"
    rang = c.get("/api/calendar/alarms/recent").json()
    assert [(x["id"], x["why"]) for x in rang] == [(f"todo:{tid}", "new")]
    c.post("/api/calendar/alarms/seen", json={"item": rang[0]["id"], "start": rang[0]["start"]})
    assert c.get("/api/calendar/alarms/recent").json() == []
    # the employer moves it: a notice again, with the new time
    later = day + timedelta(days=1)
    reminders.from_mail(app_id, "Acme · Firmware Co-op", "interview", "changed", "Moved to the next day", {"due": f"{later}T14:00"}, "m2")
    rang = c.get("/api/calendar/alarms/recent").json()
    assert len(rang) == 1 and rang[0]["start"].startswith(f"{later}T14:00") and rang[0]["why"] == "new"
    # a reminder of the same date (the employer's own) is no new notice once it is put away
    c.post("/api/calendar/alarms/seen", json={"item": rang[0]["id"], "start": rang[0]["start"]})
    reminders.from_mail(app_id, "Acme · Firmware Co-op", "interview", "reminder", "Reminder", {"due": f"{later}T14:00"}, "m3")
    assert c.get("/api/calendar/alarms/recent").json() == []
    # an assessment with its deadline: the same - on the calendar, its arrival a notice, done there
    aid = reminders.from_mail(app_id, "Acme · Firmware Co-op", "assessment", "new", "Online assessment, five tasks",
                              {"due": f"{day}T08:00", "due_text": f"{day:%B} {day.day}, 08:00"}, "m4")
    assert c.get("/api/todos").json() == [] and overview()["open_todos"] == 0
    items = c.get("/api/calendar", params={"start": day.isoformat(), "end": (day + timedelta(days=1)).isoformat()}).json()["items"]
    assert [x["kind"] for x in items if x["id"] == f"todo:{aid}"] == ["assessment"]
    assert [(x["id"], x["why"]) for x in c.get("/api/calendar/alarms/recent").json()] == [(f"todo:{aid}", "new")]
    c.post(f"/api/todos/{aid}/done", json={})
    items = c.get("/api/calendar", params={"start": day.isoformat(), "end": (day + timedelta(days=1)).isoformat()}).json()["items"]
    assert [x["done"] for x in items if x["id"] == f"todo:{aid}"] == [True]                 # (done: still on its day, marked so)
    # an interview with no time yet ("book a slot"): a task until it has one - then on the calendar alone, and said
    other = _application(2)
    nid = reminders.from_mail(other, "Acme · Firmware Co-op", "interview", "new", "Please book a time for a first interview", {}, "m5")
    assert [t["id"] for t in c.get("/api/todos").json()] == [nid] and overview()["open_todos"] == 1
    reminders.from_mail(other, "Acme · Firmware Co-op", "interview", "changed", "Booked", {"due": f"{day}T16:00"}, "m6")
    assert c.get("/api/todos").json() == [] and overview()["open_todos"] == 0
    assert (f"todo:{nid}", "new") in [(x["id"], x["why"]) for x in c.get("/api/calendar/alarms/recent").json()]
    # an offer to answer stays a task
    reminders.from_mail(app_id, "Acme · Firmware Co-op", "offer", "new", "An offer", {"due": f"{day}"}, "m7")
    assert [(t["kind"], t["ref"]) for t in c.get("/api/todos").json()] == [("followup", f"followup:{app_id}:offer")]
    assert overview()["open_todos"] == 1
