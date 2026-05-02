"""Built-in scorers for eval expectations.

Each scorer is a callable ``(output_text, params) -> ExpectationResult``.
Suites pick scorers by name in fixture JSON; new scorers can be
registered at runtime by mutating the SCORERS dict.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Scorer = Callable[[str, dict[str, Any]], "ExpectationResult"]


@dataclass
class ExpectationResult:
    type: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "passed": self.passed, "detail": self.detail}


def _contains_all(output: str, params: dict[str, Any]) -> ExpectationResult:
    needles = params.get("values") or []
    if not isinstance(needles, list) or not needles:
        return ExpectationResult("contains_all", False, "no values provided")
    missing = [n for n in needles if str(n) not in output]
    if missing:
        return ExpectationResult("contains_all", False, f"missing: {missing}")
    return ExpectationResult("contains_all", True)


def _contains_any(output: str, params: dict[str, Any]) -> ExpectationResult:
    needles = params.get("values") or []
    if not isinstance(needles, list) or not needles:
        return ExpectationResult("contains_any", False, "no values provided")
    if any(str(n) in output for n in needles):
        return ExpectationResult("contains_any", True)
    return ExpectationResult("contains_any", False, f"none of {needles} present")


def _equals(output: str, params: dict[str, Any]) -> ExpectationResult:
    expected = params.get("value", "")
    actual = output.strip() if params.get("strip", True) else output
    expected_norm = str(expected).strip() if params.get("strip", True) else str(expected)
    if actual == expected_norm:
        return ExpectationResult("equals", True)
    return ExpectationResult(
        "equals",
        False,
        f"expected {expected_norm!r}, got {actual[:120]!r}",
    )


def _regex(output: str, params: dict[str, Any]) -> ExpectationResult:
    pattern = params.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return ExpectationResult("regex", False, "no pattern provided")
    flags = re.MULTILINE | re.DOTALL if params.get("multiline") else 0
    if re.search(pattern, output, flags=flags):
        return ExpectationResult("regex", True)
    return ExpectationResult("regex", False, f"no match for {pattern!r}")


def _length_between(output: str, params: dict[str, Any]) -> ExpectationResult:
    unit = params.get("unit", "chars")
    if unit not in {"chars", "words"}:
        return ExpectationResult("length_between", False, f"unknown unit {unit!r}")
    n = len(output) if unit == "chars" else len(output.split())
    lo = params.get("min", 0)
    hi = params.get("max", 10**9)
    if lo <= n <= hi:
        return ExpectationResult("length_between", True, f"{unit}={n}")
    return ExpectationResult(
        "length_between", False, f"{unit}={n} outside [{lo}, {hi}]"
    )


SCORERS: dict[str, Scorer] = {
    "contains_all": _contains_all,
    "contains_any": _contains_any,
    "equals": _equals,
    "regex": _regex,
    "length_between": _length_between,
}


def score_expectations(
    output: str, expectations: list[dict[str, Any]]
) -> list[ExpectationResult]:
    """Score every expectation against the same output string."""
    results: list[ExpectationResult] = []
    for spec in expectations:
        kind = spec.get("type")
        scorer = SCORERS.get(kind) if isinstance(kind, str) else None
        if scorer is None:
            results.append(
                ExpectationResult(
                    str(kind or "unknown"), False, f"unknown scorer {kind!r}"
                )
            )
            continue
        results.append(scorer(output, spec))
    return results
