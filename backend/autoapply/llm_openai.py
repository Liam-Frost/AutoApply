"""Models from other vendors, through the OpenAI-compatible chat API that nearly all of them offer
(OpenAI, Google Gemini, DeepSeek, Qwen, OpenRouter, local servers such as Ollama or LM Studio, and
anything the user configures by URL).

Same three entry points as ``llm``: text, json (schema-constrained) and a tool-use loop. Differences
between vendors are handled here, not by callers:
* structured output: strict JSON schema where the server accepts it, otherwise JSON mode with the
  schema in the prompt, otherwise plain text that is parsed;
* documents: PDFs are sent as extracted text;
* screenshots returned by tools go in a follow-up user message (tool messages cannot carry images).
"""

from __future__ import annotations

from .say import say as T

import base64
import json as _json
import re
from typing import Any, Callable

import httpx

# Built-in vendors. No model names here on purpose: they change often, so the settings page reads the
# vendor's own model list and the user picks from it.
PRESETS: dict[str, dict[str, str]] = {
    "openai": {"name": T("server.llm_openai.openaiChatgptApi"), "base_url": "https://api.openai.com/v1", "keys": "https://platform.openai.com/api-keys"},
    "gemini": {"name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "keys": "https://aistudio.google.com/apikey"},
    "deepseek": {"name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "keys": "https://platform.deepseek.com/api_keys"},
    "qwen": {"name": T("server.llm_openai.qwenAlibabaCloudModel"), "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "keys": "https://bailian.console.aliyun.com/"},
    "openrouter": {"name": T("server.llm_openai.openrouterOneKeyFor"), "base_url": "https://openrouter.ai/api/v1", "keys": "https://openrouter.ai/keys"},
    "custom": {"name": T("server.llm_openai.customAnyOpenaiCompatible"), "base_url": "", "keys": ""},
}


class Unavailable(RuntimeError):
    """Cannot be used right now (no key, wrong key, out of quota, unreachable)."""


class Failed(RuntimeError):
    pass


class Client:
    def __init__(self, base_url: str, api_key: str | None, *, transport: httpx.BaseTransport | None = None) -> None:
        if not base_url:
            raise Unavailable(T("server.llm_openai.noEndpointUrlSet"))
        self.base = base_url.rstrip("/")
        self.http = httpx.Client(timeout=httpx.Timeout(300, connect=30), headers={"Authorization": f"Bearer {api_key}"} if api_key else {}, transport=transport)
        self.calls = self.input_tokens = self.output_tokens = 0
        self.effort = ""        # "low" ... "xhigh": sent as reasoning_effort when the applicant chose one for this service
        self.log: list[dict[str, Any]] = []     # one entry per request: when, how long, how it ended, the usage as reported

    # --- plumbing ---
    def _post(self, body: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        """``timeout`` (seconds): the most this one request may take - for a caller that has a deadline of its own."""
        import time

        if self.effort:
            body = {**body, "reasoning_effort": self.effort}
        t0 = time.time()
        entry: dict[str, Any] = {"t0": t0, "model": body.get("model", ""), "status": "error", "usage": None, "id": "", "error": ""}
        self.log.append(entry)
        try:
            limits = {"timeout": httpx.Timeout(max(1.0, timeout), connect=min(30.0, max(1.0, timeout)))} if timeout is not None else {}
            r = self.http.post(self.base + "/chat/completions", json=body, **limits)
        except httpx.HTTPError as e:
            entry.update(ms=int((time.time() - t0) * 1000), status="timeout" if isinstance(e, httpx.TimeoutException) else "unavailable", error=type(e).__name__)
            raise Unavailable(T("server.llm_openai.canTReachThe", p0=type(e).__name__)) from e
        entry["ms"] = int((time.time() - t0) * 1000)
        if r.status_code in (401, 403):
            entry.update(status="unavailable", error=f"HTTP {r.status_code}")
            raise Unavailable(T("server.llm_openai.theAiServiceRejected"))
        if r.status_code == 402 or (r.status_code == 429 and re.search(r"quota|billing|insufficient|balance", r.text, re.I)):
            entry.update(status="rate_limited", error=f"HTTP {r.status_code}")
            raise Unavailable(T("server.llm_openai.theAiServiceIs", p0=r.text[:200]))
        if r.status_code >= 400:
            entry.update(status="rate_limited" if r.status_code == 429 else "error", error=f"HTTP {r.status_code}")
            raise Failed(f"HTTP {r.status_code}: {r.text[:400]}")
        data = r.json()
        u = data.get("usage") or {}
        entry.update(status="ok", usage=u or None, id=str(data.get("id") or ""), model=str(data.get("model") or entry["model"]))
        self.calls += 1
        self.input_tokens += int(u.get("prompt_tokens") or 0)
        self.output_tokens += int(u.get("completion_tokens") or 0)
        return data

    def models(self) -> list[str]:
        try:
            r = self.http.get(self.base + "/models")
        except httpx.HTTPError as e:
            raise Unavailable(T("server.llm_openai.cantReachTheAi", p0=type(e).__name__)) from e
        if r.status_code in (401, 403):
            raise Unavailable(T("server.llm_openai.theAiServiceRejected2"))
        if r.status_code >= 400:
            raise Failed(T("server.llm_openai.thisServiceDoesnT", p0=r.status_code))
        rows = r.json().get("data") or r.json().get("models") or []
        return sorted({str(m.get("id") or m.get("name") or "").removeprefix("models/") for m in rows if isinstance(m, dict)} - {""})

    # --- the three entry points ---
    def text(self, prompt: Any, *, model: str, system: str | None = None, max_tokens: int = 16000) -> str:
        data = self._post(_body(model, _messages(prompt, system), max_tokens))
        return (data["choices"][0]["message"].get("content") or "").strip()

    def json(self, prompt: Any, schema: dict[str, Any], *, model: str, system: str | None = None, max_tokens: int = 16000) -> Any:
        hint = "\n\nReply with one JSON object that follows this JSON Schema exactly, and nothing else:\n" + _json.dumps(schema, ensure_ascii=False)
        attempts: list[tuple[dict[str, Any] | None, bool]] = [
            ({"type": "json_schema", "json_schema": {"name": "result", "schema": schema, "strict": True}}, False),
            ({"type": "json_object"}, True),
            (None, True),
        ]
        last: Exception | None = None
        for fmt, with_hint in attempts:
            body = _body(model, _messages(prompt, (system or "") + (hint if with_hint else "")), max_tokens)
            if fmt:
                body["response_format"] = fmt
            try:
                data = self._post(body)
            except Failed as e:  # this server does not know that response format: try the next, simpler one
                last = e
                continue
            raw = data["choices"][0]["message"].get("content") or ""
            try:
                return _parse_json(raw)
            except ValueError as e:
                last = Failed(T("server.llm_openai.theModelDidntReturn", p0=raw[:200]))
                last.__cause__ = e
        raise last or Failed("no structured output")

    def agent(self, goal: str, tools: list[Any], *, model: str, system: str, budget: Any,
              on_step: Callable[[dict[str, Any]], None] | None = None) -> tuple[str, list[dict[str, Any]], str]:
        """Tool-use loop. ``tools`` are ``llm.Tool`` objects, each of which spends from ``budget`` when it is called
        (agentbudget.py). Returns (final_text, steps, stopped): stopped is "end_turn", or what the budget ended on."""
        from .agentbudget import Spent

        by_name = {t.name: t for t in tools}
        specs = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}} for t in tools]
        messages = _messages(goal, system)
        steps: list[dict[str, Any]] = []
        while True:
            if budget.expired():
                return "", steps, budget.ended
            body = _body(model, messages, 16000)
            body["tools"] = specs
            # The request is given what is left of the budget and no more: the deadline is the run's, and a model
            # that answers after it has not answered in time - whatever it says.
            try:
                msg = self._post(body, timeout=budget.left())["choices"][0]["message"]
            except (Unavailable, Failed):
                if budget.expired():
                    return "", steps, budget.ended
                raise
            if budget.expired():
                return "", steps, budget.ended
            calls = msg.get("tool_calls") or []
            messages.append({"role": "assistant", "content": msg.get("content") or "", **({"tool_calls": calls} if calls else {})})
            if not calls:
                return (msg.get("content") or "").strip(), steps, "end_turn"
            images: list[dict[str, Any]] = []
            for c in calls:
                name = c["function"]["name"]
                step: dict[str, Any] = {"tool": name}
                try:
                    args = _json.loads(c["function"].get("arguments") or "{}")
                    step["input"] = args
                    tool = by_name.get(name)
                    if tool is None:
                        budget.spend()      # a call to a tool that is not there is a step too
                        raise KeyError(f"unknown tool {name}")
                    out = tool.fn(**args)
                    if isinstance(out, list):  # content blocks (a screenshot)
                        txt = " ".join(b.get("text", "") for b in out if b.get("type") == "text") or "see the image in the next message"
                        images += [b for b in out if b.get("type") == "image"]
                        step["output"] = "[blocks]"
                    else:
                        txt = str(out)
                        step["output"] = txt[:2000]
                    step["ok"] = True
                except Spent as e:      # not an error for the model to work around: the run ends here
                    return "", steps, e.why
                except Exception as e:  # noqa: BLE001 - errors go back to the model
                    txt = f"{type(e).__name__}: {e}"
                    step.update(ok=False, output=txt[:2000])
                    step.setdefault("input", {})
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": txt})
                steps.append(step)
                if on_step:
                    on_step(step)
            if images:
                messages.append({"role": "user", "content": [{"type": "text", "text": "Image(s) returned by the tool call(s) above:"}, *[_image(b) for b in images]]})


def _body(model: str, messages: list[dict[str, Any]], max_tokens: int) -> dict[str, Any]:
    if not model:
        raise Unavailable(T("server.llm_openai.noModelSelectedYet"))
    # (the newer OpenAI models take the limit under another name - all of them from gpt-5 on, not only gpt-5)
    return {"model": model, "messages": messages, "max_completion_tokens" if re.match(r"(gpt-[5-9]|o\d)", model) else "max_tokens": max_tokens}


def _image(block: dict[str, Any]) -> dict[str, Any]:
    src = block["source"]
    return {"type": "image_url", "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"}}


def _pdf_text(b64: str) -> str:
    import io

    from pypdf import PdfReader

    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(base64.standard_b64decode(b64))).pages)


def _content(prompt: Any) -> Any:
    """Anthropic-style content blocks -> what the chat API takes."""
    if isinstance(prompt, str):
        return prompt
    out: list[dict[str, Any]] = []
    for b in prompt:
        if b.get("type") == "text":
            out.append({"type": "text", "text": b["text"]})
        elif b.get("type") == "image":
            out.append(_image(b))
        elif b.get("type") == "document":
            out.append({"type": "text", "text": "<document>\n" + _pdf_text(b["source"]["data"]) + "\n</document>"})
    if all(x["type"] == "text" for x in out):
        return "\n\n".join(x["text"] for x in out)
    return out


def _messages(prompt: Any, system: str | None) -> list[dict[str, Any]]:
    return ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": _content(prompt)}]


def _parse_json(raw: str) -> Any:
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*(.+?)```", s, re.S)
    if m:
        s = m.group(1).strip()
    if not s.startswith(("{", "[")):
        i, j = s.find("{"), s.rfind("}")
        if i < 0 or j <= i:
            raise ValueError("no JSON object")
        s = s[i:j + 1]
    return _json.loads(s)
