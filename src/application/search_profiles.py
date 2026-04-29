"""Saved web search profile management for the Jobs page."""

from __future__ import annotations

import re

import yaml

from src.core.config import PROJECT_ROOT

SEARCH_PROFILES_PATH = PROJECT_ROOT / "config" / "search_profiles.yaml"
_PROFILE_ID_RE = re.compile(r"^[\w][\w \-\.]{0,98}[\w]$|^[\w]$")


def load_search_profiles_data() -> dict:
    profiles = _read_profiles()
    return {
        "ok": True,
        "profiles": [
            {
                "id": profile_id,
                **payload,
            }
            for profile_id, payload in profiles.items()
        ],
        "config_path": str(SEARCH_PROFILES_PATH),
        "error": None,
        "error_code": None,
    }


def save_search_profile_data(*, profile_id: str, profile: dict) -> dict:
    normalized_id = profile_id.strip()
    if not _valid_profile_id(normalized_id):
        return {
            "ok": False,
            "error": "Invalid filter profile name.",
            "error_code": "invalid_search_profile_name",
        }

    profiles = _read_profiles()
    profiles[normalized_id] = _normalize_profile_payload(profile)
    _write_profiles(profiles)
    data = load_search_profiles_data()
    data["message"] = f"Saved filter profile '{normalized_id}'."
    return data


def delete_search_profile_data(profile_id: str) -> dict:
    normalized_id = profile_id.strip()
    if not _valid_profile_id(normalized_id):
        return {
            "ok": False,
            "error": "Invalid filter profile name.",
            "error_code": "invalid_search_profile_name",
        }

    profiles = _read_profiles()
    if normalized_id not in profiles:
        return {
            "ok": False,
            "error": f"Filter profile '{normalized_id}' was not found.",
            "error_code": "search_profile_not_found",
        }

    profiles.pop(normalized_id, None)
    _write_profiles(profiles)
    data = load_search_profiles_data()
    data["message"] = f"Deleted filter profile '{normalized_id}'."
    return data


def _read_profiles() -> dict[str, dict]:
    if not SEARCH_PROFILES_PATH.exists():
        return {}

    with SEARCH_PROFILES_PATH.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    profiles = payload.get("profiles", {})
    if not isinstance(profiles, dict):
        return {}

    return {
        str(profile_id): _normalize_profile_payload(profile)
        for profile_id, profile in profiles.items()
        if isinstance(profile, dict)
    }


def _write_profiles(profiles: dict[str, dict]) -> None:
    SEARCH_PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SEARCH_PROFILES_PATH.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            {"profiles": profiles},
            handle,
            sort_keys=False,
            allow_unicode=False,
        )


def _valid_profile_id(profile_id: str) -> bool:
    return bool(_PROFILE_ID_RE.match(profile_id))


def _normalize_profile_payload(profile: dict | None) -> dict:
    payload = profile or {}
    return {
        "source": _string_value(payload.get("source"), default="ats"),
        "keywords": _list_value(payload.get("keywords")),
        "time_filter": _string_value(payload.get("time_filter"), default="all"),
        "ats": _string_value(payload.get("ats")),
        "company": _string_value(payload.get("company")),
        "locations": _list_value(payload.get("locations")),
        "experience_levels": _list_value(payload.get("experience_levels")),
        "employment_types": _list_value(payload.get("employment_types")),
        "location_types": _list_value(payload.get("location_types")),
        "education_levels": _list_value(payload.get("education_levels")),
        "pay_operator": _string_value(payload.get("pay_operator")),
        "pay_amount": _int_or_none(payload.get("pay_amount")),
        "experience_operator": _string_value(payload.get("experience_operator")),
        "experience_years": _int_or_none(payload.get("experience_years")),
        "max_pages": _int_or_default(payload.get("max_pages"), default=20),
    }


def _list_value(value) -> list[str]:
    if not value:
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _string_value(value, *, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip() or default


def _int_or_none(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_or_default(value, *, default: int) -> int:
    parsed = _int_or_none(value)
    if parsed is None:
        return default
    return max(parsed, 1)
