"""Phase 13.6: context-aware freshness predicate.

Different read sites tolerate different staleness:

  * ``search_display``    -- the Jobs page can show 72h-old rows; the
                             user is browsing.
  * ``generate_materials`` -- resume / cover-letter generation needs a
                             24h-fresh JD because the agent will quote
                             from it.
  * ``before_submit``     -- the pre-submit gate must see a 6h-fresh
                             JD; we don't want to fire an application
                             at a posting that was edited yesterday.

``should_refresh(posting, context, now=)`` returns a (bool, reason)
pair so callers can both gate behaviour AND surface "why" to the UI
or the trace store.

This is the *single* predicate the rest of the codebase should call
when asking "should I re-scrape this?". Ad-hoc TTL math sprinkled
across the call sites was exactly the drift we wanted to centralise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Mapping

FreshnessContext = Literal["search_display", "generate_materials", "before_submit"]

# (hours, human-readable label) so the UI can render the budget too.
_CONTEXT_BUDGETS: dict[FreshnessContext, tuple[int, str]] = {
    "search_display": (72, "72h"),
    "generate_materials": (24, "24h"),
    "before_submit": (6, "6h"),
}

# Postings in these states always force a refresh regardless of context;
# we will not generate materials against an unknown JD and we will not
# submit against an expired one.
_FORCE_REFRESH_STATES = frozenset({"unknown", "expired", "archived"})

# Postings in ``new`` have no snapshot yet -- ``before_submit`` should
# never see one of these. We surface that as a "force refresh" so
# callers don't proceed.
_STATES_WITHOUT_SNAPSHOT = frozenset({"new"})


@dataclass
class FreshnessVerdict:
    should_refresh: bool
    reason: str
    age_hours: float | None
    budget_hours: int


def context_budget(context: FreshnessContext) -> int:
    return _CONTEXT_BUDGETS[context][0]


def should_refresh(
    posting: Any,
    *,
    context: FreshnessContext,
    now: datetime | None = None,
) -> FreshnessVerdict:
    """Return a verdict on whether ``posting`` needs a fresh scrape.

    ``posting`` is duck-typed: only ``state`` and ``last_checked_at``
    are inspected. Pass an ORM ``JobPosting`` row, a dataclass, or a
    plain dict via ``MappingPosting`` (below).
    """
    if context not in _CONTEXT_BUDGETS:
        raise ValueError(f"unknown freshness context: {context!r}")
    budget_hours, _label = _CONTEXT_BUDGETS[context]
    now = now or datetime.now(UTC)

    state = _get(posting, "state")
    last_checked_at: datetime | None = _get(posting, "last_checked_at")

    if state in _STATES_WITHOUT_SNAPSHOT:
        return FreshnessVerdict(
            should_refresh=True,
            reason=f"state={state} has no snapshot yet",
            age_hours=None,
            budget_hours=budget_hours,
        )
    if state in _FORCE_REFRESH_STATES:
        return FreshnessVerdict(
            should_refresh=True,
            reason=f"state={state}",
            age_hours=None,
            budget_hours=budget_hours,
        )

    if last_checked_at is None:
        return FreshnessVerdict(
            should_refresh=True,
            reason="no last_checked_at",
            age_hours=None,
            budget_hours=budget_hours,
        )

    age = now - last_checked_at
    age_hours = age.total_seconds() / 3600.0
    if age >= timedelta(hours=budget_hours):
        return FreshnessVerdict(
            should_refresh=True,
            reason=f"age {age_hours:.1f}h >= budget {budget_hours}h ({context})",
            age_hours=age_hours,
            budget_hours=budget_hours,
        )
    return FreshnessVerdict(
        should_refresh=False,
        reason=f"age {age_hours:.1f}h < budget {budget_hours}h ({context})",
        age_hours=age_hours,
        budget_hours=budget_hours,
    )


def _get(posting: Any, attr: str) -> Any:
    if isinstance(posting, Mapping):
        return posting.get(attr)
    return getattr(posting, attr, None)
