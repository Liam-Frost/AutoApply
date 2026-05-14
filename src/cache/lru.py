"""In-process LRU backend used as L1 in front of Redis.

Why a hand-rolled LRU instead of ``functools.lru_cache`` or
``cachetools``:

* ``functools.lru_cache`` is per-function; we need a shared store
  keyed by string.
* ``cachetools`` is fine but pulls a transitive dep. The behaviour
  we need (capacity-bounded, TTL-bounded, thread-safe, with
  ``clear_namespace`` prefix scan) is ~70 lines of Python on top of
  :class:`collections.OrderedDict`.

Thread-safety: every mutation goes through ``self._lock`` so a
multi-threaded FastAPI worker (or two pytest threads) cannot race
on eviction. Reads also take the lock because moving an entry to
the MRU end is itself a mutation.

Expiry is checked on every read; expired entries are deleted lazily.
There is no background sweeper -- the LRU eviction handles the
worst-case memory bound, and the policy table TTLs keep individual
entries from sticking around forever.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

from src.cache.base import CacheBackend

# Default capacity tuned for "hot prompts" without hogging memory.
# A real LLM prompt + response pair runs ~5--20 KB serialised, so
# 1024 entries is roughly 5--20 MB at the high end. Tweak via the
# constructor if a deployment knows its working set is larger.
DEFAULT_MAX_ENTRIES = 1024


class LRUBackend(CacheBackend):
    """Thread-safe LRU with TTL and prefix-scan invalidation."""

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        # OrderedDict preserves insertion order; ``move_to_end`` on
        # read promotes a key to MRU. Eviction pops from the LRU end
        # via ``popitem(last=False)``.
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.RLock()

    # ----- CacheBackend interface -----

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= time.monotonic():
                # Lazy eviction: tidy up so callers don't keep
                # observing a stale slot.
                del self._store[key]
                return None
            # Promote to MRU.
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        if ttl <= 0:
            # See the rationale in base.py: ``CacheBackend.set`` must
            # reject zero/negative TTLs to make the policy enforceable.
            raise ValueError(f"ttl must be positive, got {ttl!r}")
        expires_at = time.monotonic() + ttl
        with self._lock:
            self._store[key] = (expires_at, value)
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear_namespace(self, prefix: str) -> int:
        with self._lock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]
            return len(keys)

    # ----- introspection (used by the cache inspector and tests) -----

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def keys(self) -> list[str]:
        """Snapshot of the current keys, MRU last. The inspector UI
        calls this to render a sample; tests use it for assertions."""
        with self._lock:
            return list(self._store.keys())
