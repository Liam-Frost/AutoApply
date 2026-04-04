"""Applications route -- view and manage application tracking."""

from __future__ import annotations

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["applications"])


def _render(request: Request, name: str, **ctx):
    templates = request.app.state.templates
    return templates.TemplateResponse(request=request, name=name, context=ctx)


@router.get("/", response_class=HTMLResponse)
async def applications_list(
    request: Request,
    status: str = Query("", description="Filter by status"),
    outcome: str = Query("", description="Filter by outcome"),
    company: str = Query("", description="Filter by company"),
    limit: int = Query(50, description="Max results"),
):
    """View applications with optional filters."""
    applications = []
    pipeline_stats = {}
    outcome_stats = {"total": 0, "pending": 0, "rates": {}}
    error = None

    try:
        from src.core.config import load_config
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
                "rates": {
                    "response_rate": summary.response_rate,
                    "positive_rate": summary.positive_rate,
                },
            }

    except Exception as e:
        error = str(e)

    return _render(
        request,
        "applications.html",
        page_title="Applications",
        applications=applications,
        pipeline=pipeline_stats,
        outcomes=outcome_stats,
        error=error,
        filters={"status": status, "outcome": outcome, "company": company},
    )


@router.post("/update-outcome", response_class=HTMLResponse)
async def update_outcome(
    request: Request,
    application_id: str = Form(...),
    outcome: str = Form(...),
):
    """Update application outcome (HTMX)."""
    try:
        import uuid

        from src.core.config import load_config
        from src.core.database import get_session_factory
        from src.tracker.database import update_outcome

        config = load_config()
        session_factory = get_session_factory(config)

        with session_factory() as session:
            app = update_outcome(session, uuid.UUID(application_id), outcome)
            session.commit()

        if app:
            return HTMLResponse(f'<span class="text-green-600">Updated to {outcome}</span>')
        else:
            return HTMLResponse('<span class="text-red-600">Application not found</span>')

    except Exception as e:
        return HTMLResponse(f'<span class="text-red-600">Error: {e}</span>')
