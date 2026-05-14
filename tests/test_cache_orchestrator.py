"""Phase 12.1 -- Cache orchestrator tests.

Covers the contract the rest of the codebase will rely on:
namespace TTL, version-stamped keys, L1+L2 routing, L2 graceful
degrade, and the hit/miss counters surfaced to the cost dashboard.
"""

from __future__ import annotations

from typing import Any

import fakeredis
import pytest

from src.cache.base import CACHE_VERSION, NAMESPACE_TTLS
from src.cache.cache import Cache, get_cache, reset_cache
from src.cache.lru import LRUBackend
from src.cache.redis_backend import RedisBackend


def _orchestrator_with_fakeredis() -> tuple[Cache, fakeredis.FakeRedis]:
    fake = fakeredis.FakeRedis(decode_responses=True)
    return Cache(l1=LRUBackend(), l2=RedisBackend(fake)), fake


class TestKeyComposition:
    def test_keys_are_version_namespace_keyed(self) -> None:
        """The orchestrator must compose ``{version}:{ns}:{key}`` so
        bumping ``CACHE_VERSION`` invalidates the keyspace."""
        cache, fake = _orchestrator_with_fakeredis()
        cache.set("llm", "abc", {"v": 1})
        assert fake.exists(f"{CACHE_VERSION}:llm:abc")

    def test_different_namespaces_do_not_collide(self) -> None:
        cache, fake = _orchestrator_with_fakeredis()
        cache.set("llm", "k", "from-llm")
        cache.set("embedding", "k", "from-embedding")
        assert cache.get("llm", "k") == "from-llm"
        assert cache.get("embedding", "k") == "from-embedding"


class TestTTLPolicy:
    def test_namespace_ttl_is_applied(self) -> None:
        """``cache.set`` must use the policy TTL, not a caller-supplied
        one (the policy table is the only knob)."""
        cache, fake = _orchestrator_with_fakeredis()
        cache.set("llm", "k", "v")
        remaining = fake.ttl(f"{CACHE_VERSION}:llm:k")
        # Allow some slack for fakeredis clock.
        assert NAMESPACE_TTLS["llm"] - 5 <= remaining <= NAMESPACE_TTLS["llm"]

    def test_unknown_namespace_uses_default_ttl(self) -> None:
        cache, fake = _orchestrator_with_fakeredis()
        cache.set("custom_ns", "k", "v")
        remaining = fake.ttl(f"{CACHE_VERSION}:custom_ns:k")
        # Default is short by design (see base.DEFAULT_NAMESPACE_TTL).
        # Just assert it's nonzero and finite.
        assert remaining > 0
        assert remaining < NAMESPACE_TTLS["llm"]


