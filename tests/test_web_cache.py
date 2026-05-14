"""Phase 12.6 -- ``/api/cache`` route tests.

The use-case layer is covered separately in ``test_application_cache``;
this file is about wire-up: the FastAPI route returns the right
shape, refuses destructive ops without confirmation, and surfaces
backend errors as the right status codes.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from src.web.app import create_app

    return TestClient(create_app())


class TestGetCache:
    def test_returns_snapshot_envelope(self, client: TestClient) -> None:
        fake_snapshot = {
            "ok": True,
            "redis": {
                "ok": True,
                "url": "redis://localhost:6379/0",
                "latency_ms": 2,
                "detail": "PONG",
            },
            "cache_version": "v1",
            "l2_available": True,
            "stats": {"hits_l1": 1, "hits_l2": 0, "misses": 0, "writes": 1},
            "estimated_dollars_saved": 0.0015,
            "namespaces": [
                {
                    "name": "llm",
                    "ttl_seconds": 604800,
                    "entries": 1,
                    "prefix": "v1:llm:",
                }
            ],
        }
        with patch(
            "src.application.cache.cache_snapshot", return_value=fake_snapshot
        ):
            response = client.get("/api/cache")
        assert response.status_code == 200
        payload = response.json()
        assert payload == fake_snapshot

    def test_passes_through_redis_down_state(self, client: TestClient) -> None:
        fake_snapshot = {
            "ok": True,
            "redis": {
                "ok": False,
                "url": "redis://localhost:6379/0",
                "latency_ms": None,
                "detail": "Connection refused",
            },
            "cache_version": "v1",
            "l2_available": False,
            "stats": {"hits_l1": 0, "hits_l2": 0, "misses": 0, "writes": 0},
            "estimated_dollars_saved": 0.0,
            "namespaces": [
                {
                    "name": "llm",
                    "ttl_seconds": 604800,
                    "entries": None,
                    "prefix": "v1:llm:",
                }
            ],
        }
        with patch(
            "src.application.cache.cache_snapshot", return_value=fake_snapshot
        ):
            response = client.get("/api/cache")
        # Returning the failure inside a 200 envelope is intentional --
        # the UI renders it directly. Mirrors the pattern used by
        # /api/providers/health.
        assert response.status_code == 200
        body = response.json()
        assert body["redis"]["ok"] is False
        assert body["l2_available"] is False


class TestDeleteCache:
    def test_requires_confirm_flag(self, client: TestClient) -> None:
        """``confirm: true`` must be in the body. A bare DELETE is
        rejected with 400 so a mistyped curl can't wipe the cache."""
        response = client.request("DELETE", "/api/cache/llm")
        assert response.status_code == 400
        assert "confirm" in response.text.lower()

    def test_rejects_confirm_false(self, client: TestClient) -> None:
        response = client.request(
            "DELETE",
            "/api/cache/llm",
            json={"confirm": False},
        )
        assert response.status_code == 400

    def test_confirm_true_calls_use_case(self, client: TestClient) -> None:
        with patch(
            "src.application.cache.clear_cache_namespace",
            return_value={
                "ok": True,
                "namespace": "llm",
                "deleted": 7,
                "message": "Cleared 7 entries from 'llm'.",
            },
        ) as use_case:
            response = client.request(
                "DELETE",
                "/api/cache/llm",
                json={"confirm": True},
            )
        assert response.status_code == 200
        assert response.json()["deleted"] == 7
        use_case.assert_called_once_with("llm")

    def test_invalid_namespace_returns_400(self, client: TestClient) -> None:
        """Glob metacharacters reach the use case and return
        ``invalid_namespace``; the route maps that to 400 (client
        error) rather than 500."""
        # FastAPI url-decodes the path param, so the use case is what
        # rejects "*".
        response = client.request(
            "DELETE",
            "/api/cache/%2A",  # url-encoded "*"
            json={"confirm": True},
        )
        assert response.status_code == 400
        body = response.json()
        # FastAPI wraps the use-case dict under ``detail`` for HTTPException.
        assert body["detail"]["error_code"] == "invalid_namespace"

    def test_backend_error_returns_500(self, client: TestClient) -> None:
        with patch(
            "src.application.cache.clear_cache_namespace",
            return_value={
                "ok": False,
                "error": "redis blew up",
                "error_code": "clear_failed",
            },
        ):
            response = client.request(
                "DELETE",
                "/api/cache/llm",
                json={"confirm": True},
            )
        assert response.status_code == 500
        body = response.json()
        assert body["detail"]["error_code"] == "clear_failed"
