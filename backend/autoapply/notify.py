"""Notifications. 1.0 ships one channel: a Telegram bot (send-only).

Four categories, each with its own switch in settings:
  task_started | todo | status_update | task_result

Messages never contain passwords, verification codes, or full profile data.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from . import db, messages, secrets
from .messages import Card
from .models import Notification, Todo

log = logging.getLogger("autoapply.notify")

CATEGORIES = ("task_started", "todo", "status_update", "task_result")
ALWAYS = {"interview", "assessment", "quota"}  # event tags that bypass the per-category switch (quota has its own switch: llm.quota_notify)


class Channel(Protocol):
    def send(self, text: str) -> None: ...


class TelegramChannel:
    def __init__(self, token: str, chat_id: str) -> None:
        self.token, self.chat_id = token, chat_id

    def _post(self, text: str, html: bool) -> httpx.Response:
        body = {"chat_id": self.chat_id, "text": text[:4000], "disable_web_page_preview": True}
        if html:
            body["parse_mode"] = "HTML"
        return httpx.post(f"https://api.telegram.org/bot{self.token}/sendMessage", json=body, timeout=20)

    def send_card(self, card: Card, base_url: str) -> None:
        r = self._post(card.html(base_url), True)
        if r.status_code == 400:  # markup rejected: the message still has to arrive
            r = self._post(card.plain(base_url), False)
        self._check(r)

    def send(self, text: str) -> None:
        self._check(self._post(text, False))

    def _check(self, r: httpx.Response) -> None:
        if r.status_code != 200 or not r.json().get("ok"):
            raise RuntimeError(f"telegram {r.status_code}: {r.text[:200].replace(self.token, '•••')}")


def _channels() -> list[Channel]:
    token = secrets.get(secrets.TELEGRAM_TOKEN)
    chat = db.get_setting("notify.telegram_chat_id")
    return [TelegramChannel(token, str(chat))] if token and chat else []


def link(path: str) -> str:
    return f"{str(db.get_setting('app.base_url')).rstrip('/')}{path}"


def quiet_now(at: Any = None) -> bool:
    """Are these the quiet hours the applicant set (nothing is pushed to the phone)?"""
    from datetime import datetime

    q = db.get_setting("notify.quiet") or {}
    if not q.get("on"):
        return False
    try:
        (fh, fm), (th, tm) = (map(int, str(q.get(k) or "").split(":")) for k in ("from", "to"))
    except (ValueError, TypeError):
        return False
    at = at or datetime.now()
    now_m, start, end = at.hour * 60 + at.minute, fh * 60 + fm, th * 60 + tm
    if start == end:
        return False
    return start <= now_m < end if start < end else (now_m >= start or now_m < end)


def flush_held(at: Any = None) -> int:
    """The quiet hours are over: what was kept back goes out, as one message (not a burst of them at eight in the morning)."""
    if quiet_now(at):
        return 0
    from . import i18n

    with db.session() as s:
        rows = [(n.id, n.text) for n in s.query(Notification).filter_by(held=1).order_by(Notification.id)]
    if not rows:
        return 0
    head = i18n.tr(f"静默时段里有 {len(rows)} 条通知：")
    parts, size = [], len(head)
    for _, text in rows:
        piece = i18n.tr_lines(text)
        if size + len(piece) > 3300:
            parts.append(i18n.tr(f"……还有 {len(rows) - len(parts)} 条，见活动记录里“发出的通知”。"))
            break
        parts.append(piece)
        size += len(piece) + 2
    sent, err = False, ""
    for ch in _channels():
        try:
            ch.send(head + "\n\n" + "\n\n".join(parts))
            sent = True
        except Exception as e:  # noqa: BLE001
            err = str(e)
            log.warning("held notifications could not be sent: %s", err)
    with db.session() as s:
        for n in s.query(Notification).filter(Notification.id.in_([i for i, _ in rows])):
            n.held, n.sent, n.error = 0, int(sent), err
    return len(rows)


def send(category: str, card: Card | str, *, ref: str = "", path: str = "", tag: str = "", through_quiet: bool = False) -> bool:
    """Record a notification and push it to every configured channel.
    ``card`` is normally a ``messages.Card``; a bare string is sent as a one-line card.

    In the quiet hours it is recorded and kept back (flush_held sends it when they end) - unless ``through_quiet``:
    something the applicant is waiting for right now, having started it themselves (the approval on their phone of a
    sign-in they asked for)."""
    assert category in CATEGORIES, category
    if isinstance(card, str):
        card = Card("🔔", card)
    if path and not card.path:
        card.path = path
    if ref.startswith("application:") and card.path == "/jobs" and ref[12:].split(":")[0].isdigit():
        # news about an application leads to the application - everything about it is on one page
        card.path, card.link = f"/applications/{ref[12:].split(':')[0]}", "查看这份申请"
    base = str(db.get_setting("app.base_url"))
    text = card.plain(base)       # the record kept in the program stays in the source language; the interface translates what it shows
    out = card.localized()        # what leaves the program follows the interface language
    enabled = bool(db.get_setting(f"notify.{category}")) or tag in ALWAYS
    sent, err = False, ""
    hold = enabled and not through_quiet and quiet_now()
    if hold:
        with db.session() as s:
            s.add(Notification(category=category, text=text, ref=ref, sent=0, error="", held=1))
        return False
    if enabled:
        for ch in _channels():
            try:
                rich = getattr(ch, "send_card", None)
                rich(out, base) if rich else ch.send(out.plain(base))
                sent = True
            except Exception as e:  # noqa: BLE001 - a failed push must not break the task
                err = str(e)
                log.warning("notification failed: %s", err)
    with db.session() as s:
        s.add(Notification(category=category, text=text, ref=ref, sent=int(sent), error=err))
    return sent


def test_message() -> None:
    chans = _channels()
    if not chans:
        raise RuntimeError("Telegram is not configured (bot token and chat id are both required).")
    base = str(db.get_setting("app.base_url"))
    for ch in chans:
        ch.send_card(messages.test().localized(), base)


def add_todo(kind: str, title: str, *, body: str = "", ref: str = "", payload: dict | None = None, push: bool = True) -> int:
    """Create a to-do (deduplicated on kind+ref while open) and notify.
    ``push=False`` when the caller sends its own, more specific notification for the same event.

    One thing that many tasks wait for is one card and one notice: the second task to meet it finds the card there."""
    with db.session() as s:
        existing = s.query(Todo).filter_by(kind=kind, ref=ref, status="open").first() if ref else None
        if existing:
            return existing.id
        t = Todo(kind=kind, title=title, body=body, ref=ref, payload=payload or {})
        s.add(t)
        s.flush()
        tid = t.id
    if push:
        send("todo", messages.todo(kind, title, body, payload=payload), ref=ref)
    return tid


def close_todos(kind: str, ref: str) -> None:
    from .models import now

    with db.session() as s:
        for t in s.query(Todo).filter_by(kind=kind, ref=ref, status="open"):
            t.status, t.done_at = "done", now()
