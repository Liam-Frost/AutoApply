"""Tests for the Phase 8.5 HITL approval gate."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.agent.gate.queue import (
    ApprovalGate,
    ApprovalStatus,
    GateError,
)


class TestApprovalGate:
    def test_propose_creates_pending(self, tmp_path):
        gate = ApprovalGate(base_dir=tmp_path)
        req = gate.propose(kind="submit", summary="Submit form to Workday")
        assert req.status == ApprovalStatus.PENDING
        assert req.id
        assert (tmp_path / f"{req.id}.json").exists()

    def test_propose_validates(self, tmp_path):
        gate = ApprovalGate(base_dir=tmp_path)
        with pytest.raises(GateError):
            gate.propose(kind="", summary="x")
        with pytest.raises(GateError):
            gate.propose(kind="x", summary="")
        with pytest.raises(GateError):
            gate.propose(kind="x", summary="y", ttl_seconds=0)

    def test_approve_marks_terminal(self, tmp_path):
        gate = ApprovalGate(base_dir=tmp_path)
        req = gate.propose(kind="submit", summary="x")
        decided = gate.approve(req.id, decided_by="alice", reason="looks good")
        assert decided.status == ApprovalStatus.APPROVED
        assert decided.decided_by == "alice"
        assert decided.reason == "looks good"
        assert decided.decided_at is not None

    def test_reject(self, tmp_path):
        gate = ApprovalGate(base_dir=tmp_path)
        req = gate.propose(kind="submit", summary="x")
        decided = gate.reject(req.id)
        assert decided.status == ApprovalStatus.REJECTED

    def test_terminal_decisions_are_immutable(self, tmp_path):
        gate = ApprovalGate(base_dir=tmp_path)
        req = gate.propose(kind="submit", summary="x")
        gate.approve(req.id)
        with pytest.raises(GateError):
            gate.approve(req.id)
        with pytest.raises(GateError):
            gate.reject(req.id)

    def test_get_unknown_raises(self, tmp_path):
        gate = ApprovalGate(base_dir=tmp_path)
        with pytest.raises(GateError):
            gate.get("nope")

    def test_invalid_id_format_raises(self, tmp_path):
        gate = ApprovalGate(base_dir=tmp_path)
        with pytest.raises(GateError):
            gate.get("../escape")

    def test_list_filters_by_status(self, tmp_path):
        gate = ApprovalGate(base_dir=tmp_path)
        a = gate.propose(kind="x", summary="a")
        time.sleep(0.001)
        b = gate.propose(kind="x", summary="b")
        gate.approve(a.id)
        pending = gate.list(status=ApprovalStatus.PENDING)
        assert [r.id for r in pending] == [b.id]
        approved = gate.list(status=ApprovalStatus.APPROVED)
        assert [r.id for r in approved] == [a.id]

    def test_lazy_expiry_via_ttl(self, tmp_path):
        gate = ApprovalGate(base_dir=tmp_path)
        req = gate.propose(kind="x", summary="will expire", ttl_seconds=60)
        # Backdate by editing the persisted record directly.
        path = tmp_path / f"{req.id}.json"
        data = path.read_text(encoding="utf-8")
        old_time = (
            datetime.now(UTC) - timedelta(seconds=120)
        ).isoformat()
        new_data = data.replace(req.created_at, old_time)
        path.write_text(new_data, encoding="utf-8")
        fresh = gate.get(req.id)
        assert fresh.status == ApprovalStatus.EXPIRED
        # And cannot be approved post-expiry.
        with pytest.raises(GateError):
            gate.approve(req.id)


class TestGateRoutes:
    def _client(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "src.web.routes.agent.ApprovalGate",
            lambda: ApprovalGate(base_dir=tmp_path),
        )
        from src.web.app import create_app

        return TestClient(create_app())

    def test_list_pending(self, tmp_path, monkeypatch):
        gate = ApprovalGate(base_dir=tmp_path)
        a = gate.propose(kind="submit", summary="a")
        b = gate.propose(kind="submit", summary="b")
        gate.approve(b.id)

        client = self._client(tmp_path, monkeypatch)
        response = client.get("/api/agent/gate/requests?status=pending")
        assert response.status_code == 200
        ids = [r["id"] for r in response.json()["requests"]]
        assert ids == [a.id]

    def test_invalid_status_param(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        assert (
            client.get("/api/agent/gate/requests?status=bogus").status_code == 400
        )

    def test_get_unknown_404(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        assert client.get("/api/agent/gate/requests/nope").status_code == 404

    def test_approve_endpoint(self, tmp_path, monkeypatch):
        gate = ApprovalGate(base_dir=tmp_path)
        req = gate.propose(kind="submit", summary="x")

        client = self._client(tmp_path, monkeypatch)
        response = client.post(
            f"/api/agent/gate/requests/{req.id}/approve",
            json={"reason": "ok", "decided_by": "tester"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "approved"

    def test_reject_endpoint(self, tmp_path, monkeypatch):
        gate = ApprovalGate(base_dir=tmp_path)
        req = gate.propose(kind="submit", summary="x")

        client = self._client(tmp_path, monkeypatch)
        response = client.post(
            f"/api/agent/gate/requests/{req.id}/reject", json={}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "rejected"

    def test_double_decision_returns_409(self, tmp_path, monkeypatch):
        gate = ApprovalGate(base_dir=tmp_path)
        req = gate.propose(kind="submit", summary="x")
        gate.approve(req.id)

        client = self._client(tmp_path, monkeypatch)
        response = client.post(
            f"/api/agent/gate/requests/{req.id}/approve", json={}
        )
        assert response.status_code == 409

    def test_viewer_renders(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        response = client.get("/api/agent/gate/viewer")
        assert response.status_code == 200
        assert "Approval queue" in response.text
