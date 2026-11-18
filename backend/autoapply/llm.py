"""Claude access: one place for model choice, structured output, and the agent loop.

Three entry points:
  * ``text``  - free-form generation (cover letters).
  * ``json``  - schema-constrained output (scoring, answer resolution, mail triage).
  * ``agent`` - tool-use loop with vision (reconnaissance on unknown ATS, repair).

Backends, chosen by the ``llm.provider`` setting: the Claude subscription (``llm_sdk``), the Anthropic API, the ChatGPT
subscription (``llm_codex``) and any OpenAI-compatible service (``llm_openai``).

Failover: the user can list backup services (``llm.failover``). When the service in use runs out or cannot be reached,
the same call is made on the next one; see ``_failover``. Both the main and the small model follow the same chain.
"""

from __future__ import annotations

import base64
import json as _json
import logging
import re
import sys
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import anthropic

from . import agentbudget, db, llm_codex, llm_openai, llm_sdk, metering, secrets

log = logging.getLogger("autoapply.llm")

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    pass


class LLMRefused(LLMError):
    pass


class LLMUnavailable(LLMError):
    """No credentials or the API cannot be reached."""


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    _lock: Any = field(default_factory=threading.Lock, repr=False, compare=False)

    def count(self, calls: int, input_tokens: int = 0, output_tokens: int = 0) -> None:
        with self._lock:        # a task's helper threads count on the same meter
            self.calls += int(calls or 0)
            self.input_tokens += int(input_tokens or 0)
            self.output_tokens += int(output_tokens or 0)

    def add(self, resp: Any) -> None:
        u = getattr(resp, "usage", None)
        self.count(1, getattr(u, "input_tokens", 0) if u is not None else 0, getattr(u, "output_tokens", 0) if u is not None else 0)


_tls = threading.local()        # .entry: the service this thread's call is trying right now - a thread's, not a task's
_usage: ContextVar[Usage | None] = ContextVar("llm_usage", default=None)


def usage() -> Usage:
    """The usage meter of the work that is running; a task resets it at start and stores it on its Run. It is the
    task's on every thread that does a part of it (context.py)."""
    u = _usage.get()
    if u is None:
        u = Usage()
        _usage.set(u)
    return u


def reset_usage() -> Usage:
    u = Usage()
    _usage.set(u)
    return u


feature = metering.feature      # ``with llm.feature("name"):`` names the feature for the calls inside


def _status(err: BaseException) -> str:
    """How a failed request ended, for the usage record."""
    if isinstance(err, LLMRefused):
        return "refused"
    msg = str(err).lower()
    if re.search(r"time.?out|timed out|no answer from|超时", msg):
        return "timeout"
    if re.search(r"rate.?limit|\b429\b|usage limit|limit reached|quota|额度|欠费", msg):
        return "rate_limited"
    return "unavailable" if isinstance(err, LLMUnavailable) else "error"


def _failed(model: str, t0: float, err: BaseException, **kw: Any) -> None:
    metering.record(provider=provider(), model=model, started=t0, status=_status(err), error=str(err), error_type=type(err).__name__, **kw)


_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        key = secrets.get(secrets.ANTHROPIC_KEY)
        try:
            _client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        except Exception as e:  # noqa: BLE001
            raise LLMUnavailable(f"Claude credentials are not configured: {e}") from e
    return _client


def reset_client() -> None:
    """Credentials or settings changed: forget the cached client, and give every service a fresh chance."""
    global _client
    _client = None
    reset_failover()


def _entry() -> dict[str, str] | None:
    """The failover entry this thread is trying right now (None outside a failover attempt)."""
    return getattr(_tls, "entry", None)


def _model(small: bool) -> str:
    e = _entry() or {}
    return str(e.get("small_model" if small else "model") or db.get_setting("llm.small_model" if small else "llm.model"))


def primary() -> str:
    """The AI service chosen in the settings."""
    p = str(db.get_setting("llm.provider") or "")
    if p in ("claude_subscription", "anthropic", "chatgpt") or p in llm_openai.PRESETS:
        return p
    return "anthropic" if db.get_setting("llm.auth") == "api_key" else "claude_subscription"


