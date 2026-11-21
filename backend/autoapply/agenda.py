"""The calendar: everything with a time, in one shape, for the calendar page (and, later, the calendar it exports).

Nothing here is entered anew - it is the program's own data seen by its time: the deadlines of postings, what mails
asked of the applicant (an interview, an assessment, an offer to answer, information to send), contacts to get back to,
the applicant's own notes with a date, and - when asked for - what was put off, what went out, the replies that came
and the program's own work that waits for its time.

Every item: {id, kind, title, start, all_day, about: {job_id, application_id, todo_id, contact_id}, link, ...}. Times
are the applicant's local wall clock ("2026-11-25T23:59"): a deadline as the source wrote it, an interview as the mail
said it; moments the program recorded (in UTC) are turned into local time.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import db
from .models import SENT, Application, Contact, Job, MailEvent, Task, Todo

KINDS = ("deadline", "interview", "assessment", "offer", "info_request", "contact", "own", "snoozed", "sent", "reply", "task")
SHOWN = ("deadline", "interview", "assessment", "offer", "info_request", "contact", "own")       # (the rest: when asked for)
STATES = ("unapplied", "in_progress", "sent", "progressed")
PROGRESSED = ("assessment", "interview", "offer")
NOTE = "note"          # the applicant's own dated item: a to-do card of this kind


def _local(dt: datetime | None) -> datetime | None:
    """A moment the program recorded (UTC, without a zone) as local wall clock time."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="minutes")


def _deadline(text: str) -> tuple[datetime | None, bool]:
    """A posting's deadline as written ("2026-11-25 23:59" / "2026-11-25"): the moment, and whether it is a whole day."""
    text = (text or "").strip()
    for fmt, whole in (("%Y-%m-%d %H:%M", False), ("%Y-%m-%dT%H:%M", False), ("%Y-%m-%d", True)):
        try:
            return datetime.strptime(text[: len("2026-11-25 23:59") if not whole else 10], fmt), whole
        except ValueError:
            continue
    return None, False


def state_of(a: Application | None) -> str:
    """Where the application of an item stands, in the words of the filter."""
    if a is None:
        return "unapplied"
    if a.status in PROGRESSED:
        return "progressed"
    if a.status in SENT or a.status == "submit_unknown":
        return "sent"
    return "in_progress"


