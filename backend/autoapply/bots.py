"""The Telegram and Discord bots as something to talk to, not only something that talks.

What comes back from a chat: a press on a card's button (actions.py), a reply to a card (the code a run waits for,
the answer to a question, or a word to an application's agent), a command (/status, /todo, /pause, /resume, /scan,
/app), and anything else said, which goes to the assistant (chat.py) when it is switched on.

Both bots listen with connections the program opens itself - Telegram's long poll, Discord's gateway - and only to the
applicant: Telegram's configured chat, Discord's bound user. Everything they do goes through the same functions the
program's pages use, and each thing they were told is in the activity record with the channel it came from. Each runs
in a thread of its own, started with the server and stopped with it, and stands aside in a server that is handing
over to a newer one.
"""
from __future__ import annotations

from .say import say as T

import logging
import secrets as _random
import string
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

import httpx

from . import actions, db, discord, i18n, secrets
from .models import CALENDAR_ONLY, Notification, Todo

log = logging.getLogger("autoapply.bots")

_stop = threading.Event()
_talk = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bot-chat")
_threads: list[threading.Thread] = []
_gateway: discord.Gateway | None = None
NAMES = {"telegram": "Telegram", "discord": "Discord"}

Send = Callable[[str, list[dict[str, str]]], str]      # (text, buttons) -> the id of the message sent


def _t(text: str) -> str:
    return i18n.tr(text)


def _retiring() -> bool:
    from . import tasks

    try:
        return tasks.retiring()
    except Exception:  # noqa: BLE001
        return False


# --- which card a reply is to ------------------------------------------------------------------------------------------
SENT = "bot.sent"      # messages the bots sent that are not notifications (a card listed by /todo, a prompt for a code)


def _card_of(channel: str, message_id: str) -> tuple[str, int | None]:
    """(ref, to-do id) of the card that went out as this chat message."""
    for m in reversed(db.get_setting(SENT) or []):
        if m.get("ch") == channel and str(m.get("id")) == str(message_id):
            return str(m.get("ref") or ""), m.get("todo")
    with db.session() as s:
        for n in s.query(Notification).filter(Notification.pushed.isnot(None)).order_by(Notification.id.desc()).limit(2000):
            if str((n.pushed or {}).get(channel) or "") == str(message_id):
                return n.ref or "", n.todo_id
    return "", None


def remember(channel: str, message_id: str, ref: str, todo_id: int | None = None) -> None:
    """A message the bot sent that is not a notification (a card listed by /todo, a prompt for a code): a reply to it
    is a reply to the card it is about."""
    kept = list(db.get_setting(SENT) or [])[-299:]
    db.set_setting(SENT, [*kept, {"ch": channel, "id": str(message_id), "ref": ref, "todo": todo_id}])


# --- the activity record -------------------------------------------------------------------------------------------------
def heard(channel: str, what: str, result: str) -> None:
    """What the applicant told a bot, and what came of it, in the activity record (the notifications list, marked as
    received). A code is never written down: only that one was given."""
    with db.session() as s:
        s.add(Notification(category="heard", text=f"{NAMES.get(channel, channel)}：{what}\n→ {result}"[:1500], ref="", sent=1, error=""))


def _what(data: str) -> str:
    """The thing a button was about, in words, for the record."""
    parts = data.split(":")
    with db.session() as s:
        if parts[0] == "t" and len(parts) > 2 and parts[1].isdigit():
            t = s.get(Todo, int(parts[1]))
            return f"{t.title if t else '#' + parts[1]}（{parts[2]}）"
        if parts[0] == "d" and len(parts) > 2 and parts[1].isdigit():
            from .models import Draft

            d = s.get(Draft, int(parts[1]))
            return T("server.bots.approveAndSend", p0=d.application.job.company, p1=d.application.job.title) if d else data
    return T("server.bots.confirmedTheAssistantsProposal") if parts[0] == "c" else data


# --- commands ----------------------------------------------------------------------------------------------------------
def status() -> str:
    from .models import Job, Task

    with db.session() as s:
        running = list(s.query(Task).filter_by(status="running"))
        queued = s.query(Task).filter_by(status="queued").count()
        open_ = s.query(Todo).filter(Todo.status == "open", Todo.kind.notin_(CALENDAR_ONLY)).count()
        names = []
        for t in running:
            if t.kind == "apply" and t.ref.startswith("job:"):
                j = s.get(Job, int(t.ref[4:])) if t.ref[4:].isdigit() else None
                names.append(f"{j.company} · {j.title}" if j else t.ref)
    paused = bool(db.get_setting("schedule.paused"))
    lines = [_t(T("server.bots.automaticWorkPaused")) if paused else _t(T("server.bots.running"))]
    if names:
        lines += [_t(T("server.bots.workingOn")), *(f"• {n}" for n in names[:6])]
    lines.append(_t(T("server.bots.queuedWaitingForYou", p0=queued, p1=open_)))
    return "\n".join(lines)


