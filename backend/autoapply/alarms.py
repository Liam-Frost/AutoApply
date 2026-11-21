"""Reminders of dated items: an interview a day before and half an hour before, an assessment the evening before it is
due, a deadline two days before - as many as the applicant wants, each "this long before".

Each kind of item has reminders it gets by itself when it appears (``calendar.reminders``: an interview a day before
and 30 minutes before, ...); the applicant adds and removes them per item. A reminder of a whole-day item (most
deadlines, a contact's day) is in the morning: "1 day before" is the morning before, "0" the morning of the day
(``calendar.allday_at``, 09:00).

A reminder belongs to the item, not to a moment: when the employer moves the interview, the reminders move with it and
are said again for the new time; an item that is done, called off or applied for is not reminded of. They go out on
the channels the applicant has, through the quiet hours too - they set the time themselves - unless they said they
should keep to them (``calendar.reminders_quiet``). Looked at every minute.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from . import db
from .models import Alarm

log = logging.getLogger("autoapply.alarms")

CHOICES = (5, 15, 30, 60, 120, 1440, 2880, 10080)      # what the page offers (minutes); anything else can be typed


def defaults(kind: str) -> list[int]:
    return [int(x) for x in ((db.get_setting("calendar.reminders") or {}).get(kind) or []) if int(x) >= 0]


def _morning() -> tuple[int, int]:
    try:
        h, m = map(int, str(db.get_setting("calendar.allday_at") or "09:00").split(":"))
        return h, m
    except ValueError:
        return 9, 0


def fire_at(start: datetime, all_day: bool, before: int) -> datetime:
    """When a reminder goes off."""
    if all_day:
        h, m = _morning()
        days = before // 1440 + (1 if before % 1440 else 0)
        return datetime.combine(start.date() - timedelta(days=days), datetime.min.time()).replace(hour=h, minute=m)
    return start - timedelta(minutes=before)


def add(item: str, before: int, *, by: str = "user") -> int:
    before = max(0, min(int(before), 60 * 24 * 60))
    with db.session() as s:
        same = s.query(Alarm).filter_by(item=item, before=before).first()
        if same is not None:
            return same.id
        a = Alarm(item=item, before=before, by=by)
        s.add(a)
        s.flush()
        return a.id


def remove(alarm_id: int) -> None:
    with db.session() as s:
        a = s.get(Alarm, alarm_id)
        if a is not None:
            s.delete(a)


def of(item: str) -> list[dict[str, Any]]:
    with db.session() as s:
        return [{"id": a.id, "before": a.before, "by": a.by, "sent": bool(a.sent_for)} for a in s.query(Alarm).filter_by(item=item).order_by(Alarm.before.desc())]


def by_item(items: list[str]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    with db.session() as s:
        for a in s.query(Alarm).filter(Alarm.item.in_(items)) if items else []:
            out.setdefault(a.item, []).append(a.before)
    return out


def give_defaults(item: str, kind: str, start: datetime | None = None, all_day: bool = False) -> int:
    """An item has just appeared: the reminders of its kind (none that would already have gone off)."""
    n = 0
    wanted = defaults(kind)
    if all_day:      # a whole day is reminded of in the morning: "2 hours before" and "1 day before" are the same morning
        wanted = sorted({-(-b // 1440) * 1440 for b in wanted}, reverse=True)
    for before in wanted:
        if start is not None and fire_at(start, all_day, before) <= datetime.now():
            continue
        add(item, before, by="default")
        n += 1
    return n


def tick(at: datetime | None = None) -> int:
    """Send the reminders whose time has come. Returns how many went out."""
    from . import agenda, messages, notify

    at = at or datetime.now()
    today = at.date()
    with db.session() as s:
        rows = [(a.id, a.item, a.before, a.sent_for) for a in s.query(Alarm)]
    if not rows:
        return 0
    wanted = {r[1] for r in rows}
    items = {x["id"]: x for x in agenda.items(today - timedelta(days=1), today + timedelta(days=62), kinds=agenda.KINDS[:7]) if x["id"] in wanted and not x["done"]}
    quiet_too = not db.get_setting("calendar.reminders_quiet")
    sent = 0
    for aid, item, before, sent_for in rows:
        x = items.get(item)
        if x is None or sent_for == x["start"]:
            continue
        start = datetime.fromisoformat(x["start"])
        when = fire_at(start, x["all_day"], before)
        # its time has come - and not so long ago that the item itself is over (a program that was off all night does
        # not remind of yesterday's interview this morning)
        over = (start.date() < today) if x["all_day"] else start + timedelta(minutes=10) < at
        if when > at or over:
            continue
        with db.session() as s:
            a = s.get(Alarm, aid)
            if a is None or a.sent_for == x["start"]:
                continue
            a.sent_for, a.sent_at = x["start"], datetime.now()
        card = messages.alarm(x["title"], x["subject"], start, x["all_day"], x["kind"], before, x["link"])
        try:
            notify.send("todo", card, ref=f"alarm:{item}", tag="reminder", through_quiet=quiet_too, todo_id=x["about"]["todo_id"])
        except Exception:  # noqa: BLE001 - the item is on the calendar whatever the notice does
            log.exception("a reminder could not be sent")
        sent += 1
    return sent


def recent(hours: int = 12) -> list[dict[str, Any]]:
    """The reminders that went off lately, for the top of the to-do page."""
    since = datetime.now() - timedelta(hours=hours)
    with db.session() as s:
        rows = [(a.item, a.before, a.sent_for, a.sent_at) for a in s.query(Alarm).filter(Alarm.sent_at.isnot(None), Alarm.sent_at >= since).order_by(Alarm.sent_at.desc())]
    if not rows:
        return []
    from . import agenda

    today = date.today()
    items = {x["id"]: x for x in agenda.items(today - timedelta(days=1), today + timedelta(days=62), kinds=agenda.KINDS[:7])}
    out = []
    for item, before, sent_for, sent_at in rows:
        x = items.get(item)
        if x is not None and not x["done"] and x["start"] == sent_for and item not in {o["id"] for o in out}:
            out.append({**x, "before": before, "sent_at": sent_at.isoformat(timespec="minutes")})
    return out


def migrate() -> int:
    """Once, on the first start of this version: the dated cards already open get the reminders of their kind - the
    fixed "the day before and on the day" was the program's own until now."""
    from . import agenda

    today = date.today()
    n = 0
    for x in agenda.items(today, today + timedelta(days=120), kinds=("interview", "assessment", "offer", "info_request", "contact", "own")):
        if not x["done"] and x["id"].startswith("todo:") and not of(x["id"]):
            n += give_defaults(x["id"], x["kind"], datetime.fromisoformat(x["start"]), x["all_day"])
    return n
