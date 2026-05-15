"""Phase 14.4: tests for the Postgres-backed gate transitions.

These run against a live Postgres (the dev DB is fine; rows are
cleaned up per-test). We test the *transition contract*, not the
HTTP routes -- the API routes ride on these primitives and Phase 14.8
covers the routes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import get_db_url, load_config
from src.core.models import GateRequest, TaskRecord
from src.tasks import gate
from src.tasks.gate import (
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    GateError,
)


@pytest.fixture(scope="module")
def engine():
    return create_engine(get_db_url(load_config()))


@pytest.fixture
def db_session(engine) -> Session:
    session_factory = sessionmaker(bind=engine)
    s = session_factory()
    yield s
    # Cleanup: scoped to a per-test tenant string so we never touch
    # production rows.
    s.execute(delete(GateRequest).where(GateRequest.tenant_id.like("test-gate-%")))
    s.execute(delete(TaskRecord).where(TaskRecord.tenant_id.like("test-gate-%")))
    s.commit()
    s.close()


def _make_task(session: Session, tenant: str) -> TaskRecord:
    task = TaskRecord(
        tenant_id=tenant,
        kind="materials.generate",
        queue="materials",
        status="running",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(task)
    session.flush()
    return task


def test_open_request_creates_pending_row(db_session: Session) -> None:
    tenant = "test-gate-1"
    task = _make_task(db_session, tenant)
    req = gate.open_request(
        db_session,
        kind="application.submit",
        summary="approve final submit?",
        payload={"job_id": "abc"},
        task_id=task.id,
        tenant_id=tenant,
    )
    db_session.commit()

    assert req.status == STATUS_PENDING
    assert req.tenant_id == tenant
    assert req.task_id == task.id

    # Task row flipped to waiting_human and the worker can be released.
    db_session.refresh(task)
    assert task.status == "waiting_human"


def test_approve_marks_decision_and_keeps_task_in_waiting_human(
    db_session: Session,
) -> None:
    tenant = "test-gate-2"
    task = _make_task(db_session, tenant)
    req = gate.open_request(
        db_session,
        kind="application.submit",
        summary="x",
        task_id=task.id,
        tenant_id=tenant,
    )
    db_session.commit()

    decision = gate.approve(db_session, req.id, decided_by="liam", reason="LGTM")
    db_session.commit()

    db_session.refresh(req)
    assert req.status == STATUS_APPROVED
    assert req.decision == STATUS_APPROVED
    assert req.decided_by == "liam"
    assert req.reason == "LGTM"
    assert decision.decision == STATUS_APPROVED
    assert decision.task_id == task.id

    # Task row is intentionally still waiting_human; the follow-up
    # "resume" task (Phase 14.6 / 14.8) owns the new attempt's audit
    # row. We do NOT want to lie about whether work actually re-ran.
    db_session.refresh(task)
    assert task.status == "waiting_human"
    assert task.last_error is not None and "approved" in task.last_error


def test_reject_records_reason(db_session: Session) -> None:
    tenant = "test-gate-3"
    req = gate.open_request(
        db_session,
        kind="application.submit",
        summary="bad fit",
        tenant_id=tenant,
    )
    db_session.commit()

    gate.reject(db_session, req.id, decided_by="liam", reason="not relevant")
    db_session.commit()

    db_session.refresh(req)
    assert req.status == STATUS_REJECTED
    assert req.reason == "not relevant"


def test_double_approve_returns_replay_no_op(db_session: Session) -> None:
    """The UI may double-click; a second approve of an already-approved
    row should not 409 -- it returns the existing decision."""
    tenant = "test-gate-4"
    req = gate.open_request(
        db_session,
        kind="x",
        summary="y",
        tenant_id=tenant,
    )
    db_session.commit()

    gate.approve(db_session, req.id, decided_by="liam")
    db_session.commit()

    replay = gate.approve(db_session, req.id, decided_by="liam2")
    db_session.commit()

    assert replay.decision == STATUS_APPROVED


def test_reject_after_approve_is_a_conflict(db_session: Session) -> None:
    """Approving then trying to reject is a real disagreement, not a
    double-click."""
    tenant = "test-gate-5"
    req = gate.open_request(
        db_session,
        kind="x",
        summary="y",
        tenant_id=tenant,
    )
    db_session.commit()
    gate.approve(db_session, req.id, decided_by="liam")
    db_session.commit()

    with pytest.raises(GateError):
        gate.reject(db_session, req.id, decided_by="liam")


def test_list_pending_scopes_by_tenant(db_session: Session) -> None:
    tenant_a = "test-gate-list-a"
    tenant_b = "test-gate-list-b"
    a1 = gate.open_request(db_session, kind="x", summary="a1", tenant_id=tenant_a)
    a2 = gate.open_request(db_session, kind="x", summary="a2", tenant_id=tenant_a)
    b1 = gate.open_request(db_session, kind="x", summary="b1", tenant_id=tenant_b)
    db_session.commit()

    pending_a = gate.list_pending(db_session, tenant_id=tenant_a)
    pending_b = gate.list_pending(db_session, tenant_id=tenant_b)

    ids_a = {r.id for r in pending_a}
    ids_b = {r.id for r in pending_b}
    assert {a1.id, a2.id} <= ids_a
    assert b1.id in ids_b
    assert ids_a.isdisjoint(ids_b)


def test_get_missing_raises(db_session: Session) -> None:
    with pytest.raises(GateError):
        gate.get(db_session, uuid.uuid4())


def test_table_schema_invariants() -> None:
    cols = GateRequest.__table__.columns
    assert cols["tenant_id"].nullable is False
    assert "uuid" in str(cols["id"].type).lower()
    indexes = {ix.name for ix in GateRequest.__table__.indexes}
    assert "ix_gate_queue_tenant_status" in indexes
    assert "ix_gate_queue_task" in indexes


def test_migration_chain(tmp_path) -> None:
    """Phase 14.4 migration must follow 14.2."""
    from pathlib import Path

    versions = Path(__file__).resolve().parent.parent / "migrations" / "versions"
    found = list(versions.glob("*phase_14_4_gate_queue*.py"))
    assert found
    body = found[0].read_text(encoding="utf-8")
    assert "down_revision: str | Sequence[str] | None = \"e1b4f72c8a05\"" in body
    assert "gate_queue" in body


def test_unused_text_import_kept_for_future_raw_sql_use(engine) -> None:
    # Sanity check that the test DB is reachable; surfaces failure to
    # connect early in the suite instead of mid-fixture.
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        assert result.scalar() == 1
