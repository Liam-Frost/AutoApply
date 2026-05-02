"""Bounded ReAct-style agent loop.

The loop drives an LLM (via the existing CLI wrapper or any injected
callable) through a thought/action/observation cycle until either the
agent calls the `finish` tool or a session limit is hit.

We deliberately implement a manual ReAct loop rather than relying on
provider-native tool use so the same harness works with both `claude`
and `codex` CLIs (neither exposes a clean tool-use protocol over the
exec subcommand). The cost is one extra layer of JSON parsing, which we
make robust below.

Control surfaces -- all enforced by the loop, not advisory:
    * SessionLimits.max_steps   -- hard cap on iterations
    * SessionLimits.step_timeout -- per-LLM-call timeout (seconds)
    * SessionLimits.allow_tool_errors -- abort on first ToolError if False
    * tools allowlist                -- physical inability to call others
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from src.agent.tools.base import ToolRegistry, ToolResult

logger = logging.getLogger("autoapply.agent")

LLMCallable = Callable[[str, str, int], str]
"""(prompt, system, timeout_seconds) -> raw response text."""

FINISH_TOOL = "finish"


class AgentLimitExceeded(Exception):  # noqa: N818 -- naming chosen for readability
    """Raised when the loop hits a configured limit. Caller should treat
    the partial AgentResult as the outcome."""


@dataclass
class SessionLimits:
    max_steps: int = 8
    step_timeout: int = 90
    allow_tool_errors: bool = True


@dataclass
class AgentStep:
    """One iteration of the loop. Captured verbatim into the trace."""

    index: int
    prompt: str
    raw_response: str
    thought: str
    action_name: str
    action_args: dict[str, Any]
    observation: str
    is_error: bool
    latency_ms: int
    parse_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentResult:
    """Outcome handed back to the orchestrator."""

    goal: str
    answer: str | None
    finished: bool
    steps: list[AgentStep] = field(default_factory=list)
    stop_reason: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "answer": self.answer,
            "finished": self.finished,
            "stop_reason": self.stop_reason,
            "elapsed_ms": self.elapsed_ms,
            "steps": [s.to_dict() for s in self.steps],
        }


_SYSTEM_PROMPT = """You are an AutoApply agent. You complete a single \
narrow task by calling the tools listed in the user message.

OUTPUT FORMAT
On every turn output a single JSON object and nothing else:
{
  "thought": "<one short sentence on what you are doing and why>",
  "action": {"name": "<tool_name>", "args": {<json args>}}
}

RULES
- Only use tools that appear in the tool list.
- Call exactly one tool per turn.
- When the task is complete, call the tool named `finish` with an
  `answer` string. Do not finish until the task is actually done.
- Do not invent observations; wait for the next user turn for results.
- Do not include markdown fences, comments, or any text outside the
  JSON object.
