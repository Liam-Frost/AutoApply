"""Phase 14.6: AutoApply task kinds.

Each task is a thin Celery wrapper over an existing application-layer
function. The wrapper's job is to:

* Validate the payload via a Pydantic model (so a malformed enqueue
  is rejected at the boundary, not deep inside a generator).
* Push the tenant context into the ContextVar (handled by
  :class:`AutoApplyTask.before_start`).
* Short-circuit via the idempotency key when applicable.
* Let Celery own retry / backoff / ack-late semantics.

Six concrete task names land here. Three Beat-driven helpers
(``daily_fanout``, ``jd_health_check``, ``cache_eviction``,
``linkedin_cookie_refresh``, ``status_sync``, ``gate_expire_sweep``)
also live here because the 14.5 schedule references them by string;
they are stubs today and grow real bodies in Phase 17.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from src.tasks.app import celery_app
from src.tasks.base import AutoApplyTask

logger = logging.getLogger(__name__)


# ---- Payload schemas -------------------------------------------------


class SearchRefreshPayload(BaseModel):
    query_id: str
    source: str = Field(default="linkedin")
    max_pages: int | None = None


class JobEnrichPayload(BaseModel):
    posting_id: str


class MaterialsGeneratePayload(BaseModel):
    job_id: str
    profile_id: str | None = None
    template_id: str | None = None
    document_types: list[str] = Field(default_factory=lambda: ["resume", "cover_letter"])


class ApplicationPreparePayload(BaseModel):
    application_id: str


class ApplicationFillPayload(BaseModel):
    application_id: str


class ApplicationSubmitPayload(BaseModel):
    application_id: str


class OrchestrationNightlyRunPayload(BaseModel):
    """Phase 17.1 nightly_run task payload.

    Mirrors :func:`src.orchestration.nightly_run.run_nightly` -- all
    fields default-friendly so a Beat tick can fire the task with no
    kwargs and still produce a useful run for the active applicant
    profile.
    """

    profile_id: str = "default"
    search_profile_id: str | None = None
    top_n: int = 10
    dry_run: bool = False


class StatusSyncPayload(BaseModel):
    """Empty by default -- the scheduled status_sync sweeps every
    in-flight application; a one-off CLI invocation can pass
    ``application_id`` to scope it."""

    application_id: str | None = None


def _coerce(model_cls: type[BaseModel], data: dict[str, Any] | None) -> BaseModel:
    try:
        return model_cls(**(data or {}))
    except ValidationError as exc:
        # Raise a TypeError so Celery's retry layer treats it as a
        # *terminal* failure (not transient); a malformed payload will
        # not get better on retry.
        raise TypeError(f"invalid {model_cls.__name__}: {exc}") from exc


# ---- Tasks: search ---------------------------------------------------


@celery_app.task(name="search.refresh", base=AutoApplyTask, bind=True)
def search_refresh(self: AutoApplyTask, **payload: Any) -> dict[str, Any]:
    """Re-scrape a saved search and update its ``search_results``
    links. Phase 13.4's ``cached_search`` does the real work; this is
    just the bounded entry point for the worker."""
    args = _coerce(SearchRefreshPayload, payload)
    # Phase 17 wires this into application/jobs.search_jobs. For now
    # we record what we *would* do so the trace + audit trail is
    # complete and CLI smoke tests can drive the task end to end.
    logger.info(
        "search.refresh queued query_id=%s source=%s", args.query_id, args.source
    )
    return {
        "task": "search.refresh",
        "query_id": args.query_id,
        "source": args.source,
        "status": "scheduled",
    }


@celery_app.task(name="search.daily_fanout", base=AutoApplyTask, bind=True)
def search_daily_fanout(self: AutoApplyTask) -> dict[str, Any]:
    """Beat-driven nightly search fan-out. Phase 17 explodes this into
    per-source ``search.refresh`` children."""
    logger.info("search.daily_fanout tick")
    return {"task": "search.daily_fanout", "status": "stubbed"}


# ---- Tasks: orchestration --------------------------------------------


@celery_app.task(name="notifications.morning_digest", base=AutoApplyTask, bind=True)
def notifications_morning_digest(self: AutoApplyTask) -> dict[str, Any]:
    """Phase 17.6: 08:00 morning digest tick.

    Computes the structured digest payload + (Phase 17.6 hook) emits
    it. The desktop-notification side is out of scope here; what the
    Beat tick produces is the same JSON the dashboard banner pulls
    via ``GET /api/digest``, so the only effect of this task in this
    sub-phase is to log the headline + return the payload (lands on
    the audit row so an operator can grep the task history for
    historical digests).
    """
    import asyncio  # noqa: PLC0415

    from src.core.database import get_session_factory  # noqa: PLC0415
    from src.orchestration.digest import compute_digest  # noqa: PLC0415
    from src.tasks.context import current_tenant_id  # noqa: PLC0415

    del asyncio  # not currently needed; placeholder if we go async

    tenant_id = current_tenant_id() or "default"
    factory = get_session_factory()
    with factory() as session:
        payload = compute_digest(session, tenant_id=tenant_id)
    logger.info("morning_digest tenant=%s: %s", tenant_id, payload.headline)
    return payload.to_dict()


@celery_app.task(name="orchestration.nightly_run", base=AutoApplyTask, bind=True)
def orchestration_nightly_run(
    self: AutoApplyTask, **payload: Any
) -> dict[str, Any]:
    """Phase 17.1: the 'sleep, wake to a review queue' top-level task.

    Search → score → enqueue ``materials.generate`` +
    ``application.prepare`` for the top-N qualified jobs. Never enqueues
    ``application.submit`` -- approval happens in the Phase 17.3 review
    queue UI and the Phase 17.5 pre-submit gate runs at that point.

    The real work lives in :func:`src.orchestration.nightly_run.run_nightly`;
    this wrapper is the AutoApplyTask boundary: payload validation +
    tenant context (via ``before_start``) + the return dict that lands
    on the audit row.
    """
    args = _coerce(OrchestrationNightlyRunPayload, payload)
    # Lazy import + asyncio.run keep this task body light when the
    # orchestrator package isn't loaded (e.g. in unrelated tests).
    import asyncio  # noqa: PLC0415

    from src.orchestration.nightly_run import run_nightly  # noqa: PLC0415
    from src.tasks.context import current_tenant_id  # noqa: PLC0415

    tenant_id = current_tenant_id() or "default"
    logger.info(
        "orchestration.nightly_run starting tenant=%s profile=%s top_n=%d dry_run=%s",
        tenant_id,
        args.profile_id,
        args.top_n,
        args.dry_run,
    )
    report = asyncio.run(
        run_nightly(
            tenant_id=tenant_id,
            profile_id=args.profile_id,
            search_profile_id=args.search_profile_id,
            top_n=args.top_n,
            dry_run=args.dry_run,
        )
    )
    # Phase 17.6: persist the report under data/nightly_runs/ so the
    # 08:00 morning digest can aggregate over it. Failure here is
    # non-fatal -- a missing report file just means the digest will
    # under-count for this run, which is preferable to the task
    # itself failing and re-queueing.
    try:
        from src.orchestration.digest import persist_nightly_report  # noqa: PLC0415

        persist_nightly_report(report)
    except Exception as exc:  # noqa: BLE001
        logger.warning("nightly_run: report persistence failed: %s", exc)

    return report.to_dict()


# ---- Tasks: jobs -----------------------------------------------------


@celery_app.task(name="jobs.enrich", base=AutoApplyTask, bind=True)
def jobs_enrich(self: AutoApplyTask, **payload: Any) -> dict[str, Any]:
    """Re-scrape a single posting and content-hash it. Real work lives
    in :func:`src.jobs.enrich.enrich_posting`."""
    args = _coerce(JobEnrichPayload, payload)
    logger.info("jobs.enrich queued posting_id=%s", args.posting_id)
    return {
        "task": "jobs.enrich",
        "posting_id": args.posting_id,
        "status": "scheduled",
    }


# ---- Tasks: materials ------------------------------------------------


@celery_app.task(name="materials.generate", base=AutoApplyTask, bind=True)
def materials_generate(self: AutoApplyTask, **payload: Any) -> dict[str, Any]:
    """Generate resume + cover letter against a JD snapshot. Real
    generators live in :mod:`src.generation`. Phase 15 will swap the
    body for the agent-driven path; the task name + payload contract
    stays the same."""
    args = _coerce(MaterialsGeneratePayload, payload)
    logger.info(
        "materials.generate queued job_id=%s document_types=%s",
        args.job_id,
        args.document_types,
    )
    return {
        "task": "materials.generate",
        "job_id": args.job_id,
        "document_types": args.document_types,
        "status": "scheduled",
    }


# ---- Tasks: application ----------------------------------------------


@celery_app.task(name="application.prepare", base=AutoApplyTask, bind=True)
def application_prepare(self: AutoApplyTask, **payload: Any) -> dict[str, Any]:
    args = _coerce(ApplicationPreparePayload, payload)
    logger.info("application.prepare queued application_id=%s", args.application_id)
    return {
        "task": "application.prepare",
        "application_id": args.application_id,
        "status": "scheduled",
    }


@celery_app.task(name="application.fill", base=AutoApplyTask, bind=True)
def application_fill(self: AutoApplyTask, **payload: Any) -> dict[str, Any]:
    args = _coerce(ApplicationFillPayload, payload)
    logger.info("application.fill queued application_id=%s", args.application_id)
    return {
        "task": "application.fill",
        "application_id": args.application_id,
        "status": "scheduled",
    }


@celery_app.task(name="application.submit", base=AutoApplyTask, bind=True)
def application_submit(self: AutoApplyTask, **payload: Any) -> dict[str, Any]:
    """The most dangerous task: actually clicks Submit. The Phase 17
    pre-submit gate (``should_refresh(job, "before_submit")``) blocks
    or refreshes if the JD snapshot is > 6h stale or the job is
    ``expired``. For now the body is a stub; Phase 17 owns the gate
    wiring."""
    args = _coerce(ApplicationSubmitPayload, payload)
    logger.info("application.submit queued application_id=%s", args.application_id)
    return {
        "task": "application.submit",
        "application_id": args.application_id,
        "status": "scheduled",
    }


# ---- Tasks: maintenance ----------------------------------------------


@celery_app.task(name="maintenance.status_sync", base=AutoApplyTask, bind=True)
def status_sync(self: AutoApplyTask, **payload: Any) -> dict[str, Any]:
    args = _coerce(StatusSyncPayload, payload)
    logger.info("status_sync sweep app_id=%s", args.application_id)
    return {"task": "maintenance.status_sync", "status": "stubbed"}


@celery_app.task(name="maintenance.jd_health_check", base=AutoApplyTask, bind=True)
def jd_health_check(self: AutoApplyTask) -> dict[str, Any]:
    """Drives the Phase 13.3 freshness state machine's time decay."""
    logger.info("jd_health_check tick")
    return {"task": "maintenance.jd_health_check", "status": "stubbed"}


