"""Phase 16.2 tests -- ``score_breakdown`` tool + ``EdgeCaseAgent`` orchestrator.

The agent loop itself is exercised via a stub ``llm_fn`` so tests stay
deterministic and offline. The contract under test is:

* ``ScoreBreakdownTool`` returns the right shape for ``path=""``,
  scalar paths, ``rules``, ``rules.<rule_id>``, and unknown paths
  (helpful error, ``is_error=False`` so the agent can self-correct).
* ``EdgeCaseAgent.run`` correctly short-circuits on hard-rule
  disqualifications, on out-of-band scores, on missing ``llm_fn``,
  and on ``use_agent=False``; reaches the agent on borderline scores;
  parses well-formed JSON; falls back on malformed JSON; falls back
  with ``kind="agent_error"`` on raised exceptions; clamps confidence
  to [0, 1].
"""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools.score_breakdown import ScoreBreakdownTool
from src.matching.edge_case_agent import (
    BORDERLINE_HIGH,
    BORDERLINE_LOW,
    EdgeCaseAgent,
    is_borderline,
)
from src.matching.rules import RuleResult, RuleVerdict
from src.matching.scorer import ScoreBreakdown

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _make_breakdown(
    *,
    final_score: float = 0.5,
    disqualified: bool = False,
    rules: list[RuleResult] | None = None,
    job_snapshot_id: str | None = "snap-xyz",
) -> ScoreBreakdown:
    rules = rules or [
        RuleResult(rule_id="work_authorization", rule_name="work_authorization", passed=True),
        RuleResult(rule_id="experience", rule_name="experience", passed=True),
        RuleResult(rule_id="education", rule_name="education", passed=True),
        RuleResult(rule_id="employment_type", rule_name="employment_type", passed=True),
        RuleResult(rule_id="spam_filter", rule_name="spam_filter", passed=True),
    ]
    return ScoreBreakdown(
        job_id="job-1",
        company="Acme",
        title="SWE Intern",
        final_score=final_score,
        skill_overlap=0.55,
        keyword_similarity=0.4,
        rule_bonus=1.0 if not disqualified else 0.0,
        quality_multiplier=1.0,
        rule_verdict=RuleVerdict(job_id="job-1", passed=not disqualified, results=rules),
        disqualified=disqualified,
        disqualify_reasons=[r.reason for r in rules if not r.passed],
        disqualify_results=[r for r in rules if not r.passed],
        job_snapshot_id=job_snapshot_id,
    )


# --------------------------------------------------------------------------- #
# is_borderline                                                               #
# --------------------------------------------------------------------------- #


class TestIsBorderline:
    def test_lower_bound_inclusive(self):
        assert is_borderline(BORDERLINE_LOW)

    def test_upper_bound_inclusive(self):
        assert is_borderline(BORDERLINE_HIGH)

    def test_below_lower_excluded(self):
        assert not is_borderline(BORDERLINE_LOW - 0.01)

    def test_above_upper_excluded(self):
        assert not is_borderline(BORDERLINE_HIGH + 0.01)


# --------------------------------------------------------------------------- #
# ScoreBreakdownTool                                                          #
# --------------------------------------------------------------------------- #


class TestScoreBreakdownTool:
    def test_empty_path_returns_summary(self):
        tool = ScoreBreakdownTool(_make_breakdown())
        result = tool.run({})
        assert not result.is_error
        assert result.data["final_score"] == 0.5
        assert result.data["job_snapshot_id"] == "snap-xyz"
        assert "rule_ids" in result.data
        assert result.data["n_fail"] == 0

    def test_scalar_path(self):
        tool = ScoreBreakdownTool(_make_breakdown(final_score=0.42))
        result = tool.run({"path": "final_score"})
        assert result.data["value"] == 0.42

    def test_rules_path(self):
        tool = ScoreBreakdownTool(_make_breakdown())
        result = tool.run({"path": "rules"})
        assert "rules" in result.data
        assert len(result.data["rules"]) == 5

    def test_rule_by_id(self):
        rules = [
            RuleResult(
                rule_id="experience",
                rule_name="experience",
                passed=False,
                verdict="fail",
                reason="too few years",
                evidence_excerpt="5+ years required",
            ),
            RuleResult(rule_id="spam_filter", rule_name="spam_filter", passed=True),
        ]
        tool = ScoreBreakdownTool(_make_breakdown(rules=rules))
        result = tool.run({"path": "rules.experience"})
        assert result.data["rule_id"] == "experience"
        assert result.data["evidence_excerpt"] == "5+ years required"

    def test_unknown_rule_id_returns_helpful_observation(self):
        tool = ScoreBreakdownTool(_make_breakdown())
        result = tool.run({"path": "rules.no_such_rule"})
        # is_error=False so the agent re-tries with a valid id.
        assert not result.is_error
        assert "available_rule_ids" in result.data
        assert "work_authorization" in result.data["available_rule_ids"]

    def test_unknown_scalar_path_returns_valid_paths(self):
        tool = ScoreBreakdownTool(_make_breakdown())
        result = tool.run({"path": "garbage"})
        assert not result.is_error
        assert "valid_paths" in result.data

    def test_no_rule_verdict_returns_empty_rules(self):
        bd = _make_breakdown()
        bd.rule_verdict = None
        tool = ScoreBreakdownTool(bd)
        result = tool.run({"path": "rules"})
        assert result.data["rules"] == []


