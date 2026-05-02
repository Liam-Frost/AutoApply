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
import re
from pathlib import Path
from typing import Any

from src.documents.docx_engine import build_resume_from_ir, create_default_template
from src.documents.file_manager import get_output_paths
from src.documents.latex_engine import build_resume_tex_from_ir, compile_latex_to_pdf
from src.documents.pdf_converter import convert_to_pdf
from src.documents.templates import (
    TemplateManifest,
    default_manifest,
    ensure_template_package,
    load_template_package,
)
from src.generation.evidence import (
    EvidenceBullet,
    collect_profile_evidence,
    evidence_by_entity,
    select_relevant_evidence,
)
from src.generation.fitting import fit_resume_document_to_template
from src.generation.ir import BulletRewriteResult, ResumeDocument, ResumeItem
from src.generation.validator import (
    validate_latex_artifacts,
    validate_resume_artifacts,
    validate_resume_document,
)
from src.intake.schema import RawJob

logger = logging.getLogger("autoapply.generation.resume_builder")

DEFAULT_TEMPLATE_DIR = Path("data/templates")
DEFAULT_OUTPUT_DIR = Path("data/output")


def generate_resume(
    job: RawJob,
    profile_data: dict[str, Any],
    selected_bullets: dict[str, list[str]] | None = None,
    template_path: Path | None = None,
    template_id: str = "ats_single_column_v1",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    rewrite: bool = False,
    use_llm: bool = False,
) -> dict[str, Any]:
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
        Dict with generated paths plus the ResumeDocument IR and validation result.
    """
    # Resolve template package. Visual rules live in template.docx/manifest.json;
    # this pipeline only passes structured content and named style references.
    template_manifest = _manifest_for_template_path(template_path)
    if template_path is None or not template_path.exists():
        package = ensure_template_package("resume", template_id)
        template_path = package.template_path
        template_manifest = package.manifest
    elif template_manifest is None:
        template_manifest = default_manifest("resume")

    if not template_path.exists():
        template_path = DEFAULT_TEMPLATE_DIR / "default_resume.docx"
        if not template_path.exists():
            logger.info("No template found, creating default")
            create_default_template(template_path)

    resume_document = build_resume_document(
        job=job,
        profile_data=profile_data,
        selected_bullets=selected_bullets,
        rewrite=rewrite,
        use_llm=use_llm,
        template_id=template_manifest.template_id,
        template_manifest=template_manifest,
    )
    validation = validate_resume_document(
        resume_document,
        jd_tags=resume_document.metadata.get("jd_tags", []),
        max_bullet_words=template_manifest.capacity.max_words_per_bullet or 32,
        max_estimated_pages=template_manifest.capacity.max_pages,
    )
    if not validation.ok:
        logger.warning(
            "Resume IR validation found blocking issues for %s at %s: %s",
            job.title,
            job.company,
            [issue.type for issue in validation.issues if issue.severity == "error"],
        )

    # Get output paths
    paths = get_output_paths(
        company=job.company,
        role=job.title,
        output_dir=output_dir,
    )

    # Build docx from validated IR
    docx_path = build_resume_from_ir(
        template_path=template_path,
        document=resume_document,
        output_path=paths["resume_docx"],
        manifest=template_manifest,
    )

    # Convert to PDF
    pdf_path = None
    try:
        pdf_path = convert_to_pdf(docx_path, paths["resume_pdf"])
    except Exception as e:
        logger.warning("PDF conversion failed: %s", e)

    validation = validate_resume_artifacts(
        validation,
        docx_path=docx_path,
        pdf_path=pdf_path,
        pdf_attempted=True,
        max_pages=template_manifest.capacity.max_pages,
    )

    result = {
        "docx": docx_path,
        "ir": resume_document,
        "validation": validation,
    }
    if pdf_path:
        result["pdf"] = pdf_path

    logger.info(
        "Generated resume for %s at %s: %s",
        job.title,
        job.company,
        list(result.keys()),
    )
    return result


def generate_resume_latex(
    job: RawJob,
    profile_data: dict[str, Any],
    selected_bullets: dict[str, list[str]] | None = None,
    *,
    template_id: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    rewrite: bool = False,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Generate a tailored resume as LaTeX, with optional PDF compilation."""
    package = load_template_package("resume", template_id)
    if package.manifest.renderer != "latex":
        raise ValueError("Selected resume template is not a LaTeX template.")

    resume_document = build_resume_document(
        job=job,
        profile_data=profile_data,
        selected_bullets=selected_bullets,
        rewrite=rewrite,
        use_llm=use_llm,
        template_id=package.template_id,
        template_manifest=package.manifest,
    )
    validation = validate_resume_document(
        resume_document,
        jd_tags=resume_document.metadata.get("jd_tags", []),
        max_bullet_words=package.manifest.capacity.max_words_per_bullet or 32,
        max_estimated_pages=package.manifest.capacity.max_pages,
    )

    paths = get_output_paths(
        company=job.company,
        role=job.title,
        output_dir=output_dir,
    )
    tex_path = build_resume_tex_from_ir(
        template_path=package.template_path,
        document=resume_document,
        output_path=paths["resume_tex"],
        manifest=package.manifest,
    )

    pdf_path = None
    try:
        pdf_path = compile_latex_to_pdf(tex_path, paths["resume_pdf"])
    except Exception as exc:
        logger.warning("LaTeX resume PDF compilation failed: %s", exc)

    validation = validate_latex_artifacts(
        validation,
        tex_path=tex_path,
        pdf_path=pdf_path,
        pdf_attempted=True,
        max_pages=package.manifest.capacity.max_pages,
    )

    result = {
        "tex": tex_path,
        "ir": resume_document,
        "validation": validation,
    }
    if pdf_path:
        result["pdf"] = pdf_path
    logger.info("Generated LaTeX resume for %s at %s", job.title, job.company)
    return result


