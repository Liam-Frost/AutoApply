"""Phase 12.6 -- ``src.application.cache`` use case tests.

Exercises the snapshot and clear paths against a fakeredis-backed
cache so we cover the SCAN counting + clear semantics without
needing a real Redis daemon.
"""

from __future__ import annotations

from unittest.mock import patch

import fakeredis
import pytest

from src.application.cache import (
    _DEFAULT_COST_PER_HIT_USD,
    cache_snapshot,
    clear_cache_namespace,
)
from src.cache.cache import Cache, reset_cache
from src.cache.connection import RedisHealth
from src.cache.lru import LRUBackend
from src.cache.redis_backend import RedisBackend


@pytest.fixture(autouse=True)
def _cleanup_cache():
    reset_cache()
    yield
    reset_cache()


@pytest.fixture
def fake_client() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def cache_with_l2(fake_client: fakeredis.FakeRedis) -> Cache:
    return Cache(l1=LRUBackend(), l2=RedisBackend(fake_client))


class TestSnapshot:
    def test_snapshot_with_no_keys(
        self, cache_with_l2: Cache, fake_client: fakeredis.FakeRedis
    ) -> None:
        with (
            patch("src.application.cache.get_cache", return_value=cache_with_l2),
            patch(
                "src.application.cache.redis_health",
                return_value=RedisHealth(
                    ok=True,
                    url="redis://localhost:6379/0",
                    detail="PONG",
                    latency_ms=2,
                ),
            ),
            patch(
                "src.application.cache.get_redis_client",
                return_value=fake_client,
            ),
        ):
            snap = cache_snapshot()
        assert snap["ok"] is True
        assert snap["redis"]["ok"] is True
        assert snap["l2_available"] is True
        # Every documented namespace shows up with 0 entries.
        for ns in snap["namespaces"]:
            assert ns["entries"] == 0
        # No hits yet -> nothing saved.
        assert snap["estimated_dollars_saved"] == 0.0

    def test_snapshot_counts_keys_per_namespace(
        self, cache_with_l2: Cache, fake_client: fakeredis.FakeRedis
    ) -> None:
        cache_with_l2.set("llm", "a", "x")
        cache_with_l2.set("llm", "b", "y")
        cache_with_l2.set("embedding", "c", [0.1])
        with (
            patch("src.application.cache.get_cache", return_value=cache_with_l2),
            patch(
                "src.application.cache.redis_health",
                return_value=RedisHealth(
                    ok=True, url="x", detail="PONG", latency_ms=1
                ),
            ),
            patch(
                "src.application.cache.get_redis_client",
                return_value=fake_client,
            ),
        ):
            snap = cache_snapshot()
        ns_by_name = {n["name"]: n for n in snap["namespaces"]}
        assert ns_by_name["llm"]["entries"] == 2
        assert ns_by_name["embedding"]["entries"] == 1
        assert ns_by_name["response"]["entries"] == 0

    def test_snapshot_dollars_saved_uses_hit_count(
        self, cache_with_l2: Cache, fake_client: fakeredis.FakeRedis
    ) -> None:
        # Populate then read three times to drive hits_l1 = 3.
        cache_with_l2.set("llm", "k", "v")
        for _ in range(3):
            cache_with_l2.get("llm", "k")
        with (
            patch("src.application.cache.get_cache", return_value=cache_with_l2),
            patch(
                "src.application.cache.redis_health",
                return_value=RedisHealth(
                    ok=True, url="x", detail="PONG", latency_ms=1
                ),
            ),
            patch(
                "src.application.cache.get_redis_client",
                return_value=fake_client,
            ),
        ):
            snap = cache_snapshot()
        # 3 hits * default rate; rounding tolerance via `==` because
        # the rate is constant.
        expected = round(3 * _DEFAULT_COST_PER_HIT_USD, 4)
        assert snap["estimated_dollars_saved"] == expected

    def test_snapshot_with_redis_down_returns_none_counts(self) -> None:
        l1_only = Cache(l1=LRUBackend(), l2=None)
        with (
            patch("src.application.cache.get_cache", return_value=l1_only),
            patch(
                "src.application.cache.redis_health",
                return_value=RedisHealth(
                    ok=False, url="redis://localhost:6379/0", detail="refused"
                ),
            ),
            patch(
                "src.application.cache.get_redis_client", return_value=None
            ),
        ):
            snap = cache_snapshot()
        assert snap["redis"]["ok"] is False
        assert snap["l2_available"] is False
        for ns in snap["namespaces"]:
            # ``None`` (not -1) when L2 is unavailable -- L1 is not
            # authoritative for the "world view".
            assert ns["entries"] is None


