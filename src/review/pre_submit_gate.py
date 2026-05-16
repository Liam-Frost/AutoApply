"""Phase 17.5: pre-submit hard gate.

Every approve-and-submit path runs this gate BEFORE
``application.submit`` is allowed to fire. If the JD snapshot bound to
the review queue entry is stale enough that submitting would be
dangerous, the gate flips the entry to ``stale`` (so the kanban
re-surfaces it with a refresh affordance) and returns a structured
verdict the route handler can render.

Inputs come from two places:

* The review queue entry (``ReviewQueueEntry`` row + its ``job_id`` /
  ``job_snapshot_id``).
* The job posting + snapshot rows (Phase 13.2 ``JobPosting`` /
  ``JobSnapshot``) -- we ask :func:`src.jobs.freshness.should_refresh`
  with context=``"before_submit"`` (6h budget per the plan).

Outputs:

* ``allowed=True``  -- the submit path is cleared. Caller proceeds to
  ``mark_submitted`` + enqueue ``application.submit``.
* ``allowed=False, action="refresh"`` -- snapshot is stale; the gate
  did NOT auto-refresh (snapshot refresh is an I/O-heavy operation we
  don't want to do inside a submit click). The entry has been moved to
  ``"stale"`` and the kanban will surface a Refresh button which
  re-enqueues materials generation.
* ``allowed=False, action="expired"`` -- the posting is in a state
  that forbids submission entirely (``expired`` / ``archived``). The
  entry moves to ``"rejected"`` with a reason. This is terminal.
* ``allowed=False, action="missing_binding"`` -- the entry has no
  ``job_id`` (it was created in a search-only mode that never
  persisted a posting). Returned without mutating the entry; the UI
  surfaces "this entry is missing audit data" and prompts the
  operator to re-run materials generation.

The gate is intentionally narrow -- only freshness + lifecycle. The
Phase 4 / 9 HITL approval gate is unchanged and still fires AFTER
this gate clears (so the operator has one final confirmation before
the ATS form actually gets submitted).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.application.review import mark_stale, reject
from src.core.models import JobPosting, ReviewQueueEntry
from src.jobs.freshness import FreshnessVerdict, should_refresh

logger = logging.getLogger(__name__)


PreSubmitAction = Literal["allow", "refresh", "expired", "missing_binding"]


@dataclass
class PreSubmitGateResult:
    """Structured verdict the route handler / Celery task body
    consumes.

    Always present (no exceptions for normal verdicts) so the kanban
    can render a deterministic message. ``allowed=True`` iff
    ``action=="allow"``.
    """

    allowed: bool
    action: PreSubmitAction
    reason: str
    entry_id: str
    job_id: str | None
    job_snapshot_id: str | None
    freshness: FreshnessVerdict | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "action": self.action,
            "reason": self.reason,
            "entry_id": self.entry_id,
            "job_id": self.job_id,
            "job_snapshot_id": self.job_snapshot_id,
            "freshness": (
                {
                    "should_refresh": self.freshness.should_refresh,
                    "reason": self.freshness.reason,
                    "age_hours": self.freshness.age_hours,
                    "budget_hours": self.freshness.budget_hours,
                }
                if self.freshness
                else None
            ),
            "notes": list(self.notes),
        }


# Lifecycle states that forbid submission outright (matches the
# ``_FORCE_REFRESH_STATES`` set in :mod:`src.jobs.freshness` but with a
# different semantic: there, an ``expired`` posting forces a refresh;
# here, expired/archived block submission permanently).
_TERMINAL_POSTING_STATES = frozenset({"expired", "archived"})


def run_pre_submit_gate(
    session: Session,
    entry_id: uuid.UUID | str,
    *,
    now: datetime | None = None,
    auto_mutate: bool = True,
) -> PreSubmitGateResult:
    """Evaluate the pre-submit gate for one review queue entry.

    Args:
        session: open SQLAlchemy session. The function does NOT commit;
            the caller is responsible (so a submit route can wrap the
            gate + ``mark_submitted`` + the application.submit enqueue
            in one transaction).
        entry_id: the review queue row to gate. Must already be in
            ``status="approved"`` for the gate to fire -- pending
            entries get an immediate ``missing_binding`` (approval
            was a precondition).
        now: clock injection for tests.
        auto_mutate: when True (default), the gate flips the entry to
            ``stale`` / ``rejected`` as appropriate. When False, the
            gate only computes the verdict; the caller can choose to
            apply the state change. Useful for read-only "would this
            submit?" probes from the kanban.

    Returns: :class:`PreSubmitGateResult`. The caller must commit the
    session if ``auto_mutate=True``.
    """
    entry = session.get(ReviewQueueEntry, _coerce_uuid(entry_id))
    if entry is None:
        return PreSubmitGateResult(
            allowed=False,
            action="missing_binding",
            reason=f"review entry {entry_id!r} not found",
            entry_id=str(entry_id),
            job_id=None,
            job_snapshot_id=None,
        )

    # Approval is a hard precondition for this gate; the plan's
    # "approve-and-submit" affordance only fires after Approve.
    if entry.status != "approved":
        return PreSubmitGateResult(
            allowed=False,
            action="missing_binding",
            reason=(
                f"entry status is {entry.status!r}; pre-submit gate requires 'approved'"
            ),
            entry_id=str(entry.id),
            job_id=str(entry.job_id) if entry.job_id else None,
            job_snapshot_id=(
                str(entry.job_snapshot_id) if entry.job_snapshot_id else None
            ),
        )

    if entry.job_id is None:
        return PreSubmitGateResult(
            allowed=False,
            action="missing_binding",
            reason="review entry has no job_id; re-run materials generation",
            entry_id=str(entry.id),
            job_id=None,
            job_snapshot_id=(
                str(entry.job_snapshot_id) if entry.job_snapshot_id else None
            ),
        )

    posting = (
        session.execute(select(JobPosting).where(JobPosting.id == entry.job_id))
        .scalars()
        .first()
    )
    if posting is None:
        # Job posting row has been purged (retention) but the review
        # entry still points at the id. Treat as missing_binding --
        # the user needs to re-run materials generation.
        return PreSubmitGateResult(
            allowed=False,
            action="missing_binding",
            reason="job posting row not found; re-run materials generation",
            entry_id=str(entry.id),
            job_id=str(entry.job_id),
            job_snapshot_id=(
                str(entry.job_snapshot_id) if entry.job_snapshot_id else None
            ),
        )

    if posting.state in _TERMINAL_POSTING_STATES:
        # Expired or archived -- submission must not proceed.
        if auto_mutate:
            reject(
                session,
                entry.id,
                reviewer="pre_submit_gate",
                reason=f"posting state={posting.state} forbids submission",
            )
        return PreSubmitGateResult(
            allowed=False,
            action="expired",
            reason=f"posting state={posting.state}",
            entry_id=str(entry.id),
            job_id=str(entry.job_id),
            job_snapshot_id=(
                str(entry.job_snapshot_id) if entry.job_snapshot_id else None
            ),
            notes=[f"posting.state={posting.state}"],
        )

    # Phase 13.6 freshness predicate at the "before_submit" budget (6h).
    freshness = should_refresh(posting, context="before_submit", now=now)
    if freshness.should_refresh:
        if auto_mutate:
            mark_stale(
                session,
                entry.id,
                reason=f"snapshot stale at submit time: {freshness.reason}",
            )
        return PreSubmitGateResult(
            allowed=False,
            action="refresh",
            reason=f"snapshot stale: {freshness.reason}",
            entry_id=str(entry.id),
            job_id=str(entry.job_id),
            job_snapshot_id=(
                str(entry.job_snapshot_id) if entry.job_snapshot_id else None
            ),
            freshness=freshness,
        )

    # All checks cleared.
    return PreSubmitGateResult(
        allowed=True,
        action="allow",
        reason=f"snapshot fresh: {freshness.reason}",
        entry_id=str(entry.id),
        job_id=str(entry.job_id),
        job_snapshot_id=(
            str(entry.job_snapshot_id) if entry.job_snapshot_id else None
        ),
        freshness=freshness,
    )


def _coerce_uuid(value: uuid.UUID | str) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


__all__ = [
    "PreSubmitAction",
    "PreSubmitGateResult",
    "run_pre_submit_gate",
]
