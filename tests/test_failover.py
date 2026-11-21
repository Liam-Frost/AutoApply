"""Failover between AI services: when the one in use runs out, the same call is made on the user's backups."""

import pytest


@pytest.fixture
def two_services(app_env, monkeypatch):
    """Claude subscription in use, DeepSeek and ChatGPT as backups; the backends are stand-ins that record who was asked."""
    from autoapply import db, llm, notify

    db.set_setting("llm.provider", "claude_subscription")
    db.set_setting("llm.providers", {"deepseek": {"base_url": "", "model": "deepseek-big", "small_model": "deepseek-small"}, "chatgpt": {"model": "", "small_model": ""}})
    db.set_setting("llm.failover", [{"provider": "deepseek", "model": "", "small_model": ""}, {"provider": "chatgpt", "model": "gpt-x", "small_model": ""}])
    llm.reset_failover()
    asked, sent = [], []
    behaviour = {"claude_subscription": llm.LLMUnavailable("Claude subscription usage limit reached: resets 3pm"), "deepseek": None, "chatgpt": None}

    def fake_text(prompt, *, system, small, max_tokens, effort):
        p = llm.provider()
        model = llm._model(small) if p in llm.CLAUDE else llm._other(small)[1]
        asked.append((p, model))
        if behaviour[p] is not None:
            raise behaviour[p]
        return f"reply from {p}"

    monkeypatch.setattr(llm, "_text", fake_text)
    monkeypatch.setattr(llm, "_json_call", lambda prompt, schema, **kw: {"by": fake_text(prompt, **kw)})
    monkeypatch.setattr(notify, "send", lambda category, card, **kw: sent.append(card) or True)
    yield {"asked": asked, "sent": sent, "behaviour": behaviour}
    llm.reset_failover()


def test_without_backups_nothing_changes(app_env, monkeypatch):
    from autoapply import db, llm

    db.set_setting("llm.failover", [])
    llm.reset_failover()
    monkeypatch.setattr(llm, "_text", lambda *a, **k: (_ for _ in ()).throw(llm.LLMUnavailable("Claude subscription usage limit reached")))
    with pytest.raises(llm.LLMUnavailable, match="usage limit reached$"):      # the same error as before, word for word
        llm.text("hi")
    assert [e["provider"] for e in llm.chain()] == ["claude_subscription"]


def test_a_service_that_runs_out_hands_over_to_the_next_for_both_models(two_services):
    from autoapply import llm

    t = two_services
    assert llm.text("hi") == "reply from deepseek"
    assert t["asked"] == [("claude_subscription", "claude-opus-5-5"), ("deepseek", "deepseek-big")]
    # the small model follows the same chain, with the backup's own small model
    assert llm.json("classify", {"type": "object"}, small=True) == {"by": "reply from deepseek"}
    assert t["asked"][2:] == [("deepseek", "deepseek-small")]                    # the service that ran out is left alone, not asked again
    # the user is told once, in words, not once per call
    assert len(t["sent"]) == 1 and "备用" in t["sent"][0].heading and ("原因", "用量额度用完了") in t["sent"][0].fields
    st = llm.failover_status()
    assert [(s["provider"], s["role"], s["state"]) for s in st] == [("claude_subscription", "primary", "cooling"), ("deepseek", "backup", "ok"), ("chatgpt", "backup", "ok")]
    assert st[2]["model"] == "gpt-x" and st[1]["small_model"] == "deepseek-small" and "usage limit" in st[0]["reason"]


def test_backups_are_tried_in_order_and_the_first_service_comes_back_by_itself(two_services):
    from autoapply import llm

    t = two_services
    t["behaviour"]["deepseek"] = llm.LLMError("HTTP 503: overloaded")
    assert llm.text("hi") == "reply from chatgpt"
    assert [p for p, _ in t["asked"]] == ["claude_subscription", "deepseek", "chatgpt"]
    # time passes, the limit resets: the service in the settings is used again and the switch can be announced anew next time
    t["behaviour"]["claude_subscription"] = None
    for k in list(llm._down):
        llm._down[k] = (0.0, llm._down[k][1])
    t["asked"].clear()
    assert llm.text("hi") == "reply from claude_subscription" and t["asked"] == [("claude_subscription", "claude-opus-5-5")]
    assert llm.failover_status()[0]["state"] == "ok" and not llm._announced


