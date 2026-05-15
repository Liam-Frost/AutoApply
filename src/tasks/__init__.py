"""AutoApply task queue (Phase 14).

This package layers a thin AutoApply-specific wrapper on top of Celery:

  * :mod:`src.tasks.app` defines the Celery application + queue routing.
  * :mod:`src.tasks.base` defines :class:`AutoApplyTask`, the base class
    that injects tenant context, enforces idempotency keys, and routes
    bounded agent invocations into the Phase 8 trace store and the
    Postgres-backed gate queue.
  * :mod:`src.tasks.audit` mirrors Celery task state into the
    ``tasks`` Postgres table (the durable source of truth; Celery's
    result backend is treated as transient).
  * :mod:`src.tasks.beat` declares the Celery Beat schedule that
    replaces the earlier APScheduler plan.

The contract (D023, refined by D025): Celery owns the queue layer
(transport, claim, ack/nack, retry policy, worker lifecycle); AutoApply
owns the agent boundary, HITL state, audit trail, and tenant scoping.
"""

from __future__ import annotations

# Importing :mod:`src.tasks.audit` registers the Celery signal handlers
# that mirror task state into the Postgres ``tasks`` table (Phase 14.2).
# Workers and the in-process CLI both import :mod:`src.tasks`, so the
# handlers are always wired.
from src.tasks import audit  # noqa: F401 -- side-effect import for signal registration
from src.tasks.app import celery_app

__all__ = ["celery_app"]
