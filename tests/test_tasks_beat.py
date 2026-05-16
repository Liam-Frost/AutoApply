"""Phase 14.5: tests for the Celery Beat schedule.

We assert the *contract*: which entries exist, which task name they
dispatch to, and that the routing options land them on the right
queue. We do not start the Beat process here.
"""

from __future__ import annotations

import importlib

from celery.schedules import crontab

from src.tasks import beat

app_mod = importlib.import_module("src.tasks")  # imports beat.install side-effect


EXPECTED_ENTRIES: set[str] = {
    "daily_search",
    "jd_health_check",
    "application_status_sync",
    "linkedin_cookie_refresh",
    "cache_eviction",
    "gate_expire_sweep",
    # Phase 17.1: end-to-end nightly orchestrator
    "nightly_run",
}


def test_schedule_contains_all_expected_entries() -> None:
    schedule = beat.get_schedule()
    assert set(schedule.keys()) == EXPECTED_ENTRIES


def test_every_entry_has_task_schedule_and_options() -> None:
    for name, entry in beat.get_schedule().items():
        assert "task" in entry, f"{name} missing task"
        assert "schedule" in entry, f"{name} missing schedule"
        assert isinstance(entry["schedule"], crontab), f"{name} schedule must be crontab"
        assert "options" in entry and isinstance(entry["options"], dict)
        assert entry["options"]["queue"] in (
            "search",
            "materials",
            "application",
            "maintenance",
        )


def test_daily_search_lands_on_search_queue() -> None:
    schedule = beat.get_schedule()
    assert schedule["daily_search"]["options"]["queue"] == "search"


def test_maintenance_entries_land_on_maintenance_queue() -> None:
    schedule = beat.get_schedule()
    for name in (
        "jd_health_check",
        "application_status_sync",
        "linkedin_cookie_refresh",
        "cache_eviction",
        "gate_expire_sweep",
    ):
        assert schedule[name]["options"]["queue"] == "maintenance"


def test_install_wires_redbeat_scheduler_into_app() -> None:
    """Multi-instance Beat depends on redbeat's leader election so two
    Beat processes do not double-fire."""
    assert app_mod.celery_app.conf.beat_scheduler == "redbeat.RedBeatScheduler"


def test_install_publishes_schedule_to_app_conf() -> None:
    keys = set(app_mod.celery_app.conf.beat_schedule.keys())
    assert keys == EXPECTED_ENTRIES


def test_install_is_idempotent() -> None:
    """Repeated calls (worker autoreload + reimports) must not blow
    up or change the schedule shape."""
    before = dict(app_mod.celery_app.conf.beat_schedule)
    beat.install(app_mod.celery_app)
    beat.install(app_mod.celery_app)
    after = dict(app_mod.celery_app.conf.beat_schedule)
    assert before.keys() == after.keys()
