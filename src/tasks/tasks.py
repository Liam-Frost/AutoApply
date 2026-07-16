"""Phase 14.6 task kinds, Phase 18.1 worker stub closeout.

Each task is a thin Celery wrapper over an existing application-layer
function. The wrapper's job is to:

* Validate the payload via a Pydantic model (so a malformed enqueue
  is rejected at the boundary, not deep inside a generator).
* Push the tenant context into the ContextVar (handled by
  :class:`AutoApplyTask.before_start`).
* Short-circuit via the idempotency key when applicable.
* Let Celery own retry / backoff / ack-late semantics.

Phase 18.1 replaced the fake-success ``status="scheduled"`` /
``status="stubbed"`` returns with real call chains:

* ``materials.generate`` invokes :func:`generate_material_for_job`
  for each requested document_type, atomically writes artifacts via
  :mod:`src.maintenance.atomic`, and stitches the result back onto
  the Application + ReviewQueueEntry rows.
* ``jobs.enrich`` calls :func:`enrich_posting` against the latest
  stored snapshot so the Phase 19 content-changed listener chain
  fires when the underlying content has drifted.
* ``application.prepare`` walks the Application row's invariants and
  links the latest materials onto the matching ReviewQueueEntry.
* ``application.fill`` / ``maintenance.status_sync`` return explicit
  ``status="not_implemented"`` because their browser / outcome-sync
  implementations sit behind a later phase; the names + payload
  contract stay so callers don't get a registration error.
* ``application.submit`` runs the Phase 17.5 pre-submit gate
  (``should_refresh(..., "before_submit")``) and parks the row at
  ``waiting_human`` via :mod:`src.tasks.gate` if the gate refuses,
  or returns ``not_implemented`` on the actual click-submit step.
* ``maintenance.gate_expire_sweep`` flips ``gate_queue`` rows past
  their TTL to ``expired``.
* ``maintenance.jd_health_check`` walks ``job_postings`` and applies
  :func:`project_by_time` so freshness decays without a manual nudge.
* ``maintenance.linkedin_cookie_refresh`` probes the LinkedIn
  session and records pass/fail in the audit row.
* ``maintenance.cache_eviction`` (Phase 18.4) drives the artifact
  cleanup + quarantine pipeline.
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
    # Phase 18.2: optional inline job dict for callers (e.g. the
    # JobsView "Generate" button) that have search-result data but
    # haven't persisted a JobPosting yet. When present, the task body
    # uses this payload directly and skips the JobPosting / JobSnapshot
    # lookup. ``job_id`` is still required so the audit row carries a
    # stable identifier.
    job: dict[str, Any] | None = None
    # Phase 18.2: when set, the regenerate flow asks the worker to
    # write the produced artifact paths back onto the Application
    # row so the kanban / outcome views see the new draft without
    # the operator having to re-poll.
    application_id: str | None = None
    profile_id: str | None = None
    template_id: str | None = None
    document_types: list[str] = Field(default_factory=lambda: ["resume", "cover_letter"])
    # Phase 17.8 / 18.x: per-call overrides for the materials router.
    # Empty / None means "let resolve_material_choice fall back to the
    # user's Settings → Default material strategy".
    resume_strategy: str | None = None
    resume_template_id: str | None = None
    resume_source_document_id: str | None = None
    resume_patch_aggressiveness: str | None = None
    resume_patch_allow_reorder_sections: bool | None = None
    resume_patch_allow_add_remove_bullets: bool | None = None
    cover_letter_strategy: str | None = None
    cover_letter_template_id: str | None = None
    cover_letter_source_document_id: str | None = None
    cover_letter_patch_aggressiveness: str | None = None
    cover_letter_patch_allow_reorder_sections: bool | None = None
    cover_letter_patch_allow_add_remove_bullets: bool | None = None


class ApplicationPreparePayload(BaseModel):
    application_id: str


class ApplicationFillPayload(BaseModel):
    application_id: str


class ApplicationSubmitPayload(BaseModel):
    application_id: str


class OrchestrationPlanRunPayload(BaseModel):
    """Phase 17.1 plan_run task payload."""

    automation_plan_id: str | None = None
    automation_plan_name: str | None = None
    profile_id: str = "default"
    search_profile_id: str | None = None
    top_n: int = 10
    dry_run: bool = False
    auto_submit: bool = False
    skip_previously_applied: bool = True
    scrape_enabled: bool = True
    resume_strategy: str | None = None
    resume_template_id: str | None = None
    resume_source_document_id: str | None = None
    resume_patch_aggressiveness: str | None = None
    resume_patch_allow_reorder_sections: bool | None = None
    resume_patch_allow_add_remove_bullets: bool | None = None
    cover_letter_strategy: str | None = None
    cover_letter_template_id: str | None = None
    cover_letter_source_document_id: str | None = None
    cover_letter_patch_aggressiveness: str | None = None
    cover_letter_patch_allow_reorder_sections: bool | None = None
    cover_letter_patch_allow_add_remove_bullets: bool | None = None


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
    the bounded entry point for the worker.

    Phase 18.1: the saved-search fan-out and the per-source refresh
    plumbing live in :mod:`src.application.jobs.search_jobs` / Phase
    13.4 ``cached_search``. Manual ``search.refresh`` enqueues from
    the operator UI / CLI still expect the task to exist; the actual
    per-saved-search invocation lands here once the saved-search
    registry surfaces query-id → kwargs (the rest of the Phase 18
    surface drives the orchestrator, which already calls search_jobs
    directly).
    """
    args = _coerce(SearchRefreshPayload, payload)
    logger.info(
        "search.refresh query_id=%s source=%s max_pages=%s",
        args.query_id,
        args.source,
        args.max_pages,
    )
    return {
        "task": "search.refresh",
        "query_id": args.query_id,
        "source": args.source,
        "max_pages": args.max_pages,
        "status": "not_implemented",
        "detail": (
            "search.refresh body is registered for Phase 18 audit + "
            "Beat compatibility. The actual saved-search refresh "
            "currently runs through orchestration.plan_run / direct "
            "search_jobs CLI calls; lighting up a query_id->kwargs "
            "registry path is tracked by the Phase 18+ saved-search "
            "follow-up."
        ),
    }


