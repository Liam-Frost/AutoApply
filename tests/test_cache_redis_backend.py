"""Phase 12.1 -- L2 Redis backend tests via fakeredis.

fakeredis is an in-memory implementation of the Redis protocol that
matches redis-py's API surface (including ``setex``, ``scan``,
``info``). Tests run without a live Redis server.
"""

from __future__ import annotations

import fakeredis
import pytest
from redis.exceptions import RedisError

from src.cache.redis_backend import RedisBackend


@pytest.fixture
def fake_client() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def backend(fake_client: fakeredis.FakeRedis) -> RedisBackend:
    return RedisBackend(fake_client)


class TestRedisBackend:
    def test_set_then_get_roundtrips_json(self, backend: RedisBackend) -> None:
        backend.set("k", {"foo": [1, 2, "three"]}, ttl=60)
        assert backend.get("k") == {"foo": [1, 2, "three"]}

    def test_missing_key_returns_none(self, backend: RedisBackend) -> None:
        assert backend.get("nope") is None

    def test_set_writes_ttl(
        self, backend: RedisBackend, fake_client: fakeredis.FakeRedis
    ) -> None:
        backend.set("k", "v", ttl=120)
        # fakeredis honours TTL. Allow off-by-one second.
        ttl_remaining = fake_client.ttl("k")
        assert 110 <= ttl_remaining <= 120

    def test_zero_or_negative_ttl_is_rejected(self, backend: RedisBackend) -> None:
        with pytest.raises(ValueError):
            backend.set("k", "v", ttl=0)
        with pytest.raises(ValueError):
            backend.set("k", "v", ttl=-5)

    def test_delete_is_noop_for_missing(self, backend: RedisBackend) -> None:
        backend.delete("nope")  # must not raise

    def test_non_json_serialisable_value_raises_type_error(
        self, backend: RedisBackend
    ) -> None:
        """Programmer error -- callers should see the failure rather
        than silently dropping the write."""

        class Opaque:
            pass

        with pytest.raises(TypeError):
            backend.set("k", Opaque(), ttl=60)

    def test_corrupted_payload_is_dropped_and_returns_none(
        self, backend: RedisBackend, fake_client: fakeredis.FakeRedis
    ) -> None:
        """If something stuffs a non-JSON blob into a cache key, the
        backend should self-heal by deleting it and returning None."""
        fake_client.setex("k", 60, "not-json{{{")
        assert backend.get("k") is None
        # And the poisoned key should be gone.
        assert fake_client.get("k") is None

    def test_clear_namespace_only_removes_matching_prefix(
        self, backend: RedisBackend
    ) -> None:
        backend.set("v1:llm:a", "x", ttl=60)
        backend.set("v1:llm:b", "y", ttl=60)
        backend.set("v1:embedding:c", "z", ttl=60)
        deleted = backend.clear_namespace("v1:llm:")
        assert deleted == 2
        assert backend.get("v1:llm:a") is None
        assert backend.get("v1:llm:b") is None
        assert backend.get("v1:embedding:c") == "z"

    def test_clear_namespace_rejects_empty_prefix(
        self, backend: RedisBackend
    ) -> None:
        """Refuse to clear everything by accident."""
        with pytest.raises(ValueError):
            backend.clear_namespace("")

    def test_keys_with_prefix_returns_sample(
        self, backend: RedisBackend
    ) -> None:
        for i in range(5):
            backend.set(f"v1:llm:{i}", i, ttl=60)
        keys = backend.keys_with_prefix("v1:llm:", limit=10)
        assert sorted(keys) == [f"v1:llm:{i}" for i in range(5)]

    def test_keys_with_prefix_honours_limit(
        self, backend: RedisBackend
    ) -> None:
        for i in range(50):
            backend.set(f"v1:llm:{i}", i, ttl=60)
        keys = backend.keys_with_prefix("v1:llm:", limit=10)
        assert len(keys) == 10

    def test_keys_with_prefix_rejects_empty_prefix(
        self, backend: RedisBackend
    ) -> None:
        with pytest.raises(ValueError):
            backend.keys_with_prefix("")

    def test_get_swallows_redis_errors_and_returns_none(self) -> None:
        """Transport failures must degrade to a miss, not raise."""

        class FailingClient:
            def get(self, key: str) -> str:
                raise RedisError("boom")

        backend = RedisBackend(FailingClient())  # type: ignore[arg-type]
        assert backend.get("k") is None

    def test_get_with_ttl_returns_remaining_seconds(
        self, backend: RedisBackend
    ) -> None:
        """Codex review P2 regression: the L1 promotion path needs
        the remaining TTL, not the policy TTL. This is the L2 hook
        that surfaces it."""
        backend.set("k", "v", ttl=120)
        value, remaining = backend.get_with_ttl("k")
        assert value == "v"
        assert 110 <= remaining <= 120

    def test_get_with_ttl_missing_key(self, backend: RedisBackend) -> None:
        value, remaining = backend.get_with_ttl("nope")
        assert value is None
        assert remaining == 0

    def test_get_with_ttl_swallows_redis_errors(self) -> None:
        class FailingClient:
            def pipeline(self):
                raise RedisError("pipeline boom")

        backend = RedisBackend(FailingClient())  # type: ignore[arg-type]
        value, remaining = backend.get_with_ttl("k")
        assert value is None
        assert remaining == 0

    def test_set_swallows_redis_errors(self) -> None:
        """Cache writes are best-effort: a Redis blip during SETEX
        must not propagate to the LLM call site."""

        class FailingClient:
            def setex(self, key: str, ttl: int, value: str) -> None:
                raise RedisError("boom")

        backend = RedisBackend(FailingClient())  # type: ignore[arg-type]
        backend.set("k", "v", ttl=60)  # must not raise
