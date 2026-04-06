"""Profile use cases shared by CLI and Web."""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from src.core.config import PROJECT_ROOT

PROFILE_DIR = PROJECT_ROOT / "data" / "profile"
LEGACY_PROFILE_FILE = PROFILE_DIR / "profile.yaml"
PROFILES_DIR = PROFILE_DIR / "profiles"
ACTIVE_PROFILE_FILE = PROFILE_DIR / "active_profile.txt"

DEFAULT_PROFILE_ID = "default"
VALID_PROFILE_ID_RE = re.compile(r"[^a-z0-9_-]+")


def load_profile_data(profile_id: str | None = None) -> dict:
    _ensure_profile_store()
    profiles = list_profiles()
    active_profile_id = get_active_profile_id()
    selected_profile_id = profile_id or active_profile_id
    profile_path = get_profile_path(selected_profile_id) if selected_profile_id else None
    profile = None

    if profile_path and profile_path.exists():
        from src.memory.profile import load_profile_yaml

        profile = load_profile_yaml(profile_path)

    return {
        "profile": profile,
        "profile_path": str(profile_path) if profile_path else "",
        "has_profile": profile is not None,
        "profiles": profiles,
        "active_profile_id": active_profile_id,
        "selected_profile_id": selected_profile_id,
    }


def import_resume_file(
    *,
    filename: str,
    content: bytes,
    profile_id: str | None = None,
    overwrite: bool = False,
    set_active: bool = True,
) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".docx"):
        return {
            "ok": False,
            "error": "Only .pdf and .docx files are supported.",
            "error_code": "unsupported_file_type",
        }

    _ensure_profile_store()
    target_profile_id = sanitize_profile_id(profile_id or Path(filename).stem or DEFAULT_PROFILE_ID)
    profile_path = get_profile_path(target_profile_id)
    if profile_path.exists() and not overwrite:
        return {
            "ok": False,
            "error": f"Profile '{target_profile_id}' already exists.",
            "error_code": "profile_exists",
        }

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = PROFILE_DIR / f"_upload_{uuid4().hex}{suffix}"
    tmp_path.write_bytes(content)

    try:
        from src.memory.resume_importer import import_resume

        imported = import_resume(tmp_path)
        profile = _normalize_profile_data(imported)
        _write_profile(profile_path, profile)
        if set_active:
            set_active_profile(target_profile_id)

        payload = load_profile_data(target_profile_id)
        return {
            "ok": True,
            "status": "parsed",
            "message": f"Resume parsed into profile '{target_profile_id}'.",
            **payload,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Resume parsing failed: {exc}",
            "error_code": "resume_parse_failed",
        }
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def save_profile_data(
    *, profile_id: str, profile_data: dict[str, Any], set_active: bool = False
) -> dict:
    _ensure_profile_store()
    target_profile_id = sanitize_profile_id(profile_id)
    profile_path = get_profile_path(target_profile_id)
    normalized = _normalize_profile_data(profile_data)

    if profile_path.exists():
        with open(profile_path, encoding="utf-8") as handle:
            existing = yaml.safe_load(handle) or {}
        if isinstance(existing, dict):
            for key, value in existing.items():
                if key not in normalized:
                    normalized[key] = value

    _write_profile(profile_path, normalized)

    if set_active or not get_active_profile_id():
        set_active_profile(target_profile_id)

    return {
        "ok": True,
        "status": "saved",
        "message": f"Profile '{target_profile_id}' saved.",
        **load_profile_data(target_profile_id),
    }


def create_empty_profile(*, profile_id: str, set_active: bool = True) -> dict:
    _ensure_profile_store()
    target_profile_id = sanitize_profile_id(profile_id)
    profile_path = get_profile_path(target_profile_id)
    if profile_path.exists():
        return {
            "ok": False,
            "error": f"Profile '{target_profile_id}' already exists.",
            "error_code": "profile_exists",
        }

    _write_profile(profile_path, _empty_profile())
    if set_active:
        set_active_profile(target_profile_id)

    return {
        "ok": True,
        "status": "created",
        "message": f"Profile '{target_profile_id}' created.",
        **load_profile_data(target_profile_id),
    }


def delete_profile_data(*, profile_id: str) -> dict:
    _ensure_profile_store()
    target_profile_id = sanitize_profile_id(profile_id)
    profile_path = get_profile_path(target_profile_id)
    if not profile_path.exists():
        return {
            "ok": False,
            "error": f"Profile '{target_profile_id}' not found.",
            "error_code": "profile_not_found",
        }

    profile_path.unlink()
    remaining = list_profiles()
    active_profile_id = get_active_profile_id()
    if active_profile_id == target_profile_id:
        if remaining:
            set_active_profile(remaining[0]["id"])
        elif ACTIVE_PROFILE_FILE.exists():
            ACTIVE_PROFILE_FILE.unlink()

    return {
        "ok": True,
        "status": "deleted",
        "message": f"Profile '{target_profile_id}' deleted.",
        **load_profile_data(),
    }


