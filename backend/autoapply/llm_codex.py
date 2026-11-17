"""ChatGPT subscription, through OpenAI's official Codex SDK (``openai-codex``).

How it fits together:
* Sign-in is the SDK's own "Sign in with ChatGPT" (browser) flow; this program never sees a password or token.
* Writing and structured output: one turn on a fresh thread, with ``output_schema`` for JSON.
* Tool use (the model operating a web page through this program's tools): Codex takes tools from MCP servers.
  ``toolbridge`` serves the tools of the current run on a one-off local address inside this program's own server;
  the thread is started with that address as its only MCP server. Tool functions still run on the calling thread
  (the one that owns the browser page), exactly as with the Claude backend.

The SDK is an optional install (it ships a ~190 MB runtime): ``uv sync --extra chatgpt``.

STATUS: text, structured output and a tool call through the bridge were run with a real ChatGPT account (2026-11-14).
The sign-in flow from this program (login_chatgpt) and a full site-exploration run have not been exercised.
"""

from __future__ import annotations

import concurrent.futures as cf
import json as _json
import queue
import tempfile
import threading
from typing import Any, Callable

RULES = ("You are used as a plain language model here, not as a coding agent. Do not run shell commands, do not read or write files, "
         "do not browse. Use only the tools named autoapply (if any are provided) and answer from the text you are given.")


class Unavailable(RuntimeError):
    pass


class Failed(RuntimeError):
    pass


def installed() -> bool:
    try:
        import openai_codex  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _codex():  # noqa: ANN202
    try:
        from openai_codex import Codex
    except Exception as e:  # noqa: BLE001
        raise Unavailable("还没有安装 ChatGPT 接入组件。在程序目录运行：uv sync --extra chatgpt（会下载约 190 MB）。") from e
    return Codex()


_login: dict[str, Any] = {"state": "", "url": "", "error": ""}


def status() -> dict[str, Any]:
    if not installed():
        return {"installed": False, "logged_in": False, "login": dict(_login)}
    try:
        with _codex() as c:
            acc = c.account()
        d = acc.model_dump() if hasattr(acc, "model_dump") else {}
        a = d.get("account") or {}
        val = lambda x: str(getattr(x, "value", x) or "")  # noqa: E731
        return {"installed": True, "logged_in": bool(a), "method": val(a.get("type")), "plan": val(a.get("plan_type")), "login": dict(_login)}
    except Exception as e:  # noqa: BLE001
        return {"installed": True, "logged_in": False, "detail": f"{type(e).__name__}: {str(e)[:160]}", "login": dict(_login)}


def login() -> dict[str, Any]:
    """Start "Sign in with ChatGPT": opens the sign-in page in the user's browser and waits for it in the background."""
    codex = _codex()
    codex.__enter__()
    try:
        h = codex.login_chatgpt()
    except Exception as e:  # noqa: BLE001
        codex.__exit__(None, None, None)
        raise Failed(f"没能开始登录：{type(e).__name__}: {str(e)[:200]}") from e
    _login.update(state="waiting", url=h.auth_url, error="")

    def wait() -> None:
        try:
            done = h.wait()
            ok = bool(getattr(done, "success", True))
            _login.update(state="done" if ok else "failed", error="" if ok else str(getattr(done, "error", "") or "登录没有完成"))
        except Exception as e:  # noqa: BLE001
            _login.update(state="failed", error=f"{type(e).__name__}: {str(e)[:160]}")
        finally:
            codex.__exit__(None, None, None)

    threading.Thread(target=wait, daemon=True, name="chatgpt-login").start()
    try:
        import webbrowser

        webbrowser.open(h.auth_url)
    except Exception:  # noqa: BLE001
        pass
    return {"auth_url": h.auth_url}


def models() -> list[str]:
    """The models this ChatGPT account can use."""
    try:
        with _codex() as c:
            r = c.models()
    except Unavailable:
        raise
    except Exception as e:  # noqa: BLE001
        raise Failed(f"没能读取模型列表：{type(e).__name__}: {str(e)[:160]}") from e
    d = r.model_dump() if hasattr(r, "model_dump") else {}
    rows = d.get("data") or d.get("models") or []
    return [str(m.get("id") or m.get("model") or m.get("slug") or "") for m in rows if isinstance(m, dict) and (m.get("id") or m.get("model") or m.get("slug"))]