# --------------------------------------------------------------------------- #
# EdgeCaseAgent.run -- short-circuits                                         #
# --------------------------------------------------------------------------- #


class TestEdgeCaseAgentShortCircuit:
    def test_disqualified_short_circuits_before_agent(self):
        called: list[str] = []

        def llm(prompt: str, tools: dict[str, Any]) -> str:
            called.append(prompt)
            return '{"verdict": "surface", "confidence": 1.0, "rationale": ""}'

        bd = _make_breakdown(
            disqualified=True,
            rules=[
                RuleResult(
                    rule_id="work_authorization",
                    rule_name="work_authorization",
                    passed=False,
                    reason="no visa",
                )
            ],
        )
        decision = EdgeCaseAgent(bd, llm_fn=llm).run()
        assert decision.kind == "not_invoked"
        assert decision.verdict == "reject"
        assert called == []

    def test_score_below_band_short_circuits(self):
        bd = _make_breakdown(final_score=0.3)
        decision = EdgeCaseAgent(bd, llm_fn=lambda p, t: "{}").run()
        assert decision.kind == "not_invoked"
        assert decision.verdict == "reject"

    def test_score_above_band_short_circuits_as_surface(self):
        """Above the band -- treat as already-good; agent need not run."""
        bd = _make_breakdown(final_score=0.85)
        decision = EdgeCaseAgent(bd, llm_fn=lambda p, t: "{}").run()
        assert decision.kind == "not_invoked"
        assert decision.verdict == "surface"

    def test_missing_llm_fn_returns_not_invoked(self):
        bd = _make_breakdown(final_score=0.5)
        decision = EdgeCaseAgent(bd, llm_fn=None).run()
        assert decision.kind == "not_invoked"
        assert decision.verdict == "reject"

    def test_use_agent_false_returns_not_invoked(self):
        bd = _make_breakdown(final_score=0.5)
        decision = EdgeCaseAgent(bd, llm_fn=lambda p, t: "{}").run(use_agent=False)
        assert decision.kind == "not_invoked"


# --------------------------------------------------------------------------- #
# EdgeCaseAgent.run -- agent paths                                            #
# --------------------------------------------------------------------------- #


