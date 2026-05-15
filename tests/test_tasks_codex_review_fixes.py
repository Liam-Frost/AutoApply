"""Phase 14 codex-review fix verification.

The Phase 14.10-close codex review surfaced four issues:

* P1: ``/api/tasks/{id}/cancel`` only flipped the audit row -- it did
  not revoke the broker message, so a worker still picked the task up
  and the prerun handler put it back to ``running``.
* P2: ``/api/tasks/{id}/retry``, ``autoapply tasks retry``, and Celery
  Beat all dispatched tasks without pre-creating a ``TaskRecord``;
  the signal handlers only update existing rows, so those dispatches
  were invisible to ``/api/tasks`` and ``autoapply tasks list``.

These tests pin the fixes:

* The cancel routes call ``celery_app.control.revoke``.
* The ``before_task_publish`` signal creates a row for any dispatch
  that does not carry the ``AUDIT_OK_HEADER`` deduplication flag.
* The prerun handler refuses to transition a ``cancelled`` row back to
  ``running`` (defense-in-depth for the race where revoke arrives
  after the worker claimed the message).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import get_db_url, load_config
from src.core.models import TaskRecord
from src.tasks import audit
from src.tasks.audit import (
    AUDIT_OK_HEADER,
    TENANT_HEADER,
    before_task_publish_handler,
    task_failure_handler,
    task_postrun_handler,
    task_prerun_handler,
    task_retry_handler,
)

# ---- DB fixture ------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    return create_engine(get_db_url(load_config()))


@pytest.fixture
def db_session(engine) -> Session:
    factory = sessionmaker(bind=engine)
    s = factory()
    yield s
    s.execute(delete(TaskRecord).where(TaskRecord.tenant_id.like("test-codex-%")))
    s.commit()
    s.close()


@pytest.fixture
def session_patch(monkeypatch: pytest.MonkeyPatch, db_session: Session):
    """Make the audit handlers commit on the test's session so the
    rows they write are visible to the assertions."""
    monkeypatch.setattr(audit, "_session_factory", lambda: db_session)
    yield


# ---- P2: before_task_publish writes a row when AUDIT_OK_HEADER missing


def test_publish_handler_creates_audit_row_for_beat_dispatch(
    session_patch: None, db_session: Session
) -> None:
    """Beat fires apply_async without AUDIT_OK_HEADER -- the publish
    handler must materialise the audit row so operators see the
    scheduled work in /api/tasks."""
    before_task_publish_handler(
        sender="maintenance.cache_eviction",
        body=[[], {}, {}],
        headers={
            "id": "celery-id-beat-1",
            TENANT_HEADER: "test-codex-beat",
        },
        routing_key="maintenance",
        properties={},
    )

    row = audit.find_by_celery_id(db_session, "celery-id-beat-1")
    assert row is not None
    assert row.kind == "maintenance.cache_eviction"
    assert row.tenant_id == "test-codex-beat"
    assert row.queue == "maintenance"
    assert row.status == "queued"


def test_publish_handler_skips_when_audit_ok_header_present(
    session_patch: None, db_session: Session
) -> None:
    """AutoApplyTask.enqueue sets AUDIT_OK_HEADER because it has
    already written the row -- a duplicate insert would violate the
    one-row-per-celery-task-id invariant."""
    before_task_publish_handler(
        sender="materials.generate",
        body=[[], {"job_id": "x"}, {}],
        headers={
            "id": "celery-id-skip-1",
            AUDIT_OK_HEADER: "1",
            TENANT_HEADER: "test-codex-skip",
        },
        routing_key="materials",
        properties={},
    )
    assert audit.find_by_celery_id(db_session, "celery-id-skip-1") is None


def test_publish_handler_captures_payload_from_protocol_2_body(
    session_patch: None, db_session: Session
) -> None:
    """Celery's protocol-2 JSON puts the body as [args, kwargs, options].
    The audit row must store kwargs as the payload so retry / inspect
    can reproduce the dispatch."""
    before_task_publish_handler(
        sender="search.refresh",
        body=[[], {"query_id": "q-9", "source": "linkedin"}, {}],
        headers={"id": "celery-id-body-1", TENANT_HEADER: "test-codex-body"},
        routing_key="search",
        properties={},
    )
    row = audit.find_by_celery_id(db_session, "celery-id-body-1")
    assert row is not None
    assert row.payload == {"query_id": "q-9", "source": "linkedin"}


def test_publish_handler_no_op_on_missing_task_id(
    session_patch: None, db_session: Session
) -> None:
    """A dispatch with no recoverable task id (rare; some custom
    transports) is skipped rather than written as a rootless row."""
    before = db_session.query(TaskRecord).count()
    before_task_publish_handler(
        sender="some.task",
        body=[[], {}, {}],
        headers={},
        routing_key="maintenance",
        properties={},
    )
    after = db_session.query(TaskRecord).count()
    assert before == after


def test_publish_handler_does_not_double_create_when_row_exists(
    session_patch: None, db_session: Session
) -> None:
    """Defensive: if some other caller already wrote a row with the
    same celery_task_id (race), do not insert a duplicate."""
    db_session.add(
        TaskRecord(
            tenant_id="test-codex-dup",
            celery_task_id="celery-id-dup",
            kind="prepared.kind",
            queue="maintenance",
            status="queued",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    before_task_publish_handler(
        sender="some.other.kind",
        body=[[], {}, {}],
        headers={"id": "celery-id-dup", TENANT_HEADER: "test-codex-dup"},
        routing_key="maintenance",
        properties={},
    )
    rows = (
        db_session.query(TaskRecord)
        .filter(TaskRecord.celery_task_id == "celery-id-dup")
        .all()
    )
    assert len(rows) == 1
    assert rows[0].kind == "prepared.kind"  # original, not overwritten


# ---- P1: prerun handler refuses to flip cancelled -> running --------


def test_prerun_handler_preserves_cancelled_status(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the operator cancelled the task and the broker revoke racing
    against worker claim arrives a beat too late, the prerun handler
    must NOT undo the operator's intent by flipping the row back to
    running."""
    # _safe_update opens its own session; let it talk to the real DB.
    monkeypatch.setattr(
        audit, "_session_factory", lambda: sessionmaker(bind=engine)()
    )
    setup = sessionmaker(bind=engine)()
    try:
        row = TaskRecord(
            tenant_id="test-codex-cancel-race",
            celery_task_id="celery-cancel-race-1",
            kind="search.refresh",
            queue="search",
            status="cancelled",
            attempts=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        setup.add(row)
        setup.commit()
        row_id = row.id
    finally:
        setup.close()

    task_prerun_handler(task_id="celery-cancel-race-1")

    verify = sessionmaker(bind=engine)()
    try:
        observed = verify.get(TaskRecord, row_id)
        assert observed is not None
        assert observed.status == "cancelled"
        assert observed.attempts == 0
    finally:
        verify.execute(delete(TaskRecord).where(TaskRecord.id == row_id))
        verify.commit()
        verify.close()


def test_prerun_handler_still_advances_normal_queued_to_running(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cancelled-guard must not regress the happy path: a queued
    task picked up by a worker still becomes running."""
    monkeypatch.setattr(
        audit, "_session_factory", lambda: sessionmaker(bind=engine)()
    )
    setup = sessionmaker(bind=engine)()
    try:
        row = TaskRecord(
            tenant_id="test-codex-normal-run",
            celery_task_id="celery-normal-1",
            kind="materials.generate",
            queue="materials",
            status="queued",
            attempts=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        setup.add(row)
        setup.commit()
        row_id = row.id
    finally:
        setup.close()

    task_prerun_handler(task_id="celery-normal-1")

    verify = sessionmaker(bind=engine)()
    try:
        observed = verify.get(TaskRecord, row_id)
        assert observed is not None
        assert observed.status == "running"
        assert observed.attempts == 1
    finally:
        verify.execute(delete(TaskRecord).where(TaskRecord.id == row_id))
        verify.commit()
        verify.close()


# ---- P2 (round 2): terminal handlers must also leave cancelled alone


def _make_cancelled_row(engine, celery_task_id: str, tenant_suffix: str) -> Any:
    s = sessionmaker(bind=engine)()
    try:
        row = TaskRecord(
            tenant_id=f"test-codex-{tenant_suffix}",
            celery_task_id=celery_task_id,
            kind="application.submit",
            queue="application",
            status="cancelled",
            attempts=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        s.add(row)
        s.commit()
        return row.id
    finally:
        s.close()


def _assert_still_cancelled(engine, row_id: Any) -> None:
    verify = sessionmaker(bind=engine)()
    try:
        observed = verify.get(TaskRecord, row_id)
        assert observed is not None
        assert observed.status == "cancelled", (
            f"expected status to stay cancelled, got {observed.status}"
        )
    finally:
        verify.execute(delete(TaskRecord).where(TaskRecord.id == row_id))
        verify.commit()
        verify.close()


def test_postrun_handler_preserves_cancelled_status(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even if Celery reports SUCCESS for a cancelled task (the worker
    raced the revoke), the audit row stays cancelled. The side effect
    of the body running is unavoidable with Celery's at-least-once
    semantics, but the audit log must reflect operator intent."""
    monkeypatch.setattr(
        audit, "_session_factory", lambda: sessionmaker(bind=engine)()
    )
    row_id = _make_cancelled_row(engine, "celery-cancel-postrun", "cancel-post")
    task_postrun_handler(task_id="celery-cancel-postrun", state="SUCCESS")
    _assert_still_cancelled(engine, row_id)


def test_failure_handler_preserves_cancelled_status(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        audit, "_session_factory", lambda: sessionmaker(bind=engine)()
    )
    row_id = _make_cancelled_row(engine, "celery-cancel-fail", "cancel-fail")
    task_failure_handler(
        task_id="celery-cancel-fail", exception=RuntimeError("boom")
    )
    _assert_still_cancelled(engine, row_id)


def test_retry_handler_preserves_cancelled_status(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        audit, "_session_factory", lambda: sessionmaker(bind=engine)()
    )
    row_id = _make_cancelled_row(engine, "celery-cancel-retry", "cancel-retry")

    class _Req:
        id = "celery-cancel-retry"

    task_retry_handler(request=_Req(), reason=RuntimeError("transient"))
    _assert_still_cancelled(engine, row_id)


# ---- P1: cancel route revokes the broker message --------------------


def test_cancel_route_calls_celery_revoke(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    """Pin that the cancel route forwards to celery_app.control.revoke
    with terminate=False (kill on a running task is NOT the intent;
    cancel only applies to queued)."""
    from src.tasks import celery_app

    captured: list[dict[str, Any]] = []

    class _FakeControl:
        def revoke(self, task_id: str, terminate: bool = False) -> None:
            captured.append({"task_id": task_id, "terminate": terminate})

    monkeypatch.setattr(celery_app, "control", _FakeControl())

    row = TaskRecord(
        tenant_id="test-codex-cancel-revoke",
        celery_task_id="celery-revoke-1",
        kind="application.submit",
        queue="application",
        status="queued",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(row)
    db_session.commit()

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.web.routes.tasks import router as tasks_router

    app = FastAPI()
    app.include_router(tasks_router)
    client = TestClient(app)
    resp = client.post(
        f"/api/tasks/{row.id}/cancel",
        headers={"x-autoapply-tenant": "test-codex-cancel-revoke"},
    )
    assert resp.status_code == 200, resp.text

    assert captured == [{"task_id": "celery-revoke-1", "terminate": False}]
