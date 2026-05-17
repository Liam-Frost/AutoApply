"""Phase 17.8: document library use cases.

Owns the side-effect of ingesting / listing / mutating user-curated
documents. Wraps the storage helper in :mod:`src.documents.user_documents`
with the same return-shape pattern other application/* modules use
(``{"ok": bool, "error_code": str, ...}``) so the FastAPI layer is
purely transport.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from src.core.config import load_config

logger = logging.getLogger("autoapply.application.documents")


def list_documents_data(*, document_type: str | None = None) -> dict[str, Any]:
    """Return the library payload for the UI."""
    try:
        from src.core.database import get_session_factory
        from src.documents.user_documents import list_documents

        session_factory = get_session_factory(load_config())
        with session_factory() as session:
            rows = list_documents(session, document_type=document_type or None)
            return {
                "ok": True,
                "documents": [_serialize(row) for row in rows],
                "document_type": document_type or None,
            }
    except Exception as exc:  # noqa: BLE001
        logger.exception("list_documents_data failed")
        return {
            "ok": False,
            "error": f"Failed to load documents: {exc}",
            "error_code": "documents_load_failed",
            "documents": [],
        }


def upload_document(
    *,
    document_type: str,
    filename: str,
    content: bytes,
    display_name: str | None = None,
    notes: str | None = None,
    origin: str = "uploaded",
    source_application_id: UUID | None = None,
    source_job_snapshot_id: UUID | None = None,
) -> dict[str, Any]:
    try:
        from src.core.database import get_session_factory
        from src.documents.user_documents import (
            UserDocumentError,
            get_document,
            ingest,
        )

        session_factory = get_session_factory(load_config())
        with session_factory() as session:
            try:
                result = ingest(
                    session,
                    filename=filename,
                    data=content,
                    document_type=document_type,
                    display_name=display_name,
                    origin=origin,
                    notes=notes,
                    source_application_id=source_application_id,
                    source_job_snapshot_id=source_job_snapshot_id,
                )
            except UserDocumentError as exc:
                return {
                    "ok": False,
                    "error": str(exc),
                    "error_code": "invalid_document",
                }
            session.commit()
            # Re-fetch so we serialize from a fresh row with server defaults.
            row = get_document(session, result.row_id)
            payload = _serialize(row) if row else None

        return {
            "ok": True,
            "status": "exists" if result.already_existed else "created",
            "message": (
                "Added to your library."
                if not result.already_existed
                else "This file is already in your library."
            ),
            "document": payload,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("upload_document failed")
        return {
            "ok": False,
            "error": f"Failed to add document: {exc}",
            "error_code": "document_upload_failed",
        }


def update_document(
    *,
    document_id: UUID,
    display_name: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    try:
        from src.core.database import get_session_factory
        from src.documents.user_documents import (
            UserDocumentError,
            get_document,
            update_display_name,
        )

        session_factory = get_session_factory(load_config())
        with session_factory() as session:
            row = get_document(session, document_id)
            if row is None:
                return {
                    "ok": False,
                    "error": "Document not found.",
                    "error_code": "document_not_found",
                }
            try:
                update_display_name(
                    session,
                    row,
                    display_name=display_name,
                    notes=notes,
                )
            except UserDocumentError as exc:
                return {
                    "ok": False,
                    "error": str(exc),
                    "error_code": "invalid_document",
                }
            session.commit()
            row = get_document(session, document_id)
            return {
                "ok": True,
                "status": "updated",
                "document": _serialize(row) if row else None,
            }
    except Exception as exc:  # noqa: BLE001
        logger.exception("update_document failed")
        return {
            "ok": False,
            "error": f"Failed to update document: {exc}",
            "error_code": "document_update_failed",
        }


def delete_document(*, document_id: UUID) -> dict[str, Any]:
    try:
        from src.core.database import get_session_factory
        from src.documents.user_documents import delete, get_document

        session_factory = get_session_factory(load_config())
        with session_factory() as session:
            row = get_document(session, document_id)
            if row is None:
                return {
                    "ok": False,
                    "error": "Document not found.",
                    "error_code": "document_not_found",
                }
            display = row.display_name
            delete(session, row)
            session.commit()
            return {
                "ok": True,
                "status": "deleted",
                "message": f"Removed “{display}” from your library.",
            }
    except Exception as exc:  # noqa: BLE001
        logger.exception("delete_document failed")
        return {
            "ok": False,
            "error": f"Failed to delete document: {exc}",
            "error_code": "document_delete_failed",
        }


def resolve_document_for_download(
    *, document_id: UUID
) -> dict[str, Any]:
    """Return the absolute filesystem path + original filename so the
    transport layer can stream the file. Returns ok=False if the row
    or file is missing."""
    try:
        from src.core.database import get_session_factory
        from src.documents.user_documents import get_document, resolve_storage_path

        session_factory = get_session_factory(load_config())
        with session_factory() as session:
            row = get_document(session, document_id)
            if row is None:
                return {
                    "ok": False,
                    "error": "Document not found.",
                    "error_code": "document_not_found",
                }
            path = resolve_storage_path(row)
            if not path.exists():
                return {
                    "ok": False,
                    "error": "Document file is missing on disk.",
                    "error_code": "document_file_missing",
                }
            return {
                "ok": True,
                "path": str(path),
                "filename": row.original_filename,
                "source_type": row.source_type,
            }
    except Exception as exc:  # noqa: BLE001
        logger.exception("resolve_document_for_download failed")
        return {
            "ok": False,
            "error": f"Failed to load document: {exc}",
            "error_code": "document_load_failed",
        }


def promote_artifact_to_library(
    *,
    artifact_path: str,
    document_type: str,
    display_name: str,
    application_id: UUID | None = None,
    job_snapshot_id: UUID | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Copy a generated artifact into the user's library.

    The artifact lives on disk at ``artifact_path`` (relative to
    PROJECT_ROOT, the same shape the existing /api/artifacts/download
    endpoint accepts). We read the bytes and re-ingest under
    ``origin='generated_promoted'`` with provenance pointers back to
    the application that produced it.
    """
    from src.core.config import PROJECT_ROOT

    rel = (artifact_path or "").replace("\\", "/").lstrip("/")
    abs_path = (PROJECT_ROOT / rel).resolve()
    if not abs_path.exists() or not abs_path.is_file():
        return {
            "ok": False,
            "error": "That artifact no longer exists on disk.",
            "error_code": "artifact_missing",
        }
    project_root = PROJECT_ROOT.resolve()
    if project_root not in abs_path.parents:
        return {
            "ok": False,
            "error": "Refusing to read an artifact outside the project root.",
            "error_code": "artifact_outside_root",
        }
    try:
        data = abs_path.read_bytes()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"Failed to read artifact: {exc}",
            "error_code": "artifact_read_failed",
        }

    return upload_document(
        document_type=document_type,
        filename=abs_path.name,
        content=data,
        display_name=display_name,
        notes=notes,
        origin="generated_promoted",
        source_application_id=application_id,
        source_job_snapshot_id=job_snapshot_id,
    )


def _serialize(row) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "document_type": row.document_type,
        "source_type": row.source_type,
        "editable": bool(row.editable),
        "origin": row.origin,
        "display_name": row.display_name,
        "original_filename": row.original_filename,
        "size_bytes": int(row.size_bytes or 0),
        "notes": row.notes,
        "source_application_id": (
            str(row.source_application_id) if row.source_application_id else None
        ),
        "source_job_snapshot_id": (
            str(row.source_job_snapshot_id) if row.source_job_snapshot_id else None
        ),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


__all__ = [
    "delete_document",
    "list_documents_data",
    "promote_artifact_to_library",
    "resolve_document_for_download",
    "update_document",
    "upload_document",
]