def provider() -> str:
    """Which AI service this call uses: the one in the settings, or the backup being tried."""
    e = _entry()
    return e["provider"] if e else primary()


def backend() -> str:
    """subscription (Claude login) | api_key (Anthropic API) | openai (any OpenAI-compatible service) | codex (ChatGPT login)."""
    p = provider()
    return {"claude_subscription": "subscription", "anthropic": "api_key", "chatgpt": "codex"}.get(p, "openai")


def key_name(p: str) -> str:
    return f"llm_key_{p}"


def _other(small: bool) -> tuple[dict[str, Any], str]:
    cfg = dict((db.get_setting("llm.providers") or {}).get(provider()) or {})
    e = _entry() or {}
    main = str(e.get("model") or cfg.get("model") or "")
    model = str(e.get("small_model") or cfg.get("small_model") or main) if small else main
    return cfg, model


# --- failover ------------------------------------------------------------------------------------
# One service running out (a subscription's usage limit, a rate limit, an outage, a key that stopped working) must not
# stop the work. The user lists backups in order; a call that fails for such a reason is repeated on the next one, and
# the service that failed is left alone for a while. This holds for the main model and the small one: each entry has both.

CLAUDE = ("claude_subscription", "anthropic")
TRANSIENT = re.compile(r"rate.?limit|\b429\b|quota|usage limit|limit reached|overloaded|\b5\d\d\b|time.?out|timed out|billing|credit|insufficient|capacity|unavailable|"
                       r"connection|temporar|额度|欠费|超时|连不上", re.I)
UNSUPPORTED = re.compile(r"不能发送图片|不支持在提问里附带图片|not support", re.I)
_down: dict[str, tuple[float, str]] = {}      # entry key -> (not before, why)
_announced: set[str] = set()
_lock = threading.Lock()


def label(p: str) -> str:
    return {"claude_subscription": "Claude 订阅", "anthropic": "Claude API", "chatgpt": "ChatGPT 订阅"}.get(p) or (llm_openai.PRESETS.get(p) or {}).get("name", p)


def _key(e: dict[str, str]) -> str:
    return f"{e['provider']}|{e.get('model') or ''}"


def chain() -> list[dict[str, str]]:
    """The services to try, in order: the one in use, then the backups from the settings (each at most once)."""
    out = [{"provider": primary(), "model": "", "small_model": ""}]
    for e in db.get_setting("llm.failover") or []:
        p = str((e or {}).get("provider") or "")
        if not (p in ("claude_subscription", "anthropic", "chatgpt") or p in llm_openai.PRESETS):
            continue
        ent = {"provider": p, "model": str(e.get("model") or ""), "small_model": str(e.get("small_model") or "")}
        if _key(ent) not in [_key(x) for x in out]:
            out.append(ent)
    return out


def _models_of(e: dict[str, str]) -> tuple[str, str]:
    """(main, small) model an entry would use."""
    prev = _entry()
    _tls.entry = e
    try:
        if e["provider"] in CLAUDE:
            return _model(False), _model(True)
        return _other(False)[1], _other(True)[1]
    finally:
        _tls.entry = prev


def _classify(err: Exception) -> tuple[bool, float]:
    """(move on to the next service?, minutes to leave this one alone)."""
    msg = str(err)
    if isinstance(err, LLMRefused):
        return False, 0
    if UNSUPPORTED.search(msg):                       # this service cannot do this kind of call; it is fine for others
        return True, 0
    if isinstance(err, LLMUnavailable):
        return True, 30 if re.search(r"usage limit|limit reached|额度|欠费|quota|billing", msg, re.I) else 10
    if TRANSIENT.search(msg):
        return True, 2
    return False, 0


def rest(provider: str, until: float, why: str) -> None:
    """Leave a service alone until ``until`` (epoch seconds): its allowance is known to be used up."""
    with _lock:
        for e in chain():
            if e["provider"] == provider:
                _down[_key(e)] = (max(until, _down.get(_key(e), (0.0, ""))[0]), why[:300])


