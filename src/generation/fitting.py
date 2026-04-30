"""Content fitting for template capacity constraints."""

from __future__ import annotations

import re

from src.documents.templates import TemplateManifest
from src.generation.ir import ResumeDocument, ResumeItem


def fit_resume_document_to_template(
    document: ResumeDocument,
    manifest: TemplateManifest,
) -> ResumeDocument:
    """Return a copy of the resume IR constrained by template capacity.

    Fitting removes or shortens content; it never invents new claims or changes
    template formatting. Visual details remain in template.docx/styles.
    """
    if manifest.document_type != "resume":
        return document

    fitted = document.model_copy(deep=True)
    fitted.template_id = manifest.template_id
    if manifest.section_order:
        fitted.section_order = list(manifest.section_order)

    if not _section_enabled(manifest, "summary"):
        fitted.summary = []
    else:
        fitted.summary = fitted.summary[: _section_limit(manifest, "summary", "max_items", 1)]

    if not _section_enabled(manifest, "education"):
        fitted.education = []
    else:
        fitted.education = fitted.education[
            : _section_limit(manifest, "education", "max_items", len(fitted.education))
        ]

    fitted.experiences = _fit_items(
        fitted.experiences,
        manifest,
        section="experience",
        max_items=manifest.capacity.max_experience_items,
    )
    fitted.projects = _fit_items(
        fitted.projects,
        manifest,
        section="projects",
        max_items=manifest.capacity.max_project_items,
    )
    fitted.skills = _fit_skills(fitted.skills, manifest)
    _fit_total_bullets(fitted, manifest.capacity.max_bullets_total)
    fitted.metadata = {
        **fitted.metadata,
        "template_id": manifest.template_id,
        "template_capacity": manifest.capacity.model_dump(mode="json"),
    }
    return fitted


def _fit_items(
    items: list[ResumeItem],
    manifest: TemplateManifest,
    *,
    section: str,
    max_items: int | None,
) -> list[ResumeItem]:
    if not _section_enabled(manifest, section):
        return []

    max_item_count = _section_limit(manifest, section, "max_items", max_items or len(items))
    max_bullets = _section_limit(manifest, section, "max_bullets_per_item", 4)
    max_words = _section_limit(
        manifest,
        section,
        "max_words_per_bullet",
        manifest.capacity.max_words_per_bullet or 24,
    )

    fitted_items = [item.model_copy(deep=True) for item in items[:max_item_count]]
    for item in fitted_items:
        item.bullets = sorted(item.bullets, key=lambda bullet: bullet.score, reverse=True)[
            :max_bullets
        ]
        for bullet in item.bullets:
            bullet.text = _trim_words(bullet.text, max_words)
    return fitted_items


def _fit_skills(skills: dict[str, list[str]], manifest: TemplateManifest) -> dict[str, list[str]]:
    if not _section_enabled(manifest, "skills"):
        return {}
    max_lines = _section_limit(
        manifest,
        "skills",
        "max_lines",
        manifest.capacity.max_skill_lines or len(skills),
    )
    return {key: values for index, (key, values) in enumerate(skills.items()) if index < max_lines}


def _fit_total_bullets(document: ResumeDocument, max_total: int | None) -> None:
    if not max_total:
        return
    while _bullet_count(document) > max_total:
        weakest = None
        for item in [*document.projects, *document.experiences]:
            if not item.bullets:
                continue
            candidate = min(item.bullets, key=lambda bullet: bullet.score)
            if weakest is None or candidate.score < weakest[1].score:
                weakest = (item, candidate)
        if weakest is None:
            return
        weakest[0].bullets.remove(weakest[1])


def _bullet_count(document: ResumeDocument) -> int:
    return sum(len(item.bullets) for item in [*document.experiences, *document.projects])


def _trim_words(text: str, max_words: int | None) -> str:
    if not max_words:
        return text
    words = re.findall(r"\S+", text)
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(".,;:")


def _section_enabled(manifest: TemplateManifest, section: str) -> bool:
    config = manifest.sections.get(section)
    return True if config is None else config.enabled


def _section_limit(
    manifest: TemplateManifest,
    section: str,
    field: str,
    default: int,
) -> int:
    config = manifest.sections.get(section)
    value = getattr(config, field, None) if config else None
    return int(value if value is not None else default)
