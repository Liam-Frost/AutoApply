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


def _list(query: str, max_results: int = 50) -> list[dict[str, Any]]:
    svc = _service()
    ids = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute().get("messages", [])
    return [svc.users().messages().get(userId="me", id=m["id"], format="full").execute() for m in ids]


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


def wait_for_verification(*, sender_hint: str = "", timeout: int = 180, since: datetime | None = None) -> str | None:
    """Poll for a fresh verification e-mail. Returns the code or link, or None on timeout."""
    since = since or (datetime.now(timezone.utc) - timedelta(minutes=3))
    hint = re.sub(r"^(www|jobs|careers)\.", "", sender_hint).split(".")[0] if sender_hint else ""
    from . import mailbox

    deadline = time.time() + timeout
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
            if found:
                return found
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


def match_application(company: str, title: str, received: datetime | None) -> int | None:
    """Best application for an e-mail: company must match; title breaks ties."""
    c = _norm(company)
    if not c:
        return None
    with db.session() as s:
        cands = []
        for a in s.query(Application).join(Job).all():
            jc = _norm(a.job.company)
            if not jc or not (c in jc or jc in c or set(c.split()) & set(jc.split()) - {"inc", "ltd", "corp", "the", "technologies", "group"}):
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


def track(days: int = 3, max_results: int = 80) -> dict[str, int]:
    """Read recent mail, classify, link to applications, update statuses, notify."""
    from . import mailbox

    try:
        msgs = mailbox.fetch(datetime.now(timezone.utc) - timedelta(days=days), max_results, job_related=True)
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
            continue
        new_status = STATUS_FOR.get(t["category"])
        with db.session() as s:
            a = s.get(Application, app_id)
            title = f"{a.job.company} · {a.job.title}"
            a.last_event = f"{t['category']}: {t['summary']}"[:500]
            # A confirmation confirms a submission. An application this program is still preparing (no submission by it, none
            # reported by the user) is not turned into "confirmed" by an e-mail: sites send "we have your application" style
            # mail when an application is merely started. The mail is kept on the record and shown; the status stays.
            early = t["category"] == "confirmation" and a.status in PREPARING and a.submitted_at is None
            if early:
                a.last_event = f"收到一封像确认信的邮件，但这份申请程序还没有提交过，状态没有改。如果你已经自己提交了，请在岗位页点“我已经提交了”。邮件：{t['summary']}"[:500]
            elif new_status and RANK.get(new_status, 0) > RANK.get(a.status, 0):
                a.status = new_status
                updated += 1
            if t["category"] == "confirmation" and not early:
                a.evidence = {**(a.evidence or {}), "mail_id": mid}
        if early:
            continue
        notify.send("status_update", messages.mail_update(t["category"], title, t["summary"]), ref=f"application:{app_id}", tag=t["category"])
    return {"new_mail": new, "status_updates": updated, "unmatched": unmatched}
