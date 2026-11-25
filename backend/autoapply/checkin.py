"""After an interview or an assessment: did it happen, and how did it go?

An interview or an assessment from an employer's mail is an item of the calendar alone (models.EVENT_FOLLOWUPS). Its
time passed, and nothing asked whether it took place - the application stayed where it was, and how it went was
nowhere (2026-11-26, the owner: "once the date of an assessment or an interview has passed, a card that asks me whether
I did it, which then moves the application on - and lets me say how it went"). So, once its time is past - an
interview an hour after it began, an assessment at its deadline - a card asks: done, or not; and how it felt (well, so-so,
badly), with a word of the applicant's own. The answer is kept with the calendar item (``payload["checkin"]``), shown on
the application's time line, and moves the application on to that stage when it was not there yet. Items that were
already over before the card existed (read back from old mail) are not asked about: the card is for what just happened.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from . import clock, db, lifecycle, notify
from .models import RANK, Application, Todo, now

KIND = "checkin"
AFTER = {"interview": timedelta(hours=1), "assessment": timedelta(0)}      # how long after its time the card comes
RECENT = timedelta(days=7)        # an item over longer ago than this is not asked about any more
FEELINGS = ("good", "ok", "bad")


def ask_due(at: datetime | None = None) -> int:
    """Cards for the interviews and assessments whose time just passed, not answered and not asked yet."""
    here = at or clock.now()
    made = 0
    with db.session() as s:
        items = [(t.id, t.title, dict(t.payload or {}), t.due_at) for t in s.query(Todo).filter(Todo.kind == "followup", Todo.status != "dismissed", Todo.due_at.isnot(None))]
    for tid, title, p, due in items:
        wait = AFTER.get(str(p.get("category") or ""))
        when = due.isoformat(timespec="minutes")      # (this occurrence: a new date is asked about again)
        if wait is None or p.get("cancelled") or p.get("checkin_asked") == when or (p.get("checkin") or {}).get("for") == when:
            continue
        # a whole day (the mail gave a date, no time): once that day is over; else an hour after an interview began,
        # at an assessment's deadline
        end = due + timedelta(days=1) if p.get("date_only") or p.get("all_day") else due + wait
        if not (end <= here <= end + RECENT):
            continue
        notify.add_todo(KIND, title, body="", ref=f"{KIND}:{tid}", payload={"item_id": tid, "category": p["category"], "application_id": p.get("application_id"), "for": when})
        with db.session() as s:
            t = s.get(Todo, tid)
            t.payload = {**(t.payload or {}), "checkin_asked": when}
        made += 1
    return made


def answer(card_id: int, *, done: bool, feeling: str = "", note: str = "") -> dict[str, Any]:
    """The applicant's answer: kept with the calendar item; a done one is marked done there and moves its application
    on to that stage; the card closes."""
    feeling = feeling if done and feeling in FEELINGS else ""      # (how it went: of what took place)
    with db.session() as s:
        card = s.get(Todo, card_id)
        if card is None or card.kind != KIND:
            raise KeyError(card_id)
        p = dict(card.payload or {})
        item = s.get(Todo, int(p.get("item_id") or 0))
        if item is None:
            raise KeyError(card_id)
        cat = str((item.payload or {}).get("category") or p.get("category") or "")
        # (the occurrence the card asked about - the item may have been moved since: the answer is about that one)
        current = item.due_at.isoformat(timespec="minutes") if item.due_at else ""
        asked = str(p.get("for") or current)
        said = {"done": bool(done), "feeling": feeling, "note": str(note or "").strip()[:500], "at": now().isoformat(), "for": asked}
        # (the latest answer, and every answer of the item - one for each time it was to take place)
        item.payload = {**(item.payload or {}), "checkin": said, "checkins": [*((item.payload or {}).get("checkins") or []), said]}
        if done and item.status == "open" and asked == current:      # (moved since: the new date is still ahead)
            item.status, item.done_at = "done", now()
        moved = False
        app_id = (item.payload or {}).get("application_id") or p.get("application_id")
        if done and app_id:
            a = s.get(Application, int(app_id))
            if a is not None and cat in RANK and RANK.get(a.status, 0) < RANK[cat]:
                moved = lifecycle.move(a, cat, source="user")
        card.status, card.done_at = "done", now()
    return {"done": bool(done), "moved": moved}
