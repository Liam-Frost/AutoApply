"""What every model call used and what it cost.

One row in ``llm_requests`` per request to an AI service, written by ``llm.py`` at the one place each back end is
called. A row says which service and model answered, which feature of the program asked, which task (workflow
execution) it belonged to, how long it took, how it ended, and how many tokens of each kind it used.

Three things are kept apart on purpose:

* **request** - one call to a service. For the Claude and ChatGPT subscriptions the unit is one query of their command
  line, which may contain several model turns (``turns``); the usage they report is for the whole query.
* **logical call** (``call_id``) - one ``llm.text`` / ``llm.json`` / ``llm.agent``. An agent run on an API back end is
  many requests with one ``call_id``; so are the attempts on backup services after the first one failed (``attempt``).
* **workflow execution** (``task_id``) - the task that asked. What a task achieved is on the task, not here.

Tokens are counted one way for every service (``Tokens``): prompt tokens that were neither read from nor written to a
cache, tokens read from the cache, tokens written to it, and everything the model wrote. Nothing is counted twice:
services that include cached tokens in their prompt count have them subtracted, reasoning tokens are a part of the
output and never added to it. What the service reported is kept word for word in ``raw``.

Cost is an **estimate at list price** unless the service reports a cost itself. It is stored in millionths of a dollar
as an integer, so sums are exact. A call on a subscription costs nothing extra; its estimate says what the same call
would have cost on the pay-as-you-go API. A call whose tokens are not known, or whose model has no price, has no cost:
it is never counted as zero.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from . import db

log = logging.getLogger("autoapply.metering")
_tls = threading.local()

# Which feature of the program a call belongs to, by where it was made. A call from a module that is not listed is
# named after that module, so a new feature shows up by itself.
CALLERS: dict[tuple[str, str], str] = {
    ("scoring", ""): "scoring", ("answers", ""): "answers", ("generic", "sign_in"): "sign_in", ("generic", ""): "explore_form",
    ("repair", "advance"): "navigate", ("repair", ""): "take_over", ("mail", ""): "mail_triage", ("materials", ""): "cover_letter",
    ("tailor", ""): "tailor_resume", ("drafts", ""): "revise_draft", ("persona", ""): "intake_rules", ("profile_init", ""): "profile_setup",
    ("sources.watch", ""): "careers_page", ("api.main", ""): "connection_test",
}
FEATURES: dict[str, str] = {
    "scoring": "给岗位评分", "answers": "回答申请表的问题", "explore_form": "探索申请表", "sign_in": "登录或注册网站", "take_over": "接手填表",
    "navigate": "表单翻页", "mail_triage": "邮件分类", "cover_letter": "写求职信", "tailor_resume": "定制简历", "revise_draft": "按意见修改草案",
    "intake_rules": "生成筛选规则", "profile_setup": "建立个人资料", "careers_page": "读取招聘页面", "connection_test": "连接测试", "": "未区分功能",
}
WORKFLOWS: dict[str, str] = {
    "discover": "扫描新岗位", "score": "给岗位评分", "recon": "读取申请表、生成草案", "tailor": "按岗位调整简历", "revise": "按意见修改草案",
    "reanswer": "重新回答问题", "execute": "填写申请表", "mail": "查收邮件", "canary": "驱动巡检", "": "任务之外",
}
SUBSCRIPTIONS = ("claude_subscription", "chatgpt")


def feature_label(key: str) -> str:
    return FEATURES.get(key) or key


def workflow_label(key: str) -> str:
    return WORKFLOWS.get(key) or key


# --- context: who is asking ---------------------------------------------------------------------


def _ctx() -> dict[str, Any]:
    if not hasattr(_tls, "ctx"):
        _tls.ctx = {}
    return _tls.ctx


def begin_task(task_id: int, kind: str, ref: str) -> None:
    """The worker thread starts a task: every request made until ``end_task`` belongs to it."""
    _tls.ctx = {"task_id": task_id, "workflow": kind, "ref": ref or "", "stages": []}


def end_task() -> list[dict[str, str]]:
    stages = list(_ctx().get("stages") or [])
    _tls.ctx = {}
    return stages


def stage(name: str) -> None:
    """Mark that the running task has reached a stage (kept on the task, so a failure can be placed)."""
    st = _ctx().get("stages")
    if st is not None and name and (not st or st[-1]["stage"] != name) and len(st) < 60:
        st.append({"stage": name, "at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")})


def caller_feature(frame: Any) -> str:
    """The feature a call belongs to, from the module and function that made it."""
    try:
        mod = str(frame.f_globals.get("__name__", "")).removeprefix("autoapply.")
        fn = frame.f_code.co_name
    except Exception:  # noqa: BLE001
        return ""
    return CALLERS.get((mod, fn)) or CALLERS.get((mod, "")) or mod


@contextlib.contextmanager
def feature(name: str) -> Iterator[None]:
    """Name the feature for the calls made inside (overrides what the caller's module would give)."""
    c = _ctx()
    prev = c.get("feature")
    c["feature"] = name
    try:
        yield
    finally:
        if prev is None:
            c.pop("feature", None)
        else:
            c["feature"] = prev


@contextlib.contextmanager
def call(kind: str, default_feature: str = "") -> Iterator[None]:
    """One logical call (``llm.text`` / ``json`` / ``agent``): its requests and its retries share a ``call_id``."""
    c = _ctx()
    saved = {k: c.get(k) for k in ("call_id", "attempt", "kind", "call_feature")}
    c.update(call_id=uuid.uuid4().hex, attempt=0, kind=kind, call_feature=c.get("feature") or default_feature)
    stage(c["call_feature"])
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                c.pop(k, None)
            else:
                c[k] = v


def attempt(n: int) -> None:
    _ctx()["attempt"] = n


# --- tokens: one way of counting -----------------------------------------------------------------


@dataclass
class Tokens:
    input: int | None = None        # prompt tokens neither read from nor written to a cache
    cache_read: int | None = None
    cache_write: int | None = None
    output: int | None = None       # everything the model wrote, reasoning included
    reasoning: int | None = None    # a part of ``output``, kept for information; never added to it
    detail: str = "full"            # full | no_cache_split (cached tokens, if any, are inside ``input``) | none

    @property
    def total(self) -> int | None:
        if self.detail == "none":
            return None
        return sum(int(x or 0) for x in (self.input, self.cache_read, self.cache_write, self.output))


def _i(v: Any) -> int:
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


def anthropic_usage(u: dict[str, Any] | None) -> Tokens:
    """The Anthropic API and the Claude command line: ``input_tokens`` already excludes cached tokens."""
    if not u:
        return Tokens(detail="none")
    return Tokens(input=_i(u.get("input_tokens")), cache_read=_i(u.get("cache_read_input_tokens")), cache_write=_i(u.get("cache_creation_input_tokens")),
                  output=_i(u.get("output_tokens")))


def openai_usage(u: dict[str, Any] | None) -> Tokens:
    """OpenAI-compatible services: ``prompt_tokens`` includes cached tokens, ``completion_tokens`` includes reasoning."""
    if not u or ("prompt_tokens" not in u and "completion_tokens" not in u):
        return Tokens(detail="none")
    prompt, out = _i(u.get("prompt_tokens")), _i(u.get("completion_tokens"))
    pd, cd = u.get("prompt_tokens_details") or {}, u.get("completion_tokens_details") or {}
    cached = pd.get("cached_tokens", u.get("prompt_cache_hit_tokens"))      # the second name is DeepSeek's
    written = pd.get("cache_write_tokens", pd.get("cache_creation_tokens"))
    reasoning = _i(cd.get("reasoning_tokens")) if cd.get("reasoning_tokens") is not None else None
    if cached is None:
        return Tokens(input=prompt, output=out, reasoning=reasoning, detail="no_cache_split")
    cached, written = min(_i(cached), prompt), _i(written)
    return Tokens(input=max(0, prompt - cached - min(written, prompt - cached)), cache_read=cached, cache_write=min(written, prompt - cached), output=out, reasoning=reasoning)


def codex_usage(u: dict[str, Any] | None) -> Tokens:
    """The ChatGPT command line reports a breakdown per thread. Whether its input count includes the cached part, and
    its output count the reasoning, is read from its own total instead of assumed."""
    if not u or not any(u.get(k) for k in ("input", "output", "total")):
        return Tokens(detail="none")
    inp, out, cached, written, reasoning, total = (_i(u.get(k)) for k in ("input", "output", "cached", "cache_write", "reasoning", "total"))
    # Four ways the parts can relate to the total; the one that adds up is the one in use. Without a total that settles
    # it, the OpenAI convention is assumed: cached tokens inside the input count, reasoning inside the output count.
    cached_beside = reasoning_beside = False
    if total and total != inp + out:
        for cb, rb in ((False, True), (True, False), (True, True)):
            if total == inp + out + (cached + written if cb else 0) + (reasoning if rb else 0):
                cached_beside, reasoning_beside = cb, rb
                break
    if reasoning_beside:
        out += reasoning
    if cached_beside:
        return Tokens(input=inp, cache_read=cached, cache_write=written, output=out, reasoning=reasoning or None)
    cached = min(cached, inp)
    written = min(written, inp - cached)
    return Tokens(input=inp - cached - written, cache_read=cached, cache_write=written, output=out, reasoning=reasoning or None)


# --- prices and cost ----------------------------------------------------------------------------

_table: dict[str, Any] | None = None


def price_table() -> dict[str, Any]:
    global _table
    if _table is None:
        _table = json.loads((Path(__file__).with_name("pricing.json")).read_text(encoding="utf-8"))
    return _table


def user_prices() -> list[dict[str, Any]]:
    return [p for p in (db.get_setting("llm.prices") or []) if isinstance(p, dict) and p.get("model")]


def _num(v: Any) -> Decimal | None:
    try:
        return None if v in (None, "") else Decimal(str(v))
    except Exception:  # noqa: BLE001
        return None


def price_for(provider: str, model: str) -> dict[str, Any] | None:
    """Price per million tokens for a model: the user's own entry first, then the built-in list.
    Returns {input, output, cache_read, cache_write, source, version, over?} with Decimal values, or None."""
    t = price_table()
    rc, rw = Decimal(str(t["defaults"]["cache_read_ratio"])), Decimal(str(t["defaults"]["cache_write_ratio"]))

    def shaped(e: dict[str, Any], source: str, version: str) -> dict[str, Any] | None:
        pin, pout = _num(e.get("input")), _num(e.get("output"))
        if pin is None or pout is None:
            return None
        out = {"input": pin, "output": pout, "cache_read": _num(e.get("cache_read")) if _num(e.get("cache_read")) is not None else pin * rc,
               "cache_write": _num(e.get("cache_write")) if _num(e.get("cache_write")) is not None else pin * rw, "source": source, "version": version}
        if isinstance(e.get("over"), dict) and _num(e["over"].get("input")) is not None:
            o = e["over"]
            out["over"] = {"prompt_tokens": _i(o.get("prompt_tokens")), "input": _num(o["input"]), "output": _num(o.get("output")) or pout}
        return out

    m = (model or "").strip().lower()
    if not m:
        return None
    for e in user_prices():
        if str(e["model"]).strip().lower() == m and (not e.get("provider") or e["provider"] == provider):
            got = shaped(e, "user_price", "user")
            if got:
                return got
    best = None
    for e in t["models"]:
        k = str(e["match"]).lower()
        # the model itself, or the same model with a date or a context-window suffix - never "a model whose name starts the same"
        if provider in (e.get("providers") or [provider]) and (m == k or re.fullmatch(re.escape(k) + r"(-20\d{6}|@20\d{6}|\[[^\]]*\])", m)):
            if best is None or len(k) > len(str(best["match"])):
                best = e
    return shaped(best, "list_price", str(t["version"])) if best else None


def cost_micros(tk: Tokens, price: dict[str, Any] | None, *, turns: int = 1) -> int | None:
    """Estimated cost in millionths of a dollar. None when it cannot be told (no usage, no price)."""
    if price is None or tk.detail == "none":
        return None
    pin, pout = price["input"], price["output"]
    over = price.get("over")
    prompt = _i(tk.input) + _i(tk.cache_read) + _i(tk.cache_write)
    if over and turns <= 1 and prompt > over["prompt_tokens"]:     # a long-prompt tier applies per request; a multi-turn query cannot be split
        scale = over["input"] / pin if pin else Decimal(1)
        pin, pout = over["input"], over["output"]
        cr, cw = price["cache_read"] * scale, price["cache_write"] * scale
    else:
        cr, cw = price["cache_read"], price["cache_write"]
    # price is dollars per million tokens, so tokens x price is exactly millionths of a dollar
    total = _i(tk.input) * pin + _i(tk.cache_read) * cr + _i(tk.cache_write) * cw + _i(tk.output) * pout
    return int(total.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def class_costs(tk: Tokens, price: dict[str, Any] | None) -> dict[str, int] | None:
    """How a request's cost at list price divides over the kinds of token (for the 'share of cost' view)."""
    if price is None or tk.detail != "full":
        return None
    return {"input": int(_i(tk.input) * price["input"]), "cache_read": int(_i(tk.cache_read) * price["cache_read"]),
            "cache_write": int(_i(tk.cache_write) * price["cache_write"]), "output": int(_i(tk.output) * price["output"])}


def billing(provider: str) -> str:
    """How a service is paid for: subscription (a fixed fee, a call adds nothing), metered (per token), local (free)."""
    if provider in SUBSCRIPTIONS:
        return "subscription"
    if not provider:
        return "unknown"
    try:
        cfg = (db.get_setting("llm.providers") or {}).get(provider) or {}
        host = (urlparse(str(cfg.get("base_url") or "")).hostname or "").lower()
        if host in ("localhost", "127.0.0.1", "::1", "host.docker.internal") or host.endswith(".local") or re.match(r"^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)", host):
            return "local"
    except Exception:  # noqa: BLE001
        pass
    return "metered"


# --- writing a record ---------------------------------------------------------------------------


def record(*, provider: str, model: str, started: float, tokens: Tokens | None = None, raw: Any = None, reported_cost_usd: float | None = None,
           turns: int = 1, provider_request_id: str = "", status: str = "ok", error: str = "", error_type: str = "", latency_ms: int | None = None) -> None:
    """Keep one request. Never raises: bookkeeping must not fail the call it describes."""
    try:
        from .models import LLMRequest

        c = _ctx()
        tk = tokens or Tokens(detail="none")
        price = price_for(provider, model)
        cost, source, version = None, "", ""
        if reported_cost_usd is not None:
            cost, source = int((Decimal(str(reported_cost_usd)) * 1_000_000).quantize(Decimal(1), rounding=ROUND_HALF_UP)), "provider"
        elif price is not None and tk.detail != "none":
            cost, source, version = cost_micros(tk, price, turns=turns), price["source"], price["version"]
        ref = str(c.get("ref") or "")
        m = re.match(r"^(job|application):(\d+)$", ref)
        known = tk.detail != "none"
        with db.session() as s:
            s.add(LLMRequest(
                request_id=uuid.uuid4().hex, call_id=str(c.get("call_id") or uuid.uuid4().hex), attempt=int(c.get("attempt") or 0),
                started_at=datetime.fromtimestamp(started, timezone.utc).replace(tzinfo=None),
                latency_ms=latency_ms if latency_ms is not None else max(0, int((time.time() - started) * 1000)),
                provider=provider or "", model=model or "", billing=billing(provider), kind=str(c.get("kind") or ""),
                feature=str(c.get("call_feature") or c.get("feature") or ""), task_id=c.get("task_id"), workflow=str(c.get("workflow") or ""), ref=ref,
                job_id=int(m.group(2)) if m and m.group(1) == "job" else None, application_id=int(m.group(2)) if m and m.group(1) == "application" else None,
                status=status or "ok", error_type=error_type[:80], error=error[:400], turns=max(1, int(turns or 1)),
                input_tokens=tk.input if known else None, cache_read_tokens=tk.cache_read if known and tk.detail == "full" else None,
                cache_write_tokens=tk.cache_write if known and tk.detail == "full" else None, output_tokens=tk.output if known else None,
                reasoning_tokens=tk.reasoning, detail=tk.detail, cost_micros=cost, currency="USD", cost_source=source, pricing_version=version,
                provider_request_id=str(provider_request_id or "")[:120], raw=raw if isinstance(raw, (dict, list)) else None, source="live"))
    except Exception:  # noqa: BLE001
        log.debug("could not record a model request", exc_info=True)


# --- history and re-pricing ---------------------------------------------------------------------


def import_legacy() -> int:
    """Before requests were recorded one by one, each task kept only a total: how many calls, how many prompt and output
    tokens. Those totals are carried over as one row per task, marked ``legacy``: no model, no cache split, no cost -
    none of that can be recovered, and none of it is made up."""
    from .models import LLMRequest, Run, Task

    n = 0
    with db.session() as s:
        have = {r[0] for r in s.query(LLMRequest.provider_request_id).filter(LLMRequest.source == "legacy")}
        for r in s.query(Run).filter(Run.kind == "llm"):
            key = f"run:{r.id}"
            if key in have:
                continue
            t = s.get(Task, r.task_id) if r.task_id else None
            m = re.match(r"^(job|application):(\d+)$", r.ref or "")
            s.add(LLMRequest(request_id=uuid.uuid4().hex, call_id=uuid.uuid4().hex, attempt=0, started_at=(t.started_at if t and t.started_at else r.created_at),
                             latency_ms=None, provider="", model="", billing="unknown", kind="", feature="", task_id=r.task_id, workflow=t.kind if t else "", ref=r.ref or "",
                             job_id=int(m.group(2)) if m and m.group(1) == "job" else None, application_id=int(m.group(2)) if m and m.group(1) == "application" else None,
                             status="unknown", turns=max(1, int(r.llm_calls or 1)), input_tokens=int(r.input_tokens or 0), output_tokens=int(r.output_tokens or 0),
                             detail="no_cache_split", cost_micros=None, currency="USD", cost_source="", pricing_version="", provider_request_id=key, raw=None, source="legacy"))
            n += 1
    return n


def reprice() -> int:
    """Prices were added or changed: estimate again every request whose cost comes from a price list (never one the
    service reported itself, never one without usage or without a model)."""
    from .models import LLMRequest

    n = 0
    with db.session() as s:
        for r in s.query(LLMRequest).filter(LLMRequest.cost_source != "provider", LLMRequest.source == "live", LLMRequest.detail != "none", LLMRequest.model != ""):
            price = price_for(r.provider, r.model)
            tk = Tokens(input=r.input_tokens, cache_read=r.cache_read_tokens, cache_write=r.cache_write_tokens, output=r.output_tokens, detail=r.detail)
            new = (cost_micros(tk, price, turns=r.turns), price["source"], price["version"]) if price else (None, "", "")
            if (r.cost_micros, r.cost_source, r.pricing_version) != new:
                r.cost_micros, r.cost_source, r.pricing_version = new
                n += 1
    return n
