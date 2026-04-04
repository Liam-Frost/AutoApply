"""Tests for the document processing layer."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from docx import Document

from src.documents.docx_engine import build_resume, create_default_template, substitute_placeholders
from src.documents.file_manager import get_output_paths, make_filename
from src.documents.templates import discover_templates, get_template_path, register_template

TMP_DIR = Path("data/output/_test")

SAMPLE_IDENTITY = {
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "+1 604-000-0000",
    "location": "Vancouver, BC",
    "linkedin_url": "linkedin.com/in/janedoe",
    "github_url": "github.com/janedoe",
}

SAMPLE_EDUCATION = [
    {
        "institution": "UBC",
        "degree": "Master of Science",
        "field": "Computer Science",
        "start_date": "2024-09",
        "end_date": "2026-04",
        "gpa": "4.0/4.0",
        "relevant_courses": [
            {"name": "Distributed Systems", "tags": ["distributed"]},
        ],
    }
]

SAMPLE_EXPERIENCES = [
    {
        "company": "Stripe",
        "title": "Software Engineer Intern",
        "location": "San Francisco, CA",
        "start_date": "2025-05",
        "end_date": "2025-08",
        "bullets": [
            {
                "text": "Built payment retry logic handling 1M+ transactions/day",
                "tags": ["backend"],
            },
        ],
    }
]

SAMPLE_PROJECTS = [
    {
        "name": "AutoApply",
        "role": "Lead Developer",
        "tech_stack": ["Python", "Playwright"],
        "bullets": [
            {
                "text": "Developed an AI agent for automated job applications",
                "tags": ["python", "ai"],
            },
        ],
    }
]

SAMPLE_SKILLS = {
    "languages": ["Python", "Java"],
    "frameworks": ["FastAPI", "React"],
    "databases": ["PostgreSQL"],
    "tools": ["Docker"],
}


@pytest.fixture(autouse=True)
def cleanup():
    yield
    import shutil

    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR)


class TestDocxEngine:
    def test_create_default_template(self):
        template_path = TMP_DIR / "default_template.docx"
        result = create_default_template(template_path)
        assert result.exists()
        doc = Document(str(result))
        full_text = " ".join(p.text for p in doc.paragraphs)
        assert "{{FULL_NAME}}" in full_text
        assert "{{EDUCATION_BLOCK}}" in full_text
        assert "{{EXPERIENCE_BLOCK}}" in full_text

    def test_substitute_placeholders(self):
        template_path = TMP_DIR / "template.docx"
        create_default_template(template_path)
        doc = Document(str(template_path))
        substitute_placeholders(doc, {"FULL_NAME": "Jane Doe", "EMAIL": "jane@example.com"})
        full_text = " ".join(p.text for p in doc.paragraphs)
        assert "Jane Doe" in full_text
        assert "jane@example.com" in full_text

    def test_build_resume(self):
        template_path = TMP_DIR / "template.docx"
        create_default_template(template_path)
        output_path = TMP_DIR / "resume_test.docx"

        result = build_resume(
            template_path=template_path,
            identity=SAMPLE_IDENTITY,
            education=SAMPLE_EDUCATION,
            experiences=SAMPLE_EXPERIENCES,
            projects=SAMPLE_PROJECTS,
            skills=SAMPLE_SKILLS,
            selected_bullets={},
            output_path=output_path,
        )

        assert result.exists()
        doc = Document(str(result))
        full_text = " ".join(p.text for p in doc.paragraphs)
        assert "Jane Doe" in full_text
        assert "Stripe" in full_text
        assert "AutoApply" in full_text
        assert "Python" in full_text
        assert "UBC" in full_text


class TestFileManager:
    def test_make_filename_resume(self):
        date = datetime(2026, 4, 2, tzinfo=UTC)
        name = make_filename("resume", "Stripe", "Backend Engineer", date)
        assert name == "resume_stripe_backend_engineer_2026-04-02.docx"

    def test_make_filename_cover(self):
        date = datetime(2026, 4, 2, tzinfo=UTC)
        name = make_filename("cover", "Google LLC", "SWE Intern", date, ext="pdf")
        assert name == "cover_google_llc_swe_intern_2026-04-02.pdf"

    def test_make_filename_special_chars(self):
        date = datetime(2026, 4, 2, tzinfo=UTC)
        name = make_filename("resume", "A/B & Co.", "C++ Dev", date)
        # Should not contain special chars
        assert "/" not in name
        assert "&" not in name

    def test_get_output_paths(self):
        date = datetime(2026, 4, 2, tzinfo=UTC)
        paths = get_output_paths(TMP_DIR, "Stripe", "Backend Intern", date)
        assert "resume_docx" in paths
        assert "resume_pdf" in paths
        assert "cover_docx" in paths
        assert "cover_pdf" in paths
        assert paths["resume_docx"].suffix == ".docx"
        assert paths["resume_pdf"].suffix == ".pdf"


class TestTemplateRegistry:
    def test_register_and_get(self):
        template_path = TMP_DIR / "my_template.docx"
        create_default_template(template_path)
        register_template("test_template", template_path)
        assert get_template_path("test_template") == template_path

    def test_get_missing_template_raises(self):
        with pytest.raises(KeyError):
            get_template_path("nonexistent_template_xyz")

    def test_discover_templates(self):
        # Create two templates
        create_default_template(TMP_DIR / "modern.docx")
        create_default_template(TMP_DIR / "classic.docx")
        discover_templates(TMP_DIR)
        # Both should now be registered
        assert get_template_path("modern") is not None
        assert get_template_path("classic") is not None
