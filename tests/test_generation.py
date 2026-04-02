"""Tests for src.generation — resume builder, cover letter, QA responder."""

import pytest

from src.intake.schema import JobRequirements, RawJob
from src.generation.resume_builder import (
    extract_jd_tags,
    select_bullets_for_jd,
    _rank_and_select,
)
from src.generation.cover_letter import (
    _select_evidence,
    _generate_template,
    _format_education_brief,
)
from src.generation.qa_responder import (
    QAResponse,
    answer_questions,
    classify_question,
    _find_qa_match,
    _get_variant_answer,
    _template_answer,
    _estimate_experience_years,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_job(**overrides) -> RawJob:
    defaults = {
        "source": "greenhouse",
        "source_id": "j1",
        "company": "TestCo",
        "title": "Backend Engineering Intern",
        "location": "Vancouver, BC",
        "employment_type": "internship",
        "seniority": "internship",
        "description": "We need a backend intern with Python, FastAPI, PostgreSQL, and Docker experience.",
        "ats_type": "greenhouse",
        "application_url": "https://example.com/apply",
    }
    defaults.update(overrides)
    return RawJob(**defaults)


_PROFILE = {
    "identity": {
        "full_name": "Test User",
        "email": "test@example.com",
        "location": "Vancouver, BC, Canada",
        "citizenship": "Chinese",
        "work_authorization": "Study Permit",
        "visa_sponsorship_needed": True,
    },
    "education": [
        {
            "institution": "UBC",
            "degree": "Bachelor of Science",
            "field": "Computer Science",
            "start_date": "2022-09",
            "end_date": "2026-05",
        },
    ],
    "work_experiences": [
        {
            "company": "Acme Corp",
            "title": "Software Dev Intern",
            "start_date": "2025-05",
            "end_date": "2025-08",
            "bullets": [
                {"text": "Built REST APIs with Python and FastAPI", "tags": ["python", "api", "backend", "fastapi"]},
                {"text": "Wrote unit tests achieving 90% coverage", "tags": ["testing", "python"]},
                {"text": "Designed data pipeline with Apache Kafka", "tags": ["kafka", "data", "backend"]},
            ],
        },
    ],
    "projects": [
        {
            "name": "CloudDeploy",
            "description": "CI/CD platform",
            "tech_stack": ["Python", "Docker", "AWS"],
            "bullets": [
                {"text": "Containerized microservices with Docker and Kubernetes", "tags": ["docker", "kubernetes", "devops"]},
                {"text": "Built React frontend dashboard", "tags": ["react", "frontend"]},
            ],
        },
    ],
    "skills": {
        "languages": ["Python", "TypeScript", "Java"],
        "frameworks": ["FastAPI", "React", "Next.js"],
        "databases": ["PostgreSQL", "Redis"],
        "tools": ["Docker", "Git", "AWS"],
    },
}


# ===========================================================================
# Resume builder tests
# ===========================================================================

class TestExtractJDTags:
    def test_from_requirements(self):
        job = _make_job()
        job.requirements = JobRequirements(
            must_have_skills=["Python", "PostgreSQL"],
            preferred_skills=["Docker"],
        )
        tags = extract_jd_tags(job)
        assert "python" in tags
        assert "postgresql" in tags
        assert "docker" in tags

    def test_from_title(self):
        job = _make_job(title="Python Backend Intern")
        tags = extract_jd_tags(job)
        assert "python" in tags
        assert "backend" in tags

    def test_dedup(self):
        job = _make_job(title="Python Developer")
        job.requirements = JobRequirements(must_have_skills=["Python"])
        tags = extract_jd_tags(job)
        assert tags.count("python") == 1

    def test_empty(self):
        job = _make_job(title="Intern")
        tags = extract_jd_tags(job)
        # No tech keywords in "Intern" alone
        assert isinstance(tags, list)


class TestSelectBullets:
    def test_selects_matching_bullets(self):
        jd_tags = ["python", "api", "backend"]
        selected = select_bullets_for_jd(jd_tags, _PROFILE)

        # Should have entries for Acme Corp and CloudDeploy
        assert len(selected) >= 1

        # Acme Corp bullets should prioritize python/api/backend tagged ones
        acme_key = "Acme Corp - Software Dev Intern"
        assert acme_key in selected
        assert any("REST APIs" in b for b in selected[acme_key])

    def test_max_bullets(self):
        jd_tags = ["python", "testing", "api", "backend"]
        selected = select_bullets_for_jd(jd_tags, _PROFILE, max_bullets_per_entity=2)
        acme_key = "Acme Corp - Software Dev Intern"
        assert len(selected[acme_key]) <= 2

    def test_empty_tags_returns_all(self):
        selected = select_bullets_for_jd([], _PROFILE)
        # Should still return bullets (all have 0 overlap, falls back to all)
        assert any(len(v) > 0 for v in selected.values())


class TestRankAndSelect:
    def test_ordering(self):
        bullets = [
            {"text": "low match", "tags": ["unrelated"]},
            {"text": "high match", "tags": ["python", "api"]},
            {"text": "mid match", "tags": ["python"]},
        ]
        result = _rank_and_select(bullets, {"python", "api"}, max_count=2)
        assert result[0] == "high match"
        assert len(result) == 2

    def test_empty_bullets(self):
        assert _rank_and_select([], {"python"}, max_count=3) == []


# ===========================================================================
# Cover letter tests
# ===========================================================================

class TestSelectEvidence:
    def test_selects_relevant_bullets(self):
        job = _make_job()
        job.requirements = JobRequirements(must_have_skills=["Python", "FastAPI"])
        evidence = _select_evidence(job, _PROFILE)
        assert len(evidence) > 0
        assert len(evidence) <= 3
        # Should contain the FastAPI bullet from Acme
        assert any("FastAPI" in e for e in evidence)

    def test_includes_entity_context(self):
        job = _make_job()
        job.requirements = JobRequirements(must_have_skills=["Python"])
        evidence = _select_evidence(job, _PROFILE)
        # Evidence should include "At Acme Corp, ..."
        assert any("Acme" in e for e in evidence)


class TestGenerateTemplate:
    def test_produces_text(self):
        job = _make_job()
        identity = _PROFILE["identity"]
        evidence = ["Built REST APIs with Python and FastAPI"]
        text = _generate_template(job, identity, evidence)
        assert "Backend Engineering Intern" in text
        assert "TestCo" in text
        assert len(text) > 50

    def test_no_evidence(self):
        job = _make_job()
        text = _generate_template(job, _PROFILE["identity"], [])
        assert "TestCo" in text


class TestFormatEducation:
    def test_basic(self):
        result = _format_education_brief(_PROFILE["education"])
        assert "Bachelor of Science" in result
        assert "UBC" in result

    def test_empty(self):
        assert _format_education_brief([]) == "Not specified"


# ===========================================================================
# QA responder tests
# ===========================================================================

class TestClassifyQuestion:
    def test_authorization(self):
        assert classify_question("Are you authorized to work in the US?") == "authorization"

    def test_sponsorship(self):
        assert classify_question("Do you require visa sponsorship?") == "sponsorship"

    def test_experience(self):
        assert classify_question("How many years of experience do you have?") == "experience_years"

    def test_salary(self):
        assert classify_question("What is your expected salary?") == "salary"

    def test_start_date(self):
        assert classify_question("When can you start?") == "start_date"

    def test_why_company(self):
        assert classify_question("Why do you want to work at our company?") == "why_company"

    def test_why_role(self):
        assert classify_question("Why are you interested in this role?") == "why_role"

    def test_strengths(self):
        assert classify_question("What are your strengths?") == "strengths"

    def test_weaknesses(self):
        assert classify_question("What is your biggest weakness?") == "weaknesses"

    def test_custom(self):
        assert classify_question("Tell me about a time you solved a hard problem") == "custom"


class TestFindQAMatch:
    _QA_ENTRIES = [
        {
            "question_type": "authorization",
            "question_pattern": "Are you legally authorized to work?",
            "canonical_answer": "Yes, I have a valid study permit.",
            "confidence": "high",
            "needs_review": False,
        },
        {
            "question_type": "sponsorship",
            "question_pattern": "Do you require visa sponsorship?",
            "canonical_answer": "Yes, I would need sponsorship.",
            "confidence": "high",
            "needs_review": True,
        },
    ]

    def test_type_match(self):
        match = _find_qa_match(
            "Are you authorized to work in Canada?",
            "authorization",
            self._QA_ENTRIES,
        )
        assert match is not None
        assert match["question_type"] == "authorization"

    def test_no_match(self):
        match = _find_qa_match(
            "What is your favorite color?",
            "custom",
            self._QA_ENTRIES,
        )
        assert match is None  # No custom entries, no overlap


class TestGetVariantAnswer:
    def test_geography_variant(self):
        entry = {
            "canonical_answer": "Default answer",
            "variants": {
                "by_geography": {"Canada": "Canadian variant"},
            },
        }
        job = _make_job(location="Vancouver, Canada")
        assert _get_variant_answer(entry, job) == "Canadian variant"

    def test_fallback_to_canonical(self):
        entry = {
            "canonical_answer": "Default answer",
            "variants": {},
        }
        job = _make_job(location="Unknown")
        assert _get_variant_answer(entry, job) == "Default answer"


class TestTemplateAnswer:
    def test_authorization_returns_none(self):
        """Authorization is jurisdiction-sensitive, should not auto-generate."""
        answer = _template_answer("authorization", _PROFILE, _make_job())
        assert answer is None

    def test_sponsorship_returns_none(self):
        """Sponsorship is high-risk, should not auto-generate."""
        answer = _template_answer("sponsorship", _PROFILE, _make_job())
        assert answer is None

    def test_start_date(self):
        answer = _template_answer("start_date", _PROFILE, _make_job())
        assert answer is not None
        assert "available" in answer.lower()

    def test_experience_years(self):
        answer = _template_answer("experience_years", _PROFILE, _make_job())
        assert answer is not None

    def test_unknown_type(self):
        assert _template_answer("custom", _PROFILE, _make_job()) is None


class TestEstimateExperienceYears:
    def test_basic(self):
        exps = [{"start_date": "2024-01", "end_date": "2025-01"}]
        assert _estimate_experience_years(exps) == 1

    def test_sub_year(self):
        """4-month internship should round to 0 years."""
        exps = [{"start_date": "2025-05", "end_date": "2025-08"}]
        assert _estimate_experience_years(exps) == 0

    def test_present(self):
        exps = [{"start_date": "2024-01", "end_date": "Present"}]
        years = _estimate_experience_years(exps)
        assert years >= 1

    def test_overlapping_merged(self):
        """Overlapping jobs should not double-count."""
        exps = [
            {"start_date": "2023-01", "end_date": "2024-06"},
            {"start_date": "2024-01", "end_date": "2025-01"},
        ]
        # Merged: 2023-01 to 2025-01 = 24 months = 2 years
        assert _estimate_experience_years(exps) == 2

    def test_empty(self):
        assert _estimate_experience_years([]) == 0


class TestAnswerQuestions:
    def test_with_qa_bank(self):
        qa_entries = [
            {
                "question_type": "authorization",
                "question_pattern": "Are you authorized to work?",
                "canonical_answer": "Yes, I hold a valid work permit.",
                "confidence": "high",
                "needs_review": False,
                "variants": {},
            },
        ]
        responses = answer_questions(
            ["Are you authorized to work in the US?"],
            _make_job(),
            _PROFILE,
            qa_entries=qa_entries,
            use_llm=False,
        )
        assert len(responses) == 1
        assert responses[0].source == "qa_bank"
        assert "work permit" in responses[0].answer.lower()

    def test_template_fallback(self):
        responses = answer_questions(
            ["When can you start?"],
            _make_job(),
            _PROFILE,
            qa_entries=None,
            use_llm=False,
        )
        assert len(responses) == 1
        assert responses[0].source == "template"
        assert "available" in responses[0].answer.lower()

    def test_no_answer_flagged(self):
        responses = answer_questions(
            ["Tell me about your hobbies"],
            _make_job(),
            _PROFILE,
            qa_entries=None,
            use_llm=False,
        )
        assert len(responses) == 1
        assert responses[0].needs_review is True
        assert responses[0].source == "none"

    def test_high_risk_flagged(self):
        """Salary questions should always be flagged even with QA match."""
        qa_entries = [
            {
                "question_type": "salary",
                "question_pattern": "What is your expected salary?",
                "canonical_answer": "$80,000",
                "confidence": "high",
                "needs_review": False,
                "variants": {},
            },
        ]
        responses = answer_questions(
            ["What is your expected salary?"],
            _make_job(),
            _PROFILE,
            qa_entries=qa_entries,
            use_llm=False,
        )
        assert responses[0].needs_review is True  # High-risk type overrides
