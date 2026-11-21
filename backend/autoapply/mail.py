"""Gmail (read-only), and tracking what the mailbox says about the applications.

Scope is ``gmail.readonly``. Nothing is sent, labelled, or modified. Tracking sends one e-mail body at a time to the
small model. Mail about an account - a code, a link to confirm an address - is not tracked, summarised or notified;
the agent reads it from the mailbox itself when a site sends one while it works (agent/run.py: ``mail``).
"""

from __future__ import annotations

import html
import base64
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from . import db, lifecycle, llm, messages, notify, secrets
from . import prompts
from .models import RANK, SENT, UNKNOWN, Application, Job, MailEvent  # noqa: F401  (RANK: how far along; a mail never moves an application backwards by itself)

log = logging.getLogger("autoapply.mail")
# What the applicant is asked to grant. Reading was all there was; sending (an application by e-mail, a reply to an
# employer) needs more, and they chose to grant drafts and changing a message's labels with it, for what comes later.
# A mailbox authorized before keeps working for what it was granted: ``granted`` says what that is.
READ = "https://www.googleapis.com/auth/gmail.readonly"
SEND = "https://www.googleapis.com/auth/gmail.send"
SCOPES = [READ, SEND, "https://www.googleapis.com/auth/gmail.compose", "https://www.googleapis.com/auth/gmail.modify"]


class MailNotConfigured(RuntimeError):
    pass


class GmailReconnect(MailNotConfigured):
    """Google explicitly rejected the stored refresh grant."""


# --- OAuth -------------------------------------------------------------------------


def save_client_config(client_json: str) -> None:
    """Store the OAuth client (the 'Desktop app' JSON downloaded from Google Cloud)."""
    json.loads(client_json)  # validate
    secrets.put(secrets.GMAIL_CLIENT, client_json)


def authorize() -> None:
    """Run the local OAuth consent flow (opens the system browser once)."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    cfg = secrets.get(secrets.GMAIL_CLIENT)
    if not cfg:
        raise MailNotConfigured("Upload the Google OAuth client JSON first.")
    flow = InstalledAppFlow.from_client_config(json.loads(cfg), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    secrets.put(secrets.GMAIL_TOKEN, creds.to_json())
    db.set_setting("mail.gmail_reconnect", False)


def granted() -> set[str]:
    """What the stored authorization allows."""
    try:
        scopes = json.loads(secrets.get(secrets.GMAIL_TOKEN) or "{}").get("scopes") or []
    except ValueError:
        return set()
    return set(scopes.split() if isinstance(scopes, str) else scopes)


def can_send() -> bool:
    """Can a mail be sent from the applicant's mailbox as it is connected now?"""
    from . import mailbox

    return mailbox.kind() == "gmail_api" and SEND in granted() and not bool(db.get_setting("mail.gmail_reconnect"))


def status() -> dict[str, bool]:
    return {"can_send": can_send(), "client": secrets.has(secrets.GMAIL_CLIENT), "reconnect": bool(db.get_setting("mail.gmail_reconnect")), "authorized": secrets.has(secrets.GMAIL_TOKEN) and not bool(db.get_setting("mail.gmail_reconnect"))}


def migrate_reconnect_waits() -> None:
    """Move an old employer card only when the linked task and the Google error agree."""
    from .models import Task, Todo
    from .mailbox import kind

    if kind() != "gmail_api":
        return
    with db.session() as session:
        last = session.query(Task).filter_by(kind="mail").order_by(Task.id.desc()).first()
        if not last or last.status != "failed" or "invalid_grant" not in last.error:
            return
        for task in session.query(Task).filter_by(kind="apply", status="waiting_human"):
            ref = (task.payload or {}).get("waits_for", "")
            if not ref.startswith("account:"):
                continue
            card = session.query(Todo).filter_by(ref=ref, kind="takeover", status="open").first()
            if not card or "RefreshError" not in card.body or "邮箱" not in card.body:
                continue
            task.payload = {**task.payload, "waits_for": "config:gmail"}
            card.kind, card.title, card.ref = "config", "重新授权 Gmail 邮箱", "config:gmail"
            card.payload, card.body = {}, "Google 已拒绝旧授权。请到设置 → 账号与连接 → 收件邮箱重新授权，随后重试原岗位。"


