"""Gmail (read-only): verification codes for drivers, and application tracking.

Scope is ``gmail.readonly``. Nothing is sent, labelled, or modified.
Verification codes/links are returned to drivers only (never to the LLM agent,
never logged). Tracking sends one e-mail body at a time to the small model.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from . import db, llm, messages, notify, secrets
from . import prompts
from .models import Application, Job, MailEvent

log = logging.getLogger("autoapply.mail")
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class MailNotConfigured(RuntimeError):
    pass


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


def status() -> dict[str, bool]:
    return {"client": secrets.has(secrets.GMAIL_CLIENT), "authorized": secrets.has(secrets.GMAIL_TOKEN)}


def _service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    tok = secrets.get(secrets.GMAIL_TOKEN)
    if not tok:
        raise MailNotConfigured("Gmail is not authorized (Settings > Gmail).")
    creds = Credentials.from_authorized_user_info(json.loads(tok), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        secrets.put(secrets.GMAIL_TOKEN, creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


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
    h = re.sub(r'<a[^>]+href="([^"]+)"[^>]*>', r" \1 ", h, flags=re.I)
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


# --- verification ----------------------------------------------------------------------

_CODE = re.compile(r"(?<![\w/=-])(\d{6,8}|[A-Z0-9]{6,8})(?![\w/=-])")
_LINK = re.compile(r"https?://[^\s\"'<>]+")
_LINK_HINT = re.compile(r"verif|confirm|activate|validate|token|registration", re.I)


def extract_verification(subject: str, body: str) -> str | None:
    """Rule-based extraction: a link that looks like a verification link, else a code near a keyword."""
    for m in _LINK.finditer(body):
        if _LINK_HINT.search(m.group(0)) and "unsubscribe" not in m.group(0).lower():
            return m.group(0).rstrip(").,")
    text = f"{subject}\n{body}"
    for kw in re.finditer(r"(verification|security|one[- ]time|temporary|confirmation|access|login|sign[- ]?in)\s*(code|pin|passcode|password)|\b(otp|passcode)\b", text, re.I):
        window = text[kw.end() : kw.end() + 200]
        for m in _CODE.finditer(window):
            if re.search(r"\d", m.group(1)):
                return m.group(1)
    m = re.search(r"\bcode\b[^\n]{0,40}?\b(\d{6,8})\b", text, re.I)
    return m.group(1) if m else None


_TWO_PART = {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.nz", "co.jp", "co.kr", "co.in", "com.cn", "com.hk", "com.sg", "com.br",
             "com.mx", "com.tw", "co.za", "com.tr"}


def site_domain(host: str) -> str:
    """The part of a host that names the site's owner: metacareers.com for www.metacareers.com, acme.co.uk for jobs.acme.co.uk.
    On a host shared by many employers the employer's own name is kept: ciena.wd5.myworkdayjobs.com stays whole."""
    host = (host or "").lower().split(":")[0].strip(".")
    parts = host.split(".")
    if len(parts) < 2 or re.fullmatch(r"[\d.]+", host):
        return ""
    if re.search(r"(myworkdayjobs|myworkdaysite|icims|greenhouse|lever|ashbyhq|smartrecruiters|bamboohr|taleo|oraclecloud|successfactors|jobvite|workable)\.", host):
        return host
    n = 3 if ".".join(parts[-2:]) in _TWO_PART else 2
    return ".".join(parts[-n:])


def link_refusal(url: str, site_host: str) -> str:
    """Why a link from an e-mail must not be opened by the program ('' when it may be).

    A confirmation link is opened only when it is plainly the site's own: the program is in the middle of signing up or in
    there, and the link leads to that same site over https. Anything else - another domain, a mail service's redirect, an
    address with a user name or a port in it, a bare IP - is left to the applicant: a link in a mail is the oldest way to
    send someone to a look-alike page, and this program types passwords."""
    from urllib.parse import urlparse

    try:
        u = urlparse(url)
    except ValueError:
        return "not an address"
    host = (u.hostname or "").lower()
    if u.scheme != "https":
        return "not https"
    if u.username or u.password or (u.port not in (None, 443)):
        return "has a user name or a port in it"
    if not host or re.fullmatch(r"[\d.]+", host) or host.startswith("xn--") or ".xn--" in host:
        return "not a plain host name"
    want = site_domain(site_host)
    if not want:
        return "the site is not known"
    if not (host == want or host.endswith("." + want)):
        return f"leads to {host}, not to {want}"
    return ""


