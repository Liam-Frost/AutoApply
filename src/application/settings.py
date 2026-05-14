"""Settings use cases shared by CLI and Web."""

from __future__ import annotations

from src.core.config import (
    PROJECT_ROOT,
    load_config,
    load_raw_config,
    save_config,
    update_llm_settings,
)
from src.providers import get_registry
from src.utils.llm import detect_available_providers, get_llm_settings


def load_llm_settings_data() -> dict:
    config = load_config()
    return {
        "llm": get_llm_settings(config),
        "search_cache": _search_cache_settings(config),
        "job_index": _job_index_summary(),
        "available_providers": detect_available_providers(),
        # Phase 10 providers (API key / OAuth) the user has connected
        # via ``autoapply provider`` -- the Web UI uses this to render
        # "Connected" badges alongside the CLI availability map above.
        "configured_providers": _configured_registry_providers(),
        "config_path": str(PROJECT_ROOT / "config" / "settings.yaml"),
    }


def _configured_registry_providers() -> list[dict]:
    """Return the public view of every registry provider that's
    currently configured. Empty on a fresh install. Never raises --
    if the registry blows up we just show nothing rather than break
    the settings page."""
    try:
        registry = get_registry()
    except Exception:  # noqa: BLE001
        return []
    out: list[dict] = []
    for provider in registry.all():
        try:
            if provider.is_configured():
                out.append(provider.public_view())
        except Exception:  # noqa: BLE001
            continue
    return out


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
    """Phase 13.8: clears the Job Index search rows instead of the
    legacy file cache. The file cache (`src.intake.search_cache`) was
    removed when Phase 13 landed -- the Job Index is now the source of
    truth for "have we run this search before?"."""
    try:
        from src.core.database import get_session_factory  # noqa: PLC0415
        from src.jobs.legacy import clear_indexed_searches  # noqa: PLC0415
        from src.jobs.store import JobIndexStore  # noqa: PLC0415

        session_factory = get_session_factory(load_config())
        with session_factory() as session, session.begin():
            store = JobIndexStore(session)
            cleared = clear_indexed_searches(store=store)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"Failed to clear search cache: {exc}",
            "error_code": "search_cache_clear_failed",
        }

    return {
        "ok": True,
        "message": f"Cleared {cleared} indexed LinkedIn search entries.",
        **load_llm_settings_data(),
    }


def _search_cache_settings(config: dict) -> dict:
    cache_cfg = config.get("search_cache", {})
    return {
        "enabled": bool(cache_cfg.get("enabled", True)),
        "ttl_hours": int(cache_cfg.get("ttl_hours", 24)),
    }


def _job_index_summary() -> dict:
    try:
        from sqlalchemy import func, select  # noqa: PLC0415
        from sqlalchemy.exc import ProgrammingError  # noqa: PLC0415

        from src.core.database import get_session_factory  # noqa: PLC0415
        from src.core.models import JobPosting, JobSnapshot, SearchQuery  # noqa: PLC0415

        session_factory = get_session_factory(load_config())
        with session_factory() as session:
            states = dict(
                session.execute(
                    select(JobPosting.state, func.count()).group_by(JobPosting.state)
                ).all()
            )
            search_query_count = session.scalar(select(func.count()).select_from(SearchQuery)) or 0
            return {
                "known": True,
                "search_queries": search_query_count,
                "job_postings": session.scalar(select(func.count()).select_from(JobPosting)) or 0,
                "job_snapshots": session.scalar(select(func.count()).select_from(JobSnapshot)) or 0,
                "latest_success_at": _isoformat_or_none(
                    session.scalar(select(func.max(SearchQuery.last_success_at)))
                ),
                "states": states,
            }
    except ProgrammingError:
        return {"known": False, "warning": "job index tables not present; run alembic upgrade head"}
    except Exception as exc:  # noqa: BLE001
        return {"known": False, "warning": str(exc)}


def _isoformat_or_none(value) -> str | None:
    return value.isoformat() if value is not None else None


def _update_search_cache_settings(*, enabled: bool, ttl_hours: int) -> None:
    config = load_raw_config()
    cache_cfg = config.setdefault("search_cache", {})
    cache_cfg["enabled"] = bool(enabled)
    cache_cfg["ttl_hours"] = max(int(ttl_hours), 1)
    save_config(config)
