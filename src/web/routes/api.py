"""JSON API routes for the Vue web client."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.application.documents import (
    delete_document,
    list_documents_data,
    promote_artifact_to_library,
    resolve_document_for_download,
    update_document,
    upload_document,
)
from src.application.jobs import (
    apply_to_url,
)
from src.application.jobs import (
    clear_linkedin_session as clear_linkedin_session_usecase,
)
from src.application.jobs import (
    connect_linkedin_session as connect_linkedin_session_usecase,
)
from src.application.jobs import (
    create_material_template as create_material_template_usecase,
)
from src.application.jobs import (
    delete_material_template as delete_material_template_usecase,
)
from src.application.jobs import (
    generate_material_for_job as generate_material_for_job_usecase,
)
from src.application.jobs import (
    get_linkedin_session_status as get_linkedin_session_status_usecase,
)
from src.application.jobs import (
    get_material_template as get_material_template_usecase,
)
from src.application.jobs import (
    list_material_templates as list_material_templates_usecase,
)
from src.application.jobs import (
    resolve_manual_apply_url as resolve_manual_apply_url_usecase,
)
from src.application.jobs import (
    search_jobs as search_jobs_usecase,
)
from src.application.jobs import (
    update_material_template as update_material_template_usecase,
)
from src.application.jobs import (
    update_material_template_styles as update_material_template_styles_usecase,
)
from src.application.jobs import (
    upload_material_template as upload_material_template_usecase,
)
from src.application.jobs import (
    validate_material_template as validate_material_template_usecase,
)
from src.application.matching import explain_job as explain_job_usecase
from src.application.material_defaults import (
    SUPPORTED_DOCUMENT_TYPES,
    SUPPORTED_STRATEGIES,
    load_material_defaults_data,
    save_material_defaults,
)
from src.application.profile import (
    activate_profile_data,
    create_empty_profile,
    delete_profile_data,
    import_resume_file,
    import_resume_from_library,
    load_profile_data,
    rename_profile_data,
    save_profile_data,
)
from src.application.providers import (
    connect_api_key_provider,
    disconnect_provider,
    list_provider_models,
    list_providers,
    test_provider_connection,
    update_provider_model,
    use_provider_as_primary,
)
from src.application.regenerate_materials import regenerate_application_material
from src.application.search_profiles import (
    delete_search_profile_data,
    load_search_profiles_data,
    save_search_profile_data,
)
from src.application.settings import (
    clear_search_cache_data,
    load_llm_settings_data,
    update_llm_settings_data,
)
from src.application.tracking import (
    discard_paused_application,
    load_applications_data,
    load_dashboard_data,
    soft_delete_application,
    submit_paused_application,
    update_application_outcome,
)
from src.core.config import PROJECT_ROOT

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["api"])
MAX_TEMPLATE_UPLOAD_BYTES = 10 * 1024 * 1024


_SYNC_DEPRECATION_LOGGED: set[str] = set()


def _warn_sync_materials_deprecated(route: str) -> None:
    """Phase 18.6: emit a one-time deprecation log per route when
    ``AUTOAPPLY_SYNC_MATERIALS=1`` brings back the synchronous
    materials path. The flag is a short soak / debug escape hatch;
    the warning makes it obvious in logs so the operator doesn't
    forget to flip it off."""
    import logging

    if route in _SYNC_DEPRECATION_LOGGED:
        return
    _SYNC_DEPRECATION_LOGGED.add(route)
    logging.getLogger("autoapply.web.routes.api").warning(
        "AUTOAPPLY_SYNC_MATERIALS=1 is set: %s is using the legacy "
        "synchronous path. This escape hatch is dev-only and slated "
        "for removal -- unset the env var to take the async (task_id) "
        "path the UI ships with.",
        route,
    )


class JobSearchPayload(BaseModel):
    source: str = "ats"
    keyword: str = ""
    keywords: list[str] = Field(default_factory=list)
    location: str = ""
    profile: str = ""
    time_filter: str = "all"
    ats: str = ""
    company: str = ""
    experience_levels: list[str] = Field(default_factory=list)
    employment_types: list[str] = Field(default_factory=list)
    location_types: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    pay_operator: str = ""
    pay_amount: int | None = None
    experience_operator: str = ""
    experience_years: int | None = None
    education_levels: list[str] = Field(default_factory=list)
    max_pages: int = 20
    force_refresh: bool = False


class JobApplyPayload(BaseModel):
    url: str


class JobMaterialPayload(BaseModel):
    job: dict
    material_type: str
    use_llm: bool = False
    template_id: str | None = None
    profile_id: str | None = None
    application_id: str | None = None
    # Phase 17.8: caller may override the user's saved defaults.
    strategy: str | None = None  # "regenerate" | "patch_existing" | "use_library"
    source_document_id: str | None = None  # UserDocument id
    # Phase 18.x: per-call overrides for the three patch knobs (only
    # consulted when strategy is ``patch_existing``).
    patch_aggressiveness: str | None = None
    patch_allow_reorder_sections: bool | None = None
    patch_allow_add_remove_bullets: bool | None = None


class MaterialsApplicationPayload(BaseModel):
    job: dict
    profile_id: str | None = None


class TemplateCreatePayload(BaseModel):
    document_type: str
    template_name: str = ""
    description: str = ""


class TemplateUpdatePayload(BaseModel):
    content: str
    template_name: str = ""
    description: str = ""
    target_pages: int | None = None
    filename_pattern: str | None = None
    filename_custom_label: str | None = None
    emphasis_font: str | None = None


class TemplateStyleOverridePayload(BaseModel):
    font: str | None = None
    size: int | None = None
    bold: bool | None = None
    italic: bool | None = None
    line_spacing: float | None = None
    space_before_pt: float | None = None
    space_after_pt: float | None = None


class TemplateStylesPayload(BaseModel):
    overrides: dict[str, TemplateStyleOverridePayload] = Field(default_factory=dict)
    template_name: str = ""
    description: str = ""
    target_pages: int | None = None
    filename_pattern: str | None = None
    filename_custom_label: str | None = None
    emphasis_font: str | None = None


class SearchProfilePayload(BaseModel):
    source: str = "ats"
    keywords: list[str] = Field(default_factory=list)
    time_filter: str = "all"
    ats: str = ""
    company: str = ""
    locations: list[str] = Field(default_factory=list)
    experience_levels: list[str] = Field(default_factory=list)
    employment_types: list[str] = Field(default_factory=list)
    location_types: list[str] = Field(default_factory=list)
    education_levels: list[str] = Field(default_factory=list)
    pay_operator: str = ""
    pay_amount: int | None = None
    experience_operator: str = ""
    experience_years: int | None = None
    max_pages: int = 20


class OutcomePayload(BaseModel):
    outcome: str


class DiscardPayload(BaseModel):
    reason: str | None = None


class DocumentUpdatePayload(BaseModel):
    display_name: str | None = None
    notes: str | None = None


class DocumentPromotePayload(BaseModel):
    artifact_path: str
    document_type: str
    display_name: str
    application_id: str | None = None
    job_snapshot_id: str | None = None
    notes: str | None = None


class ProfileFromLibraryPayload(BaseModel):
    document_id: str
    profile_id: str | None = None
    overwrite: bool = False
    set_active: bool = True


class MaterialDefaultEntryPayload(BaseModel):
    strategy: str = "regenerate"
    default_template_id: str | None = ""
    default_document_id: str | None = ""


class MaterialDefaultsPayload(BaseModel):
    resume: MaterialDefaultEntryPayload | None = None
    cover_letter: MaterialDefaultEntryPayload | None = None


class RegenerateMaterialPayload(BaseModel):
    material_type: str
    strategy: str | None = None
    template_id: str | None = None
    source_document_id: str | None = None
    # Phase 18.x: per-call overrides for the three patch knobs. When
    # ``None`` the saved material default for this document_type wins.
    patch_aggressiveness: str | None = None
    patch_allow_reorder_sections: bool | None = None
    patch_allow_add_remove_bullets: bool | None = None


class LLMSettingsPayload(BaseModel):
    primary_provider: str
    fallback_provider: str | None = None
    allow_fallback: bool = False
    cache_enabled: bool = True
    cache_ttl_hours: int = 24
    # Phase 17.9.9: optional small-tier knobs. Both are nullable to
    # represent "disabled". small_tier_action distinguishes "the client
    # is not touching these" (preserve, default) from "set" and "clear",
    # mirroring the same three-state contract on the writer below.
    small_provider: str | None = None
    small_model: str | None = None
    small_tier_action: str = "preserve"


class ProviderSetKeyPayload(BaseModel):
    api_key: str
    model: str | None = None
    base_url: str | None = None


class ProviderUsePayload(BaseModel):
    fallback_provider: str | None = None


class ProviderSetModelPayload(BaseModel):
    """Phase 17.9.11: swap the model on an already-connected provider
    without re-entering the API key."""

    model: str | None = None


class ProfileSavePayload(BaseModel):
    profile_id: str
    profile: dict
    set_active: bool = False


class ProfileCreatePayload(BaseModel):
    profile_id: str
    set_active: bool = True


class ProfileRenamePayload(BaseModel):
    new_profile_id: str


class MatchingExplainPayload(BaseModel):
    """Payload for ``POST /api/matching/explain``.

    The frontend sends the same ``serialize_job()`` shape it already has
    in memory; the route re-runs scoring server-side against the active
    profile and returns the structured ``ScoreBreakdown`` for the
    "Why was this filtered?" popover (Phase 16.3).
    """

    job: dict


@router.get("/digest")
async def get_morning_digest(window_hours: int = 24) -> dict:
    """Phase 17.6 morning digest payload for the dashboard banner.

    Aggregates the last ``window_hours`` of plan-run reports +
    the current review queue snapshot. The route re-computes on every
    call (the input is tiny: a directory scan + one ``count(*)``
    grouped by status), so callers don't need to worry about staleness
    after an approve/reject action.
    """
    from src.core.database import get_session_factory
    from src.orchestration.digest import compute_digest

    factory = get_session_factory()
    with factory() as session:
        # Tenant resolution mirrors the review routes' helper.
        try:
            from src.tasks.context import current_tenant_id

            tenant_id = current_tenant_id() or "default"
        except Exception:
            tenant_id = "default"
        payload = compute_digest(
            session, tenant_id=tenant_id, window_hours=max(1, min(window_hours, 168))
        )
    return {"ok": True, "digest": payload.to_dict()}


@router.post("/matching/explain")
async def matching_explain(payload: MatchingExplainPayload) -> dict:
    """Phase 16.3 explainability route.

    Returns ``{ok, score_breakdown, warnings}``. The route does NOT
    fetch from DB -- the frontend already has the job dict from a
    prior search; we re-score on demand so the popover stays accurate
    even when the user re-runs after a profile edit.
    """
    return explain_job_usecase(payload.job)


@router.get("/dashboard")
async def dashboard_data() -> dict:
    return load_dashboard_data()


@router.post("/jobs/search")
async def search_jobs(payload: JobSearchPayload) -> dict:
    return await search_jobs_usecase(
        profile=payload.profile or None,
        source=payload.source,
        ats=payload.ats or None,
        company=payload.company or None,
        keyword=payload.keyword or None,
        keywords=payload.keywords,
        search_location=payload.location or None,
        time_filter=payload.time_filter,
        experience_levels=payload.experience_levels,
        employment_types=payload.employment_types,
        location_types=payload.location_types,
        locations=payload.locations,
        pay_operator=payload.pay_operator or None,
        pay_amount=payload.pay_amount,
        experience_operator=payload.experience_operator or None,
        experience_years=payload.experience_years,
        education_levels=payload.education_levels,
        max_pages=payload.max_pages,
        force_refresh=payload.force_refresh,
        use_job_index=True,
        headless=True,
        score=True,
        allow_public_linkedin_fallback=False,
        include_views=True,
    )


@router.get("/jobs/linkedin/session")
async def linkedin_session_status(refresh: bool = False) -> dict:
    """Return the LinkedIn session status.

    By default served from a short-lived cache so opening the web UI doesn't
    spin up a headless Chromium every time. Pass ``?refresh=true`` to force a
    real probe (e.g. when the user explicitly clicks "Check status" or right
    before an authenticated search kicks off).
    """
    return await get_linkedin_session_status_usecase(force_refresh=refresh)


@router.post("/jobs/linkedin/session/connect")
async def connect_linkedin_session() -> dict:
    return await connect_linkedin_session_usecase()


@router.delete("/jobs/linkedin/session")
async def clear_linkedin_session() -> dict:
    return clear_linkedin_session_usecase()


@router.post("/jobs/manual-apply-target")
async def manual_apply_target(payload: JobApplyPayload) -> dict:
    result = await resolve_manual_apply_url_usecase(payload.url)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/jobs/generate-material")
async def generate_job_material(payload: JobMaterialPayload) -> dict:
    """Phase 18.2: defaults to enqueue + return ``task_id``.

    The browser tab can close mid-generation without losing work
    (the worker keeps running) and ``GET /api/tasks/{task_id}``
    streams progress + artifacts back via :class:`TaskRecord.result`.

    The legacy synchronous path is preserved behind the
    ``AUTOAPPLY_SYNC_MATERIALS`` env var for soak / local debugging;
    Phase 18.6 retires that escape hatch.
    """
    import os

    if os.environ.get("AUTOAPPLY_SYNC_MATERIALS") == "1":
        _warn_sync_materials_deprecated("generate-material")
        result = await generate_material_for_job_usecase(
            job_payload=payload.job,
            material_type=payload.material_type,
            use_llm=payload.use_llm,
            template_id=payload.template_id,
            profile_id=payload.profile_id,
            strategy=payload.strategy,
            source_document_id=payload.source_document_id,
            patch_aggressiveness=payload.patch_aggressiveness,
            patch_allow_reorder_sections=payload.patch_allow_reorder_sections,
            patch_allow_add_remove_bullets=payload.patch_allow_add_remove_bullets,
        )
        if result["ok"]:
            return result

        status_code = 400
        if result["error_code"] == "material_generation_failed":
            status_code = 500
        raise HTTPException(status_code=status_code, detail=result["error"])

    return _enqueue_materials_generate_from_web(payload)


@router.post("/jobs/materials-application")
async def create_materials_application(payload: MaterialsApplicationPayload) -> dict:
    """Create a draft Application row for the Materials workspace.

    The generation route is intentionally still a task enqueue endpoint.
    ``/materials`` uses this lightweight endpoint first so resume and
    cover-letter generation can share one durable Application row and
    the worker can write produced artifacts back onto it.
    """
    try:
        return _create_materials_application_from_web(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("materials application create failed")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create application: {type(exc).__name__}: {exc}",
        ) from exc


def _create_materials_application_from_web(payload: MaterialsApplicationPayload) -> dict:
    from datetime import UTC, datetime

    from sqlalchemy import select

    from src.application.jobs import (  # noqa: PLC0415
        _get_or_create_job_record,
        _raw_job_from_web_payload,
    )
    from src.core.config import load_config
    from src.core.database import get_session_factory
    from src.core.models import Application
    from src.core.state_machine import AppStatus
    from src.tasks.context import current_tenant_id

    raw_job = _raw_job_from_web_payload(payload.job, use_llm=False)
    tenant_id = current_tenant_id() or "default"
    job_snapshot_id = _extract_job_snapshot_id(payload.job)
    now = datetime.now(UTC)

    factory = get_session_factory(load_config())
    with factory() as session, session.begin():
        db_job = _get_or_create_job_record(session, raw_job)
        existing = (
            session.execute(
                select(Application)
                .where(Application.tenant_id == tenant_id)
                .where(Application.job_id == db_job.id)
                .where(Application.deleted_at.is_(None))
                .where(
                    Application.status.in_(
                        [
                            AppStatus.DISCOVERED,
                            AppStatus.QUALIFIED,
                            AppStatus.MATERIALS_READY,
                        ]
                    )
                )
                .order_by(Application.updated_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if existing is not None:
            if job_snapshot_id and not existing.job_snapshot_id:
                existing.job_snapshot_id = job_snapshot_id
            app = existing
            status = "existing"
        else:
            app = Application(
                tenant_id=tenant_id,
                job_id=db_job.id,
                job_snapshot_id=job_snapshot_id,
                status=AppStatus.DISCOVERED,
                state_history=[
                    {
                        "timestamp": now.isoformat(),
                        "event": "MATERIALS_DRAFT_CREATED",
                        "profile_id": payload.profile_id,
                        "source": raw_job.source,
                    }
                ],
            )
            session.add(app)
            session.flush()
            status = "created"

        return {
            "ok": True,
            "status": status,
            "application_id": str(app.id),
            "job_id": str(db_job.id),
            "job": {
                "id": str(db_job.id),
                "company": db_job.company,
                "title": db_job.title,
                "location": db_job.location,
                "application_url": db_job.application_url,
                "ats_type": db_job.ats_type,
            },
        }


def _extract_job_snapshot_id(job_payload: dict) -> UUID | None:
    raw_data = job_payload.get("raw_data") if isinstance(job_payload, dict) else None
    candidates = []
    if isinstance(job_payload, dict):
        candidates.append(job_payload.get("job_snapshot_id"))
    if isinstance(raw_data, dict):
        candidates.append(raw_data.get("job_snapshot_id"))
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return UUID(str(candidate))
        except (TypeError, ValueError):
            continue
    return None


def _enqueue_materials_generate_from_web(payload: JobMaterialPayload) -> dict:
    """Bridge the JobsView payload onto the Phase 14 enqueue contract.

    The ``materials.generate`` task accepts either a stored
    ``job_id`` (UUID) or an inline ``job`` dict; the JobsView path
    has scraped search-result data that hasn't been persisted yet,
    so we pass the dict through and let the task body skip the
    JobPosting lookup. The audit row gets a deterministic identifier
    from ``job.source_id`` (or a fresh UUID) so the operator can
    still find the row in ``/tasks``.
    """
    from uuid import uuid4

    from src.application.material_defaults import resolve_material_choice
    from src.tasks.app import celery_app
    from src.tasks.base import AutoApplyTask as _AutoApplyTask
    from src.tasks.base import EnqueueSpec
    from src.tasks.context import current_tenant_id

    # Resolve overrides so the task body doesn't have to re-derive
    # them. ``resolve_material_choice`` accepts ``None`` for missing
    # overrides and falls back to the saved Settings default.
    document_type = (
        "cover_letter"
        if payload.material_type.startswith("cover_letter")
        else "resume"
    )
    try:
        choice = resolve_material_choice(
            document_type=document_type,
            override_strategy=payload.strategy,
            override_template_id=payload.template_id,
            override_document_id=payload.source_document_id,
            override_patch_aggressiveness=payload.patch_aggressiveness,
            override_patch_allow_reorder_sections=payload.patch_allow_reorder_sections,
            override_patch_allow_add_remove_bullets=payload.patch_allow_add_remove_bullets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = str(payload.job.get("id") or payload.job.get("source_id") or uuid4())

    task_payload: dict[str, Any] = {
        "job_id": job_id,
        "job": payload.job,
        "application_id": payload.application_id,
        "profile_id": payload.profile_id,
        "document_types": [
            "cover_letter" if document_type == "cover_letter" else "resume"
        ],
    }
    if document_type == "resume":
        task_payload["resume_strategy"] = choice["strategy"]
        task_payload["resume_template_id"] = choice["template_id"] or payload.template_id
        task_payload["resume_source_document_id"] = choice["document_id"]
        task_payload["resume_patch_aggressiveness"] = choice["patch_aggressiveness"]
        task_payload["resume_patch_allow_reorder_sections"] = choice[
            "patch_allow_reorder_sections"
        ]
        task_payload["resume_patch_allow_add_remove_bullets"] = choice[
            "patch_allow_add_remove_bullets"
        ]
    else:
        task_payload["cover_letter_strategy"] = choice["strategy"]
        task_payload["cover_letter_template_id"] = (
            choice["template_id"] or payload.template_id
        )
        task_payload["cover_letter_source_document_id"] = choice["document_id"]
        task_payload["cover_letter_patch_aggressiveness"] = choice["patch_aggressiveness"]
        task_payload["cover_letter_patch_allow_reorder_sections"] = choice[
            "patch_allow_reorder_sections"
        ]
        task_payload["cover_letter_patch_allow_add_remove_bullets"] = choice[
            "patch_allow_add_remove_bullets"
        ]

    # Codex review fix: same idempotency-collision concern as the
    # regenerate path -- a user clicking "Generate" twice in a row
    # with different overrides would otherwise short-circuit to the
    # first run's artifact. Hash the effective choices into the key.
    import hashlib
    import json

    # 2026-05-21 fix (v3): see the regenerate path for full rationale.
    # Same template-manifest fingerprint + 5s time-bucket strategy so
    # an explicit Generate click always fires when the user means it.
    import time

    from src.documents.templates import (  # noqa: PLC0415
        DEFAULT_TEMPLATE_IDS,
        load_template_package,
    )

    effective_template_id = (
        task_payload.get("resume_template_id")
        if document_type == "resume"
        else task_payload.get("cover_letter_template_id")
    ) or DEFAULT_TEMPLATE_IDS.get(document_type)
    template_manifest_fingerprint: str | None = None
    if effective_template_id:
        try:
            template_package = load_template_package(
                document_type, effective_template_id
            )
            template_manifest_fingerprint = hashlib.sha256(
                template_package.manifest.model_dump_json(
                    exclude={"name", "description"}
                ).encode("utf-8")
            ).hexdigest()[:16]
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "materials.generate: failed to hash template manifest for %s/%s: %s",
                document_type,
                effective_template_id,
                exc,
            )

    request_bucket = int(time.time()) // 5

    choice_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "version": 3,
                "strategy": choice.get("strategy"),
                "template_id": payload.template_id,
                "template_manifest_fingerprint": template_manifest_fingerprint,
                "source_document_id": choice.get("document_id"),
                "patch_aggressiveness": choice.get("patch_aggressiveness"),
                "patch_allow_reorder_sections": choice.get(
                    "patch_allow_reorder_sections"
                ),
                "patch_allow_add_remove_bullets": choice.get(
                    "patch_allow_add_remove_bullets"
                ),
                "request_bucket_5s": request_bucket,
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()[:16]

    tenant = current_tenant_id() or "default"
    spec = EnqueueSpec(
        kind="materials.generate",
        queue="materials",
        payload=task_payload,
        tenant_id=tenant,
        idempotency_key=(
            f"materials.generate:{job_id}:{payload.material_type}:"
            f"{choice_fingerprint}"
        ),
    )

    from src.core.config import load_config
    from src.core.database import get_session_factory

    factory = get_session_factory(load_config())
    with factory() as session:
        task_id = _AutoApplyTask.enqueue(
            celery_task=celery_app.tasks["materials.generate"],
            session=session,
            spec=spec,
        )
    return {
        "ok": True,
        "status": "queued",
        "task_id": str(task_id),
        "material_type": payload.material_type,
        "application_id": payload.application_id,
        "poll_url": f"/api/tasks/{task_id}",
    }


@router.get("/templates")
async def material_templates() -> dict:
    return list_material_templates_usecase()


@router.post("/templates/upload")
async def upload_material_template(
    template: UploadFile = File(...),
    document_type: str = Form(...),
    template_name: str = Form(""),
) -> dict:
    content = await _read_upload_limited(template)
    result = upload_material_template_usecase(
        document_type=document_type,
        filename=template.filename or "",
        content=content,
        template_name=template_name or None,
    )
    if result["ok"]:
        return result
    status_code = 400 if result["error_code"] != "template_upload_failed" else 500
    raise HTTPException(status_code=status_code, detail=result["error"])


@router.post("/templates/latex")
async def create_latex_template(payload: TemplateCreatePayload) -> dict:
    result = create_material_template_usecase(
        document_type=payload.document_type,
        template_name=payload.template_name or None,
        description=payload.description or None,
    )
    if result["ok"]:
        return result
    status_code = 400 if result["error_code"] != "template_create_failed" else 500
    raise HTTPException(status_code=status_code, detail=result["error"])


@router.get("/templates/{document_type}/{template_id}")
async def material_template_detail(document_type: str, template_id: str) -> dict:
    result = get_material_template_usecase(document_type=document_type, template_id=template_id)
    if result["ok"]:
        return result
    status_code = 400 if result["error_code"] != "template_load_failed" else 500
    raise HTTPException(status_code=status_code, detail=result["error"])


@router.put("/templates/{document_type}/{template_id}")
async def update_material_template(
    document_type: str,
    template_id: str,
    payload: TemplateUpdatePayload,
) -> dict:
    if len(payload.content.encode("utf-8")) > MAX_TEMPLATE_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Template content is too large.")
    result = update_material_template_usecase(
        document_type=document_type,
        template_id=template_id,
        content=payload.content,
        template_name=payload.template_name or None,
        description=payload.description or None,
        target_pages=payload.target_pages,
        filename_pattern=payload.filename_pattern,
        filename_custom_label=payload.filename_custom_label,
        emphasis_font=payload.emphasis_font,
    )
    if result["ok"]:
        return result
    status_code = 400 if result["error_code"] != "template_update_failed" else 500
    raise HTTPException(status_code=status_code, detail=result["error"])


@router.put("/templates/{document_type}/{template_id}/styles")
async def update_material_template_styles(
    document_type: str,
    template_id: str,
    payload: TemplateStylesPayload,
) -> dict:
    overrides = {
        key: value.model_dump(exclude_none=True)
        for key, value in payload.overrides.items()
    }
    result = update_material_template_styles_usecase(
        document_type=document_type,
        template_id=template_id,
        overrides=overrides,
        template_name=payload.template_name or None,
        description=payload.description or None,
        target_pages=payload.target_pages,
        filename_pattern=payload.filename_pattern,
        filename_custom_label=payload.filename_custom_label,
        emphasis_font=payload.emphasis_font,
    )
    if result["ok"]:
        return result
    status_code = 400 if result["error_code"] != "template_update_failed" else 500
    raise HTTPException(status_code=status_code, detail=result["error"])


@router.post("/templates/{document_type}/{template_id}/validate")
async def validate_material_template(document_type: str, template_id: str) -> dict:
    result = validate_material_template_usecase(
        document_type=document_type,
        template_id=template_id,
    )
    if result["ok"]:
        return result
    status_code = 400 if result["error_code"] != "template_validate_failed" else 500
    raise HTTPException(status_code=status_code, detail=result["error"])


@router.delete("/templates/{document_type}/{template_id}")
async def delete_material_template(document_type: str, template_id: str) -> dict:
    result = delete_material_template_usecase(
        document_type=document_type,
        template_id=template_id,
    )
    if result["ok"]:
        return result
    status_code_map = {
        "template_not_found": 404,
        "template_default_protected": 403,
        "invalid_document_type": 400,
        "invalid_template_id": 400,
        "template_delete_failed": 500,
    }
    status_code = status_code_map.get(result["error_code"], 400)
    raise HTTPException(status_code=status_code, detail=result["error"])


# ---------------------------------------------------------------------------
# Document library (Phase 17.8)
# ---------------------------------------------------------------------------


def _parse_document_id(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid document ID") from exc


def _parse_optional_uuid(raw: str | None) -> UUID | None:
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid UUID: {raw!r}"
        ) from exc


@router.get("/documents")
async def list_documents(
    document_type: str = Query("", description="Filter: resume | cover_letter"),
) -> dict:
    return list_documents_data(document_type=document_type or None)


@router.post("/documents/upload")
async def upload_document_route(
    document: UploadFile = File(...),
    document_type: str = Form(...),
    display_name: str = Form(""),
    notes: str = Form(""),
) -> dict:
    content = await _read_upload_limited(document)
    result = upload_document(
        document_type=document_type,
        filename=document.filename or "",
        content=content,
        display_name=display_name or None,
        notes=notes or None,
    )
    if result["ok"]:
        return result
    status_code_map = {
        "invalid_document": 400,
        "document_upload_failed": 500,
    }
    raise HTTPException(
        status_code=status_code_map.get(result["error_code"], 400),
        detail=result["error"],
    )


@router.patch("/documents/{document_id}")
async def patch_document(document_id: str, payload: DocumentUpdatePayload) -> dict:
    document_uuid = _parse_document_id(document_id)
    result = update_document(
        document_id=document_uuid,
        display_name=payload.display_name,
        notes=payload.notes,
    )
    if result["ok"]:
        return result
    if result["error_code"] == "document_not_found":
        raise HTTPException(status_code=404, detail=result["error"])
    if result["error_code"] == "invalid_document":
        raise HTTPException(status_code=400, detail=result["error"])
    raise HTTPException(status_code=500, detail=result["error"])


@router.delete("/documents/{document_id}")
async def delete_document_route(document_id: str) -> dict:
    document_uuid = _parse_document_id(document_id)
    result = delete_document(document_id=document_uuid)
    if result["ok"]:
        return result
    if result["error_code"] == "document_not_found":
        raise HTTPException(status_code=404, detail=result["error"])
    raise HTTPException(status_code=500, detail=result["error"])


@router.get("/documents/{document_id}/download")
async def download_document_route(document_id: str):
    document_uuid = _parse_document_id(document_id)
    result = resolve_document_for_download(document_id=document_uuid)
    if not result["ok"]:
        if result["error_code"] == "document_not_found":
            raise HTTPException(status_code=404, detail=result["error"])
        if result["error_code"] == "document_file_missing":
            raise HTTPException(status_code=410, detail=result["error"])
        raise HTTPException(status_code=500, detail=result["error"])
    return FileResponse(result["path"], filename=result["filename"])


@router.post("/documents/promote")
async def promote_document_route(payload: DocumentPromotePayload) -> dict:
    application_uuid = _parse_optional_uuid(payload.application_id)
    snapshot_uuid = _parse_optional_uuid(payload.job_snapshot_id)
    result = promote_artifact_to_library(
        artifact_path=payload.artifact_path,
        document_type=payload.document_type,
        display_name=payload.display_name,
        application_id=application_uuid,
        job_snapshot_id=snapshot_uuid,
        notes=payload.notes,
    )
    if result["ok"]:
        return result
    status_code_map = {
        "artifact_missing": 404,
        "artifact_outside_root": 400,
        "artifact_read_failed": 500,
        "invalid_document": 400,
        "document_upload_failed": 500,
    }
    raise HTTPException(
        status_code=status_code_map.get(result["error_code"], 400),
        detail=result["error"],
    )


@router.get("/artifacts/download")
async def download_artifact(path: str = Query(..., description="Artifact path from generation")):
    output_root = (PROJECT_ROOT / "data" / "output").resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve()

    try:
        resolved.relative_to(output_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Artifact path is not allowed") from exc

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")

    return FileResponse(str(resolved), filename=resolved.name)


@router.get("/jobs/filter-profiles")
async def filter_profiles() -> dict:
    return load_search_profiles_data()


@router.put("/jobs/filter-profiles/{profile_id}")
async def save_filter_profile(profile_id: str, payload: SearchProfilePayload) -> dict:
    result = save_search_profile_data(profile_id=profile_id, profile=payload.model_dump())
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/jobs/filter-profiles/{profile_id}")
async def delete_filter_profile(profile_id: str) -> dict:
    result = delete_search_profile_data(profile_id)
    if not result["ok"]:
        if result["error_code"] == "invalid_search_profile_name":
            raise HTTPException(status_code=400, detail=result["error"])
        raise HTTPException(status_code=404, detail=result["error"])
    return result


async def _read_upload_limited(upload: UploadFile) -> bytes:
    chunks = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_TEMPLATE_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Template upload is too large.")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/jobs/apply")
async def apply_job(payload: JobApplyPayload) -> dict:
    result = await apply_to_url(
        url=payload.url,
        auto_submit=False,
        headless=True,
        dry_run=False,
    )

    if result["ok"]:
        if result["status"] == "SUBMITTED":
            return {
                "status": "submitted",
                "message": "Submitted",
                "job": result["job"],
                "application_id": result.get("tracking_id"),
                "result": result.get("result"),
                "artifacts": result.get("artifacts"),
            }
        if result["status"] == "REVIEW_REQUIRED":
            return {
                "status": "review",
                "message": "Filled to review stage",
                "job": result["job"],
                "application_id": result.get("tracking_id"),
                "result": result.get("result"),
                "artifacts": result.get("artifacts"),
            }

    # 400 == "request as written cannot be applied"; 500 only for
    # things the user can't recover by adjusting their input. EasyApply
    # rejection is a 400 because the user can either wait for the
    # Easy Apply automation or open the LinkedIn posting manually.
    user_recoverable_codes = {
        "unsupported_ats",
        "profile_missing",
        "linkedin_easy_apply_only",
        "job_context_required",
        "missing_application_url",
        "invalid_job_id",
        "job_not_found",
    }
    status_code = 400 if result["error_code"] in user_recoverable_codes else 500
    raise HTTPException(status_code=status_code, detail=result["error"])


@router.get("/applications")
async def applications_data(
    status: str = Query("", description="Filter by status"),
    outcome: str = Query("", description="Filter by outcome"),
    company: str = Query("", description="Filter by company"),
    limit: int = Query(50, description="Max results"),
) -> dict:
    return load_applications_data(status=status, outcome=outcome, company=company, limit=limit)


@router.patch("/applications/{application_id}/outcome")
async def update_outcome(application_id: str, payload: OutcomePayload) -> dict:
    try:
        from uuid import UUID

        application_uuid = UUID(application_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid application ID") from exc

    result = update_application_outcome(application_id=application_uuid, outcome=payload.outcome)
    if not result["ok"]:
        if result["error_code"] == "invalid_outcome":
            raise HTTPException(status_code=400, detail=result["error"])
        if result["error_code"] == "application_not_found":
            raise HTTPException(status_code=404, detail=result["error"])
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.delete("/applications/{application_id}")
async def delete_application(
    application_id: str, cascade: bool = False
) -> dict:
    """Phase 18.4 soft-delete.

    Marks the application's ``deleted_at`` column. Permanent purge
    (artifacts + DB row) is the cleanup task's job and runs after
    ``cleanup.soft_deleted_retention_days``. ``cascade=true`` moves
    the linked resume / cover-letter artifact files into the cleanup
    quarantine immediately instead of waiting for that window.
    """
    try:
        from uuid import UUID

        application_uuid = UUID(application_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid application ID") from exc

    result = soft_delete_application(
        application_id=application_uuid, cascade=cascade
    )
    if not result["ok"]:
        if result["error_code"] == "application_not_found":
            raise HTTPException(status_code=404, detail=result["error"])
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.post("/applications/{application_id}/submit")
async def submit_application(application_id: str) -> dict:
    try:
        from uuid import UUID

        application_uuid = UUID(application_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid application ID") from exc

    result = submit_paused_application(application_id=application_uuid)
    if not result["ok"]:
        if result["error_code"] == "application_not_found":
            raise HTTPException(status_code=404, detail=result["error"])
        if result["error_code"] == "invalid_status":
            raise HTTPException(status_code=409, detail=result["error"])
        if result["error_code"] == "submit_enqueue_failed":
            raise HTTPException(status_code=503, detail=result["error"])
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.post("/applications/{application_id}/regenerate-material")
async def regenerate_application_material_route(
    application_id: str, payload: RegenerateMaterialPayload
) -> dict:
    """Phase 18.2: defaults to enqueue + return ``task_id``.

    The synchronous path stays behind ``AUTOAPPLY_SYNC_MATERIALS=1``
    (Phase 18.6 retires it). The async path enqueues
    ``materials.generate`` against the application's ``job_id`` so
    the task body re-uses the canonical generation pipeline + writes
    artifacts onto the matching ReviewQueueEntry through the same
    audit hooks every other generation uses.
    """
    import os

    try:
        from uuid import UUID

        application_uuid = UUID(application_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid application ID") from exc

    if os.environ.get("AUTOAPPLY_SYNC_MATERIALS") != "1":
        return _enqueue_regenerate_material(application_uuid, payload)
    _warn_sync_materials_deprecated("regenerate-material")

    try:
        result = await regenerate_application_material(
            application_id=application_uuid,
            material_type=payload.material_type,
            strategy=payload.strategy,
            template_id=payload.template_id,
            source_document_id=payload.source_document_id,
            patch_aggressiveness=payload.patch_aggressiveness,
            patch_allow_reorder_sections=payload.patch_allow_reorder_sections,
            patch_allow_add_remove_bullets=payload.patch_allow_add_remove_bullets,
        )
    except Exception as exc:
        # The inner functions are supposed to catch their own failures
        # and return a structured error dict, but a few code paths
        # (model serialization, downstream DB writes) can still raise
        # bare exceptions. Without this catch FastAPI just renders
        # ``Internal Server Error`` with no traceback in our log,
        # leaving the operator with nothing to debug.
        import logging
        logging.getLogger("autoapply.web.routes.api").exception(
            "regenerate-material crashed: material_type=%s strategy=%s "
            "source_document_id=%s",
            payload.material_type,
            payload.strategy,
            payload.source_document_id,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Regeneration crashed: {type(exc).__name__}: {exc}",
        ) from exc
    if result["ok"]:
        return result
    status_code_map = {
        "invalid_material_type": 400,
        "application_not_found": 404,
        "job_not_found": 404,
        "database_unavailable": 503,
        "missing_artifact": 500,
        "generation_failed": 500,
        "material_generation_failed": 500,
        "serialization_failed": 500,
        "load_failed": 500,
        "application_update_failed": 500,
    }
    # Surface ``strategy_notes`` (e.g. "Library document is a PDF
    # file -- generated fresh instead") to the user. Without this
    # the front-end only sees the generic ``error`` field and the
    # operator can't tell whether the patch fell back, why the
    # artifact is missing, or which step actually failed.
    notes = result.get("strategy_notes") or []
    detail = result["error"]
    if notes:
        detail = f"{detail} Notes: {'; '.join(notes)}"
    raise HTTPException(
        status_code=status_code_map.get(result["error_code"], 400),
        detail=detail,
    )


@router.post("/applications/{application_id}/discard")
async def discard_application(application_id: str, payload: DiscardPayload) -> dict:
    try:
        from uuid import UUID

        application_uuid = UUID(application_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid application ID") from exc

    result = discard_paused_application(
        application_id=application_uuid,
        reason=payload.reason,
    )
    if not result["ok"]:
        if result["error_code"] == "application_not_found":
            raise HTTPException(status_code=404, detail=result["error"])
        if result["error_code"] == "invalid_status":
            raise HTTPException(status_code=409, detail=result["error"])
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.get("/profile")
async def profile_data(profile_id: str = Query("", description="Optional profile id")) -> dict:
    return load_profile_data(profile_id or None)


@router.post("/profile")
async def create_profile(payload: ProfileCreatePayload) -> dict:
    result = create_empty_profile(profile_id=payload.profile_id, set_active=payload.set_active)
    if not result["ok"]:
        status_code = 409 if result["error_code"] == "profile_exists" else 400
        raise HTTPException(status_code=status_code, detail=result["error"])
    return result


@router.put("/profile/{profile_id}")
async def save_profile(profile_id: str, payload: ProfileSavePayload) -> dict:
    if profile_id != payload.profile_id:
        raise HTTPException(status_code=400, detail="Profile id mismatch")
    return save_profile_data(
        profile_id=payload.profile_id,
        profile_data=payload.profile,
        set_active=payload.set_active,
    )


@router.delete("/profile/{profile_id}")
async def delete_profile(profile_id: str) -> dict:
    result = delete_profile_data(profile_id=profile_id)
    if not result["ok"]:
        status_code = 404 if result["error_code"] == "profile_not_found" else 400
        raise HTTPException(status_code=status_code, detail=result["error"])
    return result


@router.patch("/profile/{profile_id}/rename")
async def rename_profile(profile_id: str, payload: ProfileRenamePayload) -> dict:
    result = rename_profile_data(profile_id=profile_id, new_profile_id=payload.new_profile_id)
    if not result["ok"]:
        if result["error_code"] == "profile_not_found":
            raise HTTPException(status_code=404, detail=result["error"])
        if result["error_code"] == "profile_exists":
            raise HTTPException(status_code=409, detail=result["error"])
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/profile/{profile_id}/activate")
async def activate_profile(profile_id: str) -> dict:
    result = activate_profile_data(profile_id=profile_id)
    if not result["ok"]:
        status_code = 404 if result["error_code"] == "profile_not_found" else 400
        raise HTTPException(status_code=status_code, detail=result["error"])
    return result


@router.post("/profile/upload-resume")
async def upload_resume(
    resume: UploadFile = File(...),
    profile_id: str = Form(""),
    overwrite: bool = Form(False),
    set_active: bool = Form(True),
) -> dict:
    content = await resume.read()
    result = import_resume_file(
        filename=resume.filename or "",
        content=content,
        profile_id=profile_id or None,
        overwrite=overwrite,
        set_active=set_active,
    )
    if not result["ok"]:
        status_code = 400
        if result["error_code"] == "profile_exists":
            status_code = 409
        elif result["error_code"] not in {"unsupported_file_type", "profile_exists"}:
            status_code = 500
        raise HTTPException(status_code=status_code, detail=result["error"])
    return result


@router.post("/profile/from-library")
async def create_profile_from_library(payload: ProfileFromLibraryPayload) -> dict:
    result = import_resume_from_library(
        document_id=payload.document_id,
        profile_id=payload.profile_id or None,
        overwrite=payload.overwrite,
        set_active=payload.set_active,
    )
    if not result["ok"]:
        status_code_map = {
            "invalid_document_id": 400,
            "document_not_found": 404,
            "invalid_document_type": 400,
            "document_file_missing": 410,
            "profile_exists": 409,
            "unsupported_file_type": 400,
            "resume_parse_failed": 500,
            "document_load_failed": 500,
        }
        raise HTTPException(
            status_code=status_code_map.get(result["error_code"], 400),
            detail=result["error"],
        )
    return result


@router.get("/settings/llm")
async def settings_data() -> dict:
    return load_llm_settings_data()


@router.get("/settings/material-defaults")
async def material_defaults_data() -> dict:
    return load_material_defaults_data()


@router.put("/settings/material-defaults")
async def update_material_defaults(payload: MaterialDefaultsPayload) -> dict:
    raw = payload.model_dump()
    # Validate strategy values up front so we return a tidy 400 with a
    # specific message rather than letting the normalizer silently fix
    # them and the user wonder why the save "worked" but didn't.
    for doc_type in SUPPORTED_DOCUMENT_TYPES:
        entry = raw.get(doc_type)
        if entry and entry.get("strategy") not in SUPPORTED_STRATEGIES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported strategy {entry['strategy']!r} for {doc_type}; "
                    f"expected one of {SUPPORTED_STRATEGIES}"
                ),
            )
    result = save_material_defaults(raw)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.put("/settings/llm")
async def update_settings(payload: LLMSettingsPayload) -> dict:
    if payload.small_tier_action not in {"preserve", "set", "clear"}:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid small_tier_action {payload.small_tier_action!r}; "
                "expected 'preserve', 'set', or 'clear'."
            ),
        )
    result = update_llm_settings_data(
        primary_provider=payload.primary_provider,
        fallback_provider=payload.fallback_provider,
        allow_fallback=payload.allow_fallback,
        cache_enabled=payload.cache_enabled,
        cache_ttl_hours=payload.cache_ttl_hours,
        small_provider=payload.small_provider,
        small_model=payload.small_model,
        small_tier_action=payload.small_tier_action,
    )
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.delete("/settings/search-cache")
async def clear_search_cache() -> dict:
    result = clear_search_cache_data()
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


# ---------------------------------------------------------------------------
# Providers (Phase 10 registry surface)
# ---------------------------------------------------------------------------


@router.get("/providers")
async def providers_list() -> dict:
    """Return the public view of every registered provider."""
    return list_providers()


@router.get("/providers/{provider_id}/models")
async def providers_models(provider_id: str) -> dict:
    """Phase 17.9.4 model catalog for the Connect dialog picker.

    Returns the curated KNOWN_MODELS for ``provider_id``, plus the
    live runtime catalog for providers that have one (Ollama today).
    Unknown ids 404.
    """
    result = list_provider_models(provider_id)
    if not result["ok"] and result.get("error_code") == "unknown_provider":
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/providers/{provider_id}/test")
async def providers_test(provider_id: str) -> dict:
    result = test_provider_connection(provider_id)
    if not result["ok"] and result.get("error_code") == "unknown_provider":
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/providers/{provider_id}/set-key")
async def providers_set_key(
    provider_id: str, payload: ProviderSetKeyPayload
) -> dict:
    result = connect_api_key_provider(
        provider_id,
        api_key=payload.api_key,
        model=payload.model,
        base_url=payload.base_url,
    )
    code = result.get("error_code") if not result.get("ok") else None
    if code == "unknown_provider":
        raise HTTPException(status_code=404, detail=result["error"])
    if code in {"wrong_auth_type", "empty_api_key"}:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.put("/providers/{provider_id}/model")
async def providers_set_model(
    provider_id: str, payload: ProviderSetModelPayload
) -> dict:
    """Phase 17.9.11: change a provider's model without re-entering its key."""
    result = update_provider_model(provider_id, model=payload.model)
    if not result["ok"]:
        code = result.get("error_code")
        if code == "unknown_provider":
            raise HTTPException(status_code=404, detail=result["error"])
        if code == "not_connected":
            raise HTTPException(status_code=409, detail=result["error"])
    return result


