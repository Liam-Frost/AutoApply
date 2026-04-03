"""Unified Job schema.

All ATS scrapers normalize their output to this schema before storage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, field_validator


EmploymentType = Literal["internship", "fulltime", "parttime", "contract", "coop", "unknown"]
SeniorityLevel = Literal["internship", "entry", "mid", "senior", "staff", "unknown"]
ATSType = Literal["greenhouse", "lever", "linkedin", "workday", "company_site", "unknown"]


class JobRequirements(BaseModel):
    """Structured requirements extracted from a JD."""

    must_have_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    education_level: str | None = None          # e.g. "Bachelor's", "Master's"
    experience_years_min: int | None = None
    experience_years_max: int | None = None
    visa_sponsorship: bool | None = None
    us_work_auth_required: bool | None = None   # True = requires US citizen/GC
    relocation_provided: bool | None = None
    remote_ok: bool | None = None


class RawJob(BaseModel):
    """Normalized job posting — output of every scraper."""

    id: UUID = Field(default_factory=uuid4)
    source: ATSType
    source_id: str                              # ATS-native job ID
    company: str
    title: str
    location: str | None = None
    employment_type: EmploymentType = "unknown"
    seniority: SeniorityLevel = "unknown"
    description: str | None = None
    requirements: JobRequirements = Field(default_factory=JobRequirements)
    application_url: str | None = None
    ats_type: ATSType = "unknown"
    raw_data: dict = Field(default_factory=dict)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None

    @field_validator("company", "title", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    def dedup_key(self) -> str:
        """Stable key for deduplication — company + ATS source + source ID."""
        return f"{self.source}::{self.company.lower()}::{self.source_id}"


def classify_employment_type(raw: str) -> EmploymentType:
    """Map free-form employment type strings to the canonical enum."""
    s = raw.lower()
    if any(w in s for w in ("co-op", "coop")):
        return "coop"
    if any(w in s for w in ("intern", "internship")):
        return "internship"
    if "part" in s:
        return "parttime"
    if any(w in s for w in ("contract", "contractor", "freelance")):
        return "contract"
    if "full" in s:
        return "fulltime"
    return "unknown"


def classify_seniority(title: str) -> SeniorityLevel:
    """Infer seniority from the job title."""
    t = title.lower()
    if any(w in t for w in ("intern", "internship", "co-op", "coop", "student")):
        return "internship"
    if any(w in t for w in ("staff", "principal", "distinguished")):
        return "staff"
    if any(w in t for w in ("senior", "sr.", " sr ", "lead")):
        return "senior"
    if any(w in t for w in ("junior", "jr.", " jr ", "associate", "entry", "new grad")):
        return "entry"
    if "mid" in t:
        return "mid"
    return "unknown"
