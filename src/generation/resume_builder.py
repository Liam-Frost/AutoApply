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

import hashlib
import logging
import re
from datetime import date
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

# Upper bound on render/trim attempts when squeezing into the page target.
# Each round drops one bullet (or item, once bullets run out), so 8 covers
# most cases even with very dense source data.
_MAX_TRIM_ATTEMPTS = 8
_FALLBACK_WORK_START_YEAR = 2016
_FALLBACK_MIN_WORK_YEARS_PER_COMPANY = 2
_MAX_RELEVANT_SKILLS_PER_CATEGORY = 4
_MAX_FALLBACK_SKILLS_PER_CATEGORY = 2


def generate_resume(
    job: RawJob,
    profile_data: dict[str, Any],
    selected_bullets: dict[str, list[str]] | None = None,
    selected_evidence: list[EvidenceBullet] | None = None,
    template_path: Path | None = None,
    template_id: str = "ats_single_column_v1",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    rewrite: bool = False,
    use_llm: bool = False,
    rewrite_mode: str = "balanced",
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
        selected_evidence=selected_evidence,
        rewrite=rewrite,
        use_llm=use_llm,
        template_id=template_manifest.template_id,
        template_manifest=template_manifest,
        rewrite_mode=rewrite_mode,
    )
    target_pages = template_manifest.target_pages or template_manifest.capacity.max_pages
    validation = validate_resume_document(
        resume_document,
        jd_tags=resume_document.metadata.get("jd_tags", []),
        max_bullet_words=template_manifest.capacity.max_words_per_bullet or 32,
        max_estimated_pages=target_pages,
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
        pattern=template_manifest.filename_pattern,
        profile_name=profile_data.get("identity", {}).get("full_name", ""),
        custom_label=template_manifest.filename_custom_label,
        template_id=template_manifest.template_id,
    )

    # Render + iterate: if the rendered PDF is over the page target,
    # drop the weakest bullet and re-render. This is the only reliable
    # way to honour the user's "exactly N pages" setting because the
    # pre-render fitter only knows item caps -- font size, line spacing
    # and margin changes from Template Library edits can push content
    # over the line in ways the IR can't predict.
    resume_document, docx_path, pdf_path = _render_resume_to_target_pages(
        resume_document=resume_document,
        template_path=template_path,
        template_manifest=template_manifest,
        docx_output=paths["resume_docx"],
        pdf_output=paths["resume_pdf"],
        target_pages=target_pages,
    )

    validation = validate_resume_artifacts(
        validation,
        docx_path=docx_path,
        pdf_path=pdf_path,
        pdf_attempted=True,
        max_pages=template_manifest.capacity.max_pages,
        target_pages=target_pages,
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
    selected_evidence: list[EvidenceBullet] | None = None,
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
        selected_evidence=selected_evidence,
        rewrite=rewrite,
        use_llm=use_llm,
        template_id=package.template_id,
        template_manifest=package.manifest,
    )
    target_pages = package.manifest.target_pages or package.manifest.capacity.max_pages
    validation = validate_resume_document(
        resume_document,
        jd_tags=resume_document.metadata.get("jd_tags", []),
        max_bullet_words=package.manifest.capacity.max_words_per_bullet or 32,
        max_estimated_pages=target_pages,
    )

    paths = get_output_paths(
        company=job.company,
        role=job.title,
        output_dir=output_dir,
        pattern=package.manifest.filename_pattern,
        profile_name=profile_data.get("identity", {}).get("full_name", ""),
        custom_label=package.manifest.filename_custom_label,
        template_id=package.manifest.template_id,
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
        target_pages=target_pages,
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
    selected_evidence: list[EvidenceBullet] | None = None,
    rewrite: bool = False,
    use_llm: bool = False,
    template_id: str = "ats_single_column_v1",
    template_manifest: TemplateManifest | None = None,
    rewrite_mode: str = "balanced",
) -> ResumeDocument:
    """Plan a renderer-agnostic resume IR for a target job."""
    template_manifest = template_manifest or default_manifest("resume")
    jd_tags = extract_jd_tags(job)
    logger.info("JD tags for %s at %s: %s", job.title, job.company, jd_tags)

    db_session = _optional_generation_session()
    try:
        evidence = (
            selected_evidence
            if selected_evidence is not None
            else (
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
        )
    finally:
        if db_session is not None:
            db_session.close()
    grouped = evidence_by_entity(evidence)

    if rewrite and use_llm:
        grouped = _rewrite_grouped_evidence(grouped, jd_tags, mode=rewrite_mode)

    skills = _prioritize_skills(profile_data.get("skills", {}), jd_tags)
    document = ResumeDocument(
        template_id=template_id,
        target_role=job.title,
        company=job.company,
        header=profile_data.get("identity", {}),
        summary=_build_resume_summary(job, grouped, skills),
        skills=skills,
        education=profile_data.get("education", []),
        experiences=_build_experience_items(profile_data, grouped),
        projects=_build_project_items(profile_data, grouped),
        custom_sections=_build_custom_sections(profile_data),
        section_order=template_manifest.section_order or _plan_section_order(job, profile_data),
        metadata={
            "jd_tags": jd_tags,
            "selected_evidence_count": sum(len(items) for items in grouped.values()),
        },
    )
    fitted = fit_resume_document_to_template(document, template_manifest)
    fitted.experiences = _fill_missing_experience_periods(fitted.experiences)
    return fitted


def _build_custom_sections(profile_data: dict[str, Any]) -> list:
    """Load free-form sections (VOLUNTEER / AWARDS / AFFILIATIONS / ...)
    from the profile and project them onto the IR.

    Accepts either of two layouts (both produced by various profile
    sources we've shipped over the project's life):

      A) ``custom_sections: [{title, entries: [...]}, ...]`` -- the
         canonical schema the resume importer now emits.
      B) ``custom_sections: {Title1: [entries], Title2: [entries], ...}``
         -- a dict-of-sections shape we accept defensively so a
         hand-edited YAML keeps working.

    Returns an empty list when the field is missing or malformed. We do
    NOT raise: a bad custom-section payload should degrade gracefully
    rather than block the entire resume from rendering.
    """
    from src.generation.ir import CustomSection, CustomSectionEntry  # noqa: PLC0415

    raw = profile_data.get("custom_sections")
    if not raw:
        return []

    sections: list[CustomSection] = []

    def _coerce_entries(entries_raw) -> list[CustomSectionEntry]:
        entries: list[CustomSectionEntry] = []
        if not isinstance(entries_raw, list):
            return entries
        for entry in entries_raw:
            if not isinstance(entry, dict):
                # Plain string in the entry list (e.g. INTERESTS &
                # ACTIVITIES is often just a comma-separated line).
                text = str(entry).strip()
                if text:
                    entries.append(CustomSectionEntry(details=text))
                continue
            bullets_raw = entry.get("bullets") or []
            bullets: list[str] = []
            for bullet in bullets_raw:
                if isinstance(bullet, dict):
                    text = str(bullet.get("text") or "").strip()
                elif bullet is None:
                    text = ""
                else:
                    text = str(bullet).strip()
                if text:
                    bullets.append(text)
            entries.append(
                CustomSectionEntry(
                    title=str(entry.get("title") or "").strip(),
                    organization=str(entry.get("organization") or "").strip(),
                    location=str(entry.get("location") or "").strip(),
                    start_date=str(entry.get("start_date") or "").strip(),
                    end_date=str(entry.get("end_date") or "").strip(),
                    details=str(entry.get("details") or entry.get("description") or "").strip(),
                    bullets=bullets,
                )
            )
        return entries

    if isinstance(raw, list):
        for section in raw:
            if not isinstance(section, dict):
                continue
            title = str(section.get("title") or "").strip()
            if not title:
                continue
            sections.append(
                CustomSection(title=title, entries=_coerce_entries(section.get("entries")))
            )
    elif isinstance(raw, dict):
        for title, entries_raw in raw.items():
            title = str(title or "").strip()
            if not title:
                continue
            sections.append(CustomSection(title=title, entries=_coerce_entries(entries_raw)))

    # Strip empty sections so a heading with no entries doesn't leave
    # a dangling section title on the rendered resume.
    return [s for s in sections if s.entries]


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
    raw_data = getattr(job, "raw_data", {}) or {}
    if not isinstance(raw_data, dict):
        return None
    for key in ("description_embedding", "embedding"):
        value = raw_data.get(key)
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
    grouped: dict[str, list[EvidenceBullet]],
    jd_tags: list[str],
    *,
    mode: str = "balanced",
) -> dict[str, list[EvidenceBullet]]:
    rewritten_text = rewrite_bullets(
        {entity: [item.text for item in items] for entity, items in grouped.items()},
        jd_tags,
        mode=mode,
    )
    rewritten: dict[str, list[EvidenceBullet]] = {}
    for entity, items in grouped.items():
        texts = rewritten_text.get(entity, [])
        rewritten[entity] = [
            item.model_copy(update={"render_text": texts[index]}) if index < len(texts) else item
            for index, item in enumerate(items)
        ]
    return rewritten


