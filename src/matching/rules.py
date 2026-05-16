"""Hard rule matching — disqualify jobs that are objectively incompatible.

These are binary pass/fail checks based on the applicant profile and job
requirements. A job that fails any hard rule is not worth applying to.

Rule categories:
  - Location compatibility (applicant location vs job location + work mode)
  - Work authorization (visa needs vs job sponsorship/auth requirements)
  - Experience level (min years vs applicant's experience)
  - Education (degree level vs requirement)
  - Employment type (applicant preferences vs job type)

Phase 16.1 evolution
--------------------
Per-rule decisions carry structured fields:

* ``rule_id``        -- stable machine-readable identifier
                       (``"work_authorization"``, ``"experience"``,
                       ``"education"``, ``"employment_type"``,
                       ``"spam_filter"``).
* ``rule_name``      -- human-friendly label (existing field).
* ``verdict``        -- ``"pass"`` | ``"fail"`` (we don't emit ``"warn"`` yet
                       from these hard rules, but the literal includes it
                       so 16.2's edge-case agent can emit warnings into
                       the same structure).
* ``reason``         -- short sentence consumed by the UI tooltip.
* ``evidence_excerpt`` -- the JD snippet the rule decided on, or
                       ``None`` when the rule decided from
                       ``ApplicantContext`` alone (e.g. applicant lacks
                       US work authorization -- there is no JD excerpt
                       to point at). Excerpts are bounded to
                       ``_EVIDENCE_MAX_LEN`` chars with surrounding
                       context.

The aggregate ``RuleVerdict.fail_reasons: list[str]`` stays as-is so
existing tests + ``ScoreBreakdown.disqualify_reasons`` callers keep
working unchanged; new structured access is via
``RuleVerdict.fail_results: list[RuleResult]``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from src.intake.schema import RawJob

logger = logging.getLogger("autoapply.matching.rules")

# Maximum length of an evidence excerpt before truncation with an ellipsis.
# 200 fits in a UI tooltip without scrolling; long enough to include the
# trigger phrase plus surrounding clause.
_EVIDENCE_MAX_LEN = 200
_EVIDENCE_WINDOW = 80  # chars on each side of a regex match

Verdict = Literal["pass", "fail", "warn"]


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
    """Result of a single rule check.

    The class name is retained for backward compatibility; conceptually
    this is the structured "rule verdict" the Phase 16 plan asks for.
    """

    rule_name: str
    passed: bool
    reason: str = ""
    rule_id: str = ""
    verdict: Verdict = "pass"
    evidence_excerpt: str | None = None

    def __post_init__(self) -> None:
        # Default rule_id to rule_name when not provided so the new field
        # is never an empty string (old call sites without rule_id still
        # produce something useful for the UI).
        if not self.rule_id:
            self.rule_id = self.rule_name
        # Keep ``verdict`` in sync with ``passed`` when the caller did not
        # set it explicitly. "warn" is reserved for the edge-case agent in
        # 16.2; the hard rules here only emit pass/fail.
        if self.verdict == "pass" and not self.passed:
            self.verdict = "fail"
        elif self.verdict == "fail" and self.passed:
            # Mismatch -- trust ``passed`` (the legacy field).
            self.verdict = "pass"

    def __repr__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.rule_name}: {self.reason}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for trace persistence + UI payloads."""
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "verdict": self.verdict,
            "passed": self.passed,
            "reason": self.reason,
            "evidence_excerpt": self.evidence_excerpt,
        }


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

    @property
    def fail_results(self) -> list[RuleResult]:
        """Structured per-rule failures (Phase 16.1).

        UI consumers ("Why was this filtered?") and the edge-case agent
        (16.2) read this in preference to the legacy ``fail_reasons``
        string list.
        """
        return [r for r in self.results if not r.passed]

    def to_dict(self) -> dict[str, Any]:
        """Serialize for trace persistence."""
        return {
            "job_id": self.job_id,
            "passed": self.passed,
            "results": [r.to_dict() for r in self.results],
            "fail_reasons": list(self.fail_reasons),
        }


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


