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

import base64
import json as _json
import re
from typing import Any, Callable

import httpx

# Built-in vendors. No model names here on purpose: they change often, so the settings page reads the
# vendor's own model list and the user picks from it.
PRESETS: dict[str, dict[str, str]] = {
    "openai": {"name": "OpenAI（ChatGPT 的 API）", "base_url": "https://api.openai.com/v1", "keys": "https://platform.openai.com/api-keys"},
    "gemini": {"name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "keys": "https://aistudio.google.com/apikey"},
    "deepseek": {"name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "keys": "https://platform.deepseek.com/api_keys"},
    "qwen": {"name": "通义千问（阿里云百炼）", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "keys": "https://bailian.console.aliyun.com/"},
    "openrouter": {"name": "OpenRouter（一个 key 用多家模型）", "base_url": "https://openrouter.ai/api/v1", "keys": "https://openrouter.ai/keys"},
    "custom": {"name": "自定义（任何兼容 OpenAI 接口的服务，包括本机的 Ollama / LM Studio）", "base_url": "", "keys": ""},
}


class Unavailable(RuntimeError):
    """Cannot be used right now (no key, wrong key, out of quota, unreachable)."""


class Failed(RuntimeError):
    pass


class Client:
    def __init__(self, base_url: str, api_key: str | None, *, transport: httpx.BaseTransport | None = None) -> None:
        if not base_url:
            raise Unavailable("还没有填这个 AI 服务的接口地址")
        self.base = base_url.rstrip("/")
        self.http = httpx.Client(timeout=httpx.Timeout(300, connect=30), headers={"Authorization": f"Bearer {api_key}"} if api_key else {}, transport=transport)
        self.calls = self.input_tokens = self.output_tokens = 0
        self.log: list[dict[str, Any]] = []     # one entry per request: when, how long, how it ended, the usage as reported

    # --- plumbing ---
    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        import time

        t0 = time.time()
        entry: dict[str, Any] = {"t0": t0, "model": body.get("model", ""), "status": "error", "usage": None, "id": "", "error": ""}
        self.log.append(entry)
        try:
            r = self.http.post(self.base + "/chat/completions", json=body)
        except httpx.HTTPError as e:
            entry.update(ms=int((time.time() - t0) * 1000), status="timeout" if isinstance(e, httpx.TimeoutException) else "unavailable", error=type(e).__name__)
            raise Unavailable(f"连不上 AI 服务（{type(e).__name__}）。检查接口地址和“设置 → 网络”。") from e
        entry["ms"] = int((time.time() - t0) * 1000)
        if r.status_code in (401, 403):
            entry.update(status="unavailable", error=f"HTTP {r.status_code}")
            raise Unavailable("AI 服务拒绝了这个 API key（没填、填错或没有权限）。")
        if r.status_code == 402 or (r.status_code == 429 and re.search(r"quota|billing|insufficient|balance", r.text, re.I)):
            entry.update(status="rate_limited", error=f"HTTP {r.status_code}")
            raise Unavailable(f"AI 服务的额度用完了或账户欠费：{r.text[:200]}")
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
            raise Unavailable(f"连不上 AI 服务（{type(e).__name__}）") from e
        if r.status_code in (401, 403):
            raise Unavailable("AI 服务拒绝了这个 API key。")
        if r.status_code >= 400:
            raise Failed(f"这个服务不提供模型列表（HTTP {r.status_code}），请手动填写模型名称。")
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
                last = Failed(f"模型没有按要求返回 JSON：{raw[:200]}")
                last.__cause__ = e
        raise last or Failed("no structured output")

    def agent(self, goal: str, tools: list[Any], *, model: str, system: str, max_steps: int = 60,
              on_step: Callable[[dict[str, Any]], None] | None = None) -> tuple[str, list[dict[str, Any]], str]:
        """Tool-use loop. ``tools`` are ``llm.Tool`` objects. Returns (final_text, steps, stopped)."""
        by_name = {t.name: t for t in tools}
        specs = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}} for t in tools]
        messages = _messages(goal, system)
        steps: list[dict[str, Any]] = []
        for _ in range(max_steps):
            body = _body(model, messages, 16000)
            body["tools"] = specs
            msg = self._post(body)["choices"][0]["message"]
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
        return "", steps, "max_steps"


def _body(model: str, messages: list[dict[str, Any]], max_tokens: int) -> dict[str, Any]:
    if not model:
        raise Unavailable("还没有选模型。请在“设置 → AI 模型”里选择或填写模型名称。")
    return {"model": model, "messages": messages, "max_completion_tokens" if model.startswith(("gpt-5", "o1", "o3", "o4")) else "max_tokens": max_tokens}


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
