"""Phase 14.9: tests for the Celery -> trace store integration.

The trace store itself (Phase 8.3) is well-covered elsewhere; here we
just verify the *task-shape* trace gets written on each lifecycle path
and that the audit row's trace_id gets stamped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from src.tasks import trace as trace_mod


class _FakeStore:
    def __init__(self) -> None:
        self.saved: list[Any] = []

    def save(self, record: Any) -> str:  # mirror TraceStore.save signature
        self.saved.append(record)
        return "/tmp/" + record.id


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.row: Any | None = None

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


class _Request:
    def __init__(self, headers: dict[str, Any] | None = None) -> None:
        self.headers = headers or {}


class _Task:
    def __init__(self, name: str, headers: dict[str, Any] | None = None) -> None:
        self.name = name
        self.request = _Request(headers or {})


@pytest.fixture(autouse=True)
def _clean_inflight() -> None:
    trace_mod._IN_FLIGHT.clear()
    yield
    trace_mod._IN_FLIGHT.clear()


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch) -> _FakeStore:
    store = _FakeStore()
    monkeypatch.setattr(trace_mod, "_trace_store_factory", lambda: store)
    return store


@pytest.fixture
def fake_audit(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Captures attempts to stamp the audit row's trace_id."""
    state: dict[str, Any] = {"stamped": []}

    class _Row:
        def __init__(self) -> None:
            self.trace_id = None
            self.updated_at = None

    row = _Row()

    def _find(_session: Any, celery_task_id: str) -> Any:
        state["stamped"].append(celery_task_id)
        return row

    from src.tasks import audit as audit_mod

    monkeypatch.setattr(audit_mod, "find_by_celery_id", _find)
    monkeypatch.setattr(trace_mod, "_session_factory", _FakeSession)
    state["row"] = row
    return state


# ---- Happy path -----------------------------------------------------


def test_postrun_persists_a_trace_record(
    fake_store: _FakeStore, fake_audit: dict[str, Any]
) -> None:
    trace_mod._trace_prerun(
        task_id="cel-1",
        task=_Task("materials.generate"),
        args=(),
        kwargs={"job_id": "j-1"},
    )
    trace_mod._trace_postrun(
        task_id="cel-1",
        retval={"status": "scheduled"},
        state="SUCCESS",
    )

    assert len(fake_store.saved) == 1
    record = fake_store.saved[0]
    assert record.metadata["task_name"] == "materials.generate"
    assert record.metadata["celery_task_id"] == "cel-1"
    assert record.finished is True


def test_audit_trace_id_is_stamped_at_prerun(
    fake_store: _FakeStore, fake_audit: dict[str, Any]
) -> None:
    trace_mod._trace_prerun(
        task_id="cel-2",
        task=_Task("search.refresh"),
        args=(),
        kwargs={},
    )
    assert fake_audit["stamped"] == ["cel-2"]
    assert fake_audit["row"].trace_id  # set to the new trace id


def test_failure_records_error_and_stop_reason(
    fake_store: _FakeStore, fake_audit: dict[str, Any]
) -> None:
    trace_mod._trace_prerun(
        task_id="cel-3",
        task=_Task("application.submit"),
        args=(),
        kwargs={"application_id": "a"},
    )
    trace_mod._trace_failure(
        task_id="cel-3", exception=RuntimeError("network down")
    )
    record = fake_store.saved[0]
    assert record.stop_reason == "failure"
    assert "network down" in (record.metadata["error"] or "")


def test_retry_clears_inflight_and_persists(
    fake_store: _FakeStore, fake_audit: dict[str, Any]
) -> None:
    trace_mod._trace_prerun(
        task_id="cel-4",
        task=_Task("status.sync"),
        args=(),
        kwargs={},
    )
    assert "cel-4" in trace_mod._IN_FLIGHT

    class _Req:
        id = "cel-4"

    trace_mod._trace_retry(request=_Req(), reason=RuntimeError("transient"))
    assert "cel-4" not in trace_mod._IN_FLIGHT
    assert fake_store.saved[-1].stop_reason == "retry"


# ---- Parent trace propagation --------------------------------------


def test_prerun_picks_up_parent_trace_from_header(
    fake_store: _FakeStore, fake_audit: dict[str, Any]
) -> None:
    trace_mod._trace_prerun(
        task_id="cel-5",
        task=_Task(
            "application.fill",
            headers={"x-autoapply-parent-trace": "20260101T0000Z-abcd"},
        ),
        args=(),
        kwargs={},
    )
    trace_mod._trace_postrun(task_id="cel-5", retval={"status": "ok"}, state="SUCCESS")
    record = fake_store.saved[0]
    assert record.metadata["parent_trace_id"] == "20260101T0000Z-abcd"


# ---- current_trace_id helper ---------------------------------------


def test_current_trace_id_returns_none_outside_a_task() -> None:
    assert trace_mod.current_trace_id() is None


def test_current_trace_id_returns_inflight_id_inside_a_task(
    fake_store: _FakeStore, fake_audit: dict[str, Any]
) -> None:
    trace_mod._trace_prerun(
        task_id="cel-6", task=_Task("search.refresh"), args=(), kwargs={}
    )
    tid = trace_mod.current_trace_id()
    assert tid is not None
    assert tid.startswith(datetime.now(UTC).strftime("%Y%m%d"))
    trace_mod._trace_postrun(task_id="cel-6", retval={"status": "ok"}, state="SUCCESS")
    assert trace_mod.current_trace_id() is None


# ---- Defensive: persist failure never bubbles --------------------------


def test_persist_swallows_store_exceptions(
    monkeypatch: pytest.MonkeyPatch, fake_audit: dict[str, Any]
) -> None:
    class _BadStore:
        def save(self, record: Any) -> None:
            raise RuntimeError("disk full")

    monkeypatch.setattr(trace_mod, "_trace_store_factory", lambda: _BadStore())

    trace_mod._trace_prerun(
        task_id="cel-7", task=_Task("status.sync"), args=(), kwargs={}
    )
    # Must NOT raise even though save() throws.
    trace_mod._trace_postrun(task_id="cel-7", retval={"status": "ok"}, state="SUCCESS")
