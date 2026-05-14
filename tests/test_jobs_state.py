"""Phase 13.3: tests for the freshness state machine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.jobs.state import (
    ACTIVE_TO_STALE_HOURS,
    STALE_TO_UNKNOWN_HOURS,
    UNKNOWN_TO_EXPIRED_HOURS,
    IllegalTransition,
    is_safe_to_apply,
    next_state,
    project_by_time,
)


class TestNextState:
    def test_new_to_active_on_enrichment(self) -> None:
        assert next_state("new", "enriched_ok").state == "active"

    def test_active_stays_active_on_enrichment(self) -> None:
        assert next_state("active", "enriched_ok").state == "active"

    def test_stale_recovers_to_active(self) -> None:
        assert next_state("stale", "enriched_ok").state == "active"

    def test_unknown_recovers_to_active(self) -> None:
        assert next_state("unknown", "enriched_ok").state == "active"

    def test_expired_can_come_back(self) -> None:
        # A posting that was 404 may reappear (LinkedIn re-list, ATS
        # un-archive). Recovery is allowed.
        assert next_state("expired", "enriched_ok").state == "active"

    def test_refresh_failure_degrades_to_unknown(self) -> None:
        assert next_state("active", "refresh_failed").state == "unknown"
        assert next_state("stale", "refresh_failed").state == "unknown"
        assert next_state("unknown", "refresh_failed").state == "unknown"

    def test_source_404_marks_expired(self) -> None:
        for s in ("new", "active", "stale", "unknown"):
            assert next_state(s, "source_404").state == "expired"

    def test_only_expired_is_evictable(self) -> None:
        assert next_state("expired", "evict").state == "archived"
        with pytest.raises(IllegalTransition):
            next_state("active", "evict")
        with pytest.raises(IllegalTransition):
            next_state("stale", "evict")
        with pytest.raises(IllegalTransition):
            next_state("unknown", "evict")

    def test_archived_is_terminal(self) -> None:
        with pytest.raises(IllegalTransition):
            next_state("archived", "enriched_ok")
        with pytest.raises(IllegalTransition):
            next_state("archived", "refresh_failed")

    def test_tick_is_a_noop_at_event_level(self) -> None:
        for s in ("new", "active", "stale", "unknown", "expired", "archived"):
            assert next_state(s, "tick").state == s


class TestProjectByTime:
    def _at(self, hours_ago: int) -> datetime:
        return datetime.now(UTC) - timedelta(hours=hours_ago)

    def test_active_within_window_stays_active(self) -> None:
        out = project_by_time("active", last_checked_at=self._at(1))
        assert out.state == "active"

    def test_active_decays_to_stale(self) -> None:
        out = project_by_time("active", last_checked_at=self._at(ACTIVE_TO_STALE_HOURS + 1))
        assert out.state == "stale"

    def test_stale_decays_to_unknown(self) -> None:
        out = project_by_time("stale", last_checked_at=self._at(STALE_TO_UNKNOWN_HOURS + 1))
        assert out.state == "unknown"

    def test_unknown_decays_to_expired(self) -> None:
        out = project_by_time("unknown", last_checked_at=self._at(UNKNOWN_TO_EXPIRED_HOURS + 1))
        assert out.state == "expired"

    def test_new_is_not_subject_to_time_decay(self) -> None:
        out = project_by_time("new", last_checked_at=self._at(10_000))
        assert out.state == "new"

    def test_expired_and_archived_are_terminal_for_decay(self) -> None:
        assert project_by_time("expired", last_checked_at=self._at(10_000)).state == "expired"
        assert project_by_time("archived", last_checked_at=self._at(10_000)).state == "archived"

    def test_missing_last_checked_at_keeps_state(self) -> None:
        out = project_by_time("active", last_checked_at=None)
        assert out.state == "active"


class TestSafetyPredicate:
    def test_only_active_is_safe(self) -> None:
        assert is_safe_to_apply("active") is True
        for s in ("new", "stale", "unknown", "expired", "archived"):
            assert is_safe_to_apply(s) is False  # type: ignore[arg-type]
