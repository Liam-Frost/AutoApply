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
import re
from pathlib import Path
from typing import Any

from src.documents.docx_engine import build_cover_letter_from_ir
from src.documents.file_manager import get_output_paths
from src.documents.latex_engine import build_cover_letter_tex_from_ir, compile_latex_to_pdf
from src.documents.pdf_converter import convert_to_pdf
from src.documents.templates import (
    TemplateManifest,
    default_manifest,
    ensure_template_package,
    load_template_package,
)
from src.generation.evidence import select_relevant_evidence
from src.generation.ir import CoverLetterDocument, CoverLetterParagraph
from src.generation.validator import (
    validate_cover_letter_artifacts,
    validate_cover_letter_document,
    validate_latex_artifacts,
)
from src.intake.schema import RawJob
from src.utils.llm import LLMError, generate_text

logger = logging.getLogger("autoapply.generation.cover_letter")

DEFAULT_OUTPUT_DIR = Path("data/output")

# How many LLM re-asks to take before falling back to a hard paragraph
# trim. Each round costs one LLM call (~30-60s), so the cap directly
# determines the worst-case generation latency. 1 retry keeps total
# wall time within the front-end's poll budget while still giving the
# LLM a second shot when the first draft missed the page target.
_MAX_LLM_LENGTH_REGENS = 1
# Absolute ceiling so a degenerate "LLM always returns junk" loop still
# terminates with *some* output. Higher than _MAX_LLM_LENGTH_REGENS so
# the deterministic paragraph-drop fallback still gets attempts.
_MAX_RENDER_PASSES = 4


def _render_cover_letter_to_target_pages(
    *,
    document,
    template_path: Path | None,
    template_manifest,
    docx_output: Path,
    pdf_output: Path,
    target_pages: int,
    job: RawJob | None = None,
    profile_data: dict[str, Any] | None = None,
    evidence_bullets: list[str] | None = None,
    use_llm: bool = True,
    strategy: dict[str, Any] | None = None,
):
    """Render the cover letter, then iteratively ask the LLM for a longer
    or shorter draft until the produced PDF matches the target page count.

    The previous implementation chopped paragraphs to hit the page
    budget. That was the wrong call: cover letters are LLM-generated, so
    the LLM is the right place to lengthen or shorten the prose. The
    pipeline now feeds the rendered page count back into the prompt and
    re-generates, only falling back to a hard paragraph drop if the LLM
    refuses to converge (e.g. provider outage, rate limit).
    """
    from src.documents.page_count import get_pdf_page_count  # noqa: PLC0415

    current = document

    def _render_and_count(doc):
        docx = build_cover_letter_from_ir(
            doc,
            docx_output,
            template_path=template_path,
            manifest=template_manifest,
        )
        pdf: Path | None = None
        try:
            pdf = convert_to_pdf(docx, pdf_output)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cover letter PDF conversion failed: %s", exc)
        pages = get_pdf_page_count(pdf) if pdf else None
        return docx, pdf, pages

    docx_path, pdf_path, pages = _render_and_count(current)
    if target_pages <= 0 or pages is None:
        return current, docx_path, pdf_path

    llm_regens = 0
    for attempt in range(_MAX_RENDER_PASSES):
        if pages == target_pages:
            return current, docx_path, pdf_path

        if (
            use_llm
            and llm_regens < _MAX_LLM_LENGTH_REGENS
            and job is not None
            and profile_data is not None
            and evidence_bullets is not None
        ):
            feedback = _length_feedback_message(
                rendered_pages=pages,
                target_pages=target_pages,
                current_text="\n\n".join(p.text for p in current.paragraphs),
            )
            logger.info(
                "Cover letter rendered %d pages, target %d; asking LLM to %s "
                "(LLM regen %d/%d).",
                pages,
                target_pages,
                "shorten" if pages > target_pages else "lengthen",
                llm_regens + 1,
                _MAX_LLM_LENGTH_REGENS,
            )
            try:
                new_text = _generate_with_llm(
                    job,
                    profile_data,
                    evidence_bullets,
                    target_pages=target_pages,
                    length_feedback=feedback,
                    previous_attempt="\n\n".join(p.text for p in current.paragraphs),
                    strategy=strategy,
                )
            except LLMError as exc:
                logger.info(
                    "LLM length regen failed (%s); falling back to paragraph trim.",
                    exc,
                )
                llm_regens = _MAX_LLM_LENGTH_REGENS  # stop trying the LLM
            else:
                current = current.model_copy(
                    update={
                        "paragraphs": _cover_paragraphs_from_text(
                            new_text, evidence_bullets
                        )
                    }
                )
                current = _fit_cover_letter_document(current, template_manifest)
                llm_regens += 1
                docx_path, pdf_path, pages = _render_and_count(current)
                continue

        # Bounded fallback: only used when LLM regen is unavailable or
        # has refused to converge. Adds or removes a single paragraph
        # rather than relying on the LLM, so the loop still terminates.
        adjusted = (
            _drop_weakest_paragraph(current)
            if pages > target_pages
            else None  # cannot fabricate paragraphs without the LLM
        )
        if adjusted is None:
            logger.info(
                "Cover letter cannot be adjusted further (rendered %d, target %d).",
                pages,
                target_pages,
            )
            return current, docx_path, pdf_path
        current = adjusted
        docx_path, pdf_path, pages = _render_and_count(current)

    return current, docx_path, pdf_path


