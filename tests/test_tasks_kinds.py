"""Phase 14.6: smoke tests for the task kind catalog.

We run each task in Celery's ``eager`` mode (no broker, no worker
process) and verify:

* the task is registered with the right name,
* the task lands on the right queue per the 14.1 router,
* the payload schema rejects malformed input as a terminal failure
  (TypeError -- Celery's retry layer treats it as non-retryable),
* the happy path returns a structured stub result.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from src.tasks import tasks as task_kinds
from src.tasks.app import _task_router, celery_app


@pytest.fixture(autouse=True)
def _eager(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)
    monkeypatch.setattr(celery_app.conf, "task_eager_propagates", True)


# ---- Registration + routing ------------------------------------------


@pytest.mark.parametrize("name", task_kinds.KNOWN_TASK_NAMES)
def test_task_registered_in_celery_app(name: str) -> None:
    assert name in celery_app.tasks, f"task {name} not registered"


@pytest.mark.parametrize(
    ("task_name", "queue"),
    [
        ("search.refresh", "search"),
        ("search.daily_fanout", "search"),
        ("jobs.enrich", "maintenance"),
        ("materials.generate", "materials"),
        ("application.prepare", "application"),
        ("application.fill", "application"),
        ("application.submit", "application"),
        ("maintenance.status_sync", "maintenance"),
        ("maintenance.cache_eviction", "maintenance"),
    ],
)
def test_router_assigns_each_task_kind_to_named_queue(
    task_name: str, queue: str
) -> None:
    assert _task_router(task_name) == {"queue": queue}


# ---- Payload validation ---------------------------------------------


def test_search_refresh_rejects_empty_payload() -> None:
    # Eager mode + propagation surfaces our TypeError raised on
    # ValidationError.
    with pytest.raises((TypeError, ValidationError)):
        task_kinds.search_refresh.apply(kwargs={}).get()


def test_search_refresh_accepts_valid_payload() -> None:
    out = task_kinds.search_refresh.apply(
        kwargs={"query_id": "q1", "source": "greenhouse"}
    ).get()
    assert out["task"] == "search.refresh"
    assert out["query_id"] == "q1"
    assert out["source"] == "greenhouse"


def test_materials_generate_defaults_to_resume_and_cover_letter() -> None:
    out = task_kinds.materials_generate.apply(
        kwargs={"job_id": "job-1"}
    ).get()
    assert out["document_types"] == ["resume", "cover_letter"]


def test_materials_generate_rejects_missing_job_id() -> None:
    with pytest.raises((TypeError, ValidationError)):
        task_kinds.materials_generate.apply(kwargs={}).get()


def test_application_submit_round_trip() -> None:
    out = task_kinds.application_submit.apply(
        kwargs={"application_id": "app-99"}
    ).get()
    assert out["application_id"] == "app-99"


# ---- Beat-driven stubs --------------------------------------------------


@pytest.mark.parametrize(
    "task_fn",
    [
        task_kinds.search_daily_fanout,
        task_kinds.jd_health_check,
        task_kinds.linkedin_cookie_refresh,
        task_kinds.cache_eviction,
        task_kinds.gate_expire_sweep,
    ],
)
def test_beat_driven_stubs_return_stubbed_status(task_fn: Any) -> None:
    out = task_fn.apply().get()
    assert out["status"] == "stubbed"


def test_status_sync_accepts_optional_application_id() -> None:
    """No payload at all is valid (sweeps all apps); explicit id
    targets one."""
    out_a = task_kinds.status_sync.apply(kwargs={}).get()
    out_b = task_kinds.status_sync.apply(kwargs={"application_id": "x"}).get()
    assert out_a["task"] == "maintenance.status_sync"
    assert out_b["task"] == "maintenance.status_sync"
