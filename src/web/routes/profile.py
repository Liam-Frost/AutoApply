"""Profile route -- view and manage applicant profile."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import HTMLResponse

from src.core.config import PROJECT_ROOT

router = APIRouter(tags=["profile"])

PROFILE_DIR = PROJECT_ROOT / "data" / "profile"
PROFILE_FILE = PROFILE_DIR / "profile.yaml"


def _render(request: Request, name: str, **ctx):
    templates = request.app.state.templates
    return templates.TemplateResponse(request=request, name=name, context=ctx)


@router.get("/", response_class=HTMLResponse)
async def profile_view(request: Request):
    """View the current applicant profile."""
    profile_data = None
    if PROFILE_FILE.exists():
        try:
            from src.memory.profile import load_profile_yaml

            profile_data = load_profile_yaml(PROFILE_FILE)
        except Exception:
            pass

    return _render(
        request, "profile.html",
        page_title="Profile",
        profile=profile_data,
        profile_path=str(PROFILE_FILE),
    )


@router.post("/upload-resume", response_class=HTMLResponse)
async def upload_resume(request: Request, resume: UploadFile = File(...)):
    """Upload and parse a resume file."""
    suffix = Path(resume.filename).suffix.lower()
    if suffix not in (".pdf", ".docx"):
        return _render(
            request, "profile.html",
            page_title="Profile",
            profile=None,
            profile_path=str(PROFILE_FILE),
            error="Only .pdf and .docx files are supported.",
        )

    tmp_path = PROFILE_DIR / f"_upload{suffix}"
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    content = await resume.read()
    with open(tmp_path, "wb") as f:
        f.write(content)

    try:
        from src.memory.resume_importer import import_resume

        profile_data = import_resume(tmp_path, output_path=PROFILE_FILE)

        return _render(
            request, "profile.html",
            page_title="Profile",
            profile=profile_data,
            profile_path=str(PROFILE_FILE),
            success=f"Resume parsed successfully ({len(profile_data)} sections)",
        )

    except Exception as e:
        return _render(
            request, "profile.html",
            page_title="Profile",
            profile=None,
            profile_path=str(PROFILE_FILE),
            error=f"Resume parsing failed: {e}",
        )
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
