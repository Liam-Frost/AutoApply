"""FastAPI application factory for the API and Vue client."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

WEB_DIR = Path(__file__).parent
FRONTEND_DIST_DIR = WEB_DIR / "static" / "spa"
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"
FRONTEND_INDEX = FRONTEND_DIST_DIR / "index.html"
SPA_SEGMENTS = {"", "jobs", "applications", "profile", "settings"}


def _frontend_html() -> FileResponse | HTMLResponse:
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)

    return HTMLResponse(
        (
            "<h1>Frontend build missing</h1>"
            "<p>Run <code>npm install</code> and <code>npm run build</code> "
            "in <code>frontend/</code>.</p>"
        ),
        status_code=503,
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AutoApply",
        description="AI-powered job application automation web API",
        version="0.7.0",
    )

    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_ASSETS_DIR), check_dir=False),
        name="frontend_assets",
    )

    from src.web.routes.api import router as api_router

    app.include_router(api_router)

    @app.get("/", include_in_schema=False)
    async def spa_root():
        return _frontend_html()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_routes(full_path: str):
        if full_path.startswith("api") or full_path.startswith("assets"):
            return HTMLResponse("Not Found", status_code=404)

        first_segment = full_path.split("/", 1)[0]
        if first_segment in SPA_SEGMENTS:
            return _frontend_html()

        return HTMLResponse("Not Found", status_code=404)

    return app
