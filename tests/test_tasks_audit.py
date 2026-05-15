"""Phase 14.2: tests for the tasks audit table + helpers.

The signal handlers themselves are exercised by integration tests
against a live Celery worker; here we cover the pure-function helpers
and confirm the schema invariants hold.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

models = importlib.import_module("src.core.models")
audit = importlib.import_module("src.tasks.audit")


def test_taskrecord_table_columns_present() -> None:
    cols = models.TaskRecord.__table__.columns
    expected = {
        "id",
        "tenant_id",
        "celery_task_id",
        "kind",
        "queue",
        "payload",
        "idempotency_key",
        "status",
        "attempts",
        "parent_task_id",
        "trace_id",
        "last_error",
        "scheduled_for",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    }
    assert expected <= set(cols.keys()), f"missing columns: {expected - set(cols.keys())}"


def test_taskrecord_unique_idempotency_per_tenant() -> None:
    constraint_names = {c.name for c in models.TaskRecord.__table__.constraints}
    assert "uq_tasks_tenant_idempotency_key" in constraint_names


def test_taskrecord_status_default_is_queued() -> None:
    col = models.TaskRecord.__table__.columns["status"]
    # Default is set on the Mapped side (Python-level default for ORM-only inserts).
    assert col.default is not None and col.default.arg == "queued"


def test_taskrecord_tenant_id_required() -> None:
    col = models.TaskRecord.__table__.columns["tenant_id"]
    assert col.nullable is False


def test_audit_signals_fire_through_our_handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 14.2 contract: importing ``src.tasks`` must hook the five
    lifecycle signals onto our handlers. We assert this end-to-end by
    firing each signal and checking that our ``_safe_update`` is
    invoked, which only happens if the handler is connected."""
    from celery.signals import (
        task_failure,
        task_postrun,
        task_prerun,
        task_retry,
        task_revoked,
    )

    importlib.import_module("src.tasks")  # ensures handlers register

    calls: list[str] = []

    def _spy(celery_task_id: str, _mutate: object) -> None:
        calls.append(celery_task_id or "<empty>")

    monkeypatch.setattr(audit, "_safe_update", _spy)

    task_prerun.send(sender=None, task_id="t-1")
    task_postrun.send(sender=None, task_id="t-2", state="SUCCESS")
    task_failure.send(sender=None, task_id="t-3", exception=RuntimeError("boom"))

    class _FakeReq:
        id = "t-4"

    task_retry.send(sender=None, request=_FakeReq(), reason=RuntimeError("retry"))
    task_revoked.send(sender=None, request=_FakeReq())

    assert "t-1" in calls, "task_prerun handler not connected"
    assert "t-2" in calls, "task_postrun handler not connected"
    assert "t-3" in calls, "task_failure handler not connected"
    assert "t-4" in calls, "task_retry / task_revoked handler not connected"


def test_safe_update_swallows_missing_row() -> None:
    """A signal firing for a Celery task that AutoApplyTask did not
    enqueue must not crash the worker."""

    class _FakeResult:
        def scalar_one_or_none(self) -> None:
            return None

    class _FakeSession:
        def execute(self, _stmt: object) -> _FakeResult:
            return _FakeResult()

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    audit._session_factory = lambda: _FakeSession()  # type: ignore[assignment]
    audit._safe_update("unknown-id", lambda row: None)  # must not raise


def test_safe_update_no_op_on_empty_id() -> None:
    """Some Celery signal payloads omit ``task_id``; the handler must
    early-return rather than tripping the session factory."""
    sentinel: list[int] = []

    def _broken_factory():  # pragma: no cover - should not be reached
        sentinel.append(1)
        raise RuntimeError("must not be called")

    audit._session_factory = _broken_factory  # type: ignore[assignment]
    audit._safe_update("", lambda row: None)
    assert sentinel == []


def test_phase_14_2_migration_file_exists() -> None:
    """Migration must chain off Phase 13.9 head."""
    versions = Path(__file__).resolve().parent.parent / "migrations" / "versions"
    found = list(versions.glob("*phase_14_2_tasks_audit_table*.py"))
    assert found, "Phase 14.2 migration missing"
    body = found[0].read_text(encoding="utf-8")
    match = re.search(r"down_revision[^=]*=\s*['\"]([^'\"]+)['\"]", body)
    assert match is not None
    assert match.group(1) == "d8a5c2f1e9b3"
    for marker in (
        "create_table",
        '"tasks"',
        "celery_task_id",
        "idempotency_key",
        "parent_task_id",
        "trace_id",
    ):
        assert marker in body, f"migration missing marker {marker!r}"


@pytest.mark.parametrize(
    "method_name",
    ["record_enqueue", "find_by_celery_id", "find_succeeded_for_idempotency"],
)
def test_public_helpers_exported(method_name: str) -> None:
    assert hasattr(audit, method_name)
    assert callable(getattr(audit, method_name))
