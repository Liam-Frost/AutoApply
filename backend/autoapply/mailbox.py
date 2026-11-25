"""Reading the user's mailbox, read-only, whichever provider it is.

Two ways in:
* ``gmail_api`` - Google's API with the user's own OAuth client (the original way; narrowest permission);
* ``imap``      - any mailbox that offers IMAP with an app password / authorisation code: Gmail, QQ, 163 / 126,
  iCloud, Yahoo, Fastmail, Zoho, or a server the user names.

Both return the same thing: recent messages as ``Message``. Mail is never modified, moved or marked as read
(IMAP folders are opened read-only and bodies are fetched with PEEK).
"""

from __future__ import annotations

from .say import say as T

import email
import imaplib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from typing import Any

from . import db, secrets

IMAP_PASSWORD = "imap_password"

# Outlook.com / Hotmail / Microsoft 365 are not here: Microsoft no longer accepts a password over IMAP, only OAuth.
PRESETS: dict[str, dict[str, Any]] = {
    "gmail": {"name": T("server.mailbox.gmailAppPassword"), "host": "imap.gmail.com", "port": 993,
              "how": T("server.mailbox.turnOnStepVerification")},
    "qq": {"name": T("server.mailbox.qqMail"), "host": "imap.qq.com", "port": 993, "how": T("server.mailbox.inQqMailOn")},
    "163": {"name": T("server.mailbox.neteaseMail"), "host": "imap.163.com", "port": 993, "how": T("server.mailbox.inMailOnThe")},
    "126": {"name": T("server.mailbox.neteaseMail2"), "host": "imap.126.com", "port": 993, "how": T("server.mailbox.inMailOnThe2")},
    "icloud": {"name": T("server.mailbox.icloudMail"), "host": "imap.mail.me.com", "port": 993, "how": T("server.mailbox.generateOneAtAccount")},
    "yahoo": {"name": T("server.mailbox.yahooMail"), "host": "imap.mail.yahoo.com", "port": 993, "how": T("server.mailbox.createAnAppPassword")},
    "fastmail": {"name": "Fastmail", "host": "imap.fastmail.com", "port": 993, "how": T("server.mailbox.generateAReadOnly")},
    "zoho": {"name": "Zoho Mail", "host": "imap.zoho.com", "port": 993, "how": T("server.mailbox.turnOnImapIn")},
    "outlook": {"name": T("server.mailbox.outlookHotmailMicrosoftMicrosoft"), "host": "outlook.office365.com", "port": 993, "oauth": True,
                "how": T("server.mailbox.outlookHow")},
    "custom": {"name": T("server.mailbox.otherEmailEnterServer"), "host": "", "port": 993, "how": T("server.mailbox.enterTheImapServer")},
}

JOB_WORDS = re.compile(r"application|applying|applied|interview|assessment|candidate|position|thank you for your interest|unfortunately|offer|recruit|hiring|"
                       r"申请|面试|笔试|测评|录用|offer|投递|简历|应聘", re.I)


def _relevant(x: Any) -> bool:
    """Is this message worth reading as one about an application? It uses the words such mail uses - or it comes from
    an employer the applicant has applied to, in whatever words and language it is written."""
    if JOB_WORDS.search(x.subject + " " + x.body[:1500]):
        return True
    sender = re.sub(r"[^a-z0-9]+", " ", str(x.sender or "").lower())
    return any(name in sender for name in _employers())


def _employers() -> list[str]:
    """The names of the employers with an application that has gone out, as they would appear in a sender (lower case,
    words only; names too short to be told from an ordinary word are left out)."""
    from .models import SENT, Application, Job

    with db.session() as s:
        names = {re.sub(r"[^a-z0-9]+", " ", (c or "").lower()).strip() for (c,) in s.query(Job.company).join(Application).filter(Application.status.in_(SENT))}
    return [n for n in names if len(n) >= 4]


@dataclass
class Message:
    id: str
    sender: str
    subject: str
    body: str
    date: datetime | None
    thread: str = ""        # the conversation it is in: Gmail's own thread id; over IMAP, the first Message-ID of its References
    mine: bool = False      # the mailbox says it was sent from it (Gmail's SENT / DRAFT labels)


# --- what the applicant sent ---------------------------------------------------------------------------------------------
# A mail the applicant sent - by hand, or the program's reply from their mailbox - is not news about an application. A
# search over the whole mailbox finds the applicant's own reply too ("Re: ... Job Application"): it was read as if the
# employer had written it, put down as "the employer asks for more" and answered with a draft (2026-11-23).

def address_of(sender: str) -> str:
    """The e-mail address in a From line ("Name <a@b.c>" -> "a@b.c"), lower case."""
    from email.utils import parseaddr

    return parseaddr(str(sender or ""))[1].strip().lower()