def _service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google_auth_httplib2 import AuthorizedHttp
    import httplib2

    tok = secrets.get(secrets.GMAIL_TOKEN)
    if not tok:
        raise MailNotConfigured("Gmail is not authorized (Settings > Gmail).")
    # (with the scopes the token was granted, not the ones asked for today: a refresh that names a scope the applicant
    # never granted is refused, and reading their mail would stop until they authorized again)
    creds = Credentials.from_authorized_user_info(json.loads(tok))
    if creds.expired and creds.refresh_token:
        from google.auth.exceptions import RefreshError

        try:
            transport = Request()

            def request_with_deadline(*args, **kwargs):
                kwargs["timeout"] = 20
                return transport(*args, **kwargs)

            creds.refresh(request_with_deadline)
        except RefreshError as exc:
            if not any(isinstance(arg, dict) and arg.get("error") == "invalid_grant" for arg in exc.args):
                raise
            db.set_setting("mail.gmail_reconnect", True)
            raise GmailReconnect("Gmail 授权已过期或被撤销，请在设置的邮箱连接中重新授权。") from exc
        secrets.put(secrets.GMAIL_TOKEN, creds.to_json())
    return build("gmail", "v1", http=AuthorizedHttp(creds, http=httplib2.Http(timeout=20)), cache_discovery=False)


# --- sending -------------------------------------------------------------------------
def original(message_id: str) -> dict[str, str] | None:
    """A mail in the mailbox, as far as answering it needs: who it is from, where an answer goes, what it says, and
    what ties an answer to it. None when this mailbox cannot be asked for one mail."""
    from . import mailbox

    if mailbox.kind() != "gmail_api":
        return None
    msg = _service().users().messages().get(userId="me", id=message_id, format="full").execute()
    refs = " ".join(x for x in (_hdr(msg, "References"), _hdr(msg, "Message-ID")) if x)
    return {"from": _hdr(msg, "From"), "reply_to": _hdr(msg, "Reply-To"), "subject": _hdr(msg, "Subject"), "body": _body(msg["payload"]),
            "message_id_header": _hdr(msg, "Message-ID"), "references": refs, "thread_id": msg.get("threadId", "")}


def send_message(*, to: str, subject: str, body: str, cc: str = "", attachments: list[dict[str, str]] | None = None, in_reply_to: str = "") -> dict[str, str]:
    """Send one mail from the applicant's mailbox. ``in_reply_to``: the mailbox's id of the mail it answers - it then
    goes into that conversation. Returns the mailbox's id of what was sent, its conversation, and the address it went
    from. Called only by outbox.send, which has the mail on record first."""
    import mimetypes
    from email.message import EmailMessage
    from pathlib import Path

    if not can_send():
        raise MailNotConfigured("程序还没有从你的邮箱发信的权限。请到设置 → 账号与连接 → 收件邮箱重新授权（授权页会多出“发送邮件”一项）。")
    service = _service()
    sender = service.users().getProfile(userId="me").execute().get("emailAddress", "")
    m = EmailMessage()
    m["To"], m["Subject"] = to, subject
    if sender:
        m["From"] = sender
    if cc:
        m["Cc"] = cc
    thread = ""
    if in_reply_to:
        was = original(in_reply_to) or {}
        if was.get("message_id_header"):
            m["In-Reply-To"], m["References"] = was["message_id_header"], was.get("references") or was["message_id_header"]
        thread = was.get("thread_id", "")
    m.set_content(body)
    for a in attachments or []:
        kind, _ = mimetypes.guess_type(a["name"])
        main, _, sub_ = (kind or "application/octet-stream").partition("/")
        m.add_attachment(Path(a["path"]).read_bytes(), maintype=main, subtype=sub_, filename=a["name"])
    raw = {"raw": base64.urlsafe_b64encode(m.as_bytes()).decode()}
    if thread:
        raw["threadId"] = thread
    sent = service.users().messages().send(userId="me", body=raw).execute()
    return {"id": sent.get("id", ""), "thread_id": sent.get("threadId", ""), "from": sender}


# --- message helpers -----------------------------------------------------------------