@router.delete("/providers/{provider_id}")
async def providers_disconnect(provider_id: str) -> dict:
    result = disconnect_provider(provider_id)
    if not result["ok"] and result.get("error_code") == "unknown_provider":
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/providers/{provider_id}/use")
async def providers_use(
    provider_id: str, payload: ProviderUsePayload
) -> dict:
    result = use_provider_as_primary(
        provider_id, fallback_provider=payload.fallback_provider
    )
    if not result["ok"] and result.get("error_code") == "unknown_provider":
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/providers/health")
async def providers_health() -> dict:
    """Phase 11.4 -- cached health snapshot for every configured provider.

    Backed by :class:`src.providers.health.ProviderHealthMonitor`, which
    runs ``test_connection()`` against each configured provider every
    ``interval_seconds`` (default 5 min). The records survive between
    HTTP requests but reset on process restart.

    Returns ``{records, last_run_started_at, last_run_finished_at,
    interval_seconds, running}``; ``records[provider_id]`` is
    ``{ok, detail, latency_ms, checked_at}``.
    """
    from src.providers.health import get_monitor  # noqa: PLC0415

    return get_monitor().snapshot().to_dict()


@router.post("/providers/health/refresh")
async def providers_health_refresh() -> dict:
    """Force a probe round and return the fresh snapshot.

    Useful from the Settings UI when the user clicks "Refresh now" or
    just connected a new key and wants to confirm health without
    waiting for the next scheduled tick.
    """
    from src.providers.health import get_monitor  # noqa: PLC0415

    monitor = get_monitor()
    # Run in a worker thread so the HTTP loop doesn't stall on the
    # provider probes (httpx + subprocess).
    import asyncio  # noqa: PLC0415

    await asyncio.to_thread(monitor.probe_all)
    return monitor.snapshot().to_dict()