class TestEdgeCaseAgentInvocation:
    def test_well_formed_surface_verdict(self):
        def llm(prompt: str, tools: dict[str, Any]) -> str:
            # Agent calls the score_breakdown tool to inspect the data.
            tools["score_breakdown"]({"path": ""})
            return json.dumps(
                {
                    "verdict": "surface",
                    "confidence": 0.8,
                    "rationale": "skill overlap is high; short JD dragged keyword similarity",
                }
            )

        bd = _make_breakdown(final_score=0.45)
        decision = EdgeCaseAgent(bd, llm_fn=llm).run()
        assert decision.kind == "agent_ok"
        assert decision.verdict == "surface"
        assert decision.confidence == 0.8
        assert "skill overlap" in decision.rationale

    def test_well_formed_reject_verdict(self):
        def llm(prompt: str, tools: dict[str, Any]) -> str:
            return json.dumps(
                {"verdict": "reject", "confidence": 0.6, "rationale": "wrong role"}
            )

        decision = EdgeCaseAgent(_make_breakdown(final_score=0.5), llm_fn=llm).run()
        assert decision.verdict == "reject"
        assert decision.kind == "agent_ok"

    def test_well_formed_abstain_verdict(self):
        def llm(prompt: str, tools: dict[str, Any]) -> str:
            return json.dumps(
                {"verdict": "abstain", "confidence": 0.3, "rationale": "not enough JD signal"}
            )

        decision = EdgeCaseAgent(_make_breakdown(final_score=0.5), llm_fn=llm).run()
        assert decision.verdict == "abstain"
        assert decision.kind == "agent_ok"

    def test_trailing_json_after_thinking_text_is_parsed(self):
        def llm(prompt: str, tools: dict[str, Any]) -> str:
            return (
                "Let me think. The skill overlap is moderate but the JD is short, "
                "so I'd surface this.\n"
                '{"verdict": "surface", "confidence": 0.7, "rationale": "short JD"}'
            )

        decision = EdgeCaseAgent(_make_breakdown(final_score=0.5), llm_fn=llm).run()
        assert decision.kind == "agent_ok"
        assert decision.verdict == "surface"

    def test_confidence_clamped_to_unit_interval(self):
        def llm(prompt: str, tools: dict[str, Any]) -> str:
            return json.dumps(
                {"verdict": "surface", "confidence": 1.5, "rationale": "x"}
            )

        decision = EdgeCaseAgent(_make_breakdown(final_score=0.5), llm_fn=llm).run()
        assert decision.confidence == 1.0

    def test_confidence_clamped_to_zero_lower(self):
        def llm(prompt: str, tools: dict[str, Any]) -> str:
            return json.dumps(
                {"verdict": "reject", "confidence": -0.5, "rationale": "x"}
            )

        decision = EdgeCaseAgent(_make_breakdown(final_score=0.5), llm_fn=llm).run()
        assert decision.confidence == 0.0


class TestEdgeCaseAgentFallback:
    def test_malformed_output_falls_back(self):
        def llm(prompt: str, tools: dict[str, Any]) -> str:
            return "this is not JSON at all"

        decision = EdgeCaseAgent(_make_breakdown(final_score=0.5), llm_fn=llm).run()
        assert decision.kind == "agent_malformed"
        assert decision.verdict == "reject"
        assert decision.raw_agent_output is not None

    def test_invalid_verdict_value_falls_back(self):
        def llm(prompt: str, tools: dict[str, Any]) -> str:
            return json.dumps(
                {"verdict": "maybe", "confidence": 0.8, "rationale": "x"}
            )

        decision = EdgeCaseAgent(_make_breakdown(final_score=0.5), llm_fn=llm).run()
        assert decision.kind == "agent_malformed"

    def test_agent_raises_falls_back_with_error(self):
        def llm(prompt: str, tools: dict[str, Any]) -> str:
            raise RuntimeError("model API down")

        decision = EdgeCaseAgent(_make_breakdown(final_score=0.5), llm_fn=llm).run()
        assert decision.kind == "agent_error"
        assert decision.verdict == "reject"
        assert decision.agent_error and "model API down" in decision.agent_error

    def test_jd_lookup_tool_optional_agent_still_runs(self):
        """If the caller didn't bind a jd_lookup tool, the agent runs anyway
        with just score_breakdown -- borderline decisions often hinge on
        component scores, not the JD text."""
        captured_tools: list[set[str]] = []

        def llm(prompt: str, tools: dict[str, Any]) -> str:
            captured_tools.append(set(tools.keys()))
            return json.dumps(
                {"verdict": "reject", "confidence": 0.5, "rationale": "x"}
            )

        decision = EdgeCaseAgent(_make_breakdown(final_score=0.5), llm_fn=llm).run()
        assert decision.kind == "agent_ok"
        assert captured_tools == [{"score_breakdown"}]


class TestEdgeCaseDecisionDict:
    def test_to_dict_round_trip(self):
        def llm(prompt: str, tools: dict[str, Any]) -> str:
            return json.dumps({"verdict": "surface", "confidence": 0.9, "rationale": "ok"})

        decision = EdgeCaseAgent(_make_breakdown(final_score=0.55), llm_fn=llm).run()
        d = decision.to_dict()
        assert d["kind"] == "agent_ok"
        assert d["verdict"] == "surface"
        assert d["confidence"] == 0.9
        assert d["final_score"] == 0.55
        assert d["job_snapshot_id"] == "snap-xyz"
