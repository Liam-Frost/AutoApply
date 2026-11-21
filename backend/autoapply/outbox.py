"""E-mail the program writes for the applicant: an application sent by e-mail, a reply to an employer's question.

A mail is written (by the application's agent, or by the reply writer here), kept as an ``Outgoing``, and sent from
the applicant's own mailbox - at once, or after they have looked at it, as they have set (``mail.send``: "review" |
"auto"). Nothing leaves that is not on record here first, with who it goes to, what it says and what is attached; what
was sent is kept with the mailbox's own id for it, which is the evidence that it went out.

What a mail may say about the applicant is what the program was given about them. A reply that needs something it was
not given says so in the text, between ``MISSING`` marks, and is not sent while such a mark is in it.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from . import db, lifecycle, notify
from .models import Application, Outgoing, Todo, now

log = logging.getLogger("autoapply.outbox")

KIND = "mail_out"                       # the card that shows a mail waiting to be looked at and sent
MISSING = ("[[", "]]")                  # around what the applicant has to fill in before a mail can go
OPEN = ("draft", "failed")              # states in which a mail can still be changed and sent


class NotNow(ValueError):
    """The mail cannot be sent as things are: the message says why, for the applicant."""


def policy() -> str:
    return "auto" if db.get_setting("mail.send") == "auto" else "review"


def missing(text: str) -> list[str]:
    return [m.strip() for m in re.findall(re.escape(MISSING[0]) + r"(.*?)" + re.escape(MISSING[1]), text or "", flags=re.S)]


def _addresses(v: Any) -> str:
    """One line of addresses, as given: checked only for having one in it (the mailbox refuses what is malformed)."""
    line = ", ".join(str(x).strip() for x in v) if isinstance(v, (list, tuple)) else str(v or "").strip()
    return re.sub(r"\s+", " ", line)[:500]


def as_dict(o: Outgoing) -> dict[str, Any]:
    return {"id": o.id, "application_id": o.application_id, "kind": o.kind, "to": o.to, "cc": o.cc, "subject": o.subject, "body": o.body,
            "attachments": [{"name": a.get("name", ""), "there": Path(str(a.get("path") or "")).is_file()} for a in (o.attachments or [])],
            "status": o.status, "error": o.error, "missing": missing(o.body), "reply_to": bool(o.in_reply_to),
            "created_at": o.created_at.isoformat() if o.created_at else None, "sent_at": o.sent_at.isoformat() if o.sent_at else None,
            "sent_from": o.sent_from, "can_edit": o.status in OPEN}


def get(outgoing_id: int) -> dict[str, Any] | None:
    from . import mail

    with db.session() as s:
        o = s.get(Outgoing, outgoing_id)
        if o is None:
            return None
        out = as_dict(o)
        app = s.get(Application, o.application_id) if o.application_id else None
        out["about"] = f"{app.job.company} · {app.job.title}" if app is not None and app.job is not None else ""
    out["can_send"], out["policy"] = mail.can_send(), policy()
    return out


def of_application(application_id: int) -> list[dict[str, Any]]:
    with db.session() as s:
        return [as_dict(o) for o in s.query(Outgoing).filter_by(application_id=application_id).order_by(Outgoing.id.desc())]


def compose(application_id: int | None, *, kind: str, to: Any, subject: str, body: str, cc: Any = "", attachments: list[dict[str, str]] | None = None,
            in_reply_to: str = "", todo_id: int | None = None, title: str = "") -> int:
    """Put a mail on record, ready to be looked at and sent. An earlier one of the same kind for the same application
    that was not sent is replaced by it. Returns its id."""
    to = _addresses(to)
    if "@" not in to:
        raise ValueError("the mail needs an address to go to")
    if not str(subject).strip() or not str(body).strip():
        raise ValueError("the mail needs a subject and a text")
    files = []
    for a in attachments or []:
        if not Path(str(a.get("path") or "")).is_file():
            raise ValueError(f"the file {a.get('name')!r} is not there")
        files.append({"name": str(a["name"]), "path": str(a["path"])})
    with db.session() as s:
        if application_id:
            for old in s.query(Outgoing).filter(Outgoing.application_id == application_id, Outgoing.kind == kind, Outgoing.in_reply_to == in_reply_to, Outgoing.status.in_(OPEN)):
                old.status = "discarded"
                notify.close_todos(KIND, f"mail:{old.id}")
        o = Outgoing(application_id=application_id, kind=kind, to=to, cc=_addresses(cc), subject=" ".join(str(subject).split())[:300], body=str(body).strip(),
                     attachments=files, in_reply_to=in_reply_to, status="draft", todo_id=todo_id)
        s.add(o)
        s.flush()
        oid = o.id
        if todo_id:      # the card that asked for the reply now has one to show
            t = s.get(Todo, todo_id)
            if t is not None:
                t.payload = {**(t.payload or {}), "outgoing_id": oid}
    if not todo_id:
        notify.add_todo(KIND, title or subject, body=f"收件人：{to}\n主题：{subject}", ref=f"mail:{oid}", payload={"outgoing_id": oid, "application_id": application_id})
    return oid


def edit(outgoing_id: int, changes: dict[str, Any]) -> dict[str, Any]:
    with db.session() as s:
        o = s.get(Outgoing, outgoing_id)
        if o is None:
            raise KeyError(outgoing_id)
        if o.status not in OPEN:
            raise NotNow("这封邮件已经发出或已经作废，不能再改。")
        if "to" in changes:
            o.to = _addresses(changes["to"])
        if "cc" in changes:
            o.cc = _addresses(changes["cc"])
        if "subject" in changes:
            o.subject = " ".join(str(changes["subject"]).split())[:300]
        if "body" in changes:
            o.body = str(changes["body"]).strip()
        if "remove_attachment" in changes:
            o.attachments = [a for a in (o.attachments or []) if a.get("name") != changes["remove_attachment"]]
        return as_dict(o)


def discard(outgoing_id: int) -> None:
    with db.session() as s:
        o = s.get(Outgoing, outgoing_id)
        if o is None or o.status not in OPEN:
            return
        o.status = "discarded"
    notify.close_todos(KIND, f"mail:{outgoing_id}")


def send(outgoing_id: int, *, by: str = "user") -> dict[str, Any]:
    """Send the mail from the applicant's mailbox and record that it went: on the mail, and - for an application sent
    by e-mail - on the application, which is sent from this moment. ``by``: "user" (they pressed send) or "auto"."""
    from . import mail

    with db.session() as s:
        o = s.get(Outgoing, outgoing_id)
        if o is None:
            raise KeyError(outgoing_id)
        if o.status == "sent":
            return as_dict(o)
        if o.status not in OPEN:
            raise NotNow("这封邮件已经作废。")
        if "@" not in o.to or not o.subject or not o.body:
            raise NotNow("邮件还缺收件人、主题或正文。")
        if missing(o.body) or missing(o.subject):
            raise NotNow("正文里还有需要你填写的内容（[[ ]] 标出来的部分），填好再发。")
        gone = [a["name"] for a in (o.attachments or []) if not Path(str(a.get("path") or "")).is_file()]
        if gone:
            raise NotNow(f"附件不在了：{'、'.join(gone)}")
        o.status = "sending"      # (set before the mailbox is asked: a mail is not sent twice by two presses)
        what = {"to": o.to, "cc": o.cc, "subject": o.subject, "body": o.body, "attachments": list(o.attachments or []), "in_reply_to": o.in_reply_to}
        kind, app_id, todo_id = o.kind, o.application_id, o.todo_id
    try:
        got = mail.send_message(**what)
    except Exception as e:  # noqa: BLE001 - whatever stopped it, the mail is still here to be sent
        with db.session() as s:
            o = s.get(Outgoing, outgoing_id)
            # (what the applicant is told is the program's own sentence; the error as it was is in the log)
            o.status, o.error = "failed", (str(e)[:300] if isinstance(e, mail.MailNotConfigured)
                                           else "连接邮箱服务器时网络中断了，试了三次都没有发出去。到“已发送”里确认过没有这封信，可以直接再发一次。" if mail._dropped(e)
                                           else "邮箱没有接受这封邮件。详细原因记在程序的日志里。")
        if isinstance(e, mail.MailNotConfigured):
            raise NotNow(str(e)) from e
        log.exception("mail %s could not be sent", outgoing_id)
        raise
    with db.session() as s:
        o = s.get(Outgoing, outgoing_id)
        o.status, o.error, o.sent_at, o.message_id, o.thread_id, o.sent_from, o.sent_by = "sent", "", now(), got.get("id", ""), got.get("thread_id", ""), got.get("from", ""), by
        sent = as_dict(o)
        names = [a["name"] for a in (o.attachments or [])]
    notify.close_todos(KIND, f"mail:{outgoing_id}")
    words = f"E-mail sent from {got.get('from') or 'the applicant mailbox'} to {what['to']} - subject: {what['subject']}" + (f" - attached: {', '.join(names)}" if names else "")
    if kind == "application" and app_id:
        title = ""
        with db.session() as s:
            app = s.get(Application, app_id)
            if app is not None:
                title = f"{app.job.company} · {app.job.title}" if app.job is not None else ""
                lifecycle.move(app, "submitted", source="run", at=now(), evidence={"text": words, "ties_to_posting": what["subject"], "read_by": "mailbox",
                                                                                   "mail": {"outgoing_id": outgoing_id, "message_id": got.get("id", ""), "thread_id": got.get("thread_id", "")}})
                app.last_event, app.auto_approved = "", int(by == "auto")
        from .agent import work

        work._sent(app_id, title, {"words": words}, by == "auto")
    elif todo_id:      # a reply: what the employer asked for has been answered
        with db.session() as s:
            t = s.get(Todo, todo_id)
            if t is not None and t.status == "open":
                t.status, t.done_at = "done", now()
    return sent


# --- a reply to what an employer's mail asks -------------------------------------------------------------------------
REPLY_SYSTEM = """You write a reply e-mail for a job applicant, to a mail an employer sent them about one of their
applications. You are given the employer's mail, what the program knows about the applicant, and the posting.