def _body(payload: dict[str, Any]) -> str:
    """Prefer text/plain; fall back to stripped HTML."""
    plain, htmls = [], []

    def walk(p: dict[str, Any]) -> None:
        data = (p.get("body") or {}).get("data")
        mt = p.get("mimeType", "")
        if data:
            txt = base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="ignore")
            (plain if mt == "text/plain" else htmls if mt == "text/html" else []).append(txt)
        for c in p.get("parts", []) or []:
            walk(c)

    walk(payload)
    if plain:
        return "\n".join(plain)
    h = "\n".join(htmls)
    h = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", h, flags=re.I)
    # the address as a browser would follow it: in HTML, "&" in an address is written "&amp;"
    h = re.sub(r'<a[^>]+href="([^"]+)"[^>]*>', lambda m: f" {html.unescape(m.group(1))} ", h, flags=re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))


def _hdr(msg: dict[str, Any], name: str) -> str:
    for h in msg["payload"].get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _list(query: str, max_results: int = 50, *, skip: Any = None) -> list[dict[str, Any]]:
    """The messages a search finds, in full. ``skip(id)`` says which ones are already known: those are not fetched
    again - the list of ids is one request, each message is another."""
    svc = _service()
    ids = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute().get("messages", [])
    return [svc.users().messages().get(userId="me", id=m["id"], format="full").execute() for m in ids if not (skip and skip(m["id"]))]


# --- what arrived since the last look -------------------------------------------------
#
# Gmail keeps a numbered history of the mailbox. "What was added to the inbox after number N" is one small request,
# and usually the answer is "nothing" - so the mailbox can be asked every couple of minutes instead of once an hour,
# and a confirmation shows up when it arrives. Only messages that were *added* are asked for: reading a message,
# archiving it or labelling it yourself changes nothing here, and nothing here marks a message as read (the scope is
# read-only). The number is kept in the setting mail.gmail_history; the hourly pass over the last days still runs
# and catches whatever this missed.

HISTORY = "mail.gmail_history"


def mark_history() -> str:
    """Remember where the mailbox's history stands now: the next look starts from here."""
    now_at = str(_service().users().getProfile(userId="me").execute().get("historyId") or "")
    if now_at:
        db.set_setting(HISTORY, now_at)
    return now_at


def anything_new() -> bool | None:
    """Was anything added to the inbox since the last look? One request, and nothing is fetched. When nothing was,
    the place in the history is moved on; when something was, it is left for added_since_last() to read from.
    None: it cannot be told (no earlier look, or too long ago)."""
    from googleapiclient.errors import HttpError

    start = str(db.get_setting(HISTORY) or "")
    if not start or not secrets.has(secrets.GMAIL_TOKEN):
        return None
    try:
        page = _service().users().history().list(userId="me", startHistoryId=start, historyTypes=["messageAdded"], labelId="INBOX", maxResults=20).execute()
    except HttpError as e:
        if getattr(e.resp, "status", 0) == 404:
            db.set_setting(HISTORY, "")
            return None
        raise
    if any(h.get("messagesAdded") for h in page.get("history", [])) or page.get("nextPageToken"):
        return True
    if page.get("historyId"):
        db.set_setting(HISTORY, str(page["historyId"]))
    return False


_pending: str | None = None      # where the history will stand once what added_since_last() returned has been dealt with


def commit_history() -> None:
    """What added_since_last() returned has been recorded: the place in the history moves on to behind it."""
    global _pending
    if _pending:
        db.set_setting(HISTORY, _pending)
    _pending = None


