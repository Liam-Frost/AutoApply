"""Celery Beat schedule (Phase 14.5).

Replaces the prior APScheduler plan (D021, now superseded by D025).
Beat only enqueues -- business logic never runs in the Beat process.
The redbeat scheduler (configured in :mod:`src.tasks.app` via
``redbeat_redis_url``) provides leader election so multi-instance Beat
does not double-fire (Phase 14.10).

Schedule design:

* ``daily_search`` -- cron-driven nightly search pass. Phase 17 will
  fan this out into per-source ``search.refresh`` children; for now
  the schedule entry exists so 14.7 ``autoapply schedule list`` has
  something to display.
* ``jd_health_check`` -- drives the Phase 13.3 freshness state
  machine's time decay (``project_by_time``: ``active→stale @ 24h``,
  ``stale→unknown @ 72h``, ``unknown→expired @ 7d``). Hourly granularity
  is sufficient since the decay tiers are hours / days.
* ``application_status_sync`` -- polls submitted-but-pending outcomes
  every 6 hours; the actual sync logic lives in 14.6 ``status.sync``.
* ``linkedin_cookie_refresh`` -- daily refresh while the cookie is
  still warm.
* ``cache_eviction`` -- hourly L1+L2 cache hygiene (drops keys whose
  TTL is technically alive but whose underlying source has changed).
* ``gate_expire_sweep`` -- 15-minute sweep that flips
  ``gate_queue`` rows past their TTL to ``expired``.

All entries default to the ``maintenance`` queue; per-task overrides
go through ``options={'queue': '...'}`` so tasks like the search fan-out
land on the ``search`` queue.

This module is import-safe (no Beat lock acquired here); calling
:func:`get_schedule` returns the dict that ``celery beat`` consumes.
"""

from __future__ import annotations

from celery.schedules import crontab

# Per-task options to route Beat-enqueued task to the right queue.
_SEARCH_OPTS: dict[str, object] = {"queue": "search"}
_MAINTENANCE_OPTS: dict[str, object] = {"queue": "maintenance"}
# Phase 17.1: the nightly_run orchestrator is heavy (it fans out into
# materials/application tasks) and belongs on the search queue so
# materials workers don't block on it.
_ORCHESTRATION_OPTS: dict[str, object] = {"queue": "search"}


def get_schedule() -> dict[str, dict[str, object]]:
    """Return the Beat schedule. Kept as a function so callers can
    monkey-patch the entries in tests without mutating module state."""
    return {
        "daily_search": {
            "task": "search.daily_fanout",
            "schedule": crontab(hour=2, minute=0),  # 02:00 UTC every day
            "options": _SEARCH_OPTS,
        },
        # Phase 17.1: end-to-end nightly run. Fires at 23:00 UTC so the
        # full pipeline (search → score → materials.generate →
        # application.prepare) completes overnight and the user finds
        # a populated review queue at the 08:00 digest (Phase 17.6).
        # All kwargs default-friendly so a fresh install with no
        # search_profile_id still produces a report.
        "nightly_run": {
            "task": "orchestration.nightly_run",
            "schedule": crontab(hour=23, minute=0),
            "options": _ORCHESTRATION_OPTS,
        },
        # Phase 17.6: morning digest at 08:00 UTC. Produces the
        # dashboard banner payload + (future hook) desktop
        # notification. Routed to the maintenance queue since it's
        # cheap (one DB query + a directory scan).
        "morning_digest": {
            "task": "notifications.morning_digest",
            "schedule": crontab(hour=8, minute=0),
            "options": _MAINTENANCE_OPTS,
        },
        "jd_health_check": {
            "task": "maintenance.jd_health_check",
            "schedule": crontab(minute=0),  # every hour, on the hour
            "options": _MAINTENANCE_OPTS,
        },
        "application_status_sync": {
            "task": "maintenance.status_sync",
            "schedule": crontab(hour="*/6", minute=15),
            "options": _MAINTENANCE_OPTS,
        },
        "linkedin_cookie_refresh": {
            "task": "maintenance.linkedin_cookie_refresh",
            "schedule": crontab(hour=3, minute=0),  # 03:00 UTC every day
            "options": _MAINTENANCE_OPTS,
        },
        "cache_eviction": {
            "task": "maintenance.cache_eviction",
            "schedule": crontab(minute=30),  # every hour, on :30
            "options": _MAINTENANCE_OPTS,
        },
        "gate_expire_sweep": {
            "task": "maintenance.gate_expire_sweep",
            "schedule": crontab(minute="*/15"),
            "options": _MAINTENANCE_OPTS,
        },
    }


def install(app) -> None:
    """Bind the schedule onto the given Celery app + select the
    redbeat scheduler. Idempotent."""
    app.conf.beat_schedule = get_schedule()
    app.conf.beat_scheduler = "redbeat.RedBeatScheduler"


__all__ = ["get_schedule", "install"]