def open_cards(limit: int = 8) -> list[tuple[str, int, str]]:
    """(text, to-do id, ref) of the open cards, the most pressing first."""
    from . import reminders

    with db.session() as s:
        rows = [t for t in s.query(Todo).filter(Todo.status == "open", Todo.kind.notin_(CALENDAR_ONLY)).order_by(Todo.id.desc()) if not reminders.snoozed(t)]
    rank = {"code": 0, "confirm": 0, "submit": 1, "answer": 2, "resume": 2, "failed": 3}
    rows.sort(key=lambda t: (rank.get(t.kind, 5), -t.id))
    return [(i18n.tr_lines(f"{t.title}\n{(t.body or '')[:300]}".strip()), t.id, t.ref) for t in rows[:limit]]


def find_application(name: str) -> str:
    from .humanize import APP_STATUS
    from .models import Application, Job

    name = name.strip().lower()
    if not name:
        return _t(T("server.bots.usageAppCompanyName"))
    base = str(db.get_setting("app.base_url")).rstrip("/")
    with db.session() as s:
        hits = [a for a in s.query(Application).join(Job) if name in f"{a.job.company} {a.job.title}".lower()][:5]
        if not hits:
            return _t(T("server.bots.noSuchApplicationFound"))
        return "\n\n".join("\n".join(x for x in (f"{a.job.company} · {a.job.title}", _t(APP_STATUS.get(a.status, a.status)),
                                                  i18n.tr_lines((a.last_event or "")[:200]), f"{base}/applications/{a.id}") if x)
                           for a in hits)


def command(name: str, arg: str = "") -> str:
    from . import tasks

    name = name.lower().lstrip("/").split("@")[0]
    if name == "status":
        return status()
    if name == "pause":
        db.set_setting("schedule.paused", True)
        return _t(T("server.bots.automaticWorkPausedWhat"))
    if name == "resume":
        db.set_setting("schedule.paused", False)
        return _t(T("server.bots.automaticWorkResumed"))
    if name == "scan":
        asked = tasks.by_hand.set(True)
        try:
            tasks.enqueue("discover", ref="manual", priority=20, dedupe=True)
        finally:
            tasks.by_hand.reset(asked)
        return _t(T("server.bots.lookingForNewPostings"))
    if name == "app":
        return find_application(arg)
    if name == "todo":
        cards = open_cards()
        return _t(T("server.bots.nothingIsWaitingFor")) if not cards else _t(T("server.bots.thingsAreWaitingFor", p0=len(cards)))
    return help_text()


def help_text() -> str:
    return _t(T("server.bots.commandsStatusWhatIs"))


# --- what both bots do with what comes back --------------------------------------------------------------------------------
def press(channel: str, data: str, value: str = "") -> str:
    """A button pressed (with what was typed for it, a code). Returns what to say back."""
    try:
        out = actions.run(data, value, via=channel)
    except actions.Done as e:
        out = str(e)
    except Exception:  # noqa: BLE001 - the press is answered whatever happened: a button that spins forever says nothing
        log.exception("%s press %s", channel, data)
        out = _t(T("server.bots.thatDidNotWork"))
    heard(channel, _what(data) + (T("server.bots.codeGiven") if value else ""), out)
    return out


def message(channel: str, text: str, reply_to: str, send: Send) -> None:
    """A message: a command, a reply to a card, or something said to the assistant."""
    if text.startswith("/"):
        name, _, arg = text.partition(" ")
        out = command(name, arg)
        send(out, [])
        heard(channel, text[:200], out[:300])
        if name.lower().lstrip("/").split("@")[0] == "todo":
            for body, todo_id, ref in open_cards():
                remember(channel, send(body, actions.for_todo(todo_id)), ref, todo_id)
        return
    if reply_to:
        ref, todo_id = _card_of(channel, reply_to)
        if ref:
            try:
                out = actions.reply(ref, todo_id, text)
            except actions.Done as e:
                out = str(e)
            except Exception:  # noqa: BLE001
                log.exception("%s reply to %s", channel, ref)
                out = _t(T("server.bots.thatDidNotWork"))
            send(out, [])
            heard(channel, T("server.bots.repliedWithTheCode") if actions.about(ref)[0] == "code" else T("server.bots.repliedToACard", p0=text[:300]), out[:300])
            return
    if not db.get_setting("bot.chat"):
        send(help_text(), [])
        return
    _talk.submit(_answer, channel, text, send)


