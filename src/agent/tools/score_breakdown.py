"""Phase 16.2: ``score_breakdown`` agent tool.

Read-only access to a single :class:`ScoreBreakdown` for the edge-case
filter agent. Bound to one breakdown at construction time so the agent
loop cannot ask for "the breakdown of some other job" -- audit binding
matches the ``jd_lookup`` shape from 15.6.

The tool exposes a dotted-path interface so the agent can drill into
individual components without flooding its context with the full JSON
on every call:

* ``path=""`` (or omitted) returns a top-level summary -- final_score,
  rule_bonus, skill_overlap, keyword_similarity, quality_multiplier,
  disqualified flag, count of failing rules, and the list of rule_ids.
* ``path="final_score"`` / ``"skill_overlap"`` / ... returns a scalar.
* ``path="rules"`` returns the structured per-rule breakdown:
  ``[{rule_id, verdict, reason, evidence_excerpt}, ...]``.
* ``path="rules.<rule_id>"`` returns one rule's structured entry.

The tool is **read-only**. It does not let the agent rewrite the score
or change the verdict -- it only narrates. The agent's actual decision
("surface for review" vs. "stay rejected") is emitted as a structured
``finish`` payload, not by mutating the breakdown.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.agent.tools.base import Tool, ToolResult
from src.matching.scorer import ScoreBreakdown

logger = logging.getLogger(__name__)

_MAX_RETURN_CHARS = 4_000


def _truncate_json(payload: Any) -> str:
    s = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if len(s) <= _MAX_RETURN_CHARS:
        return s
    return s[: _MAX_RETURN_CHARS - 1] + "…"


class ScoreBreakdownTool(Tool):
    """Bound to one :class:`ScoreBreakdown`. Construct per-agent-run."""

    name = "score_breakdown"
    description = (
        "Read the deterministic match-score breakdown for the bound job. "
        "Use this BEFORE jd_lookup -- if the rule_bonus is 1.0 and "
        "skill_overlap is high, the borderline score is driven by text "
        "similarity, not a rule failure, and you do not need to inspect "
        "the JD in detail. Paths: '' (summary), 'final_score', "
        "'skill_overlap', 'keyword_similarity', 'rule_bonus', "
        "'quality_multiplier', 'disqualified', 'rules' (all per-rule "
        "structured entries), 'rules.<rule_id>' (one rule)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Dotted path into the breakdown. Empty returns the summary."
                ),
            }
        },
        "required": [],
    }

    def __init__(self, breakdown: ScoreBreakdown) -> None:
        self._breakdown = breakdown

    # ------------------------------------------------------------------ #
    # path resolution                                                    #
    # ------------------------------------------------------------------ #

    def _summary(self) -> dict[str, Any]:
        b = self._breakdown
        rules = b.rule_verdict.results if b.rule_verdict else []
        return {
            "job_id": b.job_id,
            "job_snapshot_id": b.job_snapshot_id,
            "company": b.company,
            "title": b.title,
            "final_score": b.final_score,
            "skill_overlap": b.skill_overlap,
            "keyword_similarity": b.keyword_similarity,
            "rule_bonus": b.rule_bonus,
            "quality_multiplier": b.quality_multiplier,
            "disqualified": b.disqualified,
            "rule_ids": [r.rule_id for r in rules],
            "fail_rule_ids": [r.rule_id for r in rules if not r.passed],
            "n_fail": sum(1 for r in rules if not r.passed),
        }

    def _scalar(self, path: str) -> Any:
        b = self._breakdown
        mapping: dict[str, Any] = {
            "final_score": b.final_score,
            "skill_overlap": b.skill_overlap,
            "keyword_similarity": b.keyword_similarity,
            "rule_bonus": b.rule_bonus,
            "quality_multiplier": b.quality_multiplier,
            "disqualified": b.disqualified,
            "company": b.company,
            "title": b.title,
            "job_id": b.job_id,
            "job_snapshot_id": b.job_snapshot_id,
        }
        if path in mapping:
            return mapping[path]
        raise KeyError(path)

    def _rules_list(self) -> list[dict[str, Any]]:
        b = self._breakdown
        if not b.rule_verdict:
            return []
        return [r.to_dict() for r in b.rule_verdict.results]

    def _rule_by_id(self, rule_id: str) -> dict[str, Any] | None:
        for r in self._rules_list():
            if r["rule_id"] == rule_id:
                return r
        return None

    # ------------------------------------------------------------------ #
    # Tool.run                                                           #
    # ------------------------------------------------------------------ #

    def run(self, args: dict[str, Any]) -> ToolResult:
        path = (args.get("path") or "").strip()

        if not path:
            payload = self._summary()
            return ToolResult(output=_truncate_json(payload), data=payload)

        if path == "rules":
            rules = self._rules_list()
            return ToolResult(output=_truncate_json(rules), data={"rules": rules})

        if path.startswith("rules."):
            rule_id = path[len("rules.") :]
            entry = self._rule_by_id(rule_id)
            if entry is None:
                available = [r["rule_id"] for r in self._rules_list()]
                # is_error=False so the agent self-corrects; we still
                # surface ``available`` so it can pick a valid id.
                return ToolResult(
                    output=(
                        f"No rule with rule_id={rule_id!r}. "
                        f"Available: {available}"
                    ),
                    data={"available_rule_ids": available},
                    is_error=False,
                )
            return ToolResult(output=_truncate_json(entry), data=entry)

        # Scalar fallback
        try:
            value = self._scalar(path)
        except KeyError:
            valid = sorted(
                {
                    "final_score",
                    "skill_overlap",
                    "keyword_similarity",
                    "rule_bonus",
                    "quality_multiplier",
                    "disqualified",
                    "company",
                    "title",
                    "job_id",
                    "job_snapshot_id",
                    "rules",
                }
            )
            return ToolResult(
                output=f"Unknown path {path!r}. Valid: {valid}",
                data={"valid_paths": valid},
                is_error=False,
            )
        return ToolResult(output=json.dumps(value, default=str), data={"value": value})
