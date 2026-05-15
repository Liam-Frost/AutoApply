"""SQLAlchemy ORM models for all database tables.

Covers: jobs, applications, applicant_profile, bullet_pool, qa_bank.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


TENANT_DEFAULT = "default"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default=TENANT_DEFAULT)
    source: Mapped[str | None] = mapped_column(String(50))
    source_id: Mapped[str | None] = mapped_column(String(200), index=True)
    company: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    employment_type: Mapped[str | None] = mapped_column(String(50))
    seniority: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    description_embedding = mapped_column(Vector(1536), nullable=True)
    requirements: Mapped[dict | None] = mapped_column(JSONB)
    visa_sponsorship: Mapped[bool | None] = mapped_column(Boolean)
    ats_type: Mapped[str | None] = mapped_column(String(50))
    application_url: Mapped[str | None] = mapped_column(Text)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default=TENANT_DEFAULT)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", name="fk_applications_job_id"),
        nullable=False,
        index=True,
    )
    job_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_snapshots.id", name="fk_applications_job_snapshot"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DISCOVERED")
    match_score: Mapped[float | None] = mapped_column(Float)
    resume_version: Mapped[str | None] = mapped_column(Text)
    cover_letter_version: Mapped[str | None] = mapped_column(Text)
    qa_responses: Mapped[dict | None] = mapped_column(JSONB)
    screenshot_paths: Mapped[dict | None] = mapped_column(JSONB)
    error_log: Mapped[str | None] = mapped_column(Text)
    state_history: Mapped[list | None] = mapped_column(JSONB)  # list[dict] FSM audit trail
    fields_filled: Mapped[int | None] = mapped_column(Integer)
    fields_total: Mapped[int | None] = mapped_column(Integer)
    files_uploaded: Mapped[list | None] = mapped_column(JSONB)  # list[str] uploaded filenames
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(30))  # pending/rejected/oa/interview/offer
    outcome_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApplicantProfile(Base):
    __tablename__ = "applicant_profile"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default=TENANT_DEFAULT)
    section: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_embedding = mapped_column(Vector(1536), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class BulletPool(Base):
    __tablename__ = "bullet_pool"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default=TENANT_DEFAULT)
    category: Mapped[str | None] = mapped_column(String(50))
    source_entity: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_embedding = mapped_column(Vector(1536), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    used_count: Mapped[int] = mapped_column(Integer, default=0)


TENANT_DEFAULT = "default"


class JobPosting(Base):
    """Stable job entity per (tenant, source, source_id). Phase 13."""

    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source", "source_id", name="uq_job_postings_tenant_source"),
        Index("ix_job_postings_tenant_state", "tenant_id", "state"),
        Index("ix_job_postings_company", "tenant_id", "company"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default=TENANT_DEFAULT)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(String(200), nullable=False)
    company: Mapped[str] = mapped_column(String(200), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    latest_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class JobSnapshot(Base):
    """Immutable content-versioned snapshot of a JobPosting. Phase 13."""

    __tablename__ = "job_snapshots"
    __table_args__ = (
        UniqueConstraint("posting_id", "content_hash", name="uq_job_snapshots_posting_hash"),
        Index("ix_job_snapshots_posting_scraped", "posting_id", "scraped_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default=TENANT_DEFAULT)
    posting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_postings.id", name="fk_job_snapshots_posting"),
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    employment_type: Mapped[str | None] = mapped_column(String(50))
    seniority: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[dict | None] = mapped_column(JSONB)
    application_url: Mapped[str | None] = mapped_column(Text)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SearchQuery(Base):
    """Normalized search condition. Phase 13."""

    __tablename__ = "search_queries"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source", "normalized_key", name="uq_search_queries_tenant_key"
        ),
        Index("ix_search_queries_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default=TENANT_DEFAULT)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="fresh")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_pages: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SearchResult(Base):
    """Many-to-many link between SearchQuery and JobPosting. Phase 13."""

    __tablename__ = "search_results"
    __table_args__ = (
        UniqueConstraint("query_id", "posting_id", name="uq_search_results_query_posting"),
        Index("ix_search_results_query", "query_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default=TENANT_DEFAULT)
    query_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("search_queries.id", name="fk_search_results_query", ondelete="CASCADE"),
        nullable=False,
    )
    posting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_postings.id", name="fk_search_results_posting", ondelete="CASCADE"),
        nullable=False,
    )
    rank: Mapped[int | None] = mapped_column(Integer)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RefreshTask(Base):
    """Priority queue row for Phase 14 RefreshTask worker. Phase 13."""

    __tablename__ = "refresh_tasks"
    __table_args__ = (
        Index(
            "ix_refresh_tasks_pending",
            "tenant_id",
            "status",
            "priority",
            "scheduled_for",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default=TENANT_DEFAULT)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="normal")
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskRecord(Base):
    """Durable audit row for a Celery-dispatched task (Phase 14.2).

    Celery's result backend is transient; this is the source of truth.
    Status transitions: ``queued → running → succeeded`` (or
    ``→ failed``); ``running → waiting_human`` parks a task at a HITL
    gate; ``→ cancelled`` is the explicit operator action.
    """

    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_tasks_tenant_idempotency_key"
        ),
        Index("ix_tasks_celery_task_id", "celery_task_id"),
        Index("ix_tasks_tenant_status", "tenant_id", "status", "created_at"),
        Index("ix_tasks_kind", "tenant_id", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default=TENANT_DEFAULT)
    celery_task_id: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    queue: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", name="fk_tasks_parent", ondelete="SET NULL"),
        nullable=True,
    )
    trace_id: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(Text)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class QABank(Base):
    __tablename__ = "qa_bank"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default=TENANT_DEFAULT)
    question_pattern: Mapped[str | None] = mapped_column(Text)
    question_type: Mapped[str | None] = mapped_column(String(50))
    canonical_answer: Mapped[str | None] = mapped_column(Text)
    variants: Mapped[dict | None] = mapped_column(JSONB)
    confidence: Mapped[str] = mapped_column(String(20), default="high")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