def _rest_minutes(e: dict[str, str], err: Exception, minutes: float) -> float:
    """How long to leave a failed service alone. When its allowance is used up and it says when the window resets, exactly that long."""
    if minutes < 30:
        return minutes
    try:
        from . import quota

        until = quota.reset_time(e["provider"])
        if until and 60 < until - time.time() < 8 * 86400:
            return (until - time.time()) / 60 + 1
    except Exception:  # noqa: BLE001
        pass
    return minutes


def reset_failover() -> None:
    with _lock:
        _down.clear()
        _announced.clear()


def failover_status() -> list[dict[str, Any]]:
    """The chain as the settings page shows it."""
    now_ = time.time()
    out = []
    for i, e in enumerate(chain()):
        until, why = _down.get(_key(e), (0.0, ""))
        main, small = _models_of(e)
        out.append({"provider": e["provider"], "name": label(e["provider"]), "role": "primary" if i == 0 else "backup", "model": main, "small_model": small,
                    "set_model": e["model"], "set_small_model": e["small_model"], "state": "cooling" if until > now_ else "ok",
                    "until": datetime.fromtimestamp(until).isoformat(timespec="minutes") if until > now_ else "", "reason": why if until > now_ else ""})
    return out


def _announce(frm: dict[str, str], to: dict[str, str], why: str) -> None:
    """Tell the user once that the work moved to a backup."""
    k = _key(frm)
    with _lock:
        if k in _announced:
            return
        _announced.add(k)
    log.warning("AI service %s is not usable (%s); using %s", frm["provider"], why[:160], to["provider"])
    try:
        from . import messages, notify

        until = _down.get(k, (0.0, ""))[0]
        notify.send("status_update", messages.llm_switched(label(frm["provider"]), label(to["provider"]), why, datetime.fromtimestamp(until).strftime("%H:%M") if until else ""), ref="config:llm")
    except Exception:  # noqa: BLE001 - a notification must not break the call that just succeeded
        log.debug("could not announce the switch", exc_info=True)


def _failover(call: Callable[[], Any]) -> Any:
    """Run ``call`` on the service in use; if that service is out, on each backup in turn."""
    if _entry() is not None:           # already inside an attempt (a call made by a tool of a running agent)
        return call()
    entries = chain()
    if len(entries) == 1:              # no backups: exactly the behaviour and the errors of before
        return call()
    now_ = time.time()
    ready = [e for e in entries if _down.get(_key(e), (0.0, ""))[0] <= now_]
    order = ready + [e for e in entries if e not in ready]     # a resting service is still tried last: better than giving up
    failed: list[tuple[dict[str, str], LLMError]] = []
    for n, e in enumerate(order):
        _tls.entry = e
        metering.attempt(n)
        try:
            out = call()
        except LLMError as err:
            go, minutes = _classify(err)
            if not go:
                raise
            failed.append((e, err))
            if minutes:
                minutes = _rest_minutes(e, err, minutes)
                with _lock:
                    _down[_key(e)] = (time.time() + minutes * 60, str(err)[:300])
            continue
        finally:
            _tls.entry = None
        with _lock:
            if _key(e) in _down and _down[_key(e)][0] <= time.time():
                _down.pop(_key(e), None)          # it works again
                _announced.discard(_key(e))
        if e is not entries[0]:
            why = next((str(x) for ent, x in failed if ent is entries[0]), "") or _down.get(_key(entries[0]), (0.0, ""))[1]
            _announce(entries[0], e, why)
        return out
    first = failed[0][1]
    detail = "；".join(f"{label(e['provider'])}: {str(x)[:160]}" for e, x in failed)
    raise (LLMUnavailable if any(isinstance(x, LLMUnavailable) for _, x in failed) else LLMError)(f"{first}. 所有配置的 AI 服务都试过了（{detail}）") from first