def items(start: date, end: date, *, kinds: tuple[str, ...] = SHOWN, states: tuple[str, ...] = (), company: str = "", priority: bool = False,
          min_score: float = 0, all_deadlines: bool = False) -> list[dict[str, Any]]:
    """What falls between ``start`` (inclusive) and ``end`` (exclusive), local days."""
    from . import employers

    lo, hi = datetime.combine(start, datetime.min.time()), datetime.combine(end, datetime.min.time())
    within = lambda d: d is not None and lo <= d < hi      # noqa: E731
    company = company.strip().lower()
    prio = employers.priority_names() if priority else set()
    out: list[dict[str, Any]] = []

    def keep(job: Job | None, app: Application | None) -> bool:
        if states and state_of(app) not in states:
            return False
        if job is None:
            return not company and not priority
        if company and company not in (job.company or "").lower():
            return False
        if priority and not employers.is_priority(job.company, job.source, prio):
            return False
        return True

    def add(id_: str, kind: str, title: str, at: datetime, whole: bool, *, job: Job | None = None, app: Application | None = None, todo: Todo | None = None,
            link: str = "", note: str = "", contact_id: int | None = None, done: bool = False) -> None:
        links = list(((todo.payload or {}).get("links") or []) if todo is not None else [])
        out.append({"id": id_, "kind": kind, "title": title, "start": _iso(at), "all_day": whole, "link": link, "links": links, "note": note[:300], "done": done,
                    "company": job.company if job else "", "subject": f"{job.company} · {job.title}" if job else "",
                    "state": state_of(app) if (job or app) else "", "score": job.score if job else None,
                    "about": {"job_id": job.id if job else None, "application_id": app.id if app else None, "todo_id": todo.id if todo else None, "contact_id": contact_id}})

    with db.session() as s:
        if "deadline" in kinds:
            for j in s.query(Job).filter(Job.duplicate_of.is_(None), Job.deadline != ""):
                at, whole = _deadline(j.deadline)
                if not within(at):
                    continue
                a = j.application
                if not all_deadlines and (j.status == "skipped" or j.archived_at is not None or not j.online or state_of(a) not in ("unapplied", "in_progress")
                                          or (a is not None and a.status == "withdrawn")):
                    continue
                if (j.score or 0) < min_score or not keep(j, a):
                    continue
                add(f"job:{j.id}", "deadline", j.title, at, whole, job=j, app=a, link=j.apply_url or "")
        asked = {k for k in ("interview", "assessment", "offer", "info_request") if k in kinds}
        for t in s.query(Todo).filter(Todo.due_at.isnot(None)):
            p = dict(t.payload or {})
            kind = NOTE if t.kind == NOTE else str(p.get("category") or "") if t.kind == "followup" else ""
            if kind == NOTE and "own" not in kinds or kind != NOTE and kind not in asked and not (t.kind == "followup" and p.get("contact_id") and "contact" in kinds):
                continue
            if t.status == "dismissed" or not within(t.due_at):
                continue
            a = s.get(Application, int(p["application_id"])) if p.get("application_id") else None
            j = a.job if a is not None else None
            if not keep(j, a):
                continue
            k = "own" if kind == NOTE else "contact" if p.get("contact_id") else kind
            add(f"todo:{t.id}", k, t.title, t.due_at, bool(p.get("date_only") or p.get("all_day")), job=j, app=a, todo=t, link=str(p.get("link") or ""),
                note=t.body or "", contact_id=p.get("contact_id"), done=t.status == "done")
        if "contact" in kinds and not company and not states and not priority:
            carded = {t.ref for t in s.query(Todo).filter(Todo.kind == "followup", Todo.ref.like("contact:%"))}
            for c in s.query(Contact).filter(Contact.follow_up != ""):
                try:
                    at = datetime.fromisoformat(c.follow_up)
                except ValueError:
                    continue
                if within(at) and f"contact:{c.id}:{c.follow_up}" not in carded:
                    out.append({"id": f"contact:{c.id}", "kind": "contact", "title": c.name, "start": _iso(at), "all_day": True, "link": "", "note": (c.note or "")[:300],
                                "done": False, "company": c.company, "subject": c.company, "state": "", "score": None,
                                "about": {"job_id": None, "application_id": None, "todo_id": None, "contact_id": c.id}})
        if "snoozed" in kinds:
            for t in s.query(Todo).filter(Todo.status == "open", Todo.snoozed_until.isnot(None)):
                if within(t.snoozed_until):
                    a = s.get(Application, int((t.payload or {})["application_id"])) if (t.payload or {}).get("application_id") else None
                    if keep(a.job if a else None, a):
                        add(f"snoozed:{t.id}", "snoozed", t.title, t.snoozed_until, False, job=a.job if a else None, app=a, todo=t)
        if "sent" in kinds:
            for a in s.query(Application).filter(Application.submitted_at.isnot(None)):
                at = _local(a.submitted_at)
                if within(at) and keep(a.job, a):
                    add(f"sent:{a.id}", "sent", a.job.title, at, False, job=a.job, app=a)
        if "reply" in kinds:
            for m in s.query(MailEvent).filter(MailEvent.received_at.isnot(None), MailEvent.category != "other"):
                at = _local(m.received_at)
                a = s.get(Application, m.application_id) if m.application_id else None
                if within(at) and keep(a.job if a else None, a):
                    add(f"mail:{m.id}", "reply", m.subject or m.category, at, False, job=a.job if a else None, app=a, note=m.summary or "")
        if "task" in kinds and not company and not states and not priority:
            from . import humanize, metering

            for t in s.query(Task).filter(Task.status == "queued", Task.due_at.isnot(None)):
                at = _local(t.due_at)
                if within(at):
                    out.append({"id": f"task:{t.id}", "kind": "task", "title": metering.workflow_label(t.kind), "start": _iso(at), "all_day": False, "link": "",
                                "note": humanize.subject(t.ref), "done": False, "company": "", "subject": humanize.subject(t.ref), "state": "", "score": None,
                                "about": {"job_id": None, "application_id": None, "todo_id": None, "contact_id": None}})
    out.sort(key=lambda x: (x["start"][:10], not x["all_day"], x["start"], x["kind"], x["title"]))
    return out


def add_own(title: str, when: datetime, *, all_day: bool, link: str = "", application_id: int | None = None, note: str = "") -> int:
    """The applicant's own dated item ("call back Acme's recruiter"): a card with its date, said the day before and on
    the day like any other."""
    payload: dict[str, Any] = {"all_day": all_day, "date_only": all_day, "link": link.strip()[:500], "date_by": "user"}
    if application_id:
        payload["application_id"] = int(application_id)
    with db.session() as s:
        if application_id and s.get(Application, int(application_id)) is None:
            raise KeyError(application_id)
        t = Todo(kind=NOTE, title=title.strip()[:200], body=note.strip()[:2000], payload=payload, due_at=when)
        s.add(t)
        s.flush()
        t.ref = f"note:{t.id}"
        tid = t.id
    from . import alarms

    alarms.give_defaults(f"todo:{tid}", "own", when, all_day)
    return tid


def set_link(todo_id: int, link: str) -> None:
    """Where an item leads: the meeting of an interview, the start of an assessment, the page to answer an offer on."""
    link = link.strip()[:500]
    if link and not link.lower().startswith(("http://", "https://")):
        raise ValueError("只能是 http(s) 地址")
    with db.session() as s:
        t = s.get(Todo, todo_id)
        if t is None:
            raise KeyError(todo_id)
        t.payload = {**(t.payload or {}), "link": link, "link_by": "user"}


def month_range(day: date) -> tuple[date, date]:
    first = day.replace(day=1)
    return first, (first + timedelta(days=32)).replace(day=1)
