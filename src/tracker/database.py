"""Application tracking database operations.

Bridges the in-memory state machine to persistent Application records.
Handles creating, updating, and querying application records.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from src.core.models import Application, Job
from src.core.state_machine import AppStatus, ApplicationState

logger = logging.getLogger("autoapply.tracker.database")


def create_application(
    session: Session,
    job_id: uuid.UUID,
    match_score: float | None = None,
    resume_version: str | None = None,
    cover_letter_version: str | None = None,
) -> Application:
    """Create a new application record in DISCOVERED state."""
    app = Application(
        job_id=job_id,
        status=AppStatus.DISCOVERED,
        match_score=match_score,
        resume_version=resume_version,
        cover_letter_version=cover_letter_version,
    )
    session.add(app)
    session.flush()
    logger.info("Created application %s for job %s", app.id, job_id)
    return app


def sync_state_to_db(
    session: Session,
    app_id: uuid.UUID,
    state: ApplicationState,
    result: dict[str, Any] | None = None,
) -> Application:
    """Update an Application record from the in-memory state machine.

    Call this after the execution layer completes (or fails) to persist
    the final state, audit history, and results.
    """
    app = session.get(Application, app_id)
    if app is None:
        raise ValueError(f"Application {app_id} not found")

    app.status = str(state.status)
    app.state_history = state.history
    app.error_log = state.metadata.get("error", app.error_log)

    if result:
        app.fields_filled = result.get("fields_filled", app.fields_filled)
        app.fields_total = result.get("fields_total", app.fields_total)
        app.files_uploaded = result.get("files_uploaded", app.files_uploaded)
        app.qa_responses = result.get("qa_responses", app.qa_responses)
        app.screenshot_paths = result.get("screenshot_paths", app.screenshot_paths)

    if state.status == AppStatus.SUBMITTED and app.submitted_at is None:
        app.submitted_at = datetime.now(timezone.utc)

    session.flush()
    logger.info("Synced application %s -> %s", app_id, state.status)
    return app


def update_outcome(
    session: Session,
    app_id: uuid.UUID,
    outcome: str,
) -> Application:
    """Record an application outcome (rejected/oa/interview/offer).

    Args:
        session: DB session.
        app_id: Application UUID.
        outcome: One of: pending, rejected, oa, interview, offer.
    """
    valid_outcomes = {"pending", "rejected", "oa", "interview", "offer"}
    if outcome not in valid_outcomes:
        raise ValueError(f"Invalid outcome '{outcome}', must be one of {valid_outcomes}")

    app = session.get(Application, app_id)
    if app is None:
        raise ValueError(f"Application {app_id} not found")

    app.outcome = outcome
    app.outcome_updated_at = datetime.now(timezone.utc)
    session.flush()
    logger.info("Updated application %s outcome -> %s", app_id, outcome)
    return app


def get_application(session: Session, app_id: uuid.UUID) -> Application | None:
    """Retrieve a single application by ID."""
    return session.get(Application, app_id)


def get_applications(
    session: Session,
    status: str | None = None,
    outcome: str | None = None,
    company: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Application]:
    """Query applications with optional filters.

    Returns applications ordered by most recently updated.
    """
    stmt = select(Application).order_by(Application.updated_at.desc())

    if status:
        stmt = stmt.where(Application.status == status)
    if outcome:
        stmt = stmt.where(Application.outcome == outcome)
    if company:
        stmt = stmt.join(Job, Application.job_id == Job.id).where(
            Job.company.ilike(f"%{company}%")
        )

    stmt = stmt.limit(limit).offset(offset)
    return list(session.execute(stmt).scalars().all())


def get_application_with_job(
    session: Session,
    app_id: uuid.UUID,
) -> tuple[Application, Job] | None:
    """Retrieve an application with its associated job."""
    stmt = (
        select(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .where(Application.id == app_id)
    )
    row = session.execute(stmt).first()
    if row is None:
        return None
    return row.tuple()


def get_applications_with_jobs(
    session: Session,
    status: str | None = None,
    outcome: str | None = None,
    company: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[tuple[Application, Job]]:
    """Query applications with jobs in a single joined query.

    Returns list of (Application, Job) tuples, ordered by most recently updated.
    """
    stmt = (
        select(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .order_by(Application.updated_at.desc())
    )

    if status:
        stmt = stmt.where(Application.status == status)
    if outcome:
        stmt = stmt.where(Application.outcome == outcome)
    if company:
        stmt = stmt.where(Job.company.ilike(f"%{company}%"))

    stmt = stmt.limit(limit).offset(offset)
    return [row.tuple() for row in session.execute(stmt).all()]


def get_application_counts(session: Session) -> dict[str, int]:
    """Get counts of applications by status."""
    stmt = (
        select(Application.status, func.count())
        .group_by(Application.status)
    )
    rows = session.execute(stmt).all()
    return {status: count for status, count in rows}


def get_outcome_counts(session: Session) -> dict[str, int]:
    """Get counts of applications by outcome (only submitted apps)."""
    stmt = (
        select(Application.outcome, func.count())
        .where(Application.status == AppStatus.SUBMITTED)
        .group_by(Application.outcome)
    )
    rows = session.execute(stmt).all()
    return {outcome or "pending": count for outcome, count in rows}
