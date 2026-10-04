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
    dates_inferred: bool = False
    meta: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    bullets: list[ResumeBullet] = Field(default_factory=list)


class CustomSectionEntry(BaseModel):
    """A single line/row inside a free-form resume section.

    Resume schemas that hard-code Experience / Projects / Skills lose
    everything else a candidate actually has on their resume --
    Volunteer Experience, Awards, Affiliations, Interests, Publications,
    Certifications, Languages-spoken, etc. This model is intentionally
    permissive: ``title`` is the visible label (e.g. "President" or an
    award name), the rest are optional supporting fields and the freeform
    ``details`` / ``bullets`` carry whatever else the source document had.
    """

    title: str = ""
    organization: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    # One-line supporting text shown under the title (e.g. award issuer,
    # affiliation level, summary description). Renderers print this as a
    # single grey line; if the source resume only had a one-liner, this
    # is where it lives.
    details: str = ""
    bullets: list[str] = Field(default_factory=list)


class CustomSection(BaseModel):
    """A resume section that the canonical schema does not know about.

    The original resume text decided what to call it ("VOLUNTEER
    EXPERIENCE", "AWARDS & HONORS", "PROFESSIONAL AFFILIATIONS",
    "INTERESTS & ACTIVITIES", ...); we preserve the title verbatim so
    the rendered output keeps the candidate's chosen heading.
    """

    title: str
    entries: list[CustomSectionEntry] = Field(default_factory=list)


class ResumeDocument(BaseModel):
    """Renderer-agnostic representation of a tailored resume."""

    document_type: Literal["resume"] = "resume"
    template_id: str = "ats_single_column_v1"
    target_role: str
    company: str
    header: dict[str, Any] = Field(default_factory=dict)
    # One JD-tailored paragraph grounded in selected evidence.
    skills: dict[str, list[str]] = Field(default_factory=dict)
    summary: str = ""
    education: list[dict[str, Any]] = Field(default_factory=list)
    experiences: list[ResumeItem] = Field(default_factory=list)
    projects: list[ResumeItem] = Field(default_factory=list)
    # Free-form sections that the canonical schema does not enumerate --
    # rendered after the known sections in their natural order unless a
    # ``custom:<title>`` token appears in ``section_order``.
    custom_sections: list[CustomSection] = Field(default_factory=list)
    section_order: list[str] = Field(
        default_factory=lambda: ["header", "education", "skills", "experience", "projects"]
    )
    # Section names (canonical or ``custom:<title>``) after which the
    # renderer inserts a thin horizontal rule. Lets the Fit Planner
    # group visually related blocks ("...projects --- volunteer...") so
    # the page reads as deliberate structure rather than a wall of text.
    dividers_after: list[str] = Field(default_factory=list)
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
