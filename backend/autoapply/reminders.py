"""Things with a date: an assessment to finish by Friday, an interview on Tuesday, a contact to write to next week -
and a card the applicant asked to be shown again later.

A mail that invites to an interview used to end in a notice ("you have an interview") and a status. What to do, and
by when, stayed in the mail. Now it becomes a card with its date: said the day before and on the day, moved when the
employer moves it, closed when the employer calls it off - and the applicant can complete it, move it, or put it off.

Only a date the mail itself states is used. A mail that names none gets a card without one.
"""
from __future__ import annotations

from .say import say as T

import logging
from datetime import datetime, timedelta
from typing import Any

from . import alarms, db, messages, notify
from .models import Application, Contact, Todo, now

log = logging.getLogger("autoapply.reminders")

# what a mail may ask the applicant to do, by what the mail is about
ASKS = ("interview", "assessment", "offer", "info_request")
KIND = "followup"


def parse_due(text: str) -> datetime | None:
    """A date, or a date and a time, as the model copied it from the mail in ISO form. Anything else: no date."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is not None:      # kept as the local wall clock time: that is what "Tuesday at 10" means to the applicant here
        d = d.astimezone().replace(tzinfo=None)
    return d


def _ref(application_id: int, category: str) -> str:
    return f"followup:{application_id}:{category}"


def from_mail(application_id: int, title: str, category: str, event: str, summary: str, asks: dict[str, Any] | None, message_id: str) -> int | None:
    """What a mail about an application asks of the applicant, as a card with its date. Returns the card's id.

    One card per application and kind of thing (its interview, its assessment): a mail that moves the date moves the
    card; a mail that calls it off closes the card; a reminder changes nothing."""
    if category not in ASKS:
        return None
    ref = _ref(application_id, category)
    if event == "cancelled":
        notify.close_todos(KIND, ref)
        return None
    asks = asks or {}
    due = parse_due(str(asks.get("due") or ""))
    action = str(asks.get("action") or "").strip()[:300]
    body = "\n".join(x for x in (action, T("server.reminders.theTimeAsThe", p0=str(asks['due_text']).strip()[:200]) if asks.get("due_text") else "", summary) if x)
    payload = {"application_id": application_id, "message_id": message_id, "category": category, "due_text": str(asks.get("due_text") or "")[:200],
               "date_only": bool(due) and "T" not in str(asks.get("due") or "") and " " not in str(asks.get("due") or "").strip()}
    links = list(asks.get("links") or [])
    if links:      # where it leads: one link is that; of several, the applicant chooses (the calendar lists them) - never guessed
        payload["links"] = links
    with db.session() as s:
        t = s.query(Todo).filter_by(kind=KIND, ref=ref, status="open").first()
        if t is not None:
            if event == "reminder" and not due:
                return t.id
            old = dict(t.payload or {})
            t.body, t.payload = body or t.body, {**old, **payload}
            if len(links) == 1 and old.get("link_by") != "user":
                t.payload = {**t.payload, "link": links[0]["url"]}
            first_date = due is not None and t.due_at is None
            if due and due != t.due_at:
                t.due_at, t.snoozed_until = due, None      # a new date from the employer: it is shown again (its reminders move with it)
            # (the same date said once more - a reminder - leaves a card that was put off where the applicant put it)
            tid, existing = t.id, True
        else:
            t = Todo(kind=KIND, ref=ref, title=f"{title}：{messages.mail_label(category, 'new')[1]}", body=body,
                     payload={**payload, "link": links[0]["url"]} if len(links) == 1 else payload, due_at=due)
            s.add(t)
            s.flush()
            tid, existing, first_date = t.id, False, due is not None      # (no notice here: the mail itself was just announced)
    if first_date:      # a date for the first time: the reminders of its kind (a moved date keeps the ones it has, and they move with it)
        alarms.give_defaults(f"todo:{tid}", category, due, bool(payload["date_only"]))
    if existing:
        return tid
    if category == "info_request" and message_id:      # something to answer by mail: the answer is written while the applicant reads the card
        from . import tasks

        tasks.enqueue("mail_reply", ref=f"todo:{tid}", payload={"todo_id": tid}, priority=40)
    return tid


def snooze(todo_id: int, until: datetime | None) -> None:
    """Show this card again later (None: now)."""
    with db.session() as s:
        t = s.get(Todo, todo_id)
        if t is None:
            raise KeyError(todo_id)
        t.snoozed_until = until
        if until is not None:
            t.payload = {**(t.payload or {}), "_snooze_told": False}


def set_due(todo_id: int, due: datetime | None) -> None:
    """The applicant corrects (or removes) the date of a card. It is said again for the new date."""
    with db.session() as s:
        t = s.get(Todo, todo_id)
        if t is None:
            raise KeyError(todo_id)
        first_date = due is not None and t.due_at is None
        t.due_at = due
        t.payload = {**(t.payload or {}), "date_only": bool(due) and due.hour == 0 and due.minute == 0, "date_by": "user"}
        kind = "own" if t.kind == "note" else "contact" if (t.payload or {}).get("contact_id") else str((t.payload or {}).get("category") or "")
        all_day = t.payload["date_only"]
    if first_date and kind:      # a date for the first time: the reminders of its kind (a moved date keeps the ones it has)
        alarms.give_defaults(f"todo:{todo_id}", kind, due, all_day)


def snoozed(t: Todo, at: datetime | None = None) -> bool:
    at = at or datetime.now()
    return t.snoozed_until is not None and t.snoozed_until > at


def check(at: datetime | None = None) -> dict[str, int]:
    """Every few minutes: show again what was put off until now, and make a card for a contact whose follow-up day has
    come. (What is coming up is said by its reminders - alarms.py, every minute.)"""
    at = at or datetime.now()
    out = {"shown_again": 0, "contacts": 0}
    tell: list[tuple[str, Any, str]] = []
    with db.session() as s:
        for t in s.query(Todo).filter_by(status="open"):
            p = dict(t.payload or {})
            if t.snoozed_until is not None and t.snoozed_until <= at:
                t.snoozed_until = None
                out["shown_again"] += 1
                tell.append(("todo", messages.reminder(t.title, "again", t.due_at, bool(p.get("date_only"))), f"todo:{t.id}"))
        # a contact to get back to: on the day (or the first look after it), a card - once per contact and date
        today = at.date().isoformat()
        for c in s.query(Contact).filter(Contact.follow_up != "", Contact.follow_up <= today):
            ref = f"contact:{c.id}:{c.follow_up}"
            if s.query(Todo).filter_by(kind=KIND, ref=ref).first() is not None:
                continue
            try:
                when = datetime.fromisoformat(c.follow_up)
            except ValueError:
                continue
            s.add(Todo(kind=KIND, ref=ref, title=T("server.reminders.followUp", p0=c.name) + (f"（{c.company}）" if c.company else ""), body=(c.note or "")[:400],
                       payload={"contact_id": c.id, "date_only": True}, due_at=when))
            out["contacts"] += 1
            tell.append(("todo", messages.reminder(T("server.reminders.followUp", p0=c.name) + (f"（{c.company}）" if c.company else ""), "day", when, True), ref))
    for category, card, ref in tell:
        try:
            notify.send(category, card, ref=ref)
        except Exception:  # noqa: BLE001 - the card is there whatever the notice does
            log.exception("a reminder could not be sent")
    try:
        notify.flush_held(at)        # what was held back for the night goes out in the morning
    except Exception:  # noqa: BLE001
        log.exception("held notices could not be sent")
    return out
