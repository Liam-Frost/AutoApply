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


def _field_mapping_match(output: str, params: dict[str, Any]) -> ExpectationResult:
    """Match agent fill proposals against an expected ``label -> value`` map.

    The runner emits JSON of the form ``{"proposals": [...]}`` where
    each proposal has at least ``field_label`` and ``value``. The
    scorer iterates the expected map and counts hits; a fixture-level
    ``min_match_rate`` (default 1.0) controls passing.

    Comparison is case-insensitive substring match by default --
    LLMs surface 'University of British Columbia' for an option that
    the fixture stored as 'university of british columbia'. Set
    ``exact: true`` for byte-equal comparison.
    """
    expected = params.get("expected") or {}
    if not isinstance(expected, dict) or not expected:
        return ExpectationResult(
            "field_mapping_match", False, "no 'expected' map provided"
        )
    min_rate = float(params.get("min_match_rate", 1.0))
    exact = bool(params.get("exact", False))

    try:
        payload = _json_loads_lenient(output)
    except ValueError as exc:
        return ExpectationResult(
            "field_mapping_match", False, f"output is not JSON: {exc}"
        )
    proposals = payload.get("proposals") if isinstance(payload, dict) else None
    if not isinstance(proposals, list):
        return ExpectationResult(
            "field_mapping_match", False, "no 'proposals' array in output"
        )
    by_label: dict[str, str] = {}
    for p in proposals:
        if not isinstance(p, dict):
            continue
        label = str(p.get("field_label", "")).strip()
        if label and label not in by_label:
            by_label[label] = str(p.get("value", ""))

    misses: list[str] = []
    hits = 0
    total = len(expected)
    for label, want in expected.items():
        got = by_label.get(label, "")
        if _value_matches(want, got, exact=exact):
            hits += 1
        else:
            misses.append(f"{label}: want={want!r} got={got!r}")
    rate = hits / total if total else 0.0
    if rate >= min_rate:
        return ExpectationResult(
            "field_mapping_match", True, f"{hits}/{total} matched (rate={rate:.2f})"
        )
    return ExpectationResult(
        "field_mapping_match",
        False,
        f"{hits}/{total} matched (rate={rate:.2f}); misses={misses[:5]}",
    )


def _no_proposal_for_label(
    output: str, params: dict[str, Any]
) -> ExpectationResult:
    """Assert the runner did NOT propose a value for a given label.

    Used for negative cases (e.g. 'must not auto-fill the cover letter
    upload field, that's the file uploader's job').
    """
    label = params.get("label")
    if not isinstance(label, str) or not label:
        return ExpectationResult(
            "no_proposal_for_label", False, "no 'label' provided"
        )
    try:
        payload = _json_loads_lenient(output)
    except ValueError as exc:
        return ExpectationResult(
            "no_proposal_for_label", False, f"output not JSON: {exc}"
        )
    proposals = payload.get("proposals") if isinstance(payload, dict) else None
    if not isinstance(proposals, list):
        return ExpectationResult("no_proposal_for_label", True, "no proposals at all")
    for p in proposals:
        if not isinstance(p, dict):
            continue
        if str(p.get("field_label", "")).strip() == label.strip():
            return ExpectationResult(
                "no_proposal_for_label",
                False,
                f"proposal present for {label!r} (value={p.get('value')!r})",
            )
    return ExpectationResult("no_proposal_for_label", True)


def _value_matches(want: Any, got: str, *, exact: bool) -> bool:
    want_s = str(want)
    if exact:
        return want_s == got
    want_norm = want_s.strip().lower()
    got_norm = (got or "").strip().lower()
    if not want_norm or not got_norm:
        return want_norm == got_norm
    return want_norm in got_norm or got_norm in want_norm


def _json_loads_lenient(text: str) -> Any:
    """Tolerate JSON objects wrapped in surrounding noise.

    Eval runners ought to emit clean JSON, but if upstream code adds a
    trailing newline / log line we still want the scorer to find the
    payload.
    """
    import json as _json  # noqa: PLC0415

    text = (text or "").strip()
    if not text:
        raise ValueError("empty output")
    try:
        return _json.loads(text)
    except _json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object detected")
    candidate = text[start : end + 1]
    return _json.loads(candidate)


SCORERS: dict[str, Scorer] = {
    "contains_all": _contains_all,
    "contains_any": _contains_any,
    "equals": _equals,
    "regex": _regex,
    "length_between": _length_between,
    "field_mapping_match": _field_mapping_match,
    "no_proposal_for_label": _no_proposal_for_label,
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
