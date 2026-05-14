"""Phase 12.7 -- Cost dashboard split tests.

Covers ``AgentStep.cached``, ``AgentResult.cached_step_count`` /
``fresh_step_count`` / ``total_cost_usd_fresh`` /
``total_cost_saved_usd``, and the trace store round-tripping the
new fields.
"""

from __future__ import annotations

from src.agent.core.loop import AgentResult, AgentStep
from src.agent.trace.store import _record_from_dict, record_from_result


def _step(
    *,
    index: int = 1,
    cost_usd: float = 0.001,
    llm_attempts: list[dict] | None = None,
) -> AgentStep:
    return AgentStep(
        index=index,
        prompt="prompt",
        raw_response='{"action":"final","args":{},"thought":""}',
        thought="",
        action_name="final",
        action_args={},
        observation="",
        is_error=False,
        latency_ms=10,
        prompt_tokens=100,
        output_tokens=50,
        cost_usd=cost_usd,
        llm_attempts=llm_attempts or [],
    )


class TestAgentStepCached:
    def test_no_attempts_is_not_cached(self) -> None:
        step = _step()
        assert step.cached is False

    def test_cached_true_when_first_attempt_has_cached_flag(self) -> None:
        step = _step(
            llm_attempts=[
                {
                    "provider": "openai",
                    "ok": True,
                    "kind": "cache_hit",
                    "cached": True,
                    "latency_ms": 0,
                }
            ]
        )
        assert step.cached is True

    def test_cached_true_when_kind_is_cache_hit(self) -> None:
        """Some stubs only set ``kind`` rather than the explicit
        ``cached`` flag; both must register."""
        step = _step(
            llm_attempts=[
                {"provider": "openai", "ok": True, "kind": "cache_hit"}
            ]
        )
        assert step.cached is True

    def test_normal_attempt_is_not_cached(self) -> None:
        step = _step(
            llm_attempts=[
                {
                    "provider": "openai",
                    "ok": True,
                    "kind": None,
                    "cached": False,
                }
            ]
        )
        assert step.cached is False

    def test_to_dict_surfaces_cached(self) -> None:
        """Trace viewers read from ``to_dict``; ``cached`` must be in
        the serialised shape, not just on the live object."""
        step = _step(
            llm_attempts=[
                {"provider": "openai", "ok": True, "kind": "cache_hit"}
            ]
        )
        assert step.to_dict()["cached"] is True


class TestAgentResultSplit:
    def _result(self, *steps: AgentStep) -> AgentResult:
        return AgentResult(
            goal="g",
            answer="a",
            finished=True,
            steps=list(steps),
            stop_reason="",
            elapsed_ms=100,
        )

    def test_counts_split_correctly(self) -> None:
        cached = _step(
            index=1,
            cost_usd=0.005,
            llm_attempts=[{"kind": "cache_hit", "cached": True}],
        )
        fresh = _step(index=2, cost_usd=0.010)
        another_fresh = _step(index=3, cost_usd=0.020)
        result = self._result(cached, fresh, another_fresh)
        assert result.cached_step_count == 1
        assert result.fresh_step_count == 2

    def test_cost_split_credits_cached_to_saved(self) -> None:
        cached = _step(
            index=1,
            cost_usd=0.005,
            llm_attempts=[{"kind": "cache_hit"}],
        )
        fresh = _step(index=2, cost_usd=0.010)
        result = self._result(cached, fresh)
        # Total cost = fresh + cached "what-it-would-have-cost"
        assert result.total_cost_usd == 0.015
        # Fresh path only counts the actual fresh cost.
        assert result.total_cost_usd_fresh == 0.010
        # Saved = cached step's would-have-cost.
        assert result.total_cost_saved_usd == 0.005

    def test_no_cached_steps_saves_zero(self) -> None:
        result = self._result(_step(cost_usd=0.001), _step(cost_usd=0.002))
        assert result.cached_step_count == 0
        assert result.total_cost_saved_usd == 0.0
        assert result.total_cost_usd_fresh == result.total_cost_usd

    def test_to_dict_includes_split_fields(self) -> None:
        result = self._result(
            _step(index=1, cost_usd=0.001, llm_attempts=[{"kind": "cache_hit"}]),
            _step(index=2, cost_usd=0.002),
        )
        out = result.to_dict()
        for field in (
            "cached_step_count",
            "fresh_step_count",
            "total_cost_usd_fresh",
            "total_cost_saved_usd",
        ):
            assert field in out


class TestTraceStoreRoundTrip:
    def test_record_from_result_copies_split_fields(self) -> None:
        result = AgentResult(
            goal="g",
            answer="a",
            finished=True,
            steps=[
                _step(cost_usd=0.001, llm_attempts=[{"kind": "cache_hit"}]),
                _step(index=2, cost_usd=0.003),
            ],
            stop_reason="",
            elapsed_ms=100,
        )
        record = record_from_result(result, tools_allowed=["final"])
        assert record.cached_step_count == 1
        assert record.fresh_step_count == 1
        assert record.total_cost_usd_fresh == 0.003
        assert record.total_cost_saved_usd == 0.001

    def test_summary_surfaces_split(self) -> None:
        result = AgentResult(
            goal="g",
            answer="a",
            finished=True,
            steps=[
                _step(cost_usd=0.002, llm_attempts=[{"kind": "cache_hit"}]),
                _step(index=2, cost_usd=0.004),
            ],
            stop_reason="",
            elapsed_ms=100,
        )
        record = record_from_result(result, tools_allowed=[])
        summary = record.summary()
        assert summary["cached_step_count"] == 1
        assert summary["fresh_step_count"] == 1
        assert summary["total_cost_usd_fresh"] == 0.004
        assert summary["total_cost_saved_usd"] == 0.002

    def test_legacy_record_defaults_to_all_fresh(self) -> None:
        """Codex review P2 regression: traces written before
        Phase 12.7 had no cache wiring -- every step was a fresh
        provider call. Loading must fold ``step_count`` /
        ``total_cost_usd`` into the fresh totals so the partition
        invariant (cached + fresh = step_count) holds for old data
        and the dashboard's "saved vs spent" math stays meaningful."""
        legacy = {
            "id": "20260101T000000Z-deadbeef",
            "started_at": "2026-01-01T00:00:00Z",
            "finished": True,
            "stop_reason": "",
            "goal": "g",
            "answer": "a",
            "elapsed_ms": 50,
            "step_count": 3,
            "tools_allowed": [],
            "metadata": {},
            "steps": [],
            "total_prompt_tokens": 100,
            "total_output_tokens": 50,
            "total_cost_usd": 0.012,
            # split fields deliberately omitted
        }
        record = _record_from_dict(legacy)
        assert record.cached_step_count == 0
        # Legacy steps are all fresh -- partition holds.
        assert record.fresh_step_count == 3
        assert record.fresh_step_count + record.cached_step_count == record.step_count
        # Fresh cost = total cost, saved cost = 0.
        assert record.total_cost_usd_fresh == 0.012
        assert record.total_cost_saved_usd == 0.0