def try_entry(e: dict[str, str]) -> dict[str, Any]:
    """One short call on each of an entry's two models, for the "test" button."""
    out: dict[str, Any] = {"provider": e["provider"], "name": label(e["provider"])}
    for kind, small in (("main", False), ("small", True)):
        _tls.entry = e
        try:
            with metering.call("text", "connection_test"):
                out[kind] = {"ok": True, "model": _models_of(e)[1 if small else 0], "reply": _text("Reply with the single word: OK", system=None, small=small, max_tokens=50, effort=None)[:80]}
        except LLMError as err:
            out[kind] = {"ok": False, "model": _models_of(e)[1 if small else 0], "error": str(err)[:300]}
        finally:
            _tls.entry = None
    return out


def _oa(fn: Callable[[llm_openai.Client, str], Any], *, small: bool = False) -> Any:
    """Run one call against the configured OpenAI-compatible service, with this module's errors and usage counting."""
    p = provider()
    cfg, model = _other(small)
    try:
        c = llm_openai.Client(str(cfg.get("base_url") or llm_openai.PRESETS[p]["base_url"]), secrets.get(key_name(p)))
        try:
            return fn(c, model)
        finally:
            usage().count(c.calls, c.input_tokens, c.output_tokens)
            for r in c.log:      # every HTTP request of this call, the failed ones too
                cost = (r["usage"] or {}).get("cost") if isinstance(r.get("usage"), dict) else None      # some services (OpenRouter) say what the request cost
                metering.record(provider=p, model=r.get("model") or model, started=r["t0"], latency_ms=r.get("ms"), tokens=metering.openai_usage(r.get("usage")), raw=r.get("usage"),
                                reported_cost_usd=cost if isinstance(cost, (int, float)) else None, provider_request_id=r.get("id", ""), status=r.get("status", "ok"), error=r.get("error", ""))
            c.http.close()
    except llm_openai.Unavailable as e:
        raise LLMUnavailable(str(e)) from e
    except llm_openai.Failed as e:
        raise LLMError(str(e)) from e


def _codex(prompt: Any, *, small: bool, system: str | None, schema: dict[str, Any] | None = None, tools: list[Any] | None = None,
           on_step: Callable[[dict[str, Any]], None] | None = None, budget: agentbudget.Budget | None = None) -> tuple[str, list[dict[str, Any]], str]:
    _, model = _other(small)
    if not isinstance(prompt, str):
        prompt = llm_openai._content(prompt)
        if not isinstance(prompt, str):
            raise LLMError("用 ChatGPT 登录时不能发送图片。")
    t0 = time.time()
    try:
        out, steps, used, stopped = llm_codex.run(prompt, system=system, model=model, schema=schema, tools=tools, on_step=on_step, budget=budget,
                                                  base_url=str(db.get_setting("app.base_url") or "http://127.0.0.1:8000"))
    except (llm_codex.Unavailable, llm_codex.Failed) as e:
        err = (LLMUnavailable if isinstance(e, llm_codex.Unavailable) else LLMError)(str(e))
        _failed(model, t0, err)       # the command line reports usage only with an answer: what a failed turn used is not known
        raise err from e
    usage().count(1 + len(steps), used.get("input", 0), used.get("output", 0))
    metering.record(provider=provider(), model=model, started=t0, tokens=metering.codex_usage(used), raw=used, turns=1 + len(steps))
    return out, steps, stopped


def _sdk(content: Any, *, small: bool, system: str | None, effort: str | None, **kw: Any) -> llm_sdk.SDKResult:
    eff = effort or (None if small else str(db.get_setting("llm.effort")))
    model, t0 = _model(small), time.time()

    def used(r: Any) -> dict[str, Any]:      # what the command line reported for this query, for the usage record
        if r is None or r.usage is None:
            return {}
        return {"tokens": metering.anthropic_usage(r.usage), "raw": {"usage": r.usage, "model_usage": r.model_usage, "api_ms": r.api_ms, "session": r.session_id},
                "reported_cost_usd": r.cost_usd, "turns": max(1, r.turns), "provider_request_id": r.session_id}

    try:
        res = llm_sdk.call(content, system=system, model=model, effort=eff, token=secrets.get(secrets.CLAUDE_OAUTH_TOKEN), **kw)
    except llm_sdk.SDKError as e:
        if e.refused:
            err: LLMError = LLMRefused(str(e))
        elif e.unavailable:
            err = LLMUnavailable(f"Claude subscription login is not usable ({e}). Run `autoapply claude-login` or check Settings.")
        elif e.status == 429 or "limit" in str(e).lower():
            err = LLMUnavailable(f"Claude subscription usage limit reached: {e}")
        else:
            err = LLMError(f"Claude (subscription) error: {e}")
        _failed(model, t0, err, **used(getattr(e, "partial", None)))     # a query that failed part-way has still used what it reports
        raise err from e
    usage().count(max(1, res.turns), res.input_tokens, res.output_tokens)
    metering.record(provider=provider(), model=model, started=t0, **(used(res) or {"turns": max(1, res.turns)}))
    return res