def logout() -> None:
    with _codex() as c:
        c.logout()
    _login.update(state="", url="", error="")


def run(prompt: Any, *, system: str | None = None, model: str = "", schema: dict[str, Any] | None = None, tools: list[Any] | None = None,
        on_step: Callable[[dict[str, Any]], None] | None = None, base_url: str = "", timeout: float = 3600) -> tuple[str, list[dict[str, Any]], dict[str, int]]:
    """One turn (with tool use if ``tools`` is given). Returns (final_text, steps, usage). Tool functions run on the calling thread."""
    from . import toolbridge

    if not isinstance(prompt, str):
        raise Failed("用 ChatGPT 登录时暂不支持在提问里附带图片或文件。")
    codex = _codex()
    calls: queue.Queue[Any] = queue.Queue()
    steps: list[dict[str, Any]] = []
    bridge = toolbridge.open(tools or [], calls) if tools else None
    result: cf.Future = cf.Future()

    def work() -> None:
        try:
            from openai_codex import Sandbox

            cfg: dict[str, Any] = {}
            if bridge is not None:
                cfg["mcp_servers"] = {"autoapply": {"url": f"{base_url.rstrip('/')}/mcp/run/{bridge.token}", "default_tools_approval_mode": "approve",
                                                    "startup_timeout_sec": 30, "tool_timeout_sec": 300}}
            with codex as c, tempfile.TemporaryDirectory(prefix="autoapply-codex-", ignore_cleanup_errors=True) as d:  # an empty folder: nothing for an agent to read
                th = c.thread_start(base_instructions=(system or "") + "\n\n" + RULES, config=cfg or None, cwd=d, ephemeral=True, sandbox=Sandbox.read_only, model=model or None)
                r = th.run(prompt, output_schema=schema)
                err = getattr(r, "error", None)
                if err is not None:
                    raise Failed(str(getattr(err, "message", err))[:400])
                u = getattr(r, "usage", None)
                tot = getattr(u, "total", u)
                g = lambda k: int(getattr(tot, k, 0) or 0)  # noqa: E731
                usage = {"input": g("input_tokens"), "output": g("output_tokens"), "cached": g("cached_input_tokens"), "cache_write": g("cache_write_input_tokens"),
                         "reasoning": g("reasoning_output_tokens"), "total": g("total_tokens")}
                result.set_result((r.final_response or "", usage))
        except Exception as e:  # noqa: BLE001
            if not result.done():
                result.set_exception(e)
        finally:
            calls.put(None)

    threading.Thread(target=work, daemon=True, name="chatgpt-turn").start()
    try:
        while True:  # tool calls arrive from the bridge; run them here, on the thread that owns the page
            item = calls.get(timeout=timeout)
            if item is None:
                break
            t, args, reply = item
            step: dict[str, Any] = {"tool": t.name, "input": args}
            try:
                out = t.fn(**args)
                step.update(ok=True, output="[blocks]" if isinstance(out, list) else str(out)[:2000])
                reply.set_result(out)
            except Exception as e:  # noqa: BLE001 - errors go back to the model
                step.update(ok=False, output=f"{type(e).__name__}: {e}"[:2000])
                reply.set_exception(e)
            steps.append(step)
            if on_step:
                on_step(step)
    except queue.Empty as e:
        raise Failed("ChatGPT 这一步超时了") from e
    finally:
        if bridge is not None:
            bridge.close()
    try:
        text, usage = result.result(timeout=30)
    except (Unavailable, Failed):
        raise
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {str(e)[:300]}"
        low = msg.lower()
        if any(w in low for w in ("login", "auth", "unauthorized", "usage limit", "rate limit", "quota", "not signed in")):
            raise Unavailable(f"ChatGPT 登录不可用或额度已用完：{msg}") from e
        raise Failed(f"ChatGPT 出错：{msg}") from e
    return text, steps, usage