def added_since_last(limit: int = 50, *, skip: Any = None) -> list[dict[str, Any]] | None:
    """Messages added to the inbox since the last look, in full, oldest first. None when that cannot be told - there
    was no earlier look, or it is so long ago that Gmail no longer keeps the history - and the caller has to read
    the last days instead.

    At most about ``limit`` messages, the oldest ones: when more arrived, the rest stays in the history for the next
    call. The place in the history is not moved here: the caller says when the messages have been dealt with
    (commit_history), so that a batch that failed half-way is read again."""
    global _pending

    from googleapiclient.errors import HttpError

    start = str(db.get_setting(HISTORY) or "")
    if not start:
        return None
    svc = _service()
    records: list[tuple[str, list[str]]] = []       # (the record's number in the history, the messages it added)
    seen: set[str] = set()
    latest, token = start, None
    try:
        while True:
            page = svc.users().history().list(userId="me", startHistoryId=start, historyTypes=["messageAdded"], labelId="INBOX", pageToken=token).execute()
            for h in page.get("history", []):
                mids = [m for a in h.get("messagesAdded", []) if (m := a.get("message", {}).get("id")) and m not in seen]
                seen.update(mids)
                if mids:
                    records.append((str(h.get("id") or ""), mids))
            latest = str(page.get("historyId") or latest)
            token = page.get("nextPageToken")
            if not token:
                break
    except HttpError as e:
        if getattr(e.resp, "status", 0) == 404:        # the number is older than what Gmail keeps (about a week)
            db.set_setting(HISTORY, "")
            return None
        raise
    ids: list[str] = []
    upto = latest
    for n, (number, mids) in enumerate(records):
        ids += mids
        if len(ids) >= limit and n < len(records) - 1 and number:      # whole records only: the place in the history is a record's number
            upto = number
            break
    out = []
    for mid in ids:
        if skip and skip(mid):
            continue
        try:
            out.append(svc.users().messages().get(userId="me", id=mid, format="full").execute())
        except HttpError as e:
            if getattr(e.resp, "status", 0) != 404:    # deleted between the two requests: not there to read
                raise
    _pending = upto
    return out


# Mail about an account - a code, a link to confirm an address, a password reset: not about an application. It is never
# summarised, stored or notified; the agent reads it from the mailbox itself when a site sends one while it works.
ACCOUNT_MAIL = re.compile(r"(security|verification|one[- ]time|temporary|access|login)\s*(code|pin|passcode|password)|\b(otp|passcode)\b|\bverify\b|"
                          r"\bactivate your\b|\bconfirm your\b.{0,40}\b(e-?mail|account|address)|reset your password", re.I)


# --- tracking ----------------------------------------------------------------------------

CATEGORIES = ["confirmation", "rejection", "interview", "assessment", "info_request", "offer", "other"]
# A category says what an e-mail is ABOUT; the event says what it says about it. "About an interview" was read as
# "invited to an interview": an e-mail cancelling one was announced as an invitation and moved the application forward.
EVENTS = ["new", "changed", "reminder", "cancelled"]
TRIAGE_SCHEMA = llm.obj(
    {
        "category": {"type": "string", "enum": CATEGORIES},
        "company": {"type": "string"},
        "job_title": {"type": "string"},
        "event": {"type": "string", "enum": EVENTS,
                  "description": "what the e-mail says about the thing its category names. new: it is announced - an invitation to an interview or an assessment, "
                                 "an offer made, a rejection, an application received. changed: it stands, with different or further details - an interview "
                                 "moved to another time, a time or place confirmed. reminder: nothing new, it is recalled. cancelled: it is called off - an "
                                 "interview cancelled, an assessment no longer needed, an offer withdrawn. An e-mail that cancels an interview is category "
                                 "interview, event cancelled - never event new."},
        "action": {"type": "string", "description": "what the applicant has to do, if the e-mail asks for something: 'complete the online assessment', 'choose an interview "
                                                    "slot', 'attend the interview', 'reply with availability'. One short phrase, in Simplified Chinese. Empty when it asks for nothing."},
        "due": {"type": "string", "description": "the date, or date and time, by which or at which that is to be done - ONLY if the e-mail states one. ISO form: 2026-11-24 or "
                                                 "2026-11-24T10:00. Use the year the e-mail implies. Empty when the e-mail states no date: never work one out from 'within a week' "
                                                 "or from when the e-mail was sent."},
        "due_text": {"type": "string", "description": "that date and time in the e-mail's own words, with the time zone if it names one ('Tuesday, Nov 24 at 10:00 AM PST'). Empty when none."},
        "received": {"type": "boolean", "description": "true only if the e-mail states that a COMPLETED application was received or submitted. false for an application "
                                                         "that was started, saved or is in progress, a reminder to finish it, an account or profile that was created, "
                                                         "an e-mail address to confirm, a sign-in or security code."},
        "summary": {"type": "string", "description": "one sentence; include any deadline or date mentioned. Write this in Simplified Chinese (it is shown to the applicant); keep company names, product names and quoted form text in their original language."},
    }
)
STATUS_FOR = {"confirmation": "confirmed", "rejection": "rejected", "interview": "interview", "assessment": "assessment", "offer": "offer"}
PREPARING = ("recon", "needs_input", "draft_ready", "revising", "approved", "executing", "needs_human", "failed", "drifted")   # before any submission
QUERY = '(application OR applying OR applied OR interview OR assessment OR candidate OR position OR "thank you for your interest" OR unfortunately) -category:promotions'


