"""Structured document IR for generated application materials.

The LLM can help choose and rewrite content, but renderers should consume a
validated intermediate representation instead of free-form prose.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ResumeBullet(BaseModel):
    """A grounded resume bullet with provenance metadata."""

    text: str
    source_id: str
    source_type: Literal["experience", "project", "manual"] = "manual"
    source_entity: str
    original_text: str | None = None
    tags: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    score: float = 0.0
    source_confidence: Literal["user_verified", "imported", "generated", "unknown"] = (
        "user_verified"
    )


class BulletRewriteResult(BaseModel):
    """Structured LLM output for a rewritten resume bullet."""

    rewritten_bullet: str
    used_skills: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    changed_claims: list[str] = Field(default_factory=list)


class ResumeItem(BaseModel):
    """A section item such as a job, project, or education entry."""

    source_id: str
    source_type: Literal["experience", "project", "education", "manual"]
    name: str
    title: str = ""
    organization: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    meta: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    bullets: list[ResumeBullet] = Field(default_factory=list)


class ResumeDocument(BaseModel):
    """Renderer-agnostic representation of a tailored resume."""

    document_type: Literal["resume"] = "resume"
    template_id: str = "ats_single_column_v1"
    target_role: str
    company: str
    header: dict[str, Any] = Field(default_factory=dict)
    summary: list[str] = Field(default_factory=list)
    skills: dict[str, list[str]] = Field(default_factory=dict)
    education: list[dict[str, Any]] = Field(default_factory=list)
    experiences: list[ResumeItem] = Field(default_factory=list)
    projects: list[ResumeItem] = Field(default_factory=list)
    section_order: list[str] = Field(
        default_factory=lambda: ["header", "education", "skills", "experience", "projects"]
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class CoverLetterParagraph(BaseModel):
    """A grounded paragraph in a cover letter."""

    type: Literal["opening", "experience_evidence", "company_fit", "closing", "other"]
    text: str
    source_ids: list[str] = Field(default_factory=list)


class CoverLetterDocument(BaseModel):
    """Renderer-agnostic representation of a cover letter."""

    document_type: Literal["cover_letter"] = "cover_letter"
    template_id: str = "cover_letter_classic_v1"
    recipient: dict[str, Any] = Field(default_factory=dict)
    applicant: dict[str, Any] = Field(default_factory=dict)
    paragraphs: list[CoverLetterParagraph] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidationIssue(BaseModel):
    """A validation finding for a generated document."""

    type: str
    severity: Literal["info", "warning", "error"] = "warning"
    message: str
    section: str | None = None
    item: str | None = None
    source_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    """Validation result consumed by generation callers and review UI."""

    ok: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
