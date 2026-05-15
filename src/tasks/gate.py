"""Phase 14.4: Postgres-backed HITL gate.

A ``needs_human`` outcome from a bounded agent (see
:class:`src.tasks.base.AgentDispatch`) parks the parent task at this
queue. The user reviews the request at ``/api/gate/...`` and either
approves or rejects it; approval enqueues a follow-up task that
resumes work using the original idempotency key.

This module exposes the *transitions*; the routes that drive them live
in :mod:`src.web.routes.api` (Phase 14.8). The file-backed gate from
Agent Phase 8 lives on as :mod:`src.agent.gate.queue` for one release
window; new code paths should use this module.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.models import GateRequest, TaskRecord
from src.tasks.context import current_tenant_id

logger = logging.getLogger(__name__)


# ---- Status constants exposed for callers + tests --------------------

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"

TERMINAL_STATUSES = frozenset({STATUS_APPROVED, STATUS_REJECTED, STATUS_EXPIRED})


class GateError(Exception):
    """Raised on illegal transitions or missing rows."""


@dataclass(frozen=True)
class GateDecision:
    """Returned from :func:`approve` / :func:`reject` so callers can
    chain into a follow-up enqueue without re-fetching the row."""

    gate_id: uuid.UUID
    task_id: uuid.UUID | None
    decision: str
    payload: dict[str, Any] | None


# ---- Read + write helpers --------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def open_request(
    session: Session,
    *,
    kind: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    task_id: uuid.UUID | None = None,
    tenant_id: str | None = None,
    ttl_seconds: int | None = None,
) -> GateRequest:
    """Insert a ``pending`` row and (if linked to a task) flip the
    task's audit row to ``waiting_human``. The caller commits.
    """
    tenant = tenant_id or current_tenant_id()
    row = GateRequest(
        tenant_id=tenant,
        task_id=task_id,
        kind=kind,
        summary=summary or "",
        payload=payload,
        status=STATUS_PENDING,
        ttl_seconds=ttl_seconds,
    )
    session.add(row)
    session.flush()

    if task_id is not None:
        task = session.get(TaskRecord, task_id)
        if task is not None:
            task.status = "waiting_human"
            task.updated_at = _utcnow()
    return row


def get(session: Session, gate_id: uuid.UUID) -> GateRequest:
    row = session.get(GateRequest, gate_id)
    if row is None:
        raise GateError(f"gate request not found: {gate_id}")
    return row


def list_pending(
    session: Session,
    *,
    tenant_id: str | None = None,
    limit: int = 100,
) -> list[GateRequest]:
    tenant = tenant_id or current_tenant_id()
    stmt = (
        select(GateRequest)
        .where(GateRequest.tenant_id == tenant)
        .where(GateRequest.status == STATUS_PENDING)
        .order_by(GateRequest.requested_at.asc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars())


def approve(
    session: Session,
    gate_id: uuid.UUID,
    *,
    decided_by: str | None = None,
    reason: str | None = None,
) -> GateDecision:
    return _transition(
        session,
        gate_id,
        target=STATUS_APPROVED,
        decided_by=decided_by,
        reason=reason,
    )


def reject(
    session: Session,
    gate_id: uuid.UUID,
    *,
    decided_by: str | None = None,
    reason: str | None = None,
) -> GateDecision:
    return _transition(
        session,
        gate_id,
        target=STATUS_REJECTED,
        decided_by=decided_by,
        reason=reason,
    )


def expire(session: Session, gate_id: uuid.UUID) -> GateDecision:
    """Used by the maintenance sweep. Idempotent."""
    return _transition(session, gate_id, target=STATUS_EXPIRED, decided_by="system")


def _transition(
    session: Session,
    gate_id: uuid.UUID,
    *,
    target: str,
    decided_by: str | None = None,
    reason: str | None = None,
) -> GateDecision:
    row = get(session, gate_id)
    if row.status in TERMINAL_STATUSES:
        # Re-approving / re-rejecting an already-decided row is a
        # double-click on the UI -- we surface it as a no-op replay
        # so the API can return 200 instead of 409.
        if row.status != target and target != STATUS_EXPIRED:
            raise GateError(
                f"gate {gate_id} already {row.status}; cannot transition to {target}"
            )
        return GateDecision(
            gate_id=row.id,
            task_id=row.task_id,
            decision=row.status,
            payload=row.payload,
        )

    row.status = target
    row.decision = target
    row.decided_at = _utcnow()
    row.decided_by = decided_by
    row.reason = reason

    # If this gate was parking a task, the task's status returns to
    # something the worker can resume. We do NOT auto-flip it to
    # succeeded -- a follow-up "resume" task (typically enqueued by
    # the route handler in Phase 14.8 immediately after approve())
    # owns the new attempt and the new audit row.
    if row.task_id is not None:
        task = session.get(TaskRecord, row.task_id)
        if task is not None and task.status == "waiting_human":
            # Leave the task row in waiting_human; the follow-up task
            # picks up the work. Marking it succeeded/failed here
            # would lie about what actually ran.
            task.last_error = (
                f"gate {row.id} {target}" + (f": {reason}" if reason else "")
            )
            task.updated_at = _utcnow()

    return GateDecision(
        gate_id=row.id,
        task_id=row.task_id,
        decision=target,
        payload=row.payload,
    )


__all__ = [
    "GateDecision",
    "GateError",
    "STATUS_APPROVED",
    "STATUS_EXPIRED",
    "STATUS_PENDING",
    "STATUS_REJECTED",
    "TERMINAL_STATUSES",
    "approve",
    "expire",
    "get",
    "list_pending",
    "open_request",
    "reject",
]