# ---------------------------------------------------------------------------
# Cache inspector (Phase 12.6)
# ---------------------------------------------------------------------------


@router.get("/cache")
async def cache_snapshot_endpoint() -> dict:
    """Per-namespace cache snapshot consumed by ``/settings/cache``.

    SCAN-based Redis counts run in a worker thread because, at worst,
    they iterate the keyspace; we do not want the FastAPI event loop
    blocked while that happens.
    """
    import asyncio  # noqa: PLC0415

    from src.application.cache import cache_snapshot  # noqa: PLC0415

    return await asyncio.to_thread(cache_snapshot)


class ClearCachePayload(BaseModel):
    """Phase 12.6 inspector UI -> ``DELETE /api/cache/{namespace}``.

    The body carries a confirmation flag (the UI sets ``confirm=True``
    after the operator clicks through the modal); without it the
    endpoint refuses to act, mirroring the ``redis flush --yes``
    posture on the CLI side."""

    confirm: bool = Field(False, description="Operator confirmed the destructive op.")


# --- Phase 13.7: Job Index freshness surface ---------------------------

class JobIndexFreshnessPayload(BaseModel):
    """Search-key inputs the Jobs page already has client-side. Mirrors
    JobSearchPayload's freshness-relevant fields. The route normalizes +
    fingerprints these to look up the SearchQuery row."""

    source: str = "linkedin"
    keywords: list[str] = Field(default_factory=list)
    profile: str = ""
    locations: list[str] = Field(default_factory=list)
    time_filter: str = "week"
    experience_levels: list[str] = Field(default_factory=list)
    employment_types: list[str] = Field(default_factory=list)
    location_types: list[str] = Field(default_factory=list)
    education_levels: list[str] = Field(default_factory=list)
    pay_operator: str = ""
    experience_operator: str = ""
    max_pages: int | None = None


