"""Jobs route -- search, browse, and manage job listings."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse

from src.core.config import PROJECT_ROOT

router = APIRouter(tags=["jobs"])


@router.get("/", response_class=HTMLResponse)
async def jobs_list(request: Request):
    """Job search page with search form and results."""
    templates = request.app.state.templates
    return templates.TemplateResponse("jobs.html", {
        "request": request,
        "page_title": "Job Search",
        "jobs": [],
        "search_params": {},
    })


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
    templates = request.app.state.templates

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

    except Exception as e:
        error = str(e)

    # Check if this is an HTMX request (partial update)
    is_htmx = request.headers.get("HX-Request") == "true"

    context = {
        "request": request,
        "jobs": jobs,
        "error": error,
        "search_params": {
            "source": source,
            "keyword": keyword,
            "location": location,
            "profile": profile,
        },
    }

    if is_htmx:
        return templates.TemplateResponse("partials/job_results.html", context)

    context["page_title"] = "Job Search"
    return templates.TemplateResponse("jobs.html", context)


@router.get("/detail/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: str):
    """View job detail page."""
    templates = request.app.state.templates

    job = None
    try:
        from src.core.config import load_config
        from src.core.database import get_session_factory
        from src.core.models import Job
        import uuid

        config = load_config()
        SessionFactory = get_session_factory(config)
        with SessionFactory() as session:
            job = session.get(Job, uuid.UUID(job_id))
    except Exception:
        pass

    return templates.TemplateResponse("job_detail.html", {
        "request": request,
        "page_title": "Job Detail",
        "job": job,
    })
