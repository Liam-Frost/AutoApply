"""Cache inspector use cases shared by CLI and Web.

Phase 12.6 surfaces the cache state to operators / the Settings page:

* :func:`cache_snapshot` -- per-namespace entry counts (from Redis
  when L2 is up), hit / miss / write counters (from the orchestrator),
  cost-saved estimate (Phase 12.7 wires this into the dashboard).

* :func:`clear_cache_namespace` -- one-namespace invalidation behind
  an explicit confirmation. Matches the ``autoapply redis flush``
  CLI's safety posture (no implicit "clear everything").

Returned dicts use the ``ok/error/error_code`` envelope shared with
``src/application/providers.py`` so the Web layer can render errors
without provider-specific branching.
"""

from __future__ import annotations

import logging
from typing import Any

from src.cache import NAMESPACE_TTLS, get_cache, validate_namespace
from src.cache.base import namespace_prefix
from src.cache.connection import (
    _resolve_redis_url,
    get_redis_client,
    redis_health,
)
from src.cache.redis_backend import _SCAN_BATCH, _SCAN_MAX_ITERATIONS

logger = logging.getLogger(__name__)


# Per-1k-token cost estimate used when no per-provider rate is wired
# up yet. Pulled from OpenAI's public pricing for ``gpt-4o-mini`` as
# a conservative reference -- adjust per deployment via the Phase
# 12.7 dashboard config once we have per-call cost telemetry to
# back it.
_DEFAULT_COST_PER_HIT_USD = 0.0015


def cache_snapshot() -> dict:
    """Return the structured cache view consumed by the inspector UI.

    Shape:
        {
            "ok": True,
            "redis": {
                "ok": bool,
                "url": str,
                "latency_ms": int | None,
                "detail": str,
            },
            "cache_version": "v1",
            "l2_available": bool,
            "stats": {hits_l1, hits_l2, misses, writes},
            "estimated_dollars_saved": float,
            "namespaces": [
                {
                    "name": "llm",
                    "ttl_seconds": 604800,
                    "entries": 42 | -1,  # -1 if Redis SCAN failed
                    "prefix": "v1:llm:",
                },
                ...
            ],
        }

    The ``entries`` count comes from a SCAN against Redis when L2 is
    up; with L2 unavailable it falls back to ``None`` because the
    in-process LRU isn't authoritative for "what does the world see".
    The cost-saved estimate folds ``hits_l1 + hits_l2`` against
    :data:`_DEFAULT_COST_PER_HIT_USD`; Phase 12.7 will replace this
    with the per-provider rate once token telemetry lands.
    """
    cache = get_cache()
    stats = cache.stats()
    hits = stats["hits_l1"] + stats["hits_l2"]
    estimated_saved = round(hits * _DEFAULT_COST_PER_HIT_USD, 4)

    # Redis health -- cheap PING, surfaces operator-visible status.
    health = redis_health()

    namespaces: list[dict[str, Any]] = []
    client = get_redis_client() if health.ok else None
    for ns, ttl in NAMESPACE_TTLS.items():
        prefix = namespace_prefix(ns)
        entries: int | None
        if client is None:
            entries = None
        else:
            try:
                entries = _scan_count(client, f"{prefix}*")
            except Exception as exc:  # noqa: BLE001 -- never break the snapshot
                logger.warning(
                    "SCAN for namespace %s failed in snapshot (%s).", ns, exc
                )
                entries = -1
        namespaces.append(
            {
                "name": ns,
                "ttl_seconds": ttl,
                "entries": entries,
                "prefix": prefix,
            }
        )

    return {
        "ok": True,
        "redis": {
            "ok": health.ok,
            "url": health.url,
            "latency_ms": health.latency_ms,
            "detail": health.detail,
        },
        "cache_version": cache.version,
        "l2_available": cache.l2_available,
        "stats": stats,
        "estimated_dollars_saved": estimated_saved,
        "namespaces": namespaces,
    }


