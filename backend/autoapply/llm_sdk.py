"""Claude through the Claude Agent SDK, authenticated by the user's Claude subscription.

The SDK drives the Claude Code CLI bundled in its wheel. That CLI uses the login
in ``~/.claude`` (``autoapply claude-login``) or a long-lived token from
``claude setup-token`` saved in Settings. Built-in tools, user settings and
CLAUDE.md are all switched off: the CLI is used as a model endpoint only.

The SDK is async and the rest of the app is sync (and often inside a Playwright
sync session), so queries run on one background event-loop thread. Tool calls
are handed back to the calling thread, which is the only thread allowed to
touch its Playwright page.
"""

from __future__ import annotations

import asyncio
import concurrent.futures as cf
import json as _json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import timing

SERVER = "autoapply"
_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


class SDKError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, unavailable: bool = False, refused: bool = False) -> None:
        super().__init__(message)
        self.status, self.unavailable, self.refused = status, unavailable, refused


@dataclass
class SDKResult:
    text: str = ""
    structured: Any = None
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    stopped: str = "end_turn"
    steps: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] | None = None      # as reported: input_tokens (uncached), cache_read_input_tokens, cache_creation_input_tokens, output_tokens
    cost_usd: float | None = None            # what the command line says the query would cost on the API
    api_ms: int | None = None
    session_id: str = ""
    model_usage: dict[str, Any] | None = None


def cli_path() -> str | None:
    try:
        import claude_agent_sdk

        root = Path(claude_agent_sdk.__file__).parent / "_bundled"
        for name in ("claude.exe", "claude"):
            if (root / name).exists():
                return str(root / name)
    except ImportError:
        return None
    return shutil.which("claude")


def _env(token: str | None) -> dict[str, str]:
    env: dict[str, str] = {}
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    if os.environ.get("ANTHROPIC_API_KEY"):
        env["ANTHROPIC_API_KEY"] = ""  # subscription mode must not fall back to a metered key
    from . import net

    env.update(net.env() if net.mode() != "system" else _system_proxy())
    return env


def _system_proxy() -> dict[str, str]:
    """The CLI only honours HTTPS_PROXY / HTTP_PROXY, not the Windows system proxy the browser uses.
    Without this the browser authorises fine and the CLI's token exchange goes out directly."""
    if any(os.environ.get(k) for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")):
        return {}
    import urllib.request

    # Not getproxies(): a lone NO_PROXY in the environment makes it skip the registry.
    reg = getattr(urllib.request, "getproxies_registry", None)
    px = reg() if reg else urllib.request.getproxies()
    url = px.get("https") or px.get("http")
    if not url:
        return {}
    if "://" not in url:
        url = "http://" + url
    elif url.startswith("https://"):
        url = "http://" + url[len("https://"):]  # the registry entry names a plain HTTP proxy
    return {"HTTPS_PROXY": url, "HTTP_PROXY": url}


def status(token: str | None = None) -> dict[str, Any]:
    """Login state of the bundled CLI. Never returns the account e-mail or any token."""
    exe = cli_path()
    if not exe:
        return {"available": False, "logged_in": False, "detail": "Claude Code CLI not found (uv sync installs it with claude-agent-sdk)"}
    if token:
        return {"available": True, "logged_in": True, "method": "token", "plan": ""}
    try:
        out = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=30, env={**os.environ, **_env(None)})
        data = _json.loads(out.stdout or "{}")
    except Exception as e:  # noqa: BLE001
        return {"available": True, "logged_in": False, "detail": f"could not read login status: {type(e).__name__}"}
    expired = False
    try:
        from datetime import datetime, timezone

        exp = data.get("loginExpiresAt")
        expired = bool(exp) and datetime.fromisoformat(exp.replace("Z", "+00:00")) < datetime.now(timezone.utc)
    except ValueError:
        pass
    if expired:
        return {"available": True, "logged_in": False, "method": data.get("authMethod", ""), "plan": data.get("subscriptionType", ""),
                "detail": "login expired; run `autoapply claude-login`"}
    return {
        "available": True,
        "logged_in": bool(data.get("loggedIn")),
        "method": data.get("authMethod", ""),
        "plan": data.get("subscriptionType", ""),
    }


def login() -> int:
    """Interactive login in the current terminal (opens the browser)."""
    exe = cli_path()
    if not exe:
        raise SDKError("Claude Code CLI not found", unavailable=True)
    return subprocess.call([exe, "auth", "login"], env={**os.environ, **_env(None)})


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="claude-sdk", daemon=True).start()
        return _loop


def _mcp_content(out: Any) -> list[dict[str, Any]]:
    """Tool output (str or Anthropic-style blocks) -> MCP content blocks."""
    if not isinstance(out, list):
        return [{"type": "text", "text": str(out)}]
    blocks = []
    for b in out:
        if b.get("type") == "image":
            src = b["source"]
            blocks.append({"type": "image", "data": src["data"], "mimeType": src["media_type"]})
        else:
            blocks.append({"type": "text", "text": b.get("text", "")})
    return blocks