TRIAGE_RULES = """Classify this e-mail from the point of view of a job applicant. 'other' covers newsletters, job alerts, and anything
not about one of the applicant's own applications.

'confirmation' means one thing only: the employer says it has received a completed, submitted application. These are NOT confirmations,
they are 'other': "keep track of your application" / "you started an application" / "finish your application" (the application was begun,
not submitted); "your account / candidate profile was created"; "confirm your e-mail address"; sign-in and security codes.
Set `received` accordingly.

The category is what the e-mail is about; `event` is what it says about it. An interview that is being cancelled, moved or
recalled is still category 'interview' - with event 'cancelled', 'changed' or 'reminder'. Only the first announcement is 'new'.
Read what the e-mail does, not the words it uses: "we need to cancel your interview" is a cancellation even though it says "interview"."""


def triage(subject: str, sender: str, body: str) -> dict[str, Any]:
    return llm.json(
        f"From: {sender}\nSubject: {subject}\n\n{body[:8000]}",
        TRIAGE_SCHEMA, small=True, max_tokens=1000, system=prompts.get("mail_triage"),
    )


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


_FORMS = {"inc", "ltd", "limited", "corp", "corporation", "co", "company", "llc", "llp", "plc", "gmbh", "ag", "sa", "the", "group", "holdings", "technologies", "technology"}


def _same_company(c: str, jc: str) -> bool:
    """Are these two names one employer? When one name is inside the other ("Google" / "Google LLC", "Amazon" /
    "Amazon Web Services") - by its words, legal forms set aside. One word in common is not enough: "4AG Robotics"
    and "Global Robotics" share a word and nothing else."""
    if not c or not jc:
        return False
    if c in jc or jc in c:
        return True
    a, b = set(c.split()) - _FORMS, set(jc.split()) - _FORMS
    return bool(a and b and (a <= b or b <= a))


def candidates(company: str) -> list[int]:
    """The applications an e-mail from this employer can be about: those at the employer that were sent (an e-mail about
    an application is not about one that is still a draft), the latest first."""
    c = _norm(company)
    with db.session() as s:
        rows = [(a.submitted_at or a.created_at, a.id) for a in s.query(Application).join(Job).all()
                if _same_company(c, _norm(a.job.company)) and (a.submitted_at is not None or RANK.get(a.status, 0) >= 1 or a.status == UNKNOWN)]
    return [i for _, i in sorted(rows, reverse=True)]


def link(message_id: str, application_ids: list[int], *, by: str = "user") -> int:
    """This e-mail is about these applications (said by the applicant on the card, or found on the employer's site).
    Each gets what the e-mail says - the same as if the e-mail had named it. Returns how many changed state."""
    changed, tell = 0, []
    with db.session() as s:      # the link and what follows from it: together, or not at all
        me = s.query(MailEvent).filter_by(message_id=message_id).first()
        if me is None or not application_ids:
            return 0
        if by != "user" and me.linked_by == "user":
            return 0        # the applicant has said which application this is about: nothing the program finds later changes that
        me.application_id, me.linked_by = int(application_ids[0]), by
        category, summary, received, event, asks = me.category, me.summary, me.received_at, me.event or "new", dict(me.asks or {})
        for app_id in application_ids:
            updated, early, title = _record(int(app_id), category, summary, received, message_id, event, session=s)
            changed += updated
            if not early:
                tell.append((int(app_id), title))
    for app_id, title in tell:
        _asked(app_id, title, category, event, summary, asks, message_id)
        _tell(lambda: notify.send("status_update", messages.mail_update(category, title, summary, event=event), ref=f"application:{app_id}", tag=category))
    notify.close_todos("mail_unmatched", f"mail:{message_id}")
    log.info("mail %s linked to application(s) %s (%s)", message_id[:12], application_ids, by)
    return changed


