"""Phase 17.8: regenerate materials for an existing application.

Companion to :func:`src.application.tracking.submit_paused_application`
and :func:`src.application.tracking.discard_paused_application`. The
user is in /review staring at a paused application whose AI-drafted
materials don't look right. They want to replace just the resume (or
just the cover letter) without throwing the whole application away.

This module:

1. Loads the Application + its Job from the DB.
2. Hands the existing per-job generation pipeline the same payload it
   would have received from the Jobs page, plus the requested
   strategy / template / source_document overrides.
3. Swaps the resulting artifact path into ``Application.resume_version``
   or ``Application.cover_letter_version`` and appends a state_history
   entry so the audit trail captures the swap.

The application is *not* transitioned out of REVIEW_REQUIRED -- the
operator still needs to approve the new draft from the kanban.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

logger = logging.getLogger("autoapply.application.regenerate")

MATERIAL_TYPE_TO_DOCUMENT_TYPE = {
    "resume_docx": "resume",
    "resume_pdf": "resume",
    "resume_tex": "resume",
    "cover_letter_docx": "cover_letter",
    "cover_letter_pdf": "cover_letter",
    "cover_letter_tex": "cover_letter",
    "cover_letter_txt": "cover_letter",
}


async def regenerate_application_material(
    *,
    application_id: UUID,
    material_type: str,
    strategy: str | None = None,
    template_id: str | None = None,
    source_document_id: str | None = None,
) -> dict[str, Any]:
    document_type = MATERIAL_TYPE_TO_DOCUMENT_TYPE.get(material_type)
    if document_type is None:
        return {
            "ok": False,
            "error": f"Unsupported material_type {material_type!r}.",
            "error_code": "invalid_material_type",
        }

    from src.application.jobs import generate_material_for_job, serialize_job
    from src.core.config import load_config
    from src.core.database import get_session_factory

    try:
        session_factory = get_session_factory(load_config())
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"Database not available: {exc}",
            "error_code": "database_unavailable",
        }

    try:
        with session_factory() as session:
            from src.core.models import Application, Job

            app = session.get(Application, application_id)
            if app is None:
                return {
                    "ok": False,
                    "error": "Application not found.",
                    "error_code": "application_not_found",
                }
            job = session.get(Job, app.job_id) if app.job_id else None
            if job is None:
                return {
                    "ok": False,
                    "error": "Application's job is missing.",
                    "error_code": "job_not_found",
                }

            from src.application.jobs import _job_to_raw_job  # type: ignore[attr-defined]

            raw_job = _job_to_raw_job(job)
            job_payload = serialize_job(raw_job)
    except Exception as exc:  # noqa: BLE001
        logger.exception("regenerate: failed to load application or job")
        return {
            "ok": False,
            "error": f"Failed to load application: {exc}",
            "error_code": "load_failed",
        }

    result = await generate_material_for_job(
        job_payload=job_payload,
        material_type=material_type,
        use_llm=False,
        template_id=template_id,
        profile_id=None,
        strategy=strategy,
        source_document_id=source_document_id,
    )
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error") or "Generation failed.",
            "error_code": result.get("error_code") or "generation_failed",
            "strategy_notes": result.get("strategy_notes") or [],
        }

    new_artifact_path = (result.get("artifact") or {}).get("path") if isinstance(
        result.get("artifact"), dict
    ) else None
    if not new_artifact_path:
        return {
            "ok": False,
            "error": "Generation produced no artifact path.",
            "error_code": "missing_artifact",
        }

    # Write the new artifact path back onto the application row +
    # leave a state_history breadcrumb.
    try:
        with session_factory() as session:
            from src.core.models import Application

            app = session.get(Application, application_id)
            if app is None:
                return {
                    "ok": False,
                    "error": "Application disappeared mid-regeneration.",
                    "error_code": "application_not_found",
                }
            old_path = (
                app.resume_version if document_type == "resume" else app.cover_letter_version
            )
            if document_type == "resume":
                app.resume_version = new_artifact_path
            else:
                app.cover_letter_version = new_artifact_path

            history = list(app.state_history or [])
            history.append(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "event": "MATERIAL_REGENERATED",
                    "from": str(app.status),
                    "to": str(app.status),
                    "meta": {
                        "material_type": material_type,
                        "document_type": document_type,
                        "old_path": old_path,
                        "new_path": new_artifact_path,
                        "strategy": result.get("strategy"),
                        "strategy_source": result.get("strategy_source"),
                        "source_document_id": result.get("source_document_id"),
                    },
                }
            )
            app.state_history = history
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("regenerate: failed to write new artifact onto application")
        return {
            "ok": False,
            "error": f"Generation succeeded but couldn't update the application: {exc}",
            "error_code": "application_update_failed",
        }

    return {
        "ok": True,
        "status": "regenerated",
        "message": "Materials regenerated.",
        "material_type": material_type,
        "document_type": document_type,
        "artifact": result.get("artifact"),
        "artifacts": result.get("artifacts"),
        "strategy": result.get("strategy"),
        "strategy_notes": result.get("strategy_notes") or [],
        "source_document_id": result.get("source_document_id"),
    }


__all__ = ["regenerate_application_material"]