def _answer(channel: str, text: str, send: Send) -> None:
    """The assistant answers in a thread of its own: the bot goes on taking presses meanwhile. One at a time."""
    from . import chat

    try:
        reply, buttons = chat.reply(text)
    except Exception as e:  # noqa: BLE001 - the model could not be reached: the commands still work
        log.info("the assistant could not answer: %s", e)
        reply, buttons = _t(T("server.bots.iCannotAnswerRight")) + "\n\n" + help_text(), []
    try:
        send(reply, buttons)
    except Exception:  # noqa: BLE001
        log.exception("the assistant's answer could not be sent")
    heard(channel, T("server.bots.saidToTheAssistant", p0=text[:300]), reply[:300])


# --- Telegram ----------------------------------------------------------------------------------------------------------
TG = "https://api.telegram.org/bot{token}/{method}"


def _tg(method: str, token: str, **body: Any) -> Any:
    r = httpx.post(TG.format(token=token, method=method), json=body, timeout=70)
    data = r.json() if r.content else {}
    if not data.get("ok"):
        raise RuntimeError(f"telegram {method} {r.status_code}: {str(data.get('description') or '')[:160]}")
    return data.get("result")


def tg_keyboard(buttons: list[dict[str, str]]) -> dict[str, Any] | None:
    if not buttons:
        return None
    rows, row = [], []
    for b in buttons:
        row.append({"text": b["label"][:60], "url": b["url"]} if b.get("url") else {"text": b["label"][:60], "callback_data": b["data"][:64]})
        if len(row) == 2 or len(b["label"]) > 18:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return {"inline_keyboard": rows}