def wait_for_verification(*, sender_hint: str = "", timeout: int = 180, since: datetime | None = None, site_host: str = "") -> str | None:
    """Poll for a fresh verification e-mail. Returns the code or link, or None on timeout. With ``site_host``, a link is
    returned only when link_refusal allows it; a mail whose only link is refused yields "refused: <why>"."""
    since = since or (datetime.now(timezone.utc) - timedelta(minutes=3))
    hint = re.sub(r"^(www|jobs|careers)\.", "", sender_hint).split(".")[0] if sender_hint else ""
    from . import mailbox

    deadline = time.time() + timeout
    refused = ""
    while time.time() < deadline:
        try:
            msgs = mailbox.fetch(since, 10)
        except mailbox.NotConfigured as e:
            raise MailNotConfigured(str(e)) from e
        for msg in msgs:
            frm, subj, body = msg.sender, msg.subject, msg.body
            if hint and hint.lower() not in (frm + subj + body[:2000]).lower():
                continue
            found = extract_verification(subj, body)
            if found is None and site_host and re.search(r"confirm|verif|activate", subj, re.I):
                # a confirmation mail whose link does not say so in its address: the site's own link if there is exactly one
                links = [m.group(0).rstrip(").,") for m in _LINK.finditer(body) if not re.search(r"unsubscribe|privacy|/help|support|terms|\.(png|jpe?g|gif|css)\b", m.group(0), re.I)]
                own = [u for u in links if not link_refusal(u, site_host)]
                if len(own) == 1:
                    found = own[0]
                elif links and not own:
                    refused = f"refused: {link_refusal(links[0], site_host)}"
                    continue
            if found is None and re.search(r"verif|code|confirm|password|passcode|otp|one[- ]time", subj, re.I):
                try:
                    out = llm.json(
                        f"Subject: {subj}\n\n{body[:6000]}\n\nExtract the verification code or verification link from this e-mail.",
                        llm.obj({"found": {"type": "boolean"}, "value": {"type": "string"}}),
                        small=True, max_tokens=500,
                    )
                    found = out["value"] if out["found"] else None
                except llm.LLMError:
                    found = None
            if found and str(found).startswith("http"):
                if str(found) not in body:      # a model read it out of the mail: it has to be in there word for word
                    found = None
                elif site_host and (why := link_refusal(str(found), site_host)):
                    refused = f"refused: {why}"
                    found = None
            if found:
                return found
        if refused:
            return refused
        time.sleep(8)
    return None


# --- tracking ----------------------------------------------------------------------------

CATEGORIES = ["confirmation", "rejection", "interview", "assessment", "info_request", "offer", "other"]
TRIAGE_SCHEMA = llm.obj(
    {
        "category": {"type": "string", "enum": CATEGORIES},
        "company": {"type": "string"},
        "job_title": {"type": "string"},
        "received": {"type": "boolean", "description": "true only if the e-mail states that a COMPLETED application was received or submitted. false for an application "
                                                         "that was started, saved or is in progress, a reminder to finish it, an account or profile that was created, "
                                                         "an e-mail address to confirm, a sign-in or security code."},
        "summary": {"type": "string", "description": "one sentence; include any deadline or date mentioned. Write this in Simplified Chinese (it is shown to the applicant); keep company names, product names and quoted form text in their original language."},
    }
)
STATUS_FOR = {"confirmation": "confirmed", "rejection": "rejected", "interview": "interview", "assessment": "assessment", "offer": "offer"}
PREPARING = ("recon", "needs_input", "draft_ready", "revising", "approved", "executing", "needs_human", "failed", "drifted")   # before any submission
RANK = {"submitted": 1, "confirmed": 2, "assessment": 3, "interview": 4, "offer": 5, "rejected": 6}
QUERY = '(application OR applying OR applied OR interview OR assessment OR candidate OR position OR "thank you for your interest" OR unfortunately) -category:promotions'


