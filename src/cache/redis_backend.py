"""L2 cache backend backed by redis-py.

This is a thin shim over :class:`redis.Redis` with three small but
important pieces of policy:

* **JSON serialisation.** ``json.dumps`` on write, ``json.loads`` on
  read. The connection in :mod:`src.cache.connection` is built with
  ``decode_responses=True`` so we get ``str`` back from Redis directly.
  Bytes-typed callers are out of scope until a future sub-phase
  needs them; the policy table in ``base.py`` documents why.

* **TTL is mandatory.** ``set`` uses ``SETEX`` so every entry has an
  expiry. There is no API to write a non-expiring key here -- see
  the rationale in ``base.py``.

* **Transport errors degrade to misses.** ``get`` swallows
  :class:`~redis.exceptions.RedisError` and returns ``None`` so the
  orchestrator can transparently fall back to L1 if Redis blips.
  ``set`` / ``delete`` log and swallow because cache writes are
  best-effort: losing a write means the next call recomputes, not
  that the user sees an error.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis
from redis.exceptions import RedisError

from src.cache.base import CacheBackend

logger = logging.getLogger(__name__)

# Cap the SCAN cursor iterations during ``clear_namespace`` so a
# pathological prefix can't lock up the cache thread. 10k matches
# is well above the inspector UI's "show me a sample" use case;
# real namespaces should stay well under that.
_SCAN_BATCH = 500
_SCAN_MAX_ITERATIONS = 1000


class RedisBackend(CacheBackend):
    """L2 backend wrapping a configured :class:`redis.Redis` client."""

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    # ----- CacheBackend interface -----

    def get(self, key: str) -> Any | None:
        try:
            raw = self._client.get(key)
        except RedisError as exc:
            logger.warning("Redis GET %s failed (%s); treating as miss.", key, exc)
            return None
        return self._decode(key, raw)

    def get_with_ttl(self, key: str, /) -> tuple[Any | None, int]:
        """Atomic ``GET`` + ``TTL`` via pipeline. Used by the
        orchestrator on L1 promotion so a near-expiry Redis entry
        doesn't get re-inserted into L1 with a fresh full-window TTL."""
        try:
            pipe = self._client.pipeline()
            pipe.get(key)
            pipe.ttl(key)
            raw, ttl_raw = pipe.execute()
        except RedisError as exc:
            logger.warning(
                "Redis pipeline GET+TTL %s failed (%s); treating as miss.",
                key,
                exc,
            )
            return None, 0
        value = self._decode(key, raw)
        if value is None:
            return None, 0
        try:
            ttl = int(ttl_raw)
        except (TypeError, ValueError):
            ttl = -1
        # Redis returns -1 for "no expiry" and -2 for "missing key".
        # We never write entries without TTL (``set`` enforces it),
        # but be defensive: treat -2 as a miss, -1 as "unknown".
        if ttl == -2:
            return None, 0
        return value, ttl

    def _decode(self, key: str, raw: Any) -> Any | None:
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError) as exc:
            # A stored value that no longer parses is poisoned --
            # drop it so the next call recomputes cleanly rather
            # than tripping on the same corruption forever.
            logger.warning(
                "Cache value at %s failed to decode (%s); deleting.", key, exc
            )
            self.delete(key)
            return None

    def set(self, key: str, value: Any, ttl: int) -> None:
        if ttl <= 0:
            raise ValueError(f"ttl must be positive, got {ttl!r}")
        try:
            payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            # Caller passed a non-JSON-serialisable value. This is a
            # programmer error, not a transport hiccup -- raise so
            # tests catch it instead of silently dropping the write.
            raise TypeError(
                f"Cache value for {key!r} is not JSON-serialisable: {exc}"
            ) from exc
        try:
            self._client.setex(key, ttl, payload)
        except RedisError as exc:
            logger.warning("Redis SETEX %s failed (%s); skipping write.", key, exc)

    def delete(self, key: str) -> None:
        try:
            self._client.delete(key)
        except RedisError as exc:
            logger.warning("Redis DEL %s failed (%s).", key, exc)

    def clear_namespace(self, prefix: str) -> int:
        """Use ``SCAN`` + batched ``DEL`` so we don't block Redis on
        a large keyspace. Returns the count of keys actually deleted."""
        if not prefix:
            # Refuse to clear everything by accident -- callers must
            # name a prefix. ``flushdb`` belongs in the CLI tool, not
            # here.
            raise ValueError("clear_namespace requires a non-empty prefix")
        deleted = 0
        try:
            cursor = 0
            iterations = 0
            while True:
                cursor, batch = self._client.scan(
                    cursor=cursor,
                    match=f"{prefix}*",
                    count=_SCAN_BATCH,
                )
                if batch:
                    deleted += self._client.delete(*batch)
                iterations += 1
                if cursor == 0:
                    break
                if iterations >= _SCAN_MAX_ITERATIONS:
                    logger.warning(
                        "clear_namespace(%s) hit %d iterations; stopping early.",
                        prefix,
                        iterations,
                    )
                    break
        except RedisError as exc:
            logger.warning("Redis SCAN/DEL for prefix %s failed (%s).", prefix, exc)
        return deleted

    # ----- introspection (used by the cache inspector and CLI) -----

    def keys_with_prefix(self, prefix: str, *, limit: int = 100) -> list[str]:
        """Return up to ``limit`` keys matching ``prefix*`` using
        ``SCAN``. Used by the inspector UI and ``redis info``."""
        if not prefix:
            raise ValueError("keys_with_prefix requires a non-empty prefix")
        out: list[str] = []
        try:
            cursor = 0
            while True:
                cursor, batch = self._client.scan(
                    cursor=cursor,
                    match=f"{prefix}*",
                    count=_SCAN_BATCH,
                )
                out.extend(batch)
                if cursor == 0 or len(out) >= limit:
                    break
        except RedisError as exc:
            logger.warning("Redis SCAN for prefix %s failed (%s).", prefix, exc)
        return out[:limit]
