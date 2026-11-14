"""ChatGPT backend: the MCP tool bridge and the turn loop, with the Codex SDK replaced by a stand-in."""
import sys
import threading
import types


def test_tool_bridge_speaks_mcp_and_runs_tools_on_the_callers_thread(app_env):
    import queue

    from fastapi.testclient import TestClient

    from autoapply import llm, toolbridge
    from autoapply.api.main import app

    where = {}
    tools = [llm.Tool("add", "add two numbers", llm.obj({"a": {"type": "integer"}, "b": {"type": "integer"}}), lambda a, b: where.setdefault("thread", threading.current_thread().name) and a + b),
             llm.Tool("shot", "screenshot", llm.obj({}), lambda: [llm.image_block(b"png")]),
             llm.Tool("boom", "fails", llm.obj({}), lambda: 1 / 0)]
    calls: queue.Queue = queue.Queue()
    b = toolbridge.open(tools, calls)
    c = TestClient(app)
    url = f"/mcp/run/{b.token}"
    rpc = lambda method, params=None, mid=1: c.post(url, json={"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})  # noqa: E731

    init = rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}).json()["result"]
    assert init["protocolVersion"] == "2025-03-26" and "tools" in init["capabilities"]
    assert c.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    listed = rpc("tools/list").json()["result"]["tools"]
    assert [t["name"] for t in listed] == ["add", "shot", "boom"] and listed[0]["inputSchema"]["properties"]["a"] == {"type": "integer"}

    def serve():  # what the agent loop does: take calls off the queue and run them here
        while (item := calls.get()) is not None:
            t, args, reply = item
            try:
                reply.set_result(t.fn(**args))
            except Exception as e:  # noqa: BLE001
                reply.set_exception(e)

    th = threading.Thread(target=serve, name="page-owner")
    th.start()
    assert rpc("tools/call", {"name": "add", "arguments": {"a": 2, "b": 3}}).json()["result"] == {"content": [{"type": "text", "text": "5"}], "isError": False}
    assert where["thread"] == "page-owner"
    img = rpc("tools/call", {"name": "shot", "arguments": {}}).json()["result"]["content"][0]
    assert img["type"] == "image" and img["mimeType"] == "image/png"
    bad = rpc("tools/call", {"name": "boom"}).json()["result"]
    assert bad["isError"] and "ZeroDivisionError" in bad["content"][0]["text"]
    assert rpc("tools/call", {"name": "nope"}).json()["result"]["isError"]
    assert rpc("resources/list").json()["error"]["code"] == -32601
    calls.put(None)
    th.join()
    b.close()
    assert rpc("tools/list").status_code == 404  # the address dies with the run
    assert c.post("/mcp/run/guess", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 404


def test_chatgpt_turns_with_structured_output_and_tools(app_env, monkeypatch):
    from autoapply import db, llm, llm_codex, toolbridge

    seen = {}

    class Thread:
        def __init__(self, kw):
            self.kw = kw

        def run(self, prompt, output_schema=None):
            seen.update(prompt=prompt, schema=output_schema, **self.kw)
            text = '{"score": 7}' if output_schema else "hello"
            servers = (self.kw.get("config") or {}).get("mcp_servers")
            if servers:  # act like the runtime: list the tools over MCP, call one
                token = servers["autoapply"]["url"].rsplit("/", 1)[1]
                names = [t["name"] for t in toolbridge.handle(token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]]
                out = toolbridge.handle(token, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": names[0], "arguments": {"a": 4, "b": 5}}})
                text = "sum=" + out["result"]["content"][0]["text"]
            return types.SimpleNamespace(final_response=text, error=None, usage=types.SimpleNamespace(total=types.SimpleNamespace(input_tokens=11, output_tokens=3)))

    class Codex:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def thread_start(self, **kw):
            return Thread(kw)

        def account(self):
            return types.SimpleNamespace(model_dump=lambda: {"account": {"type": "chatgpt", "plan_type": types.SimpleNamespace(value="plus"), "email": "x@y.z"}})

    monkeypatch.setitem(sys.modules, "openai_codex", types.SimpleNamespace(Codex=Codex, Sandbox=types.SimpleNamespace(read_only="read-only")))
    db.set_setting("llm.provider", "chatgpt")
    assert llm.backend() == "codex" and llm_codex.status()["logged_in"] and llm_codex.status()["plan"] == "plus"
    assert llm.text("say hello", system="Be brief.") == "hello"
    assert seen["base_instructions"].startswith("Be brief.") and "Do not run shell commands" in seen["base_instructions"] and seen["ephemeral"] is True and seen["sandbox"] == "read-only"
    assert llm.json("score", llm.obj({"score": {"type": "integer"}})) == {"score": 7} and seen["schema"]["properties"]["score"] == {"type": "integer"}
    ran_on = []
    tools = [llm.Tool("add", "add", llm.obj({"a": {"type": "integer"}, "b": {"type": "integer"}}), lambda a, b: ran_on.append(threading.current_thread() is threading.main_thread()) or a + b)]
    res = llm.agent("add 4 and 5", tools, system="Use the tools.")
    assert res.final_text == "sum=9" and [(s["tool"], s["ok"], s["output"]) for s in res.steps] == [("add", True, "9")]
    assert ran_on == [True]  # the tool ran on the thread that asked, not on the runtime's
    assert seen["config"]["mcp_servers"]["autoapply"]["default_tools_approval_mode"] == "approve" and not toolbridge._open  # bridge closed afterwards
    assert llm.usage().input_tokens >= 33


def test_chatgpt_not_installed_is_reported_plainly(app_env, monkeypatch):
    import pytest

    from autoapply import db, llm, llm_codex

    monkeypatch.setitem(sys.modules, "openai_codex", None)
    db.set_setting("llm.provider", "chatgpt")
    assert llm_codex.status()["installed"] is False
    with pytest.raises(llm.LLMUnavailable) as e:
        llm.text("hi")
    assert "uv sync --extra chatgpt" in str(e.value)