def build_resume_document(
    job: RawJob,
    profile_data: dict[str, Any],
    selected_bullets: dict[str, list[str]] | None = None,
    *,
    rewrite: bool = False,
    use_llm: bool = False,
    template_id: str = "ats_single_column_v1",
    template_manifest: TemplateManifest | None = None,
) -> ResumeDocument:
    """Plan a renderer-agnostic resume IR for a target job."""
    template_manifest = template_manifest or default_manifest("resume")
    jd_tags = extract_jd_tags(job)
    logger.info("JD tags for %s at %s: %s", job.title, job.company, jd_tags)

    db_session = _optional_generation_session()
    try:
        evidence = (
            _evidence_from_selected_bullets(profile_data, selected_bullets, jd_tags)
            if selected_bullets is not None
            else select_relevant_evidence(
                jd_tags,
                profile_data,
                max_bullets_per_entity=_max_bullets_per_entity(template_manifest),
                query_text=f"{job.title}\n{job.description or ''}",
                db_session=db_session,
                query_embedding=_job_query_embedding(job),
            )
        )
    finally:
        if db_session is not None:
            db_session.close()
    grouped = evidence_by_entity(evidence)

    if rewrite and use_llm:
        grouped = _rewrite_grouped_evidence(grouped, jd_tags)

    document = ResumeDocument(
        template_id=template_id,
        target_role=job.title,
        company=job.company,
        header=profile_data.get("identity", {}),
        summary=_build_summary(job, profile_data, jd_tags),
        skills=_prioritize_skills(profile_data.get("skills", {}), jd_tags),
        education=profile_data.get("education", []),
        experiences=_build_experience_items(profile_data, grouped),
        projects=_build_project_items(profile_data, grouped),
        section_order=template_manifest.section_order or _plan_section_order(job, profile_data),
        metadata={
            "jd_tags": jd_tags,
            "selected_evidence_count": sum(len(items) for items in grouped.values()),
        },
    )
    return fit_resume_document_to_template(document, template_manifest)


def _evidence_from_selected_bullets(
    profile_data: dict[str, Any],
    selected_bullets: dict[str, list[str]],
    jd_tags: list[str],
) -> list[EvidenceBullet]:
    all_evidence = evidence_by_entity(collect_profile_evidence(profile_data))
    tag_set = {_normalize_tag(tag) for tag in jd_tags}
    selected: list[EvidenceBullet] = []

    for entity, bullet_texts in selected_bullets.items():
        candidates = all_evidence.get(entity, [])
        for index, text in enumerate(bullet_texts):
            match = next((item for item in candidates if item.text == text), None)
            if match is None:
                tags = [_normalize_tag(tag) for tag in _infer_tags_from_text(text, tag_set)]
                selected.append(
                    EvidenceBullet(
                        source_id=f"manual:{_slugify(entity)}:bullet:{index}",
                        source_type="manual",
                        source_entity=entity,
                        text=text,
                        tags=tags,
                        matched_keywords=tags,
                        score=float(len(tags)),
                        original_index=index,
                    )
                )
            else:
                matched = _matched_keywords(match.text, match.tags, tag_set)
                selected.append(
                    match.model_copy(
                        update={
                            "matched_keywords": matched,
                            "score": float(len(matched)),
                        }
                    )
                )

    return selected


def _optional_generation_session():
    try:
        from src.core.config import load_config
        from src.core.database import get_session_factory

        return get_session_factory(load_config())()
    except Exception:
        return None