class TestClearNamespace:
    def test_clear_drops_all_entries_in_namespace(
        self,
        cache_with_l2: Cache,
        fake_client: fakeredis.FakeRedis,
    ) -> None:
        cache_with_l2.set("llm", "a", "x")
        cache_with_l2.set("llm", "b", "y")
        cache_with_l2.set("embedding", "c", [0.1])
        # The use case drives its own SCAN+DEL via get_redis_client so
        # it can surface failures cleanly; patch it to the same fake
        # client backing the cache's L2.
        with (
            patch("src.application.cache.get_cache", return_value=cache_with_l2),
            patch(
                "src.application.cache.get_redis_client",
                return_value=fake_client,
            ),
        ):
            result = clear_cache_namespace("llm")
        assert result["ok"] is True
        assert result["deleted"] == 2
        # llm cleared, embedding intact.
        assert cache_with_l2.get("llm", "a") is None
        assert cache_with_l2.get("embedding", "c") == [0.1]

    def test_clear_rejects_glob_namespace(self) -> None:
        result = clear_cache_namespace("*")
        assert result["ok"] is False
        assert result["error_code"] == "invalid_namespace"

    def test_clear_rejects_empty_namespace(self) -> None:
        result = clear_cache_namespace("")
        assert result["ok"] is False
        assert result["error_code"] == "invalid_namespace"

    def test_clear_propagates_l1_clear_failure(self) -> None:
        """Belt-and-braces: even if the L1 ``clear_namespace`` (which
        is unlikely to fail under normal conditions) raises, the
        clear must surface as ``clear_failed`` rather than silently
        succeed."""

        class BoomL1:
            def clear_namespace(self, *_a, **_kw):
                raise RuntimeError("L1 exploded")

        class CacheWithBoomL1:
            _l1 = BoomL1()
            l2_available = False

        with (
            patch("src.application.cache.get_cache", return_value=CacheWithBoomL1()),
            patch("src.application.cache.get_redis_client", return_value=None),
        ):
            result = clear_cache_namespace("llm")
        assert result["ok"] is False
        assert result["error_code"] == "clear_failed"
        assert "L1 exploded" in result["error"]

    def test_l2_attached_but_client_none_reports_failure(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        """Codex review P2 regression: if the cache singleton had L2
        attached (so the snapshot probably showed Redis healthy
        moments ago) but ``get_redis_client`` now returns ``None``
        because Redis dropped, the clear must NOT return ``ok=True``
        with L1-only cleanup -- stale L2 entries would come back when
        Redis recovers."""
        cache = Cache(l1=LRUBackend(), l2=RedisBackend(fake_client))
        # Pre-populate to make the test scenario concrete.
        cache.set("llm", "a", "x")

        with (
            patch("src.application.cache.get_cache", return_value=cache),
            patch("src.application.cache.get_redis_client", return_value=None),
        ):
            result = clear_cache_namespace("llm")
        assert result["ok"] is False
        assert result["error_code"] == "clear_failed"
        assert "unreachable" in result["error"].lower()

    def test_attached_l2_clear_propagates_redis_failure(
        self, cache_with_l2: Cache
    ) -> None:
        """Codex review P2 regression: even when L2 IS attached, a
        SCAN failure during clear must surface as ``clear_failed``.
        ``RedisBackend.clear_namespace`` swallows ``RedisError``
        internally, so we drive the L2 clear directly through the
        use case's own SCAN+DEL path and let exceptions propagate."""

        class BrokenClient:
            def scan(self, *_a, **_kw):
                raise RuntimeError("scan blew up under L2")

        with (
            patch("src.application.cache.get_cache", return_value=cache_with_l2),
            patch(
                "src.application.cache.get_redis_client",
                return_value=BrokenClient(),
            ),
        ):
            result = clear_cache_namespace("llm")
        assert result["ok"] is False
        assert result["error_code"] == "clear_failed"

    def test_clear_propagates_redis_failure_when_l1_only(self) -> None:
        """Codex review P2 regression: when the cache singleton is
        L1-only AND the operator-visible Redis snapshot relies on
        the direct SCAN/DEL path, a SCAN failure must surface as
        ``clear_failed`` -- otherwise the UI would show "Cleared 0"
        while every entry is still in Redis."""

        class BrokenClient:
            def scan(self, *_a, **_kw):
                raise RuntimeError("scan blew up")

        l1_only = Cache(l1=LRUBackend(), l2=None)
        with (
            patch("src.application.cache.get_cache", return_value=l1_only),
            patch(
                "src.application.cache.get_redis_client",
                return_value=BrokenClient(),
            ),
        ):
            result = clear_cache_namespace("llm")
        assert result["ok"] is False
        assert result["error_code"] == "clear_failed"
        assert "scan blew up" in result["error"]

    def test_clear_falls_back_to_direct_redis_when_l2_unattached(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        """Codex review P2 regression: if the cache singleton is
        L1-only because Redis was down at boot, ``invalidate`` only
        clears L1. The clear use-case must ALSO do a direct
        SCAN+DEL against the current Redis client so the operator's
        click actually empties what the snapshot showed."""
        # Seed Redis directly -- the orchestrator never wrote here.
        fake_client.setex("v1:llm:a", 60, '"x"')
        fake_client.setex("v1:llm:b", 60, '"y"')
        fake_client.setex("v1:embedding:c", 60, '"z"')

        # Cache singleton has NO L2 -- mirrors the down-at-boot state.
        l1_only = Cache(l1=LRUBackend(), l2=None)

        with (
            patch("src.application.cache.get_cache", return_value=l1_only),
            patch(
                "src.application.cache.get_redis_client",
                return_value=fake_client,
            ),
        ):
            result = clear_cache_namespace("llm")
        assert result["ok"] is True
        # Direct Redis cleanup ran and deleted the seeded keys.
        assert result["deleted"] == 2
        assert not fake_client.exists("v1:llm:a")
        assert not fake_client.exists("v1:llm:b")
        # Other namespace untouched.
        assert fake_client.exists("v1:embedding:c")