def _excerpt_around_match(text: str, match: re.Match[str]) -> str:
    """Return ``text[match]`` bracketed by ~_EVIDENCE_WINDOW chars on each side.

    Adds leading/trailing ellipses when the excerpt does not start/end at
    the text boundary, and collapses internal whitespace runs so the
    snippet displays cleanly in a UI tooltip.
    """
    start = max(0, match.start() - _EVIDENCE_WINDOW)
    end = min(len(text), match.end() + _EVIDENCE_WINDOW)
    snippet = text[start:end]
    snippet = re.sub(r"\s+", " ", snippet).strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return _truncate(snippet, _EVIDENCE_MAX_LEN)


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    # Trim to ``limit - 1`` then add an ellipsis to stay <= limit chars.
    return s[: limit - 1].rstrip() + "…"


def _first_match(text: str, patterns: list[re.Pattern[str]]) -> re.Match[str] | None:
    """Return the first match across ``patterns`` in their declared order."""
    for p in patterns:
        m = p.search(text)
        if m:
            return m
    return None


# --------------------------------------------------------------------------- #
# Rules                                                                       #
# --------------------------------------------------------------------------- #


_VISA_EXCERPT_PATTERNS = [
    re.compile(r"(?i)(no\s+(visa\s+)?sponsorship|do(es)?\s+not\s+sponsor)"),
    re.compile(r"(?i)visa\s+sponsorship[^.]{0,80}"),
    re.compile(r"(?i)sponsorship[^.]{0,80}"),
]

_US_AUTH_EXCERPT_PATTERNS = [
    re.compile(r"(?i)(u\.?s\.?\s+citizen|green\s+card|permanent\s+resident|ead)"),
    re.compile(r"(?i)work\s+authorization[^.]{0,80}"),
    re.compile(r"(?i)authoriz(ed|ation)\s+to\s+work[^.]{0,80}"),
]


