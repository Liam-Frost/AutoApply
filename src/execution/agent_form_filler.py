"""Agent-driven form filling orchestrator.

This is the Phase 9 entry point that ties the agent loop, browser
tools, profile lookup, the HITL gate, and the deterministic Playwright
filler into one pipeline:

    1. Build a PageSnapshot from the live page (no agent involved).
    2. Take a screenshot for the agent to reference if it asks.
    3. Run the agent loop with a restricted toolset (inspect / find /
       propose / profile_lookup / screenshot / finish).
    4. Review proposals against a confidence threshold.
    5. If anything is below threshold, park a `form_fill_review`
       request on the approval gate. The orchestrator does NOT block;
       callers poll for a decision.
    6. Once cleared, replay proposals against the page using the
       existing deterministic ``fill_fields`` machinery.
    7. Submit goes through a separate ``submit_form`` gate. There is
       no code path that clicks submit without that gate clearing.

When the agent fails (max steps, parse errors, no proposals at all)
the orchestrator falls back to the deterministic
``map_fields_to_profile`` flow so investigation never silently breaks
production runs.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.agent.core.loop import (
    AgentResult,
    AgentSession,
    LLMCallable,
    SessionLimits,
)
from src.agent.gate.queue import ApprovalGate, ApprovalRequest, ApprovalStatus
from src.agent.tools.browser import (
    build_browser_tools,
    build_snapshot_from_page,
)
from src.agent.tools.browser_models import (
    FieldDescriptor,
    FillProposal,
    PageSnapshot,
)
from src.agent.tools.profile import ProfileLookupTool
from src.agent.trace.recorder import record_agent_run
from src.agent.trace.store import TraceRecord, TraceStore
from src.execution.form_filler import (
    FieldMapping,
    FormField,
    detect_fields,
    fill_fields,
    map_fields_to_profile,
)

logger = logging.getLogger("autoapply.execution.agent_form_filler")


# ---------------------------------------------------------------------------
# Config + result types
# ---------------------------------------------------------------------------


@dataclass
class AgentFormFillerConfig:
    """Knobs the orchestrator exposes.

    All defaults err on the side of asking the user. Production callers
    can lower ``min_confidence`` or set ``always_review`` to False once
    the eval suite shows the agent is reliable on a given vendor.
    """

    min_confidence: float = 0.7
    always_review: bool = True
    max_agent_steps: int = 12
    step_timeout: int = 90
    submit_gate_ttl_seconds: int = 600
    review_gate_ttl_seconds: int = 600
    fallback_to_rules: bool = True
    fill_delay_ms: int = 50
    screenshot_dir: Path = Path("data/output/screenshots/agent")


@dataclass
class ProposalReview:
    """Outcome of evaluating an agent's proposals before applying.

    ``needs_human_review`` is true when one or more proposals fall
    below the confidence threshold, OR when ``always_review`` is set.
    Callers use this to decide whether to park a gate request.
    """

    proposals: list[FillProposal] = field(default_factory=list)
    low_confidence: list[FillProposal] = field(default_factory=list)
    needs_human_review: bool = False
    threshold: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposals": [p.to_dict() for p in self.proposals],
            "low_confidence_field_ids": [p.field_id for p in self.low_confidence],
            "needs_human_review": self.needs_human_review,
            "threshold": self.threshold,
        }


@dataclass
class AgentFormFillResult:
    """Top-level result handed back to the CLI / web caller."""

    snapshot: PageSnapshot | None
    agent_result: AgentResult | None
    review: ProposalReview
    fill_mappings: list[FieldMapping]
    used_fallback: bool
    review_request_id: str | None = None
    submit_request_id: str | None = None
    trace_id: str | None = None
    screenshot_path: str | None = None
    error: str | None = None
    elapsed_ms: int = 0

    @property
    def filled_count(self) -> int:
        return sum(1 for m in self.fill_mappings if m.filled)

    def to_dict(self) -> dict[str, Any]:
        return {
            "review": self.review.to_dict(),
            "filled_count": self.filled_count,
            "field_count": len(self.fill_mappings),
            "used_fallback": self.used_fallback,
            "review_request_id": self.review_request_id,
            "submit_request_id": self.submit_request_id,
            "trace_id": self.trace_id,
            "screenshot_path": self.screenshot_path,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
        }


# ---------------------------------------------------------------------------
# Goal prompt
# ---------------------------------------------------------------------------


_GOAL_TEMPLATE = """\
Fill out the form on the current page using the applicant profile.

