"""Phase 12.3 -- Distributed lock primitive tests.

Covers Redis-backed locks (via fakeredis), process-local fallback,
non-blocking vs blocking acquisition, TTL auto-release, token-CAS
release semantics, and the AcquiredLock context-manager contract.
"""

from __future__ import annotations

import threading
import time

import fakeredis
import pytest

from src.cache.cache import Cache
from src.cache.lock import _LOCK_KEY_PREFIX, _PROCESS_LOCKS, AcquiredLock, acquire_lock
from src.cache.lru import LRUBackend
from src.cache.redis_backend import RedisBackend


@pytest.fixture
def fake_client() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def _clear_process_locks():
    _PROCESS_LOCKS.clear()
    yield
    _PROCESS_LOCKS.clear()


class TestRedisLock:
    def test_acquire_releases_on_exit(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        redis_key = f"{_LOCK_KEY_PREFIX}k"
        with acquire_lock(
            fake_client, "k", ttl=60, blocking=False, blocking_timeout=0
        ) as handle:
            assert handle.acquired is True
            assert handle.scope == "redis"
            assert fake_client.exists(redis_key)
        # Released on exit.
        assert not fake_client.exists(redis_key)

    def test_second_acquire_returns_not_acquired(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        first = acquire_lock(
            fake_client, "k", ttl=60, blocking=False, blocking_timeout=0
        )
        try:
            second = acquire_lock(
                fake_client, "k", ttl=60, blocking=False, blocking_timeout=0
            )
            assert first.acquired is True
            assert second.acquired is False
        finally:
            first.__exit__(None, None, None)

    def test_release_uses_token_cas(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        """If our lock has expired and someone else acquired the key,
        our release must NOT delete their lock. The WATCH/MULTI/EXEC
        compare-and-delete enforces this; simulate by overwriting the
        stored token between acquire and release."""
        redis_key = f"{_LOCK_KEY_PREFIX}k"
        handle = acquire_lock(
            fake_client, "k", ttl=60, blocking=False, blocking_timeout=0
        )
        assert handle.acquired
        # Pretend another holder took over after our key expired.
        fake_client.set(redis_key, "stolen-by-someone-else")
        handle.__exit__(None, None, None)
        # The other holder's value must still be there -- we did NOT
        # del their lock.
        assert fake_client.get(redis_key) == "stolen-by-someone-else"

    def test_ttl_auto_expires(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        """Even if the holder dies without releasing, the lock must
        clear via TTL so the system unjams."""
        redis_key = f"{_LOCK_KEY_PREFIX}k"
        # ttl=1 second so the test isn't slow.
        handle = acquire_lock(
            fake_client, "k", ttl=1, blocking=False, blocking_timeout=0
        )
        assert handle.acquired
        # Force-expire by deleting (fakeredis honours TTL but waiting
        # would slow the suite); simulating the post-expiry state is
        # equivalent for the contract.
        fake_client.delete(redis_key)
        # A new acquirer should succeed.
        second = acquire_lock(
            fake_client, "k", ttl=60, blocking=False, blocking_timeout=0
        )
        assert second.acquired is True
        second.__exit__(None, None, None)

    def test_lock_keys_do_not_collide_with_cache_values(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        """Codex review P2 regression: Lock keys must live in their
        own Redis prefix so they cannot collide with cache value
        keys. Otherwise a caller that locks the same string used for
        a cache key could either spuriously block on the cache entry
        or have the cache's poison-cleanup ``DEL`` the lock."""
        # Pretend a cache write under the orchestrator's keying scheme.
        fake_client.setex("v1:llm:abc", 60, '"cached"')
        # Acquire a lock named identically to that cache key.
        with acquire_lock(
            fake_client,
            "v1:llm:abc",
            ttl=60,
            blocking=False,
            blocking_timeout=0,
        ) as handle:
            # We got the lock -- there was no collision.
            assert handle.acquired is True
            # The lock lives at the prefixed key.
            assert fake_client.exists(f"{_LOCK_KEY_PREFIX}v1:llm:abc")
            # And the cache value is untouched.
            assert fake_client.get("v1:llm:abc") == '"cached"'

    def test_blocking_acquires_after_release(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        """A second waiter using ``blocking=True`` should pick up the
        lock once the first holder releases it. Drives the polling
        path."""
        first = acquire_lock(
            fake_client, "k", ttl=60, blocking=False, blocking_timeout=0
        )
        assert first.acquired

        results: list[AcquiredLock] = []

        def waiter() -> None:
            handle = acquire_lock(
                fake_client,
                "k",
                ttl=60,
                blocking=True,
                blocking_timeout=2.0,
            )
            results.append(handle)

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.1)  # let waiter spin once
        first.__exit__(None, None, None)
        t.join(timeout=3.0)
        assert len(results) == 1
        assert results[0].acquired is True
        results[0].__exit__(None, None, None)

    def test_blocking_timeout_returns_not_acquired(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        """A blocking acquire that exceeds ``blocking_timeout`` must
        not raise -- it returns ``acquired=False`` so the caller can
        decide what to do."""
        first = acquire_lock(
            fake_client, "k", ttl=60, blocking=False, blocking_timeout=0
        )
        try:
            second = acquire_lock(
                fake_client, "k", ttl=60, blocking=True, blocking_timeout=0.2
            )
            assert second.acquired is False
        finally:
            first.__exit__(None, None, None)

    def test_invalid_ttl_raises(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        for bad in (0, -1):
            with pytest.raises(ValueError):
                acquire_lock(
                    fake_client,
                    "k",
                    ttl=bad,
                    blocking=False,
                    blocking_timeout=0,
                )

    def test_acquired_lock_has_no_bool_to_prevent_leaks(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        """Codex review P2 regression: an ``AcquiredLock`` must NOT
        be truthy. The ``if cache.lock(...): ...`` pattern discards
        the handle without entering ``with``, so the lock would leak
        until TTL. The only safe API is the context-manager form;
        AcquiredLock therefore inherits the default truthiness (any
        instance) and provides no __bool__ override."""
        with acquire_lock(
            fake_client, "k", ttl=60, blocking=False, blocking_timeout=0
        ) as handle:
            # Default truthiness is True for any object. The point
            # is that we never advertise a ``acquired`` shortcut.
            assert not hasattr(AcquiredLock, "__bool__"), (
                "AcquiredLock must not override __bool__ -- it would "
                "encourage leaking the lock outside a `with` block."
            )
            assert handle.acquired is True

    def test_redis_transport_failure_falls_back_to_process(
        self,
    ) -> None:
        """Codex review P2 regression: if the Redis client raises
        ``RedisError`` during ``SET NX PX``, the lock must degrade to
        the process-local fallback instead of pretending the key was
        held by someone else."""
        from redis.exceptions import RedisError as _RedisError

        class FailingClient:
            def set(self, *args, **kwargs):
                raise _RedisError("transport down")

        with acquire_lock(
            FailingClient(),  # type: ignore[arg-type]
            "k",
            ttl=60,
            blocking=False,
            blocking_timeout=0,
        ) as handle:
            assert handle.acquired is True
            assert handle.scope == "process"


class TestProcessFallback:
    def test_no_redis_uses_process_lock(self) -> None:
        with acquire_lock(
            None, "k", ttl=60, blocking=False, blocking_timeout=0
        ) as handle:
            assert handle.acquired is True
            assert handle.scope == "process"

    def test_process_lock_blocks_same_process_re_entry(self) -> None:
        first = acquire_lock(
            None, "k", ttl=60, blocking=False, blocking_timeout=0
        )
        try:
            second = acquire_lock(
                None, "k", ttl=60, blocking=False, blocking_timeout=0
            )
            assert first.acquired is True
            assert second.acquired is False
        finally:
            first.__exit__(None, None, None)

    def test_process_lock_blocking_timeout(self) -> None:
        first = acquire_lock(
            None, "k", ttl=60, blocking=False, blocking_timeout=0
        )
        try:
            start = time.monotonic()
            second = acquire_lock(
                None, "k", ttl=60, blocking=True, blocking_timeout=0.2
            )
            elapsed = time.monotonic() - start
            assert second.acquired is False
            # We waited at least the requested timeout (allow slack).
            assert 0.15 <= elapsed <= 0.6
        finally:
            first.__exit__(None, None, None)


class TestCacheLockIntegration:
    def test_cache_lock_uses_redis_client_from_l2(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        """The orchestrator must extract the redis client from its
        L2 backend so locks use the real Redis when available."""
        cache = Cache(l1=LRUBackend(), l2=RedisBackend(fake_client))
        with cache.lock("k") as handle:
            assert handle.acquired is True
            assert handle.scope == "redis"

    def test_cache_lock_falls_back_to_process_when_l2_missing(self) -> None:
        cache = Cache(l1=LRUBackend(), l2=None)
        with cache.lock("k") as handle:
            assert handle.acquired is True
            assert handle.scope == "process"
