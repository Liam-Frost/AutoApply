"""Profile use cases shared by CLI and Web."""

from __future__ import annotations

from pathlib import Path

from src.core.config import PROJECT_ROOT

PROFILE_DIR = PROJECT_ROOT / "data" / "profile"
PROFILE_FILE = PROFILE_DIR / "profile.yaml"


def load_profile_data() -> dict:
    profile = None
    if PROFILE_FILE.exists():
        try:
            from src.memory.profile import load_profile_yaml

            profile = load_profile_yaml(PROFILE_FILE)
        except Exception:
            profile = None

    return {
        "profile": profile,
        "profile_path": str(PROFILE_FILE),
        "has_profile": profile is not None,
    }


def import_resume_file(*, filename: str, content: bytes) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".docx"):
        return {
            "ok": False,
            "error": "Only .pdf and .docx files are supported.",
            "error_code": "unsupported_file_type",
        }

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = PROFILE_DIR / f"_upload{suffix}"
    tmp_path.write_bytes(content)

    try:
        from src.memory.resume_importer import import_resume

        profile = import_resume(tmp_path, output_path=PROFILE_FILE)
        return {
            "ok": True,
            "status": "parsed",
            "message": f"Resume parsed successfully ({len(profile)} sections)",
            "profile": profile,
            "profile_path": str(PROFILE_FILE),
            "has_profile": True,
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
