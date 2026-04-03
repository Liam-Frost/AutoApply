"""Dashboard route -- main landing page with overview stats."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dashboard"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the main dashboard with pipeline stats."""
    templates = request.app.state.templates

    # Try to load stats from DB, fall back to empty state
    stats = _load_dashboard_stats()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"stats": stats, "page_title": "Dashboard"},
    )


def _load_dashboard_stats() -> dict:
    """Load dashboard statistics. Returns safe defaults if DB unavailable."""
    try:
        from src.core.config import load_config
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
                "summary": pipeline_summary,
                "outcomes": {
                    "total": outcome_summary.total_submitted,
                    "pending": outcome_summary.pending,
                    "rates": {
                        "response_rate": outcome_summary.response_rate,
                        "positive_rate": outcome_summary.positive_rate,
                    },
                },
                "companies": companies,
                "db_connected": True,
            }
    except Exception:
        return {
            "pipeline": {},
            "summary": None,
            "outcomes": {"total": 0, "pending": 0, "rates": {}},
            "companies": [],
            "db_connected": False,
        }
