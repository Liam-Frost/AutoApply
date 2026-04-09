"""File-backed cache for LinkedIn search results."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.core.config import PROJECT_ROOT
from src.intake.schema import RawJob

CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "linkedin_search"
CACHE_VERSION = 6


def load_cached_linkedin_search(
    key: dict,
    *,
    ttl_hours: int,
    requested_max_pages: int,
) -> list[RawJob] | None:
    cache_path = _cache_path(key)
    if not cache_path.exists():
        return None

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        cache_path.unlink(missing_ok=True)
        return None

    created_at = payload.get("created_at")
    if not created_at:
        cache_path.unlink(missing_ok=True)
        return None

    expires_at = datetime.fromisoformat(created_at) + timedelta(hours=max(ttl_hours, 1))
    if expires_at <= datetime.now(UTC):
        cache_path.unlink(missing_ok=True)
        return None

    cached_max_pages = int(payload.get("max_pages") or 0)
    if cached_max_pages < requested_max_pages:
        return None

    jobs = payload.get("jobs", [])
    if not jobs:
        cache_path.unlink(missing_ok=True)
        return None

    return [RawJob.model_validate(item) for item in jobs]


def save_cached_linkedin_search(key: dict, jobs: list[RawJob], *, max_pages: int) -> None:
    if not jobs:
        _cache_path(key).unlink(missing_ok=True)
        return

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "max_pages": max_pages,
        "jobs": [job.model_dump(mode="json") for job in jobs],
    }
    _cache_path(key).write_text(json.dumps(payload), encoding="utf-8")


def clear_linkedin_search_cache() -> dict:
    if not CACHE_DIR.exists():
        return {"ok": True, "cleared": 0}

    cleared = 0
    for cache_file in CACHE_DIR.glob("*.json"):
        cache_file.unlink(missing_ok=True)
        cleared += 1
    return {"ok": True, "cleared": cleared}


def build_linkedin_search_cache_key(
    *,
    keywords: list[str],
    location: str,
    time_filter: str,
    experience_levels: list[str] | None,
    job_types: list[str] | None,
    enrich_details: bool,
    max_detail_fetches: int,
    allow_public_fallback: bool,
) -> dict:
    return {
        "version": CACHE_VERSION,
        "keywords": keywords,
        "location": location,
        "time_filter": time_filter,
        "experience_levels": experience_levels or [],
        "job_types": job_types or [],
        "enrich_details": enrich_details,
        "max_detail_fetches": max_detail_fetches,
        "allow_public_fallback": allow_public_fallback,
    }


def _cache_path(key: dict) -> Path:
    digest = hashlib.sha1(json.dumps(key, sort_keys=True).encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"