def _length_feedback_message(
    *, rendered_pages: int, target_pages: int, current_text: str
) -> str:
    """Build the natural-language steering message for the LLM regen."""
    min_words, target_words, max_words = _length_window_for(target_pages)
    actual_words = len(current_text.split())
    if rendered_pages > target_pages:
        delta = rendered_pages - target_pages
        return (
            f"Your previous draft was {rendered_pages} pages "
            f"({actual_words} words) but the template only allows "
            f"{target_pages} page(s). Rewrite the body to be SHORTER "
            f"({min_words}-{max_words} words, aim for {target_words}). "
            f"Cut about {delta} page worth of prose, tighten sentences, "
            "drop the least-impactful evidence, and remove repetition. "
            "Keep every grounded factual claim from the evidence list."
        )
    delta = target_pages - rendered_pages
    return (
        f"Your previous draft was only {rendered_pages} page(s) "
        f"({actual_words} words) but the template targets exactly "
        f"{target_pages} page(s). Rewrite the body to be LONGER "
        f"({min_words}-{max_words} words, aim for {target_words}). "
        f"Add about {delta} page worth of substantive content by going "
        "deeper into each evidence paragraph, expanding the company / role "
        "tie-in, and adding a separate paragraph that connects an "
        "additional applicant experience to a job requirement. Do NOT "
        "fabricate experiences, only elaborate on what is grounded in "
        "the evidence list."
    )


def _drop_weakest_paragraph(document):
    """Return a copy with the highest-impact, lowest-cost paragraph removed.

    Preference order:
    1. Drop a ``company_fit`` paragraph if present.
    2. Else drop one ``experience_evidence`` paragraph (keeping the rest).
    3. Else give up -- we will not delete the opening or closing.
    """
    paragraphs = list(document.paragraphs)
    if not paragraphs:
        return None

    drop_order = ("company_fit", "experience_evidence")
    for kind in drop_order:
        for idx, paragraph in enumerate(paragraphs):
            if paragraph.type == kind:
                if kind == "experience_evidence":
                    remaining = sum(
                        1
                        for other in paragraphs
                        if other.type == "experience_evidence"
                    )
                    if remaining <= 1:
                        continue
                trimmed = document.model_copy(deep=True)
                trimmed.paragraphs.pop(idx)
                return trimmed
    return None


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

    target_pages = template_manifest.target_pages or template_manifest.capacity.max_pages

    strategy = _infer_cover_letter_strategy(job, evidence_bullets)

    text_from_llm = False
    if use_llm:
        try:
            text = _generate_with_llm(
                job,
                profile_data,
                evidence_bullets,
                target_pages=target_pages,
                strategy=strategy,
            )
            text_from_llm = True
        except (LLMError, Exception) as e:
            logger.warning("LLM cover letter generation failed (%s), using template", e)
            text = _generate_template(
                job, identity, evidence_bullets, profile_data, strategy=strategy
            )
    else:
        text = _generate_template(
            job, identity, evidence_bullets, profile_data, strategy=strategy
        )

    paths = get_output_paths(
        company=job.company,
        role=job.title,
        output_dir=output_dir,
        pattern=template_manifest.filename_pattern,
        profile_name=profile_data.get("identity", {}).get("full_name", ""),
        custom_label=template_manifest.filename_custom_label,
        template_id=template_manifest.template_id,
    )

    document = build_cover_letter_document(
        job=job,
        profile_data=profile_data,
        body_text=text,
        evidence_bullets=evidence_bullets,
        strategy=strategy,
        quality_issues=[] if text_from_llm else None,
    )
    document = _fit_cover_letter_document(document, template_manifest)
    document, docx_path, pdf_path = _render_cover_letter_to_target_pages(
        document=document,
        template_path=template_path,
        template_manifest=template_manifest,
        docx_output=paths["cover_docx"],
        pdf_output=paths["cover_pdf"],
        target_pages=target_pages,
        job=job,
        profile_data=profile_data,
        evidence_bullets=evidence_bullets,
        use_llm=use_llm,
        strategy=strategy,
    )
    validation = validate_cover_letter_document(document, target_pages=target_pages)
    validation = validate_cover_letter_artifacts(
        validation,
        docx_path=docx_path,
        pdf_path=pdf_path,
        pdf_attempted=True,
        max_pages=template_manifest.capacity.max_pages,
        target_pages=target_pages,
    )

    logger.info("Generated cover letter for %s at %s", job.title, job.company)
    result: dict[str, Any] = {
        "text": text,
        "docx": docx_path,
        "ir": document,
        "validation": validation,
    }
    if pdf_path:
        result["pdf"] = pdf_path
    return result


