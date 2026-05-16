"""Phase 17.2 application-layer use cases for the review queue.

Owns the read/write paths that the FastAPI route + the Phase 17.3 UI
will call. SQLAlchemy lives behind these helpers; the routes never
touch the ORM directly.

Surface area (kept narrow on purpose):

* :func:`create_entry` -- called by ``application.prepare`` task body
  when materials generation finishes.
* :func:`list_entries` -- kanban + CLI feed.
* :func:`get_entry` -- entry detail (used by 17.3 popover).
* :func:`approve` / :func:`reject` -- single-item transitions.
* :func:`bulk_approve` / :func:`bulk_reject` -- Phase 17.4.
* :func:`mark_submitted` -- called by ``application.submit`` task
  after the Phase 17.5 pre-submit gate passes.
* :func:`mark_stale` -- called by the pre-submit gate when the JD
  snapshot is too stale to submit against.
* :func:`refresh_stale` -- transitions ``stale -> pending`` after an
  operator clicks "refresh materials" in the UI.

All write paths go through the :mod:`src.review.state_machine`'s
:func:`next_status` guard so bad transitions surface as a single
``InvalidTransitionError`` rather than landing as a corrupt row.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.models import ReviewQueueEntry
from src.review.state_machine import (
    InvalidTransitionError,
    ReviewStatus,
    next_status,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class CreateEntryArgs:
    """Inputs for :func:`create_entry`. Plain dataclass because the
    callers (Celery task body + tests) build these from dicts."""

    tenant_id: str
    job_id: uuid.UUID | str | None
    job_snapshot_id: uuid.UUID | str | None
    materials_path: str | None
    score_breakdown: dict[str, Any] | None
    company: str | None
    title: str | None
    run_id: str | None = None


def serialize_entry(entry: ReviewQueueEntry) -> dict[str, Any]:
    """Map an ORM row to a JSON-friendly dict.

    The Phase 17.3 kanban consumes this shape; the Phase 17.6 morning
    digest reads the same shape from the audit row.
    """
    return {
        "id": str(entry.id),
        "tenant_id": entry.tenant_id,
        "job_id": str(entry.job_id) if entry.job_id else None,
        "job_snapshot_id": (
            str(entry.job_snapshot_id) if entry.job_snapshot_id else None
        ),
        "run_id": entry.run_id,
        "materials_path": entry.materials_path,
        "score_breakdown": entry.score_breakdown,
        "company": entry.company,
        "title": entry.title,
        "status": entry.status,
        "decision": entry.decision,
        "reason": entry.reason,
        "reviewer": entry.reviewer,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "reviewed_at": (
            entry.reviewed_at.isoformat() if entry.reviewed_at else None
        ),
        "submitted_at": (
            entry.submitted_at.isoformat() if entry.submitted_at else None
        ),
    }


def _coerce_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def create_entry(session: Session, args: CreateEntryArgs) -> ReviewQueueEntry:
    """Insert a ``pending`` review_queue row and return the persisted entry.

    Idempotent on ``(tenant_id, job_id, job_snapshot_id, status='pending')``
    via the table's UNIQUE constraint -- a second call for the same
    job + snapshot returns the existing pending row instead of
    raising. This matters because the nightly orchestrator can
    legitimately re-fire for the same job across re-runs (e.g. after a
    transient broker hiccup).
    """
    job_uuid = _coerce_uuid(args.job_id)
    snap_uuid = _coerce_uuid(args.job_snapshot_id)

    existing = (
        session.execute(
            select(ReviewQueueEntry).where(
                ReviewQueueEntry.tenant_id == args.tenant_id,
                ReviewQueueEntry.job_id == job_uuid,
                ReviewQueueEntry.job_snapshot_id == snap_uuid,
                ReviewQueueEntry.status == "pending",
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        logger.info(
            "review_queue: reusing existing pending entry id=%s for job_id=%s",
            existing.id,
            job_uuid,
        )
        return existing

    entry = ReviewQueueEntry(
        tenant_id=args.tenant_id,
        job_id=job_uuid,
        job_snapshot_id=snap_uuid,
        run_id=args.run_id,
        materials_path=args.materials_path,
        score_breakdown=args.score_breakdown,
        company=args.company,
        title=args.title,
        status="pending",
    )
    session.add(entry)
    session.flush()
    return entry


def get_entry(session: Session, entry_id: uuid.UUID | str) -> ReviewQueueEntry | None:
    eid = _coerce_uuid(entry_id)
    if eid is None:
        return None
    return session.get(ReviewQueueEntry, eid)


def list_entries(
    session: Session,
    *,
    tenant_id: str,
    status: ReviewStatus | None = None,
    limit: int = 200,
) -> list[ReviewQueueEntry]:
    """Read path for the Phase 17.3 kanban.

    ``status=None`` returns all rows for the tenant (the UI groups
    them client-side). The implicit ordering is ``created_at DESC``
    so the most recent nightly run shows at the top.
    """
    stmt = select(ReviewQueueEntry).where(ReviewQueueEntry.tenant_id == tenant_id)
    if status is not None:
        stmt = stmt.where(ReviewQueueEntry.status == status)
    stmt = stmt.order_by(ReviewQueueEntry.created_at.desc()).limit(limit)
    return list(session.execute(stmt).scalars().all())


def _transition(
    session: Session,
    entry: ReviewQueueEntry,
    dst: ReviewStatus,
    *,
    reviewer: str | None,
    reason: str | None,
    decision: str | None = None,
    set_reviewed: bool = True,
    set_submitted: bool = False,
) -> ReviewQueueEntry:
    """Apply a transition + audit timestamps. Raises on bad edges."""
    new_status = next_status(entry.status, dst)
    entry.status = new_status
    if reviewer is not None:
        entry.reviewer = reviewer
    if reason is not None:
        entry.reason = reason
    if decision is not None:
        entry.decision = decision
    now = _utcnow()
    if set_reviewed:
        entry.reviewed_at = now
    if set_submitted:
        entry.submitted_at = now
    session.flush()
    return entry


def approve(
    session: Session,
    entry_id: uuid.UUID | str,
    *,
    reviewer: str | None = None,
    reason: str | None = None,
) -> ReviewQueueEntry:
    entry = get_entry(session, entry_id)
    if entry is None:
        raise LookupError(f"review_queue entry not found: {entry_id!r}")
    return _transition(
        session, entry, "approved", reviewer=reviewer, reason=reason, decision="approve"
    )


def reject(
    session: Session,
    entry_id: uuid.UUID | str,
    *,
    reviewer: str | None = None,
    reason: str | None = None,
) -> ReviewQueueEntry:
    entry = get_entry(session, entry_id)
    if entry is None:
        raise LookupError(f"review_queue entry not found: {entry_id!r}")
    return _transition(
        session, entry, "rejected", reviewer=reviewer, reason=reason, decision="reject"
    )


def mark_submitted(
    session: Session,
    entry_id: uuid.UUID | str,
    *,
    reviewer: str | None = None,
    reason: str | None = None,
) -> ReviewQueueEntry:
    """Flip an ``approved`` entry to ``submitted``.

    Phase 17.5 pre-submit gate calls this after the gate passes.
    Bypasses ``reviewed_at`` because reviewed_at was already set when
    the operator clicked Approve.
    """
    entry = get_entry(session, entry_id)
    if entry is None:
        raise LookupError(f"review_queue entry not found: {entry_id!r}")
    return _transition(
        session,
        entry,
        "submitted",
        reviewer=reviewer,
        reason=reason,
        decision="submit",
        set_reviewed=False,
        set_submitted=True,
    )


def mark_stale(
    session: Session,
    entry_id: uuid.UUID | str,
    *,
    reason: str | None = None,
) -> ReviewQueueEntry:
    """Called by the Phase 17.5 pre-submit gate when the JD snapshot is
    too stale and a refresh isn't possible in time. The entry stays
    visible to the operator with a refresh-or-discard prompt."""
    entry = get_entry(session, entry_id)
    if entry is None:
        raise LookupError(f"review_queue entry not found: {entry_id!r}")
    return _transition(
        session,
        entry,
        "stale",
        reviewer=None,
        reason=reason,
        decision="stale",
        set_reviewed=False,
    )


def refresh_stale(
    session: Session,
    entry_id: uuid.UUID | str,
    *,
    reviewer: str | None = None,
) -> ReviewQueueEntry:
    """``stale -> pending``. Used when the UI re-runs materials
    generation after the pre-submit gate flagged staleness."""
    entry = get_entry(session, entry_id)
    if entry is None:
        raise LookupError(f"review_queue entry not found: {entry_id!r}")
    return _transition(
        session,
        entry,
        "pending",
        reviewer=reviewer,
        reason=None,
        decision="refresh",
        set_reviewed=False,
    )


# --------------------------------------------------------------------------- #
# Bulk ops (Phase 17.4)                                                       #
# --------------------------------------------------------------------------- #


@dataclass
class BulkResult:
    """Aggregate result for a bulk operation.

    Returning per-id outcomes (rather than raising on first failure)
    lets the UI render "8 of 12 approved; 4 failed: ..." in one
    response.
    """

    succeeded: list[str]
    failed: list[dict[str, str]]  # [{id, error}, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "succeeded": list(self.succeeded),
            "failed": list(self.failed),
        }


def bulk_approve(
    session: Session,
    entry_ids: Iterable[uuid.UUID | str],
    *,
    reviewer: str | None = None,
    reason: str | None = None,
) -> BulkResult:
    succeeded: list[str] = []
    failed: list[dict[str, str]] = []
    for raw_id in entry_ids:
        try:
            entry = approve(session, raw_id, reviewer=reviewer, reason=reason)
            succeeded.append(str(entry.id))
        except (InvalidTransitionError, LookupError) as exc:
            failed.append({"id": str(raw_id), "error": str(exc)})
    return BulkResult(succeeded=succeeded, failed=failed)


def bulk_reject(
    session: Session,
    entry_ids: Iterable[uuid.UUID | str],
    *,
    reviewer: str | None = None,
    reason: str | None = None,
) -> BulkResult:
    succeeded: list[str] = []
    failed: list[dict[str, str]] = []
    for raw_id in entry_ids:
        try:
            entry = reject(session, raw_id, reviewer=reviewer, reason=reason)
            succeeded.append(str(entry.id))
        except (InvalidTransitionError, LookupError) as exc:
            failed.append({"id": str(raw_id), "error": str(exc)})
    return BulkResult(succeeded=succeeded, failed=failed)


def bulk_reject_by_filter(
    session: Session,
    *,
    tenant_id: str,
    company: str | None = None,
    keyword_in_title: str | None = None,
    reviewer: str | None = None,
    reason: str | None = None,
) -> BulkResult:
    """Phase 17.4: bulk-reject by company or by title keyword.

    Only acts on ``pending`` rows (we don't auto-flip already-approved
    or already-submitted entries). The filter is a simple
    case-insensitive substring on the persisted ``company`` /
    ``title`` snapshot, NOT a re-fetch of the JD -- the operator's
    decision is made against the data they were shown.
    """
    stmt = select(ReviewQueueEntry).where(
        ReviewQueueEntry.tenant_id == tenant_id,
        ReviewQueueEntry.status == "pending",
    )
    if company:
        stmt = stmt.where(ReviewQueueEntry.company.ilike(f"%{company}%"))
    if keyword_in_title:
        stmt = stmt.where(ReviewQueueEntry.title.ilike(f"%{keyword_in_title}%"))

    candidates = list(session.execute(stmt).scalars().all())
    return bulk_reject(
        session,
        [c.id for c in candidates],
        reviewer=reviewer,
        reason=reason,
    )


__all__ = [
    "BulkResult",
    "CreateEntryArgs",
    "approve",
    "bulk_approve",
    "bulk_reject",
    "bulk_reject_by_filter",
    "create_entry",
    "get_entry",
    "list_entries",
    "mark_stale",
    "mark_submitted",
    "refresh_stale",
    "reject",
    "serialize_entry",
]
