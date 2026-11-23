"""One application, whole.

What the program knows about an application was spread over the pages that each know one side of it: the posting in
the jobs list, the answers in the draft, a card when something waits, the mails in the activity record, the runs in
another list. "Where does this application stand, what shows it, what was sent, what came back?" took a tour. Here it
is put together - the listing for "my applications", one application with everything about it, and the applicant's own
corrections to the record (a step that happened elsewhere, a date, which application a mail is about).

Nothing here decides where an application stands: that is lifecycle.move's, and a correction goes through it like
any other change, marked as the applicant's.
"""
from __future__ import annotations

from .say import say as T

import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db, humanize, i18n, lifecycle, messages
from .discover import company_name
from .models import SENT, UNKNOWN, Application, ApplicationEvent, Draft, Job, MailEvent, Run, Task, Todo, now
from .say import Msg

# where the applicant may put an application by hand: a step that happened outside the program's sight
BY_HAND = (*SENT, "withdrawn")
# who said a change, in the applicant's words
SOURCE = {"run": "Agent", "mail": T("server.applications.email"), "site": T("server.applications.theEmployersSite"), "user": T("server.applications.you"), "draft": T("server.applications.theRecord"), "auto": T("server.applications.approvedAutomatically"), "resume": T("server.applications.aResumedTask"), "recover": T("server.applications.afterTheProgramRestarted"), "": ""}
# what comes next, by where it stands: (the task, as a short phrase for whoever's move it is - or what is waited for;
# the things that can be done about it - the page turns them into buttons)
NEXT: dict[str, tuple[str, tuple[str, ...]]] = {
    "recon": (T("server.applications.theAgentIsWorking"), ()),
    "revising": (T("server.applications.theAgentIsWorking2"), ()),
    "needs_input": (T("server.applications.questionsWaitingForYour"), ("open_draft",)),
    "draft_ready": (T("server.applications.theRecordOfThe"), ("open_draft",)),
    "approved": (T("server.applications.approvedWaitingForThe"), ()),
    "executing": (T("server.applications.theAgentIsChecking"), ()),
    "drifted": (T("server.applications.next.retry"), ("rerun",)),
    "needs_human": (T("server.applications.next.handle"), ("open_todos",)),
    "failed": (T("server.applications.next.retry"), ("rerun", "open_draft")),
    "ready_to_submit": (T("server.applications.next.submit"), ("rerun", "mark_submitted")),
    UNKNOWN: (T("server.applications.next.confirm"), ("check_mail", "mark_submitted", "rerun_not_submitted")),
    "submitted": (T("server.applications.submittedWaitingForThe"), ("check_mail",)),
    "confirmed": (T("server.applications.confirmedByTheEmployer"), ()),
    "assessment": (T("server.applications.aTestOrAssessment"), ()),
    "interview": (T("server.applications.anInterviewPrepareAs"), ()),
    "offer": (T("server.applications.offerReceived"), ()),
    "rejected": (T("server.applications.thisApplicationWasNot"), ()),
    "withdrawn": (T("server.applications.youDecidedNotTo"), ()),
}
# why that is what comes next, where the phrase alone does not say it: a sentence for the application's own page (a row
# of the list has no room for it)
WHY = {"drifted": T("server.applications.applicationFormHasChanged"), "needs_human": T("server.applications.itNeedsYouBefore"), "failed": T("server.applications.theLastAttemptDid"),
       "ready_to_submit": T("server.applications.theFormIsFilled"), UNKNOWN: T("server.applications.submitWasPressedAnd")}


