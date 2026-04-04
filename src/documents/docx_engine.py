"""Word document creation and editing engine.

Builds tailored resumes from a base template using block-based assembly.
The template uses {{PLACEHOLDER}} syntax for variable substitution.
Section blocks (experience, education, skills, projects) are rebuilt from
the applicant's bullet pool selection.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml import OxmlElement

logger = logging.getLogger("autoapply.documents.docx_engine")

PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


# ---------------------------------------------------------------------------
# Core document operations
# ---------------------------------------------------------------------------


def substitute_placeholders(doc: Document, variables: dict[str, str]) -> None:
    """Replace {{KEY}} placeholders in all paragraphs and table cells."""
    for para in _iter_paragraphs(doc):
        _substitute_para(para, variables)


def _iter_paragraphs(doc: Document):
    """Yield all paragraphs including those inside tables."""
    yield from doc.paragraphs
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs


def _substitute_para(para, variables: dict[str, str]) -> None:
    """Substitute placeholders within a paragraph, preserving run formatting."""
    # Consolidate paragraph text first for matching
    full_text = "".join(run.text for run in para.runs)
    if "{{" not in full_text:
        return

    # Replace in the full text
    def replacer(m: re.Match) -> str:
        key = m.group(1)
        return variables.get(key, m.group(0))

    new_text = PLACEHOLDER_RE.sub(replacer, full_text)

    if new_text == full_text:
        return

    # Write back to first run, clear the rest
    if para.runs:
        para.runs[0].text = new_text
        for run in para.runs[1:]:
            run.text = ""


# ---------------------------------------------------------------------------
# Block-based resume builder
# ---------------------------------------------------------------------------


def build_resume(
    template_path: Path,
    identity: dict[str, Any],
    education: list[dict],
    experiences: list[dict],
    projects: list[dict],
    skills: dict[str, list[str]],
    selected_bullets: dict[str, list[str]],  # entity_name -> [bullet texts]
    output_path: Path,
) -> Path:
    """Build a tailored resume from a template and structured data.

    Args:
        template_path: Base .docx template.
        identity: Identity section from profile.
        education: List of education records.
        experiences: List of work experience records.
        projects: List of project records.
        skills: Skills dict by category.
        selected_bullets: Maps entity (company/project name) to selected bullet texts.
        output_path: Where to save the generated .docx.

    Returns:
        Path to the generated .docx file.
    """
    doc = Document(str(template_path))

    # Step 1: Substitute header placeholders
    variables = _build_header_variables(identity)
    substitute_placeholders(doc, variables)

    # Step 2: Rebuild section blocks
    _rebuild_education_block(doc, education)
    _rebuild_experience_block(doc, experiences, selected_bullets)
    _rebuild_projects_block(doc, projects, selected_bullets)
    _rebuild_skills_block(doc, skills)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    logger.info("Saved resume to %s", output_path)
    return output_path


def _build_header_variables(identity: dict) -> dict[str, str]:
    return {
        "FULL_NAME": identity.get("full_name", ""),
        "EMAIL": identity.get("email", ""),
        "PHONE": identity.get("phone", ""),
        "LOCATION": identity.get("location", ""),
        "LINKEDIN": identity.get("linkedin_url", ""),
        "GITHUB": identity.get("github_url", ""),
        "PORTFOLIO": identity.get("portfolio_url", ""),
    }


def _find_section_paragraph(doc: Document, marker: str) -> int | None:
    """Find the index of the paragraph containing the section marker."""
    for i, para in enumerate(doc.paragraphs):
        if marker in para.text:
            return i
    return None


def _clear_section_content(doc: Document, start_idx: int, next_markers: list[str]) -> int:
    """Remove paragraphs from start_idx until a next section marker is hit.

    Returns the index where the next section begins.
    """
    i = start_idx + 1
    while i < len(doc.paragraphs):
        text = doc.paragraphs[i].text.strip()
        if any(m in text for m in next_markers):
            break
        p = doc.paragraphs[i]._element
        p.getparent().remove(p)
        # Note: after removal, len(doc.paragraphs) shrinks, but i stays same
    return i


def _add_paragraph_after(
    doc: Document, ref_idx: int, text: str, style: str = "Normal", bold: bool = False
) -> None:
    """Insert a new paragraph after the paragraph at ref_idx."""
    ref_para = doc.paragraphs[ref_idx]
    new_para = OxmlElement("w:p")
    ref_para._element.addnext(new_para)

    # Reload reference after DOM change
    target_para = doc.paragraphs[ref_idx + 1]
    run = target_para.add_run(text)
    run.bold = bold
    try:
        target_para.style = doc.styles[style]
    except KeyError:
        pass


# ---------------------------------------------------------------------------
# Section rebuilders — these operate on known template markers
# ---------------------------------------------------------------------------


def _rebuild_education_block(doc: Document, education: list[dict]) -> None:
    """Replace {{EDUCATION_BLOCK}} section with formatted education entries."""
    idx = _find_section_paragraph(doc, "{{EDUCATION_BLOCK}}")
    if idx is None:
        logger.debug("No {{EDUCATION_BLOCK}} marker found in template")
        return

    # Clear the marker text and any existing sample content below it (P1 fix)
    if doc.paragraphs[idx].runs:
        doc.paragraphs[idx].runs[0].text = ""
    _clear_section_content(
        doc, idx, ["{{EXPERIENCE_BLOCK}}", "{{PROJECTS_BLOCK}}", "{{SKILLS_BLOCK}}"]
    )

    insert_idx = idx
    for edu in education:
        institution = edu.get("institution", "")
        degree = f"{edu.get('degree', '')} in {edu.get('field', '')}"
        dates = f"{edu.get('start_date', '')} – {edu.get('end_date', '')}"
        gpa = f"GPA: {edu['gpa']}" if edu.get("gpa") else ""

        _add_paragraph_after(doc, insert_idx, f"{institution} | {dates}", bold=True)
        insert_idx += 1
        _add_paragraph_after(doc, insert_idx, degree)
        insert_idx += 1
        if gpa:
            _add_paragraph_after(doc, insert_idx, gpa)
            insert_idx += 1

        courses = edu.get("relevant_courses", [])
        if courses:
            course_names = ", ".join(c.get("name", "") for c in courses if isinstance(c, dict))
            _add_paragraph_after(doc, insert_idx, f"Relevant coursework: {course_names}")
            insert_idx += 1


def _rebuild_experience_block(
    doc: Document,
    experiences: list[dict],
    selected_bullets: dict[str, list[str]],
) -> None:
    """Replace {{EXPERIENCE_BLOCK}} with tailored experience entries."""
    idx = _find_section_paragraph(doc, "{{EXPERIENCE_BLOCK}}")
    if idx is None:
        logger.debug("No {{EXPERIENCE_BLOCK}} marker found in template")
        return

    if doc.paragraphs[idx].runs:
        doc.paragraphs[idx].runs[0].text = ""
    _clear_section_content(doc, idx, ["{{PROJECTS_BLOCK}}", "{{SKILLS_BLOCK}}"])

    insert_idx = idx
    for exp in experiences:
        company = exp.get("company", "")
        title = exp.get("title", "")
        dates = f"{exp.get('start_date', '')} – {exp.get('end_date', '')}"
        location = exp.get("location", "")

        _add_paragraph_after(doc, insert_idx, f"{company} | {location}", bold=True)
        insert_idx += 1
        _add_paragraph_after(doc, insert_idx, f"{title} | {dates}")
        insert_idx += 1

        entity_key = f"{company} - {title}"
        bullets = selected_bullets.get(entity_key, [])
        if not bullets:
            # Fall back to all bullets in the experience
            bullets = [b["text"] for b in exp.get("bullets", []) if isinstance(b, dict)]

        for bullet_text in bullets:
            _add_paragraph_after(doc, insert_idx, f"• {bullet_text}")
            insert_idx += 1


def _rebuild_projects_block(
    doc: Document,
    projects: list[dict],
    selected_bullets: dict[str, list[str]],
) -> None:
    """Replace {{PROJECTS_BLOCK}} with tailored project entries."""
    idx = _find_section_paragraph(doc, "{{PROJECTS_BLOCK}}")
    if idx is None:
        logger.debug("No {{PROJECTS_BLOCK}} marker found in template")
        return

    if doc.paragraphs[idx].runs:
        doc.paragraphs[idx].runs[0].text = ""
    _clear_section_content(doc, idx, ["{{SKILLS_BLOCK}}"])

    insert_idx = idx
    for proj in projects:
        name = proj.get("name", "")
        tech = ", ".join(proj.get("tech_stack", []))
        dates = f"{proj.get('start_date', '')} – {proj.get('end_date', '')}".strip(" –")

        header = f"{name} | {tech}"
        if dates:
            header += f" | {dates}"

        _add_paragraph_after(doc, insert_idx, header, bold=True)
        insert_idx += 1

        bullets = selected_bullets.get(name, [])
        if not bullets:
            bullets = [b["text"] for b in proj.get("bullets", []) if isinstance(b, dict)]

        for bullet_text in bullets:
            _add_paragraph_after(doc, insert_idx, f"• {bullet_text}")
            insert_idx += 1


def _rebuild_skills_block(doc: Document, skills: dict[str, list[str]]) -> None:
    """Replace {{SKILLS_BLOCK}} with a formatted skills summary."""
    idx = _find_section_paragraph(doc, "{{SKILLS_BLOCK}}")
    if idx is None:
        logger.debug("No {{SKILLS_BLOCK}} marker found in template")
        return

    if doc.paragraphs[idx].runs:
        doc.paragraphs[idx].runs[0].text = ""
    _clear_section_content(doc, idx, [])  # last section — clear to end of doc

    insert_idx = idx
    label_map = {
        "languages": "Languages",
        "frameworks": "Frameworks",
        "databases": "Databases",
        "tools": "Tools & DevOps",
        "domains": "Domains",
    }
    for key, label in label_map.items():
        items = skills.get(key, [])
        if items:
            _add_paragraph_after(doc, insert_idx, f"{label}: {', '.join(items)}")
            insert_idx += 1


# ---------------------------------------------------------------------------
# Minimal template creator (used when no template .docx exists yet)
# ---------------------------------------------------------------------------


def create_default_template(output_path: Path) -> Path:
    """Create a basic resume template .docx with all expected markers."""
    doc = Document()

    # Header
    doc.add_heading("{{FULL_NAME}}", level=1)
    doc.add_paragraph("{{EMAIL}} | {{PHONE}} | {{LOCATION}}")
    doc.add_paragraph("{{LINKEDIN}} | {{GITHUB}}")

    doc.add_heading("Education", level=2)
    doc.add_paragraph("{{EDUCATION_BLOCK}}")

    doc.add_heading("Experience", level=2)
    doc.add_paragraph("{{EXPERIENCE_BLOCK}}")

    doc.add_heading("Projects", level=2)
    doc.add_paragraph("{{PROJECTS_BLOCK}}")

    doc.add_heading("Skills", level=2)
    doc.add_paragraph("{{SKILLS_BLOCK}}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    logger.info("Created default template at %s", output_path)
    return output_path
