"""Eval runner: load fixtures, execute the runner callable, score outputs."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.agent.eval.report import EvalCaseResult, EvalReport
from src.agent.eval.scorers import score_expectations
from src.core.config import PROJECT_ROOT

RunnerFn = Callable[[dict[str, Any]], str]
"""(case_input) -> output text. Output is what scorers operate on."""


@dataclass
class EvalCase:
    id: str
    description: str
    input: dict[str, Any]
    expectations: list[dict[str, Any]]

    @classmethod
    def from_path(cls, path: Path) -> EvalCase:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            id=str(data.get("id") or path.stem),
            description=str(data.get("description", "")),
            input=dict(data.get("input", {})),
            expectations=list(data.get("expectations", [])),
        )


def load_cases(suite_dir: Path) -> list[EvalCase]:
    suite_dir = Path(suite_dir)
    if not suite_dir.exists():
        raise FileNotFoundError(f"Suite directory not found: {suite_dir}")
    files = sorted(suite_dir.glob("*.json"))
    return [EvalCase.from_path(p) for p in files]


def run_eval(
    suite_name: str,
    cases: list[EvalCase],
    runner: RunnerFn,
) -> EvalReport:
    """Run every case through the runner and score the outputs."""
    report = EvalReport(suite=suite_name)
    for case in cases:
        t0 = time.monotonic()
        error: str | None = None
        output = ""
        try:
            output = runner(case.input)
            if not isinstance(output, str):
                output = json.dumps(output, ensure_ascii=False, default=str)
        except Exception as exc:  # noqa: BLE001 -- harness boundary
            error = f"{type(exc).__name__}: {exc}"
        elapsed = int((time.monotonic() - t0) * 1000)

        if error:
            report.cases.append(
                EvalCaseResult(
                    case_id=case.id,
                    passed=False,
                    output="",
                    expectations=[],
                    elapsed_ms=elapsed,
                    error=error,
                )
            )
            continue

        results = score_expectations(output, case.expectations)
        report.cases.append(
            EvalCaseResult(
                case_id=case.id,
                passed=all(r.passed for r in results) and bool(results),
                output=output,
                expectations=results,
                elapsed_ms=elapsed,
            )
        )
    return report


# ---------- built-in suites ----------


def _agent_smoke_runner(case_input: dict[str, Any]) -> str:
    """Drive the agent loop with a scripted LLM defined in the fixture.

    Each fixture supplies ``goal``, ``tools`` (allowlist), and a list of
    ``llm_responses`` to play back. This lets the suite exercise the
    full loop with zero non-determinism, suitable for CI.
    """
    from src.agent.core.loop import AgentSession, SessionLimits
    from src.agent.tools.base import get_default_registry

    goal = str(case_input.get("goal", ""))
    allowed = list(case_input.get("tools", ["finish"]))
    responses = list(case_input.get("llm_responses", []))
    limits = SessionLimits(
        max_steps=int(case_input.get("max_steps", 6)),
        step_timeout=int(case_input.get("step_timeout", 30)),
    )

    queue = list(responses)

    def scripted(_p: str, _s: str, _t: int) -> str:
        if not queue:
            raise RuntimeError("Scripted LLM ran out of responses.")
        return queue.pop(0)

    tools = get_default_registry().view(allowed)
    session = AgentSession(goal=goal, tools=tools, llm=scripted, limits=limits)
    result = session.run()
    if result.finished and result.answer is not None:
        return result.answer
    return f"[unfinished:{result.stop_reason}]"


_BUILTIN_SUITES: dict[str, tuple[Path, RunnerFn]] = {
    "agent_smoke": (
        PROJECT_ROOT / "tests" / "agent_evals" / "fixtures" / "agent_smoke",
        _agent_smoke_runner,
    ),
}


def list_suites() -> list[str]:
    return sorted(_BUILTIN_SUITES)


def run_suite(name: str) -> EvalReport:
    if name not in _BUILTIN_SUITES:
        raise KeyError(f"Unknown suite '{name}'. Available: {list_suites()}.")
    fixtures_dir, runner = _BUILTIN_SUITES[name]
    cases = load_cases(fixtures_dir)
    return run_eval(name, cases, runner)