TRIAGE_RULES = """Classify this e-mail from the point of view of a job applicant. 'other' covers newsletters, job alerts, and anything
not about one of the applicant's own applications.

'confirmation' means one thing only: the employer says it has received a completed, submitted application. These are NOT confirmations,
they are 'other': "keep track of your application" / "you started an application" / "finish your application" (the application was begun,
not submitted); "your account / candidate profile was created"; "confirm your e-mail address"; sign-in and security codes.
Set `received` accordingly."""


def triage(subject: str, sender: str, body: str) -> dict[str, Any]:
    return llm.json(
        f"From: {sender}\nSubject: {subject}\n\n{body[:8000]}",
        TRIAGE_SCHEMA, small=True, max_tokens=1000, system=prompts.get("mail_triage"),
    )


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _same_company(c: str, jc: str) -> bool:
    return bool(c and jc and (c in jc or jc in c or set(c.split()) & set(jc.split()) - {"inc", "ltd", "corp", "the", "technologies", "group"}))


def candidates(company: str) -> list[int]:
    """The applications an e-mail from this employer can be about: those at the employer that were sent (an e-mail about
    an application is not about one that is still a draft), the latest first."""
    c = _norm(company)
    with db.session() as s:
        rows = [(a.submitted_at or a.created_at, a.id) for a in s.query(Application).join(Job).all()
                if _same_company(c, _norm(a.job.company)) and (a.submitted_at is not None or RANK.get(a.status, 0) >= 1)]
    return [i for _, i in sorted(rows, reverse=True)]


def link(message_id: str, application_ids: list[int], *, by: str = "user") -> int:
    """This e-mail is about these applications (said by the applicant on the card, or found on the employer's site).
    Each gets what the e-mail says - the same as if the e-mail had named it. Returns how many changed state."""
    with db.session() as s:
        me = s.query(MailEvent).filter_by(message_id=message_id).first()
        if me is None or not application_ids:
            return 0
        me.application_id = int(application_ids[0])
        category, summary, received = me.category, me.summary, me.received_at
    changed = 0
    for app_id in application_ids:
        updated, early, title = _record(int(app_id), category, summary, received, message_id)
        changed += updated
        if not early:
            notify.send("status_update", messages.mail_update(category, title, summary), ref=f"application:{app_id}", tag=category)
    notify.close_todos("mail_unmatched", f"mail:{message_id}")
    log.info("mail %s linked to application(s) %s (%s)", message_id[:12], application_ids, by)
    return changed


def _record(app_id: int, category: str, summary: str, received: datetime | None, mid: str) -> tuple[int, bool, str]:
    """Put what an e-mail says on its application. Returns (1 if the state changed, was it too early to believe, title)."""
    new_status, updated = STATUS_FOR.get(category), 0
    with db.session() as s:
        a = s.get(Application, app_id)
        title = f"{a.job.company} · {a.job.title}"
        a.last_event = f"{category}: {summary}"[:500]
        # A confirmation confirms a submission. An application this program is still preparing (no submission by it, none
        # reported by the user) is not turned into "confirmed" by an e-mail: sites send "we have your application" style
        # mail when an application is merely started. The mail is kept on the record and shown; the status stays.
        early = category == "confirmation" and a.status in PREPARING and a.submitted_at is None and not _was_filled(s, a.id, received)
        if early:
            a.last_event = f"收到一封像确认信的邮件，但这份申请程序还没有提交过，状态没有改。如果你已经自己提交了，请在岗位页点“我已经提交了”。邮件：{summary}"[:500]
        elif new_status and RANK.get(new_status, 0) > RANK.get(a.status, 0):
            a.status = new_status
            if a.submitted_at is None:      # the program had not seen the submission; the employer has
                a.submitted_at = received
                a.detail = a.detail or f"submitted {(received or datetime.now(timezone.utc)).date().isoformat()} (confirmed by the employer's e-mail)"
            updated = 1
        if category == "confirmation" and not early:
            a.evidence = {**(a.evidence or {}), "mail_id": mid}
    return updated, early, title