def _build_experience_items(
    profile_data: dict[str, Any], grouped: dict[str, list[EvidenceBullet]]
) -> list[ResumeItem]:
    ranked_items: list[tuple[tuple[float, float, int, int], ResumeItem]] = []
    for index, exp in enumerate(profile_data.get("work_experiences", [])):
        if not isinstance(exp, dict):
            continue
        company = str(exp.get("company") or "Unknown")
        title = str(exp.get("title") or "")
        entity = f"{company} - {title}".strip(" -")
        evidence_items = grouped.get(entity, [])
        if not evidence_items:
            continue
        item = ResumeItem(
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
        ranked_items.append((_resume_item_relevance_key(item, profile_index=index), item))
    ranked_items.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in ranked_items]


def _build_project_items(
    profile_data: dict[str, Any], grouped: dict[str, list[EvidenceBullet]]
) -> list[ResumeItem]:
    ranked_items: list[tuple[tuple[float, float, int, int], ResumeItem]] = []
    for index, project in enumerate(profile_data.get("projects", [])):
        if not isinstance(project, dict):
            continue
        name = str(project.get("name") or "Unknown")
        evidence_items = grouped.get(name, [])
        if not evidence_items:
            continue
        item = ResumeItem(
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
        ranked_items.append((_resume_item_relevance_key(item, profile_index=index), item))
    ranked_items.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in ranked_items]


def _resume_item_relevance_key(
    item: ResumeItem,
    *,
    profile_index: int,
) -> tuple[float, float, int, int]:
    scores = [bullet.score for bullet in item.bullets]
    best_score = max(scores, default=0.0)
    total_score = sum(scores)
    return (best_score, total_score, len(item.bullets), -profile_index)


def _fill_missing_experience_periods(items: list[ResumeItem]) -> list[ResumeItem]:
    missing_items = [
        item
        for item in items
        if getattr(item, "dates_inferred", False) or (not item.start_date and not item.end_date)
    ]
    if not missing_items:
        return items

    for item, (start_date, end_date) in zip(
        missing_items,
        _fallback_experience_periods(missing_items),
        strict=False,
    ):
        item.start_date = start_date
        item.end_date = end_date
        item.dates_inferred = True
    return items


