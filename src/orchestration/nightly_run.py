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

import functools
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
    review_entry_ids: list[str] = field(default_factory=list)
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
    # Production wiring needs ``tenant_id`` so it can resolve
    # ``RawJob.id`` -> ``JobPosting.id`` for the review queue rows
    # (codex P1 fix). The 2-arg ``ScoreFn`` contract stays unchanged
    # so existing test stubs are untouched.
    if score_fn is None:
        score_fn = functools.partial(_default_score_fn, tenant_id=tenant_id)
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

    # Top-N already sorted descending by score_jobs. ``top_n <= 0`` is
    # an explicit "select none" -- codex P2 fix; the previous expression
    # treated 0/negative as "no cap" which silently fanned out tasks
    # for the entire qualified pool when the operator intended to
    # enqueue nothing.
    selected = qualified[:top_n] if top_n > 0 else []

    # ----- 3. Persist review-queue rows + enqueue (skipped on dry_run)
    #
    # Codex P1 fix (Phase 17.2 promise): the orchestrator is the source
    # of truth for "a job is ready for human review", so it creates the
    # review_queue rows directly in the same logical step it enqueues
    # the materials task. The downstream application.prepare task body
    # is still a stub (Phase 18 / later will fill it in with the
    # form-filler agent's prepare step); leaving the review_queue
    # population to it would mean the kanban stays empty even after a
    # successful nightly run.
    materials_ids: list[str] = []
    application_prepare_ids: list[str] = []
    review_entry_ids: list[str] = []

    if not dry_run:
        enqueue_fn = enqueue_fn or _default_enqueue_fn
        # Persist review entries first so the kanban shows them even if
        # the enqueue step trips on broker hiccups later. The factory is
        # late-imported to keep this module light for the test harness.
        try:
            review_entry_ids = _create_review_entries(
                tenant_id=tenant_id,
                run_id=run_id,
                selected=selected,
            )
        except Exception as exc:  # noqa: BLE001 -- non-fatal; record + continue
            logger.exception("nightly_run: review_queue insert failed")
            errors.append(f"review_queue: {type(exc).__name__}: {exc}")

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
                # Phase 17.2 review-queue entries are now persisted
                # above; application.prepare still gets enqueued so the
                # future form-filler agent has its work item, but the
                # kanban is no longer waiting on that stub to populate.
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
        review_entry_ids=review_entry_ids,
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


def _coerce_job_to_rawjob(job: Any) -> Any | None:
    """Convert ``application.jobs.serialize_job`` output back to ``RawJob``.

    Codex P1 fix: ``application.jobs.search_jobs`` returns a list of
    serialized dicts (the same shape the SPA consumes), but
    ``matching.scorer.score_jobs`` expects ``RawJob`` Pydantic objects.
    Without this conversion every real nightly run would crash inside
    scoring and the report would land with ``status="error"``.

    Items that are already ``RawJob`` pass through (so test stubs that
    inject raw objects keep working). Items that can't be coerced are
    dropped with a logged warning so one malformed row doesn't blank
    the whole run.
    """
    from src.application.matching import _coerce_to_raw_job  # noqa: PLC0415
    from src.intake.schema import RawJob  # noqa: PLC0415

    if isinstance(job, RawJob):
        return job
    if isinstance(job, dict):
        coerced = _coerce_to_raw_job(job)
        if coerced is None:
            logger.warning(
                "nightly_run: dropping unscoreable job: id=%s company=%s",
                job.get("id"),
                job.get("company"),
            )
        return coerced
    # Some other shape (e.g. a Pydantic model from a future scraper).
    # Use it as-is and let scoring complain if it doesn't match.
    return job


def _default_score_fn(
    jobs: list[Any], profile_id: str, *, tenant_id: str = ""
) -> list[Any]:
    """Default wiring: load YAML, build scoring context, score the batch.

    Coerces serialized-dict jobs back to :class:`RawJob` first (see
    :func:`_coerce_job_to_rawjob`) so the production search path is
    actually scoreable.

    Then (codex P1 fix) resolves the persistent ``JobPosting.id`` +
    ``latest_snapshot_id`` for each scored job and overwrites
    ``breakdown.job_id`` / ``breakdown.job_snapshot_id`` so the
    pre-submit gate (which queries ``JobPosting`` by id) can find the
    row. Without this, every nightly-created review entry would land
    with ``RawJob.id`` (a fresh UUID per scrape) and approve+submit
    would always 404 with ``missing_binding``.

    ``tenant_id`` is captured via ``functools.partial`` in
    :func:`run_nightly`; the public ``ScoreFn`` contract stays 2-arg so
    test stubs are unaffected.
    """
    from src.application.profile import get_profile_path  # noqa: PLC0415
    from src.matching.scorer import build_scoring_context  # noqa: PLC0415
    from src.matching.scorer import score_jobs as score_ranked  # noqa: PLC0415
    from src.memory.profile import load_profile_yaml  # noqa: PLC0415

    path = get_profile_path(profile_id)
    if path is None or not path.exists():
        raise NightlyRunError(f"profile {profile_id!r} not found at {path}")
    profile_data = load_profile_yaml(path)
    ctx = build_scoring_context(profile_data)

    raw_jobs = [_coerce_job_to_rawjob(j) for j in jobs]
    raw_jobs = [j for j in raw_jobs if j is not None]
    breakdowns = score_ranked(raw_jobs, ctx)

    if tenant_id:
        try:
            _resolve_and_patch_posting_ids(breakdowns, raw_jobs, tenant_id)
        except Exception:  # noqa: BLE001 - non-fatal; logged
            logger.exception(
                "nightly_run: posting-id resolution failed; review entries "
                "will land with RawJob.id and pre-submit may fail"
            )

    return breakdowns


