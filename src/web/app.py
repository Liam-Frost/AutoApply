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
        # Reserve /api/* for the JSON API and /assets/* for the bundled SPA
        # asset chunks. Everything else falls back to index.html so client-
        # side router paths (e.g. /materials, /materials/templates,
        # /profile/<id>) survive a hard refresh; vue-router handles "not
        # found" rendering itself.
        if full_path.startswith("api") or full_path.startswith("assets"):
            return HTMLResponse("Not Found", status_code=404)

        return _frontend_html()

    return app
