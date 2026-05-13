"""Phase 11.4 -- provider health monitor.

Lightweight background poller that calls every configured provider's
``test_connection()`` on a schedule (default: every 5 minutes) and
caches the result in memory. The web layer exposes the cache through
``GET /api/providers/health`` so the Settings page can show a
``Last verified ...`` line backed by real telemetry instead of the
last manual-test timestamp.

Design choices:

* In-process, in-memory state. Phase 12 introduces Redis as the cache
  substrate; until then the monitor is fine to lose state on restart --
  the next tick will refill it within ``interval_seconds``.
* Async loop started from the FastAPI lifespan, not a thread, so we
  inherit the existing event loop and cancellation semantics. CLI
  invocations never start the monitor.
* The probe itself is synchronous (CLI subprocess + ``httpx.Client``)
  so we run it inside ``asyncio.to_thread`` to avoid blocking the loop.
* Only configured providers are probed. An unconfigured REST provider
  has no key to test; an unconfigured CLI provider is just "not on
  PATH" and ``is_installed()`` already covers that.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.providers.base import ProviderTestResult
from src.providers.registry import ProviderRegistry, get_registry

logger = logging.getLogger("autoapply.providers.health")

# 5 minutes -- balances "fresh enough for the Settings UI to feel live"
# against "don't spam the upstream API with /models pings". Override
# via :class:`ProviderHealthMonitor` constructor in tests.
DEFAULT_INTERVAL_SECONDS = 300
# Per-probe timeout. Each provider's ``test_connection`` already enforces
# its own bounds, but we add an outer guard so a wedged subprocess can't
# block the next round indefinitely.
DEFAULT_PROBE_TIMEOUT_SECONDS = 15


@dataclass
class ProviderHealthRecord:
    """Per-provider in-memory health snapshot."""

    provider_id: str
    ok: bool
    detail: str = ""
    latency_ms: int = 0
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "ok": self.ok,
            "detail": self.detail,
            "latency_ms": self.latency_ms,
            "checked_at": self.checked_at,
        }


@dataclass
class HealthSnapshot:
    """Public-shaped envelope returned by ``GET /api/providers/health``."""

    records: dict[str, ProviderHealthRecord] = field(default_factory=dict)
    last_run_started_at: str = ""
    last_run_finished_at: str = ""
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    running: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": {pid: r.to_dict() for pid, r in self.records.items()},
            "last_run_started_at": self.last_run_started_at,
            "last_run_finished_at": self.last_run_finished_at,
            "interval_seconds": self.interval_seconds,
            "running": self.running,
        }


class ProviderHealthMonitor:
    """Polls configured providers; serves a thread-safe in-memory snapshot."""

    def __init__(
        self,
        *,
        registry: ProviderRegistry | None = None,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        probe_timeout_seconds: int = DEFAULT_PROBE_TIMEOUT_SECONDS,
    ) -> None:
        self._registry = registry
        self.interval_seconds = interval_seconds
        self.probe_timeout_seconds = probe_timeout_seconds
        self._records: dict[str, ProviderHealthRecord] = {}
        self._lock = threading.Lock()
        self._last_run_started_at = ""
        self._last_run_finished_at = ""
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None

    # ----- registry plumbing -----

    @property
    def registry(self) -> ProviderRegistry:
        """Resolve the registry lazily so tests can construct the monitor
        before the global registry is initialised."""
        return self._registry or get_registry()

    # ----- public read API -----

    def snapshot(self) -> HealthSnapshot:
        """Thread-safe copy of the current health table."""
        with self._lock:
            records = {
                pid: ProviderHealthRecord(**r.to_dict())
                for pid, r in self._records.items()
            }
            return HealthSnapshot(
                records=records,
                last_run_started_at=self._last_run_started_at,
                last_run_finished_at=self._last_run_finished_at,
                interval_seconds=self.interval_seconds,
                running=self._task is not None and not self._task.done(),
            )

    def get(self, provider_id: str) -> ProviderHealthRecord | None:
        with self._lock:
            row = self._records.get(provider_id)
            if row is None:
                return None
            return ProviderHealthRecord(**row.to_dict())

    # ----- probing -----

    def probe_all(self) -> dict[str, ProviderHealthRecord]:
        """Run a single round of probes against every configured provider.

        Synchronous; safe to call from sync test code. Returns a fresh
        view of the just-collected records.
        """
        started = _now_iso()
        with self._lock:
            self._last_run_started_at = started
        # Iterate ids without holding the lock -- probing may take a while.
        try:
            providers = self.registry.configured()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Provider health monitor: registry lookup failed: %s", exc)
            providers = []

        new_records: dict[str, ProviderHealthRecord] = {}
        for provider in providers:
            try:
                t0 = time.monotonic()
                result = provider.test_connection(timeout=self.probe_timeout_seconds)
                latency = result.latency_ms or int((time.monotonic() - t0) * 1000)
                new_records[provider.id] = ProviderHealthRecord(
                    provider_id=provider.id,
                    ok=bool(result.ok),
                    detail=(result.detail or "")[:240],
                    latency_ms=latency,
                    checked_at=_now_iso(),
                )
            except Exception as exc:  # noqa: BLE001
                new_records[provider.id] = ProviderHealthRecord(
                    provider_id=provider.id,
                    ok=False,
                    detail=f"probe raised: {exc}"[:240],
                    latency_ms=0,
                    checked_at=_now_iso(),
                )

        finished = _now_iso()
        with self._lock:
            # Merge: keep records for providers that disappeared since
            # last round (e.g. user disconnected the CLI in another tab)
            # so the UI has a final "last seen" timestamp.
            self._records.update(new_records)
            self._last_run_finished_at = finished
        return new_records

    async def _probe_all_async(self) -> None:
        """Run ``probe_all`` in a worker thread so the event loop stays free."""
        await asyncio.to_thread(self.probe_all)

    # ----- async lifecycle -----

    async def start(self) -> None:
        """Spawn the background probe task. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        """Signal the background task to exit and await its shutdown."""
        if self._task is None:
            return
        assert self._stop_event is not None
        self._stop_event.set()
        # Cancel as a belt-and-suspenders fallback for tasks stuck inside
        # ``asyncio.to_thread`` (which doesn't honour the event).
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        self._task = None
        self._stop_event = None

    async def _run_forever(self) -> None:
        assert self._stop_event is not None
        try:
            # Probe once immediately so the UI doesn't show "no data" for
            # the first ``interval_seconds`` after server start.
            await self._probe_all_async()
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.interval_seconds
                    )
                    return  # stop signalled
                except TimeoutError:
                    await self._probe_all_async()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Provider health monitor loop crashed: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton -- the FastAPI lifespan wires this up.
# ---------------------------------------------------------------------------


_monitor: ProviderHealthMonitor | None = None


def get_monitor() -> ProviderHealthMonitor:
    global _monitor
    if _monitor is None:
        _monitor = ProviderHealthMonitor()
    return _monitor


def reset_monitor() -> None:
    """Drop the singleton -- used by tests that need a fresh instance."""
    global _monitor
    _monitor = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# Re-export for callers that want a sentinel value when no probe has run yet.
EMPTY_RESULT = ProviderTestResult(ok=False, detail="No probe has run yet.")
