"""One count and one clock for an agent, whichever service does the thinking (autoapply/agentbudget.py).

F-12: the Anthropic loop counted model turns, the Claude command line its own turns, an OpenAI-compatible service its
requests, and the ChatGPT command line nothing - with a time limit between two messages that an agent which keeps
calling tools never reaches. Each test here drives one of the four with a model that never stops by itself."""

import asyncio
import json
import sys
import threading
import time
import types

import pytest

from autoapply import db


def _look(log, wait=0.0):
    from autoapply import llm

    def look():
        log.append(time.monotonic())
        time.sleep(wait)
        return "a page"

    return [llm.Tool("look", "look at the page", llm.obj({}), look)]


def test_a_budget_is_so_many_tool_calls_and_a_moment_on_the_clock(app_env):
    from autoapply import agentbudget, config

    b = agentbudget.Budget(2, 60, "navigate")
    b.spend()
    b.spend()
    with pytest.raises(agentbudget.Spent) as e:
        b.spend()
    assert e.value.why == "max_steps" and b.ended == "max_steps" and b.used == 2 and b.summary()["of"] == 2
    b = agentbudget.Budget(50, 0.15)
    b.spend()
    assert not b.expired() and 0 < b.left() <= 0.15 + 1e-6      # (the clock may not have moved yet, and the sum is a float)
    time.sleep(0.2)
    assert b.expired() == "timeout" and b.left() > 0      # a wait is never for less than a moment
    with pytest.raises(agentbudget.Spent) as e:
        b.spend()
    assert e.value.why == "timeout" and b.used == 1
    # how much each kind of work gets is a setting, by kind; what it does not say is as built in
    got = agentbudget.for_kind("apply")
    assert (got.steps, got.seconds, got.kind) == (400, 45 * 60, "apply")
    db.set_setting("agent.budgets", {"apply": {"steps": 300}, "scan": {"steps": 0, "minutes": "x"}})
    assert (agentbudget.for_kind("apply").steps, agentbudget.for_kind("apply").seconds) == (300, 45 * 60)
    assert (agentbudget.for_kind("scan").steps, agentbudget.for_kind("scan").seconds) == (150, 30 * 60)      # nonsense is not a budget
    assert (agentbudget.for_kind("something new").steps, agentbudget.for_kind("something new").seconds) == (60, 20 * 60)


def _an_openai_service_that_never_stops(monkeypatch, asked):
    import httpx

    from autoapply import llm, llm_openai, secrets

    def server(req):
        asked.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": [
            {"id": f"c{len(asked)}", "type": "function", "function": {"name": "look", "arguments": "{}"}}]}}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}})

    real = llm_openai.Client
    monkeypatch.setattr(llm_openai, "Client", lambda base, key, **kw: real(base, key, transport=httpx.MockTransport(server)))
    db.set_setting("llm.provider", "deepseek")
    db.set_setting("llm.providers", {"deepseek": {"base_url": "", "model": "big-1", "small_model": "small-1"}})
    secrets.put(llm.key_name("deepseek"), "sk-test")


def test_an_openai_compatible_service_is_stopped_by_the_count_and_by_the_clock(app_env, monkeypatch):
    from autoapply import agentbudget, llm

    asked, done = [], []
    _an_openai_service_that_never_stops(monkeypatch, asked)
    db.set_setting("agent.budgets", {"navigate": {"steps": 3, "minutes": 5}})
    res = llm.agent("go on", _look(done), system="s", kind="navigate")
    assert res.stopped == "max_steps" and len(done) == 3 and len(res.steps) == 3
    assert len(asked) == 4      # the fourth answer asked for a fourth call, which was not carried out - and no fifth request was made
    assert (res.budget["steps"], res.budget["of"], res.budget["ended"], res.budget["kind"]) == (3, 3, "max_steps", "navigate")
    assert res.said() == "stopped: it used all 3 tool calls this kind of work is given"
    asked.clear()
    done.clear()
    began = time.monotonic()
    res = llm.agent("go on", _look(done, wait=0.12), system="s", budget=agentbudget.Budget(1000, 0.5))
    assert res.stopped == "timeout" and 1 <= len(done) <= 9 and time.monotonic() - began < 6
    assert "ran out of" in res.said()


