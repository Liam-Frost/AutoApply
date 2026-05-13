"""Phase 11.4 -- provider health monitor.

Covers:
* ``probe_all`` collects records from every configured provider and
  isolates exceptions thrown by ``test_connection``.
* Records survive between rounds (so the UI keeps a "last seen"
  timestamp for providers that briefly drop off).
* The ``snapshot()`` is a deep copy -- mutating it doesn't affect the
  monitor's internal state.
* ``GET /api/providers/health`` returns the monitor's snapshot shape.
* The ``AUTOAPPLY_DISABLE_HEALTH_MONITOR`` env var prevents the
  FastAPI lifespan from starting the background task.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.providers.base import LLMProvider, ProviderTestResult
from src.providers.health import ProviderHealthMonitor, reset_monitor


def _fake_provider(provider_id: str, *, result: ProviderTestResult) -> LLMProvider:
    """Build a minimal LLMProvider stub bound to a scripted test result."""
    mock = MagicMock(spec=LLMProvider)
    mock.id = provider_id
    mock.test_connection.return_value = result
    return mock


def _registry_with(*providers: LLMProvider) -> MagicMock:
    registry = MagicMock()
    registry.configured.return_value = list(providers)
    return registry


class TestProbeAll:
    def test_records_each_configured_provider(self) -> None:
        prov_a = _fake_provider(
            "openai",
            result=ProviderTestResult(ok=True, detail="200 OK", latency_ms=42),
        )
        prov_b = _fake_provider(
            "anthropic",
            result=ProviderTestResult(ok=False, detail="401", latency_ms=5),
        )

        monitor = ProviderHealthMonitor(registry=_registry_with(prov_a, prov_b))
        records = monitor.probe_all()

        assert set(records) == {"openai", "anthropic"}
        assert records["openai"].ok is True
        assert records["openai"].latency_ms == 42
        assert records["openai"].detail == "200 OK"
        assert records["anthropic"].ok is False
        assert records["anthropic"].detail == "401"
        # checked_at is ISO8601, contains 'T' and 'Z' or '+00:00'.
        assert "T" in records["openai"].checked_at

    def test_probe_isolates_provider_exceptions(self) -> None:
        good = _fake_provider(
            "openai", result=ProviderTestResult(ok=True, detail="ok")
        )
        bad = MagicMock(spec=LLMProvider)
        bad.id = "anthropic"
        bad.test_connection.side_effect = RuntimeError("boom")

        monitor = ProviderHealthMonitor(registry=_registry_with(good, bad))
        records = monitor.probe_all()

        # Failure of one provider must not eat the others.
        assert records["openai"].ok is True
        assert records["anthropic"].ok is False
        assert "boom" in records["anthropic"].detail

    def test_records_merge_across_rounds(self) -> None:
        prov_a = _fake_provider("a", result=ProviderTestResult(ok=True))
        monitor = ProviderHealthMonitor(registry=_registry_with(prov_a))
        monitor.probe_all()

        # Round 2: provider disappears from the registry. The previous
        # record should still be available via snapshot() so the UI
        # doesn't lose history.
        prov_a_gone = ProviderHealthMonitor(
            registry=_registry_with(prov_a)
        )  # placeholder
        del prov_a_gone
        monitor._registry = _registry_with()  # noqa: SLF001 -- test-only fixture
        monitor.probe_all()

        snap = monitor.snapshot()
        assert "a" in snap.records  # carried forward

    def test_snapshot_is_a_deep_copy(self) -> None:
        prov = _fake_provider("openai", result=ProviderTestResult(ok=True))
        monitor = ProviderHealthMonitor(registry=_registry_with(prov))
        monitor.probe_all()

        snap1 = monitor.snapshot()
        # Mutate the snapshot externally...
        snap1.records["openai"].detail = "MUTATED"

        snap2 = monitor.snapshot()
        # ...the second snapshot is untouched.
        assert snap2.records["openai"].detail != "MUTATED"


class TestHealthEndpoint:
    def test_get_health_returns_snapshot(self, monkeypatch) -> None:
        from src.providers.health import get_monitor  # noqa: PLC0415

        # Inject a monitor seeded with a known record so the test doesn't
        # depend on the lifespan having fired a real probe.
        reset_monitor()
        monitor = get_monitor()
        monitor._records["openai"] = (  # noqa: SLF001 -- test fixture
            __import__("src.providers.health", fromlist=["ProviderHealthRecord"])
            .ProviderHealthRecord(
                provider_id="openai",
                ok=True,
                detail="seeded",
                latency_ms=10,
                checked_at="2026-05-12T10:00:00+00:00",
            )
        )

        monkeypatch.setenv("AUTOAPPLY_DISABLE_HEALTH_MONITOR", "1")

        from src.web.app import create_app  # noqa: PLC0415

        app = create_app()
        with TestClient(app) as client:
            response = client.get("/api/providers/health")

        assert response.status_code == 200
        body = response.json()
        assert "records" in body
        assert body["records"]["openai"]["ok"] is True
        assert body["records"]["openai"]["detail"] == "seeded"

        reset_monitor()

    def test_lifespan_respects_disable_env(self, monkeypatch) -> None:
        # The env-flag path must not start any task -- starting one in
        # a test event loop that doesn't survive would leak warnings.
        monkeypatch.setenv("AUTOAPPLY_DISABLE_HEALTH_MONITOR", "1")
        reset_monitor()

        from src.web.app import create_app  # noqa: PLC0415

        app = create_app()
        with TestClient(app):
            # Lifespan fired; if it had started the task we'd see it
            # on the monitor. Force-fetch the singleton to confirm.
            from src.providers.health import get_monitor  # noqa: PLC0415

            monitor = get_monitor()
            assert monitor._task is None  # noqa: SLF001 -- inspecting opt-out
        reset_monitor()


class TestSingleton:
    def test_reset_drops_state(self) -> None:
        from src.providers.health import get_monitor  # noqa: PLC0415

        first = get_monitor()
        first._records["x"] = "sentinel"  # noqa: SLF001
        reset_monitor()
        second = get_monitor()
        assert second is not first
        assert "x" not in second._records  # noqa: SLF001
        reset_monitor()


def _unused_os_check() -> None:
    """Pin a reference to os so the import isn't flagged as unused."""
    _ = os.environ
