"""Settings route -- manage runtime configuration from the web UI."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from src.core.config import PROJECT_ROOT, load_config, update_llm_settings
from src.utils.llm import detect_available_providers, get_llm_settings

router = APIRouter(tags=["settings"])


def _render(request: Request, name: str, **ctx):
    templates = request.app.state.templates
    return templates.TemplateResponse(request=request, name=name, context=ctx)


@router.get("/", response_class=HTMLResponse)
async def settings_view(request: Request):
    """Render the settings page."""
    config = load_config()
    return _render_settings(request, config=config)


@router.post("/llm", response_class=HTMLResponse)
async def update_llm_config(
    request: Request,
    primary_provider: str = Form(...),
    fallback_provider: str = Form(""),
    allow_fallback: str | None = Form(None),
):
    """Update LLM provider priority settings."""
    fallback = fallback_provider or None
    if fallback == primary_provider:
        fallback = None

    allow = allow_fallback == "on" and fallback is not None

    try:
        update_llm_settings(primary_provider, fallback, allow)
        config = load_config()
        return _render_settings(
            request,
            config=config,
            success="LLM settings updated successfully.",
        )
    except Exception as exc:
        config = load_config()
        return _render_settings(
            request,
            config=config,
            error=f"Failed to update LLM settings: {exc}",
        )


def _render_settings(
    request: Request,
    *,
    config: dict,
    success: str | None = None,
    error: str | None = None,
):
    """Render settings with normalized LLM config and CLI availability."""
    return _render(
        request,
        "settings.html",
        page_title="Settings",
        llm=get_llm_settings(config),
        available_providers=detect_available_providers(),
        config_path=str(PROJECT_ROOT / "config" / "settings.yaml"),
        success=success,
        error=error,
    )