def test_the_anthropic_loop_is_stopped_by_the_count_and_by_the_clock(app_env, monkeypatch):
    from autoapply import agentbudget, llm

    db.set_setting("llm.provider", "anthropic")
    asked = []

    def create(**kw):
        asked.append(kw)
        return types.SimpleNamespace(stop_reason="tool_use", usage=None, content=[
            types.SimpleNamespace(type="tool_use", id=f"t{len(asked)}a", name="look", input={}),
            types.SimpleNamespace(type="tool_use", id=f"t{len(asked)}b", name="no_such_tool", input={})])

    monkeypatch.setattr(llm, "_create", create)
    done = []
    res = llm.agent("go on", _look(done), system="s", budget=agentbudget.Budget(5, 60))
    # steps are tool calls, not turns: two a turn here, and a call to a tool that is not there is one too
    assert res.stopped == "max_steps" and len(asked) == 3 and len(done) == 3 and [s["ok"] for s in res.steps] == [True, False, True, False, True]
    asked.clear()
    done.clear()
    res = llm.agent("go on", _look(done, wait=0.12), system="s", budget=agentbudget.Budget(1000, 0.4))
    assert res.stopped == "timeout" and 1 <= len(done) <= 9


class _Runtime:
    """The ChatGPT command line, as far as this program uses it: a turn that keeps calling the first tool over MCP
    until the address stops answering or it is interrupted - or that only thinks."""

    def __init__(self, thinks_only=False, hears_interrupt=True):
        self.thinks_only, self.hears_interrupt = thinks_only, hears_interrupt
        self.interrupted, self.closed, self.calls = threading.Event(), threading.Event(), 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        self.closed.set()

    def thread_start(self, **kw):
        from autoapply import toolbridge

        me = self
        token = kw["config"]["mcp_servers"]["autoapply"]["url"].rsplit("/", 1)[1]

        class Turn:
            def interrupt(self):
                me.interrupted.set()

            def run(self):
                while not (me.hears_interrupt and me.interrupted.is_set()) and not me.closed.is_set():
                    if me.thinks_only:
                        time.sleep(0.02)
                        continue
                    try:
                        toolbridge.handle(token, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "look", "arguments": {}}})
                        me.calls += 1
                    except KeyError:      # the address stopped answering
                        time.sleep(0.02)
                if me.closed.is_set() and not (me.hears_interrupt and me.interrupted.is_set()):
                    raise RuntimeError("the runtime was closed")
                return types.SimpleNamespace(final_response="", error=None, usage=None)

        return types.SimpleNamespace(turn=lambda prompt, output_schema=None: Turn())


def _chatgpt(monkeypatch, runtime):
    monkeypatch.setitem(sys.modules, "openai_codex", types.SimpleNamespace(Codex=lambda: runtime, Sandbox=types.SimpleNamespace(read_only="read-only")))
    db.set_setting("llm.provider", "chatgpt")


def test_the_chatgpt_command_line_is_stopped_by_the_count_and_its_turn_is_interrupted(app_env, monkeypatch):
    """It had no count at all, and its only time limit started again with every tool call."""
    from autoapply import agentbudget, llm, toolbridge

    rt = _Runtime()
    _chatgpt(monkeypatch, rt)
    done = []
    res = llm.agent("go on", _look(done), system="s", budget=agentbudget.Budget(4, 60))
    assert res.stopped == "max_steps" and len(done) == 4 and len(res.steps) == 4
    assert rt.interrupted.is_set() and not toolbridge._open      # both sides: the model's turn, and the address of the tools
    time.sleep(0.1)
    assert len(done) == 4      # nothing was carried out after it ended


