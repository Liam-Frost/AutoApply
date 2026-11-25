"""After an interview or an assessment: a card asks whether it took place and how it went; the answer moves the
application on and is on its time line (2026-11-26, the owner)."""
from __future__ import annotations

from datetime import timedelta


def _application(n: int, status: str = "confirmed") -> int:
    from autoapply import db
    from autoapply.models import Application, Job

    with db.session() as s:
        j = Job(source="manual", source_id=f"ck{n}", company="Acme", title=f"Co-op {n}", apply_url=f"https://acme.example/{n}", jd_text="x" * 300)
        s.add(j)
        s.flush()
        a = Application(job_id=j.id, status=status)
        s.add(a)
        s.flush()
        return a.id


def test_after_its_time_a_card_asks_and_the_answer_moves_the_application_on_and_is_on_its_time_line(app_env):
    from fastapi.testclient import TestClient

    from autoapply import checkin, clock, db, reminders
    from autoapply.api.main import app
    from autoapply.models import Application, Todo

    db.set_setting("time.zone", "UTC")
    now = clock.now().replace(second=0, microsecond=0)
    interview_app, test_app, old_app = _application(1), _application(2), _application(3)
    iv = reminders.from_mail(interview_app, "Acme · Co-op 1", "interview", "new", "Video interview", {"due": (now + timedelta(hours=2)).isoformat(timespec="minutes")}, "m1")
    ts = reminders.from_mail(test_app, "Acme · Co-op 2", "assessment", "new", "Online assessment", {"due": (now + timedelta(hours=5)).isoformat(timespec="minutes")}, "m2")
    old = reminders.from_mail(old_app, "Acme · Co-op 3", "interview", "new", "Long ago", {"due": (now - timedelta(days=20)).isoformat(timespec="minutes")}, "m3")
    c = TestClient(app)
    cards = lambda: [t for t in c.get("/api/todos").json() if t["kind"] == "checkin"]  # noqa: E731

    assert checkin.ask_due(now) == 0 and cards() == []                                   # (before its time: nothing)
    assert checkin.ask_due(now + timedelta(hours=2, minutes=30)) == 0                     # (an interview: an hour after it began)
    assert checkin.ask_due(now + timedelta(hours=3, minutes=1)) == 1
    got = cards()
    assert [(t["payload"]["item_id"], t["payload"]["category"]) for t in got] == [(iv, "interview")] and got[0]["title"].startswith("Acme · Co-op 1")
    assert checkin.ask_due(now + timedelta(hours=4)) == 0                                 # (asked once)
    assert checkin.ask_due(now + timedelta(hours=5)) == 1                                 # an assessment: at its deadline
    with db.session() as s:
        assert not (s.get(Todo, old).payload or {}).get("checkin_asked")                  # over long ago (read back): not asked

    # it took place, it went well: the application moves on to that stage; the item is done on the calendar
    card = next(t for t in cards() if t["payload"]["item_id"] == iv)
    r = c.post(f"/api/todos/{card['id']}/checkin", json={"done": True, "feeling": "good", "note": "Asked about Kafka"}).json()
    assert r == {"done": True, "moved": True}
    with db.session() as s:
        assert s.get(Application, interview_app).status == "interview"
        item = s.get(Todo, iv)
        assert item.status == "done" and item.payload["checkin"]["feeling"] == "good" and item.payload["checkin"]["note"] == "Asked about Kafka"
    line = c.get(f"/api/applications/{interview_app}").json()["timeline"]
    ck = [e for e in line if e["kind"] == "checkin"]
    assert ck == [{"at": ck[0]["at"], "kind": "checkin", "category": "interview", "done": True, "feeling": "good", "note": "Asked about Kafka"}]
    # the assessment was not done: kept as that, nothing moved, the item stays on the calendar; a feeling is not kept then
    card = next(t for t in cards() if t["payload"]["item_id"] == ts)
    assert c.post(f"/api/todos/{card['id']}/checkin", json={"done": False, "feeling": "bad"}).json() == {"done": False, "moved": False}
    with db.session() as s:
        assert s.get(Application, test_app).status == "confirmed" and s.get(Todo, ts).status == "open"
        assert s.get(Todo, ts).payload["checkin"] == {**s.get(Todo, ts).payload["checkin"], "done": False, "feeling": ""}
    assert cards() == []
    assert c.post("/api/todos/999999/checkin", json={"done": True}).status_code == 404
    # an application already further on is not taken back
    later = _application(4, status="offer")
    lt = reminders.from_mail(later, "Acme · Co-op 4", "interview", "new", "Final round", {"due": (now - timedelta(hours=2)).isoformat(timespec="minutes")}, "m4")
    checkin.ask_due(now)
    card = next(t for t in cards() if t["payload"]["item_id"] == lt)
    assert c.post(f"/api/todos/{card['id']}/checkin", json={"done": True}).json()["moved"] is False
    with db.session() as s:
        assert s.get(Application, later).status == "offer"