def clear_cache_namespace(namespace: str) -> dict:
    """Invalidate every key in ``namespace``. Returns the count of
    keys removed in the ``ok/error`` envelope shared with the rest
    of ``src/application/*``.

    Namespace is validated up-front so a glob metacharacter like
    ``*`` cannot reach the SCAN pattern and wipe unrelated keys (the
    same defence ``redis flush --namespace`` has on the CLI side).

    Belt-and-braces L2 cleanup: even after the orchestrator's
    ``invalidate`` runs, we re-resolve the Redis client directly and
    do a fresh SCAN+DEL for the namespace prefix. This matters when
    Redis was down at process start: the cache singleton was built
    L1-only, hasn't passed its retry cooldown, and ``invalidate``
    would only clear L1 -- leaving the operator-visible "Clear"
    button silently no-op on the Redis side they can see in the
    snapshot.
    """
    try:
        validate_namespace(namespace)
    except ValueError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_code": "invalid_namespace",
        }
    # We deliberately do NOT delegate the L2 clear to
    # ``Cache.invalidate`` -> ``RedisBackend.clear_namespace`` because
    # that path catches RedisError internally and returns 0, which
    # would let a silent SCAN/DEL failure look like a successful
    # clear in the UI. Instead, drive the L2 clear ourselves so any
    # exception propagates and we can return ``clear_failed``.
    cache = get_cache()
    prefix = namespace_prefix(namespace)

    redis_deleted = 0
    try:
        client = get_redis_client()
    except Exception as exc:  # noqa: BLE001 -- treat as recovery failure
        logger.exception(
            "Resolving Redis client during namespace clear failed."
        )
        return {
            "ok": False,
            "error": str(exc),
            "error_code": "clear_failed",
        }
    if client is not None:
        try:
            redis_deleted = _scan_and_delete(client, f"{prefix}*")
        except Exception as exc:  # noqa: BLE001 -- surface to operator
            logger.exception(
                "Direct Redis cleanup for namespace %s failed.", namespace
            )
            return {
                "ok": False,
                "error": str(exc),
                "error_code": "clear_failed",
            }
    elif cache.l2_available:
        # L2 was attached on the singleton (so the snapshot likely
        # showed Redis healthy moments ago), but the connection
        # factory now returns None -- Redis went down between
        # snapshot and clear. Reporting success here would leave
        # stale L2 entries that come back online once Redis recovers.
        return {
            "ok": False,
            "error": "Redis became unreachable while clearing.",
            "error_code": "clear_failed",
        }

    # Drop L1 entries too so a stale in-process copy doesn't survive
    # an L2 clear. The L1 backend's ``clear_namespace`` does not
    # touch the network and is unlikely to fail; any unexpected
    # exception is surfaced as clear_failed for consistency.
    try:
        l1_deleted = cache._l1.clear_namespace(prefix)
    except Exception as exc:  # noqa: BLE001
        logger.exception("L1 clear for namespace %s failed.", namespace)
        return {
            "ok": False,
            "error": str(exc),
            "error_code": "clear_failed",
        }

    effective_deleted = max(redis_deleted, l1_deleted)
    return {
        "ok": True,
        "namespace": namespace,
        "deleted": effective_deleted,
        "message": f"Cleared {effective_deleted} entries from {namespace!r}.",
    }


def _scan_and_delete(client: Any, pattern: str) -> int:
    """SCAN + DEL the matching keys. Returns the count actually deleted.

    Bounded by the same ``_SCAN_MAX_ITERATIONS`` as the snapshot scan
    so the request doesn't sit forever on a pathological keyspace.
    """
    deleted = 0
    cursor = 0
    iterations = 0
    while True:
        cursor, batch = client.scan(
            cursor=cursor, match=pattern, count=_SCAN_BATCH
        )
        if batch:
            deleted += client.delete(*batch)
        iterations += 1
        if cursor == 0 or iterations >= _SCAN_MAX_ITERATIONS:
            break
    return deleted


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _scan_count(client: Any, pattern: str) -> int:
    """Count keys matching ``pattern`` via ``SCAN``. Bounded so a
    pathological keyspace can't lock up the API thread -- the bounds
    come from ``RedisBackend`` to keep behaviour consistent."""
    count = 0
    cursor = 0
    iterations = 0
    while True:
        cursor, batch = client.scan(
            cursor=cursor, match=pattern, count=_SCAN_BATCH
        )
        count += len(batch)
        iterations += 1
        if cursor == 0 or iterations >= _SCAN_MAX_ITERATIONS:
            break
    return count


__all__ = [
    "cache_snapshot",
    "clear_cache_namespace",
]


# Re-export so ``from src.application.cache import _resolve_redis_url``
# works for tests that want to peek; the underscore is preserved to
# discourage non-test callers.
_resolve_redis_url = _resolve_redis_url
