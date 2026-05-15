"""Phase 16.2: edge-case filter agent.

When the deterministic scorer puts a job in the borderline band
``[0.4, 0.6]``, escalate to an LLM-driven agent that decides whether
to **surface the job for human review** or **keep it rejected**. The
agent is NOT a replacement for the deterministic scorer -- it only
fires on the borderline slice (the plan estimates ~10% of jobs), and
its decision is advisory: it sets a flag the Phase 17 review-queue
filter reads, it does not rewrite ``ScoreBreakdown.final_score``.

Why this exists
---------------
A 0.45 score from the deterministic scorer is genuinely ambiguous:

* Could be "Python intern role, JD is short" (low keyword_similarity
  dragging an otherwise good match down -- should surface).
* Could be "borderline match but JD mentions 5 yrs preferred under the
  grace window" (skill-fit looks OK but the role is wrong -- should
  stay rejected).

Hard rules can't tell these apart. A short LLM call against the
structured breakdown + a few JD lookups can.

Boundaries
----------
* **Invocation window**: ``BORDERLINE_LOW <= final_score <=
  BORDERLINE_HIGH`` (0.4 / 0.6 by default). Outside this window the
  agent never fires.
* **Inputs**: bound :class:`ScoreBreakdown` (via the new 16.2
  ``score_breakdown`` tool) + bound :class:`JobSnapshot` (via Phase
  15.6 ``jd_lookup``). The agent never sees the applicant profile in
  this phase -- it is filtering, not generating.
* **Outputs**: :class:`EdgeCaseDecision` with one of three verdicts:
  ``"surface"`` (override the rejection; flag for human review),
  ``"reject"`` (concur with the rejection), or ``"abstain"`` (low
  confidence -- treat as ``"reject"`` upstream but record the
  uncertainty for the eval set).
* **Fallback ladder** (mirrors :class:`AgentCoverLetter` from 15.7):
  no ``llm_fn`` -> ``not_invoked``; agent raised -> ``agent_error``;
  agent returned malformed JSON -> ``agent_malformed``; agent returned
  a verdict not in the literal set -> ``agent_malformed``.

D023 / Phase 14: ``run()`` is synchronous. The materials/filter task
body wraps it in ``AutoApplyTask.call_agent`` so the queue layer owns
retry / HITL / trace.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from src.agent.tools.score_breakdown import ScoreBreakdownTool
from src.matching.scorer import ScoreBreakdown

logger = logging.getLogger(__name__)


BORDERLINE_LOW = 0.4
BORDERLINE_HIGH = 0.6

EdgeCaseVerdict = Literal["surface", "reject", "abstain"]
EdgeCaseDecisionKind = Literal[
    "not_invoked",  # score outside [0.4, 0.6], or use_agent=False, or no llm_fn
    "agent_ok",  # agent returned a well-formed verdict
    "agent_error",  # agent raised
    "agent_malformed",  # agent returned JSON we couldn't parse / verdict not in set
]


@dataclass
class EdgeCaseDecision:
    """Returned from :meth:`EdgeCaseAgent.run`.

    Always present, even on the ``not_invoked`` path -- that lets the
    review-queue filter treat the result uniformly without special-casing
    "is this a borderline job?".
    """

    kind: EdgeCaseDecisionKind
    verdict: EdgeCaseVerdict
    confidence: float = 0.0  # in [0, 1]; only meaningful when kind=="agent_ok"
    rationale: str = ""
    raw_agent_output: str | None = None
    job_id: str = ""
    job_snapshot_id: str | None = None
    final_score: float = 0.0
    agent_error: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "raw_agent_output": self.raw_agent_output,
            "job_id": self.job_id,
            "job_snapshot_id": self.job_snapshot_id,
            "final_score": self.final_score,
            "agent_error": self.agent_error,
            "notes": list(self.notes),
        }


# Type of the agent callable: receives a prompt + a callable tool registry
# (tool_name -> handler) and returns a string. Tests inject a stub; the
# real loop wraps src.agent.core.loop.
LlmFn = Callable[[str, dict[str, Callable[[dict[str, Any]], Any]]], str]


def is_borderline(score: float) -> bool:
    """Plan's invocation window: ``[0.4, 0.6]`` inclusive on both ends."""
    return BORDERLINE_LOW <= score <= BORDERLINE_HIGH


def _build_prompt(breakdown: ScoreBreakdown) -> str:
    """Compose a short prompt for the edge-case agent.

    Deliberately compact: the score_breakdown + jd_lookup tools carry
    the real evidence. We only need the agent to know what its task is
    and what shape the answer takes.
    """
    return (
        "You are reviewing a borderline job match. The deterministic scorer\n"
        f"gave job_id={breakdown.job_id!r} a final_score of {breakdown.final_score}\n"
        "(borderline band is [0.4, 0.6]). Decide whether to SURFACE the job\n"
        "for human review or to keep the REJECT.\n\n"
        "Tools available:\n"
        "  - score_breakdown(path='') -- inspect the deterministic breakdown.\n"
        "  - jd_lookup(path='') -- inspect the JD snapshot the score was on.\n\n"
        "Reply with a single JSON object on the final line:\n"
        '  {"verdict": "surface" | "reject" | "abstain",\n'
        '   "confidence": <float in [0,1]>,\n'
        '   "rationale": "<one sentence>"}\n\n'
        "Choose 'surface' only when there is concrete evidence the rejection\n"
        "is a false negative (e.g. short JD dragging keyword_similarity down\n"
        "even though skill_overlap is high). Choose 'reject' when the score\n"
        "is borderline but the JD genuinely does not fit. Choose 'abstain'\n"
        "only when neither tool returns enough signal to decide -- this is\n"
        "recorded for eval auditing, not used as a third action."
    )


