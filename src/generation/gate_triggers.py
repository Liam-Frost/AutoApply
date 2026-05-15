"""Phase 15.10: HITL gate triggers for Phase 15 generation flows.

Generation itself (resume / cover letter) does NOT block on the
Phase 14.4 gate. Only the operations that *mutate persistent
grounding state* require explicit user approval:

  * Bullet pool mutation -- an agent proposes adding / editing a row
    in ``bullet_pool``. Future bullets will be selected from this
    pool, so an unreviewed mutation can leak across every future
    application.
  * Story bank mutation -- an agent proposes adding / editing a row
    in the YAML story bank for the same reason.
  * Template manifest persistence -- the Phase 15.8 adapter assistant
    proposes a manifest; finalising it would mark the template
    active for every subsequent ``materials.generate`` call.

Everything else (one-shot DOCX patch, one-shot LaTeX render, cover-
letter dispatch) is per-application and the audit row + trace are the
sufficient observability surface.

The module is intentionally narrow: it owns the *decision* "should
this mutation gate?" + the helper that opens a gate row via
:mod:`src.tasks.gate`. The actual mutation lives in 15.7 / 15.8 / the
profile YAML editor; those call into here when they want to
propose a change.

D026 contract: the gate row is created in the Phase 14.4
``gate_queue`` table with kind ``materials.<mutation>`` so the
Phase 14.8 ``/api/gate`` listing surfaces all materials gates
together.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from src.core.models import GateRequest
from src.tasks import gate as gate_module
from src.tasks.context import current_tenant_id

logger = logging.getLogger(__name__)


GateKind = Literal[
    "materials.bullet_pool_mutation",
    "materials.story_bank_mutation",
    "materials.template_manifest_persist",
]


@dataclass(frozen=True)
class GateProposal:
    """Returned from :func:`propose_*`; the caller waits on
    ``gate_id`` via the Phase 14.4 API / UI."""

    gate_id: uuid.UUID
    kind: GateKind
    summary: str


def propose_bullet_pool_mutation(
    session: Session,
    *,
    bullets: list[dict[str, Any]],
    rationale: str,
    task_id: uuid.UUID | None = None,
    tenant_id: str | None = None,
) -> GateProposal:
    """Open a gate request for an agent-proposed bullet_pool change.

    ``bullets`` is a list of ``{action: "add" | "edit" | "remove",
    bullet_id?: str, text: str, tags: [...]}`` payloads. The caller
    (typically the resume agent) must NOT have applied the mutation
    yet -- the gate is the gate.
    """
    summary = _summary_for_bullets(bullets, rationale)
    row = gate_module.open_request(
        session,
        kind="materials.bullet_pool_mutation",
        summary=summary,
        payload={"bullets": bullets, "rationale": rationale},
        task_id=task_id,
        tenant_id=tenant_id or current_tenant_id(),
    )
    return GateProposal(
        gate_id=row.id, kind="materials.bullet_pool_mutation", summary=summary
    )


def propose_story_bank_mutation(
    session: Session,
    *,
    stories: list[dict[str, Any]],
    rationale: str,
    task_id: uuid.UUID | None = None,
    tenant_id: str | None = None,
) -> GateProposal:
    """Open a gate request for a story-bank YAML edit.

    Each story is a ``{action, story_id?, title, body, themes}``
    payload. The cover-letter agent (Phase 15.7) currently does NOT
    mutate the story bank; this is reserved for the future eval-
    driven story curation flow."""
    summary = _summary_for_stories(stories, rationale)
    row = gate_module.open_request(
        session,
        kind="materials.story_bank_mutation",
        summary=summary,
        payload={"stories": stories, "rationale": rationale},
        task_id=task_id,
        tenant_id=tenant_id or current_tenant_id(),
    )
    return GateProposal(
        gate_id=row.id, kind="materials.story_bank_mutation", summary=summary
    )


def propose_template_manifest_persist(
    session: Session,
    *,
    template_id: str,
    package_dir: str,
    sample_render_ok: bool,
    notes: list[str],
    task_id: uuid.UUID | None = None,
    tenant_id: str | None = None,
) -> GateProposal:
    """Open a gate request for a Phase 15.8 manifest finalize step.

    The proposal must already be validated (sample_render_ok=True is
    the documented happy path; an override path can still propose a
    gate so the user explicitly accepts an unvalidated manifest)."""
    summary = (
        f"Persist LaTeX manifest for template {template_id!r} "
        f"({'sample render OK' if sample_render_ok else 'WARNING: sample render did NOT succeed'})"
    )
    row = gate_module.open_request(
        session,
        kind="materials.template_manifest_persist",
        summary=summary,
        payload={
            "template_id": template_id,
            "package_dir": package_dir,
            "sample_render_ok": sample_render_ok,
            "notes": notes,
        },
        task_id=task_id,
        tenant_id=tenant_id or current_tenant_id(),
    )
    return GateProposal(
        gate_id=row.id, kind="materials.template_manifest_persist", summary=summary
    )


# ---- Policy: is this kind of operation gate-worthy? ------------------


def is_gateworthy(kind: str) -> bool:
    """Per Phase 15.10: only persistent grounding mutations gate.
    One-shot generation does NOT.

    Caller passes a string the operation chose itself (e.g.
    ``"docx_patch_one_shot"`` -- the patcher routes through here so
    the *decision* lives in one place even though the answer is
    'no')."""
    return kind in {
        "materials.bullet_pool_mutation",
        "materials.story_bank_mutation",
        "materials.template_manifest_persist",
        # Future Phase 15 extensions can extend this set; bare
        # generation flows must NOT be added here.
    }


# ---- Helpers ---------------------------------------------------------


def _summary_for_bullets(bullets: list[dict[str, Any]], rationale: str) -> str:
    counts = {"add": 0, "edit": 0, "remove": 0}
    for b in bullets:
        action = (b or {}).get("action")
        if action in counts:
            counts[action] += 1
    parts = [f"{counts[k]} {k}" for k in ("add", "edit", "remove") if counts[k]]
    head = ", ".join(parts) or "no-op"
    rationale_clip = (rationale or "").strip()[:160]
    return f"Bullet pool mutation: {head}. Rationale: {rationale_clip!r}"


def _summary_for_stories(stories: list[dict[str, Any]], rationale: str) -> str:
    counts = {"add": 0, "edit": 0, "remove": 0}
    for s in stories:
        action = (s or {}).get("action")
        if action in counts:
            counts[action] += 1
    parts = [f"{counts[k]} {k}" for k in ("add", "edit", "remove") if counts[k]]
    head = ", ".join(parts) or "no-op"
    rationale_clip = (rationale or "").strip()[:160]
    return f"Story bank mutation: {head}. Rationale: {rationale_clip!r}"


def find_pending_for_task(
    session: Session, task_id: uuid.UUID
) -> list[GateRequest]:
    """List pending gate rows whose ``task_id`` matches. Used by the
    materials task to discover which mutations are blocking it."""
    from sqlalchemy import select

    stmt = (
        select(GateRequest)
        .where(GateRequest.task_id == task_id)
        .where(GateRequest.status == "pending")
    )
    return list(session.execute(stmt).scalars())


__all__ = [
    "GateKind",
    "GateProposal",
    "find_pending_for_task",
    "is_gateworthy",
    "propose_bullet_pool_mutation",
    "propose_story_bank_mutation",
    "propose_template_manifest_persist",
]
