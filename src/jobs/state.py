"""Phase 13.3: freshness state machine for ``job_postings.state``.

Centralizes the ``new -> active -> stale -> unknown -> expired -> archived``
lifecycle so callers (search flow, enrichment, scheduler, eviction) can't
each invent their own predicates and drift. Pure functions over data --
the caller decides when to load / persist the posting.

States
------
- ``new``      -- discovered in a search but not yet enriched with detail.
- ``active``   -- enriched within the recent window; safe to apply against.
- ``stale``    -- enriched-but-aging; should refresh before the next apply.
- ``unknown``  -- last refresh raised a transient error (auth bounce, 5xx);
                  we still have a snapshot but trust is degraded.
- ``expired``  -- the posting is gone from the source (404 / removed link).
- ``archived`` -- terminal; the eviction job moved an expired posting out
                  of the active working set.

Transition rules
----------------
The :data:`_TRANSITIONS` table is the source of truth. ``next_state`` is
a pure projection over (current_state, event); attempting an illegal
transition raises :class:`IllegalTransition` so a buggy caller doesn't
silently corrupt the posting lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

JobState = Literal["new", "active", "stale", "unknown", "expired", "archived"]

# Windows after which a posting transitions out of ``active``. These are
# the *default* freshness budgets; per-context overrides live in
# ``src/jobs/freshness.py`` (Phase 13.6) and the scheduler may tighten
# them for ``before_submit`` reads.
ACTIVE_TO_STALE_HOURS = 24
STALE_TO_UNKNOWN_HOURS = 72
UNKNOWN_TO_EXPIRED_HOURS = 7 * 24


class IllegalTransitionError(ValueError):
    """Raised when an event doesn't map to a valid transition from the current state."""


# Backwards-compat alias for tests written before the N818 cleanup.
IllegalTransition = IllegalTransitionError


# Events that drive the machine. Kept as a closed enum because every
# transition is hand-rolled below; "synthesizing" new events from
# callers would defeat the centralization goal.
Event = Literal[
    "enriched_ok",          # detail fetch succeeded; content is fresh
    "refresh_failed",       # transient failure (auth bounce, network, 5xx)
    "source_404",           # JD removed at the source
    "evict",                # eviction job sweeping expired -> archived
    "tick",                 # time advanced; recompute against the windows
]


@dataclass(frozen=True)
class TransitionResult:
    state: JobState
    reason: str


_TRANSITIONS: dict[tuple[JobState, Event], JobState] = {
    # Happy path: scrape succeeds.
    ("new", "enriched_ok"): "active",
    ("active", "enriched_ok"): "active",
    ("stale", "enriched_ok"): "active",
    ("unknown", "enriched_ok"): "active",
    ("expired", "enriched_ok"): "active",  # posting came back
    # Transient failures degrade trust but keep the cached snapshot usable.
    ("active", "refresh_failed"): "unknown",
    ("stale", "refresh_failed"): "unknown",
    ("new", "refresh_failed"): "unknown",
    ("unknown", "refresh_failed"): "unknown",
    # Terminal-at-source: the JD is gone.
    ("new", "source_404"): "expired",
    ("active", "source_404"): "expired",
    ("stale", "source_404"): "expired",
    ("unknown", "source_404"): "expired",
    # Eviction: only ``expired`` is evictable.
    ("expired", "evict"): "archived",
}


def next_state(current: JobState, event: Event) -> TransitionResult:
    """Apply an event to the current state. Raises on illegal pairs."""
    key = (current, event)
    if event == "tick":
        return _tick_only_reason(current)
    if key not in _TRANSITIONS:
        raise IllegalTransitionError(
            f"no transition from {current!r} on event {event!r}",
        )
    nxt = _TRANSITIONS[key]
    return TransitionResult(state=nxt, reason=f"{current}->{nxt} via {event}")


def _tick_only_reason(current: JobState) -> TransitionResult:
    # ``tick`` is a no-op at the schema level; the time-decay projection
    # lives in :func:`project_by_time`. Returning the current state keeps
    # the API uniform.
    return TransitionResult(state=current, reason=f"tick at {current}")


def project_by_time(
    current: JobState,
    *,
    last_checked_at: datetime | None,
    now: datetime | None = None,
    active_to_stale_hours: int = ACTIVE_TO_STALE_HOURS,
    stale_to_unknown_hours: int = STALE_TO_UNKNOWN_HOURS,
    unknown_to_expired_hours: int = UNKNOWN_TO_EXPIRED_HOURS,
) -> TransitionResult:
    """Pure time-decay projection used by the ``tick`` event.

    The scheduler's ``jd_health_check`` job (Phase 14.3) calls this for
    every non-archived posting, then writes the projected state back if
    it differs. We keep this separate from :func:`next_state` so a
    deterministic scheduler tick doesn't get tangled with caller-driven
    events.
    """
    if current in ("new", "expired", "archived"):
        return TransitionResult(state=current, reason=f"{current} not subject to time decay")
    if last_checked_at is None:
        return TransitionResult(state=current, reason="no last_checked_at; skipping decay")

    now = now or datetime.now(UTC)
    age = now - last_checked_at

    if current == "active" and age >= timedelta(hours=active_to_stale_hours):
        return TransitionResult(state="stale", reason=f"active->stale after {age}")
    if current == "stale" and age >= timedelta(hours=stale_to_unknown_hours):
        return TransitionResult(state="unknown", reason=f"stale->unknown after {age}")
    if current == "unknown" and age >= timedelta(hours=unknown_to_expired_hours):
        return TransitionResult(state="expired", reason=f"unknown->expired after {age}")
    return TransitionResult(state=current, reason=f"{current} within window ({age})")


def is_safe_to_apply(state: JobState) -> bool:
    """``active`` postings are safe to submit. ``stale`` should refresh first;
    ``unknown`` / ``expired`` / ``archived`` should never reach the submit step."""
    return state == "active"
