"""How much of each AI service's allowance is left, for the services that say.

Who says, and how (checked against each provider's documentation and SDK in November 2026):

* Claude subscription - every call through the Agent SDK carries the usage windows (5 hours, 7 days) with the fraction
  used and the reset time. Nothing has to be asked: the figures of the last call are kept.
* ChatGPT subscription - the Codex SDK answers "account/rateLimits/read": the same two kinds of window.
* DeepSeek - ``GET /user/balance``: the balance per currency.
* OpenRouter - ``GET /api/v1/key`` (the key's own cap) and ``GET /api/v1/credits`` (the account's credits).

The Anthropic API, the OpenAI API, Gemini and Qwen have no call that returns the remaining balance for an API key
(their consoles show it). For those the program only learns that the allowance is gone when a call is refused, which is
what the failover in ``llm`` is for.

``check_all`` runs on a timer: it warns once when a service passes the warning level, once more when it is used up, and
tells ``llm`` to leave a used-up service alone until its window resets, so no call has to fail first.
"""

from __future__ import annotations

from .say import say as T

import logging
import time
from datetime import datetime
from typing import Any

import httpx

from . import db, secrets

log = logging.getLogger("autoapply.quota")

WINDOWS = ("claude_subscription", "chatgpt")
BALANCE = ("deepseek", "openrouter")
WHY_NOT = {
    "anthropic": T("server.quota.anthropicsApiHasNo"),
    "openai": T("server.quota.openaisApiHasNo"),
    "gemini": T("server.quota.geminisApiHasNo"),
    "qwen": T("server.quota.aTongyiQianwenApi"),
    "custom": T("server.quota.aCustomServiceHas"),
}
LABEL = {"five_hour": T("server.quota.hourAllowance"), "seven_day": T("server.quota.weeklyAllowance"), "seven_day_opus": T("server.quota.weeklyAllowanceOpus"), "seven_day_sonnet": T("server.quota.weeklyAllowanceSonnet"), "overage": T("server.quota.usageOverTheAllowance")}


def supported(provider: str) -> bool:
    return provider in WINDOWS or provider in BALANCE


def _window_label(minutes: int | None, fallback: str) -> str:
    if not minutes:
        return fallback
    if minutes <= 24 * 60:
        return T("server.quota.hourAllowance2", p0=round(minutes / 60))
    return T("server.quota.weeklyAllowance") if 6 * 1440 <= minutes <= 8 * 1440 else T("server.quota.dayAllowance", p0=round(minutes / 1440))


def _store() -> dict[str, Any]:
    return dict(db.get_setting("llm.quota") or {})


def remember(provider: str, snap: dict[str, Any]) -> dict[str, Any]:
    snap = {"provider": provider, "supported": True, "checked_at": int(time.time()), **snap}
    all_ = _store()
    all_[provider] = snap
    db.set_setting("llm.quota", all_)
    return snap


def remember_claude(raw: dict[str, Any]) -> None:
    """Called for every rate-limit record a Claude subscription call reports."""
    wins = []
    for key, w in (raw.get("unifiedWindows") or {}).items():
        if isinstance(w, dict) and w.get("utilization") is not None:
            wins.append({"key": key, "label": LABEL.get(key, key), "used": round(float(w["utilization"]) * 100), "resets_at": int(w.get("resetsAt") or 0),
                         "blocked": w.get("status") == "rejected"})
    if not wins and raw.get("rateLimitType"):   # older records: one window, no fraction; "rejected" still tells that it is used up
        wins.append({"key": raw["rateLimitType"], "label": LABEL.get(raw["rateLimitType"], raw["rateLimitType"]), "used": 100 if raw.get("status") == "rejected" else None,
                     "resets_at": int(raw.get("resetsAt") or 0), "blocked": raw.get("status") == "rejected"})
    if wins:
        remember("claude_subscription", {"kind": "windows", "windows": wins, "blocked": any(w["blocked"] for w in wins)})


