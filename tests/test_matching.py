"""Tests for src.matching — rules, semantic, and scorer."""

import pytest

from src.intake.schema import JobRequirements, RawJob
from src.matching.rules import (
    ApplicantContext,
    RuleVerdict,
    check_rules,
    load_applicant_context,
)
from src.matching.semantic import (
    build_applicant_text,
    collect_applicant_skills,
    compute_keyword_similarity,
    compute_skill_overlap,
    _normalize,
)
from src.matching.scorer import (
    ScoreBreakdown,
    ScoringContext,
    build_scoring_context,
    score_job,
    score_jobs,
    _compute_quality_multiplier,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_job(**overrides) -> RawJob:
    defaults = {
        "source": "greenhouse",
        "source_id": "j1",
        "company": "TestCo",
        "title": "Software Engineering Intern",
        "location": "Vancouver, BC",
        "employment_type": "internship",
        "seniority": "internship",
        "description": "Looking for an intern with Python, React, and PostgreSQL experience. "
                       "Must be familiar with REST APIs and testing frameworks. "
                       "This is a 4-month internship in our Vancouver office.",
        "ats_type": "greenhouse",
        "application_url": "https://example.com/apply",
    }
    defaults.update(overrides)
    return RawJob(**defaults)


def _make_ctx(**overrides) -> ApplicantContext:
    defaults = {
        "location": "Vancouver, BC, Canada",
        "citizenship": "Chinese",
        "work_authorization": "Study Permit",
        "visa_sponsorship_needed": True,
        "years_of_experience": 1,
        "education_level": "Bachelor's",
        "preferred_employment_types": ["internship", "coop"],
    }
    defaults.update(overrides)
    return ApplicantContext(**defaults)


_SAMPLE_PROFILE = {
    "identity": {
        "location": "Vancouver, BC, Canada",
        "citizenship": "Chinese",
        "work_authorization": "Study Permit",
        "visa_sponsorship_needed": True,
        "willing_to_relocate": True,
    },
    "education": [
        {
            "degree": "Bachelor of Science",
            "field": "Computer Science",
        },
    ],
    "work_experiences": [
        {
            "company": "Acme",
            "title": "Software Dev Intern",
            "start_date": "2025-05",
            "end_date": "2025-08",
            "bullets": [
                {"text": "Built REST APIs with Python and FastAPI", "tags": ["python", "api", "backend"]},
                {"text": "Wrote unit tests with pytest", "tags": ["testing", "python"]},
            ],
        },
    ],
    "projects": [
        {
            "name": "Portfolio Site",
            "description": "Personal portfolio built with React and Next.js",
            "tech_stack": ["React", "Next.js", "TypeScript"],
            "bullets": [
                {"text": "Implemented responsive UI with Tailwind CSS", "tags": ["frontend", "react"]},
            ],
        },
    ],
    "skills": {
        "languages": ["Python", "TypeScript", "Java"],
        "frameworks": ["React", "FastAPI", "Next.js"],
        "databases": ["PostgreSQL", "Redis"],
        "tools": ["Docker", "Git", "AWS"],
    },
}


# ===========================================================================
# Rules tests
# ===========================================================================

class TestRulesWorkAuth:
    def test_no_sponsorship_fails(self):
        job = _make_job()
        job.requirements = JobRequirements(visa_sponsorship=False)
        ctx = _make_ctx(visa_sponsorship_needed=True)
        verdict = check_rules(job, ctx)
        assert not verdict.passed
        assert any("sponsorship" in r for r in verdict.fail_reasons)

    def test_sponsorship_available_passes(self):
        job = _make_job()
        job.requirements = JobRequirements(visa_sponsorship=True)
        ctx = _make_ctx(visa_sponsorship_needed=True)
        verdict = check_rules(job, ctx)
        assert verdict.passed

    def test_us_auth_required_fails(self):
        job = _make_job()
        job.requirements = JobRequirements(us_work_auth_required=True)
        ctx = _make_ctx(work_authorization="Study Permit")
        verdict = check_rules(job, ctx)
        assert not verdict.passed

    def test_us_citizen_passes(self):
        job = _make_job()
        job.requirements = JobRequirements(us_work_auth_required=True)
        ctx = _make_ctx(work_authorization="US Citizen")
        verdict = check_rules(job, ctx)
        assert verdict.passed


class TestRulesExperience:
    def test_under_min_fails(self):
        job = _make_job()
        job.requirements = JobRequirements(experience_years_min=5)
        ctx = _make_ctx(years_of_experience=1)
        verdict = check_rules(job, ctx)
        assert not verdict.passed

    def test_within_grace_passes(self):
        """Allow 1 year under the minimum."""
        job = _make_job()
        job.requirements = JobRequirements(experience_years_min=2)
        ctx = _make_ctx(years_of_experience=1)
        verdict = check_rules(job, ctx)
        assert verdict.passed

    def test_no_requirement_passes(self):
        job = _make_job()
        ctx = _make_ctx(years_of_experience=0)
        verdict = check_rules(job, ctx)
        assert verdict.passed


class TestRulesEducation:
    def test_phd_required_bachelors_fails(self):
        job = _make_job()
        job.requirements = JobRequirements(education_level="PhD")
        ctx = _make_ctx(education_level="Bachelor's")
        verdict = check_rules(job, ctx)
        assert not verdict.passed

    def test_bachelors_required_masters_passes(self):
        job = _make_job()
        job.requirements = JobRequirements(education_level="Bachelor's")
        ctx = _make_ctx(education_level="Master's")
        verdict = check_rules(job, ctx)
        assert verdict.passed


class TestRulesEmploymentType:
    def test_fulltime_when_seeking_intern_fails(self):
        job = _make_job(employment_type="fulltime")
        ctx = _make_ctx(preferred_employment_types=["internship"])
        verdict = check_rules(job, ctx)
        assert not verdict.passed

    def test_unknown_passes(self):
        job = _make_job(employment_type="unknown")
        ctx = _make_ctx(preferred_employment_types=["internship"])
        verdict = check_rules(job, ctx)
        assert verdict.passed


class TestRulesSpam:
    def test_staffing_agency_fails(self):
        job = _make_job(description="We are a staffing agency looking for candidates")
        verdict = check_rules(job, _make_ctx())
        assert not verdict.passed

    def test_short_title_fails(self):
        job = _make_job(title="Job")
        verdict = check_rules(job, _make_ctx())
        assert not verdict.passed

    def test_normal_job_passes(self):
        job = _make_job()
        verdict = check_rules(job, _make_ctx())
        assert verdict.passed


class TestLoadApplicantContext:
    def test_from_profile(self):
        ctx = load_applicant_context(_SAMPLE_PROFILE)
        assert ctx.location == "Vancouver, BC, Canada"
        assert ctx.citizenship == "Chinese"
        assert ctx.visa_sponsorship_needed is True
        assert ctx.education_level == "Bachelor's"


# ===========================================================================
# Semantic tests
# ===========================================================================

class TestSkillOverlap:
    def test_full_overlap(self):
        score = compute_skill_overlap(
            ["Python", "React"], ["Python", "React", "Java"],
        )
        assert score == 1.0

    def test_partial_overlap(self):
        score = compute_skill_overlap(
            ["Python", "React", "Go"], ["Python", "React"],
        )
        assert 0.5 < score < 1.0

    def test_no_overlap(self):
        score = compute_skill_overlap(["Rust", "Go"], ["Python", "Java"])
        assert score == 0.0

    def test_empty_job_skills(self):
        score = compute_skill_overlap([], ["Python"])
        assert score == 0.5  # Neutral

    def test_fuzzy_match(self):
        """reactjs should match react."""
        score = compute_skill_overlap(["ReactJS"], ["React"])
        assert score > 0.0


class TestNormalize:
    def test_aliases(self):
        assert _normalize("JS") == "javascript"
        assert _normalize("K8s") == "kubernetes"
        assert _normalize("Py") == "python"

    def test_strip(self):
        assert _normalize("  Python  ") == "python"


class TestKeywordSimilarity:
    def test_similar_texts(self):
        jd = "Python backend development with REST APIs and PostgreSQL"
        profile = "Experienced in Python backend, built REST APIs, used PostgreSQL"
        score = compute_keyword_similarity(jd, profile)
        assert score > 0.3

    def test_unrelated_texts(self):
        jd = "Financial analyst with Excel and Bloomberg terminal expertise"
        profile = "Python backend developer with API experience"
        score = compute_keyword_similarity(jd, profile)
        assert score < 0.2

    def test_empty_text(self):
        assert compute_keyword_similarity("", "something") == 0.0
        assert compute_keyword_similarity("something", "") == 0.0


class TestBuildApplicantText:
    def test_includes_skills_and_bullets(self):
        text = build_applicant_text(_SAMPLE_PROFILE)
        assert "Python" in text
        assert "REST APIs" in text
        assert "React" in text


class TestCollectSkills:
    def test_collects_from_all_sections(self):
        skills = collect_applicant_skills(_SAMPLE_PROFILE)
        assert "Python" in skills
        assert "React" in skills
        # Tags from bullets
        assert "backend" in skills
        assert "frontend" in skills


# ===========================================================================
# Scorer tests
# ===========================================================================

class TestQualityMultiplier:
    def test_good_job(self):
        job = _make_job(description="x" * 500, application_url="https://apply.com")
        assert _compute_quality_multiplier(job) == 1.0

    def test_short_description(self):
        job = _make_job(description="Short", application_url="https://apply.com")
        assert _compute_quality_multiplier(job) < 1.0

    def test_no_apply_url(self):
        job = _make_job(application_url=None)
        assert _compute_quality_multiplier(job) < 1.0


class TestScoreJob:
    def test_good_match(self):
        job = _make_job()
        job.requirements = JobRequirements(
            must_have_skills=["Python", "React"],
        )
        ctx = build_scoring_context(_SAMPLE_PROFILE)
        breakdown = score_job(job, ctx)
        assert breakdown.final_score > 0.0
        assert not breakdown.disqualified

    def test_disqualified_job(self):
        job = _make_job()
        job.requirements = JobRequirements(visa_sponsorship=False)
        ctx = build_scoring_context(_SAMPLE_PROFILE)
        breakdown = score_job(job, ctx)
        assert breakdown.disqualified
        assert breakdown.final_score == 0.0

    def test_no_skills_listed(self):
        """Jobs with no skills listed should still get a score."""
        job = _make_job()
        ctx = build_scoring_context(_SAMPLE_PROFILE)
        breakdown = score_job(job, ctx)
        assert breakdown.final_score > 0.0


class TestScoreJobs:
    def test_ranking_order(self):
        good_job = _make_job(
            source_id="g1",
            title="Python Backend Intern",
            description="Python, FastAPI, PostgreSQL, REST APIs, testing",
        )
        good_job.requirements = JobRequirements(must_have_skills=["Python", "PostgreSQL"])

        bad_job = _make_job(
            source_id="b1",
            title="Marketing Intern",
            description="Excel, presentations, social media campaigns",
        )

        ctx = build_scoring_context(_SAMPLE_PROFILE)
        results = score_jobs([bad_job, good_job], ctx)

        # Good job should rank first
        assert results[0].title == "Python Backend Intern"
        assert results[0].final_score >= results[1].final_score
