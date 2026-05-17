"""Phase 15.2: tests for the DOCX patch mode.

We build small in-memory DOCX fixtures with python-docx, run the
patcher against a representative ResumeDocument IR, and read the
output back to verify:

* The Summary section is stripped from the source DOCX entirely --
  generated resumes never include one regardless of source content.
* Skills section is rewritten in-place under its heading.
* Bullets are swapped run-by-run; surplus bullets are appended; deficit
  bullets are blanked (not physically deleted).
* Sections not in ``section_order`` get their body blanked.
* :class:`PatchFallback` is raised for missing source files so the
  Phase 15.5 router can route to the template path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from src.generation.docx_patch import (
    PatchFallback,
    patch_resume_docx,
)
from src.generation.ir import ResumeBullet, ResumeDocument, ResumeItem


def _build_source(path: Path) -> None:
    doc = Document()
    doc.add_heading("Summary", level=1)
    doc.add_paragraph("Old summary about the candidate.")
    doc.add_heading("Skills", level=1)
    doc.add_paragraph("Must Have: legacy-python, legacy-sql")
    doc.add_paragraph("Preferred: react, docker")
    doc.add_heading("Experience", level=1)
    doc.add_paragraph("Original Co — Software Engineer", style="Heading 2")
    doc.add_paragraph("Built the old thing", style="List Bullet")
    doc.add_paragraph("Shipped some feature", style="List Bullet")
    doc.add_heading("Projects", level=1)
    doc.add_paragraph("Side Project", style="Heading 2")
    doc.add_paragraph("Old bullet for side project", style="List Bullet")
    doc.add_heading("Awards", level=1)
    doc.add_paragraph("Some award text.")
    doc.save(str(path))


def _bullet(text: str) -> ResumeBullet:
    return ResumeBullet(
        text=text,
        source_id="exp-1",
        source_type="experience",
        source_entity="Original Co",
    )


def _ir(experience_bullets: list[str], project_bullets: list[str] | None = None) -> ResumeDocument:
    return ResumeDocument(
        target_role="Software Engineer Intern",
        company="Test Co",
        header={"name": "Test"},
        skills={
            "must_have": ["python", "fastapi"],
            "preferred": ["postgres", "redis"],
        },
        experiences=[
            ResumeItem(
                source_id="exp-1",
                source_type="experience",
                name="Original Co — Software Engineer",
                bullets=[_bullet(t) for t in experience_bullets],
            )
        ],
        projects=[
            ResumeItem(
                source_id="proj-1",
                source_type="project",
                name="Side Project",
                bullets=[_bullet(t) for t in (project_bullets or [])],
            )
        ],
    )


# ---- Summary stripping -----------------------------------------------


def test_summary_section_is_stripped(tmp_path: Path) -> None:
    """Generated resumes never include a Summary, regardless of what
    the user-uploaded source DOCX contained."""
    src = tmp_path / "source.docx"
    out = tmp_path / "out.docx"
    _build_source(src)
    document = _ir(experience_bullets=["Designed scalable API layer."])
    report = patch_resume_docx(src, document, output_path=out)
    assert report.success is True
    doc = Document(str(out))
    paragraph_texts = [p.text for p in doc.paragraphs]
    # No paragraph should contain the original summary copy or a
    # "Summary" heading anywhere in the output.
    assert all("Old summary about the candidate" not in t for t in paragraph_texts)
    assert all(t.strip().lower() != "summary" for t in paragraph_texts)


# ---- Skills ---------------------------------------------------------


def test_skills_section_rewritten(tmp_path: Path) -> None:
    src = tmp_path / "source.docx"
    out = tmp_path / "out.docx"
    _build_source(src)
    document = _ir(experience_bullets=["x"])
    patch_resume_docx(src, document, output_path=out)
    doc = Document(str(out))
    skills_idx = next(
        i for i, p in enumerate(doc.paragraphs) if p.text.strip() == "Skills"
    )
    body = doc.paragraphs[skills_idx + 1 : skills_idx + 3]
    bodies = [p.text for p in body if p.text.strip()]
    assert any("Must Have" in line and "python" in line for line in bodies)
    assert any("Preferred" in line and "postgres" in line for line in bodies)


# ---- Bullets --------------------------------------------------------


def test_experience_bullets_are_swapped_in_place(tmp_path: Path) -> None:
    src = tmp_path / "source.docx"
    out = tmp_path / "out.docx"
    _build_source(src)
    document = _ir(experience_bullets=["NEW: built and shipped", "NEW: scaled service"])
    patch_resume_docx(src, document, output_path=out)
    doc = Document(str(out))
    bullets = [p.text for p in doc.paragraphs if p.style.name.startswith("List")]
    assert "NEW: built and shipped" in bullets
    assert "NEW: scaled service" in bullets
    assert "Built the old thing" not in bullets


def test_surplus_bullets_are_appended(tmp_path: Path) -> None:
    src = tmp_path / "source.docx"
    out = tmp_path / "out.docx"
    _build_source(src)
    document = _ir(
        experience_bullets=[
            "bullet 1",
            "bullet 2",
            "bullet 3 (overflow)",
        ]
    )
    patch_resume_docx(src, document, output_path=out)
    doc = Document(str(out))
    bullets = [
        p.text for p in doc.paragraphs if p.style.name.startswith("List") and p.text.strip()
    ]
    assert "bullet 3 (overflow)" in bullets


def test_deficit_bullets_are_blanked_not_removed(tmp_path: Path) -> None:
    src = tmp_path / "source.docx"
    out = tmp_path / "out.docx"
    _build_source(src)
    document = _ir(experience_bullets=["only one"])
    patch_resume_docx(src, document, output_path=out)
    doc = Document(str(out))
    # The original DOCX had two List Bullet paragraphs in Experience;
    # we should still see two paragraphs styled as List Bullet under
    # Experience, just the second one is empty.
    bullets_in_exp = [
        p
        for p in doc.paragraphs
        if p.style.name.startswith("List")
    ]
    assert len(bullets_in_exp) >= 2
    assert any(p.text == "only one" for p in bullets_in_exp)
    assert any(p.text == "" for p in bullets_in_exp)


# ---- Section visibility ---------------------------------------------


def test_sections_not_in_section_order_are_blanked(tmp_path: Path) -> None:
    src = tmp_path / "source.docx"
    out = tmp_path / "out.docx"
    _build_source(src)
    document = _ir(experience_bullets=["x"])
    document.section_order = ["summary", "skills", "experience", "projects"]
    patch_resume_docx(src, document, output_path=out)
    doc = Document(str(out))
    # The Awards section should still have its heading but no body.
    awards_idx = next(
        i for i, p in enumerate(doc.paragraphs) if p.text.strip() == "Awards"
    )
    # The single body paragraph that followed should now be empty.
    assert doc.paragraphs[awards_idx + 1].text == ""


# ---- Fallback signal ------------------------------------------------


def test_missing_source_raises_patchfallback(tmp_path: Path) -> None:
    document = _ir(experience_bullets=["x"])
    with pytest.raises(PatchFallback):
        patch_resume_docx(
            tmp_path / "does-not-exist.docx",
            document,
            output_path=tmp_path / "out.docx",
        )


# ---- Report ---------------------------------------------------------


def test_report_records_what_was_changed(tmp_path: Path) -> None:
    src = tmp_path / "source.docx"
    out = tmp_path / "out.docx"
    _build_source(src)
    document = _ir(experience_bullets=["new b1", "new b2"])
    report = patch_resume_docx(src, document, output_path=out)
    kinds = {op.kind for op in report.operations}
    # ``section_drop`` covers the summary strip; ``skills`` and
    # ``bullet`` cover the in-place rewrites.
    assert {"section_drop", "skills", "bullet"} <= kinds
    assert report.output_path == out