# Where an application stands, as the applications page says it: status -> (label, tone, group, whose move it is).
# Groups: me (waits for the applicant) | agent (the agent's to do) | sent | progress | ended; "archived" is the
# applicant's own putting away, whatever the status.
STAGE: dict[str, tuple[Any, str, str, str]] = {
    "needs_input": (T("server.applications.stage.needsInput"), "warn", "me", "me"),
    "draft_ready": (T("server.applications.stage.draftReady"), "warn", "me", "me"),
    "needs_human": (T("server.applications.stage.needsHuman"), "warn", "me", "me"),
    "ready_to_submit": (T("server.applications.stage.readyToSubmit"), "warn", "me", "me"),
    UNKNOWN: (T("server.applications.stage.unknown"), "warn", "me", "me"),
    "drifted": (T("server.applications.stage.drifted"), "warn", "me", "me"),
    "failed": (T("server.applications.stage.failed"), "bad", "me", "me"),
    "recon": (T("server.applications.stage.preparing"), "info", "agent", "agent"),
    "revising": (T("server.applications.stage.revising"), "info", "agent", "agent"),
    "approved": (T("server.applications.stage.approved"), "info", "agent", "agent"),
    "executing": (T("server.applications.stage.submitting"), "info", "agent", "agent"),
    "submitted": (T("server.applications.stage.sent"), "info", "sent", "them"),
    "confirmed": (T("server.applications.stage.confirmed"), "ok", "sent", "them"),
    "assessment": (T("server.applications.stage.assessment"), "ok", "progress", "me"),
    "interview": (T("server.applications.stage.interview"), "ok", "progress", "me"),
    "offer": (T("server.applications.stage.offer"), "ok", "progress", "me"),
    "rejected": (T("server.applications.stage.rejected"), "bad", "ended", ""),
    "withdrawn": (T("server.applications.stage.withdrawn"), "", "ended", ""),
    "returned": (T("server.applications.stage.returned"), "", "ended", ""),
}
# the one thing to press on a row that waits for the applicant (the page names it): answer | approve | handle | rerun | budget | check_mail
ACT = {"needs_input": "answer", "draft_ready": "approve", "needs_human": "handle", "ready_to_submit": "handle", UNKNOWN: "check_mail", "drifted": "rerun", "failed": "rerun"}
OUTCOMES = ("confirmed", "assessment", "interview", "offer", "rejected")      # what the applicant may record as having come back
ENDED = ("withdrawn", "returned", "rejected")


def stage_of(a: Application, j: Job, *, waiting: bool = False, budget: bool = False, work: str = "") -> dict[str, Any]:
    """Where ``a`` stands, in the page's terms: its stage and label, the group it is listed under, whose move it is, and
    what to press. ``waiting``: a card asks the applicant for something about it (a sign-in, a confirmation); ``budget``:
    that card is about its budget being used up; ``work``: a run is on it ("running") or waits in the queue ("queued")."""
    label, tone, group, who = STAGE.get(a.status, (humanize.APP_STATUS.get(a.status, a.status), "", "agent", "agent"))
    key, act = a.status, ACT.get(a.status, "")
    sent = a.status in SENT or a.status == UNKNOWN
    if not sent and a.status not in ENDED and (not j.online or j.status == "offline"):
        key, label, tone, group, who, act = "offline", T("server.applications.stage.offline"), "", "ended", "", ""
    elif group == "agent" and waiting:
        key, label, tone, group, who, act = "waiting", T("server.applications.stage.needsHuman"), "warn", "me", "me", "handle"
    elif group == "agent" and work:
        label = T("server.applications.stage.working") if work == "running" else T("server.applications.stage.queued")
    if a.status == "failed" and budget:
        label, act = T("server.applications.stage.budgetUsed"), "budget"
    return {"stage": key, "stage_label": label, "tone": tone, "group": "archived" if a.archived_at else group, "who": who, "act": act}


def next_of(status: str, st: dict[str, Any]) -> tuple[Any, Any]:
    """What comes next for an application that stands at ``st`` (stage_of), and why - in step with the stage the page
    shows: an application whose posting is gone has no next step, one that waits on a card is the applicant's to
    handle whatever the agent was doing, one out of budget needs a budget before anything else."""
    if st["stage"] == "offline":
        return "", ""
    if st["stage"] == "waiting":
        return NEXT["needs_human"][0], WHY["needs_human"]
    if st["act"] == "budget":
        return T("server.applications.next.budget"), ""
    return NEXT.get(status, ("", ()))[0], WHY.get(status, "")


# the latest event of an application when it is a mail (mail._record): "interview: <summary>", "offer (changed): <summary>"
_MAIL_SAID = re.compile(r"^(confirmation|rejection|interview|assessment|offer|info_request)(?: \((\w+)\))?: (.*)$", re.S)


def explained(text: str | None) -> dict[str, Any]:
    """humanize.explain for an application's latest event - with a mail said by its heading in the page's language
    (the heading was put into the sentence as Chinese text, and a mail about a change or a cancellation was not
    recognised as a mail at all)."""
    m = _MAIL_SAID.match((text or "").strip())
    if m:
        return {"message": T("server.applications.mailSaid", what=messages.mail_label(m.group(1), m.group(2) or "new")[1], summary=m.group(3)), "detail": ""}
    return humanize.explain(text)


