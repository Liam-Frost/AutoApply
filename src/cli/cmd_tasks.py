"""``autoapply tasks ...`` (Phase 14.7).

Operator-facing inspection + retry / cancel commands. Reads the Phase
14.2 audit table; does NOT consult Celery's transient result backend.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import click
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import load_config
from src.core.database import get_engine
from src.core.models import TaskRecord
from src.tasks.tasks import KNOWN_TASK_NAMES


def _session() -> Session:
    factory = sessionmaker(bind=get_engine(load_config()))
    return factory()


@click.group("tasks")
def tasks_cmd() -> None:
    """Inspect, retry, and cancel AutoApply task runs."""


@tasks_cmd.command("list")
@click.option("--limit", default=20, type=click.IntRange(min=1, max=500))
@click.option(
    "--status",
    type=click.Choice(
        ["queued", "running", "waiting_human", "succeeded", "failed", "cancelled"]
    ),
    default=None,
)
@click.option("--kind", default=None, help="Filter by task kind (e.g. materials.generate).")
@click.option("--since", default=None, help="ISO timestamp or '24h' / '7d' shorthand.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def tasks_list(
    limit: int, status: str | None, kind: str | None, since: str | None, as_json: bool
) -> None:
    """Show recent task rows from the audit table."""
    session = _session()
    try:
        stmt = select(TaskRecord).order_by(TaskRecord.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(TaskRecord.status == status)
        if kind:
            stmt = stmt.where(TaskRecord.kind == kind)
        if since:
            stmt = stmt.where(TaskRecord.created_at >= _parse_since(since))
        rows = list(session.execute(stmt).scalars())
    finally:
        session.close()

    if as_json:
        click.echo(json.dumps([_row_to_dict(r) for r in rows], default=str))
        return
    if not rows:
        click.echo("no tasks found")
        return
    click.echo(f"{'id':<36}  {'status':<14}  {'kind':<22}  {'queue':<12}  created_at")
    for r in rows:
        click.echo(
            f"{r.id!s:<36}  {r.status:<14}  {r.kind:<22}  {r.queue:<12}  {r.created_at.isoformat()}"
        )


@tasks_cmd.command("inspect")
@click.argument("task_id")
def tasks_inspect(task_id: str) -> None:
    """Show the full audit row for one task (by UUID or celery_task_id)."""
    session = _session()
    try:
        row = _resolve(session, task_id)
        if row is None:
            click.echo(f"no task matches '{task_id}'", err=True)
            raise SystemExit(1)
        click.echo(json.dumps(_row_to_dict(row), default=str, indent=2))
    finally:
        session.close()


@tasks_cmd.command("retry")
@click.argument("task_id")
def tasks_retry(task_id: str) -> None:
    """Re-enqueue a failed task using its original payload."""
    from src.tasks import celery_app

    session = _session()
    try:
        row = _resolve(session, task_id)
        if row is None:
            click.echo(f"no task matches '{task_id}'", err=True)
            raise SystemExit(1)
        if row.status not in {"failed", "cancelled"}:
            click.echo(
                f"refusing to retry a task in status {row.status}; "
                "only failed/cancelled tasks may be retried",
                err=True,
            )
            raise SystemExit(2)
        # The ``before_task_publish`` signal handler (Phase 14.2,
        # codex-review P2 fix) writes a new audit row for this
        # dispatch because we deliberately do NOT set the
        # x-autoapply-audit-ok header. The old row stays as-is so the
        # history is intact; the new attempt is visible in
        # ``autoapply tasks list``.
        celery_app.send_task(
            row.kind,
            kwargs=row.payload or {},
            queue=row.queue,
            headers={"x-autoapply-tenant": row.tenant_id},
        )
        click.echo(f"retried {row.id} ({row.kind})")
    finally:
        session.close()


@tasks_cmd.command("cancel")
@click.argument("task_id")
def tasks_cancel(task_id: str) -> None:
    """Mark a queued task as cancelled. Does not interrupt a task that
    is already ``running`` (use Celery revoke for that)."""
    session = _session()
    try:
        row = _resolve(session, task_id)
        if row is None:
            click.echo(f"no task matches '{task_id}'", err=True)
            raise SystemExit(1)
        if row.status != "queued":
            click.echo(
                f"only queued tasks may be cancelled via CLI; got {row.status}",
                err=True,
            )
            raise SystemExit(2)
        # P1 codex fix: revoke the broker message so a worker cannot
        # still claim it (see /api/tasks/{id}/cancel for the rationale).
        if row.celery_task_id:
            try:
                from src.tasks import celery_app

                celery_app.control.revoke(row.celery_task_id, terminate=False)
            except Exception:  # noqa: BLE001
                pass
        row.status = "cancelled"
        row.updated_at = datetime.now(UTC)
        session.commit()
        click.echo(f"cancelled {row.id}")
    finally:
        session.close()


@tasks_cmd.command("kinds")
def tasks_kinds() -> None:
    """List every task name a worker is willing to execute."""
    for name in KNOWN_TASK_NAMES:
        click.echo(name)


def _resolve(session: Session, ident: str) -> TaskRecord | None:
    import uuid

    try:
        uid = uuid.UUID(ident)
        row = session.get(TaskRecord, uid)
        if row is not None:
            return row
    except ValueError:
        pass
    # Fall back to celery_task_id
    stmt = select(TaskRecord).where(TaskRecord.celery_task_id == ident).limit(1)
    return session.execute(stmt).scalar_one_or_none()


def _parse_since(value: str) -> datetime:
    now = datetime.now(UTC)
    if value.endswith("h"):
        return now - timedelta(hours=int(value[:-1]))
    if value.endswith("d"):
        return now - timedelta(days=int(value[:-1]))
    return datetime.fromisoformat(value)


def _row_to_dict(row: TaskRecord) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "celery_task_id": row.celery_task_id,
        "tenant_id": row.tenant_id,
        "kind": row.kind,
        "queue": row.queue,
        "status": row.status,
        "attempts": row.attempts,
        "payload": row.payload,
        "idempotency_key": row.idempotency_key,
        "parent_task_id": str(row.parent_task_id) if row.parent_task_id else None,
        "trace_id": row.trace_id,
        "last_error": row.last_error,
        "scheduled_for": row.scheduled_for.isoformat() if row.scheduled_for else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
