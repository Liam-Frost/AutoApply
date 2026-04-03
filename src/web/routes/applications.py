"""Applications route -- view and manage application tracking."""

from __future__ import annotations

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["applications"])


@router.get("/", response_class=HTMLResponse)
async def applications_list(
    request: Request,
    status: str = Query("", description="Filter by status"),
    outcome: str = Query("", description="Filter by outcome"),
    company: str = Query("", description="Filter by company"),
    limit: int = Query(50, description="Max results"),
):
    """View applications with optional filters."""
    templates = request.app.state.templates

    applications = []
    pipeline_stats = {}
    error = None

    try:
        from src.core.config import load_config
        from src.core.database import get_session_factory
        from src.tracker.database import get_applications_with_jobs
        from src.tracker.analytics import compute_pipeline_stats, compute_outcome_stats

        config = load_config()
        SessionFactory = get_session_factory(config)

        with SessionFactory() as session:
            applications = get_applications_with_jobs(
                session,
                status=status or None,
                outcome=outcome or None,
                company=company or None,
                limit=limit,
            )
            pipeline_stats = compute_pipeline_stats(session)
            outcome_stats = compute_outcome_stats(session)

    except Exception as e:
        error = str(e)
        outcome_stats = {"total": 0, "pending": 0, "rates": {}}

    return templates.TemplateResponse("applications.html", {
        "request": request,
        "page_title": "Applications",
        "applications": applications,
        "pipeline": pipeline_stats,
        "outcomes": outcome_stats,
        "error": error,
        "filters": {"status": status, "outcome": outcome, "company": company},
    })


@router.post("/update-outcome", response_class=HTMLResponse)
async def update_outcome(
    request: Request,
    application_id: str = Form(...),
    outcome: str = Form(...),
):
    """Update application outcome (HTMX)."""
    templates = request.app.state.templates

    try:
        import uuid
        from src.core.config import load_config
        from src.core.database import get_session_factory
        from src.tracker.database import update_application_outcome

        config = load_config()
        SessionFactory = get_session_factory(config)

        with SessionFactory() as session:
            success = update_application_outcome(
                session, uuid.UUID(application_id), outcome
            )

        if success:
            return HTMLResponse(
                f'<span class="text-green-600">Updated to {outcome}</span>'
            )
        else:
            return HTMLResponse(
                '<span class="text-red-600">Application not found</span>'
            )

    except Exception as e:
        return HTMLResponse(f'<span class="text-red-600">Error: {e}</span>')