def generate_cover_letter_latex(
    job: RawJob,
    profile_data: dict[str, Any],
    evidence_bullets: list[str] | None = None,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    use_llm: bool = True,
    template_id: str,
) -> dict[str, Any]:
    """Generate a tailored cover letter as LaTeX, with optional PDF compilation."""
    identity = profile_data.get("identity", {})
    package = load_template_package("cover_letter", template_id)
    if package.manifest.renderer != "latex":
        raise ValueError("Selected cover letter template is not a LaTeX template.")

    if evidence_bullets is None:
        evidence_bullets = _select_evidence(job, profile_data)

    target_pages = package.manifest.target_pages or package.manifest.capacity.max_pages

    strategy = _infer_cover_letter_strategy(job, evidence_bullets)

    text_from_llm = False
    if use_llm:
        try:
            text = _generate_with_llm(
                job,
                profile_data,
                evidence_bullets,
                target_pages=target_pages,
                strategy=strategy,
            )
            text_from_llm = True
        except (LLMError, Exception) as exc:
            logger.warning("LLM cover letter generation failed (%s), using template", exc)
            text = _generate_template(
                job, identity, evidence_bullets, profile_data, strategy=strategy
            )
    else:
        text = _generate_template(
            job, identity, evidence_bullets, profile_data, strategy=strategy
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
    document = build_cover_letter_document(
        job=job,
        profile_data=profile_data,
        body_text=text,
        evidence_bullets=evidence_bullets,
        strategy=strategy,
        quality_issues=[] if text_from_llm else None,
    )
    document = _fit_cover_letter_document(document, package.manifest)
    validation = validate_cover_letter_document(document, target_pages=target_pages)
    tex_path = build_cover_letter_tex_from_ir(
        package.template_path,
        document,
        paths["cover_tex"],
        manifest=package.manifest,
    )

    pdf_path = None
    try:
        pdf_path = compile_latex_to_pdf(tex_path, paths["cover_pdf"])
    except Exception as exc:
        logger.warning("LaTeX cover letter PDF compilation failed: %s", exc)

    validation = validate_latex_artifacts(
        validation,
        tex_path=tex_path,
        pdf_path=pdf_path,
        pdf_attempted=True,
        max_pages=package.manifest.capacity.max_pages,
        target_pages=target_pages,
    )

    result: dict[str, Any] = {
        "text": text,
        "tex": tex_path,
        "ir": document,
        "validation": validation,
    }
    if pdf_path:
        result["pdf"] = pdf_path
    logger.info("Generated LaTeX cover letter for %s at %s", job.title, job.company)
    return result


def build_cover_letter_document(
    *,
    job: RawJob,
    profile_data: dict[str, Any],
    body_text: str,
    evidence_bullets: list[str],
    strategy: dict[str, Any] | None = None,
    quality_issues: list[str] | None = None,
) -> CoverLetterDocument:
    """Create a structured cover letter IR from generated body text."""
    identity = profile_data.get("identity", {})
    if strategy is None:
        strategy = _infer_cover_letter_strategy(job, evidence_bullets)
    if quality_issues is None:
        quality_issues = _cover_letter_quality_issues(body_text, job_title=job.title)
    return CoverLetterDocument(
        recipient={"company": job.company, "hiring_manager": None, "location": job.location},
        applicant={
            "name": identity.get("full_name", ""),
            "email": identity.get("email", ""),
            "phone": identity.get("phone", ""),
            "location": identity.get("location", ""),
        },
        paragraphs=_cover_paragraphs_from_text(body_text, evidence_bullets),
        metadata={
            "target_role": job.title,
            "company": job.company,
            "role_type": strategy["role_type"],
            "capability_buckets": [
                bucket["name"] for bucket in strategy["capability_buckets"]
            ],
            "quality_issues": quality_issues,
        },
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


# Per-page word-count window. The cover letter renderer assumes 11pt
# Times New Roman with 0.85" margins, which fits ~340 words on a single
# page including the 5-paragraph frame. Multi-page targets multiply this.
_WORDS_PER_PAGE_TARGET = 340
_WORDS_PER_PAGE_MIN = 280
_WORDS_PER_PAGE_MAX = 400


def _length_window_for(target_pages: int) -> tuple[int, int, int]:
    """Return (min_words, target_words, max_words) for ``target_pages``.

    Used to drive both the LLM prompt (so it aims for the right length
    from the start) and the post-render validator (so a deliberately
    long 2-page letter is not flagged as too long).
    """
    pages = max(1, int(target_pages))
    return (
        _WORDS_PER_PAGE_MIN * pages,
        _WORDS_PER_PAGE_TARGET * pages,
        _WORDS_PER_PAGE_MAX * pages,
    )


def _cl_system_prompt(
    target_pages: int,
    strategy: dict[str, Any] | None = None,
) -> str:
    pages = max(1, int(target_pages))
    min_words, target_words, max_words = _length_window_for(pages)
    strategy = strategy or {}
    role_type = strategy.get("role_type") or "software_development"
    capability_block = _format_capability_buckets_for_prompt(
        strategy.get("capability_buckets") or []
    )
    if pages == 1:
        structure = (
            "1. OPENING (2 sentences): Candidate positioning, role title, "
            "company, and the specific engineering direction this role fits.\n\n"
            "2. CAPABILITY PARAGRAPH 1 (3-4 sentences): Use Claim -> Evidence "
            "-> Relevance for capability bucket #1.\n\n"
            "3. CAPABILITY PARAGRAPH 2 (3-4 sentences): Use Claim -> Evidence "
            "-> Relevance for capability bucket #2.\n\n"
            "4. WORK STYLE / COMPANY CONTEXT (2-3 sentences): Connect the "
            "role/company context to engineering habits such as maintainability, "
            "testing, reliability, documentation, or collaboration.\n\n"
            "5. CLOSE (2 sentences): Concisely return to the role's most "
            "important capability keywords."
        )
        paragraph_rule = "Use exactly 5 paragraphs separated by blank lines"
    else:
        extra_evidence = max(1, pages - 1)
        structure = (
            "1. OPENING (3-4 sentences): Candidate positioning, role title, "
            "company, and the specific engineering direction this role fits.\n\n"
            "2. CAPABILITY PARAGRAPHS (multiple): Provide "
            f"{2 + extra_evidence} evidence paragraphs of 4-5 sentences each, "
            "each organized around one role-relevant capability bucket with "
            "Claim -> Evidence -> Relevance.\n\n"
            "3. WORK STYLE / COMPANY CONTEXT (3-4 sentences): Explain how the "
            "role's constraints fit the applicant's engineering habits.\n\n"
            "4. CLOSE (2-3 sentences): Return to the role's most important "
            "capability keywords."
        )
        paragraph_count = 2 + extra_evidence + 2  # opening + evidence + tie-in + close
        paragraph_rule = (
            f"Use exactly {paragraph_count} paragraphs separated by blank lines"
        )
    return f"""You are a professional cover letter writer. Generate a compelling
cover letter body sized for a {pages}-page letter.

Primary objective:
Do not summarize the resume. Build an evidence-based argument that the candidate
fits this specific role.

Role type: {role_type}

Capability buckets to use:
{capability_block}

Follow this EXACT structure:

{structure}

Process:
- Structure the letter around role-relevant capabilities, not project names.
- Use project/work examples only as evidence for a capability claim.
- For each body paragraph, use Claim -> Evidence -> Relevance.
- Include one company or role-context sentence that is specific but not flattering.
- Use specific engineering fit instead of generic enthusiasm.
- Mention the exact job title at most once. If the title contains a term,
  season, year, or slash-heavy label, rephrase it naturally after the opening
  as "this role", "the position", "the team", or a concise role family.

Rules:
- Total length: {min_words}-{max_words} words (aim for around {target_words}).
- {paragraph_rule}.
- Tone: confident but not arrogant, specific but not verbose.
- Do NOT use clichés like "I am writing to express my interest"
  or "I believe I would be a great fit".
- Do NOT use generic phrases like "passionate", "strong candidate",
  "valuable addition", or "perfect fit".
- Do NOT fabricate experiences, skills, or achievements not in the provided profile.
- Do NOT include a greeting line (Dear Hiring Manager)
  or sign-off (Sincerely), those are added separately.
- Do NOT use em dashes or en dashes. Prefer commas, periods, or semicolons.
- Do NOT list more than 4 technologies in one sentence.
- Every technology mention must support maintainability, testing/debugging,
  reliability, integration, security, performance, or user-facing impact.

Inline formatting (use sparingly, OPTIONAL):
- ``**text**`` -- bold for a small number of named technologies or
  quantified outcomes ("**1.5M+ requests/day**", "**FastAPI**") so the
  reader's eye lands on the strongest evidence. Aim for at most 2-3
  bolded spans per letter; one per paragraph is plenty.
- ``*text*`` -- italics for proper nouns / product / paper names where
  italicisation is conventional.
- Do NOT use any other Markdown -- no headings, lists, links, code
  fences, or ``_underscores_``.

- Output ONLY the body text of the cover letter."""


def _format_capability_buckets_for_prompt(buckets: list[dict[str, Any]]) -> str:
    if not buckets:
        return "- software development and maintainability"
    lines = []
    for index, bucket in enumerate(buckets[:3], start=1):
        evidence = bucket.get("candidate_evidence") or []
        evidence_text = "; ".join(str(item) for item in evidence[:2]) or "selected profile evidence"
        signals = ", ".join(bucket.get("jd_signals") or []) or bucket.get("name", "")
        lines.append(
            f"{index}. {bucket.get('name')} | JD signals: {signals} | "
            f"candidate evidence: {evidence_text}"
        )
    return "\n".join(lines)


# Back-compat alias for any callers that imported the constant directly.
_CL_SYSTEM = _cl_system_prompt(1)

_INVALID_LLM_OUTPUT_PATTERNS = (
    "please paste the system instructions",
    "paste the system instructions",
    "system instructions you want me to follow",
    "if you want me to inspect or modify",
    "point me to the relevant file",
    "openai codex",
    "tokens used",
    "reading additional input from stdin",
)

_FORBIDDEN_COVER_LETTER_PHRASES = (
    "i am passionate about",
    "i believe my skills",
    "i believe i would",
    "strong candidate",
    "valuable addition",
    "perfect fit",
)

_TECH_TERMS = (
    "python",
    "java",
    "javascript",
    "typescript",
    "react",
    "next.js",
    "fastapi",
    "flask",
    "postgresql",
    "sqlite",
    "redis",
    "docker",
    "kubernetes",
    "aws",
    "nginx",
    "https",
    "cloudflare",
    "systemd",
    "kafka",
    "graphql",
    "rest",
    "api",
    "apis",
)


_TECH_TERM_RE = re.compile(
    r"(?<![\w.+-])(" + "|".join(re.escape(term) for term in _TECH_TERMS) + r")(?![\w.+-])"
)


def _infer_cover_letter_strategy(
    job: RawJob,
    evidence_bullets: list[str],
) -> dict[str, Any]:
    role_type = _classify_cover_letter_role(job)
    job_text = _job_signal_text(job).lower()
    boosts = _role_bucket_boosts(role_type)
    buckets = []
    for bucket in _CAPABILITY_BUCKETS:
        score = sum(2 for signal in bucket["signals"] if signal in job_text)
        if bucket["name"] in boosts:
            score += boosts[bucket["name"]]
        matched_evidence = _match_bucket_evidence(bucket, evidence_bullets)
        if matched_evidence:
            score += 1
        buckets.append(
            {
                **bucket,
                "score": score,
                "candidate_evidence": matched_evidence or evidence_bullets[:1],
            }
        )

    buckets.sort(key=lambda bucket: bucket["score"], reverse=True)
    selected = buckets[:3]
    if len(selected) < 3:
        selected.extend(bucket for bucket in buckets if bucket not in selected)
    return {
        "role_type": role_type,
        "capability_buckets": selected[:3],
        "quality_focus": _quality_focus_for_role(role_type),
    }


def _classify_cover_letter_role(job: RawJob) -> str:
    text = _job_signal_text(job).lower()
    if any(term in text for term in ("embedded", "firmware", "microcontroller", "rtos")):
        return "embedded_firmware"
    if any(term in text for term in ("test", "testing", "verification", "qa", "quality")):
        return "software_development_test"
    if re.search(r"\b(ai|agent|automation|workflow)\b", text):
        return "ai_automation"
    if any(term in text for term in ("security", "defense", "mission", "secure")):
        return "security_mission_systems"
    if any(term in text for term in ("backend", "api", "database", "service")):
        return "backend"
    return "software_development"


def _job_signal_text(job: RawJob) -> str:
    requirements = getattr(job, "requirements", None)
    parts = [job.title or "", job.company or "", job.description or ""]
    if requirements is not None:
        for attr in (
            "must_have_skills",
            "preferred_skills",
            "responsibilities",
            "soft_skills",
            "keywords",
        ):
            values = getattr(requirements, attr, []) or []
            parts.extend(str(value) for value in values if value)
        parts.extend(
            str(value)
            for value in (
                requirements.domain,
                requirements.role_family,
                requirements.seniority,
            )
            if value
        )
    return "\n".join(parts)


_CAPABILITY_BUCKETS: list[dict[str, Any]] = [
        {
            "name": "software development and maintainability",
            "signals": [
                "software development",
                "implementation",
                "maintainable",
                "api",
                "backend",
                "data model",
            ],
            "evidence_terms": ["api", "backend", "data", "model", "validation"],
            "claim": "building maintainable software systems",
            "relevance": (
                "it depends on clear interfaces, validation, and implementation "
                "choices that remain understandable after the first version works"
            ),
        },
        {
            "name": "testing, debugging, and reliability",
            "signals": [
                "test",
                "testing",
                "debug",
                "verification",
                "reliability",
                "quality",
                "edge case",
            ],
            "evidence_terms": ["test", "debug", "reliab", "edge", "coverage", "trace"],
            "claim": "testing, debugging, and reliability-focused implementation",
            "relevance": (
                "the work rewards engineers who verify assumptions, trace failures "
                "carefully, and treat correctness as part of implementation"
            ),
        },
        {
            "name": "systems integration and collaboration",
            "signals": [
                "integration",
                "collaboration",
                "team",
                "service",
                "workflow",
                "cross-functional",
            ],
            "evidence_terms": [
                "integrat",
                "service",
                "workflow",
                "frontend",
                "backend",
                "team",
            ],
            "claim": "working across system boundaries",
            "relevance": (
                "many engineering failures appear between components, so integration "
                "work requires communication, careful debugging, and attention to "
                "end-to-end behavior"
            ),
        },
        {
            "name": "security, correctness, and controlled change",
            "signals": [
                "security",
                "secure",
                "defense",
                "mission",
                "correctness",
                "documentation",
                "risk",
            ],
            "evidence_terms": ["security", "auth", "document", "reliab", "correct", "risk"],
            "claim": "reliability and careful engineering judgment",
            "relevance": (
                "secure or mission-sensitive systems need controlled changes, "
                "documentation, and a habit of checking assumptions before relying "
                "on software behavior"
            ),
        },
        {
            "name": "workflow automation and data quality",
            "signals": ["automation", "ai", "agent", "workflow", "data quality", "review"],
            "evidence_terms": ["automation", "agent", "workflow", "data", "review"],
            "claim": "designing automation around data quality and review boundaries",
            "relevance": (
                "useful automation depends on reliable inputs, explicit failure "
                "handling, and human review where software should not overreach"
            ),
        },
        {
            "name": "embedded interfaces and low-level debugging",
            "signals": ["embedded", "firmware", "hardware", "interface", "real-time", "rtos"],
            "evidence_terms": ["embedded", "hardware", "interface", "control", "system"],
            "claim": "reasoning about software at interface boundaries",
            "relevance": (
                "embedded work requires careful debugging where software behavior is "
                "constrained by hardware, timing, and resource limits"
            ),
        },
    ]


_ROLE_BUCKET_BOOSTS_DEFAULT: dict[str, int] = {"software development and maintainability": 3}
_ROLE_BUCKET_BOOSTS: dict[str, dict[str, int]] = {
    "software_development_test": {
        "testing, debugging, and reliability": 5,
        "software development and maintainability": 3,
        "systems integration and collaboration": 2,
    },
    "backend": {
        "software development and maintainability": 5,
        "systems integration and collaboration": 3,
        "testing, debugging, and reliability": 2,
    },
    "security_mission_systems": {
        "security, correctness, and controlled change": 5,
        "testing, debugging, and reliability": 3,
        "software development and maintainability": 2,
    },
    "ai_automation": {
        "workflow automation and data quality": 5,
        "testing, debugging, and reliability": 2,
        "systems integration and collaboration": 2,
    },
    "embedded_firmware": {
        "embedded interfaces and low-level debugging": 5,
        "testing, debugging, and reliability": 3,
        "software development and maintainability": 1,
    },
}


def _role_bucket_boosts(role_type: str) -> dict[str, int]:
    return _ROLE_BUCKET_BOOSTS.get(role_type, _ROLE_BUCKET_BOOSTS_DEFAULT)


def _match_bucket_evidence(bucket: dict[str, Any], evidence_bullets: list[str]) -> list[str]:
    terms = [str(term).lower() for term in bucket.get("evidence_terms", [])]
    matches = [
        evidence
        for evidence in evidence_bullets
        if any(term in evidence.lower() for term in terms)
    ]
    return matches[:2]


def _quality_focus_for_role(role_type: str) -> list[str]:
    focus = {
        "software_development_test": [
            "testability",
            "verification",
            "edge cases",
            "debugging discipline",
            "reliability",
        ],
        "backend": ["API design", "data modeling", "service boundaries", "maintainability"],
        "security_mission_systems": [
            "reliability",
            "documentation",
            "controlled change",
            "correctness",
            "secure systems",
        ],
        "ai_automation": [
            "workflow design",
            "data quality",
            "human review",
            "error handling",
        ],
        "embedded_firmware": [
            "hardware/software boundaries",
            "low-level debugging",
            "interfaces",
            "resource constraints",
        ],
    }
    return focus.get(role_type, ["maintainability", "debugging", "collaboration"])


def _format_cover_strategy_for_prompt(strategy: dict[str, Any]) -> str:
    focus = ", ".join(strategy.get("quality_focus") or [])
    return f"Quality focus: {focus}"


def _format_role_references_for_prompt(role_refs: dict[str, str]) -> str:
    return (
        f"opening={role_refs['opening']}; body={role_refs['body']}; "
        f"context={role_refs['context']}; closing={role_refs['closing']}"
    )


def _generate_with_llm(
    job: RawJob,
    profile_data: dict[str, Any],
    evidence_bullets: list[str],
    *,
    target_pages: int = 1,
    length_feedback: str | None = None,
    previous_attempt: str | None = None,
    strategy: dict[str, Any] | None = None,
) -> str:
    """Generate cover letter body using the configured LLM.

    ``length_feedback`` is an optional natural-language steering message
    appended when the previous render's page count did not match the
    template target -- used by the iterative renderer below to ask for
    a longer or shorter draft instead of crudely chopping paragraphs.
    """
    identity = profile_data.get("identity", {})
    skills = profile_data.get("skills", {})
    if strategy is None:
        strategy = _infer_cover_letter_strategy(job, evidence_bullets)
    system_prompt = _cl_system_prompt(target_pages, strategy)
    role_refs = _role_references(job, strategy)

    # Build context for the LLM
    evidence_text = "\n".join(f"- {b}" for b in evidence_bullets)

    skill_summary = []
    for category, items in skills.items():
        if isinstance(items, list) and items:
            skill_summary.append(f"{category}: {', '.join(items[:8])}")
    skills_text = "\n".join(skill_summary)

    feedback_block = ""
    if length_feedback:
        feedback_block = (
            "\n<length_feedback>\n"
            f"{length_feedback}\n"
            "Rewrite the cover letter body to match the requested length while "
            "preserving every grounded claim from the evidence above.\n"
            "</length_feedback>\n"
        )
    if previous_attempt:
        feedback_block += (
            "\n<previous_attempt>\n"
            f"{previous_attempt}\n"
            "</previous_attempt>\n"
        )

    prompt = f"""Write a cover letter body for this application.

<cover_letter_instructions>
{system_prompt}
</cover_letter_instructions>

<job>
Company: {job.company}
Role: {job.title}
Natural role references: {_format_role_references_for_prompt(role_refs)}
Location: {job.location or "Not specified"}

Job Description:
{(job.description or "")[:3000]}
</job>

<applicant>
Name: {identity.get("full_name", "")}
Education: {_format_education_brief(profile_data.get("education", []))}

Role strategy:
{_format_cover_strategy_for_prompt(strategy)}

Key evidence points from my experience:
{evidence_text}

Skills:
{skills_text}
</applicant>
{feedback_block}
Generate the cover letter body following the instructions above."""

    raw = generate_text(prompt, system=system_prompt, timeout=90)
    return _clean_llm_cover_letter_output(
        raw,
        target_pages=target_pages,
        job_title=job.title,
    )


def _clean_llm_cover_letter_output(
    raw: str,
    *,
    target_pages: int = 1,
    job_title: str | None = None,
) -> str:
    """Reject CLI/meta responses so they fall back to deterministic templates.

    The min/max word window scales with ``target_pages`` so the same
    validator works for 1-page and 2-page letters without lying about
    the budget.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()

    lower = text.lower()
    if not text:
        raise LLMError("LLM returned an empty cover letter.")
    if any(pattern in lower for pattern in _INVALID_LLM_OUTPUT_PATTERNS):
        raise LLMError("LLM returned a meta-response instead of a cover letter.")
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    min_words, _, max_words = _length_window_for(target_pages)
    # Allow a wider tolerance than the prompt target because the
    # iterative feedback loop is what will tighten the actual length.
    if len(text.split()) < int(min_words * 0.7):
        raise LLMError("LLM returned a cover letter that is too short.")
    if len(text.split()) > int(max_words * 1.5):
        raise LLMError("LLM returned a cover letter that is too long.")
    min_paragraphs = 4 if target_pages == 1 else 4 + (target_pages - 1)
    if len(paragraphs) < min_paragraphs:
        raise LLMError("LLM returned a cover letter without enough paragraph structure.")
    text = _normalize_cover_letter_dashes(text)
    quality_issues = _cover_letter_quality_issues(text, job_title=job_title)
    if quality_issues:
        raise LLMError(
            "LLM returned a cover letter that failed quality checks: "
            + "; ".join(quality_issues)
        )
    return text


def _normalize_cover_letter_dashes(text: str) -> str:
    """Remove dash punctuation that makes cover letters read AI-generated."""
    cleaned = re.sub(r"\s*[—–]\s*", ", ", text)
    cleaned = re.sub(r",\s*,+", ",", cleaned)
    return re.sub(r" {2,}", " ", cleaned).strip()


def _cover_letter_quality_issues(text: str, *, job_title: str | None = None) -> list[str]:
    issues: list[str] = []
    lower = text.lower()
    for phrase in _FORBIDDEN_COVER_LETTER_PHRASES:
        if phrase in lower:
            issues.append(f"generic_phrase:{phrase}")
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        terms = _technology_terms_in_sentence(sentence)
        if len(terms) > 4:
            issues.append(f"technology_dumping:{', '.join(sorted(terms))}")
    title_repetitions = _raw_role_title_repetitions(text, job_title)
    if title_repetitions > 1:
        issues.append(f"repeated_raw_job_title:{title_repetitions}")
    return issues


def _raw_role_title_repetitions(text: str, job_title: str | None) -> int:
    title = _normalize_role_title_for_repetition(job_title)
    if not title or len(title.split()) < 3:
        return 0
    normalized_text = _normalize_role_title_for_repetition(text)
    return len(re.findall(rf"(?<!\w){re.escape(title)}(?!\w)", normalized_text))


def _normalize_role_title_for_repetition(value: str | None) -> str:
    text = (value or "").lower()
    text = re.sub(r"[–—]", "-", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _technology_terms_in_sentence(sentence: str) -> set[str]:
    return set(_TECH_TERM_RE.findall(sentence.lower()))


def _generate_template(
    job: RawJob,
    identity: dict[str, Any],
    evidence_bullets: list[str],
    profile_data: dict[str, Any] | None = None,
    *,
    strategy: dict[str, Any] | None = None,
) -> str:
    """Generate a deterministic fallback body when the LLM is unavailable.

    This is intentionally more than a bare placeholder: users see this
    when the LLM returns a bad/short answer, so it must still read like
    a complete professional cover-letter body. The DOCX/PDF renderer
    adds the salutation and sign-off around these paragraphs.
    """
    if strategy is None:
        strategy = _infer_cover_letter_strategy(job, evidence_bullets)
    buckets = strategy["capability_buckets"]
    background = _candidate_background(identity, profile_data)
    capability_phrase = _join_natural(
        [bucket["claim"] for bucket in buckets[:3]], conjunction="and"
    )
    role_refs = _role_references(job, strategy)
    context = _role_context_sentence(job, strategy)
    opening = (
        f"As a {background} with hands-on experience in {capability_phrase}, I am "
        f"applying for {role_refs['opening']} at {job.company}. What draws me to "
        f"this role is {context}."
    )

    evidence_parts = [_clean_evidence_sentence(bullet) for bullet in evidence_bullets[:3]]
    if not evidence_parts:
        evidence_parts = [
            "My project work has required me to break ambiguous requirements into testable "
            "software components.",
            "I have built and debugged full-stack systems where backend reliability and "
            "frontend usability both mattered.",
            "I have practiced communicating tradeoffs clearly while continuing to learn new "
            "tools quickly.",
        ]

    first_evidence = _evidence_for_bucket(buckets[0], evidence_parts, 0)
    second_evidence = _evidence_for_bucket(buckets[1], evidence_parts, 1)
    evidence_one = _fallback_capability_paragraph(
        bucket=buckets[0],
        evidence=first_evidence,
        role_label=role_refs["body"],
        company=job.company,
        ordinal="A central area of fit",
    )

    evidence_two = _fallback_capability_paragraph(
        bucket=buckets[1],
        evidence=second_evidence,
        role_label=role_refs["alternate"],
        company=job.company,
        ordinal="A second area of fit",
    )

    company_tie = (
        f"The context of {job.company}'s {role_refs['context']} matters to me because "
        f"{context}. My work style is to make assumptions visible, document decisions, "
        "and debug from the user workflow back to implementation details. That approach "
        "fits teams where maintainability, testing, and reliability matter as much as "
        "initial delivery."
    )

    closing_terms = _join_natural([bucket["name"] for bucket in buckets[:2]], conjunction="and")
    close = (
        f"I would welcome the opportunity to discuss how my experience with "
        f"{closing_terms} could support {job.company}'s {role_refs['closing']}. "
        "Thank you for your time and consideration."
    )

    return _normalize_cover_letter_dashes(
        f"{opening}\n\n{evidence_one}\n\n{evidence_two}\n\n{company_tie}\n\n{close}"
    )


def _candidate_background(
    identity: dict[str, Any],
    profile_data: dict[str, Any] | None,
) -> str:
    headline = str(identity.get("headline") or "").strip()
    if headline:
        return headline
    for education in (profile_data or {}).get("education", []) or []:
        if not isinstance(education, dict):
            continue
        field = str(education.get("field") or "").strip()
        degree = str(education.get("degree") or "").strip()
        if field:
            if "computer" in field.lower() or "software" in field.lower():
                return f"{field} student"
            return f"student in {field}"
        if degree:
            return f"{degree} student"
    return "software engineering candidate"


def _role_context_sentence(job: RawJob, strategy: dict[str, Any]) -> str:
    role_type = strategy.get("role_type")
    company_text = (job.company or "").lower()
    job_text = _job_signal_text(job).lower()
    if role_type == "software_development_test":
        return (
            "the combination of implementation, verification, and "
            "reliability-focused engineering"
        )
    if role_type == "security_mission_systems" or any(
        term in company_text or term in job_text
        for term in ("mission", "defense", "secure", "security")
    ):
        return (
            "the unusual weight the work places on reliability, clear "
            "documentation, and careful verification"
        )
    if role_type == "ai_automation":
        return (
            "the need for automation that is useful, bounded, and reliable "
            "under real workflow constraints"
        )
    if role_type == "embedded_firmware":
        return (
            "the connection between software correctness, interfaces, timing, "
            "and system-level constraints"
        )
    if role_type == "backend":
        return (
            "the emphasis on maintainable services, data flow, and debugging "
            "across system boundaries"
        )
    return (
        "the focus on practical software development, maintainability, and "
        "clear engineering judgment"
    )


def _role_references(job: RawJob, strategy: dict[str, Any]) -> dict[str, str]:
    concise = _cover_letter_role_title(job.title)
    role_family = _role_family_phrase(strategy.get("role_type"), concise)
    opening = f"the {concise} position" if concise else "this position"
    return {
        "opening": opening,
        "body": "this role",
        "alternate": "the position",
        "context": f"{role_family} work",
        "closing": f"{role_family} team",
    }


def _cover_letter_role_title(title: str) -> str:
    text = re.sub(r"\s+", " ", (title or "").strip())
    if not text:
        return "software engineering"
    parts = [part.strip() for part in re.split(r"\s+[-–—|]\s+", text) if part.strip()]
    if len(parts) > 1 and any(_looks_like_term_label(part) for part in parts[1:]):
        text = parts[0]
    text = re.sub(r"\b(20\d{2}|19\d{2})\b", "", text)
    text = re.sub(r"\b(spring|summer|fall|autumn|winter)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -/,")
    text = re.sub(r"\bIntern\s*/\s*Co-?op\b", "internship/co-op", text, flags=re.IGNORECASE)
    text = re.sub(r"\bCo-?op\s*/\s*Intern\b", "internship/co-op", text, flags=re.IGNORECASE)
    text = re.sub(r"\bIntern\b", "internship", text, flags=re.IGNORECASE)
    text = re.sub(r"\bCo-?op\b", "co-op", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -/,")
    return text.lower() if text else "software engineering"


def _looks_like_term_label(text: str) -> bool:
    lower = text.lower()
    return bool(re.search(r"\b(20\d{2}|19\d{2}|spring|summer|fall|autumn|winter)\b", lower))


def _role_family_phrase(role_type: str | None, concise_title: str) -> str:
    if role_type == "software_development_test":
        return "software development and test"
    if role_type == "backend":
        return "backend engineering"
    if role_type == "security_mission_systems":
        return "reliability-focused engineering"
    if role_type == "ai_automation":
        return "automation engineering"
    if role_type == "embedded_firmware":
        return "embedded software"
    if "software" in concise_title:
        return "software engineering"
    return "engineering"


def _evidence_for_bucket(
    bucket: dict[str, Any],
    evidence_parts: list[str],
    fallback_index: int,
) -> str:
    for evidence in bucket.get("candidate_evidence") or []:
        cleaned = _clean_evidence_sentence(evidence)
        if cleaned:
            return cleaned
    if not evidence_parts:
        return (
            "My project work has required me to turn ambiguous requirements "
            "into testable software components."
        )
    return evidence_parts[min(fallback_index, len(evidence_parts) - 1)]


def _fallback_capability_paragraph(
    *,
    bucket: dict[str, Any],
    evidence: str,
    role_label: str,
    company: str,
    ordinal: str,
) -> str:
    claim = bucket.get("claim") or bucket.get("name") or "practical engineering work"
    relevance = bucket.get("relevance") or "the role depends on careful technical judgment"
    return (
        f"{ordinal} for {role_label} is {claim}. {evidence} I treated that work "
        "as more than feature delivery, focusing on the engineering constraints "
        "behind the implementation. That is relevant to "
        f"{company} because {relevance}."
    )


def _join_natural(values: list[str], *, conjunction: str = "and") -> str:
    cleaned = [value.strip() for value in values if value and value.strip()]
    if not cleaned:
        return "software development"
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f" {conjunction} ".join(cleaned)
    return f"{', '.join(cleaned[:-1])}, {conjunction} {cleaned[-1]}"


def _clean_evidence_sentence(text: str) -> str:
    cleaned = " ".join((text or "").strip().strip("•-– ").split())
    if not cleaned:
        return ""
    at_match = re.match(r"^At\s+([^,]+),\s+(.+)$", cleaned)
    if at_match:
        entity = at_match.group(1).strip()
        body = _lowercase_initial(at_match.group(2).strip())
        if body.lower().startswith("i "):
            cleaned = f"In my work with {entity}, {body}"
        else:
            cleaned = f"In my work with {entity}, I {body}"
    if not cleaned.endswith(('.', '!', '?')):
        cleaned += "."
    return cleaned


def _lowercase_initial(text: str) -> str:
    if not text:
        return text
    return text[0].lower() + text[1:]


def _job_focus_phrase(job: RawJob) -> str:
    requirements = getattr(job, "requirements", None)
    terms: list[str] = []
    for attr in ("must_have_skills", "preferred_skills", "keywords"):
        values = getattr(requirements, attr, []) if requirements is not None else []
        terms.extend(str(value) for value in values if value)
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = term.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(term.strip())
        if len(deduped) >= 4:
            break
    if deduped:
        return ", ".join(deduped[:-1]) + f", and {deduped[-1]}" if len(deduped) > 1 else deduped[0]
    return "software development, testing, and practical problem solving"


def _role_label(job: RawJob) -> str:
    title = (job.title or "this role").strip()
    return title if title.lower().startswith("the ") else f"the {title} role"


def _select_evidence(
    job: RawJob,
    profile_data: dict[str, Any],
    max_points: int = 3,
) -> list[str]:
    """Select the strongest evidence points from profile for this job.

    Picks bullets with highest tag overlap with JD requirements.
    """
    from src.generation.resume_builder import (
        _job_query_embedding,
        _optional_generation_session,
        extract_jd_tags,
    )

    jd_tags = extract_jd_tags(job)
    db_session = _optional_generation_session()
    try:
        evidence = select_relevant_evidence(
            jd_tags,
            profile_data,
            max_total=max_points,
            query_text=f"{getattr(job, 'title', '')}\n{getattr(job, 'description', '') or ''}",
            db_session=db_session,
            query_embedding=_job_query_embedding(job),
        )
    finally:
        if db_session is not None:
            db_session.close()
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