def _asked(app_id: int, title: str, category: str, event: str, summary: str, asks: dict[str, Any] | None, mid: str) -> None:
    """What the mail asks of the applicant becomes a card with its date (reminders.from_mail) - whichever way the mail
    came to its application: named by the mail, or by the applicant afterwards."""
    try:
        from . import reminders

        reminders.from_mail(app_id, title, category, event, summary, asks, mid)
    except Exception:  # noqa: BLE001 - the mail is on record and announced; a card that could not be made does not undo that
        log.exception("could not make a card for what a mail asks")


def _tell(send: Any) -> None:
    """Say what a mail changed. What it changed is on record by now; a notice that cannot be sent does not undo that
    and does not stop the mail that comes after it."""
    try:
        send()
    except Exception:  # noqa: BLE001
        log.exception("a notice about a mail could not be sent")


def _record(app_id: int, category: str, summary: str, received: datetime | None, mid: str, event: str = "new", *, session: Any = None) -> tuple[int, bool, str]:
    """Put what an e-mail says on its application. Returns (1 if the state changed, was it too early to believe, title).

    ``session``: the caller's, when the mail itself is being written in it - the mail and what it does to the
    application are then one write: both there, or neither (and the mail is read again on the next pass).

    An e-mail that calls something off does not move the application to that stage. If the application stands at
    exactly that stage (the interview it was invited to is the one being cancelled), it goes back to where it was
    before - whether another interview follows or a rejection, the next e-mail says."""
    if session is None:
        with db.session() as s:
            return _record(app_id, category, summary, received, mid, event, session=s)
    new_status, updated = STATUS_FOR.get(category), 0
    s = session
    a = s.get(Application, app_id)
    title = f"{a.job.company} · {a.job.title}"
    a.last_event = f"{category}{'' if event in ('', 'new') else ' (' + event + ')'}: {summary}"[:500]
    if event == "cancelled" and category in ("interview", "assessment", "offer"):
        if a.status == new_status:
            from .models import ApplicationEvent

            came = s.query(ApplicationEvent).filter_by(application_id=a.id, new=new_status).order_by(ApplicationEvent.id.desc()).first()
            # the one thing a mail does that takes an application back: the stage it stands at is called off
            lifecycle.move(a, came.old if came is not None and came.old in RANK and came.old != new_status else "submitted", source="mail", back=True)
            updated = 1
        return updated, False, title
    # A confirmation confirms a submission. An application this program is still preparing (no submission by it, none
    # reported by the user) is not turned into "confirmed" by an e-mail: sites send "we have your application" style
    # mail when an application is merely started. The mail is kept on the record and shown; the status stays.
    early = category == "confirmation" and a.status in PREPARING and a.submitted_at is None and not _was_filled(s, a.id, received)
    if early:
        a.last_event = f"收到一封像确认信的邮件，但这份申请程序还没有提交过，状态没有改。如果你已经自己提交了，请在岗位页点“我已经提交了”。邮件：{summary}"[:500]
    elif new_status and RANK.get(new_status, 0) > RANK.get(a.status, 0):
        lifecycle.move(a, new_status, source="mail")
        if a.submitted_at is None:      # the program had not seen the submission; the employer has
            a.submitted_at = received
            a.detail = a.detail or f"submitted {(received or datetime.now(timezone.utc)).date().isoformat()} (confirmed by the employer's e-mail)"
        updated = 1
    if category == "confirmation" and not early:
        lifecycle.add_evidence(a, {"mail_id": mid})
    return updated, early, title


def _utc(d: datetime | None) -> datetime | None:
    return None if d is None else (d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc))


def _numbers(job: Job) -> list[str]:
    """What a recruiter's mail would call this posting: its requisition or posting number, when it has one that is
    more than a few digits (a short number is in every mail)."""
    sid = str(job.source_id or "").split(":")[-1].strip()
    return [sid] if re.fullmatch(r"[A-Za-z]{0,6}[-_]?\d{4,12}", sid) else []


def ask_which(message_id: str, subject: str, category: str, event: str, summary: str, *, push: bool = True) -> None:
    """The card "which application is this mail about?" - for a mail that could not be matched, and for one the
    applicant took off the application it was matched to."""
    notify.add_todo("mail_unmatched", (subject or "")[:80], body=f"{messages.mail_label(category, event or 'new')[1]}：{summary}", ref=f"mail:{message_id}",
                    payload={"message_id": message_id, "category": category}, push=push)


