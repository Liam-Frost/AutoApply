"""Phase 14.10: Postgres advisory-lock backstop for multi-instance safety.

Celery and redbeat handle the *normal* multi-instance safety:

* Celery: a task in the queue is claimed by exactly one worker.
* redbeat: Beat schedule store + leader-election so two Beat processes
  cannot both fire the same cron tick.

This module is the *defense-in-depth* layer for the edge cases those
two do not cover -- chiefly, code that wants to run a critical section
across the entire deployment, regardless of who started it (a long
materials.generate that must not run twice for the same job, a
nightly_run orchestrator entry point, a maintenance task that mutates
shared state).

Postgres ``pg_try_advisory_xact_lock`` is the right primitive: it is
held only for the duration of the transaction, automatically releases
on rollback / connection drop, and is cheap relative to the lock
contention rates we'd see in this app. The key is a 64-bit signed
integer derived from a stable string hash.

Usage::

    with advisory_lock(session, "nightly_run:default") as acquired:
        if not acquired:
            return  # somebody else is doing it
        ...

The lock is *non-blocking*: callers decide whether to no-op or retry.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _key_to_int(key: str) -> int:
    """Hash an arbitrary string into a stable 63-bit signed integer
    so it fits the ``bigint`` Postgres advisory-lock keyspace
    (signed 64-bit; we use the low 63 bits to stay non-negative)."""
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    raw = int.from_bytes(digest[:8], "big", signed=False)
    return raw & ((1 << 63) - 1)


@contextmanager
def advisory_lock(session: Session, key: str) -> Iterator[bool]:
    """Try to acquire a Postgres transaction-scoped advisory lock.

    Yields ``True`` if we hold the lock for the duration of the
    enclosing transaction, ``False`` if another process holds it.
    Lock release is automatic on commit / rollback / connection drop;
    callers do not need an explicit ``unlock`` call.

    The session's autocommit state must be off (the default). If the
    caller is using ``begin()`` blocks, the lock survives until that
    block ends.
    """
    int_key = _key_to_int(key)
    try:
        row = session.execute(
            text("SELECT pg_try_advisory_xact_lock(:k)"),
            {"k": int_key},
        ).scalar()
        acquired = bool(row)
        if not acquired:
            logger.debug("advisory lock %s busy (key_int=%s)", key, int_key)
        yield acquired
    except Exception:
        logger.exception("advisory lock acquisition failed for %s", key)
        raise


def hash_for_key(key: str) -> int:
    """Exposed for tests + diagnostics. Should not be called from
    production code; use :func:`advisory_lock` instead."""
    return _key_to_int(key)


__all__ = ["advisory_lock", "hash_for_key"]