def match_application(company: str, title: str, received: datetime | None) -> int | None:
    """Best application for an e-mail: company must match; title breaks ties."""
    c = _norm(company)
    if not c:
        return None
    with db.session() as s:
        cands = []
        for a in s.query(Application).join(Job).all():
            jc = _norm(a.job.company)
            if not _same_company(c, jc):
                continue
            t, jt = set(_norm(title).split()), set(_norm(a.job.title).split())
            overlap = len(t & jt) / max(1, len(t | jt))
            cands.append((overlap, a.submitted_at or a.created_at, a.id, RANK.get(a.status, 0)))
        if not cands:
            return None
        cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
        if len(cands) > 1 and cands[0][0] == cands[1][0] == 0:
            # Several applications at this company and no title to tell them apart: a follow-up
            # belongs to the one that is furthest along, if exactly one is.
            live = [x for x in cands if 2 < x[3] < 6]
            return live[0][2] if len(live) == 1 else None
        return cands[0][2]


def _was_filled(s: Any, application_id: int, before: datetime | None) -> bool:
    """Has the program filled this application's form (so that the applicant had it in front of them to submit) before
    this time? Then a confirmation is what it says, whatever the program believes about the run: a window that closed, a
    confirmation page that was not recognised."""
    from .models import Run

    for r in s.query(Run).filter_by(kind="execute", ref=f"application:{application_id}"):
        at = getattr(r, "created_at", None)
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
            a.status = "confirmed"
            a.submitted_at = a.submitted_at or received
            a.last_event = f"confirmation: {summary}"[:500]
            a.evidence = {**(a.evidence or {}), "mail_id": mid}
            a.detail = a.detail or f"submitted {(received or datetime.now(timezone.utc)).date().isoformat()} (confirmed by the employer's e-mail)"
            fixed += 1
    return fixed


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
    for msg in msgs:
        mid = msg.id
        with db.session() as s:
            if s.query(MailEvent).filter_by(message_id=mid).first():
                continue
        frm, subj, received, body = msg.sender, msg.subject, msg.date, msg.body
        if re.search(r"(security|verification|one[- ]time|temporary|access|login)\s*(code|pin|passcode|password)|\b(otp|passcode)\b|verify your (e-?mail|account)", subj, re.I):
            # Codes are used by the sign-in / submit step only; they are never summarised, stored or notified.
            t = {"category": "other", "company": "", "job_title": "", "summary": "verification e-mail (not shown)"}
        else:
            t = triage(subj, frm, body)
            if t["category"] == "confirmation" and t.get("received") is False:
                t = {**t, "category": "other"}       # about an application that was begun, or about an account: nothing was received yet
        app_id = match_application(t["company"], t["job_title"], received) if t["category"] != "other" else None
        with db.session() as s:
            s.add(MailEvent(message_id=mid, sender=frm[:200], subject=subj[:300], received_at=received, category=t["category"],
                            application_id=app_id, company_guess=t["company"], summary=t["summary"]))
        new += 1
        if t["category"] == "other":
            continue
        if app_id is None:
            unmatched += 1
            notify.add_todo("mail_unmatched", subj[:80], body=f"{messages.MAIL.get(t['category'], ('', t['category']))[1]}：{t['summary']}", ref=f"mail:{mid}", payload={"message_id": mid, "category": t["category"]})
            if db.get_setting("mail.site_lookup") and candidates(t["company"]):
                # the e-mail does not say which application; the employer's site does - look there before the applicant has to
                from . import tasks

                tasks.enqueue("site_status", ref=f"mail:{mid}", payload={"message_id": mid}, priority=60)
            continue
        changed, early, title = _record(app_id, t["category"], t["summary"], received, mid)
        updated += changed
        if early:
            continue
        notify.send("status_update", messages.mail_update(t["category"], title, t["summary"]), ref=f"application:{app_id}", tag=t["category"])
    if quick:
        commit_history()        # every message of the batch is recorded: only now is it behind us
    return {"new_mail": new, "status_updates": updated, "unmatched": unmatched}