async def _run(content: Any, *, system: str | None, model: str, effort: str | None, schema: dict[str, Any] | None,
               tools: list[Any], max_turns: int, token: str | None, calls: "queue.Queue[Any]", timeout: float, res: SDKResult) -> SDKResult:
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, RateLimitEvent, ResultMessage, create_sdk_mcp_server, query, tool
    sdk_tools = []
    for t in tools:

        def make(t: Any = t):  # noqa: ANN202
            @tool(t.name, t.description, t.input_schema)
            async def handler(args: dict[str, Any]) -> dict[str, Any]:
                reply: cf.Future = cf.Future()
                calls.put((t, args or {}, reply))
                step: dict[str, Any] = {"tool": t.name, "input": args}
                try:
                    out = await asyncio.wrap_future(reply)
                    step["ok"], step["output"] = True, (out if isinstance(out, str) else "[blocks]")[:2000]
                    payload: dict[str, Any] = {"content": _mcp_content(out)}
                except Exception as e:  # noqa: BLE001 - errors go back to the model
                    step["ok"], step["output"] = False, f"{type(e).__name__}: {e}"[:2000]
                    payload = {"content": [{"type": "text", "text": step["output"]}], "is_error": True}
                res.steps.append(step)
                calls.put(("step", step))
                return payload

            return handler

        sdk_tools.append(make())

    opts = ClaudeAgentOptions(
        tools=[],  # no built-in tools (no shell, no file access)
        setting_sources=[],  # ignore the user's Claude Code settings, CLAUDE.md, hooks
        system_prompt=system or "",
        model=model,
        effort=effort,  # type: ignore[arg-type]
        max_turns=max_turns,
        cwd=tempfile.gettempdir(),
        env=_env(token),
        output_format={"type": "json_schema", "schema": schema} if schema else None,
        mcp_servers={SERVER: create_sdk_mcp_server(SERVER, tools=sdk_tools)} if sdk_tools else {},
        allowed_tools=[f"mcp__{SERVER}__{t.name}" for t in tools],
        strict_mcp_config=True,
    )

    async def prompt():  # noqa: ANN202
        yield {"type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None}

    async def consume() -> None:
        async for msg in query(prompt=prompt(), options=opts):
            if isinstance(msg, RateLimitEvent):   # how much of the subscription's allowance is used: kept for the settings page and the low-allowance warning
                try:
                    from . import quota

                    info = msg.rate_limit_info
                    quota.remember_claude(info.raw or {"status": info.status, "rateLimitType": info.rate_limit_type, "resetsAt": info.resets_at})
                except Exception:  # noqa: BLE001 - bookkeeping must never fail a call
                    pass
                continue
            if isinstance(msg, AssistantMessage) and msg.stop_reason == "refusal":
                raise SDKError("the model declined this request", refused=True)
            if isinstance(msg, ResultMessage):
                u = msg.usage or {}
                res.turns = msg.num_turns
                res.input_tokens = int(u.get("input_tokens", 0) or 0) + int(u.get("cache_read_input_tokens", 0) or 0) + int(u.get("cache_creation_input_tokens", 0) or 0)
                res.output_tokens = int(u.get("output_tokens", 0) or 0)
                # kept before any error is raised: a query that failed part-way has still used what it reports
                res.usage, res.cost_usd, res.api_ms, res.session_id = (dict(u) if u else None), msg.total_cost_usd, msg.duration_api_ms, msg.session_id or ""
                try:
                    res.model_usage = {k: dict(v) for k, v in (msg.model_usage or {}).items()} or None
                except Exception:  # noqa: BLE001
                    res.model_usage = None
                res.text, res.structured = msg.result or "", msg.structured_output
                if msg.stop_reason == "refusal":
                    raise SDKError("the model declined this request", refused=True)
                if msg.subtype == "error_max_turns" or msg.terminal_reason == "max_turns":
                    res.stopped = "max_steps"
                elif msg.is_error:
                    detail = (msg.result or "; ".join(msg.errors or []) or msg.subtype)[:400]
                    st = msg.api_error_status
                    low = detail.lower()
                    raise SDKError(detail, status=st, unavailable=st in (401, 403) or "login" in low or "authenticat" in low)

    await asyncio.wait_for(consume(), timeout)
    return res


def call(content: Any, *, system: str | None, model: str, effort: str | None = None, schema: dict[str, Any] | None = None,
         tools: list[Any] | None = None, max_turns: int = 1, token: str | None = None,
         on_step: Callable[[dict[str, Any]], None] | None = None, timeout: float = 900) -> SDKResult:
    """Run one query. Tool functions execute on the calling thread."""
    from claude_agent_sdk import ClaudeSDKError, CLINotFoundError

    calls: queue.Queue[Any] = queue.Queue()
    res = SDKResult()       # filled as the answer arrives, so that an error can still say what was used
    fut = asyncio.run_coroutine_threadsafe(
        _run(content, system=system, model=model, effort=effort, schema=schema, tools=tools or [], max_turns=max_turns,
             token=token, calls=calls, timeout=timeout, res=res),
        _ensure_loop(),
    )
    fut.add_done_callback(lambda _f: calls.put(None))
    while True:
        item = calls.get()
        if item is None:
            break
        if item[0] == "step":
            if on_step:
                on_step(item[1])
            continue
        t, args, reply = item
        try:
            began = time.monotonic()
            good = True
            try:
                reply.set_result(t.fn(**args))
            except BaseException:
                good = False
                raise
            finally:
                timing.mark("tool", t.name, (time.monotonic() - began) * 1000.0, started=began, ok=good)
        except Exception as e:  # noqa: BLE001
            reply.set_exception(e)
    def failed(err: SDKError) -> SDKError:
        err.partial = res      # type: ignore[attr-defined]
        return err

    try:
        return fut.result()
    except SDKError as e:
        raise failed(e)
    except CLINotFoundError as e:
        raise failed(SDKError(f"Claude Code CLI not found: {e}", unavailable=True)) from e
    except (asyncio.TimeoutError, TimeoutError) as e:
        raise failed(SDKError(f"no answer from Claude within {int(timeout)}s")) from e
    except ClaudeSDKError as e:
        low = str(e).lower()
        raise failed(SDKError(str(e)[:400], unavailable="login" in low or "authenticat" in low or "not logged in" in low)) from e