def test_when_every_service_is_out_the_error_says_so_and_keeps_the_first_reason(two_services):
    from autoapply import llm

    t = two_services
    t["behaviour"]["deepseek"] = llm.LLMUnavailable("AI 服务的额度用完了或账户欠费")
    t["behaviour"]["chatgpt"] = llm.LLMError("ChatGPT 这一步超时了")
    with pytest.raises(llm.LLMUnavailable) as e:
        llm.text("hi")
    assert "usage limit" in str(e.value) and "所有配置的 AI 服务都试过了" in str(e.value) and "DeepSeek" in str(e.value)   # tasks retry later on "usage limit"
    assert not t["sent"]                                                        # nothing was switched to, so nothing is announced


def test_a_wrong_answer_is_not_an_outage(two_services):
    """Only "this service cannot be used right now" moves on. A refusal, a truncated or malformed reply is that call's own failure."""
    from autoapply import llm

    t = two_services
    for err in (llm.LLMRefused("the model declined this request"), llm.LLMError("output truncated (max_tokens)"), llm.LLMError("model returned invalid JSON: {")):
        t["behaviour"]["claude_subscription"] = err
        t["asked"].clear()
        with pytest.raises(type(err)):
            llm.text("hi")
        assert [p for p, _ in t["asked"]] == ["claude_subscription"]
    # a service that cannot take this kind of input is skipped for this call only, and not set aside
    t["behaviour"]["claude_subscription"] = llm.LLMError("用 ChatGPT 登录时不能发送图片。")
    assert llm.text("hi") == "reply from deepseek" and llm.failover_status()[0]["state"] == "ok"


def test_an_agent_cut_off_midway_starts_again_on_the_backup_and_is_told(app_env, monkeypatch):
    from autoapply import db, llm, notify

    db.set_setting("llm.provider", "claude_subscription")
    db.set_setting("llm.providers", {"deepseek": {"model": "d"}})
    db.set_setting("llm.failover", [{"provider": "deepseek"}])
    llm.reset_failover()
    monkeypatch.setattr(notify, "send", lambda *a, **k: True)
    goals, clicks = [], []

    def fake_agent(goal, tools, *, system, budget, on_step):
        goals.append((llm.provider(), goal))
        tools[0].fn(selector="#a")
        if llm.provider() == "claude_subscription":
            raise llm.LLMError("rate limited: slow down")
        return llm.AgentResult(final_text="done")

    monkeypatch.setattr(llm, "_agent", fake_agent)
    tool = llm.Tool("click", "click", {"type": "object"}, lambda selector: clicks.append(selector) or "ok")
    out = llm.agent("Fill the form", [tool], system="s")
    assert out.final_text == "done" and clicks == ["#a", "#a"]
    assert goals[0] == ("claude_subscription", "Fill the form")
    assert goals[1][0] == "deepseek" and goals[1][1].startswith("Fill the form") and "earlier attempt" in goals[1][1] and "do not repeat" in goals[1][1]
    llm.reset_failover()


def test_failover_settings_endpoints(two_services):
    from fastapi.testclient import TestClient

    from autoapply.api.main import app

    c = TestClient(app)
    d = c.get("/api/llm/failover").json()
    assert [x["provider"] for x in d["chain"]] == ["claude_subscription", "deepseek", "chatgpt"] and d["chain"][0]["name"] == "Claude 订阅"
    r = c.put("/api/llm/failover", json={"entries": [{"provider": "chatgpt", "model": "gpt-y"}, {"provider": "nope"}]})
    assert r.status_code == 400
    d = c.put("/api/llm/failover", json={"entries": [{"provider": "chatgpt", "model": "gpt-y"}]}).json()
    assert [(x["provider"], x["model"]) for x in d["chain"]] == [("claude_subscription", "claude-opus-5-5"), ("chatgpt", "gpt-y")]
    t = c.post("/api/llm/failover/test", json={"provider": "deepseek"}).json()
    assert t["main"] == {"ok": True, "model": "deepseek-big", "reply": "reply from deepseek"} and t["small"]["model"] == "deepseek-small"
    t = c.post("/api/llm/failover/test", json={"provider": "claude_subscription"}).json()
    assert t["main"]["ok"] is False and "usage limit" in t["main"]["error"]