def own_addresses() -> set[str]:
    """The applicant's own addresses: the mailbox's (Gmail's, as it said when last asked; the IMAP or Outlook login),
    the address applications are made with, and every address the program has sent from."""
    from .models import Outgoing

    out = {str(db.get_setting("mail.address") or ""), str(db.get_setting("account.email") or "")}
    for key in ("mail.imap", "mail.outlook"):
        out.add(str((db.get_setting(key) or {}).get("user") or ""))
    with db.session() as s:
        out |= {f for (f,) in s.query(Outgoing.sent_from).filter(Outgoing.sent_from != "").distinct()}
    return {a.strip().lower() for a in out if "@" in a}


def sent_ids() -> set[str]:
    """The mailbox's ids of the mails the program sent."""
    from .models import Outgoing

    with db.session() as s:
        return {m for (m,) in s.query(Outgoing.message_id).filter(Outgoing.message_id != "")}


def from_applicant(x: Any, mine: set[str] | None = None, sent: set[str] | None = None) -> bool:
    """Did the applicant send this mail (not receive it)?"""
    mine = own_addresses() if mine is None else mine
    sent = sent_ids() if sent is None else sent
    return bool(getattr(x, "mine", False)) or x.id in sent or address_of(x.sender) in mine


def _received(msgs: list[Message]) -> list[Message]:
    """The mails the applicant received, of these."""
    mine, sent = own_addresses(), sent_ids()
    return [x for x in msgs if not from_applicant(x, mine, sent)]


class NotConfigured(RuntimeError):
    pass


def kind() -> str:
    return "imap" if db.get_setting("mail.kind") == "imap" else "gmail_api"


def imap_config() -> dict[str, Any]:
    c = dict(db.get_setting("mail.imap") or {})
    p = PRESETS.get(c.get("preset") or "", {})
    return {"preset": c.get("preset") or "", "host": (c.get("host") or p.get("host") or "").strip(), "port": int(c.get("port") or p.get("port") or 993), "user": (c.get("user") or "").strip()}


def status() -> dict[str, Any]:
    from . import mail

    g = mail.status()
    c = imap_config()
    from . import outlook

    ready = bool(c["user"] and outlook.status()["authorized"]) if c["preset"] == "outlook" else bool(c["host"] and c["user"] and secrets.has(IMAP_PASSWORD))
    return {**g, "kind": kind(), "outlook": outlook.status(), "imap": {**c, "has_password": secrets.has(IMAP_PASSWORD), "ready": ready}, "ready": ready if kind() == "imap" else bool(g.get("authorized"))}


# --- IMAP --------------------------------------------------------------------------------------


def _decode(v: str | None) -> str:
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:  # noqa: BLE001
        return v or ""


def _text_of(msg: email.message.Message) -> str:
    plain, html = "", ""
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() != "text" or "attachment" in str(part.get("Content-Disposition") or ""):
            continue
        try:
            txt = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", errors="replace")
        except LookupError:
            txt = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
        if part.get_content_subtype() == "plain":
            plain += txt
        elif part.get_content_subtype() == "html":
            html += txt
    if plain.strip():
        return plain
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r'(?i)<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r"\2 \1 ", html)  # keep link targets: verification links live there
    return re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&nbsp;", " ").replace("&amp;", "&")


def _connect(cfg: dict[str, Any] | None = None, password: str | None = None) -> imaplib.IMAP4_SSL:
    c = cfg or imap_config()
    if c.get("preset") == "outlook" or c["host"] == "outlook.office365.com":
        from . import outlook

        if not c["user"]:
            raise NotConfigured(T("server.mailbox.enterYourOutlookEmail"))
        try:
            token = outlook.access_token()
        except outlook.NotReady as e:
            raise NotConfigured(str(e)) from e
        try:
            m = imaplib.IMAP4_SSL(outlook.HOST, outlook.PORT, timeout=30)
            m.authenticate("XOAUTH2", lambda _challenge: outlook.xoauth2(c["user"], token))
        except imaplib.IMAP4.error as e:
            raise NotConfigured(T("server.mailbox.outlookRejectedThisSign", p0=str(e)[:160])) from e
        except Exception as e:  # noqa: BLE001
            raise NotConfigured(T("server.mailbox.cantConnectToOutlooks", p0=type(e).__name__)) from e
        return m
    pw = password or secrets.get(IMAP_PASSWORD)
    if not (c["host"] and c["user"] and pw):
        raise NotConfigured(T("server.mailbox.emailIsntSetUp"))
    try:
        m = imaplib.IMAP4_SSL(c["host"], c["port"], timeout=30)
    except Exception as e:  # noqa: BLE001
        raise NotConfigured(T("server.mailbox.cantConnectToMail", p0=c['host'], p1=c['port'], p2=type(e).__name__)) from e
    try:
        m.login(c["user"], pw)
    except imaplib.IMAP4.error as e:
        raise NotConfigured(T("server.mailbox.theMailServerRejected", p0=str(e)[:120])) from e
    if re.search(r"\.(163|126|yeah)\.(com|net)$", c["host"]):  # NetEase refuses SELECT ("Unsafe Login") until the client identifies itself
        imaplib.Commands["ID"] = ("AUTH",)
        try:
            m._simple_command("ID", '("name" "AutoApply" "version" "1.0")')
        except Exception:  # noqa: BLE001
            pass
    return m


