"""File naming, versioning, and output management.

Handles consistent naming of generated resume/cover letter files
and maintains a record of which file was used for each application.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

logger = logging.getLogger("autoapply.documents.file_manager")

DocumentType = Literal["resume", "cover"]


def make_filename(
    doc_type: DocumentType,
    company: str,
    role: str,
    date: datetime | None = None,
    ext: str = "docx",
) -> str:
    """Generate a standardized filename.

    Pattern: {type}_{company}_{role}_{date}.{ext}
    Special chars replaced with underscores, lowercased.

    Example: resume_stripe_backend_engineer_2026-04-02.docx
    """
    if date is None:
        date = datetime.now(UTC)

    def slugify(s: str) -> str:
        s = s.lower().strip()
        s = re.sub(r"[^\w\s-]", "", s)
        s = re.sub(r"[\s_-]+", "_", s)
        return s[:40]  # cap length

    return f"{doc_type}_{slugify(company)}_{slugify(role)}_{date.strftime('%Y-%m-%d')}.{ext}"


def get_output_paths(
    output_dir: Path,
    company: str,
    role: str,
    date: datetime | None = None,
) -> dict[str, Path]:
    """Return all output paths for a single application's documents.

    Returns dict with keys for DOCX, PDF, and TEX resume/cover-letter artifacts.
    """
    if date is None:
        date = datetime.now(UTC)

    output_dir.mkdir(parents=True, exist_ok=True)

    return {
        "resume_docx": output_dir / make_filename("resume", company, role, date, "docx"),
        "resume_pdf": output_dir / make_filename("resume", company, role, date, "pdf"),
        "resume_tex": output_dir / make_filename("resume", company, role, date, "tex"),
        "cover_docx": output_dir / make_filename("cover", company, role, date, "docx"),
        "cover_pdf": output_dir / make_filename("cover", company, role, date, "pdf"),
        "cover_tex": output_dir / make_filename("cover", company, role, date, "tex"),
    }


def list_generated_files(output_dir: Path, pattern: str = "*.pdf") -> list[Path]:
    """List all generated files in the output directory."""
    if not output_dir.exists():
        return []
    return sorted(output_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
