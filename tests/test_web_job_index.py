"""Phase 13.7: tests for the Job Index web surface.

These tests mock ``src.application.job_index`` so they don't require a
live Postgres -- the application module owns the session lifecycle and
the route handlers are pure shape converters.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from src.web.app import create_app  # noqa: PLC0415

    return TestClient(create_app())


def _payload(**overrides):
    base = {
        "source": "linkedin",
        "keywords": ["swe"],
        "locations": ["Toronto"],
        "time_filter": "week",
        "max_pages": 20,
    }
    base.update(overrides)
    return base


class TestFreshnessRoute:
    def test_returns_known_payload(self, client: TestClient) -> None:
        with patch(
            "src.application.job_index.get_search_freshness",
            return_value={
                "known": True,
                "status": "fresh",
                "result_count": 42,
                "age_hours": 3.5,
                "last_run_at": "2026-05-14T01:23:45+00:00",
                "last_success_at": "2026-05-14T01:23:45+00:00",
                "last_error": None,
                "fingerprint": "abc",
                "normalized_key": {"keywords": ["swe"]},
            },
        ):
            response = client.post("/api/jobs/index/freshness", json=_payload())
        assert response.status_code == 200
        body = response.json()
        assert body["known"] is True
        assert body["status"] == "fresh"
        assert body["result_count"] == 42
        assert abs(body["age_hours"] - 3.5) < 1e-6

    def test_unknown_search_returns_graceful_payload(self, client: TestClient) -> None:
        with patch(
            "src.application.job_index.get_search_freshness",
            return_value={"known": False, "fingerprint": "abc", "normalized_key": {}},
        ):
            response = client.post("/api/jobs/index/freshness", json=_payload())
        assert response.status_code == 200
        assert response.json()["known"] is False


class TestRefreshRoute:
    def test_enqueues_and_returns_task_id(self, client: TestClient) -> None:
        with patch(
            "src.application.job_index.enqueue_search_refresh",
            return_value={
                "ok": True,
                "task_id": "11111111-1111-1111-1111-111111111111",
                "query_id": "22222222-2222-2222-2222-222222222222",
                "fingerprint": "abc",
            },
        ):
            response = client.post("/api/jobs/index/refresh", json=_payload())
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["task_id"]
        assert body["query_id"]

    def test_failure_surfaces_503(self, client: TestClient) -> None:
        with patch(
            "src.application.job_index.enqueue_search_refresh",
            return_value={"ok": False, "error": "job index tables not present"},
        ):
            response = client.post("/api/jobs/index/refresh", json=_payload())
        assert response.status_code == 503
        assert "job index tables not present" in response.json()["detail"]["error"]


class TestPostingFreshnessRoute:
    def test_invalid_context_400(self, client: TestClient) -> None:
        response = client.get("/api/jobs/index/posting/abc?context=bogus")
        assert response.status_code == 400

    def test_valid_context_passes_through(self, client: TestClient) -> None:
        with patch(
            "src.application.job_index.posting_freshness",
            return_value={
                "known": True,
                "state": "active",
                "last_checked_at": "2026-05-14T00:00:00+00:00",
                "should_refresh": False,
                "reason": "age 3.0h < budget 24h (generate_materials)",
                "age_hours": 3.0,
                "budget_hours": 24,
            },
        ):
            response = client.get(
                "/api/jobs/index/posting/abc?context=generate_materials"
            )
        assert response.status_code == 200
        body = response.json()
        assert body["should_refresh"] is False
        assert body["budget_hours"] == 24
