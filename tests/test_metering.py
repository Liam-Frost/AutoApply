"""What every model call used and what it cost: one way of counting tokens, cost that is never made up, and the three
views of the analysis page built on those records."""

from datetime import timedelta

import pytest


def test_tokens_are_counted_one_way_and_nothing_twice():
    from autoapply import metering as m

    # Anthropic: the prompt count already excludes the cached part
    a = m.anthropic_usage({"input_tokens": 100, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 50, "output_tokens": 20})
    assert (a.input, a.cache_read, a.cache_write, a.output, a.total) == (100, 900, 50, 20, 1070)
    # OpenAI-compatible: the prompt count includes the cached part, the completion count includes the reasoning
    o = m.openai_usage({"prompt_tokens": 1000, "completion_tokens": 200, "prompt_tokens_details": {"cached_tokens": 600}, "completion_tokens_details": {"reasoning_tokens": 150}})
    assert (o.input, o.cache_read, o.output, o.reasoning, o.total) == (400, 600, 200, 150, 1200)       # not 1800, and reasoning is not added to the output
    d = m.openai_usage({"prompt_tokens": 1000, "completion_tokens": 10, "prompt_cache_hit_tokens": 300, "prompt_cache_miss_tokens": 700})   # DeepSeek's names
    assert (d.input, d.cache_read) == (700, 300)
    # a service that does not say how much was cached: the split is not invented
    n = m.openai_usage({"prompt_tokens": 1000, "completion_tokens": 10})
    assert n.detail == "no_cache_split" and n.input == 1000 and n.cache_read is None
    # no usage at all is "not known", not zero
    assert m.openai_usage({}).detail == "none" and m.openai_usage(None).total is None and m.anthropic_usage(None).detail == "none"
    # the ChatGPT command line: which convention it follows is read from its own total
    inside = m.codex_usage({"input": 1000, "output": 200, "cached": 600, "cache_write": 0, "reasoning": 50, "total": 1200})
    beside = m.codex_usage({"input": 400, "output": 150, "cached": 600, "cache_write": 0, "reasoning": 50, "total": 1200})
    assert (inside.input, inside.cache_read, inside.output, inside.total) == (400, 600, 200, 1200)
    assert (beside.input, beside.cache_read, beside.output, beside.total) == (400, 600, 200, 1200)


def test_cost_comes_from_a_price_or_from_the_service_and_is_never_guessed(app_env):
    from autoapply import db, metering as m

    p = m.price_for("anthropic", "claude-opus-5-5")
    t = m.Tokens(input=1000, cache_read=10000, cache_write=2000, output=500)
    assert m.cost_micros(t, p) == 1000 * 4 + 10000 * 0.2 + 2000 * 5 + 500 * 20 == 26000          # millionths of a dollar, exact
    assert m.price_for("claude_subscription", "claude-opus-5-5[1m]")["source"] == "list_price"   # the same model with a context-window suffix
    # a model that merely starts the same, and another service's model of the same name, have no price here
    assert m.price_for("anthropic", "claude-opus-5-9") is None and m.price_for("openrouter", "claude-opus-5-5") is None
    assert m.cost_micros(t, None) is None and m.cost_micros(m.Tokens(detail="none"), p) is None    # no price or no usage: no cost, not zero
    # the long-prompt tier of a model applies to a single request over the threshold
    h = m.price_for("anthropic", "claude-haiku-5-5")
    assert m.cost_micros(m.Tokens(input=50_000, output=1000), h) == 50_000 * 0.1 + 1000 * 0.5
    assert m.cost_micros(m.Tokens(input=200_000, output=1000), h) == 200_000 * 0.5 + 1000 * 2.5
    # the user's own price for a model the list does not know
    db.set_setting("llm.prices", [{"model": "deepseek-big", "input": 0.5, "output": 2}])
    u = m.price_for("deepseek", "deepseek-big")
    assert u["source"] == "user_price" and m.cost_micros(m.Tokens(input=1_000_000, output=0, detail="no_cache_split"), u) == 500_000
    # how a service is paid for
    db.set_setting("llm.providers", {"custom": {"base_url": "http://localhost:11434/v1"}})
    assert [m.billing(x) for x in ("claude_subscription", "chatgpt", "anthropic", "deepseek", "custom")] == ["subscription", "subscription", "metered", "metered", "local"]