@celery_app.task(name="search.daily_fanout", base=AutoApplyTask, bind=True)
def search_daily_fanout(self: AutoApplyTask) -> dict[str, Any]:
    """Beat-driven saved-search fan-out. Phase 17 explodes this into
    per-source ``search.refresh`` children once the saved-search
    registry surfaces source / kwargs lookup; until then the Beat
    tick is a no-op marker that lands an audit row + trace so the
    operator can confirm Beat is running."""
    logger.info("search.daily_fanout tick")
    return {
        "task": "search.daily_fanout",
        "status": "not_implemented",
        "detail": (
            "search.daily_fanout is currently a no-op tick. "
            "orchestration.plan_run owns the production search path; "
            "this slot exists so a future saved-search registry can "
            "hook in without changing the Beat schedule."
        ),
    }


# ---- Tasks: orchestration --------------------------------------------


@celery_app.task(name="notifications.morning_digest", base=AutoApplyTask, bind=True)
def notifications_morning_digest(self: AutoApplyTask) -> dict[str, Any]:
    """Phase 17.6: 08:00 morning digest tick."""
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


@celery_app.task(name="orchestration.plan_run", base=AutoApplyTask, bind=True)
def orchestration_plan_run(
    self: AutoApplyTask, **payload: Any
) -> dict[str, Any]:
    """Phase 17.1: top-level batch application automation task."""
    args = _coerce(OrchestrationPlanRunPayload, payload)
    import asyncio  # noqa: PLC0415

    from src.orchestration.plan_run import run_plan  # noqa: PLC0415
    from src.tasks.context import current_tenant_id  # noqa: PLC0415

    tenant_id = current_tenant_id() or "default"
    logger.info(
        "orchestration.plan_run starting tenant=%s profile=%s top_n=%d dry_run=%s",
        tenant_id,
        args.profile_id,
        args.top_n,
        args.dry_run,
    )
    report = asyncio.run(
        run_plan(
            tenant_id=tenant_id,
            profile_id=args.profile_id,
            search_profile_id=args.search_profile_id,
            top_n=args.top_n,
            dry_run=args.dry_run,
            auto_submit=args.auto_submit,
            skip_previously_applied=args.skip_previously_applied,
            scrape_enabled=args.scrape_enabled,
            resume_strategy=args.resume_strategy,
            resume_template_id=args.resume_template_id,
            resume_source_document_id=args.resume_source_document_id,
            resume_patch_aggressiveness=args.resume_patch_aggressiveness,
            resume_patch_allow_reorder_sections=args.resume_patch_allow_reorder_sections,
            resume_patch_allow_add_remove_bullets=args.resume_patch_allow_add_remove_bullets,
            cover_letter_strategy=args.cover_letter_strategy,
            cover_letter_template_id=args.cover_letter_template_id,
            cover_letter_source_document_id=args.cover_letter_source_document_id,
            cover_letter_patch_aggressiveness=args.cover_letter_patch_aggressiveness,
            cover_letter_patch_allow_reorder_sections=args.cover_letter_patch_allow_reorder_sections,
            cover_letter_patch_allow_add_remove_bullets=args.cover_letter_patch_allow_add_remove_bullets,
        )
    )
    try:
        from src.orchestration.digest import persist_plan_run_report  # noqa: PLC0415

        persist_plan_run_report(report)
    except Exception as exc:  # noqa: BLE001
        logger.warning("plan_run: report persistence failed: %s", exc)

    return report.to_dict()


