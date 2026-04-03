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
            compute_pipeline_stats,
            compute_outcome_stats,
            compute_company_stats,
        )

        config = load_config()
        SessionFactory = get_session_factory(config)

        with SessionFactory() as session:
            pipeline = compute_pipeline_stats(session)
            outcomes = compute_outcome_stats(session)
            companies = compute_company_stats(session)

            return {
                "pipeline": pipeline,
                "outcomes": outcomes,
                "companies": companies,
                "db_connected": True,
            }
    except Exception:
        return {
            "pipeline": {},
            "outcomes": {"total": 0, "pending": 0, "rates": {}},
            "companies": [],
            "db_connected": False,
        }
