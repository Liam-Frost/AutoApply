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
    prompt_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

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

    @property
    def total_prompt_tokens(self) -> int:
        return sum(c.prompt_tokens for c in self.cases)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.cases)

    @property
    def total_cost_usd(self) -> float:
        return round(sum(c.cost_usd for c in self.cases), 6)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "total": self.total,
            "passed": self.passed_count,
            "pass_rate": round(self.pass_rate, 4),
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": self.total_cost_usd,
            "cases": [c.to_dict() for c in self.cases],
        }
