"""Structured eval report types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.agent.eval.scorers import ExpectationResult


@dataclass
class EvalCaseResult:
    case_id: str
    passed: bool
    output: str
    expectations: list[ExpectationResult]
    elapsed_ms: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["expectations"] = [e.to_dict() for e in self.expectations]
        return d


@dataclass
class EvalReport:
    suite: str
    cases: list[EvalCaseResult] = field(default_factory=list)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.cases if c.passed)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def pass_rate(self) -> float:
        return (self.passed_count / self.total) if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "total": self.total,
            "passed": self.passed_count,
            "pass_rate": round(self.pass_rate, 4),
            "cases": [c.to_dict() for c in self.cases],
        }
