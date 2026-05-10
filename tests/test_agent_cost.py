"""Tests for the Phase 9.4 cost/telemetry module and its plumbing."""

from __future__ import annotations

import pytest

from src.agent.core.cost import (
    CostRates,
    estimate_cost_usd,
    estimate_tokens,
)
from src.agent.core.loop import AgentSession, SessionLimits
from src.agent.eval.runner import RunnerOutput, run_eval, run_suite
from src.agent.tools.base import ToolRegistry
from src.agent.tools.builtin import FinishTool, TextSummarizeTool


class TestEstimateTokens:
    def test_empty_string_zero(self) -> None:
        assert estimate_tokens("") == 0

    def test_short_string_rounds_up(self) -> None:
        # "hi" -> 2 chars -> ceil(2/4) = 1 token.
        assert estimate_tokens("hi") == 1

    def test_long_string_proportional(self) -> None:
        text = "x" * 4000
        assert estimate_tokens(text) == 1000


class TestEstimateCostUsd:
    def test_uses_default_rates(self) -> None:
        rates = CostRates(prompt_per_1k_usd=0.003, output_per_1k_usd=0.015)
        cost = estimate_cost_usd(
            prompt_tokens=2000, output_tokens=500, rates=rates
        )
        # 2 * 0.003 + 0.5 * 0.015 = 0.006 + 0.0075 = 0.0135
        assert cost == pytest.approx(0.0135)

    def test_zero_tokens_zero_cost(self) -> None:
        assert estimate_cost_usd(prompt_tokens=0, output_tokens=0) == 0.0

    def test_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOAPPLY_AGENT_COST_PROMPT_PER_1K", "1.0")
        monkeypatch.setenv("AUTOAPPLY_AGENT_COST_OUTPUT_PER_1K", "2.0")
        rates = CostRates.from_env()
        assert rates.prompt_per_1k_usd == 1.0
        assert rates.output_per_1k_usd == 2.0

    def test_invalid_env_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTOAPPLY_AGENT_COST_PROMPT_PER_1K", "not-a-float")
        rates = CostRates.from_env()
        # Default 0.003.
        assert rates.prompt_per_1k_usd == pytest.approx(0.003)


# ---------------------------------------------------------------------------
# Loop integration -- AgentStep / AgentResult carry telemetry through.
# ---------------------------------------------------------------------------


class TestLoopTelemetry:
    def test_steps_record_token_estimates(self) -> None:
        registry = ToolRegistry()
        registry.register(FinishTool())
        registry.register(TextSummarizeTool())

        responses = [
            "{\"thought\":\"go\",\"action\":{\"name\":\"text_stats\",\"args\":{\"text\":\"hi\"}}}",
            "{\"thought\":\"done\",\"action\":{\"name\":\"finish\",\"args\":{\"answer\":\"ok\"}}}",
        ]
        queue = list(responses)

        def scripted(_p: str, _s: str, _t: int) -> str:
            return queue.pop(0)

        session = AgentSession(
            goal="echo",
            tools=registry,
            llm=scripted,
            limits=SessionLimits(max_steps=3),
            cost_rates=CostRates(prompt_per_1k_usd=1.0, output_per_1k_usd=1.0),
        )
        result = session.run()
        assert result.finished
        assert all(s.prompt_tokens > 0 for s in result.steps)
        assert all(s.output_tokens > 0 for s in result.steps)
        assert all(s.cost_usd > 0 for s in result.steps)

    def test_result_aggregates_totals(self) -> None:
        registry = ToolRegistry()
        registry.register(FinishTool())
        responses = [
            "{\"thought\":\"d\",\"action\":{\"name\":\"finish\",\"args\":{\"answer\":\"ok\"}}}"
        ]
        queue = list(responses)

        def scripted(_p: str, _s: str, _t: int) -> str:
            return queue.pop(0)

        session = AgentSession(
            goal="x",
            tools=registry,
            llm=scripted,
            limits=SessionLimits(max_steps=2),
        )
        result = session.run()
        assert result.total_prompt_tokens == sum(s.prompt_tokens for s in result.steps)
        assert result.total_output_tokens == sum(s.output_tokens for s in result.steps)
        assert result.total_cost_usd == pytest.approx(
            round(sum(s.cost_usd for s in result.steps), 6)
        )

    def test_llm_failure_records_prompt_tokens_only(self) -> None:
        registry = ToolRegistry()
        registry.register(FinishTool())

        def boom(_p: str, _s: str, _t: int) -> str:
            raise RuntimeError("network")

        session = AgentSession(
            goal="x",
            tools=registry,
            llm=boom,
            limits=SessionLimits(max_steps=1, allow_tool_errors=True),
        )
        result = session.run()
        # The first step was constructed in the LLM-error branch; it
        # should still carry a non-zero prompt-token count and zero
        # output tokens.
        assert len(result.steps) >= 1
        first = result.steps[0]
        assert first.prompt_tokens > 0
        assert first.output_tokens == 0


# ---------------------------------------------------------------------------
# Trace store carries totals through.
# ---------------------------------------------------------------------------


class TestTraceTelemetry:
    def test_record_from_result_copies_totals(self, tmp_path) -> None:
        from src.agent.trace.store import TraceStore, record_from_result

        registry = ToolRegistry()
        registry.register(FinishTool())
        responses = [
            "{\"thought\":\"d\",\"action\":{\"name\":\"finish\",\"args\":{\"answer\":\"ok\"}}}"
        ]
        queue = list(responses)

        def scripted(_p: str, _s: str, _t: int) -> str:
            return queue.pop(0)

        session = AgentSession(
            goal="x", tools=registry, llm=scripted,
            limits=SessionLimits(max_steps=2),
        )
        result = session.run()

        record = record_from_result(result, tools_allowed=registry.names())
        assert record.total_prompt_tokens == result.total_prompt_tokens
        assert record.total_output_tokens == result.total_output_tokens
        assert record.total_cost_usd == result.total_cost_usd

        # Round-trip via on-disk save/load.
        store = TraceStore(base_dir=tmp_path / "traces")
        store.save(record)
        reloaded = store.load(record.id)
        assert reloaded.total_prompt_tokens == record.total_prompt_tokens
        assert reloaded.total_cost_usd == record.total_cost_usd


# ---------------------------------------------------------------------------
# Eval runner / report carry telemetry.
# ---------------------------------------------------------------------------


class TestEvalRunnerOutput:
    def test_runner_output_propagates(self) -> None:
        from src.agent.eval.runner import EvalCase

        case = EvalCase(
            id="x",
            description="",
            input={},
            expectations=[{"type": "equals", "value": "hello"}],
        )

        def runner(_inp):
            return RunnerOutput(
                output="hello", prompt_tokens=10, output_tokens=5, cost_usd=0.01
            )

        report = run_eval("synthetic", [case], runner)
        assert report.cases[0].passed
        assert report.cases[0].cost_usd == pytest.approx(0.01)
        assert report.total_prompt_tokens == 10
        assert report.total_output_tokens == 5
        assert report.total_cost_usd == pytest.approx(0.01)

    def test_form_filler_suite_reports_nonzero_cost(self) -> None:
        report = run_suite("form_filler")
        assert report.total_prompt_tokens > 0
        assert report.total_cost_usd > 0
        # Every case should have its own attribution.
        assert all(c.prompt_tokens > 0 for c in report.cases)
