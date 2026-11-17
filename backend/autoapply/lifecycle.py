"""What follows from an application having been sent.

An application reaches "sent" by many roads: the program submits it, the user submits it in the program's window or on
the employer's site, the site says an application already exists, a confirmation arrives by mail. Whichever road it was,
the same things are true afterwards: nothing is left for the applicant to do about it, its drafts are no longer waiting,
and no task should work on its form again. ``settle`` makes that so; the database session calls it whenever an
application's status changes to a sent one, so no road can forget it.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from . import db
from .models import SENT, Application, Draft, Task, Todo, now

log = logging.getLogger("autoapply.lifecycle")

LABEL = {"submitted": "已提交", "confirmed": "已确认收到", "assessment": "测评中", "interview": "面试中", "offer": "已拿到 offer", "rejected": "已被拒"}
# cards that ask the applicant to do something for this application; a card about a driver, a setting or a mail is not one
CARDS = ("failed", "submit", "answer", "takeover", "login", "blocked", "captcha")
WORK = ("recon", "scout", "execute", "revise", "reanswer", "tailor")     # tasks that prepare or fill an application


def settle(application_id: int) -> dict[str, int]:
    """Close what waited on an application that has been sent: its cards, its unapproved drafts, its queued work."""
    closed = {"todos": 0, "drafts": 0, "tasks": 0}
    with db.session() as s:
        a = s.get(Application, application_id)
        if a is None or a.status not in SENT:
            return closed
        job = a.job
        # (When it was sent is set by whoever knows - the run that submitted, the mail that confirmed. An application that
        # was sent at an unknown time keeps no date: giving it "now" once dated 59 old applications to one afternoon.)
        if job is not None and job.status not in ("applied", "closed"):
            job.status = "applied"
        draft_ids = [d.id for d in a.drafts]
        refs = {f"application:{a.id}", *(f"draft:{i}" for i in draft_ids)} | ({f"job:{job.id}"} if job is not None else set())
        urls = {job.apply_url} if job is not None and job.apply_url else set()
        for t in s.query(Todo).filter_by(status="open"):
            p = t.payload or {}
            # cards filed under the site (a sign-in for this posting) carry the posting's address or its draft
            mine = t.ref in refs or p.get("application_id") == a.id or p.get("draft_id") in draft_ids or (p.get("job_url") in urls if urls else False)
            if mine and t.kind in CARDS:
                t.status, t.done_at = "done", now()
                closed["todos"] += 1
        for d in a.drafts:
            if d.review_status == "pending":      # nothing is left to approve
                d.review_status = "closed"
                closed["drafts"] += 1
        for t in s.query(Task).filter(Task.kind.in_(WORK), Task.ref.in_(refs), Task.status.in_(("queued", "waiting_human"))):
            t.status = "cancelled"
            closed["tasks"] += 1
    if any(closed.values()):
        log.info("application %s is sent: closed %s", application_id, closed)
    return closed


APPLIED_BEFORE = "雇主网站显示这个岗位已经申请过了，没有再提交一次"
_MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}


def applied_on(text: str) -> datetime | None:
    """The date in what the site said ("You applied on Nov 3, 2026"), if it gives one that can be a date of applying."""
    text = text or ""
    dates: list[tuple[int, tuple[int, int, int]]] = []       # (where it stands in the text, year-month-day)
    for m in re.finditer(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b", text):
        dates.append((m.start(), (int(m[1]), int(m[2]), int(m[3]))))
    for m in re.finditer(r"\b([A-Za-z]{3})[a-z]*\.? (\d{1,2})(?:st|nd|rd|th)?,? (20\d\d)\b", text):
        dates.append((m.start(), (int(m[3]), _MONTHS.get(m[1].lower(), 0), int(m[2]))))
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)? ([A-Za-z]{3})[a-z]*\.?,? (20\d\d)\b", text):
        dates.append((m.start(), (int(m[3]), _MONTHS.get(m[2].lower(), 0), int(m[1]))))
    for at, found in sorted(dates):
        # only a date the text ties to applying: "applied on ...", "submitted: ...". A deadline or a posting date next to
        # "you have already applied" is not when the application was sent.
        lead = text[max(0, at - 40):at]
        tied = re.search(r"(applied|submitted|received|申请于|提交于)[^.;\n]*$", lead, re.I)
        if not tied or re.search(r"deadline|closes?|closing|posted|due|expires?|until|截止", lead[tied.start():], re.I):
            continue
        try:
            day = datetime(*found)
        except ValueError:
            continue
        if day <= now().replace(tzinfo=None):
            return day
    return None


def applied_before(application_id: int, seen: Any = None) -> None:
    """The employer's site shows this posting as applied for already, and the program met that before it had a form to
    fill (while reading it). The application is a sent one: recorded with what the site showed, and what waited on it is
    closed (settle, through the status change). When it was sent is only set if the site said so."""
    from . import messages, notify

    seen = {"text": "The site shows this job as already applied.", **(seen if isinstance(seen, dict) else {}), "already_applied": "yes"}
    with db.session() as s:
        a = s.get(Application, application_id)
        if a is None:
            return
        title = f"{a.job.company} · {a.job.title}" if a.job is not None else ""
        if a.status not in SENT:
            a.status = "submitted"
            a.evidence = seen
            a.detail = f"the site shows it as applied (seen {now().date().isoformat()})"
            if a.submitted_at is None:
                a.submitted_at = applied_on(seen["text"])
        a.last_event = APPLIED_BEFORE
    notify.send("task_result", messages.submitted(title, evidence=seen["text"], note="already applied"), ref=f"application:{application_id}")


def settle_all() -> int:
    """At start: applications that were sent before this rule existed (or while the program was not running)."""
    with db.session() as s:
        ids = [a.id for a in s.query(Application).filter(Application.status.in_(SENT))]
    return sum(1 for i in ids if any(settle(i).values()))