def _tg_send(token: str, chat: str, text: str, buttons: list[dict[str, str]] | None = None, *, force_reply: bool = False) -> str:
    body: dict[str, Any] = {"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True}
    if force_reply:
        body["reply_markup"] = {"force_reply": True}
    elif buttons:
        body["reply_markup"] = tg_keyboard(buttons)
    return str(_tg("sendMessage", token, **body)["message_id"])


def _tg_update(token: str, chat: str, u: dict[str, Any]) -> None:
    if "callback_query" in u:
        q = u["callback_query"]
        msg = q.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != chat:
            return
        data = str(q.get("data") or "")
        if data == "-":
            _tg("answerCallbackQuery", token, callback_query_id=q["id"])
            return
        if data.endswith(":code"):      # the code is typed as a reply
            _tg("answerCallbackQuery", token, callback_query_id=q["id"])
            ref, todo_id = _card_of("telegram", str(msg.get("message_id")))
            mid = _tg_send(token, chat, _t(T("server.bots.replyToThisMessage")), force_reply=True)
            remember("telegram", mid, ref, todo_id or int(data.split(":")[1]))
            return
        said_back = press("telegram", data)
        _tg("answerCallbackQuery", token, callback_query_id=q["id"], text=said_back[:190])
        try:
            _tg("editMessageReplyMarkup", token, chat_id=chat, message_id=msg.get("message_id"), reply_markup={"inline_keyboard": [[{"text": "✓ " + said_back[:50], "callback_data": "-"}]]})
        except Exception:  # noqa: BLE001, S110 - the message is too old to change: the answer above said it
            pass
        return
    m = u.get("message") or {}
    if str((m.get("chat") or {}).get("id")) != chat or not (m.get("text") or "").strip():
        return
    message("telegram", m["text"].strip(), str((m.get("reply_to_message") or {}).get("message_id") or ""),
            lambda out, buttons: _tg_send(token, chat, out, buttons))


def _telegram_loop() -> None:
    commands_set = ""
    while not _stop.is_set():
        token, chat = secrets.get(secrets.TELEGRAM_TOKEN), str(db.get_setting("notify.telegram_chat_id") or "")
        if not token or not chat or _retiring() or not db.get_setting("bot.listen"):
            _stop.wait(20)
            continue
        try:
            if commands_set != token:
                _tg("setMyCommands", token, commands=[{"command": c["name"], "description": c["description"]} for c in discord.COMMANDS])
                commands_set = token
            offset = int(db.get_setting("bot.telegram_offset") or 0)
            got = _tg("getUpdates", token, offset=offset, timeout=50, allowed_updates=["message", "callback_query"]) or []
            for u in got:
                db.set_setting("bot.telegram_offset", int(u["update_id"]) + 1)      # (before handling: one that fails is not handled again and again)
                try:
                    _tg_update(token, chat, u)
                except Exception:  # noqa: BLE001
                    log.exception("telegram update")
        except Exception as e:  # noqa: BLE001 - another program polls the same bot, the network is down: wait and try again
            log.info("telegram: %s", str(e)[:200])
            _stop.wait(15)


# --- Discord -----------------------------------------------------------------------------------------------------------
def bind_code() -> str:
    """A short code the applicant sends the bot to tell it which Discord user is theirs (valid fifteen minutes)."""
    code = "".join(_random.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    db.set_setting("notify.discord_bind", {"code": code, "until": (datetime.now() + timedelta(minutes=15)).isoformat()})
    return code


def _user_of(d: dict[str, Any]) -> str:
    return str(((d.get("member") or {}).get("user") or d.get("user") or d.get("author") or {}).get("id") or "")


def _done_row(text: str) -> list[dict[str, Any]]:
    return [{"type": 1, "components": [{"type": 2, "style": 2, "label": ("✓ " + text)[:80], "custom_id": "-", "disabled": True}]}]


def _discord_event(name: str, d: dict[str, Any]) -> None:
    bound = str(db.get_setting("notify.discord_user_id") or "")
    if name == "READY":
        app_id = str((d.get("application") or {}).get("id") or "")
        if app_id:
            discord.register_commands(app_id)
        return
    if name == "MESSAGE_CREATE":
        author = d.get("author") or {}
        if author.get("bot") or d.get("guild_id"):      # direct messages only
            return
        text, channel = str(d.get("content") or "").strip(), str(d.get("channel_id") or "")
        bind = db.get_setting("notify.discord_bind") or {}
        if bind.get("code") and text.upper() == bind["code"] and datetime.now() < datetime.fromisoformat(bind["until"]):
            db.set_setting("notify.discord_user_id", str(author.get("id")))
            db.set_setting("notify.discord_bind", {})
            db.set_setting("notify.discord_dm", {"user": str(author.get("id")), "channel": channel})
            discord.send_text(_t(T("server.bots.linkedNotificationsWillCome")), channel=channel)
            heard("discord", T("server.bots.link"), _t(T("server.bots.linked")))
            return
        if str(author.get("id")) != bound or not text:
            return
        message("discord", text, str((d.get("message_reference") or {}).get("message_id") or ""),
                lambda out, buttons: discord.send_text(out, buttons, channel=channel))
        return
    if name != "INTERACTION_CREATE" or _user_of(d) != bound:
        return
    kind, data = d.get("type"), d.get("data") or {}
    if kind == 2:      # a command
        opts = {o.get("name"): o.get("value") for o in data.get("options") or []}
        cmd = str(data.get("name") or "")
        out = command(cmd, str(opts.get("name") or ""))
        discord.respond(d, 4, {"content": out[:2000]})
        heard("discord", f"/{cmd} {opts.get('name') or ''}".strip(), out[:300])
        if cmd == "todo":
            for body, todo_id, ref in open_cards():
                remember("discord", discord.send_text(body, actions.for_todo(todo_id)), ref, todo_id)
        return
    if kind == 3:      # a button
        cid = str(data.get("custom_id") or "")
        if cid == "-":
            discord.respond(d, 6)
            return
        if cid.endswith(":code"):      # a form to type the code in
            discord.respond(d, 9, {"custom_id": cid, "title": _t(T("server.bots.code"))[:45],
                                   "components": [{"type": 1, "components": [{"type": 4, "custom_id": "value", "label": _t(T("server.bots.theCodeTheSite"))[:45], "style": 1, "required": True}]}]})
            return
        discord.respond(d, 7, {"components": _done_row(press("discord", cid))})
        return
    if kind == 5:      # the form sent: the code
        value = ""
        for row in data.get("components") or []:
            for c in row.get("components") or []:
                if c.get("custom_id") == "value":
                    value = str(c.get("value") or "")
        out = press("discord", str(data.get("custom_id") or ""), value)
        discord.respond(d, 7 if d.get("message") else 4, {"components": _done_row(out)} if d.get("message") else {"content": out})


# --- starting and stopping ---------------------------------------------------------------------------------------------
def start() -> None:
    global _gateway
    _stop.clear()
    t = threading.Thread(target=_telegram_loop, name="telegram-bot", daemon=True)
    t.start()
    _threads.append(t)
    _gateway = discord.Gateway(lambda n, d: None if (_retiring() or not db.get_setting("bot.listen")) else _discord_event(n, d))
    _gateway.start()


def stop() -> None:
    _stop.set()
    if _gateway is not None:
        _gateway.stop()