- Answer what the mail asks, each point, in the order it asks. Short, plain, courteous; the applicant's own voice
  (first person); the language of the employer's mail. No subject line in the text, no placeholders for a signature:
  sign with the applicant's name as their profile gives it.
- Every fact about the applicant comes from what you were given. Where the mail asks something you were not given -
  an eligibility, a date, a yes or no - do not guess and do not word around it: write, at that place,
  [[what the applicant has to say here, as a question to them in their own language]], and list the same question in
  `missing`. A sensible reading of what you were given is not guessing (a profile that says they study in a co-op
  programme answers "are you enrolled in a co-op programme").
- Do not promise, accept, decline or reschedule anything the applicant has not said."""

REPLY_SCHEMA = {"type": "object", "properties": {"subject": {"type": "string"}, "body": {"type": "string"}, "missing": {"type": "array", "items": {"type": "string"}}},
                "required": ["subject", "body", "missing"], "additionalProperties": False}


def draft_reply(todo_id: int) -> dict[str, Any]:
    """Write the reply to the mail a card is about, and put it on record for the applicant to look at (or send it,
    when they have set so and nothing is missing from it)."""
    from . import llm, mail
    from .agent import brief

    with db.session() as s:
        t = s.get(Todo, todo_id)
        if t is None or t.status != "open":
            return {"skipped": "the card is closed"}
        p = dict(t.payload or {})
        app = s.get(Application, int(p.get("application_id") or 0))
        if app is None or not p.get("message_id"):
            return {"skipped": "the card names no mail"}
        job = app.job
        about = f"Employer: {job.company}\nRole: {job.title}\n\n{(job.jd_text or '')[:6000]}" if job is not None else ""
        app_id, channel = app.id, (job.channel if job is not None else "") or ""
        said = "\n".join(f"- {a.get('label')}: {a.get('value')}" for d in app.drafts[-1:] for a in (d.answers or []) if a.get("value") not in ("", None, []))[:6000]
    original = mail.original(str(p["message_id"]))
    if original is None:
        return {"skipped": "the mail cannot be read from this mailbox"}
    applicant = brief.applicant_on_file(channel)
    prompt = "\n\n".join(x for x in (
        "# The employer's mail\nFrom: " + original["from"] + "\nSubject: " + original["subject"] + "\n\n" + original["body"][:12000],
        "# The applicant\n" + applicant.profile,
        ("# Their résumé\n" + applicant.resume[:8000]) if applicant.resume else "",
        ("# What they answered on this application's form\n" + said) if said else "",
        ("# The posting\n" + about) if about else "",
    ) if x)
    out = llm.json(prompt, REPLY_SCHEMA, system=REPLY_SYSTEM, max_tokens=4000)
    body = str(out.get("body") or "").strip()
    for q in out.get("missing") or []:      # (said in `missing` and not marked in the text: marked, so that it cannot be sent unanswered)
        if str(q).strip() and str(q).strip() not in " ".join(missing(body)):
            body += f"\n\n{MISSING[0]}{str(q).strip()}{MISSING[1]}"
    subject = original["subject"] if original["subject"].lower().startswith("re:") else "Re: " + original["subject"]
    oid = compose(app_id, kind="reply", to=original["reply_to"] or original["from"], subject=subject, body=body, in_reply_to=str(p["message_id"]), todo_id=todo_id)
    if policy() == "auto" and not missing(body) and mail.can_send():
        send(oid, by="auto")
        return {"outgoing_id": oid, "sent": True}
    return {"outgoing_id": oid, "sent": False, "missing": len(missing(body))}
