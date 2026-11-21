"""Discord: a bot that sends the program's cards to the applicant by direct message, with buttons, and takes their
presses, commands and replies back - over the gateway, a connection the program opens itself (no address of the
program has to be reachable from outside). A webhook can be used instead, for cards without buttons.

Only the applicant's own Discord user is listened to: the one bound with a short code they send the bot from the
settings page. The bot needs no privileged intent: what is said to it in a direct message reaches it without one.

Documentation: discord.com/developers/docs (gateway, interactions, message components).
"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from typing import Any
from collections.abc import Callable

import httpx

from . import db, secrets

log = logging.getLogger("autoapply.discord")

API = "https://discord.com/api/v10"
GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
TOKEN = "discord_bot_token"
WEBHOOK = "discord_webhook"
INTENTS = 1 << 12          # DIRECT_MESSAGES
COMMANDS = [               # the bot's commands (registered when it connects); what each does is bots.py's
    {"name": "status", "description": "What AutoApply is doing now"},
    {"name": "todo", "description": "What is waiting for you"},
    {"name": "pause", "description": "Pause automatic work"},
    {"name": "resume", "description": "Resume automatic work"},
    {"name": "scan", "description": "Look for new postings now"},
    {"name": "app", "description": "One application: where it stands", "options": [{"type": 3, "name": "name", "description": "Company or title", "required": True}]},
]


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bot {secrets.get(TOKEN)}", "User-Agent": "DiscordBot (https://github.com/Liam-Frost/AutoApply, 2)"}


def configured() -> bool:
    return bool(secrets.get(TOKEN))


def _call(method: str, path: str, body: Any = None) -> Any:
    for attempt in range(3):
        r = httpx.request(method, API + path, headers=_headers(), json=body, timeout=20)
        if r.status_code == 429:      # rate limited: wait as told
            time.sleep(min(10.0, float((r.json() or {}).get("retry_after") or 1)))
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"discord {r.status_code}: {r.text[:200]}")
        return r.json() if r.content else None
    raise RuntimeError("discord: rate limited")


def dm_channel() -> str:
    """The direct-message channel with the bound user (made once, then kept)."""
    user = str(db.get_setting("notify.discord_user_id") or "")
    if not user:
        raise RuntimeError("Discord 还没有绑定：在设置里点“绑定”，把短码私信给机器人。")
    known = db.get_setting("notify.discord_dm") or {}
    if known.get("user") == user and known.get("channel"):
        return str(known["channel"])
    ch = _call("POST", "/users/@me/channels", {"recipient_id": user})["id"]
    db.set_setting("notify.discord_dm", {"user": user, "channel": ch})
    return str(ch)


def components(buttons: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Buttons as Discord's action rows (five to a row)."""
    rows = []
    for i in range(0, min(len(buttons), 25), 5):
        rows.append({"type": 1, "components": [{"type": 2, "style": 1 if j == 0 and i == 0 else 2, "label": b["label"][:80], "custom_id": b["data"][:100]}
                                               for j, b in enumerate(buttons[i:i + 5])]})
    return rows


def embed(card: Any, base_url: str) -> dict[str, Any]:
    text = card.plain(base_url)
    head, _, rest = text.partition("\n")
    return {"title": head[:256], "description": rest.strip()[:4000], "color": 0x2563EB}


def send(card: Any, base_url: str, buttons: list[dict[str, str]] | None = None) -> str:
    """A card as a direct message to the applicant. Returns the message's id."""
    body: dict[str, Any] = {"embeds": [embed(card, base_url)]}
    if buttons:
        body["components"] = components(buttons)
    return str(_call("POST", f"/channels/{dm_channel()}/messages", body)["id"])


def send_text(text: str, buttons: list[dict[str, str]] | None = None, channel: str = "") -> str:
    body: dict[str, Any] = {"content": text[:2000]}
    if buttons:
        body["components"] = components(buttons)
    return str(_call("POST", f"/channels/{channel or dm_channel()}/messages", body)["id"])