def test_allowance_is_read_where_a_service_reports_it_and_warned_about_once(app_env, monkeypatch):
    """Claude's windows ride on every call, ChatGPT and the prepaid services are asked; a service passing the warning level is
    announced once per window, a used-up one is rested until its window resets; services that do not report say so."""
    import time

    from autoapply import db, llm, notify, quota

    db.set_setting("llm.provider", "claude_subscription")
    db.set_setting("llm.providers", {"deepseek": {"model": "d"}, "openai": {"model": "o"}})
    db.set_setting("llm.failover", [{"provider": "chatgpt"}, {"provider": "deepseek"}, {"provider": "openai"}])
    llm.reset_failover()
    sent = []
    monkeypatch.setattr(notify, "send", lambda category, card, **kw: sent.append((card, kw.get("tag"))) or True)
    soon, later = int(time.time()) + 3600, int(time.time()) + 5 * 86400
    # what a Claude call reports (the record seen on a real call)
    quota.remember_claude({"status": "allowed", "rateLimitType": "five_hour", "resetsAt": soon,
                           "unifiedWindows": {"five_hour": {"utilization": 0.86, "resetsAt": soon, "status": "allowed"}, "seven_day": {"utilization": 0.27, "resetsAt": later, "status": "allowed"}}})
    monkeypatch.setattr(quota, "_chatgpt", lambda: {"kind": "windows", "blocked": True, "plan": "plus", "windows": [
        {"key": "primary", "label": "5 小时额度", "used": 100, "resets_at": soon, "blocked": True}, {"key": "secondary", "label": "每周额度", "used": 47, "resets_at": later, "blocked": False}]})
    monkeypatch.setattr(quota, "_deepseek", lambda: {"kind": "balance", "balances": [{"currency": "CNY", "amount": 0.4}], "blocked": False})

    rows = {r["provider"]: r for r in quota.check_all()}
    assert rows["claude_subscription"]["level"] == "low" and [(w["label"], w["used"]) for w in rows["claude_subscription"]["windows"]] == [("5 小时额度", 86), ("每周额度", 27)]
    assert rows["chatgpt"]["level"] == "out" and rows["deepseek"]["level"] == "low"
    assert rows["openai"]["supported"] is False and "不提供查询余额" in rows["openai"]["note"]            # said plainly, not guessed
    heads = [c.heading for c, _ in sent]
    assert heads == ["AI 额度快用完了", "AI 额度用完了", "AI 额度快用完了"] and all(tag == "quota" for _, tag in sent)
    claude = sent[0][0]
    assert ("服务", "Claude 订阅") in claude.fields and any(k == "5 小时额度" and v.startswith("已用 86%") and "重置" in v for k, v in claude.fields)
    assert "备用服务：ChatGPT 订阅" in claude.hint
    assert ("余额", "0.40 CNY") in sent[2][0].fields
    # the used-up service is rested until its window resets, without a call having to fail first
    st = {s["provider"]: s for s in llm.failover_status()}
    assert st["chatgpt"]["state"] == "cooling" and st["claude_subscription"]["state"] == "ok"
    # the same state is not announced again; a new window is
    sent.clear()
    quota.check_all()
    assert not sent
    quota.remember_claude({"unifiedWindows": {"five_hour": {"utilization": 0.9, "resetsAt": soon + 18000, "status": "allowed"}}})
    quota.check_all()
    assert [c.heading for c, _ in sent] == ["AI 额度快用完了"]
    # switched off: figures are still read, nothing is sent
    sent.clear()
    db.set_setting("llm.quota_notify", False)
    db.set_setting("llm.quota_alerts", {})
    assert quota.check_all() and not sent
    # a figure that cannot be read is shown as such and breaks nothing
    monkeypatch.setattr(quota, "_deepseek", lambda: (_ for _ in ()).throw(RuntimeError("HTTP 500")))
    db.set_setting("llm.quota", {})
    assert "error" in quota.read("deepseek") and quota.read("claude_subscription")["pending"] is True
    llm.reset_failover()


def test_a_used_up_service_rests_until_its_window_resets(two_services, monkeypatch):
    import time

    from autoapply import llm, quota

    until = time.time() + 2 * 3600
    monkeypatch.setattr(quota, "reset_time", lambda provider: until if provider == "claude_subscription" else None)
    assert llm.text("hi") == "reply from deepseek"
    rest_until = llm._down["claude_subscription|"][0]
    assert abs(rest_until - until) < 120                                   # not the fixed half hour: as long as the service says


def test_backup_test_result_is_one_plain_sentence_with_the_details_folded(two_services):
    from fastapi.testclient import TestClient

    from autoapply.api.main import app

    t = TestClient(app).post("/api/llm/failover/test", json={"provider": "claude_subscription"}).json()
    assert t["main"]["ok"] is False and t["main"]["message"] == "Claude 订阅的额度用完了，要等它重置。" and "usage limit reached" in t["main"]["detail"]
    q = TestClient(app).get("/api/llm/quota").json()
    assert [s["provider"] for s in q["services"]] == ["claude_subscription", "deepseek", "chatgpt"] and q["warn_percent"] == 80
    assert TestClient(app).put("/api/llm/quota", json={"warn_percent": 90, "notify": False}).json()["warn_percent"] == 90