def _job_query_embedding(job: RawJob) -> list[float] | None:
    for key in ("description_embedding", "embedding"):
        value = job.raw_data.get(key)
        if (
            isinstance(value, list)
            and value
            and all(isinstance(item, int | float) for item in value)
        ):
            return [float(item) for item in value]
    return None


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


def _max_bullets_per_entity(manifest: TemplateManifest) -> int:
    limits = []
    for section in ("experience", "projects"):
        config = manifest.sections.get(section)
        if config and config.enabled and config.max_bullets_per_item:
            limits.append(config.max_bullets_per_item)
    return max(limits) if limits else 4


def _rewrite_grouped_evidence(
    grouped: dict[str, list[EvidenceBullet]], jd_tags: list[str]
) -> dict[str, list[EvidenceBullet]]:
    rewritten_text = rewrite_bullets(
        {entity: [item.text for item in items] for entity, items in grouped.items()},
        jd_tags,
    )
    rewritten: dict[str, list[EvidenceBullet]] = {}
    for entity, items in grouped.items():
        texts = rewritten_text.get(entity, [])
        rewritten[entity] = [
            item.model_copy(update={"render_text": texts[index]})
            if index < len(texts)
            else item
            for index, item in enumerate(items)
        ]
    return rewritten


def _build_experience_items(
    profile_data: dict[str, Any], grouped: dict[str, list[EvidenceBullet]]
) -> list[ResumeItem]:
    items: list[ResumeItem] = []
    for index, exp in enumerate(profile_data.get("work_experiences", [])):
        if not isinstance(exp, dict):
            continue
        company = str(exp.get("company") or "Unknown")
        title = str(exp.get("title") or "")
        entity = f"{company} - {title}".strip(" -")
        evidence_items = grouped.get(entity, [])
        if not evidence_items:
            continue
        items.append(
            ResumeItem(
                source_id=f"experience:{_slugify(entity) or index}",
                source_type="experience",
                name=company,
                title=title,
                organization=company,
                location=str(exp.get("location") or ""),
                start_date=str(exp.get("start_date") or ""),
                end_date=str(exp.get("end_date") or ""),
                meta=str(exp.get("description") or ""),
                bullets=[item.to_resume_bullet() for item in evidence_items],
            )
        )
    return items


def _build_project_items(
    profile_data: dict[str, Any], grouped: dict[str, list[EvidenceBullet]]
) -> list[ResumeItem]:
    items: list[ResumeItem] = []
    for index, project in enumerate(profile_data.get("projects", [])):
        if not isinstance(project, dict):
            continue
        name = str(project.get("name") or "Unknown")
        evidence_items = grouped.get(name, [])
        if not evidence_items:
            continue
        items.append(
            ResumeItem(
                source_id=f"project:{_slugify(name) or index}",
                source_type="project",
                name=name,
                title=str(project.get("role") or ""),
                meta=str(project.get("description") or ""),
                start_date=str(project.get("start_date") or ""),
                end_date=str(project.get("end_date") or ""),
                tech_stack=[str(value) for value in project.get("tech_stack", [])],
                bullets=[item.to_resume_bullet() for item in evidence_items],
            )
        )
    return items


def _prioritize_skills(skills: dict[str, Any], jd_tags: list[str]) -> dict[str, list[str]]:
    tag_set = {_normalize_tag(tag) for tag in jd_tags}
    prioritized: dict[str, list[str]] = {}
    for category, values in skills.items():
        if not isinstance(values, list):
            continue
        clean_values = [str(value) for value in values if str(value).strip()]
        prioritized[category] = sorted(
            clean_values,
            key=lambda value: _normalize_tag(value) in tag_set,
            reverse=True,
        )
    return prioritized


def _build_summary(job: RawJob, profile_data: dict[str, Any], jd_tags: list[str]) -> list[str]:
    education = profile_data.get("education", [])
    field = ""
    if education and isinstance(education[0], dict):
        field = education[0].get("field") or education[0].get("degree") or ""
    strongest = ", ".join(jd_tags[:4])
    if not field and not strongest:
        return []
    focus = f" with experience in {strongest}" if strongest else ""
    return [f"{field or 'Candidate'} targeting {job.title} roles{focus}.".strip()]


def _plan_section_order(job: RawJob, profile_data: dict[str, Any]) -> list[str]:
    title = job.title.lower()
    seniority = (job.seniority or "").lower()
    is_student = bool(profile_data.get("education")) and any(
        token in f"{title} {seniority}" for token in ("intern", "student", "coop", "co-op")
    )
    if is_student:
        return ["header", "education", "skills", "projects", "experience"]
    return ["header", "summary", "skills", "experience", "projects", "education"]


