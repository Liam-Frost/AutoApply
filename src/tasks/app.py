"""Celery application factory for AutoApply (Phase 14.1).

The Celery app is built lazily so importing :mod:`src.tasks` does not
require a running Redis broker -- tests that only need the task
definitions can import them without paying that cost.

Configuration commitments (D025):

* ``task_acks_late=True`` combined with ``task_reject_on_worker_lost=True``
  guarantees a task killed mid-flight is requeued exactly once instead
  of being silently lost.
* ``worker_prefetch_multiplier=1`` -- AutoApply tasks are minutes-long
  (materials generation, browser fill). The default of 4 would have a
  worker hoard four such jobs while running one, starving siblings.
* Four named queues route by domain: ``search``, ``materials``,
  ``application``, ``maintenance``. ``autoapply worker --queues ...``
  lets the operator scale each independently.
"""

from __future__ import annotations

import os
from functools import lru_cache

from celery import Celery

from src.cache.connection import DEFAULT_REDIS_URL

#: The four queues AutoApply tasks are routed to. ``maintenance`` is
#: the catch-all for cron-driven housekeeping (cache eviction, status
#: sync, cookie refresh).
QUEUES: tuple[str, ...] = ("search", "materials", "application", "maintenance")

#: Default routing map: tasks named ``<prefix>.<verb>`` land on the mapped queue.
#: Unrouted task names fall back to the ``maintenance`` queue.
DEFAULT_ROUTE_PREFIX_QUEUE: dict[str, str] = {
    **{q: q for q in QUEUES},
    "orchestration": "search",
    "notifications": "maintenance",
}


def _resolve_broker_url() -> str:
    """Reuse the cache layer's URL resolution so Celery and the L2
    cache always point at the same Redis instance unless the operator
    explicitly overrides ``CELERY_BROKER_URL``."""
    override = os.environ.get("CELERY_BROKER_URL")
    if override:
        return override
    # Avoid importing get_cache_settings at module top because it
    # touches the YAML loader; defer until first call so module import
    # is side-effect free.
    try:
        from src.cache.connection import _resolve_redis_url

        return _resolve_redis_url()
    except Exception:  # noqa: BLE001 -- broker resolution must not crash import
        return os.environ.get("REDIS_URL") or DEFAULT_REDIS_URL


def _resolve_result_backend() -> str:
    """Celery's result backend is transient -- the authoritative task
    state lives in the Phase 14.2 ``tasks`` Postgres table. Pointing it
    at the same Redis instance is fine; the override knob is
    ``CELERY_RESULT_BACKEND``."""
    return os.environ.get("CELERY_RESULT_BACKEND") or _resolve_broker_url()


def _route_for(name: str) -> dict[str, str]:
    prefix = name.split(".", 1)[0]
    queue = DEFAULT_ROUTE_PREFIX_QUEUE.get(prefix, "maintenance")
    return {"queue": queue}


def _task_router(name: str, *_args: object, **_kwargs: object) -> dict[str, str] | None:
    """Celery's router protocol. Returning ``None`` lets Celery fall
    back to ``task_default_queue``. We always return an explicit queue
    so misnamed tasks land in ``maintenance`` instead of disappearing."""
    return _route_for(name)


def _build_celery_app() -> Celery:
    app = Celery(
        "autoapply",
        broker=_resolve_broker_url(),
        backend=_resolve_result_backend(),
        # Lazy import path so worker bootstrap finds task modules.
        # Each Phase 14.6 task module is registered here.
        include=[
            "src.tasks.tasks",
        ],
    )
    app.conf.update(
        # ---- Reliability (D025 commitments) ----
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_default_queue="maintenance",
        task_default_exchange="maintenance",
        task_default_routing_key="maintenance",
        task_routes=(_task_router,),
        # ---- Serialization ----
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        # ---- Time handling ----
        timezone="UTC",
        enable_utc=True,
        # ---- Result backend hygiene. Celery's result rows are not
        # the audit source of truth (see Phase 14.2). 1-day TTL is
        # enough for callers that synchronously await; longer history
        # lives in Postgres.
        result_expires=86400,
        # ---- redbeat config (Phase 14.5 / 14.10). The scheduler
        # binary is opted into via ``celery beat -S redbeat.RedBeatScheduler``;
        # we set the namespace here so multi-instance Beat acquires
        # the same leader-election lock.
        redbeat_redis_url=_resolve_broker_url(),
        redbeat_key_prefix="autoapply:beat:",
        redbeat_lock_timeout=60,
    )
    return app


@lru_cache(maxsize=1)
def get_celery_app() -> Celery:
    """Process-singleton accessor used by both the worker entry point
    and the in-process schedulers (the CLI's ``autoapply tasks`` reads
    state via this same app)."""
    return _build_celery_app()


#: Module-level handle Celery's worker autodiscovers via ``-A src.tasks``.
celery_app: Celery = get_celery_app()


__all__ = [
    "QUEUES",
    "celery_app",
    "get_celery_app",
]
