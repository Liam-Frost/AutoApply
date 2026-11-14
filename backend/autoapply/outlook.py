"""Outlook.com / Hotmail / Microsoft 365 mailboxes, read-only.

Microsoft no longer accepts a password over IMAP; it wants OAuth. This is the standard "device code" sign-in:
the program shows a short code, the user enters it on Microsoft's own page and approves read access to mail,
and Microsoft hands back a token that works for IMAP (XOAUTH2). The program never sees the password.

It needs an application (client) ID. Microsoft issues those to whoever registers an app, free of charge, at
https://entra.microsoft.com -> App registrations: "Accounts in any organizational directory and personal Microsoft
accounts", then Authentication -> "Allow public client flows" = Yes, and API permissions -> Office 365 Exchange
Online / Microsoft Graph delegated ``IMAP.AccessAsUser.All``. The user's own ID is used, exactly like the Gmail
option uses the user's own Google OAuth client.

STATUS: written against Microsoft's documented endpoints; not run with a real application ID or mailbox.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx

from . import db, secrets

TOKEN = "outlook_oauth_token"
AUTHORITY = "https://login.microsoftonline.com/common/oauth2/v2.0"
SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
HOST, PORT = "outlook.office365.com", 993
_flow: dict[str, Any] = {"state": "", "code": "", "url": "", "error": ""}


class NotReady(RuntimeError):
    pass


def client_id() -> str:
    return str((db.get_setting("mail.outlook") or {}).get("client_id") or "").strip()


def status() -> dict[str, Any]:
    return {"client_id": bool(client_id()), "authorized": secrets.has(TOKEN), "user": str((db.get_setting("mail.outlook") or {}).get("user") or ""), "flow": dict(_flow)}


def start() -> dict[str, Any]:
    """Begin the device-code sign-in. Returns the code and the page to enter it on; the rest happens in the background."""
    cid = client_id()
    if not cid:
        raise NotReady("先填写应用（客户端）ID。")
    try:
        r = httpx.post(f"{AUTHORITY}/devicecode", data={"client_id": cid, "scope": SCOPE}, timeout=30)
    except httpx.HTTPError as e:
        raise NotReady(f"连不上微软的登录服务（{type(e).__name__}）。") from e
    d = r.json()
    if r.status_code != 200:
        raise NotReady(f"微软拒绝了这个应用 ID：{d.get('error_description', d.get('error', r.status_code))[:240]}")
    _flow.update(state="waiting", code=d["user_code"], url=d.get("verification_uri") or d.get("verification_url", ""), error="")

    def poll() -> None:
        deadline, every = time.time() + int(d.get("expires_in", 900)), int(d.get("interval", 5))
        while time.time() < deadline:
            time.sleep(every)
            try:
                t = httpx.post(f"{AUTHORITY}/token", data={"grant_type": "urn:ietf:params:oauth:grant-type:device_code", "client_id": cid, "device_code": d["device_code"]}, timeout=30).json()
            except httpx.HTTPError:
                continue
            if "access_token" in t:
                _save(t)
                _flow.update(state="done", code="", error="")
                return
            if t.get("error") == "slow_down":
                every += 5
            elif t.get("error") != "authorization_pending":
                _flow.update(state="failed", error=str(t.get("error_description") or t.get("error"))[:240])
                return
        _flow.update(state="failed", error="验证码过期了，请重新开始。")

    threading.Thread(target=poll, daemon=True, name="outlook-oauth").start()
    return {"user_code": _flow["code"], "verification_uri": _flow["url"]}


def _save(t: dict[str, Any]) -> None:
    old = json.loads(secrets.get(TOKEN) or "{}")
    secrets.put(TOKEN, json.dumps({"access_token": t["access_token"], "refresh_token": t.get("refresh_token") or old.get("refresh_token", ""),
                                   "expires_at": time.time() + int(t.get("expires_in", 3600)) - 120}))


def access_token() -> str:
    raw = secrets.get(TOKEN)
    if not raw:
        raise NotReady("Outlook 邮箱还没有授权（设置 → 通知与邮箱）。")
    t = json.loads(raw)
    if t.get("expires_at", 0) > time.time():
        return t["access_token"]
    if not t.get("refresh_token"):
        raise NotReady("Outlook 的授权过期了，请重新授权。")
    try:
        r = httpx.post(f"{AUTHORITY}/token", data={"grant_type": "refresh_token", "client_id": client_id(), "refresh_token": t["refresh_token"], "scope": SCOPE}, timeout=30)
    except httpx.HTTPError as e:
        raise NotReady(f"连不上微软的登录服务（{type(e).__name__}）。") from e
    d = r.json()
    if "access_token" not in d:
        raise NotReady(f"Outlook 的授权失效了，请重新授权：{str(d.get('error_description') or d.get('error'))[:200]}")
    _save(d)
    return d["access_token"]


def xoauth2(user: str, token: str) -> bytes:
    """The SASL XOAUTH2 initial response IMAP expects."""
    return f"user={user}\x01auth=Bearer {token}\x01\x01".encode()


def forget() -> None:
    secrets.delete(TOKEN)
    _flow.update(state="", code="", url="", error="")
