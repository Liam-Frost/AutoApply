"""Settings use cases shared by CLI and Web."""

from __future__ import annotations

from src.core.config import PROJECT_ROOT, load_config, update_llm_settings
from src.utils.llm import detect_available_providers, get_llm_settings


def load_llm_settings_data() -> dict:
    config = load_config()
    return {
        "llm": get_llm_settings(config),
        "available_providers": detect_available_providers(),
        "config_path": str(PROJECT_ROOT / "config" / "settings.yaml"),
    }


def update_llm_settings_data(
    *,
    primary_provider: str,
    fallback_provider: str | None = None,
    allow_fallback: bool = False,
) -> dict:
    fallback = fallback_provider or None
    if fallback == primary_provider:
        fallback = None

    try:
        update_llm_settings(primary_provider, fallback, allow_fallback and fallback is not None)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Failed to update LLM settings: {exc}",
            "error_code": "settings_update_failed",
        }

    return {
        "ok": True,
        "status": "updated",
        "message": "LLM settings updated successfully.",
        **load_llm_settings_data(),
    }