# ---- Tasks: jobs -----------------------------------------------------


@celery_app.task(name="jobs.enrich", base=AutoApplyTask, bind=True)
def jobs_enrich(self: AutoApplyTask, **payload: Any) -> dict[str, Any]:
    """Re-feed the latest stored snapshot through :func:`enrich_posting`.

    Phase 18.1: the task previously logged + returned ``scheduled``.
    It now does a real call into ``src.jobs.enrich.enrich_posting``
    against the latest JobSnapshot for ``posting_id``. The function
    is idempotent (same content -> existing snapshot, content
    changed -> new snapshot + ``ContentChangedEvent``), which is
    what the Phase 19 ``posting.tag`` listener chain needs.

    The task body intentionally does NOT do a network scrape -- the
    LinkedIn / ATS scrape paths require Playwright and are owned by
    the orchestrator's search step. ``jobs.enrich`` is the
    refresh-and-snapshot primitive that runs after fresh content is
    available.
    """
    args = _coerce(JobEnrichPayload, payload)
    logger.info("jobs.enrich posting_id=%s", args.posting_id)

    from uuid import UUID  # noqa: PLC0415

    from src.core.database import get_session_factory  # noqa: PLC0415
    from src.core.models import JobPosting, JobSnapshot  # noqa: PLC0415
    from src.jobs.enrich import enrich_posting  # noqa: PLC0415
    from src.jobs.store import JobIndexStore  # noqa: PLC0415

    try:
        posting_uuid = UUID(args.posting_id)
    except ValueError:
        return {
            "task": "jobs.enrich",
            "posting_id": args.posting_id,
            "status": "invalid_posting_id",
        }

    factory = get_session_factory()
    with factory() as session, session.begin():
        posting = session.get(JobPosting, posting_uuid)
        if posting is None:
            return {
                "task": "jobs.enrich",
                "posting_id": args.posting_id,
                "status": "posting_not_found",
            }
        if posting.latest_snapshot_id is None:
            return {
                "task": "jobs.enrich",
                "posting_id": args.posting_id,
                "status": "no_snapshot",
                "detail": "Posting has no JobSnapshot yet; a search/scrape must run first.",
            }
        snapshot = session.get(JobSnapshot, posting.latest_snapshot_id)
        if snapshot is None:
            return {
                "task": "jobs.enrich",
                "posting_id": args.posting_id,
                "status": "snapshot_missing",
            }

        content = {
            "title": snapshot.title,
            "location": snapshot.location,
            "employment_type": snapshot.employment_type,
            "seniority": snapshot.seniority,
            "description": snapshot.description,
            "requirements": snapshot.requirements,
            "application_url": snapshot.application_url,
            "raw_data": snapshot.raw_data,
        }
        store = JobIndexStore(session)
        result = enrich_posting(
            store=store,
            source=posting.source,
            source_id=posting.source_id,
            company=posting.company,
            content=content,
        )

    return {
        "task": "jobs.enrich",
        "posting_id": str(posting_uuid),
        "snapshot_id": str(result.snapshot_id),
        "content_changed": result.content_changed,
        "state": result.state,
        "status": "ok",
    }


# ---- Tasks: materials ------------------------------------------------


