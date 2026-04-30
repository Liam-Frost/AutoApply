"""Cover letter generator — structure-constrained semi-generation.

Structure:
  1. Opening: role + reason for interest
  2. Middle: 2-3 best-matching evidence points from profile
  3. Company tie-in: why this specific company
  4. Close: availability / enthusiasm

All LLM output is bounded by a structural template to prevent
style drift and hallucination.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.documents.docx_engine import build_cover_letter_from_ir
from src.documents.file_manager import get_output_paths
from src.documents.pdf_converter import convert_to_pdf
from src.documents.templates import TemplateManifest, default_manifest, ensure_template_package
from src.generation.evidence import select_relevant_evidence
from src.generation.ir import CoverLetterDocument, CoverLetterParagraph
from src.generation.validator import validate_cover_letter_artifacts
from src.intake.schema import RawJob
from src.utils.llm import LLMError, generate_text

logger = logging.getLogger("autoapply.generation.cover_letter")

DEFAULT_OUTPUT_DIR = Path("data/output")


def generate_cover_letter(
    job: RawJob,
    profile_data: dict[str, Any],
    evidence_bullets: list[str] | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    use_llm: bool = True,
    template_id: str = "classic_v1",
    template_path: Path | None = None,
) -> dict[str, Any]:
    """Generate a tailored cover letter for a specific job.

    Args:
        job: Target job posting.
        profile_data: Full applicant profile dict.
        evidence_bullets: Pre-selected evidence points. If None, auto-selected.
        output_dir: Directory for output files.
        use_llm: Whether to use LLM for generation (if False, returns template only).

    Returns:
        Dict with generated paths plus the CoverLetterDocument IR and validation result.
    """
    identity = profile_data.get("identity", {})
    template_manifest = _manifest_for_template_path(template_path)
    if template_path is None or not template_path.exists():
        package = ensure_template_package("cover_letter", template_id)
        template_path = package.template_path
        template_manifest = package.manifest
    elif template_manifest is None:
        template_manifest = default_manifest("cover_letter")

    # Select evidence points if not provided
    if evidence_bullets is None:
        evidence_bullets = _select_evidence(job, profile_data)

    if use_llm:
        try:
            text = _generate_with_llm(job, profile_data, evidence_bullets)
        except (LLMError, Exception) as e:
            logger.warning("LLM cover letter generation failed (%s), using template", e)
            text = _generate_template(job, identity, evidence_bullets)
    else:
        text = _generate_template(job, identity, evidence_bullets)

    paths = get_output_paths(
        company=job.company,
        role=job.title,
        output_dir=output_dir,
    )

    document = build_cover_letter_document(
        job=job,
        profile_data=profile_data,
        body_text=text,
        evidence_bullets=evidence_bullets,
    )
    document = _fit_cover_letter_document(document, template_manifest)
    docx_path = build_cover_letter_from_ir(
        document,
        paths["cover_docx"],
        template_path=template_path,
        manifest=template_manifest,
    )

    pdf_path = None
    try:
        pdf_path = convert_to_pdf(docx_path, paths["cover_pdf"])
    except Exception as e:
        logger.warning("Cover letter PDF conversion failed: %s", e)

    validation = validate_cover_letter_artifacts(
        docx_path=docx_path,
        pdf_path=pdf_path,
        pdf_attempted=True,
        max_pages=template_manifest.capacity.max_pages,
    )

    # Keep a text sidecar for easy inspection, but DOCX/PDF are the primary artifacts.
    txt_path = docx_path.with_suffix(".txt")
    txt_path.write_text(text, encoding="utf-8")

    logger.info("Generated cover letter for %s at %s", job.title, job.company)
    result: dict[str, Any] = {
        "text": text,
        "txt": txt_path,
        "docx": docx_path,
        "ir": document,
        "validation": validation,
    }
    if pdf_path:
        result["pdf"] = pdf_path
    return result


def build_cover_letter_document(
    *,
    job: RawJob,
    profile_data: dict[str, Any],
    body_text: str,
    evidence_bullets: list[str],
) -> CoverLetterDocument:
    """Create a structured cover letter IR from generated body text."""
    identity = profile_data.get("identity", {})
    return CoverLetterDocument(
        recipient={"company": job.company, "hiring_manager": None},
        applicant={
            "name": identity.get("full_name", ""),
            "email": identity.get("email", ""),
            "phone": identity.get("phone", ""),
        },
        paragraphs=_cover_paragraphs_from_text(body_text, evidence_bullets),
        metadata={"target_role": job.title, "company": job.company},
    )


def _fit_cover_letter_document(
    document: CoverLetterDocument,
    manifest: TemplateManifest,
) -> CoverLetterDocument:
    if manifest.document_type != "cover_letter":
        return document
    fitted = document.model_copy(deep=True)
    body_config = manifest.sections.get("body")
    if body_config and body_config.max_items:
        fitted.paragraphs = fitted.paragraphs[: body_config.max_items]
    fitted.metadata = {
        **fitted.metadata,
        "template_id": manifest.template_id,
        "template_capacity": manifest.capacity.model_dump(mode="json"),
    }
    return fitted


def _manifest_for_template_path(template_path: Path | None) -> TemplateManifest | None:
    if template_path is None:
        return None
    manifest_path = template_path.parent / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        return TemplateManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Ignoring invalid template manifest %s: %s", manifest_path, exc)
        return None


_CL_SYSTEM = """You are a professional cover letter writer. Generate a concise, compelling
cover letter following this EXACT structure:

