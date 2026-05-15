"""Phase 14.8: web route tests for /api/tasks /api/schedule /api/gate.

Uses FastAPI's TestClient against the real route module (no broker
involved -- we patch ``celery_app.send_task`` so the route can be
asserted without dispatching). Database fixtures use the live dev
Postgres, cleaning up rows on a per-test tenant prefix.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import get_db_url, load_config
from src.core.models import GateRequest, TaskRecord
from src.tasks.context import tenant_header_name
from src.web.routes.tasks import router as tasks_router


@pytest.fixture(scope="module")
def engine():
    return create_engine(get_db_url(load_config()))


@pytest.fixture
def db_session(engine) -> Session:
    factory = sessionmaker(bind=engine)
    s = factory()
    yield s
    s.execute(delete(GateRequest).where(GateRequest.tenant_id.like("test-web-%")))
    s.execute(delete(TaskRecord).where(TaskRecord.tenant_id.like("test-web-%")))
    s.commit()
    s.close()


@pytest.fixture
def app(engine) -> FastAPI:
    """Mounts only the Phase 14.8 router so we do not depend on the
    full SPA app factory at test time."""
    a = FastAPI()
    a.include_router(tasks_router)
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---- /api/tasks -------------------------------------------------------


def test_list_tasks_scopes_by_tenant(client: TestClient, db_session: Session) -> None:
    db_session.add(
        TaskRecord(
            tenant_id="test-web-tasks-a",
            kind="materials.generate",
            queue="materials",
            status="queued",
        )
    )
    db_session.add(
        TaskRecord(
            tenant_id="test-web-tasks-b",
            kind="materials.generate",
            queue="materials",
            status="queued",
        )
    )
    db_session.commit()

    r = client.get("/api/tasks", headers={tenant_header_name(): "test-web-tasks-a"})
    assert r.status_code == 200
    rows = r.json()["items"]
    tenants = {row["tenant_id"] for row in rows}
    assert tenants == {"test-web-tasks-a"}


def test_list_tasks_filters_by_status_and_kind(
    client: TestClient, db_session: Session
) -> None:
    for kind, status in [
        ("materials.generate", "queued"),
        ("materials.generate", "failed"),
        ("search.refresh", "failed"),
    ]:
        db_session.add(
            TaskRecord(
                tenant_id="test-web-filter",
                kind=kind,
                queue="materials" if "mat" in kind else "search",
                status=status,
            )
        )
    db_session.commit()

    r = client.get(
        "/api/tasks",
        params={"status": "failed", "kind": "materials.generate"},
        headers={tenant_header_name(): "test-web-filter"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "materials.generate"
    assert items[0]["status"] == "failed"


def test_get_task_returns_404_for_other_tenant(
    client: TestClient, db_session: Session
) -> None:
    row = TaskRecord(
        tenant_id="test-web-tenant-x",
        kind="search.refresh",
        queue="search",
        status="queued",
    )
    db_session.add(row)
    db_session.commit()

    r = client.get(
        f"/api/tasks/{row.id}",
        headers={tenant_header_name(): "test-web-tenant-y"},
    )
    assert r.status_code == 404


def test_cancel_only_works_on_queued(client: TestClient, db_session: Session) -> None:
    row = TaskRecord(
        tenant_id="test-web-cancel",
        kind="search.refresh",
        queue="search",
        status="running",
    )
    db_session.add(row)
    db_session.commit()

    r = client.post(
        f"/api/tasks/{row.id}/cancel",
        headers={tenant_header_name(): "test-web-cancel"},
    )
    assert r.status_code == 409


def test_cancel_flips_queued_to_cancelled(
    client: TestClient, db_session: Session
) -> None:
    row = TaskRecord(
        tenant_id="test-web-cancel-ok",
        kind="search.refresh",
        queue="search",
        status="queued",
    )
    db_session.add(row)
    db_session.commit()

    r = client.post(
        f"/api/tasks/{row.id}/cancel",
        headers={tenant_header_name(): "test-web-cancel-ok"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


def test_retry_only_works_on_failed_or_cancelled(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []
    from src.tasks import celery_app

    def _capture(name: str, **kwargs: Any) -> None:
        captured.append({"name": name, **kwargs})

    monkeypatch.setattr(celery_app, "send_task", _capture)

    row = TaskRecord(
        tenant_id="test-web-retry",
        kind="search.refresh",
        queue="search",
        status="failed",
        payload={"query_id": "q-1"},
    )
    db_session.add(row)
    db_session.commit()

    r = client.post(
        f"/api/tasks/{row.id}/retry",
        headers={tenant_header_name(): "test-web-retry"},
    )
    assert r.status_code == 200
    assert captured and captured[0]["name"] == "search.refresh"
    assert captured[0]["kwargs"] == {"query_id": "q-1"}


# ---- /api/schedule ----------------------------------------------------


def test_list_schedule_includes_all_six_entries(client: TestClient) -> None:
    r = client.get("/api/schedule")
    assert r.status_code == 200
    names = {entry["name"] for entry in r.json()}
    assert {
        "daily_search",
        "jd_health_check",
        "application_status_sync",
        "linkedin_cookie_refresh",
        "cache_eviction",
        "gate_expire_sweep",
    } <= names


def test_schedule_run_now_dispatches(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[dict[str, Any]] = []
    from src.tasks import celery_app

    monkeypatch.setattr(
        celery_app,
        "send_task",
        lambda name, **kw: captured.append({"name": name, **kw}),
    )
    r = client.post("/api/schedule/cache_eviction/run-now")
    assert r.status_code == 200
    assert captured[0]["name"] == "maintenance.cache_eviction"


def test_schedule_run_now_404_on_unknown_entry(client: TestClient) -> None:
    r = client.post("/api/schedule/ghost/run-now")
    assert r.status_code == 404


# ---- /api/gate -------------------------------------------------------


def test_list_gate_returns_only_pending_for_tenant(
    client: TestClient, db_session: Session
) -> None:
    from src.tasks import gate

    gate.open_request(
        db_session, kind="application.submit", summary="a", tenant_id="test-web-gate-a"
    )
    gate.open_request(
        db_session, kind="application.submit", summary="b", tenant_id="test-web-gate-a"
    )
    gate.open_request(
        db_session, kind="application.submit", summary="c", tenant_id="test-web-gate-b"
    )
    db_session.commit()

    r = client.get("/api/gate", headers={tenant_header_name(): "test-web-gate-a"})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert {row["tenant_id"] for row in rows} == {"test-web-gate-a"}


def test_approve_transitions_row(
    client: TestClient, db_session: Session
) -> None:
    from src.tasks import gate

    row = gate.open_request(
        db_session,
        kind="application.submit",
        summary="approve me",
        tenant_id="test-web-approve",
    )
    db_session.commit()

    r = client.post(
        f"/api/gate/{row.id}/approve",
        json={"decided_by": "liam", "reason": "ok"},
        headers={tenant_header_name(): "test-web-approve"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert body["decided_by"] == "liam"


def test_double_approve_returns_200_with_existing_decision(
    client: TestClient, db_session: Session
) -> None:
    from src.tasks import gate

    row = gate.open_request(
        db_session,
        kind="application.submit",
        summary="x",
        tenant_id="test-web-doubleapprove",
    )
    db_session.commit()

    r1 = client.post(
        f"/api/gate/{row.id}/approve",
        json={"decided_by": "liam"},
        headers={tenant_header_name(): "test-web-doubleapprove"},
    )
    r2 = client.post(
        f"/api/gate/{row.id}/approve",
        json={"decided_by": "liam2"},
        headers={tenant_header_name(): "test-web-doubleapprove"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json()["status"] == "approved"


def test_approve_after_reject_409s(client: TestClient, db_session: Session) -> None:
    from src.tasks import gate

    row = gate.open_request(
        db_session,
        kind="application.submit",
        summary="x",
        tenant_id="test-web-conflict",
    )
    db_session.commit()

    client.post(
        f"/api/gate/{row.id}/reject",
        json={"decided_by": "liam"},
        headers={tenant_header_name(): "test-web-conflict"},
    )
    r = client.post(
        f"/api/gate/{row.id}/approve",
        json={"decided_by": "liam"},
        headers={tenant_header_name(): "test-web-conflict"},
    )
    assert r.status_code == 409


def test_gate_cross_tenant_isolation(
    client: TestClient, db_session: Session
) -> None:
    from src.tasks import gate

    row = gate.open_request(
        db_session,
        kind="application.submit",
        summary="x",
        tenant_id="test-web-iso-a",
    )
    db_session.commit()
    r = client.get(
        f"/api/gate/{row.id}",
        headers={tenant_header_name(): "test-web-iso-b"},
    )
    assert r.status_code == 404
