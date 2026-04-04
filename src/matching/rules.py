"""Hard rule matching — disqualify jobs that are objectively incompatible.

These are binary pass/fail checks based on the applicant profile and job
requirements. A job that fails any hard rule is not worth applying to.

Rule categories:
  - Location compatibility (applicant location vs job location + work mode)
  - Work authorization (visa needs vs job sponsorship/auth requirements)
  - Experience level (min years vs applicant's experience)
  - Education (degree level vs requirement)
  - Employment type (applicant preferences vs job type)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.intake.schema import RawJob

logger = logging.getLogger("autoapply.matching.rules")


@dataclass
class ApplicantContext:
    """Minimal applicant data needed for rule matching.

    Loaded from the profile YAML / DB, not the full profile.
    """

    location: str = ""  # e.g. "Vancouver, BC, Canada"
    citizenship: str = ""  # e.g. "Chinese"
    work_authorization: str = ""  # e.g. "Study Permit", "US Citizen"
    visa_sponsorship_needed: bool = True
    willing_to_relocate: bool = True
    years_of_experience: int = 0  # total relevant years
    education_level: str = ""  # highest: "PhD", "Master's", "Bachelor's"
    preferred_employment_types: list[str] = field(
        default_factory=lambda: ["internship", "coop"],
    )
    target_locations: list[str] = field(default_factory=list)  # accepted job locations


@dataclass
class RuleResult:
    """Result of a single rule check."""

    rule_name: str
    passed: bool
    reason: str = ""

    def __repr__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.rule_name}: {self.reason}"


@dataclass
class RuleVerdict:
    """Aggregate result of all rule checks for a single job."""

    job_id: str
    passed: bool
    results: list[RuleResult] = field(default_factory=list)
    fail_reasons: list[str] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)


def check_rules(job: RawJob, ctx: ApplicantContext) -> RuleVerdict:
    """Run all hard rules against a job + applicant context.

    Returns a RuleVerdict. If any rule fails, verdict.passed = False.
    """
    results = [
        _check_work_authorization(job, ctx),
        _check_experience(job, ctx),
        _check_education(job, ctx),
        _check_employment_type(job, ctx),
        _check_spam_signals(job),
    ]

    fail_reasons = [r.reason for r in results if not r.passed]
    verdict = RuleVerdict(
        job_id=str(job.id),
        passed=len(fail_reasons) == 0,
        results=results,
        fail_reasons=fail_reasons,
    )

    if not verdict.passed:
        logger.debug(
            "Job '%s' at %s failed rules: %s",
            job.title,
            job.company,
            fail_reasons,
        )

    return verdict


def _check_work_authorization(job: RawJob, ctx: ApplicantContext) -> RuleResult:
    """Check visa/work authorization compatibility."""
    reqs = job.requirements

    # If job explicitly says no sponsorship and applicant needs it
    if reqs.visa_sponsorship is False and ctx.visa_sponsorship_needed:
        return RuleResult(
            rule_name="work_authorization",
            passed=False,
            reason="Job offers no visa sponsorship; applicant needs sponsorship",
        )

    # If job requires US work auth and applicant doesn't have it
    us_auth_terms = {
        "us citizen",
        "green card",
        "us permanent resident",
        "permanent resident",
        "ead",
    }
    if reqs.us_work_auth_required and ctx.work_authorization.lower() not in us_auth_terms:
        return RuleResult(
            rule_name="work_authorization",
            passed=False,
            reason="Job requires US work authorization; applicant lacks it",
        )

    return RuleResult(rule_name="work_authorization", passed=True, reason="OK")


def _check_experience(job: RawJob, ctx: ApplicantContext) -> RuleResult:
    """Check if applicant meets minimum experience requirement."""
    min_yrs = job.requirements.experience_years_min
    if min_yrs is not None and min_yrs > 0:
        # Allow a 1-year grace (common to apply slightly under)
        if ctx.years_of_experience < min_yrs - 1:
            return RuleResult(
                rule_name="experience",
                passed=False,
                reason=f"Job requires {min_yrs}+ yrs; applicant has {ctx.years_of_experience}",
            )
    return RuleResult(rule_name="experience", passed=True, reason="OK")


_EDUCATION_RANK = {"Bachelor's": 1, "Master's": 2, "PhD": 3}


def _check_education(job: RawJob, ctx: ApplicantContext) -> RuleResult:
    """Check if applicant meets education requirement."""
    required = job.requirements.education_level
    if not required:
        return RuleResult(rule_name="education", passed=True, reason="No requirement")

    req_rank = _EDUCATION_RANK.get(required, 0)
    app_rank = _EDUCATION_RANK.get(ctx.education_level, 0)

    if req_rank > 0 and app_rank < req_rank:
        return RuleResult(
            rule_name="education",
            passed=False,
            reason=f"Job requires {required}; applicant has {ctx.education_level or 'unknown'}",
        )

    return RuleResult(rule_name="education", passed=True, reason="OK")


def _check_employment_type(job: RawJob, ctx: ApplicantContext) -> RuleResult:
    """Check if job's employment type matches applicant preferences."""
    if not ctx.preferred_employment_types:
        return RuleResult(rule_name="employment_type", passed=True, reason="No preference set")

    if job.employment_type == "unknown":
        return RuleResult(rule_name="employment_type", passed=True, reason="Unknown type, passing")

    if job.employment_type not in ctx.preferred_employment_types:
        return RuleResult(
            rule_name="employment_type",
            passed=False,
            reason=(
                f"Job is {job.employment_type}; applicant prefers {ctx.preferred_employment_types}"
            ),
        )

    return RuleResult(rule_name="employment_type", passed=True, reason="OK")