def _matched_keywords(text: str, tags: list[str], tag_set: set[str]) -> list[str]:
    text_tokens = set(_infer_tags_from_text(text, tag_set))
    tag_matches = {_normalize_tag(tag) for tag in tags} & tag_set
    return sorted(tag_matches | text_tokens)


def _infer_tags_from_text(text: str, tag_set: set[str]) -> list[str]:
    tokens = {_normalize_tag(token) for token in text.split()}
    return sorted(tokens & tag_set)


def _normalize_tag(value: str) -> str:
    return value.lower().strip().replace(" ", "_")


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:80]


def extract_jd_tags(job: RawJob) -> list[str]:
    """Extract searchable tags from a job's requirements and description.

    Combines must-have skills, preferred skills, and inferred keywords
    from the title into a flat tag list for bullet pool querying.
    """
    tags = []

    # From structured requirements
    tags.extend(s.lower() for s in job.requirements.must_have_skills)
    tags.extend(s.lower() for s in job.requirements.preferred_skills)
    tags.extend(s.lower() for s in job.requirements.keywords)
    tags.extend(s.lower() for s in job.requirements.soft_skills)
    for value in (
        job.requirements.domain,
        job.requirements.role_family,
        job.requirements.seniority,
    ):
        if value:
            tags.append(value.lower())

    # From title and JD text -- extract meaningful technical keywords
    searchable_text = f"{job.title} {job.description or ''}".lower()
    searchable_tokens = set(re.findall(r"[a-z][a-z0-9+#.]+", searchable_text))
    tech_keywords = {
        "python",
        "java",
        "javascript",
        "typescript",
        "go",
        "rust",
        "c++",
        "react",
        "vue",
        "angular",
        "node",
        "django",
        "flask",
        "fastapi",
        "spring",
        "kubernetes",
        "docker",
        "aws",
        "gcp",
        "azure",
        "sql",
        "postgresql",
        "mongodb",
        "redis",
        "graphql",
        "ml",
        "ai",
        "machine learning",
        "deep learning",
        "nlp",
        "backend",
        "frontend",
        "fullstack",
        "devops",
        "sre",
        "data",
        "analytics",
        "infrastructure",
        "platform",
        "security",
    }
    for keyword in tech_keywords:
        if " " in keyword:
            if keyword in searchable_text:
                tags.append(keyword)
        elif keyword in searchable_tokens:
            tags.append(keyword)

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
    evidence = select_relevant_evidence(
        jd_tags,
        profile_data,
        max_bullets_per_entity=max_bullets_per_entity,
    )
    for entity, items in evidence_by_entity(evidence).items():
        selected[entity] = [item.text for item in items]

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
    from src.utils.llm import LLMError

    keywords_str = ", ".join(jd_tags[:15])

    rewritten: dict[str, list[str]] = {}
    for entity, bullets in selected_bullets.items():
        new_bullets = []
        for bullet in bullets:
            try:
                rewrite = _rewrite_single_bullet(bullet, keywords_str)
                new_text = rewrite.rewritten_bullet
                # Fact-drift check: rewritten bullet should be similar length
                if (
                    rewrite.changed_claims
                    or len(new_text) > len(bullet) * 2
                    or len(new_text) < len(bullet) * 0.3
                ):
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

Return ONLY a JSON object with exactly this shape:
{
  "rewritten_bullet": "...",
  "used_skills": ["Python"],
  "source_ids": [],
  "confidence": "high" | "medium" | "low",
  "changed_claims": []
}

Rules:
- Keep the same meaning, structure, and claims
- Preserve all numbers, metrics, and quantified results EXACTLY
- Only adjust word choice to incorporate relevant keywords where natural
- Do NOT add new skills, technologies, or achievements that weren't in the original
- Do NOT change the tone from professional to casual or vice versa
- changed_claims must list any claim that might not be grounded in the original bullet"""


def _rewrite_single_bullet(bullet: str, keywords: str) -> BulletRewriteResult:
    """Rewrite a single bullet using structured LLM output."""
    from src.utils.llm import generate_json

    prompt = (
        f"Target keywords: {keywords}\n\n"
        f"Original bullet: {bullet}\n\n"
        f"Rewrite the bullet to naturally incorporate relevant keywords."
    )
    result = generate_json(prompt, system=_REWRITE_SYSTEM, timeout=60)
    if isinstance(result, str):
        return BulletRewriteResult(rewritten_bullet=result.strip().strip("•-– ").strip())
    return BulletRewriteResult.model_validate(result)