def _freshness_params(payload: JobIndexFreshnessPayload) -> dict:
    from src.application.jobs import (  # noqa: PLC0415
        _linkedin_job_index_params,
        _linkedin_max_pages,
        _map_linkedin_experience_levels,
        _map_linkedin_job_types,
        _normalize_time_filter,
    )

    location = (payload.locations or [""])[0]
    max_pages = _linkedin_max_pages(
        payload.max_pages or 20,
        search_location=location,
        experience_levels=payload.experience_levels,
        employment_types=payload.employment_types,
        location_types=payload.location_types,
        locations=payload.locations,
        pay_operator=payload.pay_operator or None,
        experience_operator=payload.experience_operator or None,
        education_levels=payload.education_levels,
    )
    return _linkedin_job_index_params(
        {
            "keywords": payload.keywords,
            "location": location,
            "time_filter": _normalize_time_filter(payload.time_filter),
            "experience_levels": _map_linkedin_experience_levels(payload.experience_levels),
            "job_types": _map_linkedin_job_types(payload.employment_types),
            "max_pages": max_pages,
            "enrich_details": True,
            "filter_profile": payload.profile or None,
            "allow_public_fallback": False,
        }
    )


@router.post("/jobs/index/freshness")
async def job_index_freshness(payload: JobIndexFreshnessPayload) -> dict:
    """Return Job Index freshness metadata for a search condition.

    The Jobs page renders "Last updated Xh ago" from this and decides
    whether to highlight the [Refresh] button. Returns ``known=False``
    when the search has never been indexed so the existing flow keeps
    working without the index populated.
    """
    from src.application.job_index import get_search_freshness  # noqa: PLC0415

    return get_search_freshness(source=payload.source, params=_freshness_params(payload))


