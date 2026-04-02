"""Application state machine.

Models each job application as a finite state machine with defined transitions.
Every state change is logged for audit trail and recovery.

States:
    DISCOVERED → QUALIFIED → MATERIALS_READY → FORM_OPENED
    → FIELDS_MAPPED → FILES_UPLOADED → QUESTIONS_ANSWERED
    → REVIEW_REQUIRED → SUBMITTED

    Error states: FAILED, NEEDS_RETRY (reachable from any active state)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

logger = logging.getLogger("autoapply.core.state_machine")


class AppStatus(StrEnum):
    """Application lifecycle states."""

    DISCOVERED = "DISCOVERED"
    QUALIFIED = "QUALIFIED"
    MATERIALS_READY = "MATERIALS_READY"
    FORM_OPENED = "FORM_OPENED"
    FIELDS_MAPPED = "FIELDS_MAPPED"
    FILES_UPLOADED = "FILES_UPLOADED"
    QUESTIONS_ANSWERED = "QUESTIONS_ANSWERED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SUBMITTED = "SUBMITTED"
    FAILED = "FAILED"
    NEEDS_RETRY = "NEEDS_RETRY"


# Valid forward transitions (excluding error transitions which are always allowed)
_TRANSITIONS: dict[AppStatus, set[AppStatus]] = {
    AppStatus.DISCOVERED: {AppStatus.QUALIFIED},
    AppStatus.QUALIFIED: {AppStatus.MATERIALS_READY},
    AppStatus.MATERIALS_READY: {AppStatus.FORM_OPENED},
    AppStatus.FORM_OPENED: {AppStatus.FIELDS_MAPPED},
    AppStatus.FIELDS_MAPPED: {AppStatus.FILES_UPLOADED},
    AppStatus.FILES_UPLOADED: {AppStatus.QUESTIONS_ANSWERED},
    AppStatus.QUESTIONS_ANSWERED: {AppStatus.REVIEW_REQUIRED, AppStatus.SUBMITTED},
    AppStatus.REVIEW_REQUIRED: {AppStatus.SUBMITTED},
    AppStatus.NEEDS_RETRY: {AppStatus.FORM_OPENED, AppStatus.MATERIALS_READY},
}

# These states can be reached from any active (non-terminal) state
_ERROR_TARGETS = {AppStatus.FAILED, AppStatus.NEEDS_RETRY}

# Terminal states — no further transitions allowed
_TERMINAL = {AppStatus.SUBMITTED, AppStatus.FAILED}


class InvalidTransition(Exception):
    """Raised when attempting an invalid state transition."""


class ApplicationState:
    """Tracks the state of a single job application.

    Attributes:
        job_id: UUID of the target job.
        status: Current application status.
        history: List of (timestamp, from_status, to_status, metadata) tuples.
        metadata: Arbitrary data attached to the current state.
    """

    def __init__(self, job_id: str, status: AppStatus = AppStatus.DISCOVERED):
        self.job_id = job_id
        self.status = status
        self.history: list[dict[str, Any]] = []
        self.metadata: dict[str, Any] = {}
        self._record_event("INIT", None, status)

    def transition(self, target: AppStatus, **meta: Any) -> None:
        """Transition to a new state.

        Args:
            target: The target state.
            **meta: Arbitrary metadata to attach (e.g., error message, screenshot path).

        Raises:
            InvalidTransition: If the transition is not allowed.
        """
        if not self.can_transition(target):
            raise InvalidTransition(
                f"Cannot transition from {self.status} to {target} "
                f"(job_id={self.job_id})"
            )

        old = self.status
        self.status = target
        self.metadata.update(meta)
        self._record_event("TRANSITION", old, target, meta)

        logger.info(
            "[%s] %s → %s%s",
            self.job_id[:8], old, target,
            f" ({meta})" if meta else "",
        )

    def can_transition(self, target: AppStatus) -> bool:
        """Check if a transition to the target state is valid."""
        if self.status in _TERMINAL:
            return False

        # Error transitions are always allowed from non-terminal states
        if target in _ERROR_TARGETS:
            return True

        allowed = _TRANSITIONS.get(self.status, set())
        return target in allowed

    def fail(self, error: str, **meta: Any) -> None:
        """Shortcut to transition to FAILED state."""
        self.transition(AppStatus.FAILED, error=error, **meta)

    def retry(self, reason: str = "", **meta: Any) -> None:
        """Shortcut to transition to NEEDS_RETRY state."""
        self.transition(AppStatus.NEEDS_RETRY, retry_reason=reason, **meta)

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL

    @property
    def is_active(self) -> bool:
        return not self.is_terminal

    def _record_event(
        self,
        event_type: str,
        from_status: AppStatus | None,
        to_status: AppStatus,
        meta: dict | None = None,
    ) -> None:
        self.history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "from": str(from_status) if from_status else None,
            "to": str(to_status),
            "meta": meta or {},
        })

    def to_dict(self) -> dict[str, Any]:
        """Serialize state for DB persistence."""
        return {
            "job_id": self.job_id,
            "status": str(self.status),
            "history": self.history,
            "metadata": self.metadata,
        }