def test_called_off_whole_day_rescheduled_and_all_read(app_env):
    """Review: nothing asked about what was called off; a whole day only once it is over; a new date asked about again,
    the first answer kept; a check-in is a question, never a notice that "All read" puts away."""
    from fastapi.testclient import TestClient

    from autoapply import checkin, clock, db, reminders
    from autoapply.api.main import app
    from autoapply.models import Todo

    db.set_setting("time.zone", "UTC")
    now = clock.now().replace(second=0, microsecond=0)
    c = TestClient(app)
    cards = lambda: [t for t in c.get("/api/todos").json() if t["kind"] == "checkin"]  # noqa: E731
    # called off: no card
    off = _application(11)
    reminders.from_mail(off, "Acme · Co-op 11", "interview", "new", "Interview", {"due": (now + timedelta(hours=1)).isoformat(timespec="minutes")}, "c1")
    reminders.from_mail(off, "Acme · Co-op 11", "interview", "cancelled", "Called off", {}, "c2")
    assert checkin.ask_due(now + timedelta(hours=3)) == 0
    # a whole day: not on the morning of it, once it is over
    day = _application(12)
    d0 = (now + timedelta(days=2)).date()
    reminders.from_mail(day, "Acme · Co-op 12", "assessment", "new", "Assessment", {"due": d0.isoformat()}, "c3")
    from datetime import datetime as _dt

    assert checkin.ask_due(_dt.combine(d0, _dt.min.time()) + timedelta(hours=9)) == 0
    assert checkin.ask_due(_dt.combine(d0, _dt.min.time()) + timedelta(days=1, minutes=1)) == 1
    # asked, answered "did not take place", then moved by the employer: asked again after the new time; both answers kept
    moved = _application(13)
    iv = reminders.from_mail(moved, "Acme · Co-op 13", "interview", "new", "Interview", {"due": (now - timedelta(hours=3)).isoformat(timespec="minutes")}, "c4")
    checkin.ask_due(now)
    card = next(t for t in cards() if t["payload"]["item_id"] == iv)
    c.post(f"/api/todos/{card['id']}/checkin", json={"done": False})
    reminders.from_mail(moved, "Acme · Co-op 13", "interview", "changed", "Moved", {"due": (now + timedelta(days=1)).isoformat(timespec="minutes")}, "c5")
    assert checkin.ask_due(now + timedelta(days=1, hours=2)) == 1
    card = next(t for t in cards() if t["payload"]["item_id"] == iv)
    c.post(f"/api/todos/{card['id']}/checkin", json={"done": True, "feeling": "ok", "note": "x" * 400})
    with db.session() as s:
        assert [x["done"] for x in s.get(Todo, iv).payload["checkins"]] == [False, True]
    line = [e for e in c.get(f"/api/applications/{moved}").json()["timeline"] if e["kind"] == "checkin"]
    assert sorted(e["done"] for e in line) == [False, True] and any(len(e["note"]) == 400 for e in line)
    # a question, not a notice: not in what "All read" puts away
    late = _application(14)
    reminders.from_mail(late, "Acme · Co-op 14", "interview", "new", "Interview", {"due": (now - timedelta(hours=2)).isoformat(timespec="minutes")}, "c6")
    checkin.ask_due(now)
    assert all(t["category"] != "info" for t in cards()) and cards()


def test_an_answer_is_about_the_time_the_card_asked_about_even_when_the_item_moved_since(app_env):
    """Review: an unanswered card, then the employer moves the interview: the answer is kept for the first time, the
    item is not marked done, and the new time is asked about once it has passed."""
    from fastapi.testclient import TestClient

    from autoapply import checkin, clock, db, reminders
    from autoapply.api.main import app
    from autoapply.models import Todo

    db.set_setting("time.zone", "UTC")
    now = clock.now().replace(second=0, microsecond=0)
    c = TestClient(app)
    a = _application(21)
    first = (now - timedelta(hours=3)).isoformat(timespec="minutes")
    iv = reminders.from_mail(a, "Acme · Co-op 21", "interview", "new", "Interview", {"due": first}, "r1")
    checkin.ask_due(now)
    card = next(t for t in c.get("/api/todos").json() if t["kind"] == "checkin")
    reminders.from_mail(a, "Acme · Co-op 21", "interview", "changed", "Moved", {"due": (now + timedelta(days=1)).isoformat(timespec="minutes")}, "r2")
    c.post(f"/api/todos/{card['id']}/checkin", json={"done": False})
    with db.session() as s:
        item = s.get(Todo, iv)
        assert item.status == "open" and item.payload["checkin"]["for"] == first
    assert checkin.ask_due(now + timedelta(days=1, hours=2)) == 1                                     # the new time: asked
