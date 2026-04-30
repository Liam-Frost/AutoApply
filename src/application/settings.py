"""Settings use cases shared by CLI and Web."""

from __future__ import annotations

from src.core.config import (
    PROJECT_ROOT,
    load_config,
    load_raw_config,
    save_config,
    update_llm_settings,
)
from src.intake.search_cache import clear_linkedin_search_cache
from src.utils.llm import detect_available_providers, get_llm_settings


def load_llm_settings_data() -> dict:
    config = load_config()
    return {
        "llm": get_llm_settings(config),
        "search_cache": _search_cache_settings(config),
        "available_providers": detect_available_providers(),
        "config_path": str(PROJECT_ROOT / "config" / "settings.yaml"),
    }


def update_llm_settings_data(
    *,
    primary_provider: str,
    fallback_provider: str | None = None,
    allow_fallback: bool = False,
    cache_enabled: bool = True,
    cache_ttl_hours: int = 24,
) -> dict:
    fallback = fallback_provider or None
    if fallback == primary_provider:
        fallback = None

    try:
        update_llm_settings(primary_provider, fallback, allow_fallback and fallback is not None)
        _update_search_cache_settings(enabled=cache_enabled, ttl_hours=cache_ttl_hours)
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


def clear_search_cache_data() -> dict:
    try:
        cleared = clear_linkedin_search_cache()
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Failed to clear search cache: {exc}",
            "error_code": "search_cache_clear_failed",
        }

    return {
        "ok": True,
        "message": f"Cleared {cleared['cleared']} cached LinkedIn search entries.",
        **load_llm_settings_data(),
    }


def _search_cache_settings(config: dict) -> dict:
    cache_cfg = config.get("search_cache", {})
    return {
        "enabled": bool(cache_cfg.get("enabled", True)),
        "ttl_hours": int(cache_cfg.get("ttl_hours", 24)),
    }


def _update_search_cache_settings(*, enabled: bool, ttl_hours: int) -> None:
    config = load_raw_config()
    cache_cfg = config.setdefault("search_cache", {})
    cache_cfg["enabled"] = bool(enabled)
    cache_cfg["ttl_hours"] = max(int(ttl_hours), 1)
    save_config(config)