def _chatgpt() -> dict[str, Any]:
    from . import llm_codex

    try:
        from openai_codex.generated.v2_all import GetAccountRateLimitsResponse
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(T("server.quota.chatgptConnectorNotInstalled")) from e
    with llm_codex._codex() as c:
        r = c._client.request("account/rateLimits/read", None, response_model=GetAccountRateLimitsResponse)
    d = r.model_dump(mode="json", exclude_none=True)
    rl = d.get("rate_limits") or {}
    wins = []
    for key, fallback in (("primary", T("server.quota.shortTermAllowance")), ("secondary", T("server.quota.longTermAllowance"))):
        w = rl.get(key)
        if w:
            wins.append({"key": key, "label": _window_label(w.get("window_duration_mins"), fallback), "used": int(w.get("used_percent") or 0), "resets_at": int(w.get("resets_at") or 0),
                         "blocked": int(w.get("used_percent") or 0) >= 100})
    return {"kind": "windows", "windows": wins, "blocked": d.get("ordinary_usage_allowed") is False or any(w["blocked"] for w in wins), "plan": str(rl.get("plan_type") or "")}


def _deepseek() -> dict[str, Any]:
    from . import llm, llm_openai

    cfg = (db.get_setting("llm.providers") or {}).get("deepseek") or {}
    base = str(cfg.get("base_url") or llm_openai.PRESETS["deepseek"]["base_url"]).rstrip("/").removesuffix("/v1")
    key = secrets.get(llm.key_name("deepseek"))
    if not key:
        raise RuntimeError(T("server.quota.noDeepseekApiKey"))
    r = httpx.get(f"{base}/user/balance", headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}, timeout=20)
    r.raise_for_status()
    d = r.json()
    bal = [{"currency": b.get("currency", ""), "amount": float(b.get("total_balance") or 0)} for b in d.get("balance_infos") or []]
    return {"kind": "balance", "balances": bal, "blocked": d.get("is_available") is False}


def _openrouter() -> dict[str, Any]:
    from . import llm

    key = secrets.get(llm.key_name("openrouter"))
    if not key:
        raise RuntimeError(T("server.quota.noOpenrouterApiKey"))
    h = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    k = httpx.get("https://openrouter.ai/api/v1/key", headers=h, timeout=20)
    k.raise_for_status()
    data = k.json().get("data") or {}
    left = data.get("limit_remaining")
    if left is None:   # the key has no cap of its own: the account's credits are what runs out
        c = httpx.get("https://openrouter.ai/api/v1/credits", headers=h, timeout=20)
        if c.status_code == 200:
            cd = c.json().get("data") or {}
            left = float(cd.get("total_credits") or 0) - float(cd.get("total_usage") or 0)
    if left is None:
        raise RuntimeError(T("server.quota.openrouterDidNotReturn"))
    return {"kind": "balance", "balances": [{"currency": "USD", "amount": round(float(left), 4)}], "blocked": float(left) <= 0}


def read(provider: str, *, refresh: bool = False, max_age: int = 600) -> dict[str, Any]:
    """The allowance of one service: {supported, kind, windows | balances, blocked, checked_at, level} or {supported: False, note}
    or {supported: True, error}. Figures younger than ``max_age`` seconds are reused unless ``refresh``."""
    from . import llm

    name = llm.label(provider)
    if not supported(provider):
        return {"provider": provider, "name": name, "supported": False, "note": WHY_NOT.get(provider, WHY_NOT["custom"])}
    old = _store().get(provider)
    if old and not refresh and time.time() - int(old.get("checked_at") or 0) < max_age:
        return {**old, "name": name, "level": level(old)}
    try:
        if provider == "claude_subscription":
            if refresh:   # the figures ride on a call, so asking means making one (the smallest possible)
                llm._tls.entry = {"provider": "claude_subscription", "model": "", "small_model": ""}
                try:
                    llm._text("Reply with the single word: OK", system=None, small=True, max_tokens=20, effort=None)
                finally:
                    llm._tls.entry = None
            snap = _store().get(provider)
            if not snap:
                return {"provider": provider, "name": name, "supported": True, "kind": "windows", "windows": [], "pending": True,
                        "note": T("server.quota.claudesAllowanceComesBack")}
        else:
            snap = remember(provider, {"chatgpt": _chatgpt, "deepseek": _deepseek, "openrouter": _openrouter}[provider]())
    except Exception as e:  # noqa: BLE001 - a figure that cannot be read is shown as such; it never breaks the caller
        log.info("quota of %s could not be read: %s", provider, e)
        return {"provider": provider, "name": name, "supported": True, "error": f"{type(e).__name__}: {str(e)[:200]}", **({"stale": old} if old else {})}
    return {**snap, "name": name, "level": level(snap)}


