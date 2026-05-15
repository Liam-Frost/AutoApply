"""Phase 14.8 web routes for the task queue audit table, Beat schedule,
and HITL gate.

These are JSON APIs only. A minimal Vue page is added in the SPA
under ``/tasks``, ``/schedule``, and ``/gate`` so an operator can see
what's pending without dropping to the CLI.

All routes scope to the current tenant via the
``x-autoapply-tenant`` header (defaulting to ``"default"`` until Phase
18 lights up real auth). Other tenants' rows are filtered out at the
SQL boundary.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import load_config
from src.core.database import get_engine
from src.core.models import GateRequest, TaskRecord
from src.tasks import celery_app, gate
from src.tasks.beat import get_schedule
from src.tasks.context import tenant_header_name

router = APIRouter()


# ---- Tenant + session dependencies -----------------------------------


def _tenant_from_header(header_value: str | None) -> str:
    return (header_value or "default").strip() or "default"


async def get_tenant(
    x_autoapply_tenant: str | None = Header(default=None, alias=tenant_header_name())
) -> str:
    return _tenant_from_header(x_autoapply_tenant)


def get_session() -> Session:
    engine = get_engine(load_config())
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()


# ---- DTOs ------------------------------------------------------------


class TaskRowDTO(BaseModel):
    id: str
    celery_task_id: str | None
    tenant_id: str
    kind: str
    queue: str
    status: str
    attempts: int
    payload: dict[str, Any] | None
    idempotency_key: str | None
    parent_task_id: str | None
    trace_id: str | None
    last_error: str | None
    scheduled_for: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: TaskRecord) -> TaskRowDTO:
        return cls(
            id=str(row.id),
            celery_task_id=row.celery_task_id,
            tenant_id=row.tenant_id,
            kind=row.kind,
            queue=row.queue,
            status=row.status,
            attempts=row.attempts or 0,
            payload=row.payload,
            idempotency_key=row.idempotency_key,
            parent_task_id=str(row.parent_task_id) if row.parent_task_id else None,
            trace_id=row.trace_id,
            last_error=row.last_error,
            scheduled_for=row.scheduled_for,
            started_at=row.started_at,
            finished_at=row.finished_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class TaskListDTO(BaseModel):
    items: list[TaskRowDTO]
    total: int


class ScheduleEntryDTO(BaseModel):
    name: str
    task: str
    queue: str
    schedule: str


class GateRowDTO(BaseModel):
    id: str
    tenant_id: str
    task_id: str | None
    kind: str
    summary: str
    payload: dict[str, Any] | None
    status: str
    requested_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    decision: str | None
    reason: str | None

    @classmethod
    def from_row(cls, row: GateRequest) -> GateRowDTO:
        return cls(
            id=str(row.id),
            tenant_id=row.tenant_id,
            task_id=str(row.task_id) if row.task_id else None,
            kind=row.kind,
            summary=row.summary or "",
            payload=row.payload,
            status=row.status,
            requested_at=row.requested_at,
            decided_at=row.decided_at,
            decided_by=row.decided_by,
            decision=row.decision,
            reason=row.reason,
        )


class GateDecisionRequest(BaseModel):
    decided_by: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=2000)


# ---- /api/tasks --------------------------------------------------------


@router.get("/api/tasks")
def list_tasks(
    tenant: str = Depends(get_tenant),
    session: Session = Depends(get_session),
    limit: int = 50,
    status: str | None = None,
    kind: str | None = None,
) -> TaskListDTO:
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be 1..500")
    stmt = (
        select(TaskRecord)
        .where(TaskRecord.tenant_id == tenant)
        .order_by(TaskRecord.created_at.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(TaskRecord.status == status)
    if kind:
        stmt = stmt.where(TaskRecord.kind == kind)
    rows = list(session.execute(stmt).scalars())
    return TaskListDTO(
        items=[TaskRowDTO.from_row(r) for r in rows], total=len(rows)
    )


@router.get("/api/tasks/{task_id}")
def get_task(
    task_id: str,
    tenant: str = Depends(get_tenant),
    session: Session = Depends(get_session),
) -> TaskRowDTO:
    row = _resolve_task(session, task_id)
    if row is None or row.tenant_id != tenant:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskRowDTO.from_row(row)


@router.post("/api/tasks/{task_id}/cancel")
def cancel_task(
    task_id: str,
    tenant: str = Depends(get_tenant),
    session: Session = Depends(get_session),
) -> TaskRowDTO:
    row = _resolve_task(session, task_id)
    if row is None or row.tenant_id != tenant:
        raise HTTPException(status_code=404, detail="task not found")
    if row.status != "queued":
        raise HTTPException(
            status_code=409,
            detail=f"only queued tasks may be cancelled; got {row.status}",
        )
    # P1 codex fix: revoke the broker message FIRST so a worker
    # cannot still claim it. ``terminate=False`` is correct here --
    # we only cancel queued (not running) tasks; ``terminate=True``
    # would SIGKILL a running task, which is not what the operator
    # asked for. If the revoke broadcast races a worker that already
    # picked the message up, the prerun handler's status-guard
    # (Phase 14.2) refuses to flip ``cancelled`` back to ``running``.
    if row.celery_task_id:
        try:
            celery_app.control.revoke(row.celery_task_id, terminate=False)
        except Exception:  # noqa: BLE001 -- audit must win even if broker is flaky
            pass
    row.status = "cancelled"
    session.commit()
    return TaskRowDTO.from_row(row)


@router.post("/api/tasks/{task_id}/retry")
def retry_task(
    task_id: str,
    tenant: str = Depends(get_tenant),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    row = _resolve_task(session, task_id)
    if row is None or row.tenant_id != tenant:
        raise HTTPException(status_code=404, detail="task not found")
    if row.status not in {"failed", "cancelled"}:
        raise HTTPException(
            status_code=409,
            detail=f"only failed/cancelled tasks may be retried; got {row.status}",
        )
    # The ``before_task_publish`` audit handler (Phase 14.2) creates a
    # fresh ``TaskRecord`` for this new attempt because we deliberately
    # do NOT set ``x-autoapply-audit-ok``. The previous row stays as
    # historical record; the new dispatch shows up in ``/api/tasks``
    # under its own row.
    celery_app.send_task(
        row.kind,
        kwargs=row.payload or {},
        queue=row.queue,
        headers={tenant_header_name(): row.tenant_id},
    )
    return {"retried": str(row.id), "kind": row.kind}


# ---- /api/schedule -----------------------------------------------------


@router.get("/api/schedule")
def list_schedule() -> list[ScheduleEntryDTO]:
    out: list[ScheduleEntryDTO] = []
    for name, entry in get_schedule().items():
        out.append(
            ScheduleEntryDTO(
                name=name,
                task=str(entry["task"]),
                queue=str(entry.get("options", {}).get("queue", "maintenance")),
                schedule=_render_schedule(entry["schedule"]),
            )
        )
    return out


@router.post("/api/schedule/{name}/run-now")
def schedule_run_now(
    name: str, tenant: str = Depends(get_tenant)
) -> dict[str, str]:
    schedule = get_schedule()
    if name not in schedule:
        raise HTTPException(status_code=404, detail=f"no such schedule entry: {name}")
    entry = schedule[name]
    task_name = str(entry["task"])
    queue = str(entry.get("options", {}).get("queue", "maintenance"))
    celery_app.send_task(
        task_name,
        queue=queue,
        headers={tenant_header_name(): tenant},
    )
    return {"enqueued": task_name, "queue": queue}


# ---- /api/gate ---------------------------------------------------------


@router.get("/api/gate")
def list_gate(
    tenant: str = Depends(get_tenant),
    session: Session = Depends(get_session),
    status: str = "pending",
    limit: int = 100,
) -> list[GateRowDTO]:
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be 1..500")
    stmt = (
        select(GateRequest)
        .where(GateRequest.tenant_id == tenant)
        .where(GateRequest.status == status)
        .order_by(GateRequest.requested_at.asc())
        .limit(limit)
    )
    rows = list(session.execute(stmt).scalars())
    return [GateRowDTO.from_row(r) for r in rows]


@router.get("/api/gate/{gate_id}")
def get_gate(
    gate_id: str,
    tenant: str = Depends(get_tenant),
    session: Session = Depends(get_session),
) -> GateRowDTO:
    row = _resolve_gate(session, gate_id)
    if row is None or row.tenant_id != tenant:
        raise HTTPException(status_code=404, detail="gate request not found")
    return GateRowDTO.from_row(row)


@router.post("/api/gate/{gate_id}/approve")
def approve_gate(
    gate_id: str,
    body: GateDecisionRequest,
    tenant: str = Depends(get_tenant),
    session: Session = Depends(get_session),
) -> GateRowDTO:
    row = _resolve_gate(session, gate_id)
    if row is None or row.tenant_id != tenant:
        raise HTTPException(status_code=404, detail="gate request not found")
    try:
        gate.approve(
            session, row.id, decided_by=body.decided_by, reason=body.reason
        )
    except gate.GateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    session.refresh(row)
    return GateRowDTO.from_row(row)


@router.post("/api/gate/{gate_id}/reject")
def reject_gate(
    gate_id: str,
    body: GateDecisionRequest,
    tenant: str = Depends(get_tenant),
    session: Session = Depends(get_session),
) -> GateRowDTO:
    row = _resolve_gate(session, gate_id)
    if row is None or row.tenant_id != tenant:
        raise HTTPException(status_code=404, detail="gate request not found")
    try:
        gate.reject(
            session, row.id, decided_by=body.decided_by, reason=body.reason
        )
    except gate.GateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    session.refresh(row)
    return GateRowDTO.from_row(row)


# ---- helpers -----------------------------------------------------------


def _resolve_task(session: Session, ident: str) -> TaskRecord | None:
    try:
        uid = uuid.UUID(ident)
    except ValueError:
        stmt = select(TaskRecord).where(TaskRecord.celery_task_id == ident).limit(1)
        return session.execute(stmt).scalar_one_or_none()
    return session.get(TaskRecord, uid)


def _resolve_gate(session: Session, ident: str) -> GateRequest | None:
    try:
        uid = uuid.UUID(ident)
    except ValueError:
        return None
    return session.get(GateRequest, uid)


def _render_schedule(schedule: Any) -> str:
    try:
        minute = getattr(schedule, "_orig_minute", str(getattr(schedule, "minute", "*")))
        hour = getattr(schedule, "_orig_hour", str(getattr(schedule, "hour", "*")))
        dom = getattr(schedule, "_orig_day_of_month", "*")
        dow = getattr(schedule, "_orig_day_of_week", "*")
        return f"cron({minute} {hour} {dom} * {dow})"
    except Exception:  # noqa: BLE001
        return repr(schedule)


__all__ = ["router"]
