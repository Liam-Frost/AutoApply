"""Tests for the Phase 8.2 agent loop."""

from __future__ import annotations

import json

import pytest

from src.agent.core import (
    AgentSession,
    SessionLimits,
    run_agent,
)
from src.agent.core.loop import _parse_response
from src.agent.tools import Tool, ToolRegistry, ToolResult
from src.agent.tools.builtin import FinishTool, TextSummarizeTool


class _ScriptedLLM:
    """Plays back a fixed list of responses, one per call."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, int]] = []

    def __call__(self, prompt: str, system: str, timeout: int) -> str:
        self.calls.append((prompt, system, timeout))
        if not self._responses:
            raise AssertionError("LLM called more times than scripted.")
        return self._responses.pop(0)


def _registry_with(*tools: Tool) -> ToolRegistry:
    reg = ToolRegistry()
    for tool in tools:
        reg.register(tool)
    reg.register(FinishTool())
    return reg


class TestParseResponse:
    def test_parses_strict_json(self):
        thought, name, args, err = _parse_response(
            '{"thought":"go","action":{"name":"finish","args":{"answer":"hi"}}}'
        )
        assert err is None
        assert thought == "go"
        assert name == "finish"
        assert args == {"answer": "hi"}

    def test_strips_code_fences(self):
        raw = "```json\n" + json.dumps(
            {"thought": "t", "action": {"name": "finish", "args": {"answer": "ok"}}}
        ) + "\n```"
        _, name, args, err = _parse_response(raw)
        assert err is None
        assert name == "finish"
        assert args["answer"] == "ok"

    def test_extracts_json_with_surrounding_prose(self):
        raw = (
            "Sure, here is my next action:\n"
            '{"thought":"finish","action":{"name":"finish","args":{"answer":"done"}}}\n'
            "Hope that helps."
        )
        _, name, args, err = _parse_response(raw)
        assert err is None
        assert name == "finish"
        assert args["answer"] == "done"

    def test_reports_empty(self):
        assert _parse_response("")[3] == "empty response"

    def test_reports_missing_action(self):
        _, _, _, err = _parse_response('{"thought":"hmm"}')
        assert err == "missing 'action' object"

    def test_reports_bad_args_type(self):
        _, name, _, err = _parse_response(
            '{"thought":"x","action":{"name":"finish","args":"not-an-object"}}'
        )
        assert name == "finish"
        assert err == "'action.args' must be an object"


class TestAgentSession:
    def test_constructor_requires_finish_tool(self):
        reg = ToolRegistry()
        reg.register(TextSummarizeTool())
        with pytest.raises(ValueError):
            AgentSession(goal="x", tools=reg, llm=_ScriptedLLM([]))

    def test_finishes_in_one_step(self):
        llm = _ScriptedLLM(
            ['{"thought":"easy","action":{"name":"finish","args":{"answer":"done"}}}']
        )
        result = run_agent("trivial", _registry_with(), llm)
        assert result.finished
        assert result.answer == "done"
        assert result.stop_reason == "finish"
        assert len(result.steps) == 1

    def test_uses_tool_then_finishes(self):
        llm = _ScriptedLLM(
            [
                json.dumps(
                    {
                        "thought": "measure",
                        "action": {"name": "text_stats", "args": {"text": "hello world"}},
                    }
                ),
                json.dumps(
                    {
                        "thought": "report",
                        "action": {"name": "finish", "args": {"answer": "2 words"}},
                    }
                ),
            ]
        )
        result = run_agent("count words", _registry_with(TextSummarizeTool()), llm)
        assert result.finished
        assert result.answer == "2 words"
        assert [s.action_name for s in result.steps] == ["text_stats", "finish"]
        assert "words=2" in result.steps[0].observation

    def test_unknown_tool_becomes_observable_error(self):
        llm = _ScriptedLLM(
            [
                json.dumps({"thought": "?", "action": {"name": "ghost", "args": {}}}),
                json.dumps(
                    {"thought": "give up", "action": {"name": "finish", "args": {"answer": "x"}}}
                ),
            ]
        )
        result = run_agent("x", _registry_with(), llm)
        assert result.finished
        assert result.steps[0].is_error
        assert "not available" in result.steps[0].observation

    def test_parse_error_recoverable(self):
        llm = _ScriptedLLM(
            [
                "this is not JSON at all",
                json.dumps(
                    {
                        "thought": "retry",
                        "action": {"name": "finish", "args": {"answer": "ok"}},
                    }
                ),
            ]
        )
        result = run_agent("x", _registry_with(), llm)
        assert result.finished
        assert result.steps[0].parse_error is not None
        assert result.steps[0].is_error

    def test_max_steps_caps_runaway(self):
        # Always pick a non-finish tool; loop must stop at max_steps.
        forever = json.dumps(
            {"thought": "loop", "action": {"name": "text_stats", "args": {"text": "x"}}}
        )
        llm = _ScriptedLLM([forever] * 5)
        result = run_agent(
            "loop forever",
            _registry_with(TextSummarizeTool()),
            llm,
            limits=SessionLimits(max_steps=3),
        )
        assert not result.finished
        assert result.stop_reason == "max_steps"
        assert len(result.steps) == 3

    def test_llm_exception_recorded_as_step_error(self):
        def boom(_p, _s, _t):
            raise RuntimeError("network down")

        result = run_agent(
            "x",
            _registry_with(),
            boom,
            limits=SessionLimits(max_steps=1),
        )
        assert not result.finished
        assert result.steps[0].is_error
        assert "network down" in result.steps[0].observation

    def test_tool_error_can_abort_when_disallowed(self):
        class _Failing(Tool):
            name = "bad"
            description = "always fails"
            parameters = {"type": "object", "properties": {}}

            def run(self, _args):
                return ToolResult(output="boom", is_error=True)

        llm = _ScriptedLLM(
            [json.dumps({"thought": "try", "action": {"name": "bad", "args": {}}})]
        )
        result = run_agent(
            "x",
            _registry_with(_Failing()),
            llm,
            limits=SessionLimits(max_steps=4, allow_tool_errors=False),
        )
        assert not result.finished
        assert result.stop_reason == "tool_error:bad"
        assert len(result.steps) == 1

    def test_transcript_includes_tools_each_turn(self):
        llm = _ScriptedLLM(
            [
                json.dumps(
                    {"thought": "use", "action": {"name": "text_stats", "args": {"text": "a"}}}
                ),
                json.dumps(
                    {"thought": "done", "action": {"name": "finish", "args": {"answer": "k"}}}
                ),
            ]
        )
        run_agent("x", _registry_with(TextSummarizeTool()), llm)
        # First call: no transcript yet. Second call: prior assistant + observation included.
        first_prompt, _, _ = llm.calls[0]
        second_prompt, _, _ = llm.calls[1]
        assert "TRANSCRIPT SO FAR" not in first_prompt
        assert "TRANSCRIPT SO FAR" in second_prompt
        assert "OBSERVATION" in second_prompt
        assert "words=1" in second_prompt
