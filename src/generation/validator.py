"""Validation checks for generated document IR."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from src.documents.page_count import get_docx_page_count, get_pdf_page_count
from src.generation.ir import ResumeDocument, ValidationIssue, ValidationResult


def validate_resume_document(
    document: ResumeDocument,
    *,
    jd_tags: list[str] | None = None,
    max_bullet_words: int = 32,
    max_estimated_pages: int = 1,
) -> ValidationResult:
    """Run deterministic safety and fit checks before rendering."""
    issues: list[ValidationIssue] = []
    bullets = [
        bullet
        for item in [*document.experiences, *document.projects]
        for bullet in item.bullets
    ]

    if not document.header.get("full_name"):
        issues.append(
            ValidationIssue(
                type="missing_header_name",
                severity="error",
                section="header",
                message="Resume header is missing the applicant name.",
            )
        )

    if not bullets:
        issues.append(
            ValidationIssue(
                type="no_evidence_bullets",
                severity="warning",
                message="No evidence bullets were selected for this resume.",
            )
        )

    for section, items in (("experience", document.experiences), ("projects", document.projects)):
        for item in items:
            if not item.bullets:
                issues.append(
                    ValidationIssue(
                        type="empty_item",
                        severity="info",
                        section=section,
                        item=item.name,
                        source_id=item.source_id,
                        message=f"{item.name} has no selected bullets.",
                    )
                )
            for index, bullet in enumerate(item.bullets):
                word_count = _word_count(bullet.text)
                if word_count > max_bullet_words:
                    issues.append(
                        ValidationIssue(
                            type="bullet_too_long",
                            severity="warning",
                            section=section,
                            item=item.name,
                            source_id=bullet.source_id,
                            message="Bullet exceeds the target word budget.",
                            details={
                                "bullet_index": index,
                                "current_words": word_count,
                                "max_words": max_bullet_words,
                            },
                        )
                    )

                if bullet.original_text:
                    added_numbers = _added_numbers(bullet.original_text, bullet.text)
                    if added_numbers:
                        issues.append(
                            ValidationIssue(
                                type="added_unverified_number",
                                severity="error",
                                section=section,
                                item=item.name,
                                source_id=bullet.source_id,
                                message="Rewritten bullet appears to introduce new numbers.",
                                details={"numbers": added_numbers},
                            )
                        )

    repeated_verbs = _repeated_action_verbs([bullet.text for bullet in bullets])
    if repeated_verbs:
        issues.append(
            ValidationIssue(
                type="repeated_action_verbs",
                severity="info",
                message="Several bullets start with the same action verb.",
                details={"verbs": repeated_verbs},
            )
        )

    coverage = _keyword_coverage(document, jd_tags or [])
    if jd_tags and coverage["coverage_ratio"] < 0.35:
        issues.append(
            ValidationIssue(
                type="low_keyword_coverage",
                severity="warning",
                message="Resume covers few target JD keywords.",
                details=coverage,
            )
        )

    estimated_pages = _estimate_pages(document)
    if estimated_pages > max_estimated_pages:
        issues.append(
            ValidationIssue(
                type="estimated_page_overflow",
                severity="warning",
                message="Resume may exceed the configured page target.",
                details={"estimated_pages": estimated_pages, "max_pages": max_estimated_pages},
            )
        )

    metrics = {
        "bullet_count": len(bullets),
        "experience_count": len(document.experiences),
        "project_count": len(document.projects),
        "estimated_pages": estimated_pages,
        **coverage,
    }
    return ValidationResult(
        ok=not any(issue.severity == "error" for issue in issues),
        issues=issues,
        metrics=metrics,
    )


def validate_resume_artifacts(
    validation: ValidationResult,
    *,
    docx_path: Path | None,
    pdf_path: Path | None = None,
    pdf_attempted: bool = False,
    max_pages: int = 1,
) -> ValidationResult:
    """Add deterministic renderer/file-system checks to an existing validation result."""
    issues = list(validation.issues)
    metrics = dict(validation.metrics)

    docx_ok = bool(docx_path and docx_path.exists() and docx_path.stat().st_size > 0)
    pdf_ok = bool(pdf_path and pdf_path.exists() and pdf_path.stat().st_size > 0)
    pdf_pages = get_pdf_page_count(pdf_path)
    docx_pages = get_docx_page_count(docx_path, rendered_pdf_path=pdf_path)
    metrics.update(
        {
            "docx_generated": docx_ok,
            "docx_path": str(docx_path) if docx_path else None,
            "docx_page_count": docx_pages,
            "pdf_generated": pdf_ok,
            "pdf_path": str(pdf_path) if pdf_path else None,
            "pdf_page_count": pdf_pages,
        }
    )

    if not docx_ok:
        issues.append(
            ValidationIssue(
                type="docx_generation_failed",
                severity="error",
                message="DOCX renderer did not produce a valid file.",
                details={"path": str(docx_path) if docx_path else None},
            )
        )

    if pdf_attempted and not pdf_ok:
        issues.append(
            ValidationIssue(
                type="pdf_generation_failed",
                severity="warning",
                message="PDF conversion did not produce a valid file.",
                details={"path": str(pdf_path) if pdf_path else None},
            )
        )

    rendered_pages = pdf_pages or docx_pages
    if rendered_pages is not None and rendered_pages > max_pages:
        issues.append(
            ValidationIssue(
                type="rendered_page_overflow",
                severity="warning",
                message="Rendered document exceeds the configured page target.",
                details={"page_count": rendered_pages, "max_pages": max_pages},
            )
        )

    return ValidationResult(
        ok=not any(issue.severity == "error" for issue in issues),
        issues=issues,
        metrics=metrics,
    )


def validate_cover_letter_artifacts(
    *,
    docx_path: Path | None,
    pdf_path: Path | None = None,
    pdf_attempted: bool = False,
    max_pages: int = 1,
) -> ValidationResult:
    """Validate rendered cover letter files."""
    base = ValidationResult(ok=True, issues=[], metrics={})
    return validate_resume_artifacts(
        base,
        docx_path=docx_path,
        pdf_path=pdf_path,
        pdf_attempted=pdf_attempted,
        max_pages=max_pages,
    )


def _word_count(value: str) -> int:
    return len(re.findall(r"\b[\w+#.]+\b", value))


def _numbers(value: str) -> set[str]:
    return set(re.findall(r"\b\d+(?:\.\d+)?%?\+?\b", value))


def _added_numbers(original: str, rewritten: str) -> list[str]:
    return sorted(_numbers(rewritten) - _numbers(original))


def _repeated_action_verbs(bullets: list[str]) -> dict[str, int]:
    verbs = []
    for bullet in bullets:
        match = re.search(r"[A-Za-z]+", bullet)
        if match:
            verbs.append(match.group(0).lower())
    counts = Counter(verbs)
    return {verb: count for verb, count in counts.items() if count >= 3}


def _keyword_coverage(document: ResumeDocument, jd_tags: list[str]) -> dict:
    normalized_tags = {_normalize(tag) for tag in jd_tags if _normalize(tag)}
    if not normalized_tags:
        return {"covered_keywords": [], "missing_keywords": [], "coverage_ratio": 0.0}

    text_parts = []
    text_parts.extend(document.summary)
    for values in document.skills.values():
        text_parts.extend(values)
    for item in [*document.experiences, *document.projects]:
        text_parts.extend([item.name, item.title, item.organization, *item.tech_stack])
        text_parts.extend(bullet.text for bullet in item.bullets)

    haystack = {
        _normalize(token)
        for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.]+", " ".join(text_parts))
    }
    covered = sorted(tag for tag in normalized_tags if tag in haystack)
    missing = sorted(normalized_tags - set(covered))
    return {
        "covered_keywords": covered,
        "missing_keywords": missing,
        "coverage_ratio": round(len(covered) / len(normalized_tags), 3),
    }


def _estimate_pages(document: ResumeDocument) -> int:
    bullet_count = sum(len(item.bullets) for item in [*document.experiences, *document.projects])
    item_count = len(document.education) + len(document.experiences) + len(document.projects)
    skill_count = sum(len(values) for values in document.skills.values())
    estimated_lines = 5 + item_count * 2 + bullet_count * 2 + max(1, skill_count // 6)
    return max(1, (estimated_lines + 42) // 43)


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9+#.]+", "_", value.lower().strip()).strip("_")
