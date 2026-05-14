"""Phase 13.7: application-layer adapter for the Job Index web surface.

Pure functions consumed by the FastAPI routes. The web layer should
never reach into ``src/jobs/*`` directly so the route handlers stay
focused on shape conversion and HTTP semantics. Each helper opens its
own short-lived SQLAlchemy session so a slow web request can't pin a
connection across handlers.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import ProgrammingError

from src.core.config import load_config
from src.jobs.freshness import FreshnessContext, should_refresh
from src.jobs.normalize import normalize_search_key, search_query_fingerprint
from src.jobs.store import JobIndexStore

logger = logging.getLogger("autoapply.application.job_index")


def _session():
    from src.core.database import get_session_factory  # noqa: PLC0415

    return get_session_factory(load_config())()


def get_search_freshness(
    *,
    source: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Return freshness metadata for a search condition.

    Used by the Jobs page to render "Last updated 18h ago" and to
    decide whether the [Refresh] button should be primary or ghost.
    Returns ``{"known": False}`` if the search has never been indexed
    so the UI can fall back to its current behaviour without errors.
    """
    fingerprint = search_query_fingerprint(params, source=source)
    normalized = normalize_search_key(params, source=source)
    try:
        with _session() as session:
            store = JobIndexStore(session)
            query = store.find_query(source, fingerprint)
            if query is None:
                return {
                    "known": False,
                    "fingerprint": fingerprint,
                    "normalized_key": normalized,
                }

            now = datetime.now(UTC)
            age_hours = (
                (now - query.last_success_at).total_seconds() / 3600.0
                if query.last_success_at is not None
                else None
            )
            return {
                "known": True,
                "fingerprint": fingerprint,
                "normalized_key": normalized,
                "status": query.status,
                "last_run_at": query.last_run_at.isoformat() if query.last_run_at else None,
                "last_success_at": (
                    query.last_success_at.isoformat() if query.last_success_at else None
                ),
                "last_error": query.last_error,
                "result_count": query.result_count,
                "age_hours": age_hours,
            }
    except ProgrammingError as exc:
        # Migration hasn't been run yet -- the search_queries table
        # doesn't exist. Surface a graceful "unknown" so the frontend
        # keeps working until the operator runs ``autoapply migrate``.
        logger.warning("Job Index freshness lookup failed (migration not applied?): %s", exc)
        return {
            "known": False,
            "fingerprint": fingerprint,
            "normalized_key": normalized,
            "warning": "job index tables not present; run autoapply migrate",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Job Index freshness lookup failed: %s", exc, exc_info=True)
        return {
            "known": False,
            "fingerprint": fingerprint,
            "normalized_key": normalized,
            "warning": "freshness lookup failed; see server logs",
        }


def enqueue_search_refresh(
    *,
    source: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Enqueue a high-priority refresh task for a search condition.

    The Phase 14 scheduler will pick this up; for now the row sits in
    ``refresh_tasks`` waiting for the worker. The route returns the
    task id so the UI can poll status (Phase 17 will hook the queue).
    """
    fingerprint = search_query_fingerprint(params, source=source)
    normalized = normalize_search_key(params, source=source)
    try:
        with _session() as session, session.begin():
            store = JobIndexStore(session)
            # Ensure the query row exists so the task has something to
            # refresh; this is a no-op if the user has already searched.
            query = store.upsert_query(
                source=source,
                fingerprint=fingerprint,
                raw_params=normalized,
                max_pages=None,
            )
            task = store.enqueue_refresh(
                kind="search.refresh",
                target_id=query.id,
                priority="high",
                payload={"source": source, "fingerprint": fingerprint},
            )
            return {
                "ok": True,
                "task_id": str(task.id),
                "query_id": str(query.id),
                "fingerprint": fingerprint,
            }
    except ProgrammingError as exc:
        logger.warning("Job Index refresh enqueue failed (migration not applied?): %s", exc)
        return {
            "ok": False,
            "error": "job index tables not present; run autoapply migrate",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Job Index refresh enqueue failed: %s", exc, exc_info=True)
        return {"ok": False, "error": str(exc)}


def posting_freshness(
    *,
    posting_id: str,
    context: FreshnessContext = "search_display",
) -> dict[str, Any]:
    """Return a freshness verdict for a single posting."""
    try:
        with _session() as session:
            store = JobIndexStore(session)
            from uuid import UUID  # noqa: PLC0415

            posting = store.get_posting(UUID(posting_id))
            if posting is None:
                return {"known": False}
            verdict = should_refresh(posting, context=context)
            return {
                "known": True,
                "state": posting.state,
                "last_checked_at": (
                    posting.last_checked_at.isoformat() if posting.last_checked_at else None
                ),
                "should_refresh": verdict.should_refresh,
                "reason": verdict.reason,
                "age_hours": verdict.age_hours,
                "budget_hours": verdict.budget_hours,
            }
    except ProgrammingError:
        return {"known": False, "warning": "job index tables not present"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("posting freshness lookup failed: %s", exc, exc_info=True)
        return {"known": False, "error": str(exc)}