def _fallback_experience_periods(items: list[ResumeItem]) -> list[tuple[str, str]]:
    today = date.today()
    current_year = max(_FALLBACK_WORK_START_YEAR, today.year)
    count = len(items)
    if count <= 0:
        return []
    if count <= 5:
        return _fallback_year_periods(count, current_year)
    return _fallback_month_periods(items, today)


def _fallback_year_periods(count: int, current_year: int) -> list[tuple[str, str]]:
    periods: list[tuple[str, str]] = []
    end_year = current_year
    for index in range(count):
        start_year = max(
            _FALLBACK_WORK_START_YEAR,
            end_year - _FALLBACK_MIN_WORK_YEARS_PER_COMPANY,
        )
        periods.append(
            (
                str(start_year),
                "Present" if index == 0 else str(end_year),
            )
        )
        end_year = start_year
    return periods


def _fallback_month_periods(
    items: list[ResumeItem],
    today: date,
) -> list[tuple[str, str]]:
    current_month = _month_index(today.year, today.month)
    floor_month = _month_index(_FALLBACK_WORK_START_YEAR, 1)
    boundaries = _deterministic_period_boundaries(items, floor_month, current_month)

    periods: list[tuple[str, str]] = []
    count = len(items)
    for index in range(count):
        start_month = boundaries[count - index - 1]
        end_month = boundaries[count - index]
        periods.append(
            (
                _format_month_index(start_month),
                "Present" if index == 0 else _format_month_index(end_month),
            )
        )
    return periods


def _deterministic_period_boundaries(
    items: list[ResumeItem],
    floor_month: int,
    current_month: int,
) -> list[int]:
    count = len(items)
    if count <= 0:
        return [floor_month, current_month]
    total_months = max(0, current_month - floor_month)
    if total_months <= count:
        return [floor_month + index for index in range(count)] + [current_month]

    min_gap = 3 if total_months >= count * 3 else 1
    step = total_months / count
    jitter_range = max(1, int(step * 0.2))
    boundaries = [floor_month]
    for index in range(1, count):
        ideal = floor_month + round(step * index)
        weight = _deterministic_item_weight(items[index - 1])
        jitter = weight % (jitter_range * 2 + 1) - jitter_range
        lower = boundaries[-1] + min_gap
        upper = current_month - (count - index) * min_gap
        boundaries.append(min(max(ideal + jitter, lower), upper))
    boundaries.append(current_month)
    return boundaries


def _deterministic_item_weight(item: ResumeItem) -> int:
    key = "|".join([item.source_id, item.name, item.title, item.organization])
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100 + 1


def _month_index(year: int, month: int) -> int:
    return year * 12 + month - 1


def _format_month_index(value: int) -> str:
    year = value // 12
    month = value % 12 + 1
    return f"{year:04d}-{month:02d}"


def _prioritize_skills(skills: dict[str, Any], jd_tags: list[str]) -> dict[str, list[str]]:
    tag_set = {_normalize_tag(tag) for tag in jd_tags}
    prioritized: dict[str, list[str]] = {}
    fallback: dict[str, list[str]] = {}
    for category, values in skills.items():
        if not isinstance(values, list):
            continue
        clean_values = [str(value) for value in values if str(value).strip()]
        fallback[category] = clean_values[:_MAX_FALLBACK_SKILLS_PER_CATEGORY]
        relevant = [
            value
            for value in clean_values
            if _skill_matches_jd_tags(value, tag_set)
        ][:_MAX_RELEVANT_SKILLS_PER_CATEGORY]
        if relevant:
            prioritized[category] = relevant
    if prioritized:
        return prioritized
    return {category: values for category, values in fallback.items() if values}


def _skill_matches_jd_tags(skill: str, tag_set: set[str]) -> bool:
    if not tag_set:
        return False
    normalized = _normalize_tag(skill)
    variants = _skill_tag_variants(normalized)
    if variants & tag_set:
        return True
    tokens = {_normalize_tag(token) for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.]+", skill)}
    if tokens & tag_set:
        return True
    return any(
        len(tag) >= 3
        and len(variant) >= 3
        and (tag in variant or variant in tag)
        for tag in tag_set
        for variant in variants | tokens
    )


def _skill_tag_variants(normalized: str) -> set[str]:
    compact = normalized.replace("_", "").replace(".", "")
    variants = {normalized, compact}
    aliases = {
        "postgresql": {"postgresql", "postgres", "sql"},
        "mysql": {"mysql", "sql"},
        "sqlite": {"sqlite", "sql"},
        "microsoft_sql_server": {"microsoft_sql_server", "sql_server", "mssql", "sql"},
        "nodejs": {"nodejs", "node"},
        "nextjs": {"nextjs", "next.js", "react"},
        "reactjs": {"reactjs", "react"},
        "amazon_web_services": {"amazon_web_services", "aws", "cloud"},
        "google_cloud_platform": {"google_cloud_platform", "gcp", "cloud"},
        "microsoft_azure": {"microsoft_azure", "azure", "cloud"},
        "c_plus_plus": {"c_plus_plus", "cpp", "c++"},
    }
    variants.update(aliases.get(normalized, set()))
    variants.update(aliases.get(compact, set()))
    return {value for value in variants if value}