def _check_work_authorization(job: RawJob, ctx: ApplicantContext) -> RuleResult:
    """Check visa/work authorization compatibility."""
    reqs = job.requirements
    jd_text = (job.description or "") + " " + (job.title or "")

    # If job explicitly says no sponsorship and applicant needs it
    if reqs.visa_sponsorship is False and ctx.visa_sponsorship_needed:
        match = _first_match(jd_text, _VISA_EXCERPT_PATTERNS)
        return RuleResult(
            rule_id="work_authorization",
            rule_name="work_authorization",
            passed=False,
            verdict="fail",
            reason="Job offers no visa sponsorship; applicant needs sponsorship",
            evidence_excerpt=_excerpt_around_match(jd_text, match) if match else None,
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
        match = _first_match(jd_text, _US_AUTH_EXCERPT_PATTERNS)
        return RuleResult(
            rule_id="work_authorization",
            rule_name="work_authorization",
            passed=False,
            verdict="fail",
            reason="Job requires US work authorization; applicant lacks it",
            evidence_excerpt=_excerpt_around_match(jd_text, match) if match else None,
        )

    return RuleResult(
        rule_id="work_authorization",
        rule_name="work_authorization",
        passed=True,
        verdict="pass",
        reason="OK",
    )


_EXPERIENCE_EXCERPT_PATTERNS = [
    re.compile(r"(?i)(\d+\s*[-+]?\s*\d*\s*\+?\s*years?\s+of\s+experience)"),
    re.compile(r"(?i)(minimum\s+of\s+\d+\s*\+?\s*years?)"),
    re.compile(r"(?i)(\d+\s*\+\s*years?)"),
]


def _check_experience(job: RawJob, ctx: ApplicantContext) -> RuleResult:
    """Check if applicant meets minimum experience requirement."""
    min_yrs = job.requirements.experience_years_min
    jd_text = (job.description or "") + " " + (job.title or "")

    if min_yrs is not None and min_yrs > 0:
        # Allow a 1-year grace (common to apply slightly under)
        if ctx.years_of_experience < min_yrs - 1:
            match = _first_match(jd_text, _EXPERIENCE_EXCERPT_PATTERNS)
            return RuleResult(
                rule_id="experience",
                rule_name="experience",
                passed=False,
                verdict="fail",
                reason=f"Job requires {min_yrs}+ yrs; applicant has {ctx.years_of_experience}",
                evidence_excerpt=_excerpt_around_match(jd_text, match) if match else None,
            )
    return RuleResult(
        rule_id="experience",
        rule_name="experience",
        passed=True,
        verdict="pass",
        reason="OK",
    )


_EDUCATION_RANK = {"Bachelor's": 1, "Master's": 2, "PhD": 3}
_EDUCATION_EXCERPT_PATTERNS = [
    re.compile(r"(?i)(ph\.?d\.?[^.]{0,80})"),
    re.compile(r"(?i)(master'?s?\s+degree[^.]{0,80})"),
    re.compile(r"(?i)(bachelor'?s?\s+degree[^.]{0,80})"),
    re.compile(r"(?i)((ph\.?d\.?|master'?s|bachelor'?s)[^.]{0,80})"),
]


def _check_education(job: RawJob, ctx: ApplicantContext) -> RuleResult:
    """Check if applicant meets education requirement."""
    required = job.requirements.education_level
    if not required:
        return RuleResult(
            rule_id="education",
            rule_name="education",
            passed=True,
            verdict="pass",
            reason="No requirement",
        )

    req_rank = _EDUCATION_RANK.get(required, 0)
    app_rank = _EDUCATION_RANK.get(ctx.education_level, 0)

    if req_rank > 0 and app_rank < req_rank:
        jd_text = (job.description or "") + " " + (job.title or "")
        inferred_from_text = _infer_minimum_education_from_text(jd_text)
        inferred_rank = _EDUCATION_RANK.get(inferred_from_text or "", 0)
        if inferred_rank > 0 and app_rank >= inferred_rank:
            return RuleResult(
                rule_id="education",
                rule_name="education",
                passed=True,
                verdict="pass",
                reason="OK",
            )
        match = _first_match(jd_text, _EDUCATION_EXCERPT_PATTERNS)
        return RuleResult(
            rule_id="education",
            rule_name="education",
            passed=False,
            verdict="fail",
            reason=f"Job requires {required}; applicant has {ctx.education_level or 'unknown'}",
            evidence_excerpt=_excerpt_around_match(jd_text, match) if match else None,
        )

    return RuleResult(
        rule_id="education",
        rule_name="education",
        passed=True,
        verdict="pass",
        reason="OK",
    )


def _infer_minimum_education_from_text(text: str) -> str | None:
    try:
        from src.intake.jd_parser import infer_education_requirement

        return infer_education_requirement(text)
    except Exception:  # noqa: BLE001 - rule evaluation must remain best-effort
        return None


def _check_employment_type(job: RawJob, ctx: ApplicantContext) -> RuleResult:
    """Check if job's employment type matches applicant preferences."""
    if not ctx.preferred_employment_types:
        return RuleResult(
            rule_id="employment_type",
            rule_name="employment_type",
            passed=True,
            verdict="pass",
            reason="No preference set",
        )

    if job.employment_type == "unknown":
        return RuleResult(
            rule_id="employment_type",
            rule_name="employment_type",
            passed=True,
            verdict="pass",
            reason="Unknown type, passing",
        )

    if job.employment_type not in ctx.preferred_employment_types:
        # The "evidence" here is the structured employment_type field, not
        # a JD snippet -- we surface it verbatim so the UI can show
        # "JD says: fulltime" without re-parsing the description.
        return RuleResult(
            rule_id="employment_type",
            rule_name="employment_type",
            passed=False,
            verdict="fail",
            reason=(
                f"Job is {job.employment_type}; applicant prefers {ctx.preferred_employment_types}"
            ),
            evidence_excerpt=f"employment_type={job.employment_type}",
        )

    return RuleResult(
        rule_id="employment_type",
        rule_name="employment_type",
        passed=True,
        verdict="pass",
        reason="OK",
    )


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
        match = pattern.search(text)
        if match:
            return RuleResult(
                rule_id="spam_filter",
                rule_name="spam_filter",
                passed=False,
                verdict="fail",
                reason=f"Spam signal detected: {pattern.pattern[:50]}",
                evidence_excerpt=_excerpt_around_match(text, match),
            )

    # Ghost job signals: very old postings or extremely generic titles
    if job.title and len(job.title.strip()) < 5:
        return RuleResult(
            rule_id="spam_filter",
            rule_name="spam_filter",
            passed=False,
            verdict="fail",
            reason="Title too short — likely a generic/ghost posting",
            evidence_excerpt=f"title={job.title!r}",
        )

    return RuleResult(
        rule_id="spam_filter",
        rule_name="spam_filter",
        passed=True,
        verdict="pass",
        reason="OK",
    )


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