_VALID_VERDICTS = {"surface", "reject", "abstain"}


def _parse_agent_output(raw: str) -> tuple[EdgeCaseVerdict, float, str] | None:
    """Find and parse the trailing JSON object in the agent's output.

    Accepts either: the entire string is JSON, or the JSON is the last
    ``{...}`` block on the last non-empty line. Returns ``None`` when
    the verdict is not in :data:`_VALID_VERDICTS` or the JSON is
    unparseable.
    """
    candidate = raw.strip()
    if not candidate:
        return None

    # Try whole-string first.
    parsed: Any = None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # Find last balanced {...} block.
        last_open = candidate.rfind("{")
        last_close = candidate.rfind("}")
        if last_open == -1 or last_close <= last_open:
            return None
        try:
            parsed = json.loads(candidate[last_open : last_close + 1])
        except json.JSONDecodeError:
            return None

    if not isinstance(parsed, dict):
        return None
    verdict = parsed.get("verdict")
    if verdict not in _VALID_VERDICTS:
        return None
    confidence_raw = parsed.get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    rationale = str(parsed.get("rationale", "")).strip()
    return verdict, confidence, rationale  # type: ignore[return-value]


class EdgeCaseAgent:
    """Decides borderline-band jobs.

    Construct per-job (so the bound ``score_breakdown`` tool serves the
    right breakdown). The orchestrator class itself stays tiny -- the
    bounded ReAct loop lives in :mod:`src.agent.core.loop`; we just
    package the prompt + tool registry + fallback ladder here.
    """

    def __init__(
        self,
        breakdown: ScoreBreakdown,
        jd_lookup_tool: Any | None = None,
        llm_fn: LlmFn | None = None,
    ) -> None:
        self._breakdown = breakdown
        self._score_breakdown_tool = ScoreBreakdownTool(breakdown)
        self._jd_lookup_tool = jd_lookup_tool
        self._llm_fn = llm_fn

    def run(self, *, use_agent: bool = True) -> EdgeCaseDecision:
        bd = self._breakdown

        # Disqualified jobs short-circuit before the borderline check --
        # we never surface a hard-rule rejection (visa, US auth, etc.).
        # The plan explicitly scopes 16.2 to score-band edge cases.
        if bd.disqualified:
            return EdgeCaseDecision(
                kind="not_invoked",
                verdict="reject",
                rationale="hard-rule disqualification; agent does not override hard rules",
                job_id=bd.job_id,
                job_snapshot_id=bd.job_snapshot_id,
                final_score=bd.final_score,
            )

        if not is_borderline(bd.final_score):
            return EdgeCaseDecision(
                kind="not_invoked",
                verdict="surface" if bd.final_score > BORDERLINE_HIGH else "reject",
                rationale=(
                    "score outside borderline band; deterministic decision retained"
                ),
                job_id=bd.job_id,
                job_snapshot_id=bd.job_snapshot_id,
                final_score=bd.final_score,
            )

        if not use_agent or self._llm_fn is None:
            return EdgeCaseDecision(
                kind="not_invoked",
                verdict="reject",
                rationale="agent disabled or unavailable; default to deterministic reject",
                job_id=bd.job_id,
                job_snapshot_id=bd.job_snapshot_id,
                final_score=bd.final_score,
            )

        # Build tool registry. ``jd_lookup`` is optional -- if the caller
        # did not bind a snapshot, the agent works from the breakdown
        # alone (still useful, since most borderline rejections are
        # explained by component scores rather than JD text).
        tools: dict[str, Callable[[dict[str, Any]], Any]] = {
            self._score_breakdown_tool.name: self._score_breakdown_tool.run,
        }
        if self._jd_lookup_tool is not None:
            tools[self._jd_lookup_tool.name] = self._jd_lookup_tool.run

        prompt = _build_prompt(bd)

        try:
            raw_output = self._llm_fn(prompt, tools)
        except Exception as exc:  # noqa: BLE001 -- want to catch broadly
            logger.exception("Edge-case agent raised for job_id=%s", bd.job_id)
            return EdgeCaseDecision(
                kind="agent_error",
                verdict="reject",
                rationale="agent raised; falling back to deterministic reject",
                agent_error=f"{type(exc).__name__}: {exc}",
                job_id=bd.job_id,
                job_snapshot_id=bd.job_snapshot_id,
                final_score=bd.final_score,
            )

        parsed = _parse_agent_output(raw_output)
        if parsed is None:
            return EdgeCaseDecision(
                kind="agent_malformed",
                verdict="reject",
                rationale="agent output malformed; falling back to deterministic reject",
                raw_agent_output=raw_output,
                job_id=bd.job_id,
                job_snapshot_id=bd.job_snapshot_id,
                final_score=bd.final_score,
            )

        verdict, confidence, rationale = parsed
        return EdgeCaseDecision(
            kind="agent_ok",
            verdict=verdict,
            confidence=confidence,
            rationale=rationale or "agent did not provide a rationale",
            raw_agent_output=raw_output,
            job_id=bd.job_id,
            job_snapshot_id=bd.job_snapshot_id,
            final_score=bd.final_score,
        )
