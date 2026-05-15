"""Phase 14.3: tests for AutoApplyTask + tenant context + agent dispatch.

We exercise the pure-Python pieces (context propagation, agent return
normalization, idempotency short-circuit) without touching a real
broker. Worker lifecycle hooks (``before_start``, ``after_return``)
require Celery's request stack and are exercised by Phase 14.6 task
tests against ``CELERY_TASK_ALWAYS_EAGER``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from src.core.models import TENANT_DEFAULT, TaskRecord
from src.tasks.base import (
    AgentDispatch,
    AgentOutcome,
    AutoApplyTask,
    EnqueueSpec,
    _normalize_agent_return,
)
from src.tasks.context import (
    current_tenant_id,
    reset_tenant_id,
    set_tenant_id,
    tenant_header_name,
)

# ---- Tenant context --------------------------------------------------


def test_tenant_default_is_default_until_set() -> None:
    assert current_tenant_id() == TENANT_DEFAULT


def test_tenant_set_and_reset_round_trip() -> None:
    token = set_tenant_id("acme-co")
    try:
        assert current_tenant_id() == "acme-co"
    finally:
        reset_tenant_id(token)
    assert current_tenant_id() == TENANT_DEFAULT


def test_tenant_empty_value_falls_back_to_default() -> None:
    token = set_tenant_id("")
    try:
        assert current_tenant_id() == TENANT_DEFAULT
    finally:
        reset_tenant_id(token)


def test_tenant_header_name_is_stable() -> None:
    """Phase 14.4 gate APIs and Phase 14.7 CLI expect this exact value;
    flipping it is a wire-protocol break."""
    assert tenant_header_name() == "x-autoapply-tenant"


# ---- AgentDispatch normalization -------------------------------------


def test_normalize_passthrough_existing_dispatch() -> None:
    d = AgentDispatch(outcome=AgentOutcome.NEEDS_HUMAN, gate_summary="review me")
    assert _normalize_agent_return(d) is d


def test_normalize_dict_with_outcome() -> None:
    out = _normalize_agent_return({"outcome": "needs_human", "gate_summary": "x"})
    assert out.outcome is AgentOutcome.NEEDS_HUMAN
    assert out.gate_summary == "x"


def test_normalize_dict_with_unknown_outcome_is_retryable() -> None:
    out = _normalize_agent_return({"outcome": "spaghetti"})
    assert out.outcome is AgentOutcome.FAILED_RETRYABLE


def test_normalize_none_is_success() -> None:
    out = _normalize_agent_return(None)
    assert out.outcome is AgentOutcome.SUCCESS


def test_normalize_bare_value_wraps_as_success() -> None:
    out = _normalize_agent_return(42)
    assert out.outcome is AgentOutcome.SUCCESS
    assert out.result == {"value": 42}


# ---- AutoApplyTask.call_agent ----------------------------------------


def test_call_agent_normalises_exception_to_retryable() -> None:
    """Agent exceptions must not propagate -- the wrapper converts them
    to a structured ``FAILED_RETRYABLE`` so Celery's retry layer can
    decide what to do."""

    class _Boom(AutoApplyTask):
        name = "test.boom"

    boom = _Boom()

    def _raises() -> None:
        raise RuntimeError("kaboom")

    dispatch = boom.call_agent(_raises)
    assert dispatch.outcome is AgentOutcome.FAILED_RETRYABLE
    assert "kaboom" in (dispatch.error or "")


def test_call_agent_passes_through_explicit_dispatch() -> None:
    class _Echo(AutoApplyTask):
        name = "test.echo"

    echo = _Echo()
    explicit = AgentDispatch(outcome=AgentOutcome.SUCCESS, result={"k": "v"})
    assert echo.call_agent(lambda: explicit) is explicit


def test_call_agent_normalises_dict_return() -> None:
    class _DictReturn(AutoApplyTask):
        name = "test.dr"

    t = _DictReturn()
    dispatch = t.call_agent(lambda: {"outcome": "success", "result": {"ok": True}})
    assert dispatch.outcome is AgentOutcome.SUCCESS
    assert dispatch.result == {"ok": True}


# ---- enqueue() + idempotency short-circuit ---------------------------


class _FakeSession:
    """Minimal duck for the enqueue path."""

    def __init__(self, *, succeeded_for_key: TaskRecord | None = None) -> None:
        self._succeeded_for_key = succeeded_for_key
        self.added: list[TaskRecord] = []
        self.commits = 0

    def execute(self, _stmt: object) -> Any:
        succeeded = self._succeeded_for_key

        class _Result:
            def scalar_one_or_none(self) -> TaskRecord | None:
                return succeeded

        return _Result()

    def add(self, row: TaskRecord) -> None:
        # Simulate primary-key autogeneration so test code can read it back.
        if row.id is None:
            row.id = uuid.uuid4()
        self.added.append(row)

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


class _RecordingCeleryTask:
    """Captures ``apply_async`` invocations without going to a broker."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def apply_async(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def test_enqueue_writes_audit_row_and_dispatches() -> None:
    session = _FakeSession()
    captured = _RecordingCeleryTask()

    spec = EnqueueSpec(
        kind="search.refresh",
        queue="search",
        payload={"query_id": "abc"},
        tenant_id="acme",
    )
    row_id = AutoApplyTask.enqueue(captured, session, spec)  # type: ignore[arg-type]

    assert isinstance(row_id, uuid.UUID)
    assert len(session.added) == 1
    row = session.added[0]
    assert row.kind == "search.refresh"
    assert row.queue == "search"
    assert row.tenant_id == "acme"
    assert row.status == "queued"
    assert row.celery_task_id  # pre-allocated

    assert len(captured.calls) == 1
    call = captured.calls[0]
    assert call["queue"] == "search"
    assert call["kwargs"] == {"query_id": "abc"}
    assert call["headers"][tenant_header_name()] == "acme"
    assert call["task_id"] == row.celery_task_id