def test_the_chatgpt_command_line_is_stopped_by_the_clock_while_it_is_calling_tools_and_while_it_only_thinks(app_env, monkeypatch):
    from autoapply import agentbudget, llm, llm_codex, toolbridge

    rt = _Runtime()
    _chatgpt(monkeypatch, rt)
    done = []
    began = time.monotonic()
    res = llm.agent("go on", _look(done, wait=0.1), system="s", budget=agentbudget.Budget(1000, 0.5))
    # a tool call every tenth of a second: the old limit (an hour between two messages) would never have been reached
    assert res.stopped == "timeout" and 1 <= len(done) <= 9 and time.monotonic() - began < 6 and rt.interrupted.is_set()
    rt = _Runtime(thinks_only=True)
    _chatgpt(monkeypatch, rt)
    res = llm.agent("go on", _look([]), system="s", budget=agentbudget.Budget(1000, 0.3))
    assert res.stopped == "timeout" and res.steps == [] and rt.interrupted.is_set() and not toolbridge._open
    # a runtime that does not wind down when it is interrupted is closed
    monkeypatch.setattr(llm_codex, "WIND_DOWN", 0.3)
    rt = _Runtime(thinks_only=True, hears_interrupt=False)
    _chatgpt(monkeypatch, rt)
    res = llm.agent("go on", _look([]), system="s", budget=agentbudget.Budget(1000, 0.3))
    assert res.stopped == "timeout" and rt.interrupted.is_set() and rt.closed.is_set()


