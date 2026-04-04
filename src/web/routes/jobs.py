"""Jobs route -- search, browse, and manage job listings."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from src.core.config import PROJECT_ROOT

router = APIRouter(tags=["jobs"])


def _render(request: Request, name: str, **ctx):
    templates = request.app.state.templates
    return templates.TemplateResponse(request=request, name=name, context=ctx)


@router.get("/", response_class=HTMLResponse)
async def jobs_list(request: Request):
    """Job search page with search form and results."""
    return _render(request, "jobs.html", page_title="Job Search", jobs=[], search_params={})


@router.post("/search", response_class=HTMLResponse)
async def search_jobs(
    request: Request,
    source: str = Form("ats"),
    keyword: str = Form(""),
    location: str = Form(""),
    profile: str = Form("default"),
    time_filter: str = Form("week"),
    ats: str = Form(""),
    company: str = Form(""),
):
    """Execute job search and return results (HTMX partial)."""
    jobs = []
    error = None

    try:
        if source in ("linkedin", "all") and keyword:
            from src.intake.search import search_linkedin

            linkedin_jobs = await search_linkedin(
                keywords=keyword,
                location=location,
                time_filter=time_filter,
                headless=True,
                max_pages=3,
            )
            jobs.extend(linkedin_jobs)

        if source in ("ats", "all"):
            from src.intake.search import search_jobs as search_ats

            config_dir = PROJECT_ROOT / "config"
            companies = None
            if ats and company:
                companies = {ats: [company]}

            ats_jobs = search_ats(
                profile=profile,
                config_dir=config_dir,
                companies=companies,
            )
            jobs.extend(ats_jobs)

        profile_path = PROJECT_ROOT / "data" / "profile" / "profile.yaml"
        if jobs and profile_path.exists():
            from src.matching.scorer import build_scoring_context, score_jobs
            from src.memory.profile import load_profile_yaml

            profile_data = load_profile_yaml(profile_path)
            scoring_ctx = build_scoring_context(profile_data)
            scored_jobs = score_jobs(jobs, scoring_ctx)
            score_by_id = {score.job_id: score for score in scored_jobs}

            for job in jobs:
                score = score_by_id.get(str(job.id))
                if score is not None:
                    job.raw_data["match_score"] = score.final_score
                    job.raw_data["disqualified"] = score.disqualified

            jobs.sort(key=lambda item: item.raw_data.get("match_score", 0.0), reverse=True)

    except Exception as e:
        error = str(e)

    search_params = {
        "source": source,
        "keyword": keyword,
        "location": location,
        "profile": profile,
        "time_filter": time_filter,
        "ats": ats,
        "company": company,
    }

    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        return _render(
            request,
            "partials/job_results.html",
            jobs=jobs,
            error=error,
            search_params=search_params,
        )

    return _render(
        request,
        "jobs.html",
        page_title="Job Search",
        jobs=jobs,
        error=error,
        search_params=search_params,
    )


@router.post("/apply", response_class=HTMLResponse)
async def apply_job(request: Request, url: str = Form(...)):
    """Trigger the application pipeline for a search result."""
    try:
        from src.cli.cmd_apply import (
            _detect_ats_from_url,
            _load_job_for_application,
            _load_profile,
            _run_application_for_job,
        )

        ats_type = _detect_ats_from_url(url)
        if not ats_type:
            return HTMLResponse('<span class="text-red-600">Unsupported ATS URL</span>')

        profile_data = _load_profile()
        if not profile_data:
            return HTMLResponse('<span class="text-red-600">Profile not configured</span>')

        job = _load_job_for_application(url, ats_type)
        result = await _run_application_for_job(
            job=job,
            profile_data=profile_data,
            auto_submit=False,
            headless=True,
            dry_run=False,
            match_score=job.raw_data.get("match_score"),
        )

        if result is None:
            return HTMLResponse('<span class="text-red-600">Application could not start</span>')
        if result.status == "SUBMITTED":
            return HTMLResponse('<span class="text-green-600">Submitted</span>')
        if result.status == "REVIEW_REQUIRED":
            return HTMLResponse('<span class="text-cyan-600">Filled to review stage</span>')
        return HTMLResponse(f'<span class="text-red-600">Failed: {result.error}</span>')
    except Exception as e:
        return HTMLResponse(f'<span class="text-red-600">Error: {e}</span>')


@router.get("/detail/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: str):
    """View job detail page."""
    job = None
    try:
        import uuid

        from src.core.config import load_config
        from src.core.database import get_session_factory
        from src.core.models import Job

        config = load_config()
        session_factory = get_session_factory(config)
        with session_factory() as session:
            job = session.get(Job, uuid.UUID(job_id))
    except Exception:
        pass

    return _render(request, "job_detail.html", page_title="Job Detail", job=job)
