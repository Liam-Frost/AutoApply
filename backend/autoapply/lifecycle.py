"""What follows from an application having been sent.

An application reaches "sent" by many roads: the program submits it, the user submits it in the program's window or on
the employer's site, the site says an application already exists, a confirmation arrives by mail. Whichever road it was,
the same things are true afterwards: nothing is left for the applicant to do about it, its drafts are no longer waiting,
and no task should work on its form again. ``settle`` makes that so; the database session calls it whenever an
application's status changes to a sent one, so no road can forget it.
"""
from __future__ import annotations

import logging

from . import db
from .models import Application, Draft, Task, Todo, now

log = logging.getLogger("autoapply.lifecycle")

SENT = ("submitted", "confirmed", "assessment", "interview", "offer", "rejected")
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
        if a.submitted_at is None:
            a.submitted_at = now()
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


def settle_all() -> int:
    """At start: applications that were sent before this rule existed (or while the program was not running)."""
    with db.session() as s:
        ids = [a.id for a in s.query(Application).filter(Application.status.in_(SENT))]
    return sum(1 for i in ids if any(settle(i).values()))
