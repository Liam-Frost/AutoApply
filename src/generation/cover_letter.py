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

from src.documents.file_manager import get_output_paths
from src.intake.schema import RawJob
from src.utils.llm import LLMError, claude_generate

logger = logging.getLogger("autoapply.generation.cover_letter")

DEFAULT_OUTPUT_DIR = Path("data/output")


def generate_cover_letter(
    job: RawJob,
    profile_data: dict[str, Any],
    evidence_bullets: list[str] | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    use_llm: bool = True,
) -> dict[str, Path | str]:
    """Generate a tailored cover letter for a specific job.

    Args:
        job: Target job posting.
        profile_data: Full applicant profile dict.
        evidence_bullets: Pre-selected evidence points. If None, auto-selected.
        output_dir: Directory for output files.
        use_llm: Whether to use LLM for generation (if False, returns template only).

    Returns:
        Dict with keys: text (str), txt (Path to .txt file).
    """
    identity = profile_data.get("identity", {})
    applicant_name = identity.get("full_name", "Applicant")

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

    # Save to file
    paths = get_output_paths(
        company=job.company,
        role=job.title,
        output_dir=output_dir,
    )
    txt_path = paths["cover_docx"].with_suffix(".txt")
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text(text, encoding="utf-8")

    logger.info("Generated cover letter for %s at %s", job.title, job.company)
    return {"text": text, "txt": txt_path}


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
- Do NOT use clichés like "I am writing to express my interest" or "I believe I would be a great fit"
- Do NOT fabricate experiences, skills, or achievements not in the provided profile
- Do NOT include a greeting line (Dear Hiring Manager) or sign-off (Sincerely) — those are added separately
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
Location: {job.location or 'Not specified'}

Job Description:
{(job.description or '')[:3000]}
</job>

<applicant>
Name: {identity.get('full_name', '')}
Education: {_format_education_brief(profile_data.get('education', []))}

Key evidence points from my experience:
{evidence_text}

Skills:
{skills_text}
</applicant>

Generate the cover letter body following the structure in the system prompt."""

    raw = claude_generate(prompt, system=_CL_SYSTEM, timeout=90)
    return raw.strip()


def _generate_template(
    job: RawJob,
    identity: dict[str, Any],
    evidence_bullets: list[str],
) -> str:
    """Generate a template-based cover letter (no LLM)."""
    name = identity.get("full_name", "Applicant")

    opening = (
        f"I am excited about the {job.title} position at {job.company}. "
        f"The opportunity to contribute to your team aligns well with my background "
        f"and career goals."
    )

    evidence_parts = []
    for i, bullet in enumerate(evidence_bullets[:3]):
        evidence_parts.append(bullet)

    evidence_text = "\n\n".join(evidence_parts) if evidence_parts else (
        "My technical background and project experience have prepared me well "
        "for this role."
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

    jd_tags = set(extract_jd_tags(job))

    scored: list[tuple[int, str]] = []

    for section in ("work_experiences", "projects"):
        for item in profile_data.get(section, []):
            if not isinstance(item, dict):
                continue
            entity = item.get("company", item.get("name", ""))
            for bullet in item.get("bullets", []):
                if not isinstance(bullet, dict) or not bullet.get("text"):
                    continue
                tags = set(t.lower() for t in bullet.get("tags", []))
                overlap = len(tags & jd_tags)
                # Include entity context for the cover letter
                text = f"At {entity}, {bullet['text']}" if entity else bullet["text"]
                scored.append((overlap, text))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [text for _, text in scored[:max_points]]


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