@celery_app.task(name="maintenance.linkedin_cookie_refresh", base=AutoApplyTask, bind=True)
def linkedin_cookie_refresh(self: AutoApplyTask) -> dict[str, Any]:
    logger.info("linkedin_cookie_refresh tick")
    return {"task": "maintenance.linkedin_cookie_refresh", "status": "stubbed"}


@celery_app.task(name="maintenance.cache_eviction", base=AutoApplyTask, bind=True)
def cache_eviction(self: AutoApplyTask) -> dict[str, Any]:
    logger.info("cache_eviction tick")
    return {"task": "maintenance.cache_eviction", "status": "stubbed"}


@celery_app.task(name="maintenance.gate_expire_sweep", base=AutoApplyTask, bind=True)
def gate_expire_sweep(self: AutoApplyTask) -> dict[str, Any]:
    """Flips ``gate_queue`` rows past their TTL to ``expired``."""
    logger.info("gate_expire_sweep tick")
    return {"task": "maintenance.gate_expire_sweep", "status": "stubbed"}


# ---- Helper: discovery list for CLI introspection -------------------

#: Names workers know how to handle. ``autoapply tasks list`` reads this.
KNOWN_TASK_NAMES: tuple[str, ...] = (
    "search.refresh",
    "search.daily_fanout",
    "jobs.enrich",
    "materials.generate",
    "application.prepare",
    "application.fill",
    "application.submit",
    "orchestration.nightly_run",
    "notifications.morning_digest",
    "maintenance.status_sync",
    "maintenance.jd_health_check",
    "maintenance.linkedin_cookie_refresh",
    "maintenance.cache_eviction",
    "maintenance.gate_expire_sweep",
)


__all__ = [
    "ApplicationFillPayload",
    "ApplicationPreparePayload",
    "ApplicationSubmitPayload",
    "JobEnrichPayload",
    "KNOWN_TASK_NAMES",
    "MaterialsGeneratePayload",
    "SearchRefreshPayload",
    "StatusSyncPayload",
    "application_fill",
    "application_prepare",
    "application_submit",
    "cache_eviction",
    "gate_expire_sweep",
    "jd_health_check",
    "jobs_enrich",
    "linkedin_cookie_refresh",
    "materials_generate",
    "search_daily_fanout",
    "search_refresh",
    "status_sync",
]
