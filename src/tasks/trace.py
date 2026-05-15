"""Phase 14.9: Celery -> trace store integration.

Every Celery task attempt that runs through :class:`AutoApplyTask`
gets a lightweight :class:`TraceRecord` written to the Phase 8.3
file-backed store. The audit row (Phase 14.2) holds the ``trace_id``
foreign key, so the trace viewer can walk from a task to its agent
run and back.

We intentionally write a *task-shape* trace (one record per task
attempt) even when the body is a simple stub that did not invoke an
agent. This keeps the operator view consistent: every audit row has
a clickable trace, and parent/child task relationships are visible.
The agent-run trace (rich step-by-step ReAct trace) is layered on top
of this task-shape trace when an agent is actually invoked -- they
share an id so the viewer renders them together.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from celery.signals import (
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
)
from sqlalchemy.orm import Session

from src.agent.trace.store import TraceRecord, TraceStore
from src.tasks import audit as audit_mod

logger = logging.getLogger(__name__)


# ---- Per-attempt state holder (lives only inside the worker) ---------


@dataclass
class _TaskAttempt:
    """Built up across prerun -> postrun/failure for a single attempt."""

    trace_id: str
    started_at: datetime
    celery_task_id: str
    task_name: str
    parent_trace_id: str | None = None
    headers: dict[str, Any] = field(default_factory=dict)
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    finished: bool = False
    stop_reason: str = "running"
    answer: str | None = None


# Maps celery_task_id -> in-flight attempt. Cleared on terminal signal.
_IN_FLIGHT: dict[str, _TaskAttempt] = {}


def _make_trace_id(now: datetime | None = None) -> str:
    when = now or datetime.now(UTC)
    return when.strftime("%Y%m%dT%H%M%SZ-") + secrets.token_hex(4)


def _session_factory() -> Session:
    """Indirection -- monkey-patched in tests."""
    from src.core.database import get_session_factory

    return get_session_factory()()


def _trace_store_factory() -> TraceStore:
    return TraceStore()


# ---- Signal handlers --------------------------------------------------


@task_prerun.connect
def _trace_prerun(
    task_id: str | None = None,
    task: Any = None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    **_extra: Any,
) -> None:  # pragma: no cover -- exercised via send()
    if not task_id:
        return
    task_name = getattr(task, "name", "") or ""
    headers = getattr(getattr(task, "request", None), "headers", {}) or {}
    parent = headers.get("x-autoapply-parent-trace")
    attempt = _TaskAttempt(
        trace_id=_make_trace_id(),
        started_at=datetime.now(UTC),
        celery_task_id=task_id,
        task_name=task_name,
        parent_trace_id=parent if isinstance(parent, str) else None,
        headers=dict(headers),
        args=args or (),
        kwargs=dict(kwargs or {}),
    )
    _IN_FLIGHT[task_id] = attempt
    # Stamp the trace_id onto the audit row so the operator UI shows
    # the trace link the moment the task starts (not only on finish).
    _stamp_audit_trace_id(task_id, attempt.trace_id)


@task_postrun.connect
def _trace_postrun(
    task_id: str | None = None,
    retval: Any = None,
    state: str | None = None,
    **_extra: Any,
) -> None:  # pragma: no cover
    attempt = _IN_FLIGHT.pop(task_id or "", None)
    if attempt is None:
        return
    attempt.finished = True
    attempt.stop_reason = (state or "DONE").lower()
    if isinstance(retval, dict):
        attempt.answer = str(retval.get("status") or "ok")
    _persist(attempt)


@task_failure.connect
def _trace_failure(
    task_id: str | None = None,
    exception: BaseException | None = None,
    **_extra: Any,
) -> None:  # pragma: no cover
    attempt = _IN_FLIGHT.pop(task_id or "", None)
    if attempt is None:
        return
    attempt.finished = True
    attempt.stop_reason = "failure"
    attempt.error = repr(exception)[:1000] if exception else None
    _persist(attempt)


@task_retry.connect
def _trace_retry(
    request: Any = None, reason: BaseException | None = None, **_extra: Any
) -> None:  # pragma: no cover
    task_id = getattr(request, "id", None) or ""
    attempt = _IN_FLIGHT.pop(task_id, None)
    if attempt is None:
        return
    attempt.finished = True
    attempt.stop_reason = "retry"
    attempt.error = repr(reason)[:1000] if reason else None
    _persist(attempt)


# ---- Persistence ------------------------------------------------------


def _persist(attempt: _TaskAttempt) -> None:
    """Write a single :class:`TraceRecord` for this task attempt.
    Errors are logged but never raised back into the worker."""
    try:
        elapsed = int(
            (datetime.now(UTC) - attempt.started_at).total_seconds() * 1000
        )
        record = TraceRecord(
            id=attempt.trace_id,
            started_at=attempt.started_at.isoformat(),
            finished=attempt.finished,
            stop_reason=attempt.stop_reason,
            goal=f"celery:{attempt.task_name}",
            answer=attempt.answer,
            elapsed_ms=elapsed,
            step_count=0,
            tools_allowed=[],
            metadata={
                "kind": "celery_task",
                "task_name": attempt.task_name,
                "celery_task_id": attempt.celery_task_id,
                "parent_trace_id": attempt.parent_trace_id,
                "error": attempt.error,
                "kwargs": _safe_for_json(attempt.kwargs),
            },
            steps=[],
        )
        _trace_store_factory().save(record)
    except Exception:  # noqa: BLE001
        logger.exception("trace persist failed for celery_task_id=%s", attempt.celery_task_id)


def _stamp_audit_trace_id(celery_task_id: str, trace_id: str) -> None:
    """Pin the trace id onto the audit row so the SPA can render the
    link as soon as the task is observed running."""
    try:
        session = _session_factory()
    except Exception:  # noqa: BLE001
        return
    try:
        row = audit_mod.find_by_celery_id(session, celery_task_id)
        if row is None:
            return
        row.trace_id = trace_id
        row.updated_at = datetime.now(UTC)
        session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("audit trace_id stamp failed for %s", celery_task_id)
        session.rollback()
    finally:
        session.close()


def _safe_for_json(value: Any) -> Any:
    """Best-effort coerce to JSON-safe primitives -- the trace store
    re-serialises via ``json.dumps`` so anything not natively JSON
    must already be a basic type."""
    if isinstance(value, dict):
        return {str(k): _safe_for_json(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_safe_for_json(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return repr(value)


# ---- Public helper exposed for src.tasks.base.AutoApplyTask.enqueue --


def current_trace_id() -> str | None:
    """Return the trace id for whichever celery task is currently
    executing on this thread, or ``None`` if we are outside a task body.

    Phase 14.6 / Phase 17 orchestrators use this to stamp child task
    headers (``x-autoapply-parent-trace``) so the viewer can walk the
    parent/child chain.
    """
    # In Celery's prefork pool there is at most one task per process at
    # a time, so the single most-recent entry is correct. If the pool
    # ever switches to threads we'd need a ContextVar; the worker's
    # default prefork model keeps this simple.
    if not _IN_FLIGHT:
        return None
    # Return the most recently inserted attempt's trace id.
    return next(reversed(_IN_FLIGHT.values())).trace_id


__all__ = ["current_trace_id"]
