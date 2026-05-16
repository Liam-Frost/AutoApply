"""Phase 17.2: review queue state machine.

Five terminal-or-intermediate states, deliberately small so the kanban
board has fixed columns:

* ``pending``   -- created by ``application.prepare``; waiting for the
                   operator.
* ``approved``  -- operator has clicked Approve; the entry is now
                   queueable for ``application.fill`` / ``submit``.
* ``submitted`` -- ``application.submit`` succeeded (passing through
                   the Phase 17.5 pre-submit hard gate first).
* ``rejected``  -- operator declined. Terminal.
* ``stale``     -- Phase 17.5 gate found the snapshot expired or > 6h
                   stale and could not refresh in time. The entry
                   returns to the UI with a refresh-or-discard prompt.

Allowed transitions, declared as a frozen dict so callers can compare
their own transition rules to the canonical one without monkey-patching::

    pending   -> approved | rejected | stale
    approved  -> submitted | rejected | stale
    stale     -> pending | rejected
    submitted -> (terminal)
    rejected  -> (terminal)

The Phase 17.3 kanban board treats ``submitted`` + ``rejected`` as
terminal columns (no quick-action buttons); ``stale`` is rendered with
a refresh affordance that re-enqueues the materials task.
"""

from __future__ import annotations

from typing import Literal

ReviewStatus = Literal["pending", "approved", "submitted", "rejected", "stale"]


REVIEW_STATUSES: tuple[ReviewStatus, ...] = (
    "pending",
    "approved",
    "submitted",
    "rejected",
    "stale",
)


# Canonical adjacency map. Read-only by convention -- consumers should
# call :func:`is_valid_transition` rather than mutating this directly.
ALLOWED_TRANSITIONS: dict[ReviewStatus, frozenset[ReviewStatus]] = {
    "pending": frozenset({"approved", "rejected", "stale"}),
    "approved": frozenset({"submitted", "rejected", "stale"}),
    "stale": frozenset({"pending", "rejected"}),
    "submitted": frozenset(),
    "rejected": frozenset(),
}


# Statuses that the kanban renders as terminal (no action buttons).
TERMINAL_STATUSES: frozenset[ReviewStatus] = frozenset({"submitted", "rejected"})


class InvalidTransitionError(ValueError):
    """Raised when a caller asks for a transition the state machine
    refuses (e.g. ``submitted → pending``).

    Carries the source + target so the route handler can render a
    helpful 409 body."""

    def __init__(self, src: str, dst: str) -> None:
        super().__init__(f"Invalid review_queue transition: {src!r} -> {dst!r}")
        self.src = src
        self.dst = dst


def is_valid_transition(src: str, dst: str) -> bool:
    """Return True iff ``src -> dst`` is in :data:`ALLOWED_TRANSITIONS`.

    Unknown statuses (e.g. a typo) always return False; this keeps the
    function safe for use as a guard in route handlers that haven't yet
    validated their input.
    """
    if src not in ALLOWED_TRANSITIONS:
        return False
    return dst in ALLOWED_TRANSITIONS[src]


def next_status(src: str, dst: str) -> ReviewStatus:
    """Assert the transition is allowed and return the new status.

    Raises :class:`InvalidTransitionError` on disallowed edges. The
    point of having both this and :func:`is_valid_transition` is the
    distinction between "guard a UI button" (predicate) and "apply a
    decision atomically" (raises on bad input).
    """
    if not is_valid_transition(src, dst):
        raise InvalidTransitionError(src, dst)
    return dst  # type: ignore[return-value]


__all__ = [
    "ALLOWED_TRANSITIONS",
    "InvalidTransitionError",
    "REVIEW_STATUSES",
    "ReviewStatus",
    "TERMINAL_STATUSES",
    "is_valid_transition",
    "next_status",
]
