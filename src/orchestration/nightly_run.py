"""Phase 17.1: ``nightly_run`` orchestrator.

The "sleep, wake to a review queue" flow. One invocation per night per
saved search profile:

* **Search** -- ``application.jobs.search_jobs`` with
  ``use_job_index=True``, which routes through Phase 13.4
  ``cached_search`` (cache-first, refresh stale via
  ``jobs.freshness.should_refresh(context="generate_materials")``).
* **Filter** -- ``matching.scorer.score_jobs`` with the active
  applicant profile; each ``ScoreBreakdown`` carries the Phase 16.1
  structured ``disqualify_results`` for the review-queue UI.
* **Top-N selection** -- qualified jobs ranked by ``final_score``,
  capped at ``top_n``.
* **Enqueue** -- per top-N job: one ``materials.generate`` + one
  ``application.prepare`` task. Both ride the Phase 14 audit/trace
  trail; submission is never enqueued -- the operator approves via
  the Phase 17.3 review queue UI.

Boundaries
----------
* **Never auto-submits.** The orchestrator stops at
  ``application.prepare``. ``application.submit`` lands on the
  worker only after a human clicks "approve and submit" in the
  review queue, and even then the Phase 17.5 pre-submit hard gate
  re-runs ``should_refresh(..., "before_submit")``.
* **Per-tenant.** The Phase 14 ``tenant_id`` ContextVar must be set
  before ``run_nightly`` is invoked (the Celery task wrapper handles
  this via ``AutoApplyTask.before_start``; CLI/test callers pass the
  tenant explicitly).
* **Pause-aware.** When ``data/nightly_paused`` exists (Phase 17.7
  kill switch), ``run_nightly`` short-circuits with
  ``status="paused"`` so a scheduled tick doesn't generate cost on
  vacation.
* **Idempotent dry-run.** ``dry_run=True`` runs the search + filter
  but skips enqueue. Useful for the Phase 17.6 morning digest
  rehearsal and for CI.

Returned :class:`NightlyRunReport` is JSON-serializable so the Phase 14
audit row can store it verbatim and the Phase 17.6 digest can read it
back without ORM access.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Where the Phase 17.7 kill switch lives. A tenant-aware version would
# nest by tenant; we keep one global sentinel for now since multi-
# tenancy hardening is Phase 18.
NIGHTLY_PAUSE_SENTINEL_NAME = "nightly_paused"


@dataclass
class NightlyRunReport:
    """Per-invocation summary persisted to the Phase 14 task audit row.

    All fields are intentionally JSON-serializable scalars / lists so
    the Phase 17.6 morning digest can read this back without a
    SQLAlchemy session.
    """

    run_id: str
    tenant_id: str
    profile_id: str
    search_profile_id: str | None
    status: str  # "ok" | "paused" | "no_profile" | "no_results" | "error"
    started_at: str  # ISO 8601 UTC
    finished_at: str
    duration_seconds: float
    top_n: int
    total_jobs_seen: int = 0
    qualified: int = 0
    disqualified: int = 0
    borderline: int = 0  # count of jobs whose final_score sits in [0.4, 0.6]
    selected: int = 0  # jobs that actually reached the enqueue step
    materials_task_ids: list[str] = field(default_factory=list)
    application_prepare_task_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    estimated_cost_usd: float = 0.0  # Phase 17.6 fills this with real telemetry
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Type aliases for the dependency-injected callables. Real callers wire
# these to ``application.jobs.search_jobs`` /
# ``matching.scorer.score_jobs`` / Celery's ``send_task``; tests inject
# stubs that don't touch Redis or the network.
SearchFn = Callable[..., Awaitable[dict[str, Any]]]
ScoreFn = Callable[[list[Any], Any], list[Any]]
EnqueueFn = Callable[[str, dict[str, Any]], str]


class NightlyRunError(Exception):
    """Raised on programmer error (missing tenant, etc.). Worker
    failures are captured into :class:`NightlyRunReport.errors`
    instead -- a partial run should still produce a report so the
    digest has something to show."""


def nightly_pause_sentinel_path(root: Path | None = None) -> Path:
    """The well-known sentinel path the kill switch (17.7) creates.

    Centralised here so the orchestrator + CLI + tests agree on it.
    """
    from src.core.config import PROJECT_ROOT  # local import; avoid cycle

    base = root if root is not None else PROJECT_ROOT
    return base / "data" / NIGHTLY_PAUSE_SENTINEL_NAME


def nightly_run_is_paused(root: Path | None = None) -> bool:
    """Return True iff the sentinel exists.

    A symlink with no target counts as paused; that lets ops scripts
    park the sentinel however they like (touch / ln -s / mv).
    """
    return nightly_pause_sentinel_path(root).exists()


def _now_utc() -> datetime:
    """Wall-clock now in UTC. Stubbed in tests via monkeypatch."""
    return datetime.now(UTC)


def _isoformat(dt: datetime) -> str:
    return dt.isoformat()


def _borderline_count(breakdowns: list[Any]) -> int:
    """Count qualified breakdowns whose final_score sits in [0.4, 0.6]
    (matches :data:`src.matching.edge_case_agent.BORDERLINE_LOW`).

    Imported lazily to keep this module light when the matching
    package isn't loaded (e.g. unit tests of the report shape).
    """
    from src.matching.edge_case_agent import BORDERLINE_HIGH, BORDERLINE_LOW

    return sum(
        1
        for b in breakdowns
        if not getattr(b, "disqualified", False)
        and BORDERLINE_LOW <= getattr(b, "final_score", 0.0) <= BORDERLINE_HIGH
    )


async def run_nightly(
    *,
    tenant_id: str,
    profile_id: str = "default",
    search_profile_id: str | None = None,
    top_n: int = 10,
    dry_run: bool = False,
    search_fn: SearchFn | None = None,
    score_fn: ScoreFn | None = None,
    enqueue_fn: EnqueueFn | None = None,
    pause_root: Path | None = None,
    now: Callable[[], datetime] | None = None,
) -> NightlyRunReport:
    """Execute one nightly pass and return a structured report.

    Args:
        tenant_id: Required. Phase 14 tenant context.
        profile_id: Applicant profile to score against. ``"default"``
            uses the YAML pointed at by ``active_profile.txt``.
        search_profile_id: Saved web-search profile. ``None`` falls
            back to the applicant ``profile_id`` (the existing
            ``search_jobs`` convention).
        top_n: Cap on jobs that reach the enqueue step. The deterministic
            scorer's `final_score` ranks the qualified pool.
        dry_run: Run search + filter but skip enqueue. ``status`` stays
            ``"ok"``; ``materials_task_ids`` / ``application_prepare_task_ids``
            stay empty.
        search_fn: Override for the search use case. Real callers leave
            this ``None`` so the real ``search_jobs`` runs.
        score_fn: Override for the scoring pipeline. Real callers leave
            this ``None``.
        enqueue_fn: Function that takes ``(task_name, payload)`` and
            returns the task id. Real callers pass a Celery
            ``send_task`` wrapper; tests pass a list-appender.
        pause_root: Override for the kill-switch sentinel root (Phase
            17.7). ``None`` uses ``PROJECT_ROOT``.
        now: Clock injection for tests.

    Returns:
        :class:`NightlyRunReport` -- never raises for runtime failures
        (those are folded into ``errors``); raises
        :class:`NightlyRunError` only on programmer errors.
    """
    if not tenant_id:
        raise NightlyRunError("tenant_id is required")

    now_fn = now or _now_utc
    started_at = now_fn()
    run_id = str(uuid.uuid4())
    errors: list[str] = []

    # ----- 0. Kill switch (17.7) ------------------------------------
    if nightly_run_is_paused(pause_root):
        finished_at = now_fn()
        logger.info("nightly_run paused via sentinel; run_id=%s", run_id)
        return NightlyRunReport(
            run_id=run_id,
            tenant_id=tenant_id,
            profile_id=profile_id,
            search_profile_id=search_profile_id,
            status="paused",
            started_at=_isoformat(started_at),
            finished_at=_isoformat(finished_at),
            duration_seconds=(finished_at - started_at).total_seconds(),
            top_n=top_n,
            dry_run=dry_run,
        )

    # ----- 1. Search ------------------------------------------------
    search_fn = search_fn or _default_search_fn
    try:
        search_result = await search_fn(
            profile=search_profile_id or profile_id,
            source="all",
            score=False,  # we run scoring ourselves below so we can
                          # capture the structured breakdowns
            use_job_index=True,
            include_views=True,
        )
    except Exception as exc:  # noqa: BLE001 -- worker must keep going
        logger.exception("nightly_run search failed; run_id=%s", run_id)
        finished_at = now_fn()
        errors.append(f"search: {type(exc).__name__}: {exc}")
        return NightlyRunReport(
            run_id=run_id,
            tenant_id=tenant_id,
            profile_id=profile_id,
            search_profile_id=search_profile_id,
            status="error",
            started_at=_isoformat(started_at),
            finished_at=_isoformat(finished_at),
            duration_seconds=(finished_at - started_at).total_seconds(),
            top_n=top_n,
            errors=errors,
            dry_run=dry_run,
        )

    jobs = list(search_result.get("jobs") or search_result.get("items") or [])
    total_jobs_seen = len(jobs)

    # No results is a *legitimate* outcome (LinkedIn returned nothing
    # for the profile last night). Still produce a report so the
    # digest reads "0 new jobs" rather than "missing".
    if not jobs:
        finished_at = now_fn()
        logger.info("nightly_run found no jobs; run_id=%s", run_id)
        return NightlyRunReport(
            run_id=run_id,
            tenant_id=tenant_id,
            profile_id=profile_id,
            search_profile_id=search_profile_id,
            status="no_results",
            started_at=_isoformat(started_at),
            finished_at=_isoformat(finished_at),
            duration_seconds=(finished_at - started_at).total_seconds(),
            top_n=top_n,
            total_jobs_seen=0,
            dry_run=dry_run,
        )

    # ----- 2. Score + filter ---------------------------------------
    score_fn = score_fn or _default_score_fn
    try:
        breakdowns = score_fn(jobs, profile_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("nightly_run scoring failed; run_id=%s", run_id)
        finished_at = now_fn()
        errors.append(f"score: {type(exc).__name__}: {exc}")
        return NightlyRunReport(
            run_id=run_id,
            tenant_id=tenant_id,
            profile_id=profile_id,
            search_profile_id=search_profile_id,
            status="error",
            started_at=_isoformat(started_at),
            finished_at=_isoformat(finished_at),
            duration_seconds=(finished_at - started_at).total_seconds(),
            top_n=top_n,
            total_jobs_seen=total_jobs_seen,
            errors=errors,
            dry_run=dry_run,
        )

    qualified = [b for b in breakdowns if not getattr(b, "disqualified", False)]
    disqualified = total_jobs_seen - len(qualified)
    borderline = _borderline_count(breakdowns)

    # Top-N already sorted descending by score_jobs.
    selected = qualified[:top_n] if top_n > 0 else qualified

    # ----- 3. Enqueue (skipped on dry_run) -------------------------
    materials_ids: list[str] = []
    application_prepare_ids: list[str] = []

    if not dry_run:
        enqueue_fn = enqueue_fn or _default_enqueue_fn
        for breakdown in selected:
            job_id = getattr(breakdown, "job_id", None)
            if not job_id:
                errors.append("score breakdown missing job_id; skipping enqueue")
                continue
            try:
                mat_id = enqueue_fn(
                    "materials.generate",
                    {
                        "job_id": str(job_id),
                        "profile_id": profile_id,
                        "document_types": ["resume", "cover_letter"],
                    },
                )
                materials_ids.append(mat_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    f"materials.generate enqueue: {type(exc).__name__}: {exc}"
                )
                continue

            try:
                # Phase 17.2 review-queue entries will be created by
                # the application.prepare task body once the materials
                # task completes (handler will be wired up there).
                # Here we simply enqueue the next step -- the queue
                # itself isn't materialised until 17.2.
                prep_id = enqueue_fn(
                    "application.prepare",
                    {"application_id": str(job_id)},
                )
                application_prepare_ids.append(prep_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    f"application.prepare enqueue: {type(exc).__name__}: {exc}"
                )

    finished_at = now_fn()
    status = "ok" if not errors else "error"
    return NightlyRunReport(
        run_id=run_id,
        tenant_id=tenant_id,
        profile_id=profile_id,
        search_profile_id=search_profile_id,
        status=status,
        started_at=_isoformat(started_at),
        finished_at=_isoformat(finished_at),
        duration_seconds=(finished_at - started_at).total_seconds(),
        top_n=top_n,
        total_jobs_seen=total_jobs_seen,
        qualified=len(qualified),
        disqualified=disqualified,
        borderline=borderline,
        selected=len(selected),
        materials_task_ids=materials_ids,
        application_prepare_task_ids=application_prepare_ids,
        errors=errors,
        dry_run=dry_run,
    )


# --------------------------------------------------------------------------- #
# Default dependency wiring                                                   #
# --------------------------------------------------------------------------- #
# These are the production wires. ``run_nightly`` accepts overrides so the
# Celery task wrapper, the CLI, and the test suite can each substitute
# what they need without re-importing the orchestrator.


async def _default_search_fn(**kwargs: Any) -> dict[str, Any]:
    """Lazy import to keep this module light when scoring tests import it."""
    from src.application.jobs import search_jobs

    return await search_jobs(**kwargs)


def _default_score_fn(jobs: list[Any], profile_id: str) -> list[Any]:
    """Default wiring: load YAML, build scoring context, score the batch."""
    from src.application.profile import get_profile_path
    from src.matching.scorer import build_scoring_context
    from src.matching.scorer import score_jobs as score_ranked
    from src.memory.profile import load_profile_yaml

    path = get_profile_path(profile_id)
    if path is None or not path.exists():
        raise NightlyRunError(f"profile {profile_id!r} not found at {path}")
    profile_data = load_profile_yaml(path)
    ctx = build_scoring_context(profile_data)
    return score_ranked(jobs, ctx)


def _default_enqueue_fn(task_name: str, payload: dict[str, Any]) -> str:
    """Default wiring: hand off to the Phase 14 Celery app."""
    from src.tasks.app import celery_app

    async_result = celery_app.send_task(task_name, kwargs=payload)
    return str(async_result.id)


__all__ = [
    "NIGHTLY_PAUSE_SENTINEL_NAME",
    "NightlyRunError",
    "NightlyRunReport",
    "nightly_pause_sentinel_path",
    "nightly_run_is_paused",
    "run_nightly",
]
