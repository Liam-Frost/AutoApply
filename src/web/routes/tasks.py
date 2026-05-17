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
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.application.automation_plans import (
    delete_automation_plan_data,
    get_automation_plan,
    load_automation_plans_data,
    save_automation_plan_data,
    schedule_entry_for_plan,
)
from src.core.config import load_config
from src.core.database import get_engine
from src.core.models import GateRequest, TaskRecord
from src.tasks import celery_app, gate
from src.tasks.beat import SCHEDULE_DISPLAY, TASK_KIND_DISPLAY, get_schedule
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
    # Phase 17 dashboard polish -- display strings so the UI does
    # not show raw values like ``search.daily_fanout``. Falls back to the
    # raw kind when the kind is not in TASK_KIND_DISPLAY.
    kind_display: str
    kind_description: str
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
        display = TASK_KIND_DISPLAY.get(row.kind, {})
        return cls(
            id=str(row.id),
            celery_task_id=row.celery_task_id,
            tenant_id=row.tenant_id,
            kind=row.kind,
            kind_display=str(display.get("display_name", row.kind)),
            kind_description=str(display.get("description", "")),
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
    # Human-facing additions: name -> display name + description,
    # schedule -> human-readable cadence (e.g. "Daily at 02:00 UTC"), and a
    # next_run_at projection so the operator can see when this will fire.
    display_name: str
    description: str
    schedule_human: str
    next_run_at: datetime | None
    is_user_facing: bool
    plan_id: str | None = None
    source: str = "builtin"
    read_only: bool = True
    enabled: bool = True
    plan_type: str | None = None
    cadence: str | None = None
    interval_every: int | None = None
    interval_unit: str | None = None
    hour: int | None = None
    minute: int | None = None
    day_of_week: int | None = None
    day_of_month: int | None = None
    profile_id: str | None = None
    search_profile_id: str | None = None
    top_n: int | None = None
    dry_run: bool = False
    scrape_enabled: bool = True
    apply_mode: str = "review_queue"
    skip_previously_applied: bool = True


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


class AutomationPlanPayload(BaseModel):
    name: str = Field(default="", max_length=120)
    enabled: bool = True
    search_profile_id: str = Field(default="", max_length=120)
    profile_id: str = Field(default="default", max_length=120)
    cadence: str = "daily"
    interval_every: int = Field(default=1, ge=1, le=24)
    interval_unit: str = "hours"
    hour: int = Field(default=23, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    day_of_week: int = Field(default=1, ge=0, le=6)
    day_of_month: int = Field(default=1, ge=1, le=31)
    scrape_enabled: bool = True
    apply_mode: str = "review_queue"
    skip_previously_applied: bool = True
    top_n: int = Field(default=10, ge=1, le=100)
    dry_run: bool = False


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
    now = datetime.now(UTC)
    out: list[ScheduleEntryDTO] = []
    for name, entry in get_schedule().items():
        if name.startswith("automation:"):
            continue
        meta = SCHEDULE_DISPLAY.get(name, {})
        if not bool(meta.get("user_facing", False)):
            continue
        out.append(_schedule_dto(name, entry, meta, now))
    return out


@router.get("/api/automation-plans")
def list_automation_plans() -> list[ScheduleEntryDTO]:
    now = datetime.now(UTC)
    entries: list[ScheduleEntryDTO] = []
    for plan in load_automation_plans_data()["plans"]:
        entries.append(_custom_plan_dto(plan, now))
    return entries


@router.post("/api/automation-plans")
def create_automation_plan(body: AutomationPlanPayload) -> ScheduleEntryDTO:
    result = save_automation_plan_data(
        plan_id=body.name,
        plan=body.model_dump(),
    )
    return _custom_plan_dto(result["plan"], datetime.now(UTC))


@router.put("/api/automation-plans/{plan_id}")
def update_automation_plan(plan_id: str, body: AutomationPlanPayload) -> ScheduleEntryDTO:
    result = save_automation_plan_data(
        plan_id=plan_id,
        plan=body.model_dump(),
    )
    return _custom_plan_dto(result["plan"], datetime.now(UTC))


@router.delete("/api/automation-plans/{plan_id}")
def delete_automation_plan(plan_id: str) -> dict[str, str]:
    result = delete_automation_plan_data(plan_id)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return {"deleted": plan_id}


@router.post("/api/automation-plans/{plan_id}/run-now")
def automation_plan_run_now(plan_id: str, tenant: str = Depends(get_tenant)) -> dict[str, str]:
    plan = get_automation_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"no such automation plan: {plan_id}")
    entry = schedule_entry_for_plan(plan)
    task_name = str(entry["task"])
    queue = str(entry.get("options", {}).get("queue", "maintenance"))
    celery_app.send_task(
        task_name,
        kwargs=entry.get("kwargs") or {},
        queue=queue,
        headers={tenant_header_name(): tenant},
    )
    return {"enqueued": task_name, "queue": queue}


@router.post("/api/schedule/{name}/run-now")
def schedule_run_now(
    name: str, tenant: str = Depends(get_tenant)
) -> dict[str, str]:
    schedule = get_schedule()
    meta = SCHEDULE_DISPLAY.get(name, {})
    if name not in schedule or not bool(meta.get("user_facing", False)):
        raise HTTPException(status_code=404, detail=f"no such schedule entry: {name}")
    entry = schedule[name]
    task_name = str(entry["task"])
    queue = str(entry.get("options", {}).get("queue", "maintenance"))
    celery_app.send_task(
        task_name,
        kwargs=entry.get("kwargs") or {},
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


def _schedule_dto(
    name: str,
    entry: dict[str, Any],
    meta: dict[str, Any],
    now: datetime,
) -> ScheduleEntryDTO:
    schedule_obj = entry["schedule"]
    return ScheduleEntryDTO(
        name=name,
        task=str(entry["task"]),
        queue=str(entry.get("options", {}).get("queue", "maintenance")),
        schedule=_render_schedule(schedule_obj),
        display_name=str(meta.get("display_name", name)),
        description=str(meta.get("description", "")),
        schedule_human=_render_schedule_human(schedule_obj),
        next_run_at=_next_run_at(schedule_obj, now),
        is_user_facing=bool(meta.get("user_facing", False)),
    )


def _custom_plan_dto(plan: dict[str, Any], now: datetime) -> ScheduleEntryDTO:
    entry = schedule_entry_for_plan(plan)
    return ScheduleEntryDTO(
        name=f"automation:{plan['id']}",
        plan_id=plan["id"],
        task=str(entry["task"]),
        queue=str(entry.get("options", {}).get("queue", "search")),
        schedule=_render_schedule(entry["schedule"]),
        display_name=str(plan["name"]),
        description=_automation_description(plan),
        schedule_human=_render_schedule_human(entry["schedule"]),
        next_run_at=_next_run_at(entry["schedule"], now) if plan.get("enabled", True) else None,
        is_user_facing=True,
        source="custom",
        read_only=False,
        enabled=bool(plan.get("enabled", True)),
        plan_type="auto_apply",
        cadence=plan["cadence"],
        interval_every=plan["interval_every"],
        interval_unit=plan["interval_unit"],
        hour=plan["hour"],
        minute=plan["minute"],
        day_of_week=plan["day_of_week"],
        day_of_month=plan["day_of_month"],
        profile_id=plan["profile_id"],
        search_profile_id=plan["search_profile_id"],
        top_n=plan["top_n"],
        dry_run=plan["dry_run"],
        scrape_enabled=plan["scrape_enabled"],
        apply_mode=plan["apply_mode"],
        skip_previously_applied=plan["skip_previously_applied"],
    )


def _automation_description(plan: dict[str, Any]) -> str:
    filter_name = plan.get("search_profile_id") or "selected filter"
    applicant = plan.get("profile_id") or "default"
    action = "auto-apply" if plan.get("apply_mode") == "auto_apply" else "prepare for review"
    return f"Use filter '{filter_name}' as applicant '{applicant}', then {action}."


def _render_schedule(schedule: Any) -> str:
    try:
        minute = _schedule_part(schedule, "_orig_minute", "minute")
        hour = _schedule_part(schedule, "_orig_hour", "hour")
        dom = _schedule_part(schedule, "_orig_day_of_month", "day_of_month")
        dow = _schedule_part(schedule, "_orig_day_of_week", "day_of_week")
        return f"cron({minute} {hour} {dom} * {dow})"
    except Exception:  # noqa: BLE001
        return repr(schedule)


def _schedule_part(schedule: Any, original_attr: str, fallback_attr: str) -> str | None:
    value = getattr(schedule, original_attr, None)
    if value is None:
        value = getattr(schedule, fallback_attr, "*")
    if value is None:
        return None
    return str(value)


def _render_schedule_human(schedule: Any) -> str:
    """Render a celery crontab as a short English sentence.

    We only support the patterns we actually use in get_schedule(); any
    schedule that does not match falls back to the raw ``cron(...)``
    string so we never lie to the operator.
    """
    minute = _schedule_part(schedule, "_orig_minute", "minute")
    hour = _schedule_part(schedule, "_orig_hour", "hour")
    dom = _schedule_part(schedule, "_orig_day_of_month", "day_of_month")
    dow = _schedule_part(schedule, "_orig_day_of_week", "day_of_week")

    def _is_every(spec: str | None) -> int | None:
        """Return N if spec is ``*/N``, else None."""
        if not spec or not spec.startswith("*/"):
            return None
        try:
            return int(spec[2:])
        except ValueError:
            return None

    def _as_int(spec: str | None) -> int | None:
        if spec is None:
            return None
        try:
            return int(spec)
        except (TypeError, ValueError):
            return None

    every_h = _is_every(hour)
    every_m = _is_every(minute)
    h = _as_int(hour)
    m = _as_int(minute)
    day = _as_int(dom)
    weekday = _as_int(dow)

    if weekday is not None and h is not None and m is not None:
        return f"Weekly on day {weekday} at {h:02d}:{m:02d} UTC"
    if day is not None and h is not None and m is not None:
        return f"Monthly on day {day} at {h:02d}:{m:02d} UTC"

    # ``every hour, on the :M minute``
    if hour in ("*", None) and m is not None:
        return "Hourly" if m == 0 else f"Hourly at minute {m}"
    # ``every N hours at :M``
    if every_h is not None and m is not None:
        return f"Every {every_h} hours at :{m:02d}"
    # ``every N minutes``
    if every_m is not None and hour in ("*", None):
        return f"Every {every_m} minutes"
    # ``daily at HH:MM UTC``
    if h is not None and m is not None:
        return f"Daily at {h:02d}:{m:02d} UTC"

    return _render_schedule(schedule)


def _next_run_at(schedule: Any, now: datetime) -> datetime | None:
    """Project the next firing of a Celery ``crontab`` schedule.

    Uses ``remaining_estimate(last_run_at=now)`` which celery exposes on
    every BaseSchedule. Returns None on anything else so the UI can fall
    back gracefully.
    """
    remaining = getattr(schedule, "remaining_estimate", None)
    if not callable(remaining):
        return None
    try:
        delta = remaining(now)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(delta, timedelta):
        return None
    return now + delta


__all__ = ["router"]