1. OPENING (2-3 sentences): State the role and express genuine interest. Mention one specific
   reason this company/team stands out.

2. EVIDENCE (2-3 short paragraphs): Each paragraph maps one of the applicant's experiences
   to a job requirement. Use specific metrics or outcomes when available. Do NOT fabricate
   any experience — only reference what is provided in the profile.

3. COMPANY TIE-IN (1-2 sentences): Connect the applicant's goals or values to the company's
   mission or recent work. Be specific, not generic.

4. CLOSE (1-2 sentences): Express enthusiasm and availability. Keep it professional and brief.

Rules:
- Total length: 250-400 words
- Tone: confident but not arrogant, specific but not verbose
- Do NOT use clichés like "I am writing to express my interest"
  or "I believe I would be a great fit"
- Do NOT fabricate experiences, skills, or achievements not in the provided profile
- Do NOT include a greeting line (Dear Hiring Manager)
  or sign-off (Sincerely) — those are added separately
- Output ONLY the body text of the cover letter"""


def _generate_with_llm(
    job: RawJob,
    profile_data: dict[str, Any],
    evidence_bullets: list[str],
) -> str:
    """Generate cover letter body using Claude CLI."""
    identity = profile_data.get("identity", {})
    skills = profile_data.get("skills", {})

    # Build context for the LLM
    evidence_text = "\n".join(f"- {b}" for b in evidence_bullets)

    skill_summary = []
    for category, items in skills.items():
        if isinstance(items, list) and items:
            skill_summary.append(f"{category}: {', '.join(items[:8])}")
    skills_text = "\n".join(skill_summary)

    prompt = f"""Write a cover letter body for this application:

<job>
Company: {job.company}
Role: {job.title}
Location: {job.location or "Not specified"}

Job Description:
{(job.description or "")[:3000]}
</job>

<applicant>
Name: {identity.get("full_name", "")}
Education: {_format_education_brief(profile_data.get("education", []))}

Key evidence points from my experience:
{evidence_text}

Skills:
{skills_text}
</applicant>

Generate the cover letter body following the structure in the system prompt."""

    raw = generate_text(prompt, system=_CL_SYSTEM, timeout=90)
    return raw.strip()


def _generate_template(
    job: RawJob,
    identity: dict[str, Any],
    evidence_bullets: list[str],
) -> str:
    """Generate a template-based cover letter (no LLM)."""
    opening = (
        f"I am excited about the {job.title} position at {job.company}. "
        f"The opportunity to contribute to your team aligns well with my background "
        f"and career goals."
    )

    evidence_parts = []
    for i, bullet in enumerate(evidence_bullets[:3]):
        evidence_parts.append(bullet)

    evidence_text = (
        "\n\n".join(evidence_parts)
        if evidence_parts
        else ("My technical background and project experience have prepared me well for this role.")
    )

    close = (
        f"I would welcome the opportunity to discuss how my skills and experience "
        f"can contribute to {job.company}'s goals. I am available to start "
        f"at your earliest convenience."
    )

    return f"{opening}\n\n{evidence_text}\n\n{close}"


def _select_evidence(
    job: RawJob,
    profile_data: dict[str, Any],
    max_points: int = 3,
) -> list[str]:
    """Select the strongest evidence points from profile for this job.

    Picks bullets with highest tag overlap with JD requirements.
    """
    from src.generation.resume_builder import extract_jd_tags

    jd_tags = extract_jd_tags(job)
    evidence = select_relevant_evidence(jd_tags, profile_data, max_total=max_points)
    return [
        f"At {item.source_entity}, {item.text}" if item.source_entity else item.text
        for item in evidence[:max_points]
    ]


def _cover_paragraphs_from_text(
    body_text: str, evidence_bullets: list[str]
) -> list[CoverLetterParagraph]:
    raw_paragraphs = [part.strip() for part in body_text.split("\n\n") if part.strip()]
    if not raw_paragraphs:
        return []

    paragraph_types = ["opening", "experience_evidence", "experience_evidence", "company_fit"]
    paragraphs: list[CoverLetterParagraph] = []
    for index, text in enumerate(raw_paragraphs):
        paragraph_type = paragraph_types[index] if index < len(paragraph_types) else "closing"
        source_ids = []
        if paragraph_type == "experience_evidence":
            source_ids = [str(i) for i, evidence in enumerate(evidence_bullets) if evidence in text]
        paragraphs.append(
            CoverLetterParagraph(
                type=paragraph_type,  # type: ignore[arg-type]
                text=text,
                source_ids=source_ids,
            )
        )
    if paragraphs:
        paragraphs[-1].type = "closing"
    return paragraphs


def _format_education_brief(education: list[dict]) -> str:
    """One-line education summary for LLM context."""
    parts = []
    for edu in education:
        if isinstance(edu, dict):
            degree = edu.get("degree", "")
            field = edu.get("field", "")
            institution = edu.get("institution", "")
            if degree or institution:
                parts.append(f"{degree} in {field}, {institution}".strip(", "))
    return "; ".join(parts) if parts else "Not specified"
