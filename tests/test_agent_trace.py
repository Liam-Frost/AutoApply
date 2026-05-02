"""Tests for the Phase 8.3 trace store and web routes."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from src.agent.core.loop import AgentResult, AgentStep
from src.agent.trace.store import (
    TraceStore,
    make_trace_id,
    record_from_result,
)


def _result(finished=True, steps=1) -> AgentResult:
    step = AgentStep(
        index=1,
        prompt="p",
        raw_response="r",
        thought="t",
        action_name="finish",
        action_args={"answer": "ok"},
        observation="ok",
        is_error=False,
        latency_ms=42,
    )
    return AgentResult(
        goal="hello",
        answer="ok" if finished else None,
        finished=finished,
        steps=[step] * steps,
        stop_reason="finish" if finished else "max_steps",
        elapsed_ms=100,
    )


class TestMakeTraceId:
    def test_format_is_sortable(self):
        a = make_trace_id(datetime(2026, 1, 1, tzinfo=UTC))
        b = make_trace_id(datetime(2026, 1, 2, tzinfo=UTC))
        assert a < b
        assert a.startswith("20260101T000000Z-")


class TestTraceStore:
    def test_save_and_load_roundtrip(self, tmp_path):
        store = TraceStore(base_dir=tmp_path)
        record = record_from_result(_result(), tools_allowed=["finish"])
        path = store.save(record)
        assert path.exists()

        loaded = store.load(record.id)
        assert loaded.id == record.id
        assert loaded.goal == "hello"
        assert loaded.finished is True
        assert loaded.steps[0]["action_name"] == "finish"

    def test_list_returns_newest_first(self, tmp_path):
        store = TraceStore(base_dir=tmp_path)
        early = record_from_result(
            _result(),
            tools_allowed=["finish"],
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        late = record_from_result(
            _result(),
            tools_allowed=["finish"],
            started_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        store.save(early)
        store.save(late)

        listed = store.list()
        assert [r.id for r in listed] == [late.id, early.id]

    def test_list_skips_corrupt_files(self, tmp_path):
        store = TraceStore(base_dir=tmp_path)
        record = record_from_result(_result(), tools_allowed=["finish"])
        store.save(record)
        (tmp_path / "garbage.json").write_text("not json", encoding="utf-8")
        listed = store.list()
        assert [r.id for r in listed] == [record.id]

    def test_load_missing_raises(self, tmp_path):
        store = TraceStore(base_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            store.load("nope")

    def test_safe_path_rejects_traversal(self, tmp_path):
        store = TraceStore(base_dir=tmp_path)
        with pytest.raises(ValueError):
            store.load("../etc/passwd")
        with pytest.raises(ValueError):
            store.delete("..")

    def test_summary_omits_step_bodies(self, tmp_path):
        record = record_from_result(_result(steps=3), tools_allowed=["finish"])
        summary = record.summary()
        assert "steps" not in summary
        assert summary["step_count"] == 3
        assert summary["finished"] is True


class TestAgentRoutes:
    def _client(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "src.web.routes.agent.TraceStore",
            lambda: TraceStore(base_dir=tmp_path),
        )
        from src.web.app import create_app

        return TestClient(create_app())

    def test_list_endpoint_returns_summaries(self, tmp_path, monkeypatch):
        store = TraceStore(base_dir=tmp_path)
        record = record_from_result(_result(steps=2), tools_allowed=["finish"])
        store.save(record)

        client = self._client(tmp_path, monkeypatch)
        response = client.get("/api/agent/traces")
        assert response.status_code == 200
        body = response.json()
        assert len(body["traces"]) == 1
        assert body["traces"][0]["step_count"] == 2
        assert "steps" not in body["traces"][0]

    def test_detail_endpoint_returns_full_record(self, tmp_path, monkeypatch):
        store = TraceStore(base_dir=tmp_path)
        record = record_from_result(_result(), tools_allowed=["finish"])
        store.save(record)

        client = self._client(tmp_path, monkeypatch)
        response = client.get(f"/api/agent/traces/{record.id}")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == record.id
        assert body["steps"][0]["action_name"] == "finish"

    def test_detail_404s_for_unknown_id(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        response = client.get("/api/agent/traces/nope")
        assert response.status_code == 404

    def test_detail_400s_for_bad_id(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        # Backslash is not normalized by the path matcher and triggers our
        # explicit guard rail in TraceStore._safe_path.
        response = client.get("/api/agent/traces/bad..id")
        assert response.status_code == 400

    def test_viewer_returns_html(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        response = client.get("/api/agent/viewer")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Agent traces" in response.text

    def test_list_validates_limit(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        assert client.get("/api/agent/traces?limit=0").status_code == 400
        assert client.get("/api/agent/traces?limit=600").status_code == 400


class TestRecorder:
    def test_record_agent_run_persists(self, tmp_path):
        from src.agent.tools import ToolRegistry
        from src.agent.tools.builtin import FinishTool
        from src.agent.trace.recorder import record_agent_run

        registry = ToolRegistry()
        registry.register(FinishTool())

        def llm(_p, _s, _t):
            return json.dumps(
                {"thought": "go", "action": {"name": "finish", "args": {"answer": "yes"}}}
            )

        store = TraceStore(base_dir=tmp_path)
        result, record = record_agent_run(
            goal="say yes",
            tools=registry,
            llm=llm,
            store=store,
            metadata={"caller": "test"},
        )
        assert result.finished
        assert record.metadata == {"caller": "test"}
        assert record.tools_allowed == ["finish"]
        assert (tmp_path / f"{record.id}.json").exists()
