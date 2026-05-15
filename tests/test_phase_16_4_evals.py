"""Phase 16.4: filter_borderline eval suite registration + smoke run.

Ships 10 JSON fixtures under
``tests/agent_evals/fixtures/filter_borderline/`` covering:

* Score-band positives (high skill but low-keyword JD that should
  surface; quality-multiplier drag that should surface).
* Score-band negatives (borderline-but-wrong-role rejects).
* Short-circuits (hard-rule disqualification; score below band;
  score above band).
* Fallback ladder (malformed output, llm_fn raises, invalid verdict
  literal).
* Abstain (low-confidence agent verdict recorded for auditing).

The plan asks for ``agent decision matches human label >= 70%`` once a
real LLM is wired in. Here, the runner uses fixture-injected
``llm_output`` strings so the eval is deterministic and offline -- we
assert that every fixture passes its declared expectations. The 70%
human-agreement bar is a Phase 17 concern (real LLM, real cost
budget); this suite is the harness it will measure against.
"""

from __future__ import annotations

from src.agent.eval.runner import list_suites, run_suite


def test_filter_borderline_suite_is_registered() -> None:
    assert "filter_borderline" in set(list_suites())


def test_filter_borderline_suite_has_ten_fixtures() -> None:
    """The plan calls for 10 annotated borderline jobs."""
    report = run_suite("filter_borderline")
    assert len(report.cases) == 10, (
        f"filter_borderline must have 10 fixtures, got {len(report.cases)}"
    )


def test_filter_borderline_suite_passes() -> None:
    report = run_suite("filter_borderline")
    failures = [c for c in report.cases if not c.passed]
    assert not failures, (
        "filter_borderline failures: "
        + ", ".join(
            f"{c.case_id}: {c.error or c.expectations}" for c in failures
        )
    )


def test_filter_borderline_covers_all_decision_kinds() -> None:
    """Make sure the 10 fixtures cover every EdgeCaseDecisionKind so
    the suite stays well-rounded. Otherwise a regression that breaks
    one branch (e.g. malformed parsing) might still ship green."""
    report = run_suite("filter_borderline")
    seen_kinds: set[str] = set()
    seen_verdicts: set[str] = set()
    for case in report.cases:
        # Expectations are typed; we walked through the runner already
        # and want the *kind*/*verdict* the fixture asserted on.
        for exp in case.expectations:
            if exp.detail and "==" in exp.detail:
                # "kind=agent_ok == 'agent_ok'" shape
                lhs = exp.detail.split("==")[0].strip()
                if lhs.startswith("kind="):
                    seen_kinds.add(lhs.removeprefix("kind=").strip("'\""))
                elif lhs.startswith("verdict="):
                    seen_verdicts.add(lhs.removeprefix("verdict=").strip("'\""))
    assert seen_kinds >= {
        "agent_ok",
        "agent_malformed",
        "agent_error",
        "not_invoked",
    }, f"kinds covered: {seen_kinds}"
    assert seen_verdicts >= {"surface", "reject", "abstain"}, (
        f"verdicts covered: {seen_verdicts}"
    )
