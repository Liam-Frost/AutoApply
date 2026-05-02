"""Fixture-driven evaluation harness for agent regressions.

The evaluator is intentionally generic: a suite is a directory of
fixture JSON files plus a callable that turns a fixture's ``input`` into
an output string. The harness scores the output against fixture-level
expectations and emits a report comparable across runs.

Built-in suites live in ``tests/agent_evals/fixtures/<name>/``.
"""

from src.agent.eval.report import EvalCaseResult, EvalReport, ExpectationResult
from src.agent.eval.runner import EvalCase, run_eval, run_suite
from src.agent.eval.scorers import (
    SCORERS,
    Scorer,
    score_expectations,
)

__all__ = [
    "SCORERS",
    "EvalCase",
    "EvalCaseResult",
    "EvalReport",
    "ExpectationResult",
    "Scorer",
    "run_eval",
    "run_suite",
    "score_expectations",
]