def _imap_fetch(since: datetime, limit: int, cfg: dict[str, Any] | None = None, password: str | None = None) -> list[Message]:
    m = _connect(cfg, password)
    try:
        typ, _ = m.select("INBOX", readonly=True)
        if typ != "OK":
            raise NotConfigured(T("server.mailbox.thisMailboxDoesntAllow"))
        typ, data = m.search(None, "SINCE", since.strftime("%d-%b-%Y"))
        ids = (data[0] or b"").split()[-limit:] if typ == "OK" else []
        out: list[Message] = []
        for num in reversed(ids):
            typ, parts = m.fetch(num, "(BODY.PEEK[])")
            raw = next((p[1] for p in parts or [] if isinstance(p, tuple)), None)
            if typ != "OK" or raw is None:
                continue
            msg = email.message_from_bytes(raw)
            try:
                when = parsedate_to_datetime(msg.get("Date"))
                when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
            except Exception:  # noqa: BLE001
                when = None
            if when is not None and when < since - timedelta(minutes=5):  # SINCE is by day; cut to the minute here
                continue
            mid = (msg.get("Message-ID") or "").strip() or f"imap:{c_user(cfg)}:{num.decode()}"
            refs = (msg.get("References") or "").split() or (msg.get("In-Reply-To") or "").split()
            out.append(Message(id=mid[:200], sender=_decode(msg.get("From")), subject=_decode(msg.get("Subject")), body=_text_of(msg), date=when,
                               thread=(refs[0] if refs else mid).strip()[:200]))
        return out
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass


def c_user(cfg: dict[str, Any] | None) -> str:
    return (cfg or imap_config())["user"]


# --- the one entry point -----------------------------------------------------------------------


def _gmail_message(g: dict[str, Any]) -> Message:
    from . import mail

    try:
        when = parsedate_to_datetime(mail._hdr(g, "Date"))
    except Exception:  # noqa: BLE001
        when = None
    return Message(id=g["id"], sender=mail._hdr(g, "From"), subject=mail._hdr(g, "Subject"), body=mail._body(g["payload"]), date=when, thread=str(g.get("threadId") or ""),
                   mine=bool({"SENT", "DRAFT"} & set(g.get("labelIds") or [])))


def incremental() -> bool:
    """Can this mailbox be asked for just what is new? (Gmail through its API.)"""
    return (db.get_setting("mail.kind") or "gmail_api") == "gmail_api"


def fetch_new(limit: int = 50, *, skip: Any = None) -> list[Message] | None:
    """What arrived since the last look and looks like it is about an application. None when that cannot be told
    (another kind of mailbox, no earlier look, too long ago): read the last days with fetch() instead. The look is
    only over once the caller has dealt with the messages and says so (mail.commit_history)."""
    if not incremental():
        return None
    from . import mail

    added = mail.added_since_last(limit, skip=skip)
    if added is None:
        return None
    msgs = [_gmail_message(g) for g in added]
    return [x for x in _received(msgs) if _relevant(x)]


def fetch(since: datetime, limit: int = 50, *, job_related: bool = False, skip: Any = None, until: datetime | None = None) -> list[Message]:
    """Messages received after ``since`` (and before ``until``), newest first. ``job_related`` keeps only mail that looks
    like it is about an application. ``skip(id)``: messages already known, which need not be fetched again (Gmail)."""
    def before(msgs: list[Message]) -> list[Message]:
        if until is None:
            return msgs
        end = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
        return [x for x in msgs if x.date is None or (x.date if x.date.tzinfo else x.date.replace(tzinfo=timezone.utc)) < end]

    if kind() == "imap":
        msgs = before(_received(_imap_fetch(since, limit * 3 if job_related else limit)))
        if job_related:
            msgs = [x for x in msgs if _relevant(x)][:limit]
        return msgs
    from . import mail

    days = max(1, (datetime.now(timezone.utc) - since).days + 1)
    # (a search covers the whole mailbox: what was sent from it and the drafts in it are left out here already)
    q = (f"newer_than:{days}d after:{int(since.timestamp())}" + (f" before:{int(until.timestamp())}" if until else "") + " -in:sent -in:drafts"
         + (f" {mail.QUERY}" if job_related else ""))
    mail.remember_address()
    out = before(_received([_gmail_message(g) for g in mail._list(q, limit, skip=skip)]))
    if not mail.db.get_setting(mail.HISTORY):
        mail.mark_history()        # from here on, "what is new" can be asked (fetch_new)
    return out


def test(cfg: dict[str, Any] | None = None, password: str | None = None) -> dict[str, Any]:
    """Can the mailbox be read? Returns how many messages arrived in the last three days (nothing about their content)."""
    since = datetime.now(timezone.utc) - timedelta(days=3)
    if cfg is not None or kind() == "imap":
        n = len(_imap_fetch(since, 50, cfg, password))
    else:
        n = len(fetch(since, 50))
    return {"ok": True, "recent": n}
