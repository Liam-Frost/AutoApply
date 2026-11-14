"""This program's tools, offered to an outside agent runtime over MCP (Model Context Protocol).

Used for the ChatGPT backend: the Codex runtime can only be given tools as an MCP server. For the length of one
run, the run's tools are reachable at ``/mcp/run/<token>`` on this program's own local server. The token is random
and single-use; when the run ends the address stops answering. Tool calls are not executed here: they are put on
the run's queue and carried out by the thread that owns the browser page; this side only waits for the answer.

The protocol subset implemented is what a tools-only server needs (streamable HTTP, JSON responses):
initialize, notifications/initialized, ping, tools/list, tools/call.
"""

from __future__ import annotations

import concurrent.futures as cf
import queue
import secrets as _secrets
from dataclasses import dataclass
from typing import Any

PROTOCOL = "2025-06-18"
_open: dict[str, "Bridge"] = {}


@dataclass
class Bridge:
    token: str
    tools: list[Any]
    calls: "queue.Queue[Any]"

    def close(self) -> None:
        _open.pop(self.token, None)


def open(tools: list[Any], calls: "queue.Queue[Any]") -> Bridge:  # noqa: A001
    b = Bridge(_secrets.token_urlsafe(24), tools, calls)
    _open[b.token] = b
    return b


def _content(out: Any) -> list[dict[str, Any]]:
    if not isinstance(out, list):
        return [{"type": "text", "text": str(out)}]
    blocks = []
    for x in out:
        if x.get("type") == "image":
            blocks.append({"type": "image", "data": x["source"]["data"], "mimeType": x["source"]["media_type"]})
        else:
            blocks.append({"type": "text", "text": x.get("text", "")})
    return blocks


def handle(token: str, msg: dict[str, Any], *, timeout: float = 300) -> dict[str, Any] | None:
    """One JSON-RPC message in, the reply out (None for notifications). Raises KeyError for an unknown or closed run."""
    b = _open[token]
    mid, method, params = msg.get("id"), msg.get("method", ""), msg.get("params") or {}
    if mid is None:  # a notification (notifications/initialized, cancelled ...): nothing to answer
        return None

    def ok(result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion") or PROTOCOL, "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "autoapply", "version": "1"}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": t.name, "description": t.description, "inputSchema": t.input_schema} for t in b.tools]})
    if method == "tools/call":
        tool = next((t for t in b.tools if t.name == params.get("name")), None)
        if tool is None:
            return ok({"content": [{"type": "text", "text": f"unknown tool {params.get('name')}"}], "isError": True})
        reply: cf.Future = cf.Future()
        b.calls.put((tool, params.get("arguments") or {}, reply))
        try:
            return ok({"content": _content(reply.result(timeout=timeout)), "isError": False})
        except Exception as e:  # noqa: BLE001 - the tool's own error goes back to the model as a failed call
            return ok({"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"[:2000]}], "isError": True})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
