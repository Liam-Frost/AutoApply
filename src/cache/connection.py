"""Redis connection management for the L2 cache.

Phase 12 keeps this small: a process-singleton :class:`redis.Redis`
client built from ``REDIS_URL`` (or the ``cache.redis_url`` setting),
plus a cheap :func:`redis_health` check used by the CLI and the
inspector UI.

Failure mode: callers should treat a ``None`` return from
:func:`get_redis_client` (or any ``RedisError`` raised by an
:class:`~src.cache.redis_backend.RedisBackend` operation) as "L2 is
unavailable, degrade to L1 only". The orchestrator does this
automatically; CLI/UI surface the failure to the user.

A single sync client is intentional. Phase 12 cache call sites are
sync (``generate_text``, ``embed_text``); when async paths arrive we
will add a parallel ``get_async_redis_client`` returning
``redis.asyncio.Redis`` rather than overload this module.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass

import redis
from redis.exceptions import RedisError

from src.core.config import get_cache_settings

logger = logging.getLogger(__name__)

# Default URL when no setting / env var is present. Matches the
# docker-compose service that Phase 12 ships with. Resolution is
# delegated to :func:`src.core.config.get_cache_settings` so the
# env > settings > default order has a single owner.
DEFAULT_REDIS_URL = "redis://localhost:6379/0"

# Module-level singleton state. The lock protects (re-)creation; the
# client itself is thread-safe under load.
_client_lock = threading.Lock()
_client: redis.Redis | None = None
_client_url: str | None = None


@dataclass(frozen=True)
class RedisHealth:
    """Snapshot returned by :func:`redis_health`.

    ``ok`` is the bottom-line "is L2 usable right now"; ``detail``
    carries the underlying error (or a one-line summary on success)
    for the CLI / inspector UI.
    """

    ok: bool
    url: str
    detail: str
    latency_ms: int | None = None


def _resolve_redis_url() -> str:
    """Resolve via :func:`src.core.config.get_cache_settings` so env >
    settings > default is enforced in exactly one place. Falls back to
    the default URL if settings load fails -- cache must not block
    process startup on a malformed YAML."""
    try:
        return get_cache_settings()["redis_url"]
    except Exception:  # noqa: BLE001 -- settings load failure must not break cache
        return os.environ.get("REDIS_URL") or DEFAULT_REDIS_URL


def get_redis_client(*, force_reload: bool = False) -> redis.Redis | None:
    """Return the process-singleton Redis client, or ``None`` if the
    server is unreachable.

    ``force_reload=True`` drops the cached singleton and recreates it
    from the current env / settings -- used by the CLI when a user
    rotates ``REDIS_URL`` and re-runs ``autoapply redis ping``.

    Any failure -- transport (:class:`~redis.exceptions.RedisError`),
    a malformed URL (``ValueError`` from ``Redis.from_url``), or a
    DNS / socket lookup failure (``OSError``) -- degrades to the
    documented L1-only mode rather than propagating an exception
    that would crash cache-using call sites.
    """
    global _client, _client_url

    desired_url = _resolve_redis_url()
    with _client_lock:
        if force_reload or _client is None or _client_url != desired_url:
            try:
                client = redis.Redis.from_url(
                    desired_url,
                    decode_responses=True,
                    socket_timeout=2.0,
                    socket_connect_timeout=2.0,
                )
                client.ping()
            except (RedisError, ValueError, TypeError, OSError) as exc:
                logger.warning(
                    "Redis unavailable at %s (%s); cache degrades to L1 only.",
                    desired_url,
                    exc,
                )
                _client = None
                _client_url = desired_url
                return None
            _client = client
            _client_url = desired_url
        return _client


def reset_redis_client() -> None:
    """Drop the singleton so the next call rebuilds it. Used by tests
    that swap ``REDIS_URL`` between cases."""
    global _client, _client_url
    with _client_lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:  # noqa: BLE001 -- best-effort teardown
                pass
        _client = None
        _client_url = None


def redis_health() -> RedisHealth:
    """Run a single ``PING`` against the configured Redis URL and
    return a :class:`RedisHealth` snapshot suitable for the CLI.

    Mirrors :func:`get_redis_client` in catching the full set of
    failures (transport, malformed URL, socket lookup) so the CLI
    surfaces "not available" instead of stack-tracing on a typo'd
    ``REDIS_URL``.
    """
    url = _resolve_redis_url()
    import time

    started = time.monotonic()
    try:
        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
        )
        client.ping()
        latency_ms = int((time.monotonic() - started) * 1000)
        client.close()
        return RedisHealth(
            ok=True,
            url=url,
            detail="PONG",
            latency_ms=latency_ms,
        )
    except (RedisError, ValueError, TypeError, OSError) as exc:
        return RedisHealth(ok=False, url=url, detail=str(exc))