class TestL1AndL2Routing:
    def test_l1_hit_does_not_query_l2(self) -> None:
        """An L1 hit must short-circuit so we don't pay an L2 round
        trip on hot keys."""
        l2 = LRUBackend()
        cache = Cache(l1=LRUBackend(), l2=l2)
        cache.set("llm", "k", "v")
        # Delete from L2 directly to prove L2 isn't queried.
        from src.cache.base import make_key

        l2.delete(make_key("llm", "k"))
        assert cache.get("llm", "k") == "v"
        stats = cache.stats()
        assert stats["hits_l1"] == 1
        assert stats["hits_l2"] == 0

    def test_l2_hit_promotes_into_l1(self) -> None:
        """If L1 missed but L2 hit, the next read should be L1."""
        l1 = LRUBackend()
        l2_backing = LRUBackend()
        cache = Cache(l1=l1, l2=l2_backing)
        # Bypass write-through: stuff a value directly into L2 only.
        from src.cache.base import make_key

        l2_backing.set(make_key("llm", "k"), "v", ttl=NAMESPACE_TTLS["llm"])
        # First read: L1 miss, L2 hit -> promotes into L1.
        assert cache.get("llm", "k") == "v"
        # Now break L2 to prove the next read came from L1.
        l2_backing.delete(make_key("llm", "k"))
        assert cache.get("llm", "k") == "v"

    def test_l1_promotion_uses_remaining_ttl(self) -> None:
        """Codex review P2 regression: an L2 entry near expiry must
        not be promoted into L1 with a fresh full-namespace TTL --
        otherwise the process can serve the value for another full
        window after Redis dropped it. The orchestrator must respect
        the remaining TTL ``get_with_ttl`` reports."""
        from src.cache.base import make_key

        class StubL2:
            """L2 that claims a tiny remaining TTL on a value."""

            def __init__(self) -> None:
                self.stored: dict[str, Any] = {}

            def get(self, key: str) -> Any | None:
                return self.stored.get(key)

            def get_with_ttl(self, key: str) -> tuple[Any | None, int]:
                if key not in self.stored:
                    return None, 0
                return self.stored[key], 3  # 3 seconds remaining

            def set(self, key: str, value: Any, ttl: int) -> None:
                self.stored[key] = value

            def delete(self, key: str) -> None:
                self.stored.pop(key, None)

            def clear_namespace(self, prefix: str) -> int:
                return 0

        captured: list[tuple[str, Any, int]] = []

        class RecordingLRU(LRUBackend):
            def set(self, key: str, value: Any, ttl: int) -> None:
                captured.append((key, value, ttl))
                super().set(key, value, ttl)

        stub_l2 = StubL2()
        cache = Cache(l1=RecordingLRU(), l2=stub_l2)  # type: ignore[arg-type]
        full_key = make_key("llm", "k")
        stub_l2.stored[full_key] = "v"
        assert cache.get("llm", "k") == "v"
        # The L1 promotion must have used the 3-second remaining TTL,
        # not the 7-day namespace policy.
        assert captured, "L1 promotion did not fire"
        promote_key, promote_value, promote_ttl = captured[-1]
        assert promote_key == full_key
        assert promote_value == "v"
        assert promote_ttl == 3, (
            f"Expected promotion TTL to be 3s (remaining), got {promote_ttl}"
        )

    def test_l1_promotion_skipped_when_remaining_ttl_zero(self) -> None:
        """If L2 reports remaining TTL of 0 (race with expiry), skip
        the promotion entirely rather than try to ``set`` ttl=0 which
        the LRU rightly rejects."""

        class ExpiredL2:
            stored = {"v1:llm:k": "v"}

            def get(self, key: str) -> Any | None:
                return self.stored.get(key)

            def get_with_ttl(self, key: str) -> tuple[Any | None, int]:
                # Value still there but TTL already 0 (the racing
                # case Redis can produce).
                return self.stored.get(key), 0

            def set(self, key: str, value: Any, ttl: int) -> None:
                pass

            def delete(self, key: str) -> None:
                pass

            def clear_namespace(self, prefix: str) -> int:
                return 0

        promotions: list[int] = []

        class RecordingLRU(LRUBackend):
            def set(self, key: str, value: Any, ttl: int) -> None:
                promotions.append(ttl)
                super().set(key, value, ttl)

        cache = Cache(l1=RecordingLRU(), l2=ExpiredL2())  # type: ignore[arg-type]
        # Still returns the value because L2.get is non-None.
        assert cache.get("llm", "k") == "v"
        # But L1 was not poked.
        assert promotions == []

    def test_full_miss_returns_none(self) -> None:
        cache, _ = _orchestrator_with_fakeredis()
        assert cache.get("llm", "absent") is None
        assert cache.stats()["misses"] == 1

    def test_l2_optional_l1_only_still_works(self) -> None:
        """If Redis is down at boot, the cache runs L1-only and the
        orchestrator must not raise on get/set/invalidate."""
        cache = Cache(l1=LRUBackend(), l2=None)
        assert cache.l2_available is False
        cache.set("llm", "k", "v")
        assert cache.get("llm", "k") == "v"
        cache.invalidate("llm", "k")
        assert cache.get("llm", "k") is None