def _create(*, small: bool, max_tokens: int, system: str | None, messages: list, effort: str | None = None, **extra: Any):
    model = _model(small)
    kwargs: dict[str, Any] = dict(model=model, max_tokens=max_tokens, messages=messages, **extra)
    if system:
        kwargs["system"] = system
    oc = dict(kwargs.pop("output_config", {}) or {})
    eff = effort or (None if small else str(db.get_setting("llm.effort")))
    if eff:
        oc["effort"] = eff
    if oc:
        kwargs["output_config"] = oc
    betas: list[str] = list(kwargs.pop("betas", []))
    # Server-side refusal fallback: Haiku has none, so only on the main model.
    if not small and db.get_setting("llm.fallbacks"):
        betas.append(FALLBACK_BETA)
        kwargs["fallbacks"] = "default"
    t0 = time.time()
    within = kwargs.pop("timeout", None)        # seconds this one request may take (an agent's budget); tried once, not again
    try:
        try:
            api = client().with_options(timeout=max(1.0, float(within)), max_retries=0) if within is not None else client()
            if betas:
                resp = api.beta.messages.create(betas=betas, **kwargs)
            else:
                resp = api.messages.create(**kwargs)
        except anthropic.AuthenticationError as e:
            raise LLMUnavailable("Claude API key is missing or invalid. Set it in Settings.") from e
        except anthropic.RateLimitError as e:
            raise LLMError(f"rate limited: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMUnavailable(f"cannot reach the Claude API: {e}") from e
        except TypeError as e:  # e.g. "Could not resolve authentication method"
            raise LLMUnavailable(str(e)) from e
    except LLMError as err:
        _failed(model, t0, err)        # nothing came back: whether it was billed is not known, so no usage and no cost are recorded
        raise
    usage().add(resp)
    try:
        raw = resp.usage.to_dict() if hasattr(resp.usage, "to_dict") else dict(getattr(resp.usage, "__dict__", {}) or {})
    except Exception:  # noqa: BLE001
        raw = None
    metering.record(provider=provider(), model=str(getattr(resp, "model", "") or model), started=t0, tokens=metering.anthropic_usage(raw), raw=raw,
                    provider_request_id=str(getattr(resp, "_request_id", "") or getattr(resp, "id", "") or ""), status="refused" if resp.stop_reason == "refusal" else "ok")
    if resp.stop_reason == "refusal":
        raise LLMRefused("the model declined this request")
    return resp


def _text_of(resp: Any) -> str:
    return "".join(b.text for b in resp.content if b.type == "text")


def text(prompt: str | list, *, system: str | None = None, small: bool = False, max_tokens: int = 16000, effort: str | None = None) -> str:
    with metering.call("text", metering.caller_feature(sys._getframe(1))):
        return _failover(lambda: _text(prompt, system=system, small=small, max_tokens=max_tokens, effort=effort))


def _text(prompt: str | list, *, system: str | None, small: bool, max_tokens: int, effort: str | None) -> str:
    if backend() == "openai":
        return _oa(lambda c, m: c.text(prompt, model=m, system=system, max_tokens=max_tokens), small=small)
    if backend() == "codex":
        return _codex(prompt, small=small, system=system)[0].strip()
    if backend() == "subscription":
        return _sdk(prompt, small=small, system=system, effort=effort).text.strip()
    resp = _create(small=small, max_tokens=max_tokens, system=system, effort=effort, messages=[{"role": "user", "content": prompt}])
    if resp.stop_reason == "max_tokens":
        raise LLMError("output truncated (max_tokens)")
    return _text_of(resp).strip()


def json(
    prompt: str | list,
    schema: dict[str, Any],
    *,
    system: str | None = None,
    small: bool = False,
    max_tokens: int = 16000,
    effort: str | None = None,
) -> Any:
    """Schema-constrained JSON. ``prompt`` may be a content-block list (documents, images)."""
    with metering.call("json", metering.caller_feature(sys._getframe(1))):
        return _failover(lambda: _json_call(prompt, schema, system=system, small=small, max_tokens=max_tokens, effort=effort))


def _json_call(prompt: str | list, schema: dict[str, Any], *, system: str | None, small: bool, max_tokens: int, effort: str | None) -> Any:
    if backend() == "openai":
        return _oa(lambda c, m: c.json(prompt, schema, model=m, system=system, max_tokens=max_tokens), small=small)
    if backend() == "codex":
        raw = _codex(prompt, small=small, system=system, schema=schema)[0]
        try:
            return llm_openai._parse_json(raw)
        except ValueError as e:
            raise LLMError(f"model returned no structured output: {raw[:200]}") from e
    if backend() == "subscription":
        # The CLI returns structured output through a tool call, so it needs more than one turn.
        res = _sdk(prompt, small=small, system=system, effort=effort, schema=schema, max_turns=4)
        if res.structured is not None:
            return res.structured
        try:
            return _json.loads(res.text)
        except _json.JSONDecodeError as e:
            raise LLMError(f"model returned no structured output: {res.text[:200]}") from e
    resp = _create(
        small=small,
        max_tokens=max_tokens,
        system=system,
        effort=effort,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    if resp.stop_reason == "max_tokens":
        raise LLMError("output truncated (max_tokens)")
    raw = _text_of(resp)
    try:
        return _json.loads(raw)
    except _json.JSONDecodeError as e:
        raise LLMError(f"model returned invalid JSON: {raw[:200]}") from e


def obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    """Shorthand for a strict object schema."""
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }


# --- content helpers -----------------------------------------------------------


def pdf_block(path: str | Path) -> dict[str, Any]:
    data = base64.standard_b64encode(Path(path).read_bytes()).decode()
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}


