"""Phase 15.7: :class:`AgentCoverLetter` orchestrator.

Routes cover-letter generation through the bounded agent harness. The
agent emits a :class:`CoverLetterDocument` IR (structured paragraphs
with evidence citations); the deterministic renderer turns that into
DOCX/PDF.

Flow::

    [evidence selection] -> [agent loop with jd_lookup + profile_lookup]
                            -> [IR with paragraphs + source_ids]
    [fact-drift post-guard] -> block on number drift, warn on entity drift
    [deterministic fallback] when:
       - agent raised
       - agent returned malformed IR
       - post-guard flagged drift

The fallback is the existing ``generate_cover_letter(..., use_llm=True)``
path (which already has its own try/except + template fallback), so we
end up with at most two layers of safety: the agent path, then the
deterministic LLM-driven template path.

D023 / Phase 14 contract: this module exposes a synchronous
``run(...)`` that returns a :class:`CoverLetterAgentResult`. Phase
14.6's ``materials.generate`` task wraps this inside
``AutoApplyTask.call_agent`` so the queue layer owns retry / HITL /
trace.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from src.generation.cover_letter import _select_evidence
from src.generation.fact_drift import FactDriftReport, check_fact_drift
from src.generation.ir import CoverLetterDocument, CoverLetterParagraph

logger = logging.getLogger(__name__)


CoverLetterDecision = Literal[
    "agent_ok",  # agent IR passed the fact-drift guard
    "agent_drift_fallback",  # agent IR flagged by guard; using deterministic path
    "agent_error_fallback",  # agent raised / malformed; using deterministic path
    "deterministic_only",  # caller asked for use_agent=False up front
]


@dataclass
class CoverLetterAgentResult:
    """Returned from :meth:`AgentCoverLetter.run`. The orchestrator
    owns the *decision*; the materials task body persists the
    artifacts."""

    decision: CoverLetterDecision
    document: CoverLetterDocument | None
    fact_drift: FactDriftReport | None = None
    used_evidence: list[str] = field(default_factory=list)
    agent_error: str | None = None
    notes: list[str] = field(default_factory=list)


class AgentCoverLetterError(Exception):
    """Raised on programmer error (missing JD snapshot, etc.)."""


class AgentCoverLetter:
    """Bound to a single :class:`JobSnapshot` + applicant profile +
    LLM callable.

    The orchestrator does NOT itself run a multi-step agent loop --
    that lives in :mod:`src.agent.core.loop` and Phase 14.6's task
    body wraps the AutoApplyTask boundary. ``run`` here is the
    contract between the queue task and the cover-letter generator;
    the agent loop is opt-in via the ``llm_fn`` parameter so unit
    tests can inject a deterministic stub.
    """

    def __init__(
        self,
        *,
        job_snapshot: Any,
        profile_data: dict[str, Any],
        llm_fn: Any | None = None,
    ) -> None:
        if job_snapshot is None:
            raise AgentCoverLetterError(
                "AgentCoverLetter requires a bound job_snapshot (Phase 15.6 jd_lookup)"
            )
        self._snapshot = job_snapshot
        self._profile = profile_data or {}
        # llm_fn(prompt, system=...) -> str. When None, the orchestrator
        # routes straight to the deterministic path (Phase 17 sets
        # this when the operator pauses LLM use; tests use this to
        # exercise the fallback ladder).
        self._llm_fn = llm_fn

    # ----- public ----------------------------------------------------

    def run(
        self,
        *,
        evidence_bullets: list[str] | None = None,
        use_agent: bool = True,
    ) -> CoverLetterAgentResult:
        """Produce a cover-letter IR + decision.

        ``use_agent=False`` forces the deterministic-only path
        (returns ``decision="deterministic_only"`` and the
        :class:`CoverLetterDocument` from the existing
        ``cover_letter.py`` template renderer)."""
        bullets = evidence_bullets or _select_evidence_safe(self._snapshot, self._profile)

        if not use_agent or self._llm_fn is None:
            document = self._render_deterministic(bullets)
            return CoverLetterAgentResult(
                decision="deterministic_only",
                document=document,
                used_evidence=bullets,
                notes=["agent disabled by caller"] if not use_agent else ["no llm_fn provided"],
            )

        try:
            document = self._call_agent(bullets)
        except Exception as exc:  # noqa: BLE001 -- agent failure is bounded
            logger.warning("AgentCoverLetter: agent raised; falling back: %s", exc)
            deterministic = self._render_deterministic(bullets)
            return CoverLetterAgentResult(
                decision="agent_error_fallback",
                document=deterministic,
                used_evidence=bullets,
                agent_error=repr(exc)[:1000],
            )

        if document is None:
            deterministic = self._render_deterministic(bullets)
            return CoverLetterAgentResult(
                decision="agent_error_fallback",
                document=deterministic,
                used_evidence=bullets,
                agent_error="agent returned None",
            )

        # Post-guard.
        generated_text = "\n\n".join(p.text for p in document.paragraphs if p.text)
        report = check_fact_drift(
            generated_text,
            evidence_texts=bullets,
            jd_snapshot_text=_snapshot_text(self._snapshot),
            profile_text=_profile_text(self._profile),
        )
        if report.has_blocking_drift:
            logger.info(
                "AgentCoverLetter: fact drift detected, falling back. drift=%s",
                report.number_drift,
            )
            deterministic = self._render_deterministic(bullets)
            return CoverLetterAgentResult(
                decision="agent_drift_fallback",
                document=deterministic,
                used_evidence=bullets,
                fact_drift=report,
            )

        return CoverLetterAgentResult(
            decision="agent_ok",
            document=document,
            used_evidence=bullets,
            fact_drift=report,
        )

    # ----- internals -------------------------------------------------

    def _call_agent(self, evidence_bullets: list[str]) -> CoverLetterDocument | None:
        """Invoke ``self._llm_fn`` to produce IR. Kept narrow so the
        Phase 14.6 task body can swap it for the harness's bounded
        loop (the harness already provides jd_lookup + profile_lookup
        tools via Phase 15.6 + the existing profile tool)."""
        if self._llm_fn is None:
            return None
        prompt = self._build_agent_prompt(evidence_bullets)
        raw = self._llm_fn(prompt, system=_AGENT_SYSTEM_PROMPT)
        if raw is None:
            return None
        return _parse_agent_output(raw)

    def _build_agent_prompt(self, evidence_bullets: list[str]) -> str:
        title = getattr(self._snapshot, "title", "")
        company = getattr(self._snapshot, "raw_data", {}).get("company") if isinstance(
            getattr(self._snapshot, "raw_data", None), dict
        ) else ""
        return (
            f"Produce a CoverLetterDocument JSON for the role {title!r} at company {company!r}.\n"
            f"Evidence bullets you must ground every claim in:\n"
            + "\n".join(f"- {b}" for b in evidence_bullets)
            + "\n"
            + "Use jd_lookup for JD facts, profile_lookup for applicant facts. "
            + "Return JSON matching the CoverLetterDocument IR schema: "
            + '{"paragraphs": [{"type": "opening|experience_evidence|company_fit|closing", '
            + '"text": "...", "source_ids": ["..."]}]}.'
        )

    def _render_deterministic(
        self, evidence_bullets: list[str]
    ) -> CoverLetterDocument:
        """Build a CoverLetterDocument via the existing deterministic
        template builder. We import lazily because the chain pulls
        python-docx + the LLM wrapper -- a unit test that only checks
        the agent path should not have to fault those in."""
        from src.generation.cover_letter import (
            _cover_paragraphs_from_text,
            _generate_template,
            build_cover_letter_document,
        )

        identity = self._profile.get("identity", {}) or {}
        # _generate_template needs a job-like object; we synthesise one
        # from the snapshot's surface (title / company / description).
        snapshot = self._snapshot

        class _Job:
            title = getattr(snapshot, "title", "")
            company = getattr(snapshot, "raw_data", {}).get("company", "") if isinstance(
                getattr(snapshot, "raw_data", None), dict
            ) else ""
            description = getattr(snapshot, "description", "")
            location = getattr(snapshot, "location", "")

        text = _generate_template(_Job, identity, evidence_bullets)
        document = build_cover_letter_document(
            job=_Job,
            profile_data=self._profile,
            body_text=text,
            evidence_bullets=evidence_bullets,
        )
        # In case the build helper returns a thinner doc than expected,
        # ensure we at least have the paragraphs structure populated.
        if not document.paragraphs:
            document.paragraphs = _cover_paragraphs_from_text(text)
        return document


# ---- Agent output parsing -------------------------------------------


_AGENT_SYSTEM_PROMPT = (
    "You are AgentCoverLetter. You produce structured CoverLetterDocument "
    "JSON. Every paragraph cites at least one source_id from the evidence "
    "you were given. You do not fabricate numbers or company names."
)


def _parse_agent_output(raw: str) -> CoverLetterDocument | None:
    """Best-effort JSON parse. We accept either a bare JSON object or
    a fenced code block; on parse failure we return None and let the
    orchestrator route to the deterministic fallback."""
    import json
    import re as _re

    if not isinstance(raw, str):
        return None
    text = raw.strip()
    # Strip ``` blocks.
    fenced = _re.search(r"```(?:json)?\s*(.*?)```", text, _re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        paragraphs_raw = payload.get("paragraphs") or []
        paragraphs = [
            CoverLetterParagraph(**p) for p in paragraphs_raw if isinstance(p, dict)
        ]
        if not paragraphs:
            return None
        return CoverLetterDocument(
            template_id=payload.get("template_id", "cover_letter_classic_v1"),
            recipient=payload.get("recipient", {}),
            applicant=payload.get("applicant", {}),
            paragraphs=paragraphs,
        )
    except Exception:  # noqa: BLE001
        return None


# ---- Helpers --------------------------------------------------------


def _select_evidence_safe(snapshot: Any, profile: dict[str, Any]) -> list[str]:
    """Best-effort evidence picker using the existing helper. We wrap
    in try/except because the helper expects a ``RawJob`` shape; if
    the snapshot does not match, we fall back to applicant bullets."""

    class _JobLike:
        title = getattr(snapshot, "title", "") or ""
        company = ""
        description = getattr(snapshot, "description", "") or ""
        location = getattr(snapshot, "location", "") or ""
        requirements = getattr(snapshot, "requirements", None) or {}

    raw_data = getattr(snapshot, "raw_data", None)
    if isinstance(raw_data, dict):
        _JobLike.company = raw_data.get("company", "")

    try:
        return _select_evidence(_JobLike, profile)
    except Exception:  # noqa: BLE001
        # Fallback: surface the first few work-experience bullets.
        bullets: list[str] = []
        for entry in profile.get("work_experiences", []) or []:
            for bullet in entry.get("bullets", []) or []:
                if isinstance(bullet, dict):
                    text = bullet.get("text", "")
                elif isinstance(bullet, str):
                    text = bullet
                else:
                    continue
                if text:
                    bullets.append(text)
                if len(bullets) >= 6:
                    return bullets
        return bullets


def _snapshot_text(snapshot: Any) -> str:
    parts: list[str] = []
    for attr in ("title", "location", "employment_type", "description"):
        value = getattr(snapshot, attr, None)
        if value:
            parts.append(str(value))
    requirements = getattr(snapshot, "requirements", None)
    if isinstance(requirements, dict):
        for value in requirements.values():
            if isinstance(value, list):
                parts.extend(str(v) for v in value)
            elif value:
                parts.append(str(value))
    return "\n".join(parts)


def _profile_text(profile: dict[str, Any]) -> str:
    parts: list[str] = []
    identity = profile.get("identity") or {}
    for value in identity.values():
        if value:
            parts.append(str(value))
    for entry in profile.get("work_experiences", []) or []:
        for key in ("company", "title", "location"):
            value = entry.get(key)
            if value:
                parts.append(str(value))
        for bullet in entry.get("bullets", []) or []:
            if isinstance(bullet, dict):
                text = bullet.get("text", "")
            elif isinstance(bullet, str):
                text = bullet
            else:
                continue
            if text:
                parts.append(text)
    for entry in profile.get("education") or []:
        for key in ("institution", "degree", "field"):
            value = entry.get(key)
            if value:
                parts.append(str(value))
    return "\n".join(parts)


__all__ = [
    "AgentCoverLetter",
    "AgentCoverLetterError",
    "CoverLetterAgentResult",
    "CoverLetterDecision",
]