def _resolve_and_patch_posting_ids(
    breakdowns: list[Any],
    raw_jobs: list[Any],
    tenant_id: str,
) -> None:
    """Look up ``JobPosting`` by ``(tenant_id, source, source_id)`` and
    rewrite each breakdown's ``job_id`` / ``job_snapshot_id`` to the
    persisted ids.

    Operates in-place because :class:`ScoreBreakdown` is a dataclass we
    own. RawJob.id → posting.id mapping is keyed on (source, source_id)
    which is the Phase 13 ``uq_job_postings_tenant_source`` constraint.

    Misses (a posting the scorer scored but the job index never saw)
    leave the breakdown unchanged; the review entry will still be
    inserted but the pre-submit gate will report ``missing_binding``
    until the next refresh fills in the posting row. That's strictly
    better than the current behaviour (silent failure on every entry).
    """
    if not breakdowns or not raw_jobs:
        return

    from sqlalchemy import and_, or_, select  # noqa: PLC0415

    from src.core.database import get_session_factory  # noqa: PLC0415
    from src.core.models import JobPosting  # noqa: PLC0415

    # Build (source, source_id) keys from raw_jobs and index them by
    # the RawJob.id so we can map breakdown.job_id (RawJob.id as str) ->
    # source key after the DB lookup.
    rawjob_id_to_key: dict[str, tuple[str, str]] = {}
    keys: set[tuple[str, str]] = set()
    for rj in raw_jobs:
        source = getattr(rj, "source", None)
        source_id = getattr(rj, "source_id", None)
        rj_id = getattr(rj, "id", None)
        if source and source_id and rj_id is not None:
            key = (str(source), str(source_id))
            keys.add(key)
            rawjob_id_to_key[str(rj_id)] = key

    if not keys:
        return

    factory = get_session_factory()
    with factory() as session:
        rows = (
            session.execute(
                select(
                    JobPosting.id,
                    JobPosting.latest_snapshot_id,
                    JobPosting.source,
                    JobPosting.source_id,
                ).where(
                    JobPosting.tenant_id == tenant_id,
                    or_(
                        *[
                            and_(
                                JobPosting.source == s,
                                JobPosting.source_id == sid,
                            )
                            for s, sid in keys
                        ]
                    ),
                )
            )
            .all()
        )
    key_to_ids: dict[tuple[str, str], tuple[Any, Any]] = {
        (row.source, row.source_id): (row.id, row.latest_snapshot_id)
        for row in rows
    }

    for bd in breakdowns:
        rj_id = str(getattr(bd, "job_id", "") or "")
        key = rawjob_id_to_key.get(rj_id)
        if key is None:
            continue
        persisted = key_to_ids.get(key)
        if persisted is None:
            # Scored a job that was never persisted (search bypassed the
            # job index, or the row was retention-purged between scrape
            # and score). Leave the breakdown alone -- the review row
            # will still write but pre-submit will fail informatively.
            continue
        posting_id, snapshot_id = persisted
        # Mutate in place. ScoreBreakdown is a dataclass; both fields
        # are typed as ``str | None`` for job_snapshot_id (Phase 16.1)
        # and ``str`` for job_id.
        bd.job_id = str(posting_id)
        if snapshot_id is not None:
            bd.job_snapshot_id = str(snapshot_id)


def _create_review_entries(
    *,
    tenant_id: str,
    run_id: str,
    selected: list[Any],
) -> list[str]:
    """Insert one ``pending`` review_queue row per selected breakdown.

    Codex P1 fix: the Phase 17.2 promise is "the operator wakes up to
    /api/review populated with last night's matches". Persisting from
    the orchestrator keeps that promise true even though the
    downstream ``application.prepare`` task body is still a stub
    (Phase 18+ will wire the form-filler agent into it).

    Each entry is bound to:
      * ``job_id`` from the breakdown (Phase 13 audit link)
      * ``job_snapshot_id`` from the breakdown
      * ``run_id`` from this nightly_run (so the digest groups them)
      * the structured ``score_breakdown`` so the popover renders
        without re-scoring
      * denormalised ``company`` / ``title`` so the kanban renders
        without joining ``jobs``

    Returns the list of inserted entry ids (as strings).
    """
    from src.application.review import CreateEntryArgs, create_entry  # noqa: PLC0415
    from src.core.database import get_session_factory  # noqa: PLC0415

    if not selected:
        return []

    factory = get_session_factory()
    inserted: list[str] = []
    with factory() as session, session.begin():
        for breakdown in selected:
            try:
                bd_dict = (
                    breakdown.to_dict()
                    if hasattr(breakdown, "to_dict")
                    else {}
                )
            except Exception:  # noqa: BLE001 -- defensive
                bd_dict = {}
            entry = create_entry(
                session,
                CreateEntryArgs(
                    tenant_id=tenant_id,
                    job_id=getattr(breakdown, "job_id", None),
                    job_snapshot_id=getattr(breakdown, "job_snapshot_id", None),
                    materials_path=None,
                    score_breakdown=bd_dict,
                    company=getattr(breakdown, "company", None),
                    title=getattr(breakdown, "title", None),
                    run_id=run_id,
                ),
            )
            inserted.append(str(entry.id))
    return inserted


def _default_enqueue_fn(task_name: str, payload: dict[str, Any]) -> str:
    """Default wiring: hand off to the Phase 14 Celery app."""
    from src.tasks.app import celery_app  # noqa: PLC0415

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
