"""An application made elsewhere (2026-11-23): an interview invitation for a posting the program never had came as an
e-mail that matched no application, and its date could go nowhere. Its card now puts the date the e-mail gives on the
applicant's own calendar - converted from the zone the e-mail said it in, with its end, its words and its link - once.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from autoapply.i18n import tr


@pytest.fixture()
def desk(app_env):
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app as api

    db.set_setting("time.zone", "UTC")          # (a zone without daylight time: the conversion below is fixed)
    db.set_setting("ui.lang", "en")
    return TestClient(api)


def _mail(message_id: str, asks: dict, *, category: str = "interview", company: str = "Example Corp") -> int:
    from autoapply import db, notify
    from autoapply.models import MailEvent

    with db.session() as s:
        s.add(MailEvent(message_id=message_id, sender="recruiting@example.com", subject="Interview invitation", category=category,
                        company_guess=company, summary="A first technical interview, one hour, by video.", asks=asks,
                        received_at=datetime(2026, 11, 20, tzinfo=timezone.utc)))
    return notify.add_todo("mail_unmatched", "Interview invitation", body="x", ref=f"mail:{message_id}",
                           payload={"message_id": message_id, "category": category}, push=False)


INVITATION = {"action": "Join the video interview", "due": "2026-11-27T15:00", "due_zone": "Asia/Shanghai", "due_end": "2026-11-27T16:00",
              "due_text": "27 November, 15:00 Beijing time", "links": [{"url": "https://meet.example.com/j/123", "label": "Join"}]}


def _card(desk, todo_id):
    return next(t for t in desk.get("/api/todos").json() if t["id"] == todo_id)


def test_the_date_an_email_gives_goes_on_the_applicants_own_calendar_on_their_clock(desk):
    from autoapply import db
    from autoapply.models import Todo

    tid = _mail("m1", INVITATION)
    card = _card(desk, tid)
    # the card shows what it would put there: the time on the applicant's clock (15:00 in Shanghai is 07:00 UTC), and the words
    assert card["mail_when"] == {"start": "2026-11-27T07:00", "all_day": False, "end": "2026-11-27T08:00", "said": "27 November, 15:00 Beijing time"}
    assert card["on_calendar"] is None

    r = desk.post(f"/api/todos/{tid}/to-calendar").json()
    assert r["existing"] is False and r["start"] == "2026-11-27T07:00"
    with db.session() as s:
        own = s.get(Todo, r["id"])
        assert own.kind == "note" and tr(own.title, "en") == "Interview · Example Corp" and own.due_at == datetime(2026, 11, 27, 7, 0)
        p = own.payload
        assert p["link"] == "https://meet.example.com/j/123" and p["end_at"] == "2026-11-27T08:00" and p["from_mail"] == "m1"
        assert p["due_zone"] == "Asia/Shanghai" and p["due_said"] == "2026-11-27T15:00" and p["all_day"] is False
        assert "Join the video interview" in own.body and "15:00 Beijing time" in own.body
        # the mail is dealt with: its card is closed, and the calendar item (a card of its own) is what is left. The card
        # used to stay; beside the item's card it read as the same thing twice, the wrong one was closed and the item was gone
        assert s.query(Todo).filter_by(kind="mail_unmatched").one().status == "done"
    assert desk.get("/api/todos").json() == []          # (the item is on the calendar, not a task on the to-do page)

    # on the calendar, as the applicant's own item, with its end
    items = desk.get("/api/calendar", params={"start": "2026-11-27", "end": "2026-11-28"}).json()["items"]
    mine = [x for x in items if x.get("title") == "Interview · Example Corp"]
    assert len(mine) == 1 and mine[0]["start"].startswith("2026-11-27T07:00") and mine[0]["end"].startswith("2026-11-27T08:00")

    # once: asking again (a second press, a page not reloaded) makes no second item
    again = desk.post(f"/api/todos/{tid}/to-calendar").json()
    assert again == {"id": r["id"], "existing": True}
    with db.session() as s:
        assert s.query(Todo).filter_by(kind="note").count() == 1


def test_an_item_removed_from_the_calendar_by_mistake_is_put_back_with_undo_and_a_whole_day_stays_one(desk):
    from autoapply import db
    from autoapply.models import Todo

    tid = _mail("m2", {"action": "Finish the online assessment", "due": "2026-12-04", "due_text": "within two weeks"}, category="assessment")
    assert _card(desk, tid)["mail_when"]["all_day"] is True
    first = desk.post(f"/api/todos/{tid}/to-calendar").json()["id"]
    with db.session() as s:
        own = s.get(Todo, first)
        assert own.due_at == datetime(2026, 12, 4) and own.payload["all_day"] is True and tr(own.title, "en") == "Assessment · Example Corp"
    on_the_4th = lambda: [x for x in desk.get("/api/calendar", params={"start": "2026-12-04", "end": "2026-12-05"}).json()["items"] if x.get("kind") == "own"]  # noqa: E731
    assert len(on_the_4th()) == 1
    # "Remove from my calendar" on its card, then "Undo" in the notice: back, with its date
    desk.post(f"/api/todos/{first}/done", json={"status": "dismissed", "resume": False})
    assert on_the_4th() == []
    assert desk.post(f"/api/todos/{first}/reopen").json() == {"reopened": True}
    assert len(on_the_4th()) == 1 and desk.post(f"/api/todos/{first}/reopen").json() == {"reopened": False}
    # removed for good: the mail can be put on the calendar again (a new item)
    desk.post(f"/api/todos/{first}/done", json={"status": "dismissed", "resume": False})
    assert desk.post(f"/api/todos/{tid}/to-calendar").json()["id"] != first


def test_no_date_is_invented_and_other_cards_are_not_mails(desk):
    from autoapply import db, notify
    from autoapply.models import Todo

    tid = _mail("m3", {"action": "Reply with your availability", "due": ""})
    card = _card(desk, tid)
    assert "mail_when" not in card
    r = desk.post(f"/api/todos/{tid}/to-calendar")
    assert r.status_code == 409 and "no date" in r.json()["detail"]      # (said in the language of the page that asked)
    other = notify.add_todo("config", "Something to set", ref="config:x", push=False)
    assert desk.post(f"/api/todos/{other}/to-calendar").status_code == 400
    with db.session() as s:
        assert s.query(Todo).filter_by(kind="note").count() == 0