"""


class AgentSession:
    """Stateful single-task agent invocation.

    Construction is cheap; call `run()` to execute. The session keeps a
    transcript so the trace store can record it post-hoc.
    """

    def __init__(
        self,
        *,
        goal: str,
        tools: ToolRegistry,
        llm: LLMCallable,
        limits: SessionLimits | None = None,
        system_prompt: str | None = None,
    ) -> None:
        if FINISH_TOOL not in tools:
            raise ValueError(
                f"Agent toolset must include the '{FINISH_TOOL}' sentinel tool."
            )
        self.goal = goal
        self.tools = tools
        self.llm = llm
        self.limits = limits or SessionLimits()
        self.system_prompt = system_prompt or _SYSTEM_PROMPT
        self.steps: list[AgentStep] = []
        self._transcript: list[tuple[str, str]] = []

    def run(self) -> AgentResult:
        """Drive the loop to completion, a limit, or a fatal tool error."""
        started = time.monotonic()
        result = AgentResult(goal=self.goal, answer=None, finished=False)
        try:
            for index in range(1, self.limits.max_steps + 1):
                step = self._step(index)
                self.steps.append(step)
                result.steps = self.steps

                if step.action_name == FINISH_TOOL and not step.is_error:
                    result.answer = step.action_args.get("answer", step.observation)
                    result.finished = True
                    result.stop_reason = "finish"
                    break

                if step.is_error and not self.limits.allow_tool_errors:
                    result.stop_reason = f"tool_error:{step.action_name}"
                    break
            else:
                result.stop_reason = "max_steps"
                raise AgentLimitExceeded(
                    f"Agent did not finish within {self.limits.max_steps} steps."
                )
        except AgentLimitExceeded:
            # Already recorded; surface as a non-finished result.
            pass
        finally:
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result

    def _step(self, index: int) -> AgentStep:
        prompt = self._build_prompt(index)
        t0 = time.monotonic()
        try:
            raw = self.llm(prompt, self.system_prompt, self.limits.step_timeout)
        except Exception as exc:  # noqa: BLE001 -- LLM boundary
            latency = int((time.monotonic() - t0) * 1000)
            logger.warning("LLM call failed at step %d: %s", index, exc)
            return AgentStep(
                index=index,
                prompt=prompt,
                raw_response="",
                thought="",
                action_name="",
                action_args={},
                observation=f"LLM error: {exc}",
                is_error=True,
                latency_ms=latency,
                parse_error=str(exc),
            )
        latency = int((time.monotonic() - t0) * 1000)

        thought, action_name, action_args, parse_error = _parse_response(raw)
        if parse_error:
            obs = (
                f"Parse error: {parse_error}. "
                "Reply with ONLY the JSON object described in the system prompt."
            )
            self._transcript.append(("assistant", raw))
            self._transcript.append(("observation", obs))
            return AgentStep(
                index=index,
                prompt=prompt,
                raw_response=raw,
                thought=thought,
                action_name=action_name,
                action_args=action_args,
                observation=obs,
                is_error=True,
                latency_ms=latency,
                parse_error=parse_error,
            )

        if action_name == FINISH_TOOL:
            answer = str(action_args.get("answer", ""))
            self._transcript.append(("assistant", raw))
            return AgentStep(
                index=index,
                prompt=prompt,
                raw_response=raw,
                thought=thought,
                action_name=action_name,
                action_args=action_args,
                observation=answer,
                is_error=False,
                latency_ms=latency,
            )

        if action_name not in self.tools:
            obs = (
                f"Tool '{action_name}' is not available. "
                f"Allowed tools: {self.tools.names()}."
            )
            self._transcript.append(("assistant", raw))
            self._transcript.append(("observation", obs))
            return AgentStep(
                index=index,
                prompt=prompt,
                raw_response=raw,
                thought=thought,
                action_name=action_name,
                action_args=action_args,
                observation=obs,
                is_error=True,
                latency_ms=latency,
            )

        tool_result = self.tools.get(action_name).invoke(action_args)
        self._transcript.append(("assistant", raw))
        self._transcript.append(("observation", _format_observation(tool_result)))
        return AgentStep(
            index=index,
            prompt=prompt,
            raw_response=raw,
            thought=thought,
            action_name=action_name,
            action_args=action_args,
            observation=tool_result.output,
            is_error=tool_result.is_error,
            latency_ms=latency,
        )

    def _build_prompt(self, index: int) -> str:
        if index == 1:
            header = (
                f"GOAL\n{self.goal}\n\n"
                f"AVAILABLE TOOLS\n{self.tools.render_for_prompt()}\n\n"
                "Begin. Output the JSON object now."
            )
            return header

        history_lines = []
        for role, content in self._transcript:
            label = "ASSISTANT" if role == "assistant" else "OBSERVATION"
            history_lines.append(f"--- {label} ---\n{content}")
        history = "\n".join(history_lines)
        return (
            f"GOAL\n{self.goal}\n\n"
            f"AVAILABLE TOOLS\n{self.tools.render_for_prompt()}\n\n"
            f"TRANSCRIPT SO FAR\n{history}\n\n"
            "Continue. Output the next JSON object."
        )


def run_agent(
    goal: str,
    tools: ToolRegistry,
    llm: LLMCallable,
    *,
    limits: SessionLimits | None = None,
) -> AgentResult:
    """Convenience wrapper around AgentSession for one-shot use."""
    return AgentSession(goal=goal, tools=tools, llm=llm, limits=limits).run()


# ---------- response parsing ----------

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(?P<body>.*?)```", re.DOTALL | re.IGNORECASE)


def _parse_response(raw: str) -> tuple[str, str, dict[str, Any], str | None]:
    """Extract (thought, action_name, action_args, parse_error) from raw LLM text.

    The agent is instructed to output strict JSON, but we tolerate code
    fences and leading/trailing prose so a single sloppy turn does not
    derail the whole session.
    """
    text = (raw or "").strip()
    if not text:
        return "", "", {}, "empty response"

    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group("body").strip()

    obj, err = _extract_json_object(text)
    if obj is None:
        return "", "", {}, err or "no JSON object found"

    if not isinstance(obj, dict):
        return "", "", {}, f"expected JSON object, got {type(obj).__name__}"

    thought = str(obj.get("thought", "")).strip()
    action = obj.get("action")
    if not isinstance(action, dict):
        return thought, "", {}, "missing 'action' object"

    name = action.get("name")
    args = action.get("args", {})
    if not isinstance(name, str) or not name:
        return thought, "", {}, "missing or non-string 'action.name'"
    if not isinstance(args, dict):
        return thought, name, {}, "'action.args' must be an object"

    return thought, name, args, None


def _extract_json_object(text: str) -> tuple[Any, str | None]:
    """Robustly extract the first JSON object from a string.

    Tries strict parse first, then a brace-balanced scan for cases where
    the model emitted prose before/after the JSON.
    """
    try:
        return json.loads(text), None
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate), None
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None, "could not parse JSON object from response"


def _format_observation(result: ToolResult) -> str:
    prefix = "ERROR: " if result.is_error else ""
    return f"{prefix}{result.output}"