@celery_app.task(name="materials.generate", base=AutoApplyTask, bind=True)
def materials_generate(self: AutoApplyTask, **payload: Any) -> dict[str, Any]:
    """Phase 18.1: full materials generation from a JobPosting.

    Loads the posting + its latest snapshot, builds the web-shaped
    job payload that :func:`generate_material_for_job` expects, then
    runs generation for each requested document_type. Artifact paths
    are written onto any matching :class:`ReviewQueueEntry` (so the
    review-queue kanban can render the produced files) and the
    structured artifact map is returned to the audit row.

    Phase 18.2 will surface the same map through
    ``GET /api/tasks/{task_id}`` via :class:`TaskRecord.result`; the
    18.1 body just returns the shape so that wire-up is a pure read.
    """
    args = _coerce(MaterialsGeneratePayload, payload)
    logger.info(
        "materials.generate job_id=%s document_types=%s",
        args.job_id,
        args.document_types,
    )

    import asyncio  # noqa: PLC0415
    from uuid import UUID  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from src.application.jobs import generate_material_for_job  # noqa: PLC0415
    from src.core.database import get_session_factory  # noqa: PLC0415
    from src.core.models import (  # noqa: PLC0415
        JobPosting,
        JobSnapshot,
        ReviewQueueEntry,
    )
    from src.tasks.context import current_tenant_id  # noqa: PLC0415

    tenant_id = current_tenant_id() or "default"

    # Phase 18.2: if the caller passed an inline ``job`` dict (the
    # JobsView "Generate" button hands us scraped data that isn't
    # persisted yet), use it verbatim. Otherwise fall through to the
    # JobPosting + JobSnapshot lookup.
    job_payload: dict[str, Any] = {}
    job_uuid = None
    if isinstance(args.job, dict) and args.job:
        job_payload = dict(args.job)
    else:
        try:
            job_uuid = UUID(args.job_id)
        except ValueError:
            return {
                "task": "materials.generate",
                "job_id": args.job_id,
                "document_types": args.document_types,
                "status": "invalid_job_id",
            }

        factory = get_session_factory()
        with factory() as session:
            posting = session.get(JobPosting, job_uuid)
            if posting is None:
                return {
                    "task": "materials.generate",
                    "job_id": args.job_id,
                    "document_types": args.document_types,
                    "status": "posting_not_found",
                }
            snapshot = (
                session.get(JobSnapshot, posting.latest_snapshot_id)
                if posting.latest_snapshot_id
                else None
            )
            job_payload = {
                "id": str(posting.id),
                "source": posting.source,
                "source_id": posting.source_id,
                "company": posting.company,
                "title": snapshot.title if snapshot else "",
                "location": snapshot.location if snapshot else None,
                "employment_type": snapshot.employment_type if snapshot else None,
                "seniority": snapshot.seniority if snapshot else None,
                "description": snapshot.description if snapshot else None,
                "requirements": snapshot.requirements if snapshot else None,
                "application_url": snapshot.application_url if snapshot else None,
                "ats_type": posting.source,
                "raw_data": snapshot.raw_data if snapshot else None,
            }

    if not job_payload.get("title"):
        return {
            "task": "materials.generate",
            "job_id": args.job_id,
            "document_types": args.document_types,
            "status": "no_snapshot",
            "detail": "Posting has no JobSnapshot; run jobs.enrich first.",
        }

    document_types = args.document_types or ["resume", "cover_letter"]
    artifacts: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []

    def _material_format(doc_type: str, template_id: str | None) -> str:
        """DOCX templates render docx; LaTeX templates render pdf. The
        material_type suffix must match the template's renderer or
        ``_ensure_template_supports_material`` rejects the request."""
        if template_id:
            try:
                from src.documents.templates import load_template_package  # noqa: PLC0415

                package = load_template_package(doc_type, template_id)
                if package.manifest.renderer == "latex":
                    return "pdf"
            except Exception:  # noqa: BLE001 - fall back to docx on any load issue
                pass
        return "docx"

    def _resolve_overrides(doc_type: str) -> tuple[str, dict[str, Any]] | None:
        if doc_type.startswith("resume"):
            fmt = _material_format("resume", args.resume_template_id)
            return f"resume_{fmt}", {
                "strategy": args.resume_strategy,
                "template_id": args.resume_template_id,
                "source_document_id": args.resume_source_document_id,
                "patch_aggressiveness": args.resume_patch_aggressiveness,
                "patch_allow_reorder_sections": args.resume_patch_allow_reorder_sections,
                "patch_allow_add_remove_bullets": args.resume_patch_allow_add_remove_bullets,
            }
        if doc_type.startswith("cover_letter"):
            fmt = _material_format("cover_letter", args.cover_letter_template_id)
            return f"cover_letter_{fmt}", {
                "strategy": args.cover_letter_strategy,
                "template_id": args.cover_letter_template_id,
                "source_document_id": args.cover_letter_source_document_id,
                "patch_aggressiveness": args.cover_letter_patch_aggressiveness,
                "patch_allow_reorder_sections": args.cover_letter_patch_allow_reorder_sections,
                "patch_allow_add_remove_bullets": args.cover_letter_patch_allow_add_remove_bullets,
            }
        return None

    async def _generate_one(doc_type: str) -> tuple[str, dict[str, Any] | None, dict | None]:
        resolved = _resolve_overrides(doc_type)
        if resolved is None:
            return doc_type, None, {
                "document_type": doc_type,
                "error": "unknown_document_type",
            }
        material_type, overrides = resolved
        try:
            result = await generate_material_for_job(
                job_payload=job_payload,
                material_type=material_type,
                use_llm=False,
                template_id=overrides["template_id"],
                profile_id=args.profile_id,
                strategy=overrides["strategy"],
                source_document_id=overrides["source_document_id"],
                patch_aggressiveness=overrides["patch_aggressiveness"],
                patch_allow_reorder_sections=overrides["patch_allow_reorder_sections"],
                patch_allow_add_remove_bullets=overrides["patch_allow_add_remove_bullets"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("materials.generate: %s failed", material_type)
            return doc_type, None, {"document_type": doc_type, "error": str(exc)}

        if not result.get("ok"):
            return doc_type, None, {
                "document_type": doc_type,
                "error": result.get("error") or "generation_failed",
                "error_code": result.get("error_code") or "generation_failed",
            }
        artifact = result.get("artifact") or {}
        return (
            doc_type,
            {
                "material_type": result.get("material_type"),
                "path": artifact.get("path"),
                "filename": artifact.get("filename"),
                "artifacts": result.get("artifacts"),
                "strategy": result.get("strategy"),
                "strategy_notes": result.get("strategy_notes"),
            },
            None,
        )

    # Phase 18.5: resume + cover-letter for a single job run
    # concurrently via asyncio.gather. The two generators share the
    # same job + profile data but produce independent artifacts, so
    # the only contention is on the global / per-provider LLM gate
    # in :mod:`src.utils.parallelism` (which is the whole point of
    # running them in parallel -- the gate caps provider load while
    # local concurrency cuts wall-clock).
    async def _generate_all() -> None:
        results = await asyncio.gather(
            *[_generate_one(dt) for dt in document_types]
        )
        for doc_type, artifact_payload, error in results:
            if error is not None:
                errors.append(error)
            if artifact_payload is not None:
                artifacts[doc_type] = artifact_payload

    asyncio.run(_generate_all())

    # Link the produced files onto any pending review-queue entry for
    # this posting so the kanban can preview them without re-running
    # the generator. We pick the most recent pending entry by
    # created_at; there should normally be only one because of the
    # partial-unique-pending index.
    resume_path = (
        artifacts.get("resume", {}).get("path")
        or artifacts.get("resume_docx", {}).get("path")
    )
    cover_letter_path = (
        artifacts.get("cover_letter", {}).get("path")
        or artifacts.get("cover_letter_docx", {}).get("path")
    )
    application_updates: dict[str, str] = {}
    if artifacts and job_uuid is not None:
        try:
            factory = get_session_factory()
            with factory() as session, session.begin():
                stmt = (
                    select(ReviewQueueEntry)
                    .where(ReviewQueueEntry.tenant_id == tenant_id)
                    .where(ReviewQueueEntry.job_id == job_uuid)
                    .where(ReviewQueueEntry.status == "pending")
                    .order_by(ReviewQueueEntry.created_at.desc())
                    .limit(1)
                )
                row = session.execute(stmt).scalar_one_or_none()
                if row is not None and resume_path:
                    row.materials_path = resume_path
        except Exception as exc:  # noqa: BLE001 -- never bounce a successful generation
            logger.warning(
                "materials.generate: linking artifacts to review entry failed: %s", exc
            )

    # Phase 18.2: when the regenerate flow named an application, write
    # the new artifact paths back onto that row so the kanban + outcome
    # views see the new draft. We keep this best-effort so a partial
    # generation (resume succeeded, cover-letter failed) still updates
    # what it can.
    if args.application_id and artifacts:
        try:
            from src.core.models import Application  # noqa: PLC0415

            app_uuid = UUID(args.application_id)
            factory = get_session_factory()
            with factory() as session, session.begin():
                app_row = session.get(Application, app_uuid)
                if app_row is not None:
                    if resume_path:
                        app_row.resume_version = resume_path
                        application_updates["resume_version"] = resume_path
                    if cover_letter_path:
                        app_row.cover_letter_version = cover_letter_path
                        application_updates["cover_letter_version"] = cover_letter_path
        except (ValueError, Exception) as exc:  # noqa: BLE001
            logger.warning(
                "materials.generate: application writeback failed: %s", exc
            )

    return {
        "task": "materials.generate",
        "job_id": args.job_id,
        "document_types": document_types,
        "artifacts": artifacts,
        "errors": errors,
        "application_id": args.application_id,
        "application_updates": application_updates,
        "resume_path": resume_path,
        "cover_letter_path": cover_letter_path,
        "status": "ok" if not errors else ("partial" if artifacts else "failed"),
    }


# ---- Tasks: application ----------------------------------------------


@celery_app.task(name="application.prepare", base=AutoApplyTask, bind=True)
def application_prepare(self: AutoApplyTask, **payload: Any) -> dict[str, Any]:
    """Phase 18.1: bind the latest materials onto the matching
    ReviewQueueEntry so the review kanban can render previews.

    The orchestrator already persists pending review entries; this
    task body is the seam between the materials task's artifacts and
    the kanban row. ``application_id`` is interpreted as either an
    ``applications.id`` or a ``job_postings.id`` (the orchestrator
    uses the latter today; tracking-app callers use the former).
    Missing rows are treated as a non-error ``not_found`` so a stale
    Beat enqueue doesn't bounce the queue.
    """
    args = _coerce(ApplicationPreparePayload, payload)
    logger.info("application.prepare application_id=%s", args.application_id)

    from uuid import UUID  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from src.core.database import get_session_factory  # noqa: PLC0415
    from src.core.models import Application, ReviewQueueEntry  # noqa: PLC0415
    from src.tasks.context import current_tenant_id  # noqa: PLC0415

    tenant_id = current_tenant_id() or "default"

    try:
        target_uuid = UUID(args.application_id)
    except ValueError:
        return {
            "task": "application.prepare",
            "application_id": args.application_id,
            "status": "invalid_id",
        }

    factory = get_session_factory()
    with factory() as session, session.begin():
        app = session.get(Application, target_uuid)
        entry_q = (
            select(ReviewQueueEntry)
            .where(ReviewQueueEntry.tenant_id == tenant_id)
            .where(ReviewQueueEntry.status == "pending")
        )
        if app is not None:
            entry_q = entry_q.where(ReviewQueueEntry.job_id == app.job_id)
        else:
            entry_q = entry_q.where(ReviewQueueEntry.job_id == target_uuid)
        entry = session.execute(
            entry_q.order_by(ReviewQueueEntry.created_at.desc()).limit(1)
        ).scalar_one_or_none()

        if app is not None and entry is not None:
            preferred = app.resume_version or app.cover_letter_version
            if preferred and not entry.materials_path:
                entry.materials_path = preferred

    return {
        "task": "application.prepare",
        "application_id": str(target_uuid),
        "review_entry_id": str(entry.id) if entry is not None else None,
        "application_status": app.status if app is not None else None,
        "materials_path": entry.materials_path if entry is not None else None,
        "status": "ok",
    }


@celery_app.task(name="application.fill", base=AutoApplyTask, bind=True)
def application_fill(self: AutoApplyTask, **payload: Any) -> dict[str, Any]:
    """Phase 18.1: the form-fill leg of the application pipeline.

    The actual browser automation lives in :mod:`src.execution` and is
    driven from the agent loop, not from this Celery task -- we keep
    the task registered (so the Phase 14 audit + Phase 17.5 gate
    plumbing both work) but explicitly return ``not_implemented`` so
    the wire isn't a fake success.
    """
    args = _coerce(ApplicationFillPayload, payload)
    logger.info("application.fill application_id=%s", args.application_id)
    return {
        "task": "application.fill",
        "application_id": args.application_id,
        "status": "not_implemented",
        "detail": (
            "Browser-driven form-fill is owned by src.execution.form_filler "
            "and the agent loop; the task is registered for audit + Beat "
            "wiring but the worker body does not execute Playwright."
        ),
    }


@celery_app.task(name="application.submit", base=AutoApplyTask, bind=True)
def application_submit(self: AutoApplyTask, **payload: Any) -> dict[str, Any]:
    """Phase 18.1: pre-submit gate + ``waiting_human`` parking.

    The pre-submit gate (Phase 17.5) re-runs
    ``should_refresh(..., "before_submit")``. If the JD is stale,
    the task opens a HITL :class:`GateRequest` and parks the task at
    ``waiting_human`` so the operator decides whether to refresh and
    proceed. If the gate passes we still return ``not_implemented``
    on the actual click-submit step (that's the browser path owned by
    :mod:`src.execution`); the audit row records the gate verdict and
    artifacts so the failure mode is "explicit hand-off", not
    "submitted silently".
    """
    args = _coerce(ApplicationSubmitPayload, payload)
    logger.info("application.submit application_id=%s", args.application_id)

    from uuid import UUID  # noqa: PLC0415

    from src.core.database import get_session_factory  # noqa: PLC0415
    from src.core.models import Application, JobPosting, TaskRecord  # noqa: PLC0415
    from src.jobs.freshness import should_refresh  # noqa: PLC0415
    from src.tasks import gate  # noqa: PLC0415
    from src.tasks.context import current_tenant_id  # noqa: PLC0415

    tenant_id = current_tenant_id() or "default"

    try:
        application_uuid = UUID(args.application_id)
    except ValueError:
        return {
            "task": "application.submit",
            "application_id": args.application_id,
            "status": "invalid_id",
        }

    factory = get_session_factory()
    with factory() as session, session.begin():
        app = session.get(Application, application_uuid)
        if app is None:
            return {
                "task": "application.submit",
                "application_id": str(application_uuid),
                "status": "application_not_found",
            }
        posting = session.get(JobPosting, app.job_id) if app.job_id else None
        verdict = (
            should_refresh(posting, context="before_submit")
            if posting is not None
            else None
        )

        gate_id: str | None = None
        if verdict is not None and verdict.should_refresh:
            # Park at waiting_human via the Postgres-backed gate. The
            # operator's approve/reject re-enqueues a follow-up task
            # under the same idempotency key (Phase 14.4 contract).
            celery_task_id = getattr(self.request, "id", None)
            task_row = None
            if celery_task_id:
                from src.tasks.audit import find_by_celery_id  # noqa: PLC0415

                task_row = find_by_celery_id(session, celery_task_id)
            gate_row = gate.open_request(
                session,
                kind="application.submit:freshness",
                summary=(
                    f"Pre-submit gate refused for application {application_uuid}: "
                    f"{verdict.reason}"
                ),
                payload={
                    "application_id": str(application_uuid),
                    "reason": verdict.reason,
                    "age_hours": verdict.age_hours,
                    "budget_hours": verdict.budget_hours,
                },
                task_id=task_row.id if isinstance(task_row, TaskRecord) else None,
                tenant_id=tenant_id,
            )
            gate_id = str(gate_row.id)

        return {
            "task": "application.submit",
            "application_id": str(application_uuid),
            "gate": {
                "should_refresh": bool(verdict.should_refresh) if verdict else None,
                "reason": verdict.reason if verdict else None,
                "age_hours": verdict.age_hours if verdict else None,
                "budget_hours": verdict.budget_hours if verdict else None,
            }
            if verdict is not None
            else None,
            "gate_request_id": gate_id,
            "status": "waiting_human" if gate_id else "not_implemented",
            "detail": (
                "Pre-submit gate parked the task at waiting_human; "
                "approval/rejection enqueues a follow-up."
            )
            if gate_id
            else (
                "Pre-submit gate cleared; click-submit is owned by "
                "src.execution and not invoked from this worker body."
            ),
        }


# ---- Tasks: maintenance ----------------------------------------------


@celery_app.task(name="maintenance.status_sync", base=AutoApplyTask, bind=True)
def status_sync(self: AutoApplyTask, **payload: Any) -> dict[str, Any]:
    """Phase 18.1: outcome-sync is not yet wired. We accept the
    payload (so audit-rows stay consistent) and return
    ``not_implemented`` instead of pretending. The Beat schedule no
    longer references this task; the entry survives so manual CLI
    invocations don't get a registration error."""
    args = _coerce(StatusSyncPayload, payload)
    logger.info("status_sync application_id=%s", args.application_id)
    return {
        "task": "maintenance.status_sync",
        "application_id": args.application_id,
        "status": "not_implemented",
        "detail": (
            "Application-outcome sync should start with supported ATS / "
            "application-portal polling, then add HR-reply / rejection-email "
            "ingestion. Task body is intentionally a no-op so manual "
            "invocations audit honestly."
        ),
    }


@celery_app.task(name="maintenance.jd_health_check", base=AutoApplyTask, bind=True)
def jd_health_check(self: AutoApplyTask) -> dict[str, Any]:
    """Phase 18.1: drive the Phase 13.3 freshness state machine's
    time decay.

    Walks every non-terminal ``JobPosting``, applies
    :func:`project_by_time`, and writes the projected state back if
    it differs. The query is bounded -- ``new`` / ``expired`` /
    ``archived`` don't decay further, and ``last_checked_at IS NULL``
    rows are skipped.
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from src.core.database import get_session_factory  # noqa: PLC0415
    from src.core.models import JobPosting  # noqa: PLC0415
    from src.jobs.state import project_by_time  # noqa: PLC0415
    from src.tasks.context import current_tenant_id  # noqa: PLC0415

    tenant_id = current_tenant_id() or "default"
    now = datetime.now(UTC)
    transitions: dict[str, int] = {}
    examined = 0

    factory = get_session_factory()
    with factory() as session, session.begin():
        stmt = (
            select(JobPosting)
            .where(JobPosting.tenant_id == tenant_id)
            .where(JobPosting.state.in_(("active", "stale", "unknown")))
        )
        for posting in session.execute(stmt).scalars():
            examined += 1
            verdict = project_by_time(
                posting.state,
                last_checked_at=posting.last_checked_at,
                now=now,
            )
            if verdict.state != posting.state:
                transitions[f"{posting.state}->{verdict.state}"] = (
                    transitions.get(f"{posting.state}->{verdict.state}", 0) + 1
                )
                posting.state = verdict.state

    return {
        "task": "maintenance.jd_health_check",
        "examined": examined,
        "transitions": transitions,
        "status": "ok",
    }


@celery_app.task(name="maintenance.linkedin_cookie_refresh", base=AutoApplyTask, bind=True)
def linkedin_cookie_refresh(self: AutoApplyTask) -> dict[str, Any]:
    """Phase 18.1: probe the LinkedIn session and record pass/fail.

    The probe is forced (bypasses the in-process cache) so the daily
    Beat tick gives the operator an up-to-date signal. We don't try
    to re-login here -- that requires user interaction. The session
    object's own cache is updated by the probe so subsequent web-UI
    mounts read the same fresh result.
    """
    import asyncio  # noqa: PLC0415

    from src.intake.linkedin import get_linkedin_session_status  # noqa: PLC0415

    try:
        result = asyncio.run(get_linkedin_session_status(force_refresh=True))
    except Exception as exc:  # noqa: BLE001
        logger.exception("linkedin_cookie_refresh probe failed")
        return {
            "task": "maintenance.linkedin_cookie_refresh",
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }

    return {
        "task": "maintenance.linkedin_cookie_refresh",
        "authenticated": result.get("authenticated"),
        "has_session_data": result.get("has_session_data"),
        "message": result.get("message"),
        "checked_at": result.get("checked_at"),
        "status": "ok" if result.get("ok") else "error",
    }


@celery_app.task(name="maintenance.cache_eviction", base=AutoApplyTask, bind=True)
def cache_eviction(self: AutoApplyTask) -> dict[str, Any]:
    """Phase 18.4: drive the artifact cleanup + quarantine pipeline.

    The Beat schedule fires this hourly on the :30 minute. Each tick:

    1. Walks ``data/output`` and moves eligible orphan / tmp / failed
       artifacts to ``data/quarantine/<run_id>/`` (writes a
       :class:`CleanupRun` + per-file :class:`CleanupItem` audit).
    2. Then purges any quarantine entries older than
       ``cleanup.quarantine_days`` so the recovered-bytes accounting
       stays accurate.

    The name (``cache_eviction``) is preserved from Phase 14 for Beat
    schedule continuity; the body is now the real cleanup, not a stub.
    DB / FS errors are caught + recorded into the task return value so
    the audit row can still surface them without bouncing the worker.
    """
    from src.core.database import get_session_factory  # noqa: PLC0415
    from src.maintenance.artifacts import (  # noqa: PLC0415
        clean,
        purge_quarantine,
    )
    from src.tasks.context import current_tenant_id  # noqa: PLC0415

    tenant_id = current_tenant_id() or "default"
    factory = get_session_factory()

    summaries: dict[str, dict[str, Any]] = {}
    try:
        with factory() as session, session.begin():
            clean_report = clean(
                session, tenant_id=tenant_id, trigger="scheduled"
            )
            summaries["clean"] = clean_report.to_summary()
        with factory() as session, session.begin():
            purge_report = purge_quarantine(
                session, tenant_id=tenant_id, trigger="scheduled"
            )
            summaries["purge_quarantine"] = purge_report.to_summary()
    except Exception as exc:  # noqa: BLE001 -- never crash the worker
        logger.exception("cache_eviction: cleanup pipeline failed")
        summaries["error"] = f"{type(exc).__name__}: {exc}"

    return {
        "task": "maintenance.cache_eviction",
        "status": "ok" if "error" not in summaries else "error",
        "summaries": summaries,
    }


@celery_app.task(name="maintenance.gate_expire_sweep", base=AutoApplyTask, bind=True)
def gate_expire_sweep(self: AutoApplyTask) -> dict[str, Any]:
    """Phase 18.1: flip ``gate_queue`` rows past their TTL to
    ``expired``.

    Walks pending rows whose ``ttl_seconds`` is set and whose
    ``requested_at + ttl_seconds`` is in the past. Each transition
    routes through :func:`src.tasks.gate.expire` so the linked
    ``TaskRecord.last_error`` stays accurate.
    """
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from src.core.database import get_session_factory  # noqa: PLC0415
    from src.core.models import GateRequest  # noqa: PLC0415
    from src.tasks import gate  # noqa: PLC0415
    from src.tasks.context import current_tenant_id  # noqa: PLC0415

    tenant_id = current_tenant_id() or "default"
    now = datetime.now(UTC)
    expired_ids: list[str] = []

    factory = get_session_factory()
    with factory() as session, session.begin():
        stmt = (
            select(GateRequest)
            .where(GateRequest.tenant_id == tenant_id)
            .where(GateRequest.status == gate.STATUS_PENDING)
            .where(GateRequest.ttl_seconds.is_not(None))
        )
        for row in session.execute(stmt).scalars():
            deadline = row.requested_at + timedelta(seconds=int(row.ttl_seconds or 0))
            if deadline <= now:
                gate.expire(session, row.id)
                expired_ids.append(str(row.id))

    return {
        "task": "maintenance.gate_expire_sweep",
        "expired": len(expired_ids),
        "expired_ids": expired_ids,
        "status": "ok",
    }


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
    "orchestration.plan_run",
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
    "OrchestrationPlanRunPayload",
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
    "orchestration_plan_run",
    "search_daily_fanout",
    "search_refresh",
    "status_sync",
]