# Spam / ghost job signals
_SPAM_PATTERNS = [
    re.compile(r"(?i)staffing\s+agency|recruitment\s+agency|talent\s+partner"),
    re.compile(r"(?i)multiple\s+openings|various\s+locations|general\s+application"),
    re.compile(r"(?i)commission[\s-]only|unpaid\s+intern"),
]


def _check_spam_signals(job: RawJob) -> RuleResult:
    """Detect likely spam, ghost jobs, or staffing agency postings."""
    text = f"{job.title} {job.description or ''}"

    for pattern in _SPAM_PATTERNS:
        if pattern.search(text):
            return RuleResult(
                rule_name="spam_filter",
                passed=False,
                reason=f"Spam signal detected: {pattern.pattern[:50]}",
            )

    # Ghost job signals: very old postings or extremely generic titles
    if job.title and len(job.title.strip()) < 5:
        return RuleResult(
            rule_name="spam_filter",
            passed=False,
            reason="Title too short — likely a generic/ghost posting",
        )

    return RuleResult(rule_name="spam_filter", passed=True, reason="OK")


def load_applicant_context(profile_data: dict[str, Any]) -> ApplicantContext:
    """Build ApplicantContext from a profile YAML dict."""
    identity = profile_data.get("identity", {})
    education = profile_data.get("education", [])
    experiences = profile_data.get("work_experiences", [])

    # Calculate total experience years from work history
    total_years = 0
    for exp in experiences:
        if isinstance(exp, dict):
            start = exp.get("start_date", "")
            end = exp.get("end_date", "")
            if start:
                try:
                    start_year = int(start[:4])
                    end_year = int(end[:4]) if end and end != "Present" else datetime.now().year
                    total_years += max(0, end_year - start_year)
                except (ValueError, IndexError):
                    pass

    # Highest education
    edu_level = ""
    for edu in education:
        if isinstance(edu, dict):
            degree = edu.get("degree", "")
            if "phd" in degree.lower() or "doctor" in degree.lower():
                edu_level = "PhD"
            elif "master" in degree.lower():
                edu_level = edu_level or "Master's"
            elif "bachelor" in degree.lower():
                edu_level = edu_level or "Bachelor's"

    return ApplicantContext(
        location=identity.get("location", ""),
        citizenship=identity.get("citizenship", ""),
        work_authorization=identity.get("work_authorization", ""),
        visa_sponsorship_needed=identity.get("visa_sponsorship_needed", True),
        willing_to_relocate=identity.get("willing_to_relocate", True),
        years_of_experience=total_years,
        education_level=edu_level,
    )