def _build_resume_summary(
    job: RawJob,
    grouped: dict[str, list[EvidenceBullet]],
    skills: dict[str, list[str]],
) -> str:
    role = _clean_summary_text(job.title or "this role")
    skill_phrase = _summary_skill_phrase(skills)
    evidence = sorted(
        [item for items in grouped.values() for item in items],
        key=lambda item: item.score + item.semantic_score + item.vector_score,
        reverse=True,
    )
    roles = _summary_source_roles(evidence)
    evidence_sentences = [_summary_evidence_sentence(item) for item in evidence[:2]]
    evidence_sentences = [sentence for sentence in evidence_sentences if sentence]

    sentences = [
        (
            f"{role} with hands-on experience in {skill_phrase}, combining "
            "engineering depth with practical technical discovery, implementation, "
            "and stakeholder-facing problem solving."
        ),
    ]
    sentences.extend(evidence_sentences)
    if roles:
        sentences.append(f"Relevant background spans {roles}.")
    sentences.append(
        "Work emphasizes practical delivery, maintainable implementation, debugging, "
        "security-conscious engineering, and technical judgment in production systems."
    )
    return _trim_summary_words(" ".join(sentences), max_words=115)


def _summary_skill_phrase(skills: dict[str, list[str]]) -> str:
    values = [
        value
        for category_values in skills.values()
        for value in category_values
        if str(value).strip()
    ]
    if not values:
        return "the role's most relevant engineering requirements"
    return _join_natural(values[:5])


def _summary_evidence_sentence(item: EvidenceBullet) -> str:
    text = _clean_summary_text(item.render_text or item.text)
    if not text:
        return ""
    text = _trim_summary_fragment(text, max_words=24)
    text = text[0].lower() + text[1:] if len(text) > 1 else text.lower()
    role = _summary_source_role(item)
    if role:
        return f"As a {role}, {text}."
    return f"Experience includes work that {text}."


def _summary_source_roles(evidence: list[EvidenceBullet]) -> str:
    roles: list[str] = []
    for item in evidence:
        role = _summary_source_role(item)
        if role and role not in roles:
            roles.append(role)
        if len(roles) >= 3:
            break
    return _join_natural(roles)


def _summary_source_role(item: EvidenceBullet) -> str:
    entity = _clean_summary_text(item.source_entity)
    if not entity:
        return ""
    if " - " in entity:
        return entity.split(" - ", 1)[1].strip()
    return entity