def _claude_command_line(monkeypatch, state):
    """The Claude command line's SDK, as far as llm_sdk uses it: a query that keeps calling the first tool until it is
    cancelled - or that only thinks."""

    def tool(name, description, schema):
        return lambda fn: types.SimpleNamespace(name=name, handler=fn)

    async def query(prompt, options):
        handlers = options.mcp_servers["autoapply"]
        state["system"] = options.system_prompt
        async for first in prompt:
            state["first"] = first["message"]["content"]
        if state.get("summarizes"):      # the command line shortened a long conversation
            yield System("compact_boundary", {"compact_metadata": {"trigger": "auto", "pre_tokens": 150000}})
        try:
            while True:
                if state.get("thinks_only"):
                    await asyncio.sleep(0.02)
                else:
                    await handlers[0].handler({})
                    state["calls"] = state.get("calls", 0) + 1
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        yield None      # (never reached: it makes this an async generator, as the real one is)

    class Options:
        def __init__(self, **kw):
            self.__dict__.update(kw)
            state["max_turns"] = kw.get("max_turns")

    class System:
        def __init__(self, subtype, data):
            self.subtype, self.data = subtype, data

    fake = types.SimpleNamespace(AssistantMessage=type("AssistantMessage", (), {}), ClaudeAgentOptions=Options, RateLimitEvent=type("RateLimitEvent", (), {}), SystemMessage=System,
                                 ResultMessage=type("ResultMessage", (), {}), create_sdk_mcp_server=lambda name, tools: tools, query=query, tool=tool,
                                 ClaudeSDKError=type("ClaudeSDKError", (Exception,), {}), CLINotFoundError=type("CLINotFoundError", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake)
    from autoapply import llm_sdk

    monkeypatch.setattr(llm_sdk, "SERVER", "autoapply")
    monkeypatch.setattr(llm_sdk, "call", llm_sdk.real_call)      # (conftest puts "no model in tests" in its place)
    db.set_setting("llm.provider", "claude_subscription")


def test_the_claude_command_line_is_stopped_by_the_count_and_by_the_clock_and_its_query_is_cancelled(app_env, monkeypatch):
    from autoapply import agentbudget, llm

    state = {}
    _claude_command_line(monkeypatch, state)
    done = []
    res = llm.agent("go on", _look(done), system="s", budget=agentbudget.Budget(4, 60))
    assert res.stopped == "max_steps" and len(done) == 4 and len(res.steps) >= 4
    assert state["max_turns"] is None      # one count, and it is the budget's
    time.sleep(0.2)
    assert state.get("cancelled") and len(done) == 4      # the query - the command line's process - ended with it
    state.clear()
    done.clear()
    began = time.monotonic()
    res = llm.agent("go on", _look(done, wait=0.1), system="s", budget=agentbudget.Budget(1000, 0.5))
    assert res.stopped == "timeout" and 1 <= len(done) <= 9 and time.monotonic() - began < 6
    state.clear()
    state["thinks_only"] = True
    res = llm.agent("go on", _look([]), system="s", budget=agentbudget.Budget(1000, 0.3))
    time.sleep(0.2)
    assert res.stopped == "timeout" and res.steps == [] and state.get("cancelled")


def test_what_an_agent_is_told_stands_with_its_instructions_and_a_summarized_conversation_is_said(app_env, monkeypatch, tmp_path):
    """A long run's conversation is shortened by the service that holds it. What the agent was told about its task is
    not in the conversation: it goes with the instructions, which are sent whole with every step."""
    from autoapply import agentbudget, llm
    from autoapply.agent.run import Desk

    state = {"summarizes": True}
    _claude_command_line(monkeypatch, state)
    desk = Desk(tmp_path, None, site="generic:example.com", mode="auto")
    res = llm.agent("THE APPLICANT'S PROFILE, THE RECORD, THEIR ANSWERS", _look([]), system="the manual", budget=agentbudget.Budget(2, 60), on_step=desk.step)
    assert state["system"].startswith("the manual") and "THE APPLICANT'S PROFILE, THE RECORD, THEIR ANSWERS" in state["system"]
    assert "PROFILE" not in str(state["first"]) and str(state["first"]).startswith("Begin.")
    assert res.budget["steps"] == 2 and all(st.get("tool") == "look" for st in res.steps)      # the summary is not a tool call: it takes nothing from the budget
    lines = [json.loads(ln) for ln in (tmp_path / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    said = [e["text"] for e in lines if e["kind"] == "log"]
    assert len(said) == 1 and "summarized" in said[0] and "150,000" in said[0]      # whoever follows the run can see that it happened


def test_a_backup_service_goes_on_with_what_is_left_of_the_budget(app_env, monkeypatch):
    from autoapply import agentbudget, llm, notify

    db.set_setting("llm.provider", "claude_subscription")
    db.set_setting("llm.providers", {"deepseek": {"model": "d"}})
    db.set_setting("llm.failover", [{"provider": "deepseek"}])
    llm.reset_failover()
    monkeypatch.setattr(notify, "send", lambda *a, **k: True)
    done = []

    def service(goal, tools, *, system, budget, on_step):
        try:
            for _ in range(3):
                tools[0].fn()
        except agentbudget.Spent as e:
            return llm.AgentResult(final_text="", stopped=e.why)
        if llm.provider() == "claude_subscription":
            raise llm.LLMError("rate limited: slow down")
        return llm.AgentResult(final_text="done")

    monkeypatch.setattr(llm, "_agent", service)
    res = llm.agent("go on", _look(done), system="s", budget=agentbudget.Budget(5, 60))
    # three calls on the first service, which then gave out; the backup had two left, not five again
    assert res.stopped == "max_steps" and len(done) == 5 and res.budget["steps"] == 5
    llm.reset_failover()


def test_the_budgets_are_a_setting_shown_whole_and_checked_when_saved(app_env):
    from fastapi.testclient import TestClient

    from autoapply import agentbudget, config
    from autoapply.api.main import app

    c = TestClient(app)
    db.set_setting("agent.budgets", {"apply": {"steps": 300}})      # saved before the other kinds were there
    shown = c.get("/api/settings").json()["settings"]["agent.budgets"]
    assert shown["apply"] == {"steps": 300, "minutes": 45} and shown["site_status"] == {"steps": 60, "minutes": 15} and set(shown) == set(config.DEFAULT_SETTINGS["agent.budgets"])
    shown["scan"] = {"steps": 55, "minutes": 12}
    assert c.put("/api/settings", json={"settings": {"agent.budgets": shown}}).status_code == 200
    assert (agentbudget.for_kind("scan").steps, agentbudget.for_kind("scan").seconds) == (55, 12 * 60)
    for bad in ({"scan": {"steps": 0, "minutes": 10}}, {"scan": {"steps": 10, "minutes": 999}}, {"scan": {"steps": "many"}}, {"scan": 5}, []):
        r = c.put("/api/settings", json={"settings": {"agent.budgets": bad}})
        assert r.status_code == 400, bad
    assert agentbudget.for_kind("scan").steps == 55      # a refused table changed nothing


def test_a_request_to_the_model_is_given_what_is_left_of_the_budget_and_no_more(app_env, monkeypatch):
    """The deadline was looked at before a request and not after: a request could run for the client's own five
    minutes, and an answer that came after the deadline was taken as if it had come in time."""
    import httpx

    from autoapply import agentbudget, llm, llm_openai, secrets

    # an OpenAI-compatible service that takes longer than there is, and then answers
    given = []
    real_post = llm_openai.Client._post

    def post(self, body, *, timeout=None):
        given.append(timeout)
        return real_post(self, body, timeout=timeout)

    def slow(req):
        time.sleep(0.4)
        return httpx.Response(200, json={"choices": [{"message": {"content": "here is my answer"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}})

    real = llm_openai.Client
    monkeypatch.setattr(llm_openai.Client, "_post", post)
    monkeypatch.setattr(llm_openai, "Client", lambda base, key, **kw: real(base, key, transport=httpx.MockTransport(slow)))
    db.set_setting("llm.provider", "deepseek")
    db.set_setting("llm.providers", {"deepseek": {"base_url": "", "model": "big-1", "small_model": "small-1"}})
    secrets.put(llm.key_name("deepseek"), "sk-test")
    res = llm.agent("go on", _look([]), system="s", budget=agentbudget.Budget(10, 0.2))
    assert res.stopped == "timeout" and res.final_text == ""                     # it answered - after the time was up
    assert len(given) == 1 and 0 < given[0] <= 0.2 + 1e-6                        # the request was told how long it had
    # the same request failing after the deadline is the budget's end, not the service's failure (no backup is tried for it)
    monkeypatch.setattr(llm_openai, "Client", lambda base, key, **kw: real(base, key, transport=httpx.MockTransport(lambda req: (time.sleep(0.3), httpx.Response(500, text="late"))[1])))
    assert llm.agent("go on", _look([]), system="s", budget=agentbudget.Budget(10, 0.2)).stopped == "timeout"
    # ...and before the deadline it is a failure like any other
    monkeypatch.setattr(llm_openai, "Client", lambda base, key, **kw: real(base, key, transport=httpx.MockTransport(lambda req: httpx.Response(500, text="broken"))))
    with pytest.raises(llm.LLMError):
        llm.agent("go on", _look([]), system="s", budget=agentbudget.Budget(10, 30))

    # the Anthropic loop: the same three
    db.set_setting("llm.provider", "anthropic")
    asked = []

    def late(**kw):
        asked.append(kw.get("timeout"))
        time.sleep(0.3)
        return types.SimpleNamespace(stop_reason="end_turn", usage=None, content=[types.SimpleNamespace(type="text", text="here is my answer")])

    monkeypatch.setattr(llm, "_create", late)
    res = llm.agent("go on", _look([]), system="s", budget=agentbudget.Budget(10, 0.2))
    assert res.stopped == "timeout" and res.final_text == "" and 0 < asked[0] <= 0.2 + 1e-6

    def cut_off(**kw):
        time.sleep(0.3)
        raise llm.LLMUnavailable("cannot reach the Claude API: timed out")

    monkeypatch.setattr(llm, "_create", cut_off)
    assert llm.agent("go on", _look([]), system="s", budget=agentbudget.Budget(10, 0.2)).stopped == "timeout"
    monkeypatch.setattr(llm, "_create", lambda **kw: (_ for _ in ()).throw(llm.LLMUnavailable("cannot reach the Claude API")))
    with pytest.raises(llm.LLMUnavailable):
        llm.agent("go on", _look([]), system="s", budget=agentbudget.Budget(10, 30))
