"""Cache orchestrator: L1 (in-process) in front of L2 (Redis).

The orchestrator owns:

* **Namespace TTL policy.** Callers say ``cache.set("llm", key, value)``
  and the TTL is looked up in :data:`~src.cache.base.NAMESPACE_TTLS`.
  Callers do not pass TTLs directly so the policy stays auditable
  in one place.

* **Version-stamped keys.** Every key is prefixed with
  :data:`~src.cache.base.CACHE_VERSION` so a serialisation-format
  bump invalidates the entire keyspace without ``FLUSHALL``.

* **L1 promotion on L2 hit.** If L2 returns a value and L1 missed,
  L1 is repopulated so the next read in this process is one
  dictionary lookup.

* **L2 graceful degrade.** Any :class:`~redis.exceptions.RedisError`
  from the L2 backend is logged and treated as a miss for ``get`` /
  a no-op for ``set``/``delete``. L1 keeps serving so the call site
  never has to ``try/except`` cache failures.

A single :func:`get_cache` accessor returns the process-wide
singleton, built lazily on first call. Tests use :func:`reset_cache`
between cases to start fresh.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from src.cache.base import (
    CACHE_VERSION,
    DEFAULT_NAMESPACE_TTL,
    NAMESPACE_TTLS,
    CacheBackend,
    make_key,
    namespace_prefix,
)
from src.cache.connection import get_redis_client
from src.cache.lru import DEFAULT_MAX_ENTRIES, LRUBackend
from src.cache.redis_backend import RedisBackend

logger = logging.getLogger(__name__)


class Cache:
    """L1 LRU in front of an optional L2 Redis backend.

    The L2 argument is optional so tests can run without Redis and
    production can degrade gracefully when the Redis singleton
    returns ``None``.
    """

    def __init__(
        self,
        l1: CacheBackend,
        l2: CacheBackend | None = None,
        *,
        version: str = CACHE_VERSION,
        namespace_ttls: dict[str, int] | None = None,
        default_ttl: int = DEFAULT_NAMESPACE_TTL,
    ) -> None:
        self._l1 = l1
        self._l2 = l2
        self._version = version
        self._namespace_ttls = (
            dict(namespace_ttls) if namespace_ttls is not None else dict(NAMESPACE_TTLS)
        )
        self._default_ttl = default_ttl
        # Hit/miss counters surfaced to the inspector UI and the
        # cost dashboard. Wrapped in a lock so concurrent FastAPI
        # workers don't lose increments.
        self._stats_lock = threading.Lock()
        self._stats = {
            "hits_l1": 0,
            "hits_l2": 0,
            "misses": 0,
            "writes": 0,
        }

    # ----- public API -----

    def get(self, namespace: str, key: str) -> Any | None:
        """Two-tier read. Returns ``None`` on miss across both tiers."""
        full_key = make_key(namespace, key, version=self._version)
        value = self._l1.get(full_key)
        if value is not None:
            with self._stats_lock:
                self._stats["hits_l1"] += 1
            return value
        if self._l2 is not None:
            value, remaining_ttl = self._l2.get_with_ttl(full_key)
            if value is not None:
                # Promote into L1 using the *remaining* TTL from L2 so
                # an entry close to expiry in Redis doesn't get a fresh
                # full-namespace window in L1. ``remaining_ttl`` is in
                # seconds; ``-1`` from a backend that doesn't track TTL
                # falls back to the namespace policy (since we have no
                # better signal). Skip the promotion entirely if the
                # remaining window is <= 0 -- the LRU rejects ttl=0.
                if remaining_ttl > 0:
                    promote_ttl = remaining_ttl
                elif remaining_ttl < 0:
                    promote_ttl = self._ttl_for(namespace)
                else:
                    promote_ttl = 0
                if promote_ttl > 0:
                    try:
                        self._l1.set(full_key, value, promote_ttl)
                    except ValueError:
                        logger.debug(
                            "L1 promotion failed for %s (ttl=%s)",
                            full_key,
                            promote_ttl,
                        )
                with self._stats_lock:
                    self._stats["hits_l2"] += 1
                return value
        with self._stats_lock:
            self._stats["misses"] += 1
        return None

    def set(self, namespace: str, key: str, value: Any) -> None:
        """Write through to both tiers under the namespace TTL."""
        full_key = make_key(namespace, key, version=self._version)
        ttl = self._ttl_for(namespace)
        self._l1.set(full_key, value, ttl)
        if self._l2 is not None:
            # RedisBackend.set already swallows transport errors
            # internally; a JSON-serialisation error is a programmer
            # bug and is allowed to propagate.
            self._l2.set(full_key, value, ttl)
        with self._stats_lock:
            self._stats["writes"] += 1

    def invalidate(self, namespace: str, key: str | None = None) -> int:
        """Drop ``namespace/key`` from both tiers, or the entire
        namespace if ``key`` is ``None``. Returns the L2 count for the
        bulk case (L1 LRU returns its own count internally)."""
        if key is not None:
            full_key = make_key(namespace, key, version=self._version)
            self._l1.delete(full_key)
            if self._l2 is not None:
                self._l2.delete(full_key)
            return 1
        prefix = namespace_prefix(namespace, version=self._version)
        l1_count = self._l1.clear_namespace(prefix)
        l2_count = 0
        if self._l2 is not None:
            l2_count = self._l2.clear_namespace(prefix)
        # L2 is authoritative for "how many entries existed"; L1 is
        # a strict subset, so report L2 when present.
        return l2_count if self._l2 is not None else l1_count

    # ----- L2 attachment -----

    def attach_l2(self, l2: CacheBackend) -> None:
        """Upgrade an L1-only cache to L1+L2.

        Used by :func:`get_cache` when Redis recovers after being
        unavailable at boot. Idempotent: a second call with the same
        backend is a no-op, a call with a different backend replaces
        the previous one (matches the singleton replacement that
        ``get_redis_client`` already supports for URL rotation).
        """
        self._l2 = l2

    # ----- introspection -----

    def stats(self) -> dict[str, int]:
        """Snapshot of the hit/miss counters. Inspector UI and cost
        dashboard render directly from this."""
        with self._stats_lock:
            return dict(self._stats)

    @property
    def l2_available(self) -> bool:
        """Whether an L2 backend is wired up. False means callers
        are running L1-only (Redis unreachable or disabled)."""
        return self._l2 is not None

    @property
    def version(self) -> str:
        return self._version

    # ----- helpers -----

    def _ttl_for(self, namespace: str) -> int:
        return self._namespace_ttls.get(namespace, self._default_ttl)


# ---------------------------------------------------------------------------
# Process singleton
# ---------------------------------------------------------------------------

_singleton_lock = threading.Lock()
_singleton: Cache | None = None
_l2_retry_at: float = 0.0

# Cooldown between L2 reattachment attempts. If Redis was down at boot
# (or restarted), we want to recover the L2 cache without blocking
# every get/set on an attempted connect. 30s is short enough that the
# advertised "L2 cache" feature actually re-enables itself promptly,
# long enough that a steady-state-failed Redis doesn't generate a
# connect attempt per cache call.
_L2_RETRY_COOLDOWN_SEC = 30.0


def get_cache() -> Cache:
    """Return the process-wide :class:`Cache`, built lazily.

    The L1 backend is always an :class:`LRUBackend` sized via the
    ``cache.l1_max_entries`` setting. L2 is attached if
    :func:`~src.cache.connection.get_redis_client` returns a live
    client; otherwise the cache runs L1-only and the next call after
    :data:`_L2_RETRY_COOLDOWN_SEC` retries the attachment so a
    Redis-down-at-boot deployment recovers without a process restart.
    """
    global _singleton, _l2_retry_at

    # Fast path: singleton already exists AND has L2 attached -- the
    # common case once everything is healthy. No lock acquisition.
    if _singleton is not None and _singleton.l2_available:
        return _singleton

    with _singleton_lock:
        # Re-check under the lock.
        if _singleton is not None and _singleton.l2_available:
            return _singleton

        now = time.monotonic()
        # Either no singleton yet, or it has no L2. In the second
        # case, respect the cooldown so we don't hammer Redis.
        if _singleton is not None and now < _l2_retry_at:
            return _singleton

        client = get_redis_client()
        l2: CacheBackend | None = RedisBackend(client) if client is not None else None

        if _singleton is None:
            # First build.
            try:
                from src.core.config import get_cache_settings

                settings = get_cache_settings()
                max_entries = settings.get("l1_max_entries") or DEFAULT_MAX_ENTRIES
            except Exception:  # noqa: BLE001 -- settings load must never block cache init
                max_entries = DEFAULT_MAX_ENTRIES
            l1 = LRUBackend(max_entries=max_entries)
            _singleton = Cache(l1=l1, l2=l2)
            if l2 is None:
                logger.info(
                    "Cache running L1-only (Redis unavailable). "
                    "Will retry attachment in %.0fs.",
                    _L2_RETRY_COOLDOWN_SEC,
                )
                _l2_retry_at = now + _L2_RETRY_COOLDOWN_SEC
        elif l2 is not None:
            # Existing L1-only singleton; Redis recovered -- attach.
            _singleton.attach_l2(l2)
            logger.info("L2 cache attached (Redis recovered).")
        else:
            # Still down; schedule the next retry.
            _l2_retry_at = now + _L2_RETRY_COOLDOWN_SEC

        return _singleton


def reset_cache() -> None:
    """Drop the singleton. Tests use this between cases."""
    global _singleton, _l2_retry_at
    with _singleton_lock:
        _singleton = None
        _l2_retry_at = 0.0