def image_block(png: bytes) -> dict[str, Any]:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(png).decode()}}


# --- agent loop ----------------------------------------------------------------


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[..., Any]  # returns str | list[content blocks]

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


@dataclass
class AgentResult:
    final_text: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    stopped: str = "end_turn"      # how it ended: end_turn (by itself) | max_steps | timeout (agentbudget.py) | what the service said
    budget: dict[str, Any] = field(default_factory=dict)      # what it spent of what it had (Budget.summary)

    def said(self) -> str:
        """What the agent said last - or, when it was stopped before it could, why it was stopped, in words."""
        if self.final_text:
            return self.final_text
        b = self.budget or {}
        if self.stopped == "max_steps":
            return f"stopped: it used all {b.get('of', '')} tool calls this kind of work is given".replace("  ", " ")
        if self.stopped == "timeout":
            return f"stopped: it ran out of the {round((b.get('limit_seconds') or 0) / 60) or ''} minutes this kind of work is given".replace("  ", " ")
        return self.stopped


def agent(
    goal: str,
    tools: list[Tool],
    *,
    system: str,
    kind: str = "",
    on_step: Callable[[dict[str, Any]], None] | None = None,
    budget: agentbudget.Budget | None = None,
) -> AgentResult:
    """Manual tool-use loop (kept manual so tool results can carry screenshots
    and every call is recorded on the run).

    ``kind`` names the work ("explore_form", "take_over", ...): it decides how many tool calls and how long the agent
    is given (the setting agent.budgets). There is one budget for the whole of it, counted here - every tool the model
    is handed goes through ``spend`` - so it is the same for every service, and a backup that takes over goes on with
    what is left. How the run ended is in ``stopped``.

    If the service gives out part-way and a backup takes over, the backup starts the task again and is told that an
    earlier attempt already acted, so it looks at the current state first instead of repeating steps."""
    budget = budget or agentbudget.for_kind(kind)
    acted = {"n": 0}

    def counted(fn: Callable[..., Any]) -> Callable[..., Any]:
        def run(**kw: Any) -> Any:
            budget.spend()      # the one place a tool call is counted; raises agentbudget.Spent when it is not covered
            acted["n"] += 1
            return fn(**kw)
        return run

    watched = [Tool(t.name, t.description, t.input_schema, counted(t.fn)) for t in tools]

    def attempt() -> AgentResult:
        g = goal if not acted["n"] else goal + ("\n\n[An earlier attempt at this task was cut off after it had already acted. Look at the current state first "
                                                "(read the page, list the controls) and carry on from there; do not repeat what is already done.]")
        return _agent(g, watched, system=system, budget=budget, on_step=on_step)

    with metering.call("agent", metering.caller_feature(sys._getframe(1))):
        res = _failover(attempt)
    res.stopped = budget.ended or res.stopped
    res.budget = {**budget.summary(), "ended": res.stopped}
    if budget.ended:
        log.info("agent (%s) stopped: %s after %s tool calls, %ss", budget.kind or "?", budget.ended, budget.used, res.budget["seconds"])
    return res


