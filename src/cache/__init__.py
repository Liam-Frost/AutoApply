"""Phase 12 cache infrastructure.

Two-tier cache (L1 in-process LRU + L2 Redis) consumed by LLM and
embedding call sites. The public surface is intentionally narrow:

* :class:`Cache` -- orchestrator with ``get/set/invalidate(namespace, key)``.
* :func:`get_cache` -- process-singleton accessor wired up at import time
  so call sites don't have to plumb the instance through.
* :data:`NAMESPACE_TTLS` -- per-namespace TTL policy (``llm: 7d``,
  ``embedding: 30d``, ``response: 5m``).

Phase 12.2 will introduce the distributed lock primitive
(``cache.lock(key, ttl=...)``); Phases 13 / 17 / 18 will consume it.
"""

from __future__ import annotations

from src.cache.base import CACHE_VERSION, NAMESPACE_TTLS, CacheBackend, validate_namespace
from src.cache.cache import Cache, get_cache, reset_cache
from src.cache.connection import get_redis_client, redis_health
from src.cache.lock import AcquiredLock
from src.cache.lru import LRUBackend
from src.cache.redis_backend import RedisBackend

__all__ = [
    "CACHE_VERSION",
    "AcquiredLock",
    "Cache",
    "CacheBackend",
    "LRUBackend",
    "NAMESPACE_TTLS",
    "RedisBackend",
    "get_cache",
    "get_redis_client",
    "redis_health",
    "reset_cache",
    "validate_namespace",
]
