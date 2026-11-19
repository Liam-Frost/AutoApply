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

import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db, humanize, i18n, lifecycle, messages, stages
from .models import SENT, UNKNOWN, Application, ApplicationEvent, Draft, Job, MailEvent, Run, Todo, now

# where the applicant may put an application by hand: a step that happened outside the program's sight
BY_HAND = (*SENT, "withdrawn")
# who said a change, in the applicant's words
SOURCE = {"run": "Agent", "mail": "邮件", "site": "雇主网站", "user": "你", "draft": "申请记录", "auto": "自动批准", "resume": "继续任务", "recover": "程序重启后", "": ""}
# what comes next, by where it stands: (what is open, the things that can be done about it - the page turns them into buttons)
NEXT: dict[str, tuple[str, tuple[str, ...]]] = {
    "recon": ("Agent 正在做这份申请", ()),
    "revising": ("Agent 正在按你的意见处理这份申请", ()),
    "needs_input": ("有问题等你回答", ("open_draft",)),
    "draft_ready": ("申请记录等你批准", ("open_draft",)),
    "approved": ("已批准，等 Agent 去提交", ()),
    "executing": ("Agent 正在核对并提交", ()),
    "drifted": ("申请表有变化", ("rerun",)),
    "needs_human": ("需要你处理后才能继续（见“需要我处理”）", ("open_todos",)),
    "failed": ("上一次没有做成，可以让 Agent 再做一次", ("rerun", "open_draft")),
    "ready_to_submit": ("表单已经填好，还没有提交", ("rerun", "mark_submitted")),
    UNKNOWN: ("点过提交，还不知道有没有提交成功：等确认邮件，或告诉程序结果", ("check_mail", "mark_submitted", "rerun_not_submitted")),
    "submitted": ("已提交，等雇主的确认邮件", ("check_mail",)),
    "confirmed": ("雇主已确认收到，等后续消息", ()),
    "assessment": ("有笔试 / 测评，按邮件里的安排完成", ()),
    "interview": ("有面试，按邮件里的安排准备", ()),
    "offer": ("收到 Offer", ()),
    "rejected": ("这份申请没有通过", ()),
    "withdrawn": ("你决定不投这个岗位", ()),
}


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def _utc(d: datetime | None) -> datetime:
    if d is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def _row(a: Application) -> dict[str, Any]:
    j = a.job
    st = stages.describe(stages.stage(j.status, bool(j.online), j.deadline or "", a.status))
    return {"id": a.id, "job_id": j.id, "company": j.company, "title": j.title, "location": j.location, "apply_url": j.apply_url,
            "status": a.status, "status_label": humanize.APP_STATUS.get(a.status, a.status), "group": st["stage_group"], "tone": st["stage_tone"],
            "submitted_at": _iso(a.submitted_at), "created_at": _iso(a.created_at), "updated_at": _iso(a.updated_at),
            "last_event": humanize.explain(a.last_event)["message"] if a.last_event else "", "sent": a.status in SENT, "unknown": a.status == UNKNOWN,
            "next": NEXT.get(a.status, ("", ()))[0]}


def listing() -> list[dict[str, Any]]:
    """The applications that have gone out, or whose submission is open - "my applications", the latest change first.
    (What is still being prepared is in the drafts and the jobs list.)"""
    with db.session() as s:
        rows = [_row(a) for a in s.query(Application).join(Job) if a.status in SENT or a.status in (UNKNOWN, "ready_to_submit")]
    return sorted(rows, key=lambda r: r["updated_at"] or r["created_at"] or "", reverse=True)


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
        out = _row(a)
        out["actions"] = list(NEXT.get(a.status, ("", ()))[1])
        out["explained"] = humanize.explain(a.last_event)
        out["detail"], out["auto_approved"], out["channel"] = a.detail, bool(a.auto_approved), a.channel
        out["job_id"] = j.id
        out["job"] = {"id": j.id, "company": j.company, "title": j.title, "location": j.location, "deadline": j.deadline, "apply_url": j.apply_url, "score": j.score,
                      "online": bool(j.online), "posted": j.posted, "summary": j.summary, "brief": j.brief, "source": j.source, "source_id": j.source_id,
                      "ats_label": humanize.ats_name(j.ats), "term": j.term, "months": j.months, "salary": j.salary}
        ev = dict(a.evidence or {})
        out["evidence"] = {"text": str(ev.get("text") or ""), "url": str(ev.get("url") or ""), "read_by": str(ev.get("read_by") or ""),
                           "already_applied": bool(ev.get("already_applied")), "has_screenshot": picture(ev) is not None,
                           "mail_ids": list(ev.get("mail_ids") or ([ev["mail_id"]] if ev.get("mail_id") else [])), "by_user": bool(ev.get("user"))}
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
            line.append({"at": _iso(r.created_at), "kind": "run", "what": "填写申请表" if r.kind == "execute" else "预读表单后面的步骤", "ok": bool(r.ok), "run_id": r.id})
        from .agent import work

        for e in work.journal(a.id):      # each run of the agent on it: how it ended, in the agent's own words
            if e["kind"] in ("report", "ended"):
                line.append({"at": e["at"], "kind": "run", "what": "Agent 的一次运行", "ok": e["kind"] == "report", "said": str(e.get("text") or "")[:300]})
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
                raise NotAllowed("只能手动记为：已提交、已确认、笔试、面试、Offer、被拒、不投了。准备和填写中的状态由程序维护。")
            lifecycle.move(a, status, source="user", back=True, note=note)
            label = humanize.APP_STATUS.get(status, status)
            a.last_event = f"你手动记为“{label}”" + (f"：{note}" if note else "")
            if status in SENT:
                lifecycle.add_evidence(a, {"user": {"status": status, "at": now().isoformat(), "note": note}})
        if submitted_at is not None:
            if a.status not in SENT:
                raise NotAllowed("还没有投出的申请没有投出日期。")
            old = a.submitted_at
            a.submitted_at = submitted_at
            if _utc(old) != _utc(submitted_at):
                s.add(ApplicationEvent(application_id=a.id, old=a.status, new=a.status, source="user",
                                       note=f"投出日期改为 {submitted_at.date().isoformat()}" + (f"（原为 {old.date().isoformat()}）" if old else "")))
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
        s.add(ApplicationEvent(application_id=application_id, old=a.status, new=a.status, source="user", note=f"邮件“{(m.subject or '')[:80]}”不是关于这份申请的"))
    if back is not None:
        # It is about some application, only not this one: the card that asks which comes back. (A mail the program
        # matched by itself never had one, and a mail matched by hand had its card closed; the mailbox is not read
        # twice for the same mail - so the mail went nowhere, though the page said it would wait among the to-dos.)
        from . import mail

        mail.ask_which(*back, push=False)
    return True


def as_csv() -> str:
    """The applications as a table to keep or to open in a spreadsheet: what was applied for, when, where it stands."""
    out = io.StringIO()
    wr = csv.writer(out, lineterminator="\n")
    wr.writerow([i18n.tr(h) for h in ("公司", "岗位", "地点", "状态", "投出日期", "最近进展", "岗位链接", "最后更新")])
    for r in listing():
        wr.writerow([r["company"], r["title"], r["location"] or "", i18n.tr(r["status_label"]), (r["submitted_at"] or "")[:10], i18n.tr(r["last_event"] or r["next"]),
                     r["apply_url"] or "", (r["updated_at"] or "")[:16].replace("T", " ")])
    return "﻿" + out.getvalue()       # (the mark a spreadsheet needs to read the names of companies in any script)
