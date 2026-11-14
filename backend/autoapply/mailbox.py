"""Reading the user's mailbox, read-only, whichever provider it is.

Two ways in:
* ``gmail_api`` - Google's API with the user's own OAuth client (the original way; narrowest permission);
* ``imap``      - any mailbox that offers IMAP with an app password / authorisation code: Gmail, QQ, 163 / 126,
  iCloud, Yahoo, Fastmail, Zoho, or a server the user names.

Both return the same thing: recent messages as ``Message``. Mail is never modified, moved or marked as read
(IMAP folders are opened read-only and bodies are fetched with PEEK).
"""

from __future__ import annotations

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
    "gmail": {"name": "Gmail（应用专用密码）", "host": "imap.gmail.com", "port": 993,
              "how": "需要先开启两步验证，然后在 myaccount.google.com/apppasswords 生成一个 16 位的“应用专用密码”，填在下面。比 OAuth 方式省事，但这个密码能读全部邮件。"},
    "qq": {"name": "QQ 邮箱", "host": "imap.qq.com", "port": 993, "how": "在 QQ 邮箱网页版：设置 → 账号 → 开启 IMAP/SMTP 服务，生成“授权码”，填在下面（不是 QQ 密码）。"},
    "163": {"name": "网易 163 邮箱", "host": "imap.163.com", "port": 993, "how": "在 163 邮箱网页版：设置 → POP3/SMTP/IMAP → 开启 IMAP，生成“授权密码”，填在下面。"},
    "126": {"name": "网易 126 邮箱", "host": "imap.126.com", "port": 993, "how": "在 126 邮箱网页版：设置 → POP3/SMTP/IMAP → 开启 IMAP，生成“授权密码”，填在下面。"},
    "icloud": {"name": "iCloud 邮箱", "host": "imap.mail.me.com", "port": 993, "how": "在 account.apple.com → 登录与安全 → App 专用密码 里生成一个，填在下面。用户名是完整的邮箱地址。"},
    "yahoo": {"name": "Yahoo 邮箱", "host": "imap.mail.yahoo.com", "port": 993, "how": "在 Yahoo 账户安全设置里生成“应用密码”，填在下面。"},
    "fastmail": {"name": "Fastmail", "host": "imap.fastmail.com", "port": 993, "how": "在 Settings → Privacy & Security → App passwords 里生成一个只读（IMAP）的应用密码。"},
    "zoho": {"name": "Zoho Mail", "host": "imap.zoho.com", "port": 993, "how": "在 Zoho 邮箱设置里开启 IMAP；开了两步验证的话需要生成应用专用密码。"},
    "outlook": {"name": "Outlook / Hotmail / Microsoft 365（微软授权）", "host": "outlook.office365.com", "port": 993, "oauth": True,
                "how": "微软不接受密码，需要授权。要先有一个“应用（客户端）ID”：在 entra.microsoft.com → 应用注册 新建一个应用（账户类型选“任何组织目录和个人 Microsoft 帐户”），"
                       "在“身份验证”里把“允许公共客户端流”设为“是”，在“API 权限”里添加委托权限 IMAP.AccessAsUser.All。把应用 ID 填在下面，再点“授权”。"},
    "custom": {"name": "其他邮箱（自己填服务器）", "host": "", "port": 993, "how": "填邮箱服务商提供的 IMAP 服务器地址和端口（一般是 993，SSL）。学校和公司邮箱是否允许 IMAP 取决于管理员。"},
}

JOB_WORDS = re.compile(r"application|applying|applied|interview|assessment|candidate|position|thank you for your interest|unfortunately|offer|recruit|hiring|"
                       r"申请|面试|笔试|测评|录用|offer|投递|简历|应聘", re.I)


@dataclass
class Message:
    id: str
    sender: str
    subject: str
    body: str
    date: datetime | None


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
            raise NotConfigured("请填写 Outlook 邮箱地址。")
        try:
            token = outlook.access_token()
        except outlook.NotReady as e:
            raise NotConfigured(str(e)) from e
        try:
            m = imaplib.IMAP4_SSL(outlook.HOST, outlook.PORT, timeout=30)
            m.authenticate("XOAUTH2", lambda _challenge: outlook.xoauth2(c["user"], token))
        except imaplib.IMAP4.error as e:
            raise NotConfigured(f"Outlook 拒绝了这次登录：{str(e)[:160]}。检查邮箱地址和应用的 IMAP 权限。") from e
        except Exception as e:  # noqa: BLE001
            raise NotConfigured(f"连不上 Outlook 的邮件服务器（{type(e).__name__}）。") from e
        return m
    pw = password or secrets.get(IMAP_PASSWORD)
    if not (c["host"] and c["user"] and pw):
        raise NotConfigured("邮箱还没有设置（设置 → 通知与邮箱）。")
    try:
        m = imaplib.IMAP4_SSL(c["host"], c["port"], timeout=30)
    except Exception as e:  # noqa: BLE001
        raise NotConfigured(f"连不上邮箱服务器 {c['host']}:{c['port']}（{type(e).__name__}）。") from e
    try:
        m.login(c["user"], pw)
    except imaplib.IMAP4.error as e:
        raise NotConfigured(f"邮箱拒绝登录：{str(e)[:120]}。检查用户名，以及填的是不是授权码 / 应用专用密码。") from e
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
            raise NotConfigured("邮箱不允许读取收件箱。")
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
            out.append(Message(id=mid[:200], sender=_decode(msg.get("From")), subject=_decode(msg.get("Subject")), body=_text_of(msg), date=when))
        return out
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass


def c_user(cfg: dict[str, Any] | None) -> str:
    return (cfg or imap_config())["user"]


# --- the one entry point -----------------------------------------------------------------------


def fetch(since: datetime, limit: int = 50, *, job_related: bool = False) -> list[Message]:
    """Messages received after ``since``, newest first. ``job_related`` keeps only mail that looks like it is about an application."""
    if kind() == "imap":
        msgs = _imap_fetch(since, limit * 3 if job_related else limit)
        if job_related:
            msgs = [x for x in msgs if JOB_WORDS.search(x.subject + " " + x.body[:1500])][:limit]
        return msgs
    from . import mail

    days = max(1, (datetime.now(timezone.utc) - since).days + 1)
    q = f"newer_than:{days}d after:{int(since.timestamp())}" + (f" {mail.QUERY}" if job_related else "")
    out = []
    for g in mail._list(q, limit):
        try:
            when = parsedate_to_datetime(mail._hdr(g, "Date"))
        except Exception:  # noqa: BLE001
            when = None
        out.append(Message(id=g["id"], sender=mail._hdr(g, "From"), subject=mail._hdr(g, "Subject"), body=mail._body(g["payload"]), date=when))
    return out


def test(cfg: dict[str, Any] | None = None, password: str | None = None) -> dict[str, Any]:
    """Can the mailbox be read? Returns how many messages arrived in the last three days (nothing about their content)."""
    since = datetime.now(timezone.utc) - timedelta(days=3)
    if cfg is not None or kind() == "imap":
        n = len(_imap_fetch(since, 50, cfg, password))
    else:
        n = len(fetch(since, 50))
    return {"ok": True, "recent": n}