Step-by-step:
  1. Call browser_inspect_page to learn the field layout.
  2. For each fillable field, look up the right value via profile_lookup
     (e.g. profile_lookup path='identity.email'). Keep one lookup per turn.
  3. Call browser_propose_fill with the field_id, value, and a confidence
     in [0, 1]. Use confidence < 0.7 for any field you are uncertain
     about -- a human will review those before they are filled.
  4. Skip file upload fields. Skip submit/cancel buttons.
  5. When every required field has a proposal, call finish with a one-line
     summary like 'proposed values for 12 fields, 1 needs review'.

Constraints:
  - Never invent profile data. If profile_lookup fails, set confidence
    low and explain in `reasoning`.
  - Do NOT attempt to submit, click, or navigate -- you do not have
    those tools. The orchestrator handles submission separately.
  - Keep going only until every required field has a proposal; do not
    propose values for optional fields you have no profile data for.
"""


def build_goal(
    *,
    profile_summary: str | None = None,
    extra_context: str | None = None,
) -> str:
    parts = [_GOAL_TEMPLATE]
    if profile_summary:
        parts.append(f"\nProfile summary (top-level keys):\n{profile_summary}")
    if extra_context:
        parts.append(f"\nExtra context:\n{extra_context}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class AgentFormFiller:
    """End-to-end agent-driven form filler.

    Construction is cheap; each application page calls :meth:`run` once.
    The class is stateless across invocations -- all per-run state lives
    in :class:`AgentFormFillResult`.
    """

    def __init__(
        self,
        *,
        config: AgentFormFillerConfig | None = None,
        gate: ApprovalGate | None = None,
        trace_store: TraceStore | None = None,
        llm: LLMCallable | None = None,
    ) -> None:
        self.config = config or AgentFormFillerConfig()
        self.gate = gate or ApprovalGate()
        self.trace_store = trace_store or TraceStore()
        self._llm = llm  # Lazily resolved if not provided.

    # ----- top-level entry point -----

    async def run(
        self,
        *,
        page: Any,
        profile_data: dict[str, Any],
        job_id: str = "",
        extra_context: str | None = None,
    ) -> AgentFormFillResult:
        """Drive snapshot -> agent -> review -> apply (no submit)."""
        t0 = time.monotonic()
        snapshot: PageSnapshot | None = None
        agent_result: AgentResult | None = None
        review = ProposalReview(threshold=self.config.min_confidence)
        mappings: list[FieldMapping] = []
        screenshot_path: str | None = None
        trace_id: str | None = None
        review_request_id: str | None = None
        error: str | None = None

        try:
            snapshot = await build_snapshot_from_page(page)
            screenshot_path = await self._take_screenshot(page, job_id)
        except Exception as exc:  # noqa: BLE001 -- top-level boundary
            error = f"snapshot failed: {type(exc).__name__}: {exc}"
            logger.warning("Snapshot/screenshot failed: %s", error)

        if snapshot is None or not snapshot.fields:
            # Nothing the agent can do; let the deterministic path try.
            logger.info("Snapshot empty -- falling back to rule-based filler")
            mappings = await self._run_fallback(page, profile_data)
            return AgentFormFillResult(
                snapshot=snapshot,
                agent_result=None,
                review=review,
                fill_mappings=mappings,
                used_fallback=True,
                screenshot_path=screenshot_path,
                error=error,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
            )

        try:
            agent_result, trace_id, review = self._run_agent(
                snapshot=snapshot,
                profile_data=profile_data,
                screenshot_path=screenshot_path,
                job_id=job_id,
                extra_context=extra_context,
            )
        except Exception as exc:  # noqa: BLE001
            error = f"agent failed: {type(exc).__name__}: {exc}"
            logger.warning("Agent loop crashed: %s", error)

        if (
            self.config.fallback_to_rules
            and (agent_result is None or not review.proposals)
        ):
            logger.info(
                "Agent produced no proposals (%s); falling back to rules.",
                "crashed" if agent_result is None else agent_result.stop_reason,
            )
            mappings = await self._run_fallback(page, profile_data)
            return AgentFormFillResult(
                snapshot=snapshot,
                agent_result=agent_result,
                review=review,
                fill_mappings=mappings,
                used_fallback=True,
                trace_id=trace_id,
                screenshot_path=screenshot_path,
                error=error,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
            )

        if review.needs_human_review:
            request = self._propose_review_gate(
                snapshot=snapshot,
                review=review,
                job_id=job_id,
                trace_id=trace_id,
            )
            review_request_id = request.id
            logger.info(
                "Agent fill review parked at %s (threshold %.2f, %d low-confidence)",
                request.id,
                review.threshold,
                len(review.low_confidence),
            )
            return AgentFormFillResult(
                snapshot=snapshot,
                agent_result=agent_result,
                review=review,
                fill_mappings=[],
                used_fallback=False,
                trace_id=trace_id,
                screenshot_path=screenshot_path,
                review_request_id=review_request_id,
                error=error,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
            )

        # Confidence high across the board: apply directly.
        mappings = await self._apply_proposals(
            page=page,
            snapshot=snapshot,
            proposals=review.proposals,
        )
        return AgentFormFillResult(
            snapshot=snapshot,
            agent_result=agent_result,
            review=review,
            fill_mappings=mappings,
            used_fallback=False,
            trace_id=trace_id,
            screenshot_path=screenshot_path,
            error=error,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    # ----- review-gate completion (called after the user approves) -----

    async def apply_after_review(
        self,
        *,
        page: Any,
        snapshot: PageSnapshot,
        proposals: list[FillProposal],
    ) -> list[FieldMapping]:
        """Apply previously-reviewed proposals.

        Separate method (rather than continuing :meth:`run`) so the web
        layer can call it once it sees ``ApprovalStatus.APPROVED`` for
        the parked review request.
        """
        return await self._apply_proposals(
            page=page, snapshot=snapshot, proposals=proposals
        )

    # ----- submit gate -----

    def request_submit_approval(
        self,
        *,
        snapshot: PageSnapshot,
        review: ProposalReview,
        job_id: str = "",
        trace_id: str | None = None,
    ) -> ApprovalRequest:
        """Park a ``submit_form`` gate request. Always required pre-submit."""
        payload = {
            "job_id": job_id,
            "trace_id": trace_id,
            "url": snapshot.url,
            "title": snapshot.title,
            "field_count": len(snapshot.fields),
            "proposals": [p.to_dict() for p in review.proposals],
            "low_confidence_field_ids": [p.field_id for p in review.low_confidence],
        }
        return self.gate.propose(
            kind="submit_form",
            summary=(
                f"Submit application for {snapshot.title or snapshot.url} "
                f"({len(review.proposals)} fields filled)"
            ),
            payload=payload,
            ttl_seconds=self.config.submit_gate_ttl_seconds,
        )

    async def submit(
        self,
        *,
        page: Any,
        request_id: str,
        submit_selector: str | None = None,
    ) -> bool:
        """Click the submit button -- only if ``request_id`` is approved.

        Returns True on success. Raises :class:`PermissionError` when
        the gate has not approved the request, so test/dev callers see
        a hard failure rather than a silent no-op.
        """
        req = self.gate.get(request_id)
        if req.status != ApprovalStatus.APPROVED:
            raise PermissionError(
                f"submit blocked: gate request {request_id} is "
                f"{req.status.value}, not approved."
            )
        return await _click_submit(page, submit_selector)

    # ----- internal helpers -----

    def _run_agent(
        self,
        *,
        snapshot: PageSnapshot,
        profile_data: dict[str, Any],
        screenshot_path: str | None,
        job_id: str,
        extra_context: str | None,
    ) -> tuple[AgentResult, str, ProposalReview]:
        bundle = build_browser_tools(
            snapshot,
            screenshot_path=screenshot_path,
        )
        bundle.registry.register(ProfileLookupTool(profile_data))

        goal = build_goal(
            profile_summary=", ".join(sorted(profile_data.keys())),
            extra_context=extra_context,
        )
        limits = SessionLimits(
            max_steps=self.config.max_agent_steps,
            step_timeout=self.config.step_timeout,
        )
        llm = self._resolve_llm()

        if self._uses_recorder():
            agent_result, trace_record = record_agent_run(
                goal=goal,
                tools=bundle.registry,
                llm=llm,
                limits=limits,
                metadata={
                    "phase": "9",
                    "agent": "form_filler",
                    "job_id": job_id,
                    "url": snapshot.url,
                    "field_count": len(snapshot.fields),
                    "screenshot_path": screenshot_path,
                },
                store=self.trace_store,
            )
        else:
            session = AgentSession(
                goal=goal, tools=bundle.registry, llm=llm, limits=limits
            )
            agent_result = session.run()
            trace_record = None

        review = self._review(bundle.collector.latest())
        trace_id = trace_record.id if trace_record else ""
        return agent_result, trace_id, review

    def _review(self, proposals: list[FillProposal]) -> ProposalReview:
        threshold = self.config.min_confidence
        low = [p for p in proposals if p.confidence < threshold]
        needs = self.config.always_review or bool(low) or not proposals
        return ProposalReview(
            proposals=list(proposals),
            low_confidence=low,
            needs_human_review=needs,
            threshold=threshold,
        )

    def _propose_review_gate(
        self,
        *,
        snapshot: PageSnapshot,
        review: ProposalReview,
        job_id: str,
        trace_id: str | None,
    ) -> ApprovalRequest:
        payload = {
            "job_id": job_id,
            "trace_id": trace_id,
            "url": snapshot.url,
            "title": snapshot.title,
            "threshold": review.threshold,
            "proposals": [
                _proposal_with_label(p, snapshot) for p in review.proposals
            ],
            "low_confidence_field_ids": [p.field_id for p in review.low_confidence],
        }
        summary = (
            f"Review {len(review.proposals)} proposed values for "
            f"{snapshot.title or snapshot.url} "
            f"({len(review.low_confidence)} below threshold)"
        )
        return self.gate.propose(
            kind="form_fill_review",
            summary=summary,
            payload=payload,
            ttl_seconds=self.config.review_gate_ttl_seconds,
        )

    async def _apply_proposals(
        self,
        *,
        page: Any,
        snapshot: PageSnapshot,
        proposals: list[FillProposal],
    ) -> list[FieldMapping]:
        if not proposals:
            return []
        mappings = _proposals_to_mappings(snapshot, proposals)
        if not mappings:
            return []
        return await fill_fields(page, mappings, delay_ms=self.config.fill_delay_ms)

    async def _run_fallback(
        self, page: Any, profile_data: dict[str, Any]
    ) -> list[FieldMapping]:
        try:
            fields = await detect_fields(page)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fallback detect_fields failed: %s", exc)
            return []
        if not fields:
            return []
        mappings = map_fields_to_profile(fields, profile_data)
        return await fill_fields(page, mappings, delay_ms=self.config.fill_delay_ms)

    async def _take_screenshot(self, page: Any, job_id: str) -> str | None:
        try:
            self.config.screenshot_dir.mkdir(parents=True, exist_ok=True)
            prefix = (job_id[:8] + "_") if job_id else ""
            path = self.config.screenshot_dir / f"{prefix}agent_pre_fill.png"
            await page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception as exc:  # noqa: BLE001 -- screenshot is best-effort
            logger.debug("Screenshot failed: %s", exc)
            return None

    def _resolve_llm(self) -> LLMCallable:
        if self._llm is not None:
            return self._llm
        # Late import to keep test imports of the orchestrator cheap.
        from src.agent.core.llm_adapter import cli_llm  # noqa: PLC0415

        return cli_llm

    def _uses_recorder(self) -> bool:
        # Lets tests pass an in-memory store while still recording.
        return self.trace_store is not None


# ---------------------------------------------------------------------------
# Proposal -> FieldMapping conversion
# ---------------------------------------------------------------------------


def _proposals_to_mappings(
    snapshot: PageSnapshot, proposals: list[FillProposal]
) -> list[FieldMapping]:
    """Translate agent proposals into ``FieldMapping`` rows the
    deterministic ``fill_fields`` understands.

    Skips proposals whose field_id has no Playwright selector (e.g.
    HTML-fixture snapshots used in evals where no live page exists).
    Radio fields are special-cased: we have to point Playwright at the
    specific radio button matching the proposed value, not the group.
    """
    mappings: list[FieldMapping] = []
    selectors = snapshot.selectors_by_id
    for proposal in proposals:
        descriptor = snapshot.field_by_id(proposal.field_id)
        if descriptor is None:
            continue
        selector = selectors.get(proposal.field_id, "")
        if not selector:
            # No live selector -- skip silently. Eval suites care about
            # the proposal payload itself, not Playwright execution.
            continue
        ff = _form_field_for_proposal(descriptor, selector, proposal, snapshot)
        if ff is None:
            continue
        mappings.append(
            FieldMapping(
                form_field=ff,
                data_key=proposal.field_id,
                value=proposal.value,
            )
        )
    return mappings


def _form_field_for_proposal(
    descriptor: FieldDescriptor,
    selector: str,
    proposal: FillProposal,
    snapshot: PageSnapshot,
) -> FormField | None:
    if descriptor.field_type == "file":
        # File uploads handled by the dedicated uploader, not here.
        return None
    if descriptor.field_type == "radio":
        # Specific-radio selector: match by value attribute. Falls back
        # to the group selector if we can't refine -- the deterministic
        # filler then clicks the first radio, which is at least visible
        # in the trace.
        radio_name = snapshot.radio_names_by_id.get(descriptor.field_id, "")
        if radio_name:
            specific = (
                f"input[type='radio'][name='{_css_attr(radio_name)}']"
                f"[value='{_css_attr(proposal.value)}']"
            )
            return FormField(
                selector=specific,
                label=descriptor.label,
                field_type="radio",
                options=list(descriptor.options),
            )
    return FormField(
        selector=selector,
        label=descriptor.label,
        field_type=descriptor.field_type,
        required=descriptor.required,
        options=list(descriptor.options),
    )


def _css_attr(value: str) -> str:
    """Escape a value for safe interpolation into a CSS attribute selector."""
    return value.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')


def _proposal_with_label(
    proposal: FillProposal, snapshot: PageSnapshot
) -> dict[str, Any]:
    descriptor = snapshot.field_by_id(proposal.field_id)
    return {
        "field_id": proposal.field_id,
        "field_label": descriptor.label if descriptor else "",
        "field_type": descriptor.field_type if descriptor else "",
        "value": proposal.value,
        "confidence": proposal.confidence,
        "reasoning": proposal.reasoning,
    }


# ---------------------------------------------------------------------------
# Submit (deliberately separate, rate-limited surface)
# ---------------------------------------------------------------------------


async def _click_submit(page: Any, selector: str | None) -> bool:
    """Click submit. Hard-isolated from the agent's reach.

    Tries an explicit selector if provided, then falls back to common
    submit-button patterns. Returns True on click success.
    """
    candidates: list[str] = []
    if selector:
        candidates.append(selector)
    candidates += [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Submit')",
        "button:has-text('Apply')",
        "button:has-text('Send Application')",
    ]
    for css in candidates:
        try:
            locator = page.locator(css)
            count_method = getattr(locator, "count", None)
            count = await count_method() if count_method else 1
            if count and count > 0:
                await locator.first.click()
                return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("Submit candidate %s failed: %s", css, exc)
            continue
    return False


# ---------------------------------------------------------------------------
# Convenience top-level
# ---------------------------------------------------------------------------


async def run_agent_form_fill(
    *,
    page: Any,
    profile_data: dict[str, Any],
    job_id: str = "",
    config: AgentFormFillerConfig | None = None,
    gate: ApprovalGate | None = None,
    trace_store: TraceStore | None = None,
    llm: LLMCallable | None = None,
    extra_context: str | None = None,
) -> AgentFormFillResult:
    """Run the orchestrator with default wiring.

    Tests and the eval suite use the class directly so they can swap
    individual collaborators; live application code calls this.
    """
    filler = AgentFormFiller(
        config=config, gate=gate, trace_store=trace_store, llm=llm
    )
    return await filler.run(
        page=page,
        profile_data=profile_data,
        job_id=job_id,
        extra_context=extra_context,
    )


# ---------------------------------------------------------------------------
# Re-exports so callers don't have to know the internal layout.
# ---------------------------------------------------------------------------


__all__ = [
    "AgentFormFillResult",
    "AgentFormFiller",
    "AgentFormFillerConfig",
    "ApprovalGate",  # re-exported for callers that propose/approve gates
    "FillProposal",
    "PageSnapshot",
    "ProposalReview",
    "TraceRecord",
    "TraceStore",
    "build_goal",
    "run_agent_form_fill",
]


# Defensive: catch any sync caller that forgets to await ``run``.
def _disallow_sync_run() -> None:
    raise RuntimeError("AgentFormFiller.run is async; await it.")


# We want ``asyncio.iscoroutinefunction(filler.run)`` to be True without
# decorators; nothing else here, just a marker the test suite asserts on.
assert asyncio.iscoroutinefunction(AgentFormFiller.run)
