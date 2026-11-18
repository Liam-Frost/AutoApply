"""The record of an application, as the applicant sees it and changes it.

One row per version (models.Draft): what the agent entered for each question of the form and where it has that from,
the files it gave, the questions that are open, its own summary. The applicant answers the open questions, corrects
an entry, writes a note about the whole, approves the record or sends it back. Each of these is on the record for the
agent's next run (agent/work.py: ``record_of``, ``answers_of``), and that run is what acts on it. Nothing here opens a
browser or asks a model.

An answer belongs to this application. It becomes something the program knows about the applicant from then on only
when they say so ("also from now on"): then it is written to their profile as a rule.
"""

from __future__ import annotations

from typing import Any

from . import db, knowledge, lifecycle, materials, notify
from .models import SENT, Application, ApplicationEvent, Draft, DraftComment, MailEvent, now

NOT_TO_ANSWER = "(the applicant says this is not to be answered: leave it as the form has it)"


class Locked(ValueError):
    """The record cannot be changed now; the message says why, for the applicant."""


def locked(d: Draft) -> str:
    """Why this record cannot be changed ('' when it can).

    The applicant can change anything in it for as long as the application has not gone out - before approving it and
    after. Approving is their word that the answers are right; changing an answer afterwards is their word again, so
    the record stays approved and the next run sends what it says now. It is closed only when changing it could no
    longer do what the applicant means: it is an old version, the application was sent (the record is then what was
    sent), or the agent is working from it this moment."""
    if d.review_status not in ("pending", "approved"):
        return "这是草案的旧版本，不能再改。请打开最新的那一版。"
    status = d.application.status
    if status in SENT:
        return "这份申请已经发出去了，草案保留作记录，不能再改。"
    if status == "executing":
        return "Agent 正在按这份草案填写表单，等这一次结束后再改。"
    return ""