def test_enqueue_short_circuits_on_idempotency_hit() -> None:
    prior = TaskRecord(
        id=uuid.uuid4(),
        tenant_id="acme",
        kind="materials.generate",
        queue="materials",
        status="succeeded",
        idempotency_key="mat-42",
        payload={"resume_path": "/tmp/r.pdf"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session = _FakeSession(succeeded_for_key=prior)
    captured = _RecordingCeleryTask()

    spec = EnqueueSpec(
        kind="materials.generate",
        queue="materials",
        payload={"job_id": "x"},
        tenant_id="acme",
        idempotency_key="mat-42",
    )
    row_id = AutoApplyTask.enqueue(captured, session, spec)  # type: ignore[arg-type]

    # Prior row's id returned; no new row added; no celery dispatch.
    assert row_id == prior.id
    assert session.added == []
    assert captured.calls == []


def test_enqueue_uses_current_tenant_when_spec_omits_it() -> None:
    session = _FakeSession()
    captured = _RecordingCeleryTask()

    token = set_tenant_id("from-ctx")
    try:
        AutoApplyTask.enqueue(
            captured,  # type: ignore[arg-type]
            session,
            EnqueueSpec(kind="status.sync", queue="maintenance"),
        )
    finally:
        reset_tenant_id(token)

    assert session.added[0].tenant_id == "from-ctx"
    assert captured.calls[0]["headers"][tenant_header_name()] == "from-ctx"


# ---- short_circuit_if_already_succeeded ------------------------------


def test_short_circuit_returns_replayed_payload_when_prior_exists() -> None:
    prior = TaskRecord(
        id=uuid.uuid4(),
        tenant_id=TENANT_DEFAULT,
        kind="materials.generate",
        queue="materials",
        status="succeeded",
        idempotency_key="k",
        payload={"output": "ok"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    class _T(AutoApplyTask):
        name = "test.sc"

    session = _FakeSession(succeeded_for_key=prior)
    out = _T().short_circuit_if_already_succeeded(session, "k")
    assert out is not None
    assert out["replayed"] is True
    assert out["result"] == {"output": "ok"}


def test_short_circuit_is_noop_without_key() -> None:
    class _T(AutoApplyTask):
        name = "test.sc2"

    assert _T().short_circuit_if_already_succeeded(_FakeSession(), None) is None
