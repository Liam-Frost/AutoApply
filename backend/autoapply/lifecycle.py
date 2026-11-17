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
from .models import RANK, SENT, UNKNOWN, Application, Draft, Task, Todo, now

log = logging.getLogger("autoapply.lifecycle")

LABEL = {"submitted": "已提交", "confirmed": "已确认收到", "assessment": "测评中", "interview": "面试中", "offer": "已拿到 offer", "rejected": "已被拒"}
# cards that ask the applicant to do something for this application; a card about a driver, a setting or a mail is not one
CARDS = ("failed", "submit", "answer", "takeover", "login", "blocked", "captcha")
WORK = ("recon", "scout", "execute", "revise", "reanswer", "tailor")     # tasks that prepare or fill an application


def move(app: Any, to: str, *, source: str, evidence: dict[str, Any] | None = None, at: datetime | None = None, back: bool = False) -> bool:
    """Put an application at ``to``. The one way an application's status is written.

    ``app``: the application (in the caller's session) or its id. ``source``: who says so - "run" (the program filled
    or submitted), "mail", "site" (the employer's site shows it), "user", "draft" (preparing it), "resume", "recover".
    Returns whether the application is at ``to`` afterwards. It is not when it has gone out and ``to`` would take it
    back (models: the rule is kept at the attribute): the caller's news is old, and what it says about the present -
    "failed", "being read" - is not said.

    ``evidence`` is added to what is there, never put in its place - also when the status was kept: what a run saw on
    the page is worth keeping even if a mail got there first. ``at``: when it was sent, used when it becomes a sent
    application and no date is known yet. ``back``: the two cases that may take a sent application back - the applicant
    correcting the record, and a mail calling off the stage it stands at."""
    if not isinstance(app, Application):
        with db.session() as s:
            a = s.get(Application, int(app))
            return a is not None and move(a, to, source=source, evidence=evidence, at=at, back=back)
    was = app.status
    if to != was:
        app.__dict__["_moving"] = {"source": source, "back": back}
        try:
            app.status = to
        finally:
            app.__dict__.pop("_moving", None)
        if app.status != was:
            app.__dict__["_moved_by"] = source       # kept with the change (db: the history of an application's status)
    if evidence:
        add_evidence(app, evidence)
    if app.status == to and to in SENT and was not in SENT and at is not None and app.submitted_at is None:
        app.submitted_at = at
    return app.status == to


def add_evidence(app: Application, more: dict[str, Any]) -> None:
    """Add to what shows an application was sent. What a page showed (text, url, screenshot) is the latest page's; the
    mails about it are all kept (``mail_ids``; ``mail_id`` stays the latest, for what reads one); nothing else that is
    there is dropped."""
    ev = dict(app.evidence or {})
    mid = more.get("mail_id")
    if mid:
        ids = list(ev.get("mail_ids") or ([ev["mail_id"]] if ev.get("mail_id") else []))
        if mid not in ids:
            ids.append(mid)
        ev["mail_ids"] = ids
    ev.update({k: v for k, v in more.items() if v not in (None, "")})
    app.evidence = ev


def is_sent(app: Application | None) -> bool:
    return app is not None and app.status in SENT


def furthest(a: str, b: str) -> str:
    """The stage that is further along of two (a stage that is not a sent one is before all that are)."""
    return a if RANK.get(a, 0) >= RANK.get(b, 0) else b


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
            move(a, "submitted", source="site", evidence=seen)
            a.detail = f"the site shows it as applied (seen {now().date().isoformat()})"
            if a.submitted_at is None:
                a.submitted_at = applied_on(seen["text"])
        a.last_event = APPLIED_BEFORE
    notify.send("task_result", messages.submitted(title, evidence=seen["text"], note="already applied"), ref=f"application:{application_id}")


def outcome_unknown(application_id: int, title: str, said: str, *, draft_id: int | None = None, source: str = "run") -> None:
    """Submit was pressed - by the program, by the applicant in their window, or by something that should not have - and
    nothing says the application was received. Put it there, say so in one card, and look for the confirmation mail as
    after any submission. (An application that has meanwhile gone out stays where it is.)"""
    from . import messages, notify, tasks

    with db.session() as s:
        a = s.get(Application, application_id)
        if a is None or a.status in SENT:
            return
        if move(a, UNKNOWN, source=source):
            a.last_event = said[:500]
    for kind in ("failed", "submit"):
        notify.close_todos(kind, f"application:{application_id}")
    notify.add_todo("submit", f"{title}：提交结果待确认", body=f"{said}。如果已经提交成功，雇主的确认邮件会把它记为已投出；程序会继续留意邮箱，你也可以现在就查。"[:500],
                    ref=f"application:{application_id}", payload={"draft_id": draft_id, "application_id": application_id},
                    push=not db.get_setting("notify.task_result"))
    for m in db.get_setting("mail.confirm_check_minutes") or []:
        tasks.enqueue_later("mail", ref=f"confirm:{application_id}", minutes=float(m), priority=40)
    notify.send("task_result", messages.submit_unknown(title, said=said), ref=f"application:{application_id}")


def unknown_from_before() -> list[int]:
    """Runs of earlier versions that pressed Submit and saw no confirmation were filed as failed, with a card that offered
    to fill the form in again. They are what they are: submissions whose outcome is not known. Returns the applications."""
    from . import notify

    found: dict[int, tuple[int, int | None, str]] = {}
    with db.session() as s:
        for t in s.query(Todo).filter(Todo.status == "open", Todo.kind.in_(("failed", "submit"))):
            p = t.payload or {}
            if not (p.get("maybe_submitted") or "no confirmation after submit" in (t.body or "")):
                continue
            d = s.get(Draft, int(p["draft_id"])) if p.get("draft_id") else None
            a = s.get(Application, int(p["application_id"])) if p.get("application_id") else (d.application if d is not None else None)
            if a is None or a.status in SENT or a.status not in ("failed", "ready_to_submit"):
                continue
            job = a.job
            found[a.id] = (t.id, d.id if d is not None else None, f"{job.company} · {job.title}" if job is not None else "")
            t.status, t.done_at = "done", now()
            if move(a, UNKNOWN, source="recover"):
                a.last_event = "点过提交，但没有看到提交成功的页面；等确认邮件核实"
    for app_id, (_, draft_id, title) in found.items():
        notify.add_todo("submit", f"{title}：提交结果待确认", ref=f"application:{app_id}", payload={"draft_id": draft_id, "application_id": app_id},
                        body="点过提交，但没有看到提交成功的页面。如果已经提交成功，雇主的确认邮件会把它记为已投出；你也可以现在就查。", push=False)
    return sorted(found)


def settle_all() -> int:
    """At start: applications that were sent before this rule existed (or while the program was not running)."""
    with db.session() as s:
        ids = [a.id for a in s.query(Application).filter(Application.status.in_(SENT))]
    return sum(1 for i in ids if any(settle(i).values()))
