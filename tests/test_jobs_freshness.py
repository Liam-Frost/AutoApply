"""Phase 13.6: tests for the context-aware freshness predicate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from src.jobs.freshness import context_budget, should_refresh


@dataclass
class _Posting:
    state: str
    last_checked_at: datetime | None


def _ago(hours: float) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


@pytest.mark.parametrize(
    ("context", "expected_budget"),
    [("search_display", 72), ("generate_materials", 24), ("before_submit", 6)],
)
def test_context_budgets(context: str, expected_budget: int) -> None:
    assert context_budget(context) == expected_budget  # type: ignore[arg-type]


def test_unknown_context_raises() -> None:
    with pytest.raises(ValueError):
        should_refresh(_Posting(state="active", last_checked_at=_ago(1)), context="bogus")  # type: ignore[arg-type]


class TestSearchDisplay:
    def test_within_72h_is_fresh(self) -> None:
        v = should_refresh(_Posting("active", _ago(48)), context="search_display")
        assert v.should_refresh is False

    def test_beyond_72h_needs_refresh(self) -> None:
        v = should_refresh(_Posting("active", _ago(73)), context="search_display")
        assert v.should_refresh is True


class TestGenerateMaterials:
    def test_within_24h_is_fresh(self) -> None:
        v = should_refresh(_Posting("active", _ago(12)), context="generate_materials")
        assert v.should_refresh is False

    def test_beyond_24h_needs_refresh(self) -> None:
        v = should_refresh(_Posting("active", _ago(25)), context="generate_materials")
        assert v.should_refresh is True


class TestBeforeSubmit:
    def test_within_6h_is_fresh(self) -> None:
        v = should_refresh(_Posting("active", _ago(2)), context="before_submit")
        assert v.should_refresh is False

    def test_beyond_6h_needs_refresh(self) -> None:
        v = should_refresh(_Posting("active", _ago(7)), context="before_submit")
        assert v.should_refresh is True

    def test_stale_state_within_window_is_still_fresh(self) -> None:
        # State machine governs the lifecycle; per-context freshness
        # judges *time*. Stale-but-recently-checked is OK -- the state
        # itself signals "should refresh before next apply" elsewhere.
        v = should_refresh(_Posting("stale", _ago(1)), context="before_submit")
        assert v.should_refresh is False


class TestStateOverrides:
    @pytest.mark.parametrize("state", ["unknown", "expired", "archived"])
    def test_terminal_or_degraded_state_always_refreshes(self, state: str) -> None:
        v = should_refresh(_Posting(state, _ago(0.1)), context="search_display")
        assert v.should_refresh is True
        assert state in v.reason

    def test_new_state_always_refreshes(self) -> None:
        v = should_refresh(_Posting("new", _ago(0.1)), context="search_display")
        assert v.should_refresh is True
        assert "no snapshot" in v.reason

    def test_missing_last_checked_forces_refresh(self) -> None:
        v = should_refresh(_Posting("active", None), context="generate_materials")
        assert v.should_refresh is True


def test_dict_posting_supported() -> None:
    v = should_refresh(
        {"state": "active", "last_checked_at": _ago(3)},
        context="before_submit",
    )
    assert v.should_refresh is False


def test_age_hours_reported() -> None:
    v = should_refresh(_Posting("active", _ago(3)), context="before_submit")
    assert v.age_hours is not None
    assert 2.9 < v.age_hours < 3.1
    assert v.budget_hours == 6