def _files_as_they_are(mats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The record's files, for showing: one whose document no longer has the file it was made with is marked."""
    gone = materials.overwritten([m.get("document_id") for m in mats or []])
    return [{**m, "overwritten": True} if m.get("document_id") in gone else m for m in mats or []]


def get(draft_id: int) -> dict[str, Any]:
    from .agent import work

    with db.session() as s:
        d = s.get(Draft, draft_id)
        if d is None:
            raise KeyError(draft_id)
        app, job = d.application, d.application.job
        return {
            "id": d.id, "version": d.version, "review_status": d.review_status, "created_at": d.created_at.isoformat(),
            "locked": locked(d),            # why nothing in it can be changed now; "" when the applicant can change it
            "application": {"id": app.id, "status": app.status, "last_event": app.last_event},
            "job": {"id": job.id, "company": job.company, "title": job.title, "deadline": job.deadline, "score": job.score,
                    "score_reason": job.score_reason, "apply_url": job.apply_url, "ats": job.ats, "source_id": job.source_id},
            "answers": d.answers, "unresolved": d.unresolved, "materials": _files_as_they_are(d.materials), "notes": d.notes,
            "policy": work.policy(job.company),      # how this application is sent, as the settings are now: auto | approve | hand_over
            "comments": [{"comment": c.comment, "result": c.result, "created_at": c.created_at.isoformat()} for c in d.comments],
        }


def _shown(value: Any) -> str:
    """An answer as words: a list joined, a tick box as what is done with it."""
    if isinstance(value, list):
        return "; ".join(map(str, value))
    if isinstance(value, bool):
        return "Yes (tick the box)" if value else "No (leave the box unticked)"
    return "" if value is None else str(value)


def _goes_on(d: Draft) -> bool:
    """Nothing is open in a record that waits, and applications are sent when nothing is open: the agent goes on
    without another word from the applicant."""
    from .agent import work

    return not d.unresolved and d.review_status == "pending" and work.policy(d.application.job.company) == "auto"


def _settled(s: Any, d: Draft, draft_id: int) -> tuple[bool, bool, int, str]:
    """After a change: (every question has its answer now, the agent goes on, the posting, its deadline)."""
    resolved_all = not d.unresolved and d.application.status == "needs_input"
    if resolved_all:
        lifecycle.move(d.application, "draft_ready", source="draft")
    return resolved_all, resolved_all and _goes_on(d), d.application.job_id, d.application.job.deadline


def _again(job_id: int, priority: int) -> int:
    """Queue the application's task because its record has changed. A run that is in progress has read the record as
    it was and cannot be told anything any more: this is a task of its own after it (the request says when the record
    changed, so that the queue does not take it for the request that run is carrying out)."""
    from . import tasks

    return tasks.enqueue("apply", ref=f"job:{job_id}", payload={"job_id": job_id, "record_changed": now().isoformat()}, priority=priority)


def _after(draft_id: int, resolved_all: bool, goes_on: bool, job_id: int, deadline: str) -> None:
    if resolved_all:  # outside the session: SQLite allows one writer at a time
        notify.close_todos("answer", f"draft:{draft_id}")
    if goes_on:
        from . import tasks

        _again(job_id, tasks.deadline_priority(deadline))


def edit_answer(draft_id: int, qid: str, value: Any, *, save_rule: str = "", remember: bool = False) -> None:
    """The applicant answers a question or corrects an entry. Theirs from then on: the agent enters it as it stands.
    ``remember`` / ``save_rule``: also from now on - written to the profile as a rule."""
    with db.session() as s:
        d = s.get(Draft, draft_id)
        why = locked(d)
        if why:
            raise Locked(why)
        label = next((a.get("label", "") for a in d.answers if a["id"] == qid), "")
        if d.review_status == "approved":      # after the approval: kept where the applicant's other words on this record are
            before = next((a.get("value") for a in d.answers if a["id"] == qid), None)
            s.add(DraftComment(draft_id=draft_id, comment=f"批准之后修改了“{label.strip()[:120]}”", result=f"{_shown(before)} → {_shown(value)}"))
        d.answers = [{**a, "value": value, "basis": "edited by user", "confidence": "high", "source": "profile", "dropped": False} if a["id"] == qid else a for a in d.answers]
        d.unresolved = [u for u in d.unresolved if u["id"] != qid or value in ("", None, [])]
        after = _settled(s, d, draft_id)
    _after(draft_id, *after)
    shown, note = _shown(value), save_rule.strip()
    if remember or note:
        # a rule is only usable later if it says what was asked; a bare "No" means nothing on the next form
        rule = f'Form question "{label.strip()[:200]}": answer "{shown[:300]}".' + (f" Note: {note}" if note and note.lower() != shown.lower() else "")
        knowledge.append_rule(rule, source="user", section="Standard answers")


def drop_question(draft_id: int, qid: str) -> None:
    """The applicant says an open question should not be answered at all (a field that is not theirs to fill; an
    entry the site made by itself). It stops being open, and the agent is told to leave it as the form has it. The
    form is the judge of whether that holds: if it will not go on without the field, the agent says so."""
    with db.session() as s:
        d = s.get(Draft, draft_id)
        why = locked(d)
        if why:
            raise Locked(why)
        row = next((a for a in d.answers if a["id"] == qid), None)
        if row is None or row.get("source") != "unresolved" or row.get("value") not in ("", None, []):
            raise Locked("只有还没有答案的问题可以去掉。")
        d.answers = [{**a, "dropped": True, "basis": "edited by user", "source": "profile", "required": False} if a["id"] == qid else a for a in d.answers]
        d.unresolved = [u for u in d.unresolved if u["id"] != qid]
        d.notes = [*(d.notes or []), f"你去掉了一个问题：“{str(row.get('label') or '')[:120]}”"]
        after = _settled(s, d, draft_id)
    _after(draft_id, *after)


def comment(draft_id: int, text: str) -> int:
    """What the applicant writes about the record as a whole ("say I can start in May", "use the other résumé"). It is
    kept with the record and the agent works the application again with it. Returns the task."""
    with db.session() as s:
        d = s.get(Draft, draft_id)
        if d is None:
            raise KeyError(draft_id)
        if d.review_status == "superseded":      # written on a version a later one has replaced: it is about the record, and that is its newest version
            newest = [x for x in d.application.drafts if x.review_status in ("pending", "approved")]
            d = newest[-1] if newest else d
        why = locked(d)
        if why:
            raise Locked(why)
        s.add(DraftComment(draft_id=d.id, comment=str(text)[:4000], result=""))
        lifecycle.move(d.application, "revising", source="user")
        job_id = d.application.job_id
    return _again(job_id, 10)


def use_resume(draft_id: int, which: str) -> None:
    """Which résumé this application is made with: "tailored" (the one written for this posting) or "base" (as uploaded)."""
    with db.session() as s:
        d = s.get(Draft, draft_id)
        why = locked(d)
        if why:
            raise Locked(why)
        sch = dict(d.schema or {})
        sch["extra"] = {**(sch.get("extra") or {}), "resume": "base" if which == "base" else "tailored"}
        d.schema = sch


def approve(draft_id: int) -> None:
    """The applicant's word that this record is what is to be sent - this version of it. The agent then sends it."""
    with db.session() as s:
        d = s.get(Draft, draft_id)
        if d.unresolved:
            raise ValueError("draft still has unanswered required questions")
        if d.review_status not in ("pending",):
            raise ValueError(f"draft is {d.review_status}")
        d.review_status, d.approved_at = "approved", now()
        app, job = d.application, d.application.job
        lifecycle.move(app, "approved", source="user")
        job_id, deadline = job.id, job.deadline
    from . import tasks

    _again(job_id, tasks.deadline_priority(deadline))


def reject(draft_id: int, *, withdraw: bool = False) -> None:
    with db.session() as s:
        d = s.get(Draft, draft_id)
        d.review_status = "rejected"
        app = d.application
        left = [x for x in app.drafts if x.id != d.id and x.review_status in ("pending", "approved")]
        if withdraw:
            lifecycle.move(app, "withdrawn", source="user")
        elif left:
            lifecycle.move(app, "needs_input" if left[-1].unresolved else "draft_ready", source="user")
        elif lifecycle.move(app, "returned", source="user"):
            # No record is waiting any more: the posting reads "not applied" again, and says what was done and what there is to do.
            app.last_event = "你退回了草案。想投这个岗位时，在岗位页重新开始。"


def undo(app_id: int) -> None:
    """An application for which nothing was recorded is taken away again, so that the posting reads "not applied". The
    record of its status changes goes with it (it only says "work began"), and mail that was linked to it is kept
    without the link."""
    with db.session() as s:
        a = s.get(Application, app_id)
        if a is None or a.drafts:
            return
        s.query(ApplicationEvent).filter_by(application_id=app_id).delete()
        s.query(MailEvent).filter_by(application_id=app_id).update({"application_id": None})
        s.delete(a)