def latest(text: str | None) -> Any:
    """The latest event in a few words, for a row of the list: a mail by its heading alone ("Interview invitation" -
    what it says is on the application's page), one of the program's own messages whole, anything else (the agent's
    words, the applicant's note) by its first sentence. The whole of it stays in ``last_event``."""
    m = _MAIL_SAID.match((text or "").strip())
    if m:
        return messages.mail_label(m.group(1), m.group(2) or "new")[1]
    said = humanize.explain(text)["message"]
    if isinstance(said, Msg):
        return said
    # (a full stop ends a sentence only before a new one - a capital, or a script without capitals: "Labs Inc. is
    # not ..." is not two)
    return re.split(r"(?<=[。！？!?])|(?<=\.)\s+(?=[^\Wa-z0-9_])|\n", str(said).strip(), maxsplit=1)[0].strip()


def job_group(j: Job, a: Application | None) -> str:
    """The group of a posting on the postings page: todo (open, nothing begun) | started (an application was begun: the
    posting leads to it) | skip (not applying: the applicant's word, or a rule) | closed (taken down, or past its
    deadline) | archived (put away)."""
    from .stages import _past

    if j.archived_at is not None:
        return "archived"
    if a is not None and a.status not in ("withdrawn", "returned"):
        return "started"
    if j.status == "skipped" or (a is not None and a.status == "withdrawn"):
        return "skip"
    if not j.online or j.status == "offline" or _past(j.deadline or ""):
        return "closed"
    return "todo"