@router.post("/jobs/index/refresh")
async def job_index_refresh(payload: JobIndexFreshnessPayload) -> dict:
    """Enqueue a high-priority refresh task for a search condition.

    The Phase 14 scheduler will pick this up. For now the response is
    used by the Jobs page to flip the [Refresh] button into a spinner
    state pending the actual re-scrape."""
    from src.application.job_index import enqueue_search_refresh  # noqa: PLC0415

    result = enqueue_search_refresh(source=payload.source, params=_freshness_params(payload))
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result)
    return result


@router.get("/jobs/index/posting/{posting_id}")
async def job_index_posting_freshness(
    posting_id: str,
    context: str = Query("search_display"),
) -> dict:
    """Per-posting freshness verdict (Phase 13.6 should_refresh)."""
    from src.application.job_index import posting_freshness  # noqa: PLC0415

    if context not in ("search_display", "generate_materials", "before_submit"):
        raise HTTPException(status_code=400, detail={"error": "invalid_context"})
    return posting_freshness(posting_id=posting_id, context=context)


@router.delete("/cache/{namespace}")
async def cache_clear_namespace_endpoint(
    namespace: str, payload: ClearCachePayload | None = None
) -> dict:
    """Drop every entry in ``namespace``. Requires ``{"confirm": true}``
    in the body so a mistyped curl can't wipe the cache."""
    if payload is None or not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "confirmation_required",
                "message": "Send {\"confirm\": true} to clear this namespace.",
            },
        )
    # SCAN+DEL against a large namespace can take a moment; run off
    # the event loop so one operator click doesn't stall unrelated
    # API requests. Mirrors the GET /api/cache snapshot path.
    import asyncio  # noqa: PLC0415

    from src.application.cache import clear_cache_namespace  # noqa: PLC0415

    result = await asyncio.to_thread(clear_cache_namespace, namespace)
    if not result["ok"]:
        # 400 for client-side mistakes (bad namespace name); 500 for
        # backend failures during the actual clear.
        status = (
            400
            if result.get("error_code") == "invalid_namespace"
            else 500
        )
        raise HTTPException(status_code=status, detail=result)
    return result


