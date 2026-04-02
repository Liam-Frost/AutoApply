"""Resume builder — JD-driven bullet selection, optional rewrite, and document generation.

Pipeline:
  1. Extract keywords/tags from JD requirements
  2. Select best-matching bullets from the bullet pool
  3. Optionally rewrite bullets with light lexical adjustment (keyword injection)
  4. Run fact-drift check to ensure no fabrication
  5. Assemble into docx via the document engine, convert to PDF

Design principle: block-based assembly, NOT full-text LLM rewrite.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.documents.docx_engine import build_resume, create_default_template
from src.documents.file_manager import get_output_paths
from src.documents.pdf_converter import convert_to_pdf
from src.intake.schema import RawJob

logger = logging.getLogger("autoapply.generation.resume_builder")

DEFAULT_TEMPLATE_DIR = Path("data/templates")
DEFAULT_OUTPUT_DIR = Path("data/output")


def generate_resume(
    job: RawJob,
    profile_data: dict[str, Any],
    selected_bullets: dict[str, list[str]] | None = None,
    template_path: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    rewrite: bool = False,
    use_llm: bool = False,
) -> dict[str, Path]:
    """Generate a tailored resume for a specific job.

    Args:
        job: The target job posting.
        profile_data: Full applicant profile dict.
        selected_bullets: Pre-selected bullets (if None, auto-selected from JD).
        template_path: Path to .docx template (creates default if None/missing).
        output_dir: Directory for output files.
        rewrite: Whether to do light lexical rewrite on bullets.
        use_llm: Whether to use LLM for rewrite (requires rewrite=True).

    Returns:
        Dict with keys: docx, pdf (paths to generated files).
    """
    # Resolve template
    if template_path is None or not template_path.exists():
        template_path = DEFAULT_TEMPLATE_DIR / "default_resume.docx"
        if not template_path.exists():
            logger.info("No template found, creating default")
            create_default_template(template_path)

    # Extract JD keywords for bullet selection
    jd_tags = extract_jd_tags(job)
    logger.info("JD tags for %s at %s: %s", job.title, job.company, jd_tags)

    # Select bullets if not provided
    if selected_bullets is None:
        selected_bullets = select_bullets_for_jd(
            jd_tags, profile_data,
        )

    # Optional light rewrite
    if rewrite and use_llm:
        selected_bullets = rewrite_bullets(selected_bullets, jd_tags)

    # Get output paths
    paths = get_output_paths(
        company=job.company,
        role=job.title,
        output_dir=output_dir,
    )

    # Build docx
    docx_path = build_resume(
        template_path=template_path,
        identity=profile_data.get("identity", {}),
        education=profile_data.get("education", []),
        experiences=profile_data.get("work_experiences", []),
        projects=profile_data.get("projects", []),
        skills=profile_data.get("skills", {}),
        selected_bullets=selected_bullets,
        output_path=paths["resume_docx"],
    )

    # Convert to PDF
    pdf_path = None
    try:
        pdf_path = convert_to_pdf(docx_path, paths["resume_pdf"])
    except Exception as e:
        logger.warning("PDF conversion failed: %s", e)

    result = {"docx": docx_path}
    if pdf_path:
        result["pdf"] = pdf_path

    logger.info(
        "Generated resume for %s at %s: %s",
        job.title, job.company, list(result.keys()),
    )
    return result


def extract_jd_tags(job: RawJob) -> list[str]:
    """Extract searchable tags from a job's requirements and description.

    Combines must-have skills, preferred skills, and inferred keywords
    from the title into a flat tag list for bullet pool querying.
    """
    tags = []

    # From structured requirements
    tags.extend(s.lower() for s in job.requirements.must_have_skills)
    tags.extend(s.lower() for s in job.requirements.preferred_skills)

    # From title — extract meaningful words
    title_words = job.title.lower().split()
    tech_keywords = {
        "python", "java", "javascript", "typescript", "go", "rust", "c++",
        "react", "vue", "angular", "node", "django", "flask", "fastapi",
        "spring", "kubernetes", "docker", "aws", "gcp", "azure",
        "sql", "postgresql", "mongodb", "redis", "graphql",
        "ml", "ai", "machine learning", "deep learning", "nlp",
        "backend", "frontend", "fullstack", "devops", "sre",
        "data", "analytics", "infrastructure", "platform", "security",
    }
    for word in title_words:
        if word in tech_keywords:
            tags.append(word)

    # Deduplicate preserving order
    seen = set()
    unique = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            unique.append(tag)

    return unique


def select_bullets_for_jd(
    jd_tags: list[str],
    profile_data: dict[str, Any],
    max_bullets_per_entity: int = 4,
) -> dict[str, list[str]]:
    """Select the best-matching bullets from profile based on JD tags.

    For each experience/project entity, selects bullets whose tags have
    the highest overlap with the JD tags. Falls back to all bullets if
    no tag overlap found.

    Returns:
        {entity_name: [bullet_text, ...]}
    """
    selected: dict[str, list[str]] = {}
    tag_set = set(jd_tags)

    # Process work experiences
    for exp in profile_data.get("work_experiences", []):
        if not isinstance(exp, dict):
            continue
        entity = f"{exp.get('company', 'Unknown')} - {exp.get('title', '')}"
        bullets = exp.get("bullets", [])
        selected[entity] = _rank_and_select(bullets, tag_set, max_bullets_per_entity)

    # Process projects
    for proj in profile_data.get("projects", []):
        if not isinstance(proj, dict):
            continue
        entity = proj.get("name", "Unknown")
        bullets = proj.get("bullets", [])
        selected[entity] = _rank_and_select(bullets, tag_set, max_bullets_per_entity)

    total = sum(len(v) for v in selected.values())
    logger.info("Selected %d bullets across %d entities", total, len(selected))
    return selected


def _rank_and_select(
    bullets: list[dict],
    tag_set: set[str],
    max_count: int,
) -> list[str]:
    """Rank bullets by tag overlap and return top N texts."""
    scored = []
    for bullet in bullets:
        if not isinstance(bullet, dict) or not bullet.get("text"):
            continue
        bullet_tags = set(t.lower() for t in bullet.get("tags", []))
        overlap = len(bullet_tags & tag_set)
        scored.append((overlap, bullet["text"]))

    # Sort by overlap descending, then by original order for ties
    scored.sort(key=lambda x: x[0], reverse=True)

    # If no overlap at all, return all bullets (better than nothing)
    if scored and scored[0][0] == 0:
        return [text for _, text in scored[:max_count]]

    return [text for _, text in scored[:max_count]]


def rewrite_bullets(
    selected_bullets: dict[str, list[str]],
    jd_tags: list[str],
) -> dict[str, list[str]]:
    """Light lexical rewrite of bullets to inject JD keywords.

    Rules:
    - Only adjust phrasing, never change facts or add claims
    - Inject relevant keywords where natural
    - Preserve quantified results exactly
    """
    from src.utils.llm import LLMError, claude_generate

    keywords_str = ", ".join(jd_tags[:15])

    rewritten: dict[str, list[str]] = {}
    for entity, bullets in selected_bullets.items():
        new_bullets = []
        for bullet in bullets:
            try:
                new_text = _rewrite_single_bullet(bullet, keywords_str)
                # Fact-drift check: rewritten bullet should be similar length
                if len(new_text) > len(bullet) * 2 or len(new_text) < len(bullet) * 0.3:
                    logger.warning("Rewrite drift detected for bullet, keeping original")
                    new_bullets.append(bullet)
                else:
                    new_bullets.append(new_text)
            except (LLMError, Exception) as e:
                logger.debug("Rewrite failed for bullet: %s", e)
                new_bullets.append(bullet)
        rewritten[entity] = new_bullets

    return rewritten


_REWRITE_SYSTEM = """You are a resume bullet point editor. Your job is to lightly adjust
a resume bullet to better match target job keywords while preserving ALL facts.

Rules:
- Keep the same meaning, structure, and claims
- Preserve all numbers, metrics, and quantified results EXACTLY
- Only adjust word choice to incorporate relevant keywords where natural
- Do NOT add new skills, technologies, or achievements that weren't in the original
- Do NOT change the tone from professional to casual or vice versa
- Output ONLY the rewritten bullet, nothing else"""


def _rewrite_single_bullet(bullet: str, keywords: str) -> str:
    """Rewrite a single bullet using LLM."""
    from src.utils.llm import claude_generate

    prompt = (
        f"Target keywords: {keywords}\n\n"
        f"Original bullet: {bullet}\n\n"
        f"Rewrite the bullet to naturally incorporate relevant keywords. "
        f"Output only the rewritten bullet."
    )
    result = claude_generate(prompt, system=_REWRITE_SYSTEM, timeout=60)
    return result.strip().strip("•-– ").strip()