def context(s: Any, *, dates: bool = True) -> dict[str, Any]:
    """What the rows of the listing need besides the applications themselves, read once for all of them: the cards that
    wait for the applicant (by application), runs on a posting (by posting), the latest draft that counts (by
    application), and - with ``dates`` - the next dated thing on the calendar (by application)."""
    app_of_job = {jid: aid for aid, jid in s.query(Application.id, Application.job_id)}
    drafts: dict[int, tuple[int, str]] = {}
    app_of_draft: dict[int, int] = {}
    for did, aid, review in s.query(Draft.id, Draft.application_id, Draft.review_status).order_by(Draft.version):
        app_of_draft[did] = aid
        if review in ("pending", "approved") or drafts.get(aid, ("", ""))[1] not in ("pending", "approved"):
            drafts[aid] = (did, review)      # (the one that counts; else the latest)
    cards: dict[int, set[str]] = {}
    for t in s.query(Todo).filter(Todo.status == "open", Todo.kind.in_(lifecycle.CARDS)):
        p = t.payload or {}
        kind, _, rest = (t.ref or "").partition(":")
        num = int(rest.split(":")[0]) if rest.split(":")[0].isdigit() else 0
        aid = p.get("application_id") or (num if kind == "application" else app_of_draft.get(num) if kind == "draft" else app_of_job.get(num) if kind == "job" else None) \
            or app_of_draft.get(int(p.get("draft_id") or 0))
        if aid:
            cards.setdefault(int(aid), set()).add("budget" if p.get("budget") else t.kind)
    work: dict[int, str] = {}
    for ref, status in s.query(Task.ref, Task.status).filter(Task.kind == "apply", Task.status.in_(("running", "queued"))):
        if (ref or "").startswith("job:") and ref[4:].isdigit():
            jid = int(ref[4:])
            work[jid] = "running" if status == "running" or work.get(jid) == "running" else "queued"
    nxt: dict[int, dict[str, Any]] = {}
    if dates:
        from datetime import timedelta

        from . import agenda
        from . import clock as _clock

        # (the calendar's times are the local wall clock, written without a zone: compared as they are written)
        clock = _clock.now().isoformat(timespec="minutes")
        order: dict[int, tuple[bool, str]] = {}
        try:
            for it in agenda.items(_clock.today(), _clock.today() + timedelta(days=120), kinds=("interview", "assessment", "offer", "info_request", "own")):
                aid = (it.get("about") or {}).get("application_id")
                if it.get("done"):      # (what was asked and has been done is not what comes next)
                    continue
                # what is still to come before what was earlier today; among each, the earliest
                rank = (not it.get("all_day") and str(it.get("start") or "") < clock, str(it.get("start") or ""))
                if aid and (aid not in order or rank < order[aid]):
                    order[aid] = rank
                    nxt[aid] = {"kind": it.get("kind"), "title": it.get("title"), "start": it.get("start"), "all_day": bool(it.get("all_day"))}
        except Exception:  # noqa: BLE001 - a date the calendar cannot read leaves the column empty, not the page
            nxt = {}
    return {"cards": cards, "work": work, "drafts": drafts, "next": nxt}


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def _utc(d: datetime | None) -> datetime:
    if d is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def _row(a: Application, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    j = a.job
    ctx = ctx or {}
    cards = ctx.get("cards", {}).get(a.id, set())
    st = stage_of(a, j, waiting=bool(cards), budget="budget" in cards, work=ctx.get("work", {}).get(j.id, ""))
    draft = ctx.get("drafts", {}).get(a.id)
    todo, why = next_of(a.status, st)
    # (the company as it is shown everywhere else: without the fields of the posting some sources glue to it)
    return {"id": a.id, "job_id": j.id, "company": company_name(j.company), "title": j.title, "location": j.location, "apply_url": j.apply_url,
            "status": a.status, "status_label": humanize.APP_STATUS.get(a.status, a.status), **st,
            "submitted_at": _iso(a.submitted_at), "created_at": _iso(a.created_at), "updated_at": _iso(a.updated_at),
            "last_event": explained(a.last_event)["message"] if a.last_event else "", "latest": latest(a.last_event) if a.last_event else "",
            "sent": a.status in SENT, "unknown": a.status == UNKNOWN,
            "next": todo, "next_why": why, "deadline": "" if a.status in SENT else (j.deadline or ""), "next_date": ctx.get("next", {}).get(a.id),
            "archived": a.archived_at is not None, "note": a.note or "", "score": j.score, "ats_label": humanize.ats_name(j.ats) or "",
            "draft_id": draft[0] if draft else None, "draft_review": draft[1] if draft else ""}


def listing(*, dates: bool = True) -> list[dict[str, Any]]:
    """Every application, from the moment it was begun to its outcome - the latest change first. Each row says where it
    stands, whose move it is, and what to press (stage_of)."""
    with db.session() as s:
        ctx = context(s, dates=dates)
        rows = [_row(a, ctx) for a in s.query(Application).join(Job)]
    return sorted(rows, key=lambda r: r["updated_at"] or r["created_at"] or "", reverse=True)


def need_me() -> int:
    """How many applications wait for the applicant (the number on "Applications" in the menu)."""
    return sum(1 for r in listing(dates=False) if r["group"] == "me")


def review(ids: list[int]) -> list[dict[str, Any]]:
    """Before several records are approved at once: for each, what the applicant has to have seen - the answers the
    agent was not sure of, what changed since the version before, the questions still open."""
    from . import actions

    out = []
    with db.session() as s:
        for i in ids:
            a = s.get(Application, int(i))
            if a is None:
                continue
            d = next((x for x in reversed(a.drafts) if x.review_status == "pending"), None)
            out.append({"id": a.id, "company": company_name(a.job.company), "title": a.job.title, "draft_id": d.id if d else None,
                        "unresolved": len(d.unresolved) if d else 0, "unsure": actions._unsure(d)[:30] if d else [],
                        "changed": actions._changed(s, d)[:30] if d else [], "can": d is not None and not d.unresolved})
    return out


def bulk(action: str, ids: list[int]) -> dict[str, Any]:
    """One action on several applications: approve | rerun | withdraw | archive | unarchive. What does not apply to one
    (a record with open questions, an application that went out) is counted as skipped, with the reason."""
    from . import drafts as _drafts, tasks

    if action not in ("approve", "rerun", "withdraw", "archive", "unarchive"):
        raise NotAllowed("unsupported action")
    done, skipped, errors = 0, 0, {}
    to_approve: list[tuple[int, int]] = []
    to_run: list[tuple[int, str]] = []
    with db.session() as s:
        for i in ids[:500]:
            a = s.get(Application, int(i))
            if a is None:
                continue
            if action in ("archive", "unarchive"):
                a.archived_at = now() if action == "archive" else None
                done += 1
            elif action == "withdraw":
                if lifecycle.not_applying(a.job):
                    done += 1
                else:
                    skipped += 1
                    errors[str(a.id)] = lifecycle.closed_to_work(a)
            elif action == "rerun":
                if a.status in SENT or a.status in (UNKNOWN, "withdrawn"):
                    skipped += 1
                    errors[str(a.id)] = lifecycle.closed_to_work(a)
                else:
                    to_run.append((a.job_id, a.job.deadline or ""))
            else:
                d = next((x for x in reversed(a.drafts) if x.review_status == "pending"), None)
                if d is None or d.unresolved:
                    skipped += 1
                    errors[str(a.id)] = T("server.applications.nothingToApprove") if d is None else T("server.applications.questionsOpen", n=len(d.unresolved))
                else:
                    to_approve.append((a.id, d.id))
    for aid, did in to_approve:
        try:
            _drafts.approve(did)
            done += 1
        except ValueError as e:
            skipped += 1
            errors[str(aid)] = str(e)
    for job_id, deadline in to_run:      # (after the session: one writer at a time)
        tasks.enqueue("apply", ref=f"job:{job_id}", payload={"job_id": job_id}, priority=tasks.deadline_priority(deadline))
        done += 1
    return {"done": done, "skipped": skipped, "errors": errors}


def withdraw(application_id: int) -> None:
    """Not applying after all: the application is withdrawn and its posting marked "not applying"."""
    with db.session() as s:
        a = s.get(Application, application_id)
        if a is None:
            raise KeyError(application_id)
        if not lifecycle.not_applying(a.job):
            raise NotAllowed(lifecycle.closed_to_work(a))


def set_note(application_id: int, note: str) -> None:
    with db.session() as s:
        a = s.get(Application, application_id)
        if a is None:
            raise KeyError(application_id)
        a.note = (note or "").strip()[:4000]


def outcome(application_id: int, *, status: str, day: str = "", at: str = "", note: str = "") -> dict[str, Any]:
    """What came back, in the applicant's words where the program could not see it (a call, a mail it did not read): a
    rejection, an assessment or interview arranged, an offer - with its date and a line. An assessment or an interview
    with a date goes on the calendar too, as the applicant's own item about this application."""
    from datetime import datetime as _dt

    from . import agenda

    if status not in OUTCOMES:
        raise NotAllowed(T("server.applications.byHandItCan"))
    when = None
    if day:
        try:
            when = _dt.fromisoformat(f"{day[:10]}T{(at or '09:00')[:5]}")
        except ValueError as e:
            raise NotAllowed(T("server.api.main.theDateIsNot")) from e
    said = " · ".join(x for x in ((f"{day[:10]} {at[:5]}".strip() if day else ""), (note or "").strip()[:240]) if x)
    out = correct(application_id, status=status, note=said)
    if when is not None and status in ("assessment", "interview"):
        label = STAGE[status][0]
        agenda.add_own(T("server.applications.onTheCalendar", what=label, company=out.get("company", "")), when, all_day=not at,
                       application_id=application_id, note=(note or "").strip())
    return detail(application_id) or out


def picture(evidence: dict[str, Any] | None) -> Path | None:
    """The picture kept with an application's evidence, when there is one and it is in the program's own data: named
    by where it is in the data folder (or, in records of earlier versions, by its whole path)."""
    from . import config

    shot = str((evidence or {}).get("screenshot") or "")
    if not shot:
        return None
    p = Path(shot)
    p = (p if p.is_absolute() else config.DATA / p).resolve()
    return p if p.is_file() and config.DATA.resolve() in p.parents else None


def detail(application_id: int) -> dict[str, Any] | None:
    with db.session() as s:
        a = s.get(Application, application_id)
        if a is None:
            return None
        j = a.job
        out = _row(a, context(s))
        out["actions"] = list(NEXT.get(a.status, ("", ()))[1])
        out["explained"] = explained(a.last_event)
        out["detail"], out["auto_approved"], out["channel"] = a.detail, bool(a.auto_approved), a.channel
        out["job_id"] = j.id
        out["job"] = {"id": j.id, "company": j.company, "title": j.title, "location": j.location, "deadline": j.deadline, "apply_url": j.apply_url, "score": j.score,
                      "online": bool(j.online), "posted": j.posted, "summary": j.summary, "brief": j.brief, "source": j.source, "source_id": j.source_id,
                      "ats_label": humanize.ats_name(j.ats), "term": j.term, "months": j.months, "salary": j.salary, "direction": j.direction,
                      "score_reason": j.score_reason, "jd_text": j.jd_text, "status": j.status}
        ev = dict(a.evidence or {})
        out["evidence"] = {"text": str(ev.get("text") or ""), "url": str(ev.get("url") or ""), "read_by": str(ev.get("read_by") or ""),
                           "already_applied": bool(ev.get("already_applied")), "has_screenshot": picture(ev) is not None,
                           "mail_ids": list(ev.get("mail_ids") or ([ev["mail_id"]] if ev.get("mail_id") else [])), "by_user": bool(ev.get("user"))}
        from .agent import work as _work

        # what the agent wrote down while it worked this application, what it has used, and whether a run is on it now
        out["journal"], out["spent"], out["running_task"], out["run_expected"] = _work.journal(a.id), _work.spent(a.id), _work.being_worked(j.id), _work.expected(j.id)
        drafts = list(a.drafts)
        out["drafts"] = [{"id": d.id, "version": d.version, "review_status": d.review_status, "review_label": humanize.REVIEW.get(d.review_status, d.review_status),
                          "created_at": _iso(d.created_at)} for d in drafts]
        # what was sent: the materials of the draft the form was filled from (the approved one; else the latest)
        used = next((d for d in reversed(drafts) if d.review_status in ("approved", "closed")), drafts[-1] if drafts else None)
        out["materials"] = [{"slot": m.get("slot_label") or m.get("slot") or "", "name": m.get("name") or "", "kind": m.get("kind") or "", "document_id": m.get("document_id"),
                             "exists": bool(m.get("path") and Path(str(m["path"])).exists())} for m in ((used.materials if used is not None else None) or [])]
        out["materials_from_draft"] = used.id if used is not None else None
        mails = s.query(MailEvent).filter_by(application_id=a.id).order_by(MailEvent.received_at.desc().nullslast(), MailEvent.id.desc()).all()
        out["mails"] = [{"message_id": m.message_id, "received_at": _iso(m.received_at), "sender": m.sender, "subject": m.subject, "category": m.category,
                         "event": m.event or "new", "label": messages.mail_label(m.category, m.event or "new")[1], "summary": m.summary,
                         "linked_by": m.linked_by or "", "is_evidence": m.message_id in out["evidence"]["mail_ids"]} for m in mails]
        # the story of it: every change of where it stands, every time the form was worked on, every mail
        line: list[dict[str, Any]] = []
        for e in s.query(ApplicationEvent).filter_by(application_id=a.id):
            line.append({"at": _iso(e.at), "kind": "status", "old": humanize.APP_STATUS.get(e.old, e.old), "new": humanize.APP_STATUS.get(e.new, e.new),
                         "by": SOURCE.get(e.source or "", e.source or ""), "note": getattr(e, "note", "") or ""})
        for r in s.query(Run).filter(Run.ref == f"application:{a.id}", Run.kind.in_(("execute", "scout"))):      # (runs of earlier versions)
            line.append({"at": _iso(r.created_at), "kind": "run", "what": T("server.applications.fillApplicationForms") if r.kind == "execute" else T("server.applications.readingTheLaterSteps"), "ok": bool(r.ok), "run_id": r.id})
        from .agent import work

        for e in work.journal(a.id):      # each run of the agent on it: how it ended, in the agent's own words
            if e["kind"] in ("report", "ended"):
                line.append({"at": e["at"], "kind": "run", "what": T("server.applications.aRunOfThe"), "ok": e["kind"] == "report", "said": str(e.get("text") or "")[:300]})
        for m in mails:
            line.append({"at": _iso(m.received_at), "kind": "mail", "label": messages.mail_label(m.category, m.event or "new")[1], "subject": m.subject, "message_id": m.message_id})
        out["timeline"] = sorted(line, key=lambda x: x["at"] or "", reverse=True)
        refs = {f"application:{a.id}", f"job:{j.id}", *(f"draft:{d.id}" for d in drafts)}
        draft_ids = {d.id for d in drafts}
        out["cards"] = [{"id": t.id, "kind": t.kind, "title": t.title, "body": t.body, "created_at": _iso(t.created_at)} for t in s.query(Todo).filter_by(status="open")
                        if t.ref in refs or (t.payload or {}).get("application_id") == a.id or (t.payload or {}).get("draft_id") in draft_ids]
        return out


class NotAllowed(ValueError):
    """What the applicant asked to record cannot be recorded (and why, in their words)."""


def correct(application_id: int, *, status: str = "", submitted_at: datetime | None = None, note: str = "") -> dict[str, Any]:
    """The applicant puts the record right: a step that happened where the program could not see it ("I had the
    interview", "they called: rejected", "I withdrew"), or the date it was sent. It is their word, kept as theirs - in
    the history with its source, and able to take the application back as well as forward."""
    note = (note or "").strip()[:300]
    with db.session() as s:
        a = s.get(Application, application_id)
        if a is None:
            raise KeyError(application_id)
        was = a.status
        if status and status != was:
            if status not in BY_HAND:
                raise NotAllowed(T("server.applications.byHandItCan"))
            lifecycle.move(a, status, source="user", back=True, note=note)
            label = humanize.APP_STATUS.get(status, status)
            a.last_event = T("server.applications.youRecordedItAs", p0=label) + (f"：{note}" if note else "")
            if status in SENT:
                lifecycle.add_evidence(a, {"user": {"status": status, "at": now().isoformat(), "note": note}})
        if submitted_at is not None:
            if a.status not in SENT:
                raise NotAllowed(T("server.applications.anApplicationThatHas"))
            old = a.submitted_at
            a.submitted_at = submitted_at
            if _utc(old) != _utc(submitted_at):
                s.add(ApplicationEvent(application_id=a.id, old=a.status, new=a.status, source="user",
                                       note=T("server.applications.dateSentChangedTo", p0=submitted_at.date().isoformat()) + (T("server.applications.was", p0=old.date().isoformat()) if old else "")))
        elif note and (not status or status == was):
            # a note with nothing else changed (the page sends no status when it is the one the application has)
            s.add(ApplicationEvent(application_id=a.id, old=was, new=was, source="user", note=note))
    return detail(application_id) or {}


def unlink_mail(application_id: int, message_id: str) -> bool:
    """This mail is not about this application (the applicant says). The mail goes back to "which application is this
    about?"; where the application stands is not guessed back - the applicant corrects that themselves if it was wrong."""
    with db.session() as s:
        m = s.query(MailEvent).filter_by(message_id=message_id, application_id=application_id).first()
        if m is None:
            return False
        m.application_id, m.linked_by = None, "user"
        back = (m.message_id, m.subject or "", m.category, m.event or "new", m.summary or "") if m.category != "other" else None
        a = s.get(Application, application_id)
        ev = dict(a.evidence or {})
        if message_id in (ev.get("mail_ids") or []) or ev.get("mail_id") == message_id:
            ids = [x for x in (ev.get("mail_ids") or []) if x != message_id]
            ev["mail_ids"] = ids
            ev["mail_id"] = ids[-1] if ids else ""
            a.evidence = ev
        s.add(ApplicationEvent(application_id=application_id, old=a.status, new=a.status, source="user", note=T("server.applications.theEMailIs", p0=(m.subject or '')[:80])))
    if back is not None:
        # It is about some application, only not this one: the card that asks which comes back. (A mail the program
        # matched by itself never had one, and a mail matched by hand had its card closed; the mailbox is not read
        # twice for the same mail - so the mail went nowhere, though the page said it would wait among the to-dos.)
        from . import mail

        mail.ask_which(*back, push=False)
    return True


def as_csv(ids: set[int] | None = None) -> str:
    """The applications as a table to keep or to open in a spreadsheet: what was applied for, when, where it stands
    (``ids``: only these)."""
    out = io.StringIO()
    wr = csv.writer(out, lineterminator="\n")
    wr.writerow([i18n.tr(h) for h in (T("server.applications.company"), T("server.applications.postings"), T("server.applications.location"), T("server.applications.status"), T("server.applications.dateSent"), T("server.applications.latest"), T("server.applications.postingLink"), T("server.applications.lastUpdated"))])
    for r in listing(dates=False):
        if ids is not None and r["id"] not in ids:
            continue
        wr.writerow([r["company"], r["title"], r["location"] or "", i18n.tr(r["status_label"]), (r["submitted_at"] or "")[:10], i18n.tr(r["last_event"] or r["next"]),
                     r["apply_url"] or "", (r["updated_at"] or "")[:16].replace("T", " ")])
    return "﻿" + out.getvalue()       # (the mark a spreadsheet needs to read the names of companies in any script)