def rename_profile_data(*, profile_id: str, new_profile_id: str) -> dict:
    _ensure_profile_store()
    current_profile_id = sanitize_profile_id(profile_id)
    target_profile_id = sanitize_profile_id(new_profile_id)
    current_path = get_profile_path(current_profile_id)
    target_path = get_profile_path(target_profile_id)

    if not current_path.exists():
        return {
            "ok": False,
            "error": f"Profile '{current_profile_id}' not found.",
            "error_code": "profile_not_found",
        }

    if target_profile_id != current_profile_id and target_path.exists():
        return {
            "ok": False,
            "error": f"Profile '{target_profile_id}' already exists.",
            "error_code": "profile_exists",
        }

    if target_profile_id != current_profile_id:
        current_path.rename(target_path)
        if get_active_profile_id() == current_profile_id:
            set_active_profile(target_profile_id)

    return {
        "ok": True,
        "status": "renamed",
        "message": f"Profile '{current_profile_id}' renamed to '{target_profile_id}'.",
        **load_profile_data(target_profile_id),
    }


def activate_profile_data(*, profile_id: str) -> dict:
    _ensure_profile_store()
    target_profile_id = sanitize_profile_id(profile_id)
    profile_path = get_profile_path(target_profile_id)
    if not profile_path.exists():
        return {
            "ok": False,
            "error": f"Profile '{target_profile_id}' not found.",
            "error_code": "profile_not_found",
        }

    set_active_profile(target_profile_id)
    return {
        "ok": True,
        "status": "activated",
        "message": f"Profile '{target_profile_id}' activated.",
        **load_profile_data(target_profile_id),
    }


def get_active_profile_path() -> Path | None:
    _ensure_profile_store()
    active_profile_id = get_active_profile_id()
    if not active_profile_id:
        return None
    profile_path = get_profile_path(active_profile_id)
    return profile_path if profile_path.exists() else None


def get_active_profile_id() -> str | None:
    if not ACTIVE_PROFILE_FILE.exists():
        return None
    profile_id = ACTIVE_PROFILE_FILE.read_text(encoding="utf-8").strip()
    return profile_id or None


def get_profile_path(profile_id: str) -> Path:
    return PROFILES_DIR / f"{sanitize_profile_id(profile_id)}.yaml"


def list_profiles() -> list[dict[str, Any]]:
    _ensure_profile_store()
    active_profile_id = get_active_profile_id()
    profiles = []
    for path in sorted(PROFILES_DIR.glob("*.yaml")):
        stat = path.stat()
        profiles.append(
            {
                "id": path.stem,
                "name": path.stem,
                "path": str(path),
                "is_active": path.stem == active_profile_id,
                "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
            }
        )
    return profiles


def sanitize_profile_id(value: str) -> str:
    cleaned = VALID_PROFILE_ID_RE.sub("-", value.strip().lower()).strip("-")
    return cleaned or DEFAULT_PROFILE_ID


def set_active_profile(profile_id: str) -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_PROFILE_FILE.write_text(sanitize_profile_id(profile_id), encoding="utf-8")


def _ensure_profile_store() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    default_profile_path = get_profile_path(DEFAULT_PROFILE_ID)
    if LEGACY_PROFILE_FILE.exists() and not default_profile_path.exists():
        shutil.copy2(LEGACY_PROFILE_FILE, default_profile_path)

    if not get_active_profile_id():
        profiles = list(PROFILES_DIR.glob("*.yaml"))
        if profiles:
            set_active_profile(profiles[0].stem)


def _write_profile(path: Path, profile_data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(
            profile_data, handle, default_flow_style=False, allow_unicode=True, sort_keys=False
        )


def _normalize_profile_data(profile_data: dict[str, Any]) -> dict[str, Any]:
    data = dict(profile_data or {})
    data.setdefault("identity", {})
    data.setdefault("education", [])
    data.setdefault("work_experiences", [])
    data.setdefault("projects", [])
    data.setdefault("skills", {})
    return data


def _empty_profile() -> dict[str, Any]:
    return {
        "identity": {
            "full_name": "",
            "email": "",
            "phone": "",
            "location": "",
            "linkedin_url": "",
            "github_url": "",
            "portfolio_url": "",
        },
        "education": [],
        "work_experiences": [],
        "projects": [],
        "skills": {
            "languages": [],
            "frameworks": [],
            "databases": [],
            "tools": [],
            "domains": [],
        },
    }
