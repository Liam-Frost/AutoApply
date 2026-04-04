"""JSON API routes for the Vue web client."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from src.core.config import PROJECT_ROOT, load_config, update_llm_settings
from src.utils.llm import detect_available_providers, get_llm_settings

router = APIRouter(prefix="/api", tags=["api"])

PROFILE_DIR = PROJECT_ROOT / "data" / "profile"
PROFILE_FILE = PROFILE_DIR / "profile.yaml"
VALID_OUTCOMES = {"pending", "rejected", "oa", "interview", "offer"}


class JobSearchPayload(BaseModel):
    source: str = "ats"
    keyword: str = ""
    location: str = ""
    profile: str = "default"
    time_filter: str = "week"
    ats: str = ""
    company: str = ""


class JobApplyPayload(BaseModel):
    url: str


class OutcomePayload(BaseModel):
    outcome: str


class LLMSettingsPayload(BaseModel):
    primary_provider: str
    fallback_provider: str | None = None
    allow_fallback: bool = False


@router.get("/dashboard")
async def dashboard_data() -> dict:
    return _load_dashboard_data()


@router.post("/jobs/search")
async def search_jobs(payload: JobSearchPayload) -> dict:
    jobs = []
    errors = []

    if payload.source in ("linkedin", "all") and payload.keyword:
        try:
            from src.intake.search import search_linkedin

            linkedin_jobs = await search_linkedin(
                keywords=payload.keyword,
                location=payload.location,
                time_filter=payload.time_filter,
                headless=True,
                max_pages=3,
            )
            jobs.extend(linkedin_jobs)
        except Exception as exc:
            errors.append(f"LinkedIn: {exc}")

    if payload.source in ("ats", "all"):
        try:
            from src.intake.search import search_jobs as search_ats

            companies = None
            if payload.ats and payload.company:
                companies = {payload.ats: [payload.company]}

            ats_jobs = search_ats(
                profile=payload.profile,
                config_dir=PROJECT_ROOT / "config",
                companies=companies,
            )
            jobs.extend(ats_jobs)
        except Exception as exc:
            errors.append(f"ATS: {exc}")

    if jobs and PROFILE_FILE.exists():
        try:
            from src.matching.scorer import build_scoring_context, score_jobs
            from src.memory.profile import load_profile_yaml

            profile_data = load_profile_yaml(PROFILE_FILE)
            scoring_ctx = build_scoring_context(profile_data)
            scored_jobs = score_jobs(jobs, scoring_ctx)
            score_by_id = {score.job_id: score for score in scored_jobs}

            for job in jobs:
                score = score_by_id.get(str(job.id))
                if score is not None:
                    job.raw_data["match_score"] = score.final_score
                    job.raw_data["disqualified"] = score.disqualified

            jobs.sort(key=lambda item: item.raw_data.get("match_score", 0.0), reverse=True)
        except Exception as exc:
            errors.append(f"Scoring: {exc}")

    return {
        "jobs": [_serialize_raw_job(job) for job in jobs],
        "error": "; ".join(errors) or None,
        "search_params": payload.model_dump(),
    }


@router.post("/jobs/apply")
async def apply_job(payload: JobApplyPayload) -> dict:
    try:
        from src.cli.cmd_apply import (
            _detect_ats_from_url,
            _load_job_for_application,
            _load_profile,
            _run_application_for_job,
        )

        ats_type = _detect_ats_from_url(payload.url)
        if not ats_type:
            raise HTTPException(status_code=400, detail="Unsupported ATS URL")

        profile_data = _load_profile()
        if not profile_data:
            raise HTTPException(status_code=400, detail="Profile not configured")

        job = _load_job_for_application(payload.url, ats_type)
        result = await _run_application_for_job(
            job=job,
            profile_data=profile_data,
            auto_submit=False,
            headless=True,
            dry_run=False,
            match_score=job.raw_data.get("match_score"),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Application failed: {exc}") from exc

    if result is None:
        raise HTTPException(status_code=500, detail="Application could not start")
    if result.status == "SUBMITTED":
        return {"status": "submitted", "message": "Submitted"}
    if result.status == "REVIEW_REQUIRED":
        return {"status": "review", "message": "Filled to review stage"}
    raise HTTPException(status_code=500, detail=f"Failed: {result.error}")


@router.get("/applications")
async def applications_data(
    status: str = Query("", description="Filter by status"),
    outcome: str = Query("", description="Filter by outcome"),
    company: str = Query("", description="Filter by company"),
    limit: int = Query(50, description="Max results"),
) -> dict:
    applications = []
    pipeline_stats = {}
    outcome_stats = {
        "total": 0,
        "pending": 0,
        "rejected": 0,
        "oa": 0,
        "interview": 0,
        "offer": 0,
        "rates": {},
    }
    error = None

    try:
        from src.core.database import get_session_factory
        from src.tracker.analytics import compute_outcome_stats
        from src.tracker.database import get_application_counts, get_applications_with_jobs

        config = load_config()
        session_factory = get_session_factory(config)

        with session_factory() as session:
            applications = get_applications_with_jobs(
                session,
                status=status or None,
                outcome=outcome or None,
                company=company or None,
                limit=limit,
            )
            pipeline_stats = get_application_counts(session)
            summary = compute_outcome_stats(session)
            outcome_stats = {
                "total": summary.total_submitted,
                "pending": summary.pending,
                "rejected": summary.rejected,
                "oa": summary.oa,
                "interview": summary.interview,
                "offer": summary.offer,
                "rates": {
                    "response_rate": summary.response_rate,
                    "positive_rate": summary.positive_rate,
                },
            }
    except Exception as exc:
        error = str(exc)

    return {
        "applications": [_serialize_application(app, job) for app, job in applications],
        "pipeline": pipeline_stats,
        "outcomes": outcome_stats,
        "error": error,
        "filters": {"status": status, "outcome": outcome, "company": company, "limit": limit},
    }


@router.patch("/applications/{application_id}/outcome")
async def update_application_outcome(application_id: UUID, payload: OutcomePayload) -> dict:
    if payload.outcome not in VALID_OUTCOMES:
        raise HTTPException(status_code=400, detail="Invalid outcome")

    try:
        from src.core.database import get_session_factory
        from src.tracker.database import update_outcome

        config = load_config()
        session_factory = get_session_factory(config)

        with session_factory() as session:
            app = update_outcome(session, application_id, payload.outcome)
            session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update outcome: {exc}") from exc

    return {
        "status": "updated",
        "message": f"Updated to {payload.outcome}",
        "application_id": str(app.id),
        "outcome": app.outcome,
        "updated_at": _isoformat(app.outcome_updated_at),
    }


@router.get("/profile")
async def profile_data() -> dict:
    profile = None
    if PROFILE_FILE.exists():
        try:
            from src.memory.profile import load_profile_yaml

            profile = load_profile_yaml(PROFILE_FILE)
        except Exception:
            profile = None

    return {
        "profile": profile,
        "profile_path": str(PROFILE_FILE),
        "has_profile": profile is not None,
    }


@router.post("/profile/upload-resume")
async def upload_resume(resume: UploadFile = File(...)) -> dict:
    suffix = Path(resume.filename or "").suffix.lower()
    if suffix not in (".pdf", ".docx"):
        raise HTTPException(status_code=400, detail="Only .pdf and .docx files are supported.")

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = PROFILE_DIR / f"_upload{suffix}"
    content = await resume.read()
    tmp_path.write_bytes(content)

    try:
        from src.memory.resume_importer import import_resume

        profile = import_resume(tmp_path, output_path=PROFILE_FILE)
        return {
            "status": "parsed",
            "message": f"Resume parsed successfully ({len(profile)} sections)",
            "profile": profile,
            "profile_path": str(PROFILE_FILE),
            "has_profile": True,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Resume parsing failed: {exc}") from exc
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@router.get("/settings/llm")
async def settings_data() -> dict:
    config = load_config()
    return {
        "llm": get_llm_settings(config),
        "available_providers": detect_available_providers(),
        "config_path": str(PROJECT_ROOT / "config" / "settings.yaml"),
    }


@router.put("/settings/llm")
async def update_settings(payload: LLMSettingsPayload) -> dict:
    fallback = payload.fallback_provider or None
    if fallback == payload.primary_provider:
        fallback = None

    try:
        update_llm_settings(
            payload.primary_provider, fallback, payload.allow_fallback and fallback is not None
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to update LLM settings: {exc}"
        ) from exc

    config = load_config()
    return {
        "status": "updated",
        "message": "LLM settings updated successfully.",
        "llm": get_llm_settings(config),
        "available_providers": detect_available_providers(),
        "config_path": str(PROJECT_ROOT / "config" / "settings.yaml"),
    }


def _load_dashboard_data() -> dict:
    try:
        from src.core.database import get_session_factory
        from src.tracker.analytics import (
            compute_company_stats,
            compute_outcome_stats,
            compute_pipeline_stats,
        )
        from src.tracker.database import get_application_counts

        config = load_config()
        session_factory = get_session_factory(config)

        with session_factory() as session:
            pipeline_summary = compute_pipeline_stats(session)
            pipeline = get_application_counts(session)
            outcome_summary = compute_outcome_stats(session)
            companies = compute_company_stats(session)

        return {
            "pipeline": pipeline,
            "summary": {
                "total_discovered": pipeline_summary.total_discovered,
                "total_applied": pipeline_summary.total_applied,
                "total_failed": pipeline_summary.total_failed,
                "total_review": pipeline_summary.total_review,
                "avg_match_score": pipeline_summary.avg_match_score,
                "avg_fields_filled_pct": pipeline_summary.avg_fields_filled_pct,
            },
            "outcomes": {
                "total": outcome_summary.total_submitted,
                "pending": outcome_summary.pending,
                "rejected": outcome_summary.rejected,
                "oa": outcome_summary.oa,
                "interview": outcome_summary.interview,
                "offer": outcome_summary.offer,
                "rates": {
                    "response_rate": outcome_summary.response_rate,
                    "positive_rate": outcome_summary.positive_rate,
                },
            },
            "companies": [
                {
                    "company": company.company,
                    "applications": company.applications,
                    "submitted": company.submitted,
                    "outcomes": company.outcomes,
                    "avg_match_score": company.avg_match_score,
                }
                for company in companies
            ],
            "db_connected": True,
        }
    except Exception as exc:
        return {
            "pipeline": {},
            "summary": {
                "total_discovered": 0,
                "total_applied": 0,
                "total_failed": 0,
                "total_review": 0,
                "avg_match_score": 0.0,
                "avg_fields_filled_pct": 0.0,
            },
            "outcomes": {
                "total": 0,
                "pending": 0,
                "rejected": 0,
                "oa": 0,
                "interview": 0,
                "offer": 0,
                "rates": {"response_rate": 0.0, "positive_rate": 0.0},
            },
            "companies": [],
            "db_connected": False,
            "error": str(exc),
        }


def _serialize_raw_job(job) -> dict:
    return {
        "id": str(job.id),
        "source": job.source,
        "source_id": job.source_id,
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "employment_type": job.employment_type,
        "seniority": job.seniority,
        "description": job.description,
        "application_url": job.application_url,
        "ats_type": job.ats_type,
        "raw_data": job.raw_data,
        "discovered_at": _isoformat(job.discovered_at),
    }


def _serialize_application(app, job) -> dict:
    return {
        "id": str(app.id),
        "job_id": str(app.job_id),
        "status": app.status,
        "match_score": app.match_score,
        "outcome": app.outcome or "pending",
        "created_at": _isoformat(app.created_at),
        "updated_at": _isoformat(app.updated_at),
        "submitted_at": _isoformat(app.submitted_at),
        "job": {
            "id": str(job.id),
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "application_url": job.application_url,
            "ats_type": job.ats_type,
        },
    }


def _isoformat(value) -> str | None:
    return value.isoformat() if value is not None else None