def match_application(company: str, title: str, received: datetime | None, text: str = "") -> int | None:
    """The application an e-mail is about, or None when what it says does not single one out (it then goes to the
    applicant as "which application is this about?").

    The employer has to be the same. Then, in this order:
    - an application that did not exist when the mail was written is not what the mail is about. (A mail of forty days
      ago was put on an application made yesterday for a posting of the same name.) "Existed": the earlier of when the
      program made it and when it was sent - an application the applicant sent by hand and the program met later has
      its real date of sending.
    - the posting's own number in the mail (``text``: subject and body) settles it.
    - the title: more of its words in common is better; among equals, the one sent last before the mail.
    Several applications at the employer and nothing in the mail about which: the one that is furthest along, if
    exactly one is; otherwise None."""
    c = _norm(company)
    if not c:
        return None
    when = _utc(received)
    low = (text or "").lower()
    with db.session() as s:
        cands = []
        for a in s.query(Application).join(Job).all():
            jc = _norm(a.job.company)
            if not _same_company(c, jc):
                continue
            began = min(x for x in (_utc(a.created_at), _utc(a.submitted_at)) if x is not None) if (a.created_at or a.submitted_at) else None
            if when is not None and began is not None and began > when + timedelta(hours=1):
                continue
            named = any(re.search(r"(?<![a-z0-9])" + re.escape(n.lower()) + r"(?![a-z0-9])", low) for n in _numbers(a.job)) if low else False
            t, jt = set(_norm(title).split()), set(_norm(a.job.title).split())
            overlap = len(t & jt) / max(1, len(t | jt))
            at = _utc(a.submitted_at or a.created_at) or datetime.min.replace(tzinfo=timezone.utc)
            cands.append((named, overlap, at, a.id, RANK.get(a.status, 0)))
        if not cands:
            return None
        by_number = [x for x in cands if x[0]]
        if len(by_number) == 1:
            return by_number[0][3]
        cands.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        if len(cands) > 1 and cands[0][1] == cands[1][1] == 0 and not cands[0][0]:
            # Several applications at this company and no title to tell them apart: a follow-up
            # belongs to the one that is furthest along, if exactly one is.
            live = [x for x in cands if 2 < x[4] < 6]
            return live[0][3] if len(live) == 1 else None
        return cands[0][3]


def _was_filled(s: Any, application_id: int, before: datetime | None) -> bool:
    """Has the program filled this application's form (so that the applicant had it in front of them to submit) before
    this time? Then a confirmation is what it says, whatever the program believes about the run: a window that closed, a
    confirmation page that was not recognised."""
    from .agent import work
    from .models import Run

    began = [getattr(r, "created_at", None) for r in s.query(Run).filter_by(kind="execute", ref=f"application:{application_id}")]      # (runs of earlier versions)
    for e in work.journal(application_id):      # the agent's runs on it
        if e["kind"] == "run":
            try:
                began.append(datetime.fromisoformat(str(e["at"])).astimezone(timezone.utc))
            except ValueError:
                began.append(None)
    for at in began:
        if before is None or at is None:
            return True
        a, b = (at if at.tzinfo else at.replace(tzinfo=timezone.utc)), (before if before.tzinfo else before.replace(tzinfo=timezone.utc))
        if a <= b + timedelta(minutes=5):
            return True
    return False


def reconcile() -> int:
    """Confirmations that were read while the program still took the application for unsent (it was filling the form
    again, or the run had ended without a confirmation page): the mail is right. Returns how many were corrected."""
    fixed = 0
    with db.session() as s:
        rows = [(m.application_id, m.message_id, m.received_at, m.summary) for m in
                s.query(MailEvent).filter(MailEvent.category == "confirmation", MailEvent.application_id.isnot(None)).order_by(MailEvent.id)]
    for app_id, mid, received, summary in rows:
        with db.session() as s:
            a = s.get(Application, app_id)
            if a is None or RANK.get(a.status, 0) >= RANK["confirmed"]:
                continue
            if a.status in PREPARING and a.submitted_at is None and not _was_filled(s, a.id, received):
                continue
            lifecycle.move(a, "confirmed", source="mail")
            a.submitted_at = a.submitted_at or received
            a.last_event = f"confirmation: {summary}"[:500]
            lifecycle.add_evidence(a, {"mail_id": mid})
            a.detail = a.detail or f"submitted {(received or datetime.now(timezone.utc)).date().isoformat()} (confirmed by the employer's e-mail)"
            fixed += 1
    return fixed