def webhook_send(card: Any, base_url: str) -> None:
    url = secrets.get(WEBHOOK)
    if not url:
        raise RuntimeError("no webhook")
    r = httpx.post(url, params={"wait": "true"}, json={"embeds": [embed(card, base_url)]}, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"discord webhook {r.status_code}: {r.text[:200]}")


def respond(interaction: dict[str, Any], kind: int, data: dict[str, Any] | None = None) -> None:
    """Answer an interaction (a press, a command, a form sent): 4 a message, 7 the message updated, 9 a form."""
    r = httpx.post(f"{API}/interactions/{interaction['id']}/{interaction['token']}/callback", json={"type": kind, **({"data": data} if data is not None else {})}, timeout=20)
    if r.status_code >= 400:
        log.warning("discord interaction answer %s: %s", r.status_code, r.text[:200])


# --- the gateway ---------------------------------------------------------------------------------------------------------
class Gateway:
    """One connection to Discord's gateway, kept up until ``stop``: hello, identify, heartbeats, the events, and a new
    connection (after a pause that grows) when it drops. ``on_event(name, data)`` is called for every dispatch."""

    def __init__(self, on_event: Callable[[str, dict[str, Any]], None]) -> None:
        self.on_event = on_event
        self.stopping = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="discord-gateway", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()

    def _run(self) -> None:
        pause = 2.0
        while not self.stopping.is_set():
            if not configured():
                self.stopping.wait(30)
                continue
            try:
                self._session()
                pause = 2.0
            except Exception as e:  # noqa: BLE001 - dropped, refused, the network gone: try again after a while
                log.info("discord gateway: %s", type(e).__name__ + ": " + str(e)[:160])
            self.stopping.wait(pause)
            pause = min(300.0, pause * 2)

    def _session(self) -> None:
        from websockets.sync.client import connect

        token = secrets.get(TOKEN)
        with connect(GATEWAY, open_timeout=20, close_timeout=5, max_size=2 ** 22) as ws:
            hello = json.loads(ws.recv(timeout=30))
            every = float(hello["d"]["heartbeat_interval"]) / 1000
            seq: list[Any] = [None]
            ws.send(json.dumps({"op": 2, "d": {"token": token, "intents": INTENTS, "properties": {"os": "autoapply", "browser": "autoapply", "device": "autoapply"}}}))
            beat = time.monotonic() + every * random.random()
            while not self.stopping.is_set():
                if secrets.get(TOKEN) != token:      # the token was changed in the settings: connect again with the new one
                    return
                if time.monotonic() >= beat:
                    ws.send(json.dumps({"op": 1, "d": seq[0]}))
                    beat = time.monotonic() + every
                try:
                    raw = ws.recv(timeout=max(0.5, min(5.0, beat - time.monotonic())))
                except TimeoutError:
                    continue
                msg = json.loads(raw)
                if msg.get("s") is not None:
                    seq[0] = msg["s"]
                op = msg.get("op")
                if op == 1:
                    beat = 0.0
                elif op in (7, 9):       # reconnect / invalid session: a new connection
                    return
                elif op == 0:
                    try:
                        self.on_event(str(msg.get("t") or ""), msg.get("d") or {})
                    except Exception:  # noqa: BLE001 - one event that could not be handled does not end the connection
                        log.exception("discord event %s", msg.get("t"))


def about_bot() -> dict[str, str]:
    """The bot behind the saved token: its application id, its name, and the link that adds it to a server of the
    applicant's (a bot can write to a user it shares a server with)."""
    app = _call("GET", "/oauth2/applications/@me") or {}
    aid = str(app.get("id") or "")
    return {"id": aid, "name": str((app.get("bot") or {}).get("username") or app.get("name") or ""),
            "invite": f"https://discord.com/oauth2/authorize?client_id={aid}&scope=bot+applications.commands&permissions=0" if aid else ""}


def register_commands(application_id: str) -> None:
    try:
        _call("PUT", f"/applications/{application_id}/commands", COMMANDS)
    except Exception as e:  # noqa: BLE001 - the buttons and replies work without them
        log.info("discord commands were not registered: %s", e)