def _agent(goal: str, tools: list[Tool], *, system: str, budget: agentbudget.Budget, on_step: Callable[[dict[str, Any]], None] | None) -> AgentResult:
    if backend() == "openai":
        final, steps, stopped = _oa(lambda c, m: c.agent(goal, tools, model=m, system=system, budget=budget, on_step=on_step))
        return AgentResult(final_text=final, steps=steps, stopped=stopped)
    if backend() == "codex":
        final, steps, stopped = _codex(goal, small=False, system=system, tools=tools, on_step=on_step, budget=budget)
        return AgentResult(final_text=final, steps=steps, stopped=stopped)
    if backend() == "subscription":
        res = _sdk(goal, small=False, system=system, effort=None, tools=tools, max_turns=None, on_step=on_step, budget=budget)
        return AgentResult(final_text=res.text, steps=res.steps, stopped=res.stopped)
    by_name = {t.name: t for t in tools}
    messages: list[dict[str, Any]] = [{"role": "user", "content": goal}]
    result = AgentResult(final_text="")
    while True:
        if budget.expired():
            result.stopped = budget.ended
            return result
        # (the request is given what is left of the budget and no more; an answer that comes after it is not in time)
        try:
            resp = _create(small=False, max_tokens=16000, system=system, messages=messages, tools=[t.spec() for t in tools], timeout=budget.left())
        except LLMError:
            if budget.expired():
                result.stopped = budget.ended
                return result
            raise
        if budget.expired():
            result.stopped = budget.ended
            return result
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "pause_turn":
            continue
        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:
            result.final_text = _text_of(resp)
            result.stopped = resp.stop_reason or "end_turn"
            return result
        tool_results = []
        for call in calls:
            step: dict[str, Any] = {"tool": call.name, "input": call.input}
            tool = by_name.get(call.name)
            began = time.monotonic()
            try:
                if tool is None:
                    budget.spend()      # a call to a tool that is not there is a step too: it must not go on for ever
                    raise KeyError(f"unknown tool {call.name}")
                out = tool.fn(**(call.input or {}))
                content = out if isinstance(out, list) else str(out)
                step["ok"] = True
                step["output"] = content if isinstance(content, str) else "[blocks]"
                tool_results.append({"type": "tool_result", "tool_use_id": call.id, "content": content})
            except agentbudget.Spent as e:      # not an error for the model to work around: the run ends here
                result.stopped = e.why
                return result
            except Exception as e:  # noqa: BLE001 - errors go back to the model
                step["ok"] = False
                step["output"] = f"{type(e).__name__}: {e}"
                tool_results.append({"type": "tool_result", "tool_use_id": call.id, "content": step["output"], "is_error": True})
            if isinstance(step.get("output"), str):
                step["output"] = step["output"][:2000]
            step["ms"] = int((time.monotonic() - began) * 1000)
            result.steps.append(step)
            if on_step:
                on_step(step)
        messages.append({"role": "user", "content": tool_results})
