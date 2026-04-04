"""Tests for the memory layer (profile, bullet pool, QA bank)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import get_db_url, load_config
from src.core.models import ApplicantProfile, BulletPool, QABank
from src.memory.bullet_pool import (
    get_all_bullets,
    ingest_bullets_from_profile,
    query_bullets_by_tags,
)
from src.memory.profile import get_full_profile, get_profile_section, ingest_profile
from src.memory.qa_bank import find_answer, get_answer_text, ingest_qa_from_profile
from src.memory.story_bank import get_stories, ingest_stories

SAMPLE_PROFILE = {
    "identity": {
        "full_name": "Test User",
        "email": "test@example.com",
        "location": "Vancouver, BC",
    },
    "education": [
        {
            "institution": "University of Test",
            "degree": "Master of Science",
            "field": "Computer Science",
            "start_date": "2024-09",
            "end_date": "2026-04",
            "relevant_courses": [
                {"name": "Distributed Systems", "tags": ["distributed", "backend"]},
                {"name": "Machine Learning", "tags": ["ml", "python"]},
            ],
        }
    ],
    "work_experiences": [
        {
            "company": "TechCorp",
            "title": "Software Engineer",
            "bullets": [
                {
                    "text": "Built a REST API serving 10k requests/sec using Python and FastAPI",
                    "tags": ["backend", "python", "api", "fastapi"],
                },
                {
                    "text": "Designed distributed cache layer reducing latency by 40%",
                    "tags": ["backend", "distributed", "performance"],
                },
            ],
        }
    ],
    "projects": [
        {
            "name": "AutoApply",
            "role": "Lead Developer",
            "tech_stack": ["Python", "Playwright", "PostgreSQL"],
            "bullets": [
                {
                    "text": "Developed an AI agent for automated job applications",
                    "tags": ["python", "automation", "ai"],
                },
            ],
        }
    ],
    "skills": {
        "languages": ["Python", "Java", "TypeScript"],
        "frameworks": ["FastAPI", "React"],
        "databases": ["PostgreSQL", "Redis"],
        "tools": ["Docker", "Git"],
    },
    "story_bank": [
        {
            "theme": "technical_challenge",
            "context": "Production cache was failing under load",
            "action": "Redesigned with consistent hashing",
            "result": "Reduced latency by 40%, zero downtime migration",
            "applicable_to": ["backend_roles", "big_tech"],
        }
    ],
    "qa_bank": [
        {
            "question_type": "authorization",
            "question_pattern": "Are you legally authorized to work in the United States?",
            "canonical_answer": "Yes, I am authorized to work with OPT status.",
            "variants": {
                "by_geography": {"Canada": "Yes, I have a valid work permit."},
            },
            "confidence": "high",
            "needs_review": False,
        },
        {
            "question_type": "sponsorship",
            "question_pattern": "Will you now or in the future require sponsorship?",
            "canonical_answer": "Yes, I will require H-1B sponsorship after OPT.",
            "confidence": "high",
            "needs_review": True,
        },
    ],
}


@pytest.fixture
def db_session():
    """Create a test database session using the real DB."""
    config = load_config()
    engine = create_engine(get_db_url(config))
    session_factory = sessionmaker(bind=engine)
    session = session_factory()

    yield session

    # Cleanup test data
    session.query(QABank).delete()
    session.query(BulletPool).delete()
    session.query(ApplicantProfile).delete()
    session.commit()
    session.close()


class TestProfile:
    def test_ingest_profile(self, db_session: Session):
        records = ingest_profile(db_session, SAMPLE_PROFILE)
        assert len(records) >= 4  # identity, education, work_experiences, projects, skills

    def test_get_profile_section(self, db_session: Session):
        ingest_profile(db_session, SAMPLE_PROFILE)
        identity = get_profile_section(db_session, "identity")
        assert identity is not None
        assert identity["full_name"] == "Test User"

    def test_get_full_profile(self, db_session: Session):
        ingest_profile(db_session, SAMPLE_PROFILE)
        full = get_full_profile(db_session)
        assert "identity" in full
        assert "skills" in full


class TestBulletPool:
    def test_ingest_bullets(self, db_session: Session):
        bullets = ingest_bullets_from_profile(db_session, SAMPLE_PROFILE)
        assert len(bullets) == 3  # 2 from experience + 1 from project

    def test_query_by_tags(self, db_session: Session):
        ingest_bullets_from_profile(db_session, SAMPLE_PROFILE)
        results = query_bullets_by_tags(db_session, ["backend", "python"])
        assert len(results) >= 1
        # The API bullet should rank highest (matches both tags)
        assert "API" in results[0].text or "api" in results[0].text.lower()

    def test_get_all_bullets(self, db_session: Session):
        ingest_bullets_from_profile(db_session, SAMPLE_PROFILE)
        all_bullets = get_all_bullets(db_session)
        assert len(all_bullets) == 3
        exp_only = get_all_bullets(db_session, category="experience")
        assert len(exp_only) == 2


class TestStoryBank:
    def test_ingest_stories(self, db_session: Session):
        count = ingest_stories(db_session, SAMPLE_PROFILE)
        assert count == 1

    def test_get_stories_by_theme(self, db_session: Session):
        ingest_stories(db_session, SAMPLE_PROFILE)
        stories = get_stories(db_session, theme="technical_challenge")
        assert len(stories) == 1
        assert "cache" in stories[0]["context"].lower()


class TestQABank:
    def test_ingest_qa(self, db_session: Session):
        records = ingest_qa_from_profile(db_session, SAMPLE_PROFILE)
        assert len(records) == 2

    def test_find_answer_by_type(self, db_session: Session):
        ingest_qa_from_profile(db_session, SAMPLE_PROFILE)
        entry = find_answer(db_session, "authorization question", question_type="authorization")
        assert entry is not None
        assert "authorized" in entry.canonical_answer.lower()

    def test_get_answer_with_variant(self, db_session: Session):
        ingest_qa_from_profile(db_session, SAMPLE_PROFILE)
        entry = find_answer(db_session, "", question_type="authorization")
        assert entry is not None

        # Default answer
        default = get_answer_text(entry)
        assert "OPT" in default

        # Canada variant
        canada = get_answer_text(entry, geography="Canada")
        assert "work permit" in canada.lower()
