"""JSON API routes for the Vue web client."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from src.application.jobs import apply_to_url
from src.application.jobs import clear_linkedin_session as clear_linkedin_session_usecase
from src.application.jobs import connect_linkedin_session as connect_linkedin_session_usecase
from src.application.jobs import get_linkedin_session_status as get_linkedin_session_status_usecase
from src.application.jobs import resolve_manual_apply_url as resolve_manual_apply_url_usecase
from src.application.jobs import search_jobs as search_jobs_usecase
from src.application.profile import (
    activate_profile_data,
    create_empty_profile,
    delete_profile_data,
    import_resume_file,
    load_profile_data,
    rename_profile_data,
    save_profile_data,
)
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
    load_applications_data,
    load_dashboard_data,
    update_application_outcome,
)

router = APIRouter(prefix="/api", tags=["api"])


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


class JobApplyPayload(BaseModel):
    url: str


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


class OutcomePayload(BaseModel):
    outcome: str


class LLMSettingsPayload(BaseModel):
    primary_provider: str
    fallback_provider: str | None = None
    allow_fallback: bool = False
    cache_enabled: bool = True
    cache_ttl_hours: int = 24


class ProfileSavePayload(BaseModel):
    profile_id: str
    profile: dict
    set_active: bool = False


class ProfileCreatePayload(BaseModel):
    profile_id: str
    set_active: bool = True


class ProfileRenamePayload(BaseModel):
    new_profile_id: str


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
        headless=True,
        score=True,
        allow_public_linkedin_fallback=False,
    )


@router.get("/jobs/linkedin/session")
async def linkedin_session_status() -> dict:
    return await get_linkedin_session_status_usecase()


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
        raise HTTPException(status_code=404, detail=result["error"])
    return result


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
            return {"status": "submitted", "message": "Submitted", "job": result["job"]}
        if result["status"] == "REVIEW_REQUIRED":
            return {
                "status": "review",
                "message": "Filled to review stage",
                "job": result["job"],
            }

    status_code = 400 if result["error_code"] in {"unsupported_ats", "profile_missing"} else 500
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


@router.get("/settings/llm")
async def settings_data() -> dict:
    return load_llm_settings_data()


@router.put("/settings/llm")
async def update_settings(payload: LLMSettingsPayload) -> dict:
    result = update_llm_settings_data(
        primary_provider=payload.primary_provider,
        fallback_provider=payload.fallback_provider,
        allow_fallback=payload.allow_fallback,
        cache_enabled=payload.cache_enabled,
        cache_ttl_hours=payload.cache_ttl_hours,
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
