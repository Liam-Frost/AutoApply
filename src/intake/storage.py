"""Job intake storage — persist RawJob objects to the database with deduplication."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.core.models import Job
from src.intake.schema import RawJob

logger = logging.getLogger("autoapply.intake.storage")


def upsert_jobs(session: Session, jobs: list[RawJob]) -> tuple[int, int]:
    """Persist jobs to the database, skipping duplicates.

    Deduplication key: source + company (normalized) + source_id.
    If a job already exists (same key), it is skipped.

    Returns:
        (inserted_count, skipped_count)
    """
    if not jobs:
        return 0, 0

    # Build a set of existing dedup keys to avoid re-querying per job
    existing_keys = _load_existing_keys(session, jobs)

    inserted = 0
    skipped = 0

    for raw in jobs:
        key = raw.dedup_key()
        if key in existing_keys:
            skipped += 1
            continue

        db_job = Job(
            id=raw.id,
            source=raw.source,
            company=raw.company,
            title=raw.title,
            location=raw.location,
            employment_type=raw.employment_type,
            seniority=raw.seniority,
            description=raw.description,
            requirements=raw.requirements.model_dump(),
            visa_sponsorship=raw.requirements.visa_sponsorship,
            ats_type=raw.ats_type,
            application_url=raw.application_url,
            raw_data={**raw.raw_data, "_source_id": raw.source_id},
            discovered_at=raw.discovered_at,
            expires_at=raw.expires_at,
        )
        session.add(db_job)
        existing_keys.add(key)
        inserted += 1

    session.commit()
    logger.info("Upserted jobs: %d new, %d skipped", inserted, skipped)
    return inserted, skipped


def _load_existing_keys(session: Session, jobs: list[RawJob]) -> set[str]:
    """Load dedup keys for jobs that might already be in the DB."""
    companies = {j.company.lower() for j in jobs}
    sources = {j.source for j in jobs}

    existing = (
        session.query(Job.source, Job.company, Job.raw_data)
        .filter(Job.source.in_(sources))
        .all()
    )

    keys = set()
    for row in existing:
        source_id = (row.raw_data or {}).get("_source_id", "")
        keys.add(f"{row.source}::{row.company.lower()}::{source_id}")

    return keys


def get_recent_jobs(
    session: Session,
    source: str | None = None,
    limit: int = 100,
) -> list[Job]:
    """Get recently discovered jobs, optionally filtered by source."""
    query = session.query(Job).order_by(Job.discovered_at.desc())
    if source:
        query = query.filter(Job.source == source)
    return query.limit(limit).all()


def mark_expired(session: Session, job_id: str) -> None:
    """Mark a job as expired (no longer accepting applications)."""
    session.query(Job).filter(Job.id == job_id).update(
        {"expires_at": datetime.now(timezone.utc)}
    )
    session.commit()
