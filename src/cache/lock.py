"""Phase 12.3 -- Distributed lock primitive on top of Redis.

Contract (matches what Phase 13's force-refresh path will rely on):

* :meth:`Cache.lock` returns a context manager. Inside the ``with``
  block, :attr:`AcquiredLock.acquired` tells the caller whether they
  hold the lock.

* Non-blocking by default (``blocking=False``): if another process
  already holds the lock, ``acquired`` is ``False`` and the caller
  should skip its work. This matches the cache-stampede pattern --
  if someone else is already scraping/recomputing, don't pile on.

* Blocking mode polls with exponential backoff up to
  ``blocking_timeout``. Timing out also yields ``acquired=False``;
  it never raises.

* TTL is mandatory. Without it, a process that died mid-work would
  hold the lock forever. The default 10 minutes matches the planned
  Phase 13 ``force-refresh`` window.

* Release uses a compare-and-delete Lua script so we never release a
  lock that some other process acquired after ours expired. This
  matches the Redlock single-node recipe.

L2 fallback: if Redis is unavailable, the cache degrades to a
process-local :class:`threading.Lock` keyed by ``key``. This isn't
a real distributed lock -- it only protects against same-process
races -- but it's the best signal we can offer when L2 is gone, and
it lets single-process deployments keep working. The :attr:`scope`
field tells the caller which mode they got so they can decide
whether process-local protection is sufficient.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from redis.exceptions import RedisError, WatchError

if TYPE_CHECKING:
    import redis

logger = logging.getLogger(__name__)

# Lock keys live in their own Redis prefix so they can never collide
# with cache value keys ("v1:llm:abc", etc). Without this, a caller
# that locked the same string used for a cache key would either:
#   * see ``SET NX`` fail because the cache entry already holds the
#     key, making the lock look held until the cache TTL expires; or
#   * win the lock first, after which any later ``RedisBackend.get()``
#     on that cache key would JSON-decode the token, treat it as a
#     poisoned cache entry, and ``DEL`` -- silently releasing the lock.
_LOCK_KEY_PREFIX = "lock:"


def _lock_key(name: str) -> str:
    """Compose the Redis key for a lock named ``name``."""
    return f"{_LOCK_KEY_PREFIX}{name}"

# Release uses WATCH/MULTI/EXEC for compare-and-delete: WATCH the key,
# read it, and only DEL if the stored token still matches ours. If any
# other client mutates the key between WATCH and EXEC, EXEC fails and
# we abort the DEL -- so we cannot release a lock another holder
# acquired after ours expired.
#
# Rationale for choosing WATCH/MULTI over a Lua ``EVAL`` script: the
# Lua approach is also correct, but ``fakeredis`` (the in-memory
# double we run tests against) doesn't always support EVAL on every
# platform. WATCH/MULTI/EXEC is a first-class Redis primitive supported
# everywhere we care about, and the atomicity guarantee is identical
# for this use case.


# Process-local lock registry used when L2 isn't available. Each
# ``key`` maps to its own :class:`threading.Lock`. The registry
# itself is guarded by a meta-lock so we don't race when creating
# the per-key lock object.
_PROCESS_LOCKS: dict[str, threading.Lock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


def _get_process_lock(key: str) -> threading.Lock:
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PROCESS_LOCKS[key] = lock
        return lock


@dataclass
class AcquiredLock(AbstractContextManager["AcquiredLock"]):
    """Context manager returned by :meth:`Cache.lock`.

    ``acquired`` reflects the actual outcome. Always safe to use in
    a ``with`` block: ``__exit__`` only releases if we got the lock.
    """

    key: str
    acquired: bool
    scope: str  # "redis" | "process" | "none"
    _release: Callable[[], None] | None = field(default=None, repr=False)

    def __enter__(self) -> AcquiredLock:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # Release happens unconditionally on exit so callers don't
        # have to remember to call it. If we didn't acquire, the
        # release function is a no-op.
        if self.acquired and self._release is not None:
            try:
                self._release()
            except Exception as exc:  # noqa: BLE001 -- best-effort release
                logger.warning(
                    "Lock release failed for %s (%s); TTL will expire it.",
                    self.key,
                    exc,
                )
        return None

    # Deliberately no ``__bool__``: a previous version exposed
    # truthiness so callers could write ``if cache.lock(...):``, but
    # that pattern discards the handle without entering a ``with``
    # block, so ``__exit__`` never fires and the lock leaks until
    # TTL (Redis) or process exit (process-local). The only safe API
    # is the context-manager form; inside the ``with`` block, check
    # ``handle.acquired`` to branch on whether you got the lock.


def acquire_lock(
    client: redis.Redis | None,
    key: str,
    *,
    ttl: int,
    blocking: bool,
    blocking_timeout: float,
) -> AcquiredLock:
    """Try to acquire a lock. Returns an :class:`AcquiredLock` whose
    ``acquired`` field tells the caller whether they got it.

    This is split out of :class:`Cache` so the orchestrator stays a
    pure key/value facade; the lock logic with its Lua release path
    has its own module.
    """
    if ttl <= 0:
        raise ValueError(f"lock ttl must be positive, got {ttl!r}")

    if client is None:
        return _acquire_process_local_lock(key, blocking, blocking_timeout)

    return _acquire_redis_lock(
        client, key, ttl=ttl, blocking=blocking, blocking_timeout=blocking_timeout
    )


def _acquire_redis_lock(
    client: redis.Redis,
    key: str,
    *,
    ttl: int,
    blocking: bool,
    blocking_timeout: float,
) -> AcquiredLock:
    # Token must be unguessable so a stale process can't release a
    # lock we hold. ``secrets.token_hex`` is overkill against the
    # threat model but cheap; mix in the host-unique uuid to make it
    # diagnosable in operator-grade logs.
    token = f"{uuid.uuid4().hex}:{secrets.token_hex(8)}"
    ttl_ms = ttl * 1000
    # Internal Redis key (with lock prefix) -- the public ``key``
    # argument is what the caller sees / what the handle reports.
    redis_key = _lock_key(key)

    class _TransportFailedError(Exception):
        """Internal sentinel: Redis is unreachable, fall back."""

    def _try_set() -> bool:
        """``True`` -> got the lock, ``False`` -> someone else has it.
        Raises ``_TransportFailedError`` on a Redis error so the caller
        falls back to the process-local lock instead of pretending
        the key was held."""
        try:
            return bool(client.set(redis_key, token, nx=True, px=ttl_ms))
        except RedisError as exc:
            logger.warning(
                "Redis SET NX PX failed on %s (%s); falling back to "
                "process-local lock.",
                redis_key,
                exc,
            )
            raise _TransportFailedError from exc

    try:
        got = _try_set()
    except _TransportFailedError:
        return _acquire_process_local_lock(key, blocking, blocking_timeout)
    if got:
        return _build_redis_lock_handle(client, key, redis_key, token)

    if not blocking:
        return AcquiredLock(key=key, acquired=False, scope="redis")

    # Blocking path: poll with exponential backoff bounded by
    # ``blocking_timeout``. Start small so a fast unlock is picked
    # up quickly; cap so we don't spin tightly under sustained
    # contention.
    deadline = time.monotonic() + blocking_timeout
    backoff = 0.025  # 25 ms
    while time.monotonic() < deadline:
        time.sleep(backoff)
        try:
            got = _try_set()
        except _TransportFailedError:
            # Redis went away mid-poll; switch to process-local
            # behaviour for the rest of this acquire so a
            # transient outage doesn't lock callers out completely.
            remaining = max(0.0, deadline - time.monotonic())
            return _acquire_process_local_lock(key, blocking, remaining)
        if got:
            return _build_redis_lock_handle(client, key, redis_key, token)
        backoff = min(backoff * 2, 0.5)

    return AcquiredLock(key=key, acquired=False, scope="redis")


def _build_redis_lock_handle(
    client: redis.Redis, key: str, redis_key: str, token: str
) -> AcquiredLock:
    def release() -> None:
        # WATCH/MULTI/EXEC compare-and-delete: only releases if the
        # stored value still matches our token. Prevents the classic
        # "I expired, someone else acquired, then I release" bug.
        try:
            with client.pipeline() as pipe:
                try:
                    pipe.watch(redis_key)
                    current = pipe.get(redis_key)
                    if current != token:
                        # Someone else holds it now (or TTL cleared
                        # the key); UNWATCH and bail.
                        pipe.unwatch()
                        return
                    pipe.multi()
                    pipe.delete(redis_key)
                    pipe.execute()
                except WatchError:
                    # The key changed between WATCH and EXEC -- another
                    # holder acquired during the tiny window. Their
                    # lock is safe; ours is gone.
                    pass
        except RedisError as exc:
            # If Redis is down at release time, the lock will expire
            # via TTL. Logging this beats blocking the caller's
            # ``with`` exit on a transport error.
            logger.warning("Lock release for %s failed (%s).", redis_key, exc)

    return AcquiredLock(key=key, acquired=True, scope="redis", _release=release)


def _acquire_process_local_lock(
    key: str, blocking: bool, blocking_timeout: float
) -> AcquiredLock:
    lock = _get_process_lock(key)
    # ``threading.Lock.acquire(blocking, timeout)`` is the natural fit.
    if blocking:
        acquired = lock.acquire(blocking=True, timeout=blocking_timeout)
    else:
        acquired = lock.acquire(blocking=False)

    if not acquired:
        return AcquiredLock(key=key, acquired=False, scope="process")

    def release() -> None:
        try:
            lock.release()
        except RuntimeError:
            # Lock was already released somehow; safe to ignore.
            pass

    return AcquiredLock(
        key=key, acquired=True, scope="process", _release=release
    )