def _written(msg: Any) -> datetime:
    """When a message was written, comparable whether or not it says its time zone (none: the oldest)."""
    d = getattr(msg, "date", None)
    if d is None:
        return datetime.min
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def _known(message_id: str) -> bool:
    with db.session() as s:
        return s.query(MailEvent).filter_by(message_id=message_id).first() is not None


def track(days: int = 3, max_results: int = 80, *, quick: bool = False) -> dict[str, Any]:
    """Read recent mail, classify, link to applications, update statuses, notify.

    ``quick``: only what arrived since the last look (Gmail). When that cannot be told, nothing is read and the
    answer says so; the pass over the last ``days`` is the one that sets the starting point."""
    from . import mailbox

    try:
        if quick:
            msgs = mailbox.fetch_new(max_results, skip=_known)
            if msgs is None:
                return {"skipped": "no starting point yet: the next full pass sets one"}
        else:
            msgs = mailbox.fetch(datetime.now(timezone.utc) - timedelta(days=days), max_results, job_related=True, skip=_known)
    except mailbox.NotConfigured as e:
        raise MailNotConfigured(str(e)) from e
    new = updated = unmatched = 0
    # In the order they were written. A mailbox hands over the newest first; a cancellation followed by a new invitation
    # would then be read backwards - the invitation changes nothing, and the older cancellation takes the interview away.
    for msg in sorted(msgs, key=_written):
        mid = msg.id
        with db.session() as s:
            if s.query(MailEvent).filter_by(message_id=mid).first():
                continue
        frm, subj, received, body = msg.sender, msg.subject, msg.date, msg.body
        if ACCOUNT_MAIL.search(subj):
            t = {"category": "other", "company": "", "job_title": "", "summary": "verification e-mail (not shown)"}
        else:
            t = triage(subj, frm, body)
            if t["category"] == "confirmation" and t.get("received") is False:
                t = {**t, "category": "other"}       # about an application that was begun, or about an account: nothing was received yet
        app_id = match_application(t["company"], t["job_title"], received, f"{subj}\n{body}") if t["category"] != "other" else None
        changed, early, title = 0, False, ""
        with db.session() as s:
            # The mail and what it does to its application are one write. Written apart, a failure in between left the
            # mail "read" for good and the application where it was: an interview invitation on file, the application
            # still "submitted". Now a failure leaves neither, and the next pass reads the mail again.
            asks = {k: str(t.get(k) or "")[:300] for k in ("action", "due", "due_text") if t.get(k)}
            s.add(MailEvent(message_id=mid, sender=frm[:200], subject=subj[:300], received_at=received, category=t["category"], event=t.get("event") or "new",
                            application_id=app_id, company_guess=t["company"], summary=t["summary"], asks=asks or None))
            if app_id is not None and t["category"] != "other":
                changed, early, title = _record(app_id, t["category"], t["summary"], received, mid, t.get("event") or "new", session=s)
        new += 1
        if t["category"] == "other":
            continue
        if app_id is None:
            unmatched += 1
            ask_which(mid, subj, t["category"], t.get("event") or "new", t["summary"])
            if db.get_setting("mail.site_lookup") and candidates(t["company"]):
                # the e-mail does not say which application; the employer's site does - look there before the applicant has to
                from . import tasks

                tasks.enqueue("site_status", ref=f"mail:{mid}", payload={"message_id": mid}, priority=60)
            continue
        updated += changed
        if early:
            continue
        _asked(app_id, title, t["category"], t.get("event") or "new", t["summary"], asks, mid)
        _tell(lambda: notify.send("status_update", messages.mail_update(t["category"], title, t["summary"], event=t.get("event") or "new"), ref=f"application:{app_id}", tag=t["category"]))
    if quick:
        commit_history()        # every message of the batch is recorded: only now is it behind us
    return {"new_mail": new, "status_updates": updated, "unmatched": unmatched}
