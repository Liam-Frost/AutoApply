"""Phase 17.2 review queue package.

The review_queue table (Phase 17.2) holds applications awaiting human
approval; this package owns the state machine and the application-layer
helpers (``create_entry`` / ``approve`` / ``reject`` / ``mark_submitted``
/ ``list_entries`` / ``bulk_*``) the route handler + CLI consume.

Submission state transitions go through the Phase 17.5 pre-submit hard
gate; that lives in :mod:`src.review.pre_submit_gate` and is invoked by
the approve-and-submit path before flipping to ``"submitted"``.
"""

from src.review.state_machine import (
    ALLOWED_TRANSITIONS,
    REVIEW_STATUSES,
    InvalidTransitionError,
    ReviewStatus,
    is_valid_transition,
    next_status,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "REVIEW_STATUSES",
    "InvalidTransitionError",
    "ReviewStatus",
    "is_valid_transition",
    "next_status",
]
