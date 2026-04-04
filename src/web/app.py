"""FastAPI application factory.

Creates the main FastAPI app with Jinja2 templates, static files,
and all route modules registered.

Usage:
    uvicorn src.web.app:create_app --factory --reload
    OR
    autoapply web
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

WEB_DIR = Path(__file__).parent
TEMPLATE_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AutoApply",
        description="AI-powered job application automation dashboard",
        version="0.7.0",
    )

    # Session middleware for flash messages
    app.add_middleware(SessionMiddleware, secret_key="autoapply-dev-key")

    # Static files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Templates (shared across routes)
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    app.state.templates = templates

    # Register route modules
    from src.web.routes import applications, dashboard, jobs, profile, settings

    app.include_router(dashboard.router)
    app.include_router(jobs.router, prefix="/jobs")
    app.include_router(applications.router, prefix="/applications")
    app.include_router(profile.router, prefix="/profile")
    app.include_router(settings.router, prefix="/settings")

    return app