def _clean_summary_text(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.rstrip(".;")


def _trim_summary_words(text: str, *, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(" ,;:") + "."


def _trim_summary_fragment(text: str, *, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(" ,;:")


def _join_natural(values: list[str]) -> str:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def _plan_section_order(job: RawJob, profile_data: dict[str, Any]) -> list[str]:
    # Summary is intentionally absent in every branch -- see ResumeDocument
    # in src/generation/ir.py.
    title = job.title.lower()
    seniority = (job.seniority or "").lower()
    is_student = bool(profile_data.get("education")) and any(
        token in f"{title} {seniority}" for token in ("intern", "student", "coop", "co-op")
    )
    if is_student:
        return ["header", "summary", "education", "skills", "projects", "experience"]
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
    *,
    mode: str = "balanced",
) -> dict[str, list[str]]:
    """Light lexical rewrite of bullets to inject JD keywords.

    ``mode`` selects which rules block the LLM gets:
      - ``conservative``: change at most a word or two; mostly pass-through
      - ``balanced``: default; sensible rewriting while preserving claims
      - ``aggressive``: rewrite freely while keeping all facts grounded

    Mode is plumbed in from ``material_defaults.patch_aggressiveness``
    for the patch_existing strategy. For regenerate the caller may
    leave ``mode`` at the default; aggressiveness is meaningful mainly
    when there's an original document the user wants to "preserve".

    Phase 18.5: bullets within one ``rewrite_bullets`` call run
    concurrently via :mod:`asyncio` capped by
    ``parallelism.bullet_rewrites.max_concurrent_per_task``. Provider
    abuse is bounded by the global / per-provider semaphores in
    :mod:`src.utils.parallelism` so increasing the per-task cap does
    NOT translate into unbounded LLM concurrency across workers.
    """
    from src.utils.parallelism import run_coroutine_safely  # noqa: PLC0415

    return run_coroutine_safely(
        _rewrite_bullets_async(selected_bullets, jd_tags, mode=mode)
    )


async def _rewrite_bullets_async(
    selected_bullets: dict[str, list[str]],
    jd_tags: list[str],
    *,
    mode: str = "balanced",
) -> dict[str, list[str]]:
    """Phase 18.5 implementation behind :func:`rewrite_bullets`."""
    import asyncio  # noqa: PLC0415

    from src.utils.llm import LLMError  # noqa: PLC0415
    from src.utils.parallelism import bullet_rewrite_cap  # noqa: PLC0415

    keywords_str = ", ".join(jd_tags[:15])
    cap = max(1, bullet_rewrite_cap())
    sem = asyncio.Semaphore(cap)

    async def _one(bullet: str) -> str:
        async with sem:
            try:
                rewrite = await asyncio.to_thread(
                    _rewrite_single_bullet, bullet, keywords_str, mode=mode
                )
                new_text = rewrite.rewritten_bullet
                if (
                    rewrite.changed_claims
                    or len(new_text) > len(bullet) * 2
                    or len(new_text) < len(bullet) * 0.3
                ):
                    logger.warning("Rewrite drift detected for bullet, keeping original")
                    return bullet
                return new_text
            except (LLMError, Exception) as exc:  # noqa: BLE001
                logger.debug("Rewrite failed for bullet: %s", exc)
                return bullet

    rewritten: dict[str, list[str]] = {}
    for entity, bullets in selected_bullets.items():
        results = await asyncio.gather(*[_one(b) for b in bullets])
        rewritten[entity] = list(results)
    return rewritten


_REWRITE_SYSTEM_BASE = """You are a resume bullet point editor. Your job is to adjust
a resume bullet to better match target job keywords while preserving facts.

Return ONLY a JSON object with exactly this shape:
{
  "rewritten_bullet": "...",
  "used_skills": ["Python"],
  "source_ids": [],
  "confidence": "high" | "medium" | "low",
  "changed_claims": []
}

Inline markup you MAY use sparingly inside ``rewritten_bullet``:
- ``**text**`` -- bold for ONE or TWO key skills, named technologies,
  or quantified outcomes per bullet (e.g. "**FastAPI**", "**1.5M+
  requests/day**"). Never bold a whole sentence.
- ``*text*`` -- italics for proper nouns, paper / product / project
  names. Never italicise ordinary technical terms.
- Do NOT use any other Markdown -- no headings, no links, no code
  fences, no ``_underscores_`` (so ``model_v2`` stays literal).
- Markup is OPTIONAL. Leave bullets plain when no term clearly merits
  emphasis.
"""

_REWRITE_RULES_BY_MODE: dict[str, str] = {
    "conservative": (
        "Rules (CONSERVATIVE — make the smallest possible change):\n"
        "- Preserve sentence structure, length, and verbs as much as humanly possible\n"
        "- Swap at most 1-2 words to incorporate ONE highly-relevant keyword if it "
        "lands naturally; otherwise return the bullet unchanged\n"
        "- Preserve all numbers, metrics, and quantified results EXACTLY\n"
        "- Do NOT add new skills, technologies, or achievements that weren't in the original\n"
        "- Do NOT change the tone or claims\n"
        "- changed_claims must list any claim that might not be grounded in the original bullet"
    ),
    "balanced": (
        "Rules (BALANCED — sensible rewriting):\n"
        "- Keep the same meaning, structure, and claims\n"
        "- Preserve all numbers, metrics, and quantified results EXACTLY\n"
        "- Adjust word choice to incorporate relevant keywords where natural\n"
        "- Do NOT add new skills, technologies, or achievements that weren't in the original\n"
        "- Do NOT change the tone from professional to casual or vice versa\n"
        "- changed_claims must list any claim that might not be grounded in the original bullet"
    ),
    "aggressive": (
        "Rules (AGGRESSIVE — rewrite freely while keeping facts):\n"
        "- You may rewrite the sentence structure and verbs as needed to surface "
        "relevant keywords for the target role\n"
        "- Preserve all numbers, metrics, and quantified results EXACTLY\n"
        "- You may emphasise transferable skills implied by the original bullet, "
        "but do NOT invent skills, technologies, or achievements that aren't grounded\n"
        "- Keep the tone professional\n"
        "- changed_claims must list any claim whose grounding in the original bullet "
        "is even slightly uncertain"
    ),
}


def _rewrite_system_for(mode: str) -> str:
    rules = _REWRITE_RULES_BY_MODE.get(mode, _REWRITE_RULES_BY_MODE["balanced"])
    return _REWRITE_SYSTEM_BASE + "\n" + rules


# Kept for back-compat with any external imports of the legacy name.
_REWRITE_SYSTEM = _rewrite_system_for("balanced")


_INVALID_BULLET_REWRITE_PATTERNS = (
    "please paste the system instructions",
    "paste the system instructions",
    "system instructions you want me to follow",
    "if you want me to inspect or modify",
    "point me to the relevant file",
    "openai codex",
    "tokens used",
    "reading additional input from stdin",
    "i cannot rewrite",
    "i can't rewrite",
    "i am unable to",
    "i'm unable to",
    "as an ai language model",
    "as a language model",
)


def _clean_llm_bullet_rewrite_output(
    rewritten: str,
    original: str,
) -> str:
    """Reject CLI/meta responses and obvious garbage so bad rewrites fall back.

    Mirrors ``cover_letter._clean_llm_cover_letter_output``: surface an
    :class:`LLMError` whenever the model returns a meta-response, fenced
    code-block dump, or a payload so short/long it cannot be a real
    resume bullet. The async wrapper above catches ``LLMError`` and keeps
    the original bullet, which is the correct fallback.
    """
    from src.utils.llm import LLMError  # noqa: PLC0415

    text = (rewritten or "").strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    text = text.strip("•-– ").strip()

    if not text:
        raise LLMError("LLM returned an empty bullet rewrite.")

    lower = text.lower()
    if any(pattern in lower for pattern in _INVALID_BULLET_REWRITE_PATTERNS):
        raise LLMError("LLM returned a meta-response instead of a bullet rewrite.")

    word_count = len(text.split())
    if word_count < 4:
        raise LLMError("LLM returned a bullet rewrite that is too short.")
    if word_count > 80:
        raise LLMError("LLM returned a bullet rewrite that is too long.")
    if "\n\n" in text:
        raise LLMError("LLM returned multiple paragraphs instead of one bullet.")

    original_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\+?\b", original))
    new_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\+?\b", text))
    if new_numbers - original_numbers:
        raise LLMError("LLM rewrite introduced numbers not present in the original bullet.")

    return text


def _rewrite_single_bullet(
    bullet: str,
    keywords: str,
    *,
    mode: str = "balanced",
) -> BulletRewriteResult:
    """Rewrite a single bullet using structured LLM output.

    ``mode`` is one of ``conservative`` / ``balanced`` / ``aggressive``
    and chooses the rewriting rules section in the system prompt.
    """
    from src.utils.llm import generate_json

    prompt = (
        f"Target keywords: {keywords}\n\n"
        f"Original bullet: {bullet}\n\n"
        f"Rewrite the bullet to naturally incorporate relevant keywords."
    )
    result = generate_json(prompt, system=_rewrite_system_for(mode), timeout=60)
    if isinstance(result, str):
        cleaned = _clean_llm_bullet_rewrite_output(result, bullet)
        return BulletRewriteResult(rewritten_bullet=cleaned)

    parsed = BulletRewriteResult.model_validate(result)
    cleaned = _clean_llm_bullet_rewrite_output(parsed.rewritten_bullet, bullet)
    return parsed.model_copy(update={"rewritten_bullet": cleaned})


_LENGTH_REWRITE_SYSTEM = """You are a resume bullet editor adjusting bullet
length while preserving every grounded fact.

Return ONLY a JSON object with exactly this shape:
{
  "rewritten_bullet": "...",
  "used_skills": [],
  "source_ids": [],
  "confidence": "high" | "medium" | "low",
  "changed_claims": []
}

Rules:
- Preserve every claim, number, metric, and named technology from the original.
- Do NOT invent skills, technologies, accomplishments, or projects.
- Stay professional and concise; one bullet, one sentence (or two short ones).
- changed_claims must list any phrasing whose grounding is even slightly uncertain.

Inline markup you MAY use sparingly inside ``rewritten_bullet``:
- ``**text**`` -- bold for ONE or TWO key skills, named technologies,
  or quantified outcomes per bullet (e.g. "**FastAPI**", "**1.5M+
  requests/day**"). Never bold a whole sentence.
- ``*text*`` -- italics for proper nouns, paper / product / project
  names (e.g. "*Operating Systems: Three Easy Pieces*"). Never italicise
  ordinary technical terms.
- Do NOT use any other Markdown -- no headings, no links, no code
  fences, no ``_underscores_``. Underscores stay literal so identifiers
  like ``model_v2`` render correctly.
- Markup is OPTIONAL. If a bullet does not have an obvious key term to
  highlight, leave it plain.
"""


def _rewrite_bullet_for_length(
    bullet: str,
    *,
    direction: str,
    target_words: int,
) -> str:
    """Ask the LLM to make a bullet roughly ``target_words`` long.

    ``direction`` is ``"shorter"`` or ``"longer"`` -- chosen by the
    caller from the rendered page-count delta so the prompt explicitly
    asks for the right adjustment instead of letting the model guess.
    Raises :class:`LLMError` on bad output so the caller can fall back
    to the original bullet for that round.
    """
    from src.utils.llm import generate_json  # noqa: PLC0415

    instruction = (
        f"Make this bullet noticeably {direction}, around {target_words} words. "
        "Keep every grounded fact, number, and named tool. Do not invent any "
        "new claim."
    )
    prompt = (
        f"Original bullet:\n{bullet}\n\n"
        f"{instruction}\n\n"
        "Return the JSON object specified by the system instructions."
    )
    result = generate_json(prompt, system=_LENGTH_REWRITE_SYSTEM, timeout=60)
    if isinstance(result, str):
        return _clean_llm_bullet_rewrite_output(result, bullet)
    parsed = BulletRewriteResult.model_validate(result)
    return _clean_llm_bullet_rewrite_output(parsed.rewritten_bullet, bullet)


def _resize_document_bullets(
    document: ResumeDocument,
    *,
    direction: str,
    target_words: int,
) -> ResumeDocument:
    """Return a copy of ``document`` whose experience/project bullets have
    been rewritten for length via the LLM.

    Failures on individual bullets (LLMError) silently keep the original
    text for that bullet so a single bad rewrite does not abort the
    whole convergence loop.
    """
    from src.utils.llm import LLMError  # noqa: PLC0415

    updated = document.model_copy(deep=True)
    for section in (updated.experiences, updated.projects):
        for item in section:
            for bullet in item.bullets:
                if not bullet.text:
                    continue
                try:
                    bullet.text = _rewrite_bullet_for_length(
                        bullet.text,
                        direction=direction,
                        target_words=target_words,
                    )
                except (LLMError, Exception) as exc:  # noqa: BLE001
                    logger.debug("Length rewrite kept original bullet (%s): %s", direction, exc)
    return updated


# Upper bound on Fit-Planner rounds. Each round = at most 1 LLM call +
# 1 render + 1 PDF convert. Two rounds keep the total wall time within
# the front-end's poll budget even on slow LLM providers.
_MAX_FIT_PLAN_ROUNDS = 2


def _render_resume_to_target_pages(
    *,
    resume_document: ResumeDocument,
    template_path: Path,
    template_manifest: TemplateManifest,
    docx_output: Path,
    pdf_output: Path,
    target_pages: int,
    use_llm: bool = True,
    jd_tags: list[str] | None = None,
) -> tuple[ResumeDocument, Path, Path | None]:
    """Render the resume, then drive it to exactly ``target_pages`` using
    a single-shot **Fit Planner** LLM call per attempt.

    Why this design (replacing the per-bullet rewrite loop)
    --------------------------------------------------------
    The previous loop rewrote every selected bullet via the LLM up to
    two rounds. With ~10 bullets and a 60 s per-call timeout, the worst
    case blew past the front-end's 2-minute poll budget and the
    operator saw "no worker completed it" even though the task was
    still grinding.

    More importantly, per-bullet rewriting is the *wrong* abstraction.
    The smart move when a resume runs over (or under) the page target
    is to decide at the **section level** what stays, what shrinks,
    and what gets dropped -- e.g. cut "INTERESTS & ACTIVITIES" for a
    backend-engineer role rather than trim sentences of real evidence.
    The LLM has the relevance judgement to make that call when it sees
    the full outline.

    Convergence loop
    ----------------
    1. Render initial draft, check PDF page count.
    2. If wrong, send ONE LLM call with a compact section outline
       (canonical sections + custom_sections + bullet counts + JD tags)
       and ask for a JSON fit plan: per-section ``keep`` / ``max_items``
       / ``bullets_mode`` decisions plus the LLM's reasoning.
    3. Apply the plan deterministically -- drop sections marked drop,
       trim each section to its ``max_items``, batch-rewrite bullets
       only when the plan asked for it.
    4. Re-render. Repeat up to :data:`_MAX_FIT_PLAN_ROUNDS` rounds.
    5. Final deterministic fallback for stubborn overflow: drop the
       weakest bullet until pages fit or the resume can't shrink more.

    Returns (final_document, docx_path, pdf_path | None).
    """
    from src.documents.page_count import get_pdf_page_count  # noqa: PLC0415

    def _render(doc):
        doc = _with_current_experience_periods(doc)
        path = build_resume_from_ir(
            template_path=template_path,
            document=doc,
            output_path=docx_output,
            manifest=template_manifest,
        )
        pdf: Path | None = None
        try:
            pdf = convert_to_pdf(path, pdf_output)
        except Exception as exc:  # noqa: BLE001
            logger.warning("PDF conversion failed: %s", exc)
        pages = get_pdf_page_count(pdf) if pdf else None
        return path, pdf, pages, doc

    current = resume_document
    docx_path, pdf_path, pages, current = _render(current)
    if target_pages <= 0 or pages is None:
        return current, docx_path, pdf_path

    jd_tags = jd_tags or list(current.metadata.get("jd_tags", []) or [])
    plan_history: list[str] = []

    for round_idx in range(_MAX_FIT_PLAN_ROUNDS if use_llm else 0):
        if pages == target_pages:
            return current, docx_path, pdf_path

        try:
            plan = _generate_resume_fit_plan(
                document=current,
                target_pages=target_pages,
                current_pages=pages,
                jd_tags=jd_tags,
                previous_plans=plan_history,
            )
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "Resume fit-planner round %d failed (%s); falling back to deterministic trim.",
                round_idx + 1,
                exc,
            )
            break

        plan_history.append(_summarise_plan(plan))
        logger.info(
            "Resume fit-plan round %d/%d (pages %d -> target %d): %s",
            round_idx + 1,
            _MAX_FIT_PLAN_ROUNDS,
            pages,
            target_pages,
            plan_history[-1],
        )
        current = _apply_fit_plan(current, plan)
        docx_path, pdf_path, pages, current = _render(current)

    # Deterministic structural fallback: only used when the LLM plan
    # didn't converge. Overflow -> drop weakest bullet; underflow is
    # left to the validator since we will not fabricate content.
    for attempt in range(_MAX_TRIM_ATTEMPTS):
        if pages == target_pages:
            break
        if pages < target_pages:
            logger.info(
                "Resume under target pages (%d < %d) after fit planner; "
                "cannot fabricate content -- validator will flag.",
                pages,
                target_pages,
            )
            break
        trimmed = _drop_weakest_bullet(current)
        if trimmed is None:
            logger.info(
                "Resume already minimal; cannot trim further to hit %d pages (currently %d).",
                target_pages,
                pages,
            )
            break
        logger.info(
            "Resume rendered %d pages > target %d; deterministic bullet drop %d/%d.",
            pages,
            target_pages,
            attempt + 1,
            _MAX_TRIM_ATTEMPTS,
        )
        current = trimmed
        docx_path, pdf_path, pages, current = _render(current)

    return current, docx_path, pdf_path


def _with_current_experience_periods(document: ResumeDocument) -> ResumeDocument:
    updated = document.model_copy(deep=True)
    updated.experiences = _fill_missing_experience_periods(updated.experiences)
    return updated


def _drop_weakest_bullet(document: ResumeDocument) -> ResumeDocument | None:
    """Return a copy of ``document`` with one bullet (or empty item) removed.

    Picks the lowest-scoring bullet across projects + experiences so the
    most relevant evidence stays on the page. When a section item has
    no bullets left after a previous trim, the whole item is removed
    instead. Returns None when there is no more content to drop.
    """
    trimmed = document.model_copy(deep=True)

    # 1. Drop any item that has been fully emptied by prior trims.
    for section_name in ("projects", "experiences"):
        section = getattr(trimmed, section_name)
        empty_idx = next((idx for idx, item in enumerate(section) if not item.bullets), None)
        if empty_idx is not None:
            section.pop(empty_idx)
            return trimmed

    # 2. Otherwise drop the single weakest bullet across both sections.
    weakest: tuple[list, int, float] | None = None
    for section in (trimmed.projects, trimmed.experiences):
        for item in section:
            for idx, bullet in enumerate(item.bullets):
                score = float(getattr(bullet, "score", 0.0) or 0.0)
                if weakest is None or score < weakest[2]:
                    weakest = (item.bullets, idx, score)
    if weakest is None:
        return None
    bullets, idx, _ = weakest
    bullets.pop(idx)
    return trimmed


# ---------------------------------------------------------------------------
# Fit Planner: single-shot section-level decisions
# ---------------------------------------------------------------------------

_FIT_PLAN_SYSTEM = """You are a resume editor making a SINGLE structural
decision to fit a resume to an exact page target. You see every section
in the candidate's resume (canonical: experiences / projects / education
/ skills, plus any custom sections such as VOLUNTEER, AWARDS,
AFFILIATIONS, INTERESTS, CERTIFICATIONS, PUBLICATIONS). For each section,
decide whether to keep it, how many items to keep, whether to ask for
shorter bullets, and whether to place a horizontal divider after it for
visual grouping.

Return ONLY a JSON object of this exact shape:
{
  "reasoning": "1-2 sentence summary of your decision",
  "sections": [
    {
      "id": "<the id from the outline>",
      "keep": true | false,
      "max_items": <int or null>,
      "bullets_mode": "shorter" | "keep" | "longer",
      "divider_after": true | false
    }
  ]
}

Decision rules:
- The candidate's JD-relevant evidence (experiences + projects with
  high-overlap tags) is the LAST thing you should cut.
- Drop low-relevance custom sections FIRST when over budget. For a
  backend engineer role, INTERESTS or PROFESSIONAL AFFILIATIONS are
  usually cheaper to lose than a Volunteer Engineering experience.
- Never set keep=false on experiences or skills -- they are required.
  Education and Projects are required for student / new-grad resumes;
  mark keep=false only if the candidate has plenty of full-time work.
- max_items=null means keep all items in that section.
- bullets_mode applies to experiences / projects / volunteer-like
  sections that carry bullet text. Use shorter when over-budget,
  longer when under-budget, keep when length is fine.
- divider_after=true inserts a thin horizontal rule after the section.
  Use SPARINGLY -- at most one or two per resume, only where the visual
  break clearly helps (e.g. between the experience block and a list of
  awards). Default to false. Skipped automatically for the very last
  rendered section.
- Include every section id from the outline in your response.
"""


def _generate_resume_fit_plan(
    *,
    document: ResumeDocument,
    target_pages: int,
    current_pages: int,
    jd_tags: list[str],
    previous_plans: list[str],
) -> dict[str, Any]:
    """Ask the LLM for a section-level plan to hit the page target.

    Single LLM round-trip. Returns ``{"reasoning": str, "sections":
    {<id>: {keep, max_items, bullets_mode}}}``. Raises if the LLM is
    unavailable or returns malformed JSON so the caller can fall back
    to deterministic trimming.
    """
    from src.generation._fit_planner_helpers import (  # noqa: PLC0415
        build_section_outline,
        coerce_optional_int,
    )
    from src.utils.llm import generate_json  # noqa: PLC0415

    outline = build_section_outline(document)
    over = current_pages > target_pages
    delta_word = (
        f"OVER target by {current_pages - target_pages} page(s)"
        if over
        else f"UNDER target by {target_pages - current_pages} page(s)"
    )
    history_block = ""
    if previous_plans:
        bullets = "\n".join(f"- {entry}" for entry in previous_plans)
        history_block = (
            "\n<previous_attempts>\n" + bullets + "\n</previous_attempts>\n"
            "Adjust more aggressively than last time -- the previous "
            "plan did not converge.\n"
        )

    jd_block = ", ".join(jd_tags[:25]) if jd_tags else "(none provided)"
    prompt = (
        "<target>\n"
        f"Target pages: {target_pages}\n"
        f"Current rendered pages: {current_pages} ({delta_word})\n"
        "</target>\n\n"
        "<jd_keywords>\n"
        f"{jd_block}\n"
        "</jd_keywords>\n\n"
        "<resume_outline>\n"
        f"{outline}\n"
        "</resume_outline>\n"
        f"{history_block}"
        "\nReturn the JSON object specified by the system instructions.\n"
    )

    result = generate_json(prompt, system=_FIT_PLAN_SYSTEM, timeout=60)
    if not isinstance(result, dict):
        raise ValueError(f"Fit plan response is not a JSON object: {type(result).__name__}")
    sections_raw = result.get("sections")
    if not isinstance(sections_raw, list) or not sections_raw:
        raise ValueError("Fit plan missing 'sections' list")

    by_id: dict[str, dict] = {}
    for entry in sections_raw:
        if not isinstance(entry, dict):
            continue
        section_id = str(entry.get("id") or "").strip()
        if not section_id:
            continue
        by_id[section_id] = {
            "keep": bool(entry.get("keep", True)),
            "max_items": coerce_optional_int(entry.get("max_items")),
            "bullets_mode": str(entry.get("bullets_mode") or "keep").lower(),
            "divider_after": bool(entry.get("divider_after", False)),
        }

    return {
        "reasoning": str(result.get("reasoning") or "").strip(),
        "sections": by_id,
    }


def _summarise_plan(plan: dict[str, Any]) -> str:
    """One-line plan summary for logs + the planner's previous_plans block."""
    from src.generation._fit_planner_helpers import summarise_plan  # noqa: PLC0415

    return summarise_plan(plan)


def _apply_fit_plan(document: ResumeDocument, plan: dict[str, Any]) -> ResumeDocument:
    """Deterministically apply a fit plan returned by the LLM.

    Delegates to the helper module so the planner/apply logic stays
    importable without pulling all of ``resume_builder`` (which has a
    heavy import surface). The per-bullet rewriter callable is injected
    here so the helper module never imports from this file.
    """
    from src.generation._fit_planner_helpers import apply_fit_plan  # noqa: PLC0415

    return apply_fit_plan(
        document,
        plan,
        bullet_rewriter=_rewrite_bullet_for_length,
    )
