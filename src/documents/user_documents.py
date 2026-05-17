"""Phase 17.8: user-curated document library.

The user-facing twin of :mod:`src.generation.source_resume`. While
``SourceResume`` is an internal artifact wired straight into the
materials router, ``UserDocument`` is the library the user actually
sees: uploads, profile imports, and "save to my library" promotions
from generated drafts all land here.

The materials router doesn't need to learn a new type --
:func:`to_source_resume_view` adapts a ``UserDocument`` row into the
existing :class:`SourceResumeView` the router already consumes.

Storage layout (mirrors D013 / source_resume.py):

    data/user_documents/<tenant>/<document_type>/<checksum><suffix>

All paths in the DB are stored relative to ``PROJECT_ROOT`` so we
never leak host paths across the API boundary.
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
from src.core.models import UserDocument
from src.tasks.context import current_tenant_id

logger = logging.getLogger(__name__)

_STORAGE_ROOT = PROJECT_ROOT / "data" / "user_documents"

_SUPPORTED_DOCUMENT_TYPES = ("resume", "cover_letter")
_SUPPORTED_SOURCE_TYPES = ("docx", "latex", "pdf", "txt")
_SUPPORTED_ORIGINS = ("uploaded", "profile_import", "generated_promoted")

_EXT_TO_SOURCE_TYPE = {
    ".docx": "docx",
    ".tex": "latex",
    ".pdf": "pdf",
    ".txt": "txt",
}


class UserDocumentError(Exception):
    """Raised on invalid input (bad type, bad bytes)."""


@dataclass(frozen=True)
class IngestResult:
    row_id: Any
    document_type: str
    source_type: str
    editable: bool
    origin: str
    display_name: str
    checksum: str
    storage_path: str  # relative to PROJECT_ROOT
    size_bytes: int
    already_existed: bool


def detect_source_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in _EXT_TO_SOURCE_TYPE:
        raise UserDocumentError(
            f"unsupported file type {suffix!r}; expected one of "
            f"{tuple(_EXT_TO_SOURCE_TYPE)}"
        )
    return _EXT_TO_SOURCE_TYPE[suffix]


def compute_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_document_type(value: str) -> str:
    if value not in _SUPPORTED_DOCUMENT_TYPES:
        raise UserDocumentError(
            f"unsupported document_type {value!r}; expected one of "
            f"{_SUPPORTED_DOCUMENT_TYPES}"
        )
    return value


def validate_origin(value: str) -> str:
    if value not in _SUPPORTED_ORIGINS:
        raise UserDocumentError(
            f"unsupported origin {value!r}; expected one of "
            f"{_SUPPORTED_ORIGINS}"
        )
    return value


def ingest(
    session: Session,
    *,
    filename: str,
    data: bytes,
    document_type: str,
    display_name: str | None = None,
    origin: str = "uploaded",
    notes: str | None = None,
    tenant_id: str | None = None,
    source_application_id: Any | None = None,
    source_job_snapshot_id: Any | None = None,
) -> IngestResult:
    """Validate, store, extract structure, persist. Caller commits.

    Idempotent on (tenant_id, document_type, checksum): re-uploading
    the same file as the same type returns the existing row with
    ``already_existed=True`` rather than failing or duplicating bytes
    on disk.
    """
    if not filename:
        raise UserDocumentError("filename is required")
    if not data:
        raise UserDocumentError("uploaded bytes are empty")

    document_type = validate_document_type(document_type)
    origin = validate_origin(origin)
    source_type = detect_source_type(filename)
    editable = source_type != "pdf"  # PDF stays read-only per D024.
    checksum = compute_checksum(data)
    tenant = tenant_id or current_tenant_id()
    label = (display_name or Path(filename).stem or "Untitled").strip()
    if not label:
        label = "Untitled"
    if len(label) > 200:
        label = label[:200]

    existing = session.execute(
        select(UserDocument)
        .where(UserDocument.tenant_id == tenant)
        .where(UserDocument.document_type == document_type)
        .where(UserDocument.checksum == checksum)
    ).scalar_one_or_none()
    if existing is not None:
        return IngestResult(
            row_id=existing.id,
            document_type=existing.document_type,
            source_type=existing.source_type,
            editable=existing.editable,
            origin=existing.origin,
            display_name=existing.display_name,
            checksum=existing.checksum,
            storage_path=existing.storage_path,
            size_bytes=existing.size_bytes,
            already_existed=True,
        )

    storage_path = _store(tenant, document_type, checksum, filename, data)
    structure = _extract_structure(source_type, data, storage_path)

    row = UserDocument(
        tenant_id=tenant,
        document_type=document_type,
        source_type=source_type,
        editable=editable,
        origin=origin,
        display_name=label,
        original_filename=Path(filename).name,
        checksum=checksum,
        storage_path=str(storage_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        extracted_structure=structure,
        size_bytes=len(data),
        notes=notes,
        source_application_id=source_application_id,
        source_job_snapshot_id=source_job_snapshot_id,
    )
    session.add(row)
    session.flush()

    return IngestResult(
        row_id=row.id,
        document_type=document_type,
        source_type=source_type,
        editable=editable,
        origin=origin,
        display_name=label,
        checksum=checksum,
        storage_path=row.storage_path,
        size_bytes=len(data),
        already_existed=False,
    )


def list_documents(
    session: Session,
    *,
    tenant_id: str | None = None,
    document_type: str | None = None,
) -> list[UserDocument]:
    """List the library, newest first. Optionally filter by type."""
    tenant = tenant_id or current_tenant_id()
    stmt = (
        select(UserDocument)
        .where(UserDocument.tenant_id == tenant)
        .order_by(UserDocument.created_at.desc())
    )
    if document_type:
        stmt = stmt.where(UserDocument.document_type == document_type)
    return list(session.execute(stmt).scalars())


def get_document(
    session: Session,
    document_id: Any,
    *,
    tenant_id: str | None = None,
) -> UserDocument | None:
    tenant = tenant_id or current_tenant_id()
    row = session.get(UserDocument, document_id)
    if row is None or row.tenant_id != tenant:
        return None
    return row


def update_display_name(
    session: Session,
    row: UserDocument,
    *,
    display_name: str | None = None,
    notes: str | None = None,
) -> UserDocument:
    if display_name is not None:
        clean = display_name.strip()
        if not clean:
            raise UserDocumentError("display_name cannot be empty")
        row.display_name = clean[:200]
    if notes is not None:
        row.notes = notes.strip() or None
    session.flush()
    return row


def delete(session: Session, row: UserDocument) -> None:
    """Remove row + its on-disk file. Caller commits.

    Idempotent on the file: if the bytes are missing we log and move
    on so a corrupt FS state cannot block library cleanup.
    """
    try:
        path = resolve_storage_path(row)
        if path.exists():
            path.unlink()
    except Exception:  # noqa: BLE001
        logger.exception("user-document file delete failed for %s", row.id)
    session.delete(row)


def resolve_storage_path(row: UserDocument) -> Path:
    rel = (row.storage_path or "").replace("\\", "/").lstrip("/")
    target = (PROJECT_ROOT / rel).resolve()
    storage_root = _STORAGE_ROOT.resolve()
    if storage_root not in target.parents and target != storage_root:
        raise UserDocumentError(
            f"resolved document path {target} escapes storage root {storage_root}"
        )
    return target


def to_source_resume_view(row: UserDocument):
    """Adapter: feed the existing materials router from a UserDocument.

    The router only needs ``id``, ``source_type``, ``editable``, and
    an absolute path. ``SourceResumeView.source_type`` is typed as a
    Literal of docx/latex/pdf — a ``txt`` cover-letter base is not a
    valid patching target, so the caller should route those through
    ``generate_from_template`` instead before calling this adapter.

    The import is local so callers that only need ``list_documents``
    don't have to fault in the materials router (which transitively
    pulls Celery).
    """
    from src.generation.materials_router import SourceResumeView

    if row.source_type not in ("docx", "latex", "pdf"):
        raise UserDocumentError(
            f"cannot adapt source_type {row.source_type!r} to the patch_existing "
            "router path; route through generate_from_template instead"
        )
    return SourceResumeView(
        id=row.id,
        source_type=row.source_type,  # type: ignore[arg-type]
        editable=bool(row.editable),
        absolute_path=resolve_storage_path(row),
    )


# ---- Internal helpers ------------------------------------------------


def _store(
    tenant: str,
    document_type: str,
    checksum: str,
    filename: str,
    data: bytes,
) -> Path:
    safe_tenant = re.sub(r"[^A-Za-z0-9_.-]", "_", tenant or "default")
    dest_dir = _STORAGE_ROOT / safe_tenant / document_type
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()
    dest = dest_dir / f"{checksum}{suffix}"
    if not dest.exists():
        dest.write_bytes(data)
    return dest


def _extract_structure(source_type: str, data: bytes, path: Path) -> dict[str, Any]:
    """Mirror src.generation.source_resume._extract_structure for the
    types the router needs. ``txt`` cover-letter bases don't carry a
    structure index — they're consumed verbatim by the patcher."""
    try:
        if source_type == "docx":
            from src.generation.source_resume import _extract_docx_structure

            return _extract_docx_structure(path)
        if source_type == "latex":
            from src.generation.source_resume import _extract_latex_structure

            return _extract_latex_structure(data)
        if source_type == "pdf":
            from src.generation.source_resume import _extract_pdf_headings

            return _extract_pdf_headings(path)
        if source_type == "txt":
            text = data.decode("utf-8", errors="replace")
            return {"format": "txt", "char_count": len(text)}
    except Exception:  # noqa: BLE001
        logger.exception("structure extraction failed for %s", source_type)
    return {}


def shutil_copy(src: Path, dst: Path) -> None:  # pragma: no cover -- thin wrapper
    shutil.copy2(src, dst)


__all__ = [
    "IngestResult",
    "UserDocumentError",
    "compute_checksum",
    "delete",
    "detect_source_type",
    "get_document",
    "ingest",
    "list_documents",
    "resolve_storage_path",
    "to_source_resume_view",
    "update_display_name",
    "validate_document_type",
    "validate_origin",
]
