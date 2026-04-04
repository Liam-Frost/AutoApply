"""SQLAlchemy ORM models for all database tables.

Covers: jobs, applications, applicant_profile, bullet_pool, qa_bank.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
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
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", name="fk_applications_job_id"),
        nullable=False,
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
    section: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_embedding = mapped_column(Vector(1536), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class BulletPool(Base):
    __tablename__ = "bullet_pool"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    category: Mapped[str | None] = mapped_column(String(50))
    source_entity: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_embedding = mapped_column(Vector(1536), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    used_count: Mapped[int] = mapped_column(Integer, default=0)


class QABank(Base):
    __tablename__ = "qa_bank"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    question_pattern: Mapped[str | None] = mapped_column(Text)
    question_type: Mapped[str | None] = mapped_column(String(50))
    canonical_answer: Mapped[str | None] = mapped_column(Text)
    variants: Mapped[dict | None] = mapped_column(JSONB)
    confidence: Mapped[str] = mapped_column(String(20), default="high")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
