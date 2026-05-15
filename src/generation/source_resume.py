"""Phase 15.1: source-resume ingestion.

The :class:`SourceResume` ORM row is the durable record; this module
owns the side-effecting operations that build a row from an uploaded
file: SHA256 checksum, file-type classification, on-disk storage
under ``data/source_resumes/<tenant>/``, and a best-effort structural
extraction so the materials router (Phase 15.5) can decide ``docx``
patch vs ``generate_from_template`` without re-opening the file.

The structural extraction is intentionally shallow:

* ``docx`` -- collect ``(style_name, text_first_chars)`` per paragraph
  using ``python-docx``. The DOCX patch mode (Phase 15.2) reads this
  index to find the bullets / summary block by style without
  re-parsing the file.
* ``latex`` -- record positions of ``\\section`` / ``\\subsection``
  commands so the LaTeX adapter (Phase 15.8) can map them to manifest
  blocks.
* ``pdf`` -- record extracted headings via the existing
  ``resume_importer`` so fact extraction still works even though
  format-preserving edits do not. Per D024: PDF imports feed fact
  extraction only.

Storage path is always relative to ``PROJECT_ROOT`` so the API can
return it without leaking host filesystem layout (mirrors D013).
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.config import PROJECT_ROOT
from src.core.models import SourceResume
from src.tasks.context import current_tenant_id

logger = logging.getLogger(__name__)

_STORAGE_ROOT = PROJECT_ROOT / "data" / "source_resumes"

_SUPPORTED_TYPES = ("docx", "latex", "pdf")
_EXT_TO_TYPE = {
    ".docx": "docx",
    ".tex": "latex",
    ".pdf": "pdf",
}


class SourceResumeError(Exception):
    """Raised on invalid input (unsupported type, checksum collision)."""


@dataclass(frozen=True)
class IngestResult:
    """Returned from :func:`ingest`. Callers use ``row_id`` to bind a
    materials.generate task to this exact source."""

    row_id: Any
    source_type: str
    editable: bool
    checksum: str
    storage_path: str  # relative to PROJECT_ROOT
    size_bytes: int


def detect_source_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in _EXT_TO_TYPE:
        raise SourceResumeError(
            f"unsupported source resume type {suffix!r}; expected one of {_SUPPORTED_TYPES}"
        )
    return _EXT_TO_TYPE[suffix]


def compute_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ingest(
    session: Session,
    *,
    filename: str,
    data: bytes,
    tenant_id: str | None = None,
    notes: str | None = None,
) -> IngestResult:
    """Validate, store, extract structure, persist row. Caller commits."""
    if not filename:
        raise SourceResumeError("filename is required")
    if not data:
        raise SourceResumeError("uploaded bytes are empty")

    source_type = detect_source_type(filename)
    editable = source_type != "pdf"  # PDF is fact-extraction-only per D024.
    checksum = compute_checksum(data)
    tenant = tenant_id or current_tenant_id()

    # Reject re-uploads of identical content (the user can pass
    # `notes` to disambiguate intent, but the underlying bytes
    # already exist as a source).
    existing = session.execute(
        select(SourceResume)
        .where(SourceResume.tenant_id == tenant)
        .where(SourceResume.checksum == checksum)
    ).scalar_one_or_none()
    if existing is not None:
        return IngestResult(
            row_id=existing.id,
            source_type=existing.source_type,
            editable=existing.editable,
            checksum=existing.checksum,
            storage_path=existing.storage_path,
            size_bytes=existing.size_bytes,
        )

    storage_path = _store(tenant, checksum, filename, data)
    structure = _extract_structure(source_type, data, storage_path)

    row = SourceResume(
        tenant_id=tenant,
        source_type=source_type,
        editable=editable,
        original_filename=Path(filename).name,
        checksum=checksum,
        storage_path=str(storage_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        extracted_structure=structure,
        size_bytes=len(data),
        notes=notes,
    )
    session.add(row)
    session.flush()

    return IngestResult(
        row_id=row.id,
        source_type=source_type,
        editable=editable,
        checksum=checksum,
        storage_path=row.storage_path,
        size_bytes=len(data),
    )


def resolve_storage_path(row: SourceResume) -> Path:
    """Project-relative ``storage_path`` -> absolute path on disk.

    Kept as a single function so callers (Phase 15.2 patch mode, 15.4
    LaTeX generator, 15.5 materials router) never recompute the join
    themselves -- saves us re-checking traversal each time.
    """
    rel = row.storage_path.replace("\\", "/").lstrip("/")
    target = (PROJECT_ROOT / rel).resolve()
    # Defense in depth: reject paths that escaped the storage root.
    storage_root = _STORAGE_ROOT.resolve()
    if storage_root not in target.parents and target != storage_root:
        raise SourceResumeError(
            f"resolved source path {target} is outside storage root {storage_root}"
        )
    return target


def delete(session: Session, row: SourceResume) -> None:
    """Remove a source resume and its on-disk file. Caller commits.

    Idempotent: missing-file is logged, not raised. The DB row is
    always deleted so a corrupt on-disk state cannot block cleanup."""
    try:
        path = resolve_storage_path(row)
        if path.exists():
            path.unlink()
    except Exception:  # noqa: BLE001
        logger.exception("source-resume file delete failed for %s", row.id)
    session.delete(row)


# ---- Internal helpers ------------------------------------------------


def _store(tenant: str, checksum: str, filename: str, data: bytes) -> Path:
    safe_tenant = re.sub(r"[^A-Za-z0-9_.-]", "_", tenant or "default")
    dest_dir = _STORAGE_ROOT / safe_tenant
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()
    dest = dest_dir / f"{checksum}{suffix}"
    if not dest.exists():
        dest.write_bytes(data)
    return dest


def _extract_structure(source_type: str, data: bytes, path: Path) -> dict[str, Any]:
    """Best-effort -- failure returns an empty dict rather than
    raising. The materials router can still operate; downstream
    surfaces will note an extraction failure in notes."""
    try:
        if source_type == "docx":
            return _extract_docx_structure(path)
        if source_type == "latex":
            return _extract_latex_structure(data)
        if source_type == "pdf":
            return _extract_pdf_headings(path)
    except Exception:  # noqa: BLE001
        logger.exception("structure extraction failed for %s", source_type)
    return {}


def _extract_docx_structure(path: Path) -> dict[str, Any]:
    from docx import Document  # local import: heavy

    doc = Document(str(path))
    paragraphs: list[dict[str, Any]] = []
    for idx, para in enumerate(doc.paragraphs):
        text = (para.text or "").strip()
        if not text:
            continue
        style = getattr(getattr(para, "style", None), "name", "") or ""
        paragraphs.append(
            {
                "index": idx,
                "style": style,
                "text_head": text[:120],
                "is_bullet": style.startswith("List") or text.startswith(("•", "-")),
            }
        )
    return {
        "format": "docx",
        "paragraph_count": len(paragraphs),
        "paragraphs": paragraphs[:200],  # truncate to keep JSONB row size sane
    }


_LATEX_SECTION_RE = re.compile(
    r"\\(section|subsection|subsubsection|paragraph)\s*\*?\s*\{([^}]*)\}"
)


def _extract_latex_structure(data: bytes) -> dict[str, Any]:
    text = data.decode("utf-8", errors="replace")
    sections: list[dict[str, Any]] = []
    for match in _LATEX_SECTION_RE.finditer(text):
        sections.append(
            {
                "kind": match.group(1),
                "title": match.group(2).strip(),
                "offset": match.start(),
            }
        )
    return {
        "format": "latex",
        "section_count": len(sections),
        "sections": sections[:200],
        "char_count": len(text),
    }


def _extract_pdf_headings(path: Path) -> dict[str, Any]:
    try:
        import pymupdf  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        return {"format": "pdf", "headings": [], "extraction_supported": False}
    headings: list[str] = []
    page_count = 0
    with pymupdf.open(str(path)) as doc:
        # Capture page_count INSIDE the with block -- ``len(doc)`` after
        # the context manager closes the Document raises (codex P2).
        page_count = len(doc)
        for page in doc:
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = (span.get("text") or "").strip()
                        if not text:
                            continue
                        # Heuristic: large or bold text is a heading.
                        size = float(span.get("size") or 0)
                        is_bold = "Bold" in (span.get("font") or "")
                        if size >= 12.5 or is_bold:
                            headings.append(text)
    # Dedupe order-preserving.
    seen: set[str] = set()
    uniq = [h for h in headings if not (h in seen or seen.add(h))]
    return {
        "format": "pdf",
        "headings": uniq[:80],
        "page_count": page_count,
        "extraction_supported": True,
    }


def shutil_copy(src: Path, dst: Path) -> None:  # pragma: no cover -- thin wrapper
    """Exposed for tests that want to seed the storage dir without
    going through :func:`ingest` (uncommon)."""
    shutil.copy2(src, dst)


__all__ = [
    "IngestResult",
    "SourceResumeError",
    "compute_checksum",
    "delete",
    "detect_source_type",
    "ingest",
    "resolve_storage_path",
]
