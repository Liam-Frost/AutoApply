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
    before_task_publish,
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


#: Header set by :meth:`AutoApplyTask.enqueue` (Phase 14.3) to tell the
#: ``before_task_publish`` handler "I already wrote the audit row for
#: this dispatch -- do not duplicate." Any path that publishes a task
#: without going through ``enqueue`` (Beat, raw ``send_task``, retries
#: from the API/CLI) omits this header, and the publish handler writes
#: the row for them.
AUDIT_OK_HEADER = "x-autoapply-audit-ok"

#: Header carrying the tenant_id at publish time. Read by
#: :func:`before_task_publish_handler` when an external dispatcher
#: (Beat, API retry, CLI retry) wants the row tagged for the right
#: tenant. Mirrors :func:`src.tasks.context.tenant_header_name`.
TENANT_HEADER = "x-autoapply-tenant"


def _extract_kwargs_from_body(body: Any) -> dict[str, Any]:
    """Celery's JSON protocol packs task bodies in two shapes:
    ``[args, kwargs, options]`` (protocol 2) and ``{"args": ..., "kwargs": ...}``
    (older). Tolerate both; return ``{}`` when the shape is alien so the
    audit row still gets written with an empty payload."""
    if isinstance(body, list | tuple) and len(body) >= 2 and isinstance(body[1], dict):
        return dict(body[1])
    if isinstance(body, dict):
        kwargs = body.get("kwargs")
        if isinstance(kwargs, dict):
            return dict(kwargs)
    return {}


@before_task_publish.connect
def before_task_publish_handler(
    sender: str | None = None,
    body: Any = None,
    headers: dict[str, Any] | None = None,
    routing_key: str | None = None,
    properties: dict[str, Any] | None = None,
    **_kwargs: Any,
) -> None:  # pragma: no cover -- exercised via send()
    """Universal audit-row creator (Phase 14.10 codex-review P2 fix).

    Every Celery dispatch (Beat tick, ``send_task`` / ``apply_async``
    from any caller) fires this signal. We write a ``queued`` row for
    dispatches that are NOT already covered by
    :meth:`AutoApplyTask.enqueue`, identified by the
    :data:`AUDIT_OK_HEADER`. This guarantees the audit table is the
    durable source of truth -- nothing slips past it.

    The handler swallows exceptions: a bug in the audit layer must
    never block a legitimate publish.
    """
    hdrs = headers or {}
    if hdrs.get(AUDIT_OK_HEADER):
        # AutoApplyTask.enqueue already wrote a row.
        return

    # Celery's outgoing protocol-2 messages put the task id on the
    # outer envelope's ``headers.id`` (kombu sets this). The
    # ``properties`` dict has ``correlation_id`` / ``message_id`` on
    # some brokers. Try both before giving up.
    task_id = (
        hdrs.get("id")
        or hdrs.get("task_id")
        or (properties or {}).get("correlation_id")
        or (properties or {}).get("message_id")
    )
    if not task_id:
        # Nothing we can join later -- skip rather than write a
        # rootless row.
        return

    task_name = sender or hdrs.get("task") or ""
    tenant_id = hdrs.get(TENANT_HEADER) or "default"
    queue = routing_key or "maintenance"
    payload = _extract_kwargs_from_body(body)

    try:
        session = _session_factory()
    except Exception:  # noqa: BLE001
        logger.exception("audit publish handler: DB session unavailable")
        return
    try:
        existing = find_by_celery_id(session, str(task_id))
        if existing is not None:
            # Defensive: should not happen because AutoApplyTask.enqueue
            # sets AUDIT_OK_HEADER, but guard against double-creation
            # when a caller hand-rolls the id.
            return
        record_enqueue(
            session,
            kind=task_name,
            queue=queue,
            payload=payload,
            tenant_id=str(tenant_id),
            idempotency_key=None,
            parent_task_id=None,
            celery_task_id=str(task_id),
        )
        session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("audit publish handler: insert failed for %s", task_id)
        session.rollback()
    finally:
        session.close()


@task_prerun.connect
def task_prerun_handler(
    task_id: str | None = None, **_kwargs: Any
) -> None:  # pragma: no cover - exercised in integration
    def _mutate(row: TaskRecord) -> None:
        # P1 codex fix: a row already marked cancelled (via the
        # /api/tasks/{id}/cancel route or the CLI) means the operator
        # asked us to abandon the work even if Celery's revoke arrived
        # too late and a worker still picked the message up. Refuse to
        # transition back to ``running`` -- the task body will run
        # because we cannot bind a Python exception into the worker
        # from here, but the operator's intent is preserved in the
        # audit + trace.
        if row.status == "cancelled":
            return
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
            # P2 second-round codex fix: a row already cancelled by
            # the operator (cancel route or CLI) is terminal. Even if
            # the worker raced the revoke and the task body returned
            # successfully, the audit log preserves the operator's
            # decision. The side effects of the body running are an
            # unavoidable race with Celery's at-least-once delivery;
            # the audit row tells the truth about what was *asked*.
            if row.status == "cancelled":
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
        # cancelled is terminal -- a failed body after the operator
        # cancelled does not promote the row out of cancelled (see
        # task_postrun_handler for the full rationale).
        if row.status == "cancelled":
            return
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
        # Same cancelled-terminal guard: an in-flight retry of a
        # cancelled task should not put it back into the queue.
        if row.status == "cancelled":
            return
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
