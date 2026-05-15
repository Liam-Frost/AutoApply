"""Phase 14.1 smoke tests for the Celery app wiring.

These guard the D025 configuration commitments (acks_late,
reject_on_worker_lost, prefetch=1, four named queues) so a careless
later edit to :mod:`src.tasks.app` fails loudly. They do NOT start a
broker -- we only inspect the configured Celery object.
"""

from __future__ import annotations

import importlib

import pytest

app_mod = importlib.import_module("src.tasks.app")


def test_celery_app_singleton_is_stable() -> None:
    """``get_celery_app`` must be process-cached so the worker and the
    in-process CLI share the same handle."""
    assert app_mod.get_celery_app() is app_mod.get_celery_app()
    assert app_mod.celery_app is app_mod.get_celery_app()


def test_reliability_commitments_are_set() -> None:
    """If any of these flip silently, Phase 14.10's multi-instance
    promises break."""
    conf = app_mod.celery_app.conf
    assert conf.task_acks_late is True, "task_acks_late must stay True (D025)"
    assert conf.task_reject_on_worker_lost is True, "reject_on_worker_lost required (D025)"
    assert conf.worker_prefetch_multiplier == 1, "long-task workload requires prefetch=1 (D025)"


def test_four_queues_declared() -> None:
    assert app_mod.QUEUES == ("search", "materials", "application", "maintenance")


@pytest.mark.parametrize(
    ("task_name", "expected_queue"),
    [
        ("search.refresh", "search"),
        ("materials.generate", "materials"),
        ("application.prepare", "application"),
        ("application.fill", "application"),
        ("status.sync", "maintenance"),  # status.* falls back -> maintenance
        ("maintenance.cache_eviction", "maintenance"),
        ("totally.unknown", "maintenance"),  # unknown prefix -> maintenance, not lost
    ],
)
def test_router_assigns_each_task_to_a_named_queue(task_name: str, expected_queue: str) -> None:
    route = app_mod._task_router(task_name)
    assert route == {"queue": expected_queue}


def test_default_queue_is_maintenance() -> None:
    """Unrouted tasks must not vanish into a void; they fall back to
    the maintenance queue, which the operator is expected to run."""
    assert app_mod.celery_app.conf.task_default_queue == "maintenance"


def test_redbeat_namespace_is_set() -> None:
    """Phase 14.5/14.10 multi-instance Beat depends on a stable redbeat
    namespace for leader election."""
    conf = app_mod.celery_app.conf
    assert conf["redbeat_key_prefix"] == "autoapply:beat:"
    assert conf["redbeat_redis_url"]  # not empty


def test_serializer_is_json() -> None:
    """JSON only: pickle would let a compromised broker execute
    arbitrary code on the workers."""
    conf = app_mod.celery_app.conf
    assert conf.task_serializer == "json"
    assert conf.result_serializer == "json"
    assert "json" in conf.accept_content
    assert "pickle" not in conf.accept_content


def test_broker_url_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://override:6379/9")
    assert app_mod._resolve_broker_url() == "redis://override:6379/9"


def test_result_backend_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://elsewhere:6379/8")
    assert app_mod._resolve_result_backend() == "redis://elsewhere:6379/8"
