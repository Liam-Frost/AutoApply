"""The :class:`AutoApplyTask` base class (Phase 14.3).

Celery owns the queue layer; this class owns the AutoApply-specific
concerns layered on top:

1. **Tenant context.** Every enqueue carries a ``x-autoapply-tenant``
   header (Phase 14.3 / Phase 18 contract); the worker pushes it into
   the :mod:`src.tasks.context` ContextVar before user code runs.
2. **Idempotency short-circuit.** If a previous run with the same
   ``(tenant_id, idempotency_key)`` already reached ``succeeded``, the
   task body is skipped and the original ``payload`` is returned.
3. **Agent boundary.** :meth:`call_agent` routes the structured
   :class:`AgentDispatch` return from a bounded agent into the right
   Celery primitive (``raise self.retry``, transition the audit row to
   ``waiting_human``, enqueue a child task, or return the result).
4. **Audit row creation.** Submitting via :meth:`enqueue` writes a
   ``queued`` row to the :class:`TaskRecord` table; the Phase 14.2
   signal handlers walk it through the lifecycle.

This module is small on purpose: it does NOT define any business
tasks (Phase 14.6 does), and it does NOT own retry policy (Celery
does). It is the *seam* between Celery primitives and AutoApply's
agent/HITL semantics.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from celery import Task

from src.tasks.audit import (
    AUDIT_OK_HEADER,
    find_succeeded_for_idempotency,
    record_enqueue,
)
from src.tasks.context import (
    current_tenant_id,
    reset_tenant_id,
    set_tenant_id,
    tenant_header_name,
)

logger = logging.getLogger(__name__)


class AgentOutcome(str, Enum):  # noqa: UP042 -- str+Enum keeps JSON value behavior
    """The five structured returns an agent may produce inside a task.

    Anything else (raw exception, unrecognized dict shape) is treated
    as ``FAILED_RETRYABLE``.
    """

    SUCCESS = "success"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    NEEDS_HUMAN = "needs_human"
    NEEDS_FOLLOWUP_TASK = "needs_followup_task"


@dataclass(frozen=True)
class AgentDispatch:
    """The result an agent hands back to the task wrapper. The wrapper
    is responsible for converting it into a Celery primitive."""

    outcome: AgentOutcome
    result: dict[str, Any] | None = None
    # When NEEDS_HUMAN: the gate request describing what needs review.
    gate_kind: str | None = None
    gate_summary: str | None = None
    gate_payload: dict[str, Any] | None = None
    # When NEEDS_FOLLOWUP_TASK: kind + payload for the child task.
    followup_kind: str | None = None
    followup_payload: dict[str, Any] | None = None
    followup_queue: str | None = None
    # When FAILED_RETRYABLE: optional retry delay in seconds.
    retry_in: float | None = None
    # When any FAILED_*: short message to record as last_error.
    error: str | None = None


@dataclass
class EnqueueSpec:
    """Argument bundle for :meth:`AutoApplyTask.enqueue`.

    Kept as a dataclass instead of kwargs so Phase 14.6 task
    definitions get type checking; trying to pass an unknown field
    raises at construction time."""

    kind: str
    queue: Literal["search", "materials", "application", "maintenance"]
    payload: dict[str, Any] | None = None
    tenant_id: str | None = None  # defaults to current ContextVar
    idempotency_key: str | None = None
    parent_task_id: uuid.UUID | None = None
    scheduled_for: datetime | None = None
    headers: dict[str, str] = field(default_factory=dict)


class AutoApplyTask(Task):
    """Base Task class. Concrete tasks should subclass this and put the
    body in ``run(self, **payload)``.

    Subclasses must NOT override :meth:`__call__` or the lifecycle
    hooks (``before_start``, ``on_failure``, ``after_return``) without
    calling ``super()`` -- they own the tenant + idempotency contract.
    """

    abstract = True

    # Celery options surfaced for self-documentation; subclasses override
    # via decorator kwargs (``@celery_app.task(bind=True, base=AutoApplyTask, max_retries=3)``).
    autoretry_for: tuple[type[BaseException], ...] = ()
    max_retries: int = 3
    default_retry_delay: int = 30

    # ----- Lifecycle hooks ------------------------------------------------

    def before_start(
        self, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None:  # pragma: no cover -- needs broker to exercise
        """Push tenant ContextVar; check idempotency; record start."""
        super().before_start(task_id, args, kwargs)
        # Tenant header propagation.
        tenant = self._read_header(tenant_header_name(), default=current_tenant_id())
        token = set_tenant_id(tenant)
        # Stash the token on the request so after_return can pop it.
        try:
            self.request.autoapply_tenant_token = token  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            logger.debug("could not attach tenant token to celery request")

    def after_return(
        self,
        status: str,
        retval: Any,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:  # pragma: no cover -- needs broker
        token = getattr(self.request, "autoapply_tenant_token", None)
        if token is not None:
            try:
                reset_tenant_id(token)
            except Exception:  # noqa: BLE001
                pass
        super().after_return(status, retval, task_id, args, kwargs, einfo)

    # ----- Header helpers -------------------------------------------------

    def _read_header(self, name: str, default: str = "") -> str:
        try:
            headers = getattr(self.request, "headers", None) or {}
        except Exception:  # noqa: BLE001
            return default
        value = headers.get(name)
        return str(value) if value else default

    # ----- Idempotency ---------------------------------------------------

    def short_circuit_if_already_succeeded(
        self, session: Any, idempotency_key: str | None
    ) -> dict[str, Any] | None:
        """Phase 14.3 contract: a task body should call this first.
        If a previous run with the same idempotency key already
        reached ``succeeded``, returns the stored payload (suitable to
        ``return`` straight from the task)."""
        if not idempotency_key:
            return None
        tenant = current_tenant_id()
        prior = find_succeeded_for_idempotency(session, tenant, idempotency_key)
        if prior is None:
            return None
        return {
            "replayed": True,
            "task_id": str(prior.id),
            "result": prior.payload,
        }

    # ----- Agent boundary -------------------------------------------------

    def call_agent(
        self,
        agent_fn: Any,
        *agent_args: Any,
        **agent_kwargs: Any,
    ) -> AgentDispatch:
        """Run a bounded agent for a single decision and normalise its
        return shape into :class:`AgentDispatch`.

        ``agent_fn`` must return either an :class:`AgentDispatch` or a
        ``dict`` with at least ``outcome``. Anything else (raw return,
        ``None``, raised exception inside the wrapper) is mapped to
        ``FAILED_RETRYABLE`` so Celery's retry layer handles it.
        """
        try:
            raw = agent_fn(*agent_args, **agent_kwargs)
        except Exception as exc:  # noqa: BLE001 -- agent failure is bounded
            logger.warning("agent call raised: %s", exc, exc_info=True)
            return AgentDispatch(
                outcome=AgentOutcome.FAILED_RETRYABLE,
                error=f"agent raised: {exc!r}",
            )
        return _normalize_agent_return(raw)

    # ----- Enqueue (used by orchestrators that schedule child tasks) -----

    @staticmethod
    def enqueue(
        celery_task: Task,
        session: Any,
        spec: EnqueueSpec,
    ) -> uuid.UUID:
        """Atomically: write a queued audit row, then dispatch to
        Celery with the tenant header set.

        Returns the audit row's UUID so callers can link parents to
        children explicitly.
        """
        tenant = spec.tenant_id or current_tenant_id()
        headers = dict(spec.headers)
        headers.setdefault(tenant_header_name(), tenant)
        # Tell the ``before_task_publish`` audit handler (Phase 14.2)
        # to skip this dispatch -- we are about to write the audit row
        # ourselves (with idempotency_key + parent_task_id, which the
        # publish handler does not see). Without this flag a duplicate
        # row would land on every enqueue going through this helper.
        headers[AUDIT_OK_HEADER] = "1"
        # Idempotency short-circuit pre-dispatch: if a successful run
        # already exists, we still write a "replayed" audit row but
        # do not dispatch.
        if spec.idempotency_key:
            prior = find_succeeded_for_idempotency(
                session, tenant, spec.idempotency_key
            )
            if prior is not None:
                logger.info(
                    "enqueue short-circuited by idempotency: kind=%s key=%s prior=%s",
                    spec.kind,
                    spec.idempotency_key,
                    prior.id,
                )
                return prior.id

        # Pre-write the audit row (status=queued) so the prerun signal
        # can find it by celery_task_id immediately.
        celery_task_id = uuid.uuid4().hex
        row = record_enqueue(
            session,
            kind=spec.kind,
            queue=spec.queue,
            payload=spec.payload,
            tenant_id=tenant,
            idempotency_key=spec.idempotency_key,
            parent_task_id=spec.parent_task_id,
            celery_task_id=celery_task_id,
            scheduled_for=spec.scheduled_for,
        )
        session.commit()

        # Dispatch with our pre-allocated id so the audit row and the
        # broker entry agree from the start.
        celery_task.apply_async(
            kwargs=spec.payload or {},
            task_id=celery_task_id,
            queue=spec.queue,
            headers=headers,
            eta=spec.scheduled_for,
        )
        return row.id


# ---- Helpers ---------------------------------------------------------


def _normalize_agent_return(raw: Any) -> AgentDispatch:
    """Coerce arbitrary agent returns into :class:`AgentDispatch`."""
    if isinstance(raw, AgentDispatch):
        return raw
    if isinstance(raw, dict):
        outcome_value = raw.get("outcome")
        try:
            outcome = AgentOutcome(outcome_value) if outcome_value else AgentOutcome.SUCCESS
        except ValueError:
            outcome = AgentOutcome.FAILED_RETRYABLE
        return AgentDispatch(
            outcome=outcome,
            result=raw.get("result"),
            gate_kind=raw.get("gate_kind"),
            gate_summary=raw.get("gate_summary"),
            gate_payload=raw.get("gate_payload"),
            followup_kind=raw.get("followup_kind"),
            followup_payload=raw.get("followup_payload"),
            followup_queue=raw.get("followup_queue"),
            retry_in=raw.get("retry_in"),
            error=raw.get("error"),
        )
    if raw is None:
        return AgentDispatch(outcome=AgentOutcome.SUCCESS)
    # Bare-return shape: agents that just return a dict-of-data are
    # treated as success.
    return AgentDispatch(outcome=AgentOutcome.SUCCESS, result={"value": raw})


__all__ = [
    "AgentDispatch",
    "AgentOutcome",
    "AutoApplyTask",
    "EnqueueSpec",
]