def level(snap: dict[str, Any]) -> str:
    """ok | low | out, against the user's warning levels."""
    warn_pct = float(db.get_setting("llm.quota_warn_percent") or 80)
    warn_bal = float(db.get_setting("llm.quota_warn_balance") or 1)
    now_ = time.time()
    if snap.get("kind") == "windows":
        live = [w for w in snap.get("windows") or [] if not w.get("resets_at") or w["resets_at"] > now_]   # a window that has reset says nothing about now
        if any(w.get("blocked") or (w.get("used") or 0) >= 100 for w in live):
            return "out"
        return "low" if any((w.get("used") or 0) >= warn_pct for w in live) else "ok"
    if snap.get("kind") == "balance":
        amounts = [b["amount"] for b in snap.get("balances") or []]
        if snap.get("blocked") or (amounts and max(amounts) <= 0):
            return "out"
        return "low" if amounts and max(amounts) < warn_bal else "ok"
    return "ok"


def reset_time(provider: str) -> float | None:
    """When a used-up service can be used again (epoch seconds), if it says. Used to rest it exactly that long."""
    if provider not in WINDOWS:
        return None
    try:
        snap = read(provider, max_age=60) if provider == "chatgpt" else (_store().get(provider) or {})
    except Exception:  # noqa: BLE001
        return None
    now_ = time.time()
    blocked = [w["resets_at"] for w in snap.get("windows") or [] if (w.get("blocked") or (w.get("used") or 0) >= 100) and (w.get("resets_at") or 0) > now_]
    return float(max(blocked)) if blocked else None


def describe(snap: dict[str, Any]) -> list[tuple[str, str]]:
    """Lines for a message: [("5 小时额度", "已用 85%，22:27 重置"), ...]."""
    out = []
    for w in snap.get("windows") or []:
        when = datetime.fromtimestamp(w["resets_at"]).strftime("%m-%d %H:%M" if w["resets_at"] - time.time() > 20 * 3600 else "%H:%M") if w.get("resets_at") else ""
        used = T("server.quota.usedUp") if (w.get("blocked") or (w.get("used") or 0) >= 100) else T("server.quota.used", p0=w['used']) if w.get("used") is not None else T("server.quota.unknown")
        out.append((w["label"], used + (T("server.quota.resets", p0=when) if when else "")))
    for b in snap.get("balances") or []:
        out.append((T("server.quota.balance"), f"{b['amount']:.2f} {b['currency']}".strip()))
    return out


def check_all(*, announce: bool = True) -> list[dict[str, Any]]:
    """Read the allowance of every service in the failover chain; warn about the ones running low; rest the used-up ones."""
    from . import llm, messages, notify

    providers: list[str] = []
    for e in llm.chain():
        if e["provider"] not in providers:
            providers.append(e["provider"])
    out = []
    told = dict(db.get_setting("llm.quota_alerts") or {})
    changed = False
    for i, p in enumerate(providers):
        snap = read(p)
        out.append(snap)
        lvl = snap.get("level")
        if lvl not in ("low", "out"):
            continue
        if lvl == "out":
            until = reset_time(p)
            if until:
                llm.rest(p, until, T("server.quota.theAllowanceIsUsed"))
        if not announce or not db.get_setting("llm.quota_notify"):
            continue
        if snap.get("kind") == "windows":
            marks = [f"{p}|{w['key']}|{w.get('resets_at')}|{lvl}" for w in snap["windows"] if w.get("blocked") or (w.get("used") or 0) >= float(db.get_setting("llm.quota_warn_percent") or 80)]
        else:
            marks = [f"{p}|balance|{lvl}|{datetime.now().date().isoformat()}"]
        fresh = [m for m in marks if m not in told]
        if not fresh:
            continue
        nxt = next((llm.label(x) for x in providers[i + 1:] + providers[:i] if x != p), "")
        notify.send("status_update", messages.quota_low(snap["name"], describe(snap), out=lvl == "out", backup=nxt, primary=i == 0), ref="config:llm", tag="quota")
        for m in fresh:
            told[m] = int(time.time())
        changed = True
    if changed:
        cut = time.time() - 14 * 86400
        db.set_setting("llm.quota_alerts", {k: v for k, v in told.items() if v > cut})
    return out
