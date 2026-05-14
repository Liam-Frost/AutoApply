"""Cache abstractions: backend ABC, namespace TTL policy, version stamp.

The :class:`Cache` orchestrator in ``src/cache/cache.py`` consumes any
:class:`CacheBackend` implementation, which means the L1 in-process
LRU and the L2 Redis backend can be unit-tested in isolation and
swapped at runtime (e.g. tests substitute :class:`~src.cache.lru.LRUBackend`
for L2 when Redis is unavailable).

Design notes:

* **Keys are opaque strings.** The orchestrator handles namespace +
  version prefixing; backends just see the final composed key.
* **Values are JSON-serialisable.** Phase 12.1 ships JSON serialisation
  per the user's chosen tradeoff -- human-readable in ``redis-cli``,
  no pickle attack surface, slightly larger payloads than msgpack.
  Bytes-typed callers (image data, etc.) are out of scope until a
  future sub-phase needs them.
* **TTLs are mandatory.** Cache entries without expiry are an
  operational liability (no eviction, no rotation). The
  :data:`NAMESPACE_TTLS` table defines the policy in one place so
  reviewers can see the eviction posture at a glance.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

# Version stamp prefixed onto every key. Bumping this is the
# rolling-deploy escape hatch: when a serialisation format or a
# value schema changes, bump the version and the old keys become
# inaccessible (and naturally expire). Keep this short -- it is
# repeated on every key in Redis.
CACHE_VERSION = "v1"

# Per-namespace TTL policy (seconds). The orchestrator looks up the
# TTL by namespace at write time; callers do not specify TTLs
# directly so the policy stays centralised and reviewable.
#
# Rationale for each entry:
#   llm:       7d  -- prompt+model+system+temperature is a stable
#                     idempotent key; cost-saved per hit is large
#                     enough that 7d retention pays for itself.
#   embedding: 30d -- embeddings change only on model upgrades, which
#                     bump CACHE_VERSION anyway.
#   response:  5m  -- short-lived API response cache for the web layer
#                     (e.g. /api/providers/health snapshot); long
#                     enough to deduplicate UI polls, short enough that
#                     mutations show up quickly.
NAMESPACE_TTLS: dict[str, int] = {
    "llm": 7 * 24 * 3600,
    "embedding": 30 * 24 * 3600,
    "response": 5 * 60,
}

# TTL used when a caller writes to a namespace that the policy table
# doesn't recognise. Deliberately short -- forcing the policy table
# to grow consciously rather than letting ad-hoc namespaces inherit
# a long TTL by accident.
DEFAULT_NAMESPACE_TTL = 5 * 60


class CacheBackend(ABC):
    """Plain key-value backend with TTL-bound writes.

    The orchestrator composes the full key (including version stamp
    and namespace prefix) before calling these methods, so backends
    only deal with opaque strings.
    """

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Return the stored value or ``None`` if the key is missing
        or has expired. ``None`` is also returned on transport errors
        for the L2 backend; the orchestrator treats those as misses."""

    @abstractmethod
    def set(self, key: str, value: Any, ttl: int) -> None:
        """Write ``value`` under ``key`` with a TTL in seconds.

        Implementations must reject ``ttl <= 0`` -- a non-expiring
        entry is always a policy bug given the rationale above.
        """

    @abstractmethod
    def delete(self, key: str) -> None:
        """Drop ``key`` if present. No-op if missing."""

    @abstractmethod
    def clear_namespace(self, prefix: str) -> int:
        """Delete every key beginning with ``prefix``. Returns the
        count of keys removed so the inspector UI can show what
        actually happened."""

    def get_with_ttl(self, key: str) -> tuple[Any | None, int]:
        """Return ``(value, remaining_ttl_seconds)`` for ``key``.

        Default implementation falls back to :meth:`get` and reports
        ``-1`` for the TTL meaning "unknown". The L2 Redis backend
        overrides this to use a pipeline so the L1 promotion path in
        the orchestrator can preserve the *remaining* TTL instead of
        re-extending the entry to a full namespace window -- otherwise
        an entry close to expiry in Redis would keep serving from L1
        for another full TTL window after Redis dropped it.
        """
        value = self.get(key)
        if value is None:
            return None, 0
        return value, -1


# Namespaces must be plain identifiers. The bound matters because the
# string flows into Redis ``SCAN`` patterns, where unescaped glob
# metacharacters (``*``, ``?``, ``[``, ``]``) would match keys outside
# the intended namespace. Rejecting them at the boundary is simpler
# than escaping at every call site and matches how the rest of the
# codebase uses namespaces (short identifier-like strings).
_NAMESPACE_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def validate_namespace(namespace: str) -> str:
    """Enforce the namespace shape used by :func:`make_key` and the
    Redis SCAN paths. Raises :class:`ValueError` for anything that
    could be misread as a glob.

    Returning the validated value lets callers do ``ns =
    validate_namespace(ns)`` in one line.
    """
    if not isinstance(namespace, str) or not _NAMESPACE_RE.match(namespace):
        raise ValueError(
            f"namespace {namespace!r} must match {_NAMESPACE_RE.pattern}; "
            "got something that could be a Redis glob pattern."
        )
    return namespace


def make_key(namespace: str, key: str, *, version: str = CACHE_VERSION) -> str:
    """Compose ``{version}:{namespace}:{key}``. Centralised so the
    orchestrator and the inspector UI never disagree on the layout.

    The namespace is validated to be a plain identifier so a caller
    passing ``*`` cannot turn this into a glob pattern further down.
    """
    validate_namespace(namespace)
    return f"{version}:{namespace}:{key}"


def namespace_prefix(namespace: str, *, version: str = CACHE_VERSION) -> str:
    """Prefix used by ``clear_namespace`` / Redis ``SCAN``."""
    validate_namespace(namespace)
    return f"{version}:{namespace}:"