def _enqueue_regenerate_material(
    application_uuid: Any, payload: RegenerateMaterialPayload
) -> dict:
    """Phase 18.2: enqueue ``materials.generate`` for an existing
    application's job, returning ``{task_id, poll_url}`` so the SPA
    can poll ``GET /api/tasks/{task_id}`` for the produced artifacts.

    ``regenerate_application_material``'s logic (lookup the
    Application, resolve the Job, pick the right
    ``document_type`` from ``material_type``) is mirrored here at the
    enqueue boundary; the post-completion writeback to
    ``Application.resume_version`` / ``cover_letter_version`` is done
    by the task body via the same code path
    ``application.prepare`` uses.
    """
    from src.application.material_defaults import resolve_material_choice
    from src.application.regenerate_materials import (
        MATERIAL_TYPE_TO_DOCUMENT_TYPE,
    )
    from src.core.config import load_config
    from src.core.database import get_session_factory
    from src.core.models import Application
    from src.tasks.app import celery_app
    from src.tasks.base import AutoApplyTask as _AutoApplyTask
    from src.tasks.base import EnqueueSpec
    from src.tasks.context import current_tenant_id

    document_type = MATERIAL_TYPE_TO_DOCUMENT_TYPE.get(payload.material_type)
    if document_type is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported material_type {payload.material_type!r}.",
        )

    factory = get_session_factory(load_config())
    job_payload: dict[str, Any] | None = None
    with factory() as session:
        app = session.get(Application, application_uuid)
        if app is None:
            raise HTTPException(status_code=404, detail="Application not found.")
        job_id = str(app.job_id)
        try:
            from src.core.models import Job  # noqa: PLC0415

            job = session.get(Job, app.job_id) if app.job_id else None
            if job is not None:
                job_payload = {
                    "id": str(job.id),
                    "source": job.source or "unknown",
                    "source_id": job.source_id or str(job.id),
                    "company": job.company,
                    "title": job.title,
                    "location": job.location,
                    "employment_type": job.employment_type,
                    "seniority": job.seniority,
                    "description": job.description,
                    "requirements": job.requirements or {},
                    "application_url": job.application_url,
                    "ats_type": job.ats_type or job.source or "unknown",
                    "raw_data": job.raw_data or {},
                }
        except Exception:
            job_payload = None

    try:
        choice = resolve_material_choice(
            document_type=document_type,
            override_strategy=payload.strategy,
            override_template_id=payload.template_id,
            override_document_id=payload.source_document_id,
            override_patch_aggressiveness=payload.patch_aggressiveness,
            override_patch_allow_reorder_sections=payload.patch_allow_reorder_sections,
            override_patch_allow_add_remove_bullets=payload.patch_allow_add_remove_bullets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    task_payload: dict[str, Any] = {
        "job_id": job_id,
        "application_id": str(application_uuid),
        "document_types": [document_type],
    }
    if job_payload:
        task_payload["job"] = job_payload
    if document_type == "resume":
        task_payload["resume_strategy"] = choice["strategy"]
        task_payload["resume_template_id"] = choice["template_id"] or payload.template_id
        task_payload["resume_source_document_id"] = choice["document_id"]
        task_payload["resume_patch_aggressiveness"] = choice["patch_aggressiveness"]
        task_payload["resume_patch_allow_reorder_sections"] = choice[
            "patch_allow_reorder_sections"
        ]
        task_payload["resume_patch_allow_add_remove_bullets"] = choice[
            "patch_allow_add_remove_bullets"
        ]
    else:
        task_payload["cover_letter_strategy"] = choice["strategy"]
        task_payload["cover_letter_template_id"] = (
            choice["template_id"] or payload.template_id
        )
        task_payload["cover_letter_source_document_id"] = choice["document_id"]
        task_payload["cover_letter_patch_aggressiveness"] = choice["patch_aggressiveness"]
        task_payload["cover_letter_patch_allow_reorder_sections"] = choice[
            "patch_allow_reorder_sections"
        ]
        task_payload["cover_letter_patch_allow_add_remove_bullets"] = choice[
            "patch_allow_add_remove_bullets"
        ]

    # Codex review fix: an idempotency key keyed only on
    # ``application_id + material_type`` made every subsequent
    # regenerate short-circuit to the first successful run, so a
    # user who switched template / strategy / source_document after
    # the first regenerate would silently get the old artifact back.
    # Fingerprint the effective generation choices so each distinct
    # request still hits the broker, while duplicate identical clicks
    # still short-circuit. Include a version because older regenerate
    # tasks omitted inline legacy Job payloads and could persist
    # ``posting_not_found`` as a Celery-successful result under the old
    # key; those stale rows must not block the fixed enqueue payload.
    import hashlib
    import json

    # 2026-05-21 fix (v4): a user-initiated **Regenerate** click is an
    # explicit intent to re-run. The previous fingerprint-only model
    # blocked the click whenever the configuration looked identical,
    # even when:
    #   * the same template's content was edited (style overrides /
    #     target_pages / filename pattern) but the template_id stayed
    #     the same,
    #   * the rendered template_id was the seeded default (None on the
    #     task payload because the user never explicitly picked one),
    #     so the manifest hash never even made it into the fingerprint.
    #
    # The fix has two pieces:
    #   1. Resolve the *effective* template_id by falling back to the
    #      seeded default when the payload has no explicit pick. This
    #      is the template the renderer will actually load, so it is
    #      the one whose manifest should fingerprint the run.
    #   2. Include a 5-second time bucket in the fingerprint. Real
    #      double-clicks (network retry, accidental dup) land in the
    #      same bucket and still dedupe; a user who waits long enough
    #      to actually want a re-run lands in a fresh bucket and gets
    #      one. This is the right tradeoff: the idempotency guard is
    #      meant to catch automation-level duplicates, not to lock
    #      humans out of their own button.
    import time

    from src.documents.templates import (  # noqa: PLC0415
        DEFAULT_TEMPLATE_IDS,
        load_template_package,
    )

    effective_template_id = (
        task_payload.get(f"{document_type}_template_id")
        or DEFAULT_TEMPLATE_IDS.get(document_type)
    )
    template_manifest_fingerprint: str | None = None
    if effective_template_id:
        try:
            template_package = load_template_package(
                document_type, effective_template_id
            )
            template_manifest_fingerprint = hashlib.sha256(
                template_package.manifest.model_dump_json(
                    exclude={"name", "description"}
                ).encode("utf-8")
            ).hexdigest()[:16]
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "regenerate: failed to hash template manifest for %s/%s: %s",
                document_type,
                effective_template_id,
                exc,
            )

    request_bucket = int(time.time()) // 5

    choice_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "regenerate_enqueue_version": 4,
                "strategy": choice.get("strategy"),
                "template_id": effective_template_id,
                "template_manifest_fingerprint": template_manifest_fingerprint,
                "legacy_job_payload": bool(job_payload),
                "job_id": job_id,
                "source_document_id": choice.get("document_id"),
                "patch_aggressiveness": choice.get("patch_aggressiveness"),
                "patch_allow_reorder_sections": choice.get(
                    "patch_allow_reorder_sections"
                ),
                "patch_allow_add_remove_bullets": choice.get(
                    "patch_allow_add_remove_bullets"
                ),
                "request_bucket_5s": request_bucket,
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()[:16]

    tenant = current_tenant_id() or "default"
    spec = EnqueueSpec(
        kind="materials.generate",
        queue="materials",
        payload=task_payload,
        tenant_id=tenant,
        idempotency_key=(
            f"regenerate:{application_uuid}:{payload.material_type}:"
            f"{choice_fingerprint}"
        ),
    )
    with factory() as session:
        task_id = _AutoApplyTask.enqueue(
            celery_task=celery_app.tasks["materials.generate"],
            session=session,
            spec=spec,
        )
    return {
        "ok": True,
        "status": "queued",
        "task_id": str(task_id),
        "material_type": payload.material_type,
        "application_id": str(application_uuid),
        "poll_url": f"/api/tasks/{task_id}",
    }