@pytest.fixture
def services(app_env, monkeypatch):
    """The Claude subscription in use and DeepSeek as a backup; both are stand-ins that answer with a usage report."""
    import httpx

    from autoapply import db, llm, llm_openai, llm_sdk, notify

    db.set_setting("llm.provider", "claude_subscription")
    db.set_setting("llm.providers", {"deepseek": {"base_url": "https://api.deepseek.example/v1", "model": "deepseek-big", "small_model": "deepseek-big"}})
    db.set_setting("llm.failover", [{"provider": "deepseek", "model": "", "small_model": ""}])
    llm.reset_failover()
    state = {"claude": "ok", "http": 200}

    def sdk_call(content, *, system, model, **kw):
        if state["claude"] == "limit":      # the query ran two turns before the limit was hit: it reports what it used
            e = llm_sdk.SDKError("usage limit reached", status=429)
            e.partial = llm_sdk.SDKResult(turns=2, usage={"input_tokens": 10, "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 0, "output_tokens": 30}, cost_usd=0.0021, session_id="s-1")
            raise e
        return llm_sdk.SDKResult(text="ok", structured={"a": 1}, turns=3, input_tokens=6100, output_tokens=400, session_id="s-2", cost_usd=0.0125,
                                 usage={"input_tokens": 100, "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 1000, "output_tokens": 400})

    def handler(request):
        if state["http"] != 200:
            return httpx.Response(state["http"], text="server error")
        return httpx.Response(200, json={"id": "cmpl-1", "model": "deepseek-big", "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 1000, "completion_tokens": 200, "prompt_tokens_details": {"cached_tokens": 600}}})

    real = llm_openai.Client
    monkeypatch.setattr(llm_sdk, "call", sdk_call)
    monkeypatch.setattr(llm_openai, "Client", lambda base, key, **kw: real(base, key, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(notify, "send", lambda *a, **k: True)
    yield state
    llm.reset_failover()


def _rows():
    from autoapply import db
    from autoapply.models import LLMRequest

    with db.session() as s:
        return s.query(LLMRequest).order_by(LLMRequest.id).all()


def test_every_request_is_recorded_with_who_asked_what_it_used_and_what_it_cost(services):
    from autoapply import db, llm, metering
    from autoapply.models import Task

    with db.session() as s:
        s.add(Task(id=7, kind="score", ref="job:12", status="running"))
    metering.begin_task(7, "score", "job:12")
    try:
        assert llm.json("score this", {"type": "object"}) == {"a": 1}
    finally:
        metering.end_task()
    (r,) = _rows()
    assert (r.provider, r.model, r.billing, r.kind, r.status) == ("claude_subscription", "claude-opus-5-5", "subscription", "json", "ok")
    assert (r.task_id, r.workflow, r.ref, r.job_id) == (7, "score", "job:12", 12)
    assert r.feature == "test_metering"                                      # named after the module that asked, when it is not a known feature
    assert (r.input_tokens, r.cache_read_tokens, r.cache_write_tokens, r.output_tokens, r.turns) == (100, 5000, 1000, 400, 3)
    assert (r.cost_micros, r.cost_source) == (12500, "provider")              # what the command line reported, not a second estimate on top
    assert r.raw["usage"]["cache_read_input_tokens"] == 5000 and r.latency_ms is not None

    with llm.feature("scoring"):                                               # a feature can also be named by the caller
        llm.text("again")
    assert _rows()[-1].feature == "scoring" and _rows()[-1].task_id is None and _rows()[-1].call_id != r.call_id


def test_a_failed_attempt_and_the_backup_that_answered_are_two_requests_of_one_call(services):
    from autoapply import db, llm

    services["claude"] = "limit"
    assert llm.text("hi") == "hello"
    first, second = _rows()
    assert first.call_id == second.call_id and (first.attempt, second.attempt) == (0, 1)
    # the attempt that failed part-way is kept with what it had used; it is not counted as a success and not dropped
    assert (first.status, first.provider, first.turns, first.cache_read_tokens, first.cost_micros) == ("rate_limited", "claude_subscription", 2, 5000, 2100)
    # the backup: cached tokens taken out of the prompt count; no price for this model, so no cost - not zero
    assert (second.status, second.provider, second.model, second.billing) == ("ok", "deepseek", "deepseek-big", "metered")
    assert (second.input_tokens, second.cache_read_tokens, second.output_tokens, second.cost_micros, second.provider_request_id) == (400, 600, 200, None, "cmpl-1")

    # the user enters a price: the request that had none is estimated, the one the service reported stays as it was
    from fastapi.testclient import TestClient

    from autoapply.api.main import app

    c = TestClient(app)
    assert c.put("/api/analytics/ai/prices", json={"prices": [{"model": "deepseek-big", "input": 0.5, "output": 2, "cache_read": 0.05}]}).json()["repriced"] == 1
    first, second = _rows()
    assert second.cost_micros == round(400 * 0.5 + 600 * 0.05 + 200 * 2) == 630 and second.cost_source == "user_price" and first.cost_micros == 2100
    assert c.put("/api/analytics/ai/prices", json={"prices": [{"model": "x", "input": "abc", "output": 1}]}).status_code == 400
    assert db.get_setting("llm.prices")[0]["model"] == "deepseek-big"          # a rejected list changes nothing

    # a request that got no answer at all: recorded as failed, usage and cost not known
    services["http"], services["claude"] = 500, "limit"
    llm.reset_failover()
    with pytest.raises(llm.LLMError):
        llm.text("hi")
    last = _rows()[-1]
    assert (last.provider, last.status, last.detail, last.input_tokens, last.cost_micros) == ("deepseek", "error", "none", None, None)


def test_the_status_history_of_an_application_is_kept(app_env):
    from autoapply import db
    from autoapply.models import Application, ApplicationEvent, Job

    with db.session() as s:
        j = Job(source="manual", source_id="h1", company="A", title="B")
        s.add(j)
        s.flush()
        a = Application(job_id=j.id, status="submitted")
        s.add(a)
        s.flush()
        aid = a.id
    for st in ("interview", "interview", "rejected"):       # setting the same status again is not a change
        with db.session() as s:
            s.get(Application, aid).status = st
    with db.session() as s:
        assert [(e.old, e.new) for e in s.query(ApplicationEvent).order_by(ApplicationEvent.id)] == [("submitted", "interview"), ("interview", "rejected")]


def _seed(s, t):
    """Tasks and their model requests: scoring that worked, a draft that failed once and then worked, a filling that was handed over."""
    from autoapply.models import LLMRequest, Task

    def task(kind, ref, status, result=None, error="", minutes=1.0, days_ago=1, stages=None):
        x = Task(kind=kind, ref=ref, status=status, result=result or {}, error=error, attempts=1, started_at=t - timedelta(days=days_ago),
                 finished_at=t - timedelta(days=days_ago) + timedelta(minutes=minutes), stages=stages)
        s.add(x)
        s.flush()
        return x.id

    def req(task_id, workflow, feature, cost, *, status="ok", model="claude-opus-5-5", provider="claude_subscription", billing="subscription", attempt=0, call="", days_ago=1, tokens=(100, 900, 0, 50)):
        s.add(LLMRequest(request_id=f"r{task_id}-{feature}-{cost}-{attempt}-{call}", call_id=call or f"c{task_id}-{feature}-{cost}", attempt=attempt, started_at=t - timedelta(days=days_ago),
                         latency_ms=1200, provider=provider, model=model, billing=billing, kind="json", feature=feature, task_id=task_id, workflow=workflow, status=status, turns=1,
                         input_tokens=tokens[0] if tokens else None, cache_read_tokens=tokens[1] if tokens else None, cache_write_tokens=tokens[2] if tokens else None,
                         output_tokens=tokens[3] if tokens else None, detail="full" if tokens else "none", cost_micros=cost, cost_source="list_price" if cost is not None else "", source="live"))

    score = task("score", "unscored", "done", {"scored": 10})
    req(score, "score", "scoring", 4000)
    bad = task("recon", "job:1", "failed", error="TimeoutError: Page.goto: Timeout 30000ms exceeded", stages=[{"stage": "read_form", "at": "x"}, {"stage": "explore_form", "at": "x"}])
    req(bad, "recon", "explore_form", 30000, status="error", tokens=None)                    # failed, but the service had reported a cost
    good = task("recon", "job:1", "done", {"draft_id": 1})
    req(good, "recon", "explore_form", 50000)
    req(good, "recon", "answers", 20000)
    fill = task("execute", "application:1", "done", {"status": "ready_to_submit"}, minutes=12)
    req(fill, "execute", "take_over", 9000, attempt=1, call="shared")                        # the backup that answered ...
    req(fill, "execute", "take_over", None, status="rate_limited", call="shared", tokens=None)   # ... after the first service refused
    req(fill, "execute", "take_over", None, model="gpt-x", provider="chatgpt")             # usage known, no price for this model
    old = task("recon", "job:2", "done", {"draft_id": 2}, days_ago=40)
    req(old, "recon", "explore_form", 70000, days_ago=40)
    s.add(LLMRequest(request_id="legacy", call_id="legacy", started_at=t - timedelta(days=50), provider="", model="", billing="unknown", task_id=None, workflow="recon", status="unknown",
                     turns=12, input_tokens=100000, output_tokens=2000, detail="no_cache_split", cost_micros=None, source="legacy"))
    return {"score": score, "bad": bad, "good": good, "fill": fill}


def test_the_automation_view_tells_done_from_handed_over_from_failed(app_env):
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app
    from autoapply.models import now

    with db.session() as s:
        ids = _seed(s, now())
    c = TestClient(app)
    d = c.get("/api/analytics/automation?days=30").json()
    assert (d["total"]["total"], d["total"]["success"], d["total"]["handed"], d["total"]["failed"], d["total"]["unfinished"]) == (4, 2, 1, 1, 1)
    assert d["total"]["success_rate"] == round(2 / 3, 4)                    # of the tasks that ran to an end of their own; "handed over" is neither
    recon = next(k for k in d["by_kind"] if k["kind"] == "recon")
    # everything spent on drafts, the failed run included, over the one draft that came of it
    assert (recon["total"], recon["success"], recon["failed"], recon["cost"], recon["cost_per_success"]) == (2, 1, 1, 100000, 100000)
    fill = next(k for k in d["by_kind"] if k["kind"] == "execute")
    assert fill["success"] == 0 and fill["handed"] == 1 and fill["cost"] == 9000 and fill["cost_unknown_requests"] == 2 and fill["cost_per_success"] is None
    assert d["reasons"][0]["n"] == 1 and d["stages"] == [{"stage": "探索申请表", "n": 1}]      # where the failed task had got to
    assert d["repeats"] == {"objects": 1, "extra_runs": 1, "auto_retries": 0, "restarted": 0}
    row = next(r for r in d["recent"] if r["id"] == ids["fill"])
    assert (row["outcome"], row["requests"], row["cost"], row["cost_partial"]) == ("handed", 3, 9000, True)
    assert d["previous"] == {"total": 1}                                      # the 30 days before: one task
    only = c.get("/api/analytics/automation?days=30&kind=score").json()
    assert only["total"]["total"] == 1 and only["previous"] is None and len(only["by_kind"]) == 3
    assert len(c.get(f"/api/analytics/ai/requests?task_id={ids['fill']}").json()["requests"]) == 3


def test_the_ai_view_adds_up_and_keeps_unknown_apart_from_zero(app_env):
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app
    from autoapply.models import now

    with db.session() as s:
        ids = _seed(s, now())
    c = TestClient(app)
    d = c.get("/api/analytics/ai?days=30&group=feature").json()
    t = d["total"]
    assert (t["requests"], t["calls"], t["cost"], t["priced_requests"], t["unpriced_requests"], t["no_usage_requests"], t["failed_requests"]) == (7, 6, 113000, 5, 1, 2, 2)
    assert t["by_billing"] == {"subscription": 113000} and t["legacy"] is None
    assert t["tokens"] == {"input": 500, "cache_read": 4500, "cache_write": 0, "output": 250, "unsplit": 0}       # the two requests without usage add nothing, and say so
    assert d["previous"]["cost"] == 70000 and d["previous"]["requests"] == 1
    # by feature: the parts add up to the total, each with its share
    feats = {f["feature"]: f for f in d["by_feature"]}
    assert sum(f["cost"] or 0 for f in d["by_feature"]) == 113000 and feats["explore_form"]["cost"] == 80000 and feats["explore_form"]["share"] == round(80000 / 113000, 4)
    assert (feats["take_over"]["requests"], feats["take_over"]["calls"], feats["take_over"]["ok_calls"], feats["take_over"]["unpriced_requests"]) == (3, 2, 2, 1)
    assert {s_["key"] for s_ in d["series"]} == set(feats) and sum(sum(b["values"].values()) for b in d["trend"]) == 113000
    # by model: a model without a price is listed with its tokens and no cost
    gpt = next(m for m in d["by_model"] if m["model"] == "gpt-x")
    assert gpt["cost"] is None and gpt["tokens"] == 1050 and gpt["price"] is None and d["pricing"]["missing"] == ["ChatGPT 订阅 · gpt-x"]
    # cost per result: all runs of a kind, the failed one included, over what was achieved
    units = {u["kind"]: u for u in d["units"]}
    assert (units["score"]["results"], units["score"]["per_result"]) == (10, 400)
    assert (units["recon"]["runs"], units["recon"]["failed_runs"], units["recon"]["results"], units["recon"]["cost"], units["recon"]["per_result"]) == (2, 1, 1, 100000, 100000)
    assert units["execute"]["partial"] is True and units["execute"]["per_result"] == 9000     # some of its requests have no cost: a lower bound, marked as one
    # what failures and repeats cost
    w = d["waste"]
    assert w["failed_requests"] == {"requests": 2, "cost": 30000, "unknown": 1} and w["backup_attempts"] == {"requests": 1, "cost": 9000, "unknown": 0}
    assert w["failed_tasks"]["cost"] == 30000 and w["repeated_tasks"]["cost"] == 70000 and w["by_feature"] == [{"feature": "explore_form", "label": "探索申请表", "requests": 1, "cost": 30000}]
    # token kinds: how many, and what share of the cost (only where the split is known)
    kinds = {k["key"]: k for k in d["token_kinds"]}
    assert kinds["cache_read"]["tokens"] == 4500 and kinds["output"]["cost"] is not None and sum(k["cost"] for k in d["token_kinds"]) <= 113000
    # filters apply to everything; the choices offered stay the same
    f = c.get("/api/analytics/ai?days=30&feature=answers").json()
    assert f["total"]["cost"] == 20000 and len(f["filters"]["features"]) == 4 and f["filters"]["feature"] == "answers"
    # everything: the record from before requests were kept is shown apart, with no cost
    everything = c.get("/api/analytics/ai").json()
    assert everything["total"]["legacy"] == {"tasks": 1, "calls": 12, "input": 100000, "output": 2000} and everything["total"]["cost"] == 183000 and everything["previous"] is None
    # a custom range in local dates, inclusive
    day = (now().astimezone() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert c.get(f"/api/analytics/ai?start={day}&end={day}").json()["total"]["requests"] == 7
    # nothing in the window is "no data", not zeros
    empty = c.get("/api/analytics/ai?start=2020-01-01&end=2020-01-31").json()
    assert empty["total"]["requests"] == 0 and empty["total"]["cost"] is None and empty["trend"] == [] and empty["units"] == []
    assert ids


def test_totals_from_before_requests_were_recorded_are_carried_over_once(app_env):
    from autoapply import db, metering
    from autoapply.models import LLMRequest, Run, Task

    with db.session() as s:
        t = Task(kind="recon", ref="job:3", status="done")
        s.add(t)
        s.flush()
        s.add(Run(task_id=t.id, kind="llm", ref="job:3", ok=1, llm_calls=14, input_tokens=120000, output_tokens=3000))
    assert metering.import_legacy() == 1 and metering.import_legacy() == 0
    with db.session() as s:
        (r,) = s.query(LLMRequest).all()
        assert (r.source, r.workflow, r.job_id, r.turns, r.input_tokens, r.output_tokens, r.detail, r.cost_micros, r.model) == ("legacy", "recon", 3, 14, 120000, 3000, "no_cache_split", None, "")
