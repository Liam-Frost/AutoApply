"""Phase 14.2: Postgres-backed task audit log.

The :class:`TaskRecord` ORM row is the durable source of truth for
what a Celery worker tried to do, how many attempts it took, and where
the resulting trace lives. Celery signals plumb that information back
into the table without business code having to call us explicitly.

Status lifecycle::

  queued ─┬─► running ─┬─► succeeded
          │            ├─► failed
          │            └─► waiting_human (Phase 14.4)
          └─► cancelled

Callers (typically the Phase 14.3 :class:`AutoApplyTask` base class)
build a row via :func:`record_enqueue` before dispatching to Celery and
let the signal handlers walk it through the lifecycle. The signal
handlers tolerate missing rows: tasks that were dispatched outside the
AutoApplyTask base class (third-party libraries, tests) simply do not
get audited.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from celery.signals import (
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    task_revoked,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.models import TaskRecord

logger = logging.getLogger(__name__)


# ---- Public helpers ----------------------------------------------------


def record_enqueue(
    session: Session,
    *,
    kind: str,
    queue: str,
    payload: dict[str, Any] | None,
    tenant_id: str,
    idempotency_key: str | None,
    parent_task_id: uuid.UUID | None,
    celery_task_id: str | None,
    scheduled_for: datetime | None = None,
) -> TaskRecord:
    """Insert a ``queued`` row before dispatching to Celery.

    Caller is responsible for committing the session. ``celery_task_id``
    may be ``None`` if the dispatcher hasn't called ``.apply_async()``
    yet; the prerun signal will fill it in.
    """
    row = TaskRecord(
        kind=kind,
        queue=queue,
        payload=payload,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        parent_task_id=parent_task_id,
        celery_task_id=celery_task_id,
        status="queued",
        scheduled_for=scheduled_for,
    )
    session.add(row)
    session.flush()
    return row


def find_by_celery_id(session: Session, celery_task_id: str) -> TaskRecord | None:
    return session.execute(
        select(TaskRecord).where(TaskRecord.celery_task_id == celery_task_id)
    ).scalar_one_or_none()


def find_succeeded_for_idempotency(
    session: Session, tenant_id: str, idempotency_key: str
) -> TaskRecord | None:
    """Phase 14.3 short-circuit: if a previous run with the same
    idempotency key already reached ``succeeded``, the new enqueue
    must return the stored result rather than re-execute."""
    return session.execute(
        select(TaskRecord)
        .where(TaskRecord.tenant_id == tenant_id)
        .where(TaskRecord.idempotency_key == idempotency_key)
        .where(TaskRecord.status == "succeeded")
    ).scalar_one_or_none()


# ---- Signal handlers ---------------------------------------------------
#
# Signal handlers receive a session via :func:`_session_factory`, which
# can be monkey-patched in tests. The handlers swallow exceptions: a
# bug in the audit layer must not poison the worker that is running
# user-visible work.


def _session_factory() -> Session:
    """Indirection so tests can monkey-patch this without importing
    the production DB."""
    from src.core.database import get_session_factory

    return get_session_factory()()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_update(celery_task_id: str, mutate: Any) -> None:
    """Look up the row and call ``mutate(row)``; commit. Errors are
    logged, not raised, so worker control flow never breaks because
    of an audit miss."""
    if not celery_task_id:
        return
    try:
        session = _session_factory()
    except Exception:  # noqa: BLE001 -- DB unavailable must not crash the worker
        logger.exception("task audit: failed to open DB session")
        return
    try:
        row = find_by_celery_id(session, celery_task_id)
        if row is None:
            return
        mutate(row)
        row.updated_at = _utcnow()
        session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("task audit: update failed for %s", celery_task_id)
        session.rollback()
    finally:
        session.close()


@task_prerun.connect
def task_prerun_handler(
    task_id: str | None = None, **_kwargs: Any
) -> None:  # pragma: no cover - exercised in integration
    def _mutate(row: TaskRecord) -> None:
        row.status = "running"
        row.attempts = (row.attempts or 0) + 1
        if row.started_at is None:
            row.started_at = _utcnow()

    _safe_update(task_id or "", _mutate)


@task_postrun.connect
def task_postrun_handler(
    task_id: str | None = None,
    state: str | None = None,
    **_kwargs: Any,
) -> None:  # pragma: no cover
    if state == "SUCCESS":
        def _mutate(row: TaskRecord) -> None:
            # Do not flip out of waiting_human even if Celery thinks
            # the task "succeeded" because the AutoApplyTask base
            # class returned needs_human (Phase 14.4 contract).
            if row.status == "waiting_human":
                return
            row.status = "succeeded"
            row.finished_at = _utcnow()
            row.last_error = None

        _safe_update(task_id or "", _mutate)


@task_failure.connect
def task_failure_handler(
    task_id: str | None = None,
    exception: BaseException | None = None,
    **_kwargs: Any,
) -> None:  # pragma: no cover
    summary = repr(exception)[:1000] if exception else None

    def _mutate(row: TaskRecord) -> None:
        row.status = "failed"
        row.finished_at = _utcnow()
        if summary:
            row.last_error = summary

    _safe_update(task_id or "", _mutate)


@task_retry.connect
def task_retry_handler(
    request: Any = None, reason: BaseException | None = None, **_kwargs: Any
) -> None:  # pragma: no cover
    summary = repr(reason)[:1000] if reason else None
    celery_task_id = getattr(request, "id", None) or ""

    def _mutate(row: TaskRecord) -> None:
        row.status = "queued"  # back into the queue
        if summary:
            row.last_error = summary

    _safe_update(celery_task_id, _mutate)


@task_revoked.connect
def task_revoked_handler(
    request: Any = None, **_kwargs: Any
) -> None:  # pragma: no cover
    celery_task_id = getattr(request, "id", None) or ""

    def _mutate(row: TaskRecord) -> None:
        row.status = "cancelled"
        row.finished_at = _utcnow()

    _safe_update(celery_task_id, _mutate)


__all__ = [
    "find_by_celery_id",
    "find_succeeded_for_idempotency",
    "record_enqueue",
]
