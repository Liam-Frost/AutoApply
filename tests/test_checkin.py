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