class TestInvalidate:
    def test_invalidate_single_key_removes_from_both_tiers(self) -> None:
        cache, fake = _orchestrator_with_fakeredis()
        cache.set("llm", "k", "v")
        cache.invalidate("llm", "k")
        assert cache.get("llm", "k") is None
        from src.cache.base import make_key

        assert not fake.exists(make_key("llm", "k"))

    def test_invalidate_namespace_clears_only_that_prefix(self) -> None:
        cache, _ = _orchestrator_with_fakeredis()
        cache.set("llm", "a", "x")
        cache.set("llm", "b", "y")
        cache.set("embedding", "c", "z")
        deleted = cache.invalidate("llm")
        # L2 reports the actual count.
        assert deleted == 2
        assert cache.get("llm", "a") is None
        assert cache.get("llm", "b") is None
        assert cache.get("embedding", "c") == "z"


class TestStats:
    def test_writes_counter_increments(self) -> None:
        cache, _ = _orchestrator_with_fakeredis()
        for i in range(5):
            cache.set("llm", f"k{i}", i)
        assert cache.stats()["writes"] == 5

    def test_hits_and_misses_counters(self) -> None:
        cache, _ = _orchestrator_with_fakeredis()
        cache.set("llm", "k", "v")
        cache.get("llm", "k")  # L1 hit
        cache.get("llm", "absent")  # miss
        stats = cache.stats()
        assert stats["hits_l1"] == 1
        assert stats["misses"] == 1


class TestGetCacheSingleton:
    def test_singleton_returns_same_instance(self) -> None:
        reset_cache()
        first = get_cache()
        second = get_cache()
        assert first is second

    def test_reset_cache_drops_singleton(self) -> None:
        reset_cache()
        first = get_cache()
        reset_cache()
        second = get_cache()
        assert first is not second

    def test_l2_reattaches_after_redis_recovery(self, monkeypatch) -> None:
        """Codex review P2 regression: a cache built without L2
        (Redis down at boot) must reattach L2 when Redis recovers.
        We model this by patching ``get_redis_client`` to return
        ``None`` first, then a live fake on a later call after the
        retry cooldown has elapsed."""
        import fakeredis

        from src.cache import cache as cache_module

        reset_cache()

        # First call: Redis "down".
        monkeypatch.setattr(
            "src.cache.cache.get_redis_client", lambda: None
        )
        first = get_cache()
        assert first.l2_available is False

        # Advance the monotonic clock past the cooldown.
        monkeypatch.setattr(
            cache_module, "_l2_retry_at", 0.0
        )

        # Second call: Redis "up". The singleton must be re-used (same
        # ``id``) but now have L2 attached.
        fake = fakeredis.FakeRedis(decode_responses=True)
        monkeypatch.setattr(
            "src.cache.cache.get_redis_client", lambda: fake
        )
        second = get_cache()
        assert second is first  # same singleton
        assert second.l2_available is True

    def test_l2_retry_respects_cooldown(self, monkeypatch) -> None:
        """If Redis is down, the next attempt must wait out the
        cooldown rather than running ``get_redis_client`` on every
        call. Otherwise we'd burn a 2s socket timeout per cache hit."""
        from src.cache import cache as cache_module

        reset_cache()

        calls = {"n": 0}

        def fake_client():
            calls["n"] += 1
            return None

        monkeypatch.setattr(
            "src.cache.cache.get_redis_client", fake_client
        )

        # First call builds the L1-only singleton (1 attempt).
        get_cache()
        # ``_l2_retry_at`` is now in the future. Subsequent calls
        # must NOT re-invoke get_redis_client.
        for _ in range(5):
            get_cache()
        assert calls["n"] == 1, (
            f"get_redis_client was called {calls['n']} times despite cooldown"
        )

        # Move past the cooldown -> next call attempts again.
        monkeypatch.setattr(
            cache_module, "_l2_retry_at", 0.0
        )
        get_cache()
        assert calls["n"] == 2

    @pytest.fixture(autouse=True)
    def _cleanup(self):
        """Always reset the singleton between cases so test order
        doesn't matter."""
        reset_cache()
        yield
        reset_cache()
