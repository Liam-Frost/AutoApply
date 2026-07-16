"""Single-file LaTeX rendering and PDF compilation helpers."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.documents._shared import (
    clean_cover_letter_location as _clean_cover_letter_location,
    clean_field as _clean_field,
    cover_letter_contact_lines as _cover_letter_contact_lines,
    cover_letter_date as _cover_letter_date,
    cover_letter_recipient_lines as _cover_letter_recipient_lines,
    normalise_divider_set as _normalise_divider_set,
    section_wants_divider as _section_wants_divider,
)
from src.documents.templates import TemplateManifest, default_manifest

logger = logging.getLogger("autoapply.documents.latex_engine")

PLACEHOLDER_RE = re.compile(r"\{\{([\w.]+)\}\}")

LATEX_ESCAPE_MAP = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(value: Any) -> str:
    """Escape user/generated text for safe insertion into LaTeX content.

    The escape map deliberately does not handle Markdown-ish inline
    markers (``**bold**`` / ``*italic*``) -- those are pre-processed
    by :func:`latex_inline` so the markup never reaches this escape
    pass. Calling ``latex_escape`` on raw text from the LLM is still
    safe -- a stray ``**`` becomes literal characters in the output
    rather than corrupting the document.
    """
    text = "" if value is None else str(value)
    return "".join(LATEX_ESCAPE_MAP.get(char, char) for char in text)


def latex_inline(value: Any) -> str:
    """Render text that may carry inline ``**bold**`` / ``*italic*``
    markers as a LaTeX-safe string, wrapping the marked spans in
    ``\\textbf{...}`` / ``\\textit{...}``.

    All non-marker characters still go through :func:`latex_escape` so
    backslashes / underscores / percent signs are escaped properly.
    Divider paragraphs (a line of dashes) come back as the LaTeX HR
    command from :func:`latex_horizontal_rule` -- callers that want a
    block divider should detect it earlier via
    :func:`src.generation.inline_format.is_divider_paragraph` and emit
    the rule themselves.
    """
    from src.generation.inline_format import parse_inline_markup  # noqa: PLC0415

    pieces: list[str] = []
    for run in parse_inline_markup(value):
        escaped = latex_escape(run.text)
        if not escaped:
            continue
        if run.bold and run.italic:
            pieces.append(rf"\textbf{{\textit{{{escaped}}}}}")
        elif run.bold:
            pieces.append(rf"\textbf{{{escaped}}}")
        elif run.italic:
            pieces.append(rf"\textit{{{escaped}}}")
        else:
            pieces.append(escaped)
    return "".join(pieces)


def latex_horizontal_rule() -> str:
    """LaTeX snippet for a thin horizontal divider rule spanning the
    text width. Used by the section-divider rendering path so the
    LaTeX and DOCX outputs match visually.
    """
    return r"\noindent\rule{\linewidth}{0.4pt}"


def build_resume_tex_from_ir(
    template_path: Path,
    document,
    output_path: Path,
    manifest: TemplateManifest | None = None,
) -> Path:
    """Build a single-file LaTeX resume from a validated ResumeDocument IR."""
    manifest = manifest or default_manifest("resume")
    template_text = template_path.read_text(encoding="utf-8")
    _ensure_required_markers(template_text, manifest)

    rendered = _substitute_placeholders(
        template_text,
        {
            **_resume_template_variables(document),
            "resume.sections": _render_resume_sections(document),
        },
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8", newline="\n")
    logger.info("Saved LaTeX resume to %s", output_path)
    return output_path


def build_cover_letter_tex_from_ir(
    template_path: Path,
    document,
    output_path: Path,
    manifest: TemplateManifest | None = None,
) -> Path:
    """Build a single-file LaTeX cover letter from a CoverLetterDocument IR."""
    manifest = manifest or default_manifest("cover_letter")
    template_text = template_path.read_text(encoding="utf-8")
    _ensure_required_markers(template_text, manifest)

    rendered = _substitute_placeholders(
        template_text,
        {
            **_cover_letter_template_variables(document),
            "cover_letter.body": _render_cover_letter_body(document),
        },
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8", newline="\n")
    logger.info("Saved LaTeX cover letter to %s", output_path)
    return output_path


def compile_latex_to_pdf(
    tex_path: Path,
    output_path: Path | None = None,
    *,
    timeout: int = 60,
) -> Path:
    """Compile a single .tex file to PDF using latexmk or pdflatex.

    The command is fixed by the application, shell escape is disabled, and all
    auxiliary files stay in a temporary working directory.
    """
    if not tex_path.exists():
        raise FileNotFoundError(f"LaTeX source file not found: {tex_path}")
    output_path = output_path or tex_path.with_suffix(".pdf")

    latexmk = shutil.which("latexmk")
    pdflatex = shutil.which("pdflatex")
    if not latexmk and not pdflatex:
        raise RuntimeError("LaTeX PDF compiler not found. Install latexmk or pdflatex.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="autoapply_latex_") as temp_dir:
        workdir = Path(temp_dir)
        work_tex = workdir / "main.tex"
        shutil.copy2(tex_path, work_tex)

        commands = _latex_commands(latexmk=latexmk, pdflatex=pdflatex)
        for command in commands:
            result = subprocess.run(
                command,
                cwd=workdir,
                capture_output=True,
                text=True,
                # pdflatex logs echo raw template bytes (e.g. a latin-1
                # middle dot in a contact line); strict utf-8 decoding
                # turns a successful compile into a spurious crash.
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            if result.returncode != 0:
                _copy_latex_log(workdir, output_path)
                raise RuntimeError(_latex_error_message(result))

        generated = workdir / "main.pdf"
        if not generated.exists():
            _copy_latex_log(workdir, output_path)
            raise RuntimeError("LaTeX compiler finished without producing a PDF.")

        shutil.copy2(generated, output_path)
        _copy_latex_log(workdir, output_path)
        logger.info("Compiled LaTeX PDF to %s", output_path)
        return output_path


def _latex_commands(*, latexmk: str | None, pdflatex: str | None) -> list[list[str]]:
    if latexmk:
        return [
            [
                latexmk,
                "-pdf",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-pdflatex=pdflatex -interaction=nonstopmode -halt-on-error -no-shell-escape %O %S",
                "main.tex",
            ]
        ]
    assert pdflatex is not None
    command = [
        pdflatex,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-no-shell-escape",
        "main.tex",
    ]
    return [command, command]


def _copy_latex_log(workdir: Path, output_path: Path) -> None:
    log_path = workdir / "main.log"
    if log_path.exists():
        shutil.copy2(log_path, output_path.with_suffix(".log"))


def _latex_error_message(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(part for part in [result.stderr, result.stdout] if part).strip()
    if len(output) > 2000:
        output = output[-2000:]
    return f"LaTeX compilation failed: {output or 'compiler returned a non-zero exit code.'}"


def _ensure_required_markers(template_text: str, manifest: TemplateManifest) -> None:
    missing = [
        marker for marker in manifest.blocks.values() if marker and marker not in template_text
    ]
    if missing:
        raise ValueError(f"LaTeX template is missing block marker(s): {', '.join(missing)}")


def _substitute_placeholders(template_text: str, variables: dict[str, str]) -> str:
    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))

    return PLACEHOLDER_RE.sub(replacer, template_text)


def _resume_template_variables(document) -> dict[str, str]:
    identity = document.header or {}
    return {
        "full_name": latex_escape(identity.get("full_name") or identity.get("name") or ""),
        "contact": latex_escape(
            _join_nonempty([identity.get("email"), identity.get("phone"), identity.get("location")])
        ),
        "links": latex_escape(
            _join_nonempty(
                [
                    identity.get("linkedin_url"),
                    identity.get("github_url"),
                    identity.get("portfolio_url"),
                ]
            )
        ),
    }


def _cover_letter_template_variables(document) -> dict[str, str]:
    applicant = document.applicant or {}
    recipient = document.recipient or {}
    name = applicant.get("name") or applicant.get("full_name") or ""
    contact = _latex_line_block(_cover_letter_contact_lines(applicant))
    recipient_block = _latex_line_block(_cover_letter_recipient_lines(recipient))
    return {
        "applicant.name": latex_escape(name),
        "applicant.contact": contact,
        "date": latex_escape(_cover_letter_date()),
        "recipient.block": recipient_block,
        "recipient.company": latex_escape(recipient.get("company") or ""),
        "signature": latex_escape(name),
    }


def _render_resume_sections(document) -> str:
    rendered: list[str] = []
    seen: set[str] = set()
    rendered_custom_titles: set[str] = set()
    dividers_after = _normalise_divider_set(getattr(document, "dividers_after", None))

    for section in _resolved_section_order(document):
        if section == "header" or section in seen:
            continue
        seen.add(section)
        if section.startswith("custom:"):
            rendered_custom_titles.add(section.split(":", 1)[1].strip().lower())
        elif section in ("custom", "custom_sections"):
            for custom in getattr(document, "custom_sections", []) or []:
                rendered_custom_titles.add(custom.title.strip().lower())
        section_text = _render_resume_section(section, document)
        if section_text:
            rendered.append(section_text)
            if _section_wants_divider(section, dividers_after):
                rendered.append(latex_horizontal_rule())

    # Append any CustomSection the user/profile carried that
    # section_order didn't explicitly place. Same fallback policy as
    # the DOCX renderer in docx_engine.py.
    for custom in getattr(document, "custom_sections", []) or []:
        if custom.title.strip().lower() in rendered_custom_titles:
            continue
        section_text = _render_custom_section(custom)
        if section_text:
            rendered.append(section_text)
            rendered_custom_titles.add(custom.title.strip().lower())
            token = f"custom:{custom.title}"
            if _section_wants_divider(token, dividers_after):
                rendered.append(latex_horizontal_rule())
    return "\n\n".join(rendered)


def _render_resume_section(section: str, document) -> str:
    if section == "education":
        return _render_education(document.education)
    if section == "skills":
        return _render_skills(document.skills)
    if section == "experience":
        return _render_items("Experience", document.experiences)
    if section == "projects":
        return _render_items("Projects", document.projects)
    if section in ("custom", "custom_sections"):
        chunks = [
            _render_custom_section(custom)
            for custom in getattr(document, "custom_sections", []) or []
        ]
        return "\n\n".join(chunk for chunk in chunks if chunk)
    if section.startswith("custom:"):
        title = section.split(":", 1)[1].strip().lower()
        for custom in getattr(document, "custom_sections", []) or []:
            if custom.title.strip().lower() == title:
                return _render_custom_section(custom)
        return ""
    return ""


def _render_custom_section(custom) -> str:
    """Render one CustomSection as a LaTeX block.

    Mirrors :func:`src.documents.docx_engine._render_ir_custom_section`
    but using the existing LaTeX line / bullet helpers, so a resume
    with a "VOLUNTEER EXPERIENCE" section renders consistently in both
    output formats. Skips entries with no usable fields so that empty
    profile data doesn't leave hanging headings.
    """
    entries = [
        entry
        for entry in getattr(custom, "entries", []) or []
        if (entry.title or entry.organization or entry.details or entry.bullets)
    ]
    if not entries:
        return ""
    lines = [_section_heading(custom.title)]
    for entry in entries:
        primary = entry.title.strip() or entry.organization.strip()
        dates = _format_date_range(entry.start_date, entry.end_date)
        if primary or dates:
            lines.append(_bold_line(latex_escape(primary), latex_escape(dates)))
        subtitle_parts: list[str] = []
        if entry.title and entry.organization and primary != entry.organization:
            subtitle_parts.append(entry.organization)
        if entry.location:
            subtitle_parts.append(entry.location)
        subtitle = _join_nonempty(subtitle_parts)
        if subtitle:
            lines.append(latex_escape(subtitle))
        if entry.details:
            lines.append(latex_inline(entry.details))
        for bullet in entry.bullets:
            text = str(bullet).strip()
            if text:
                lines.append(rf"\textbullet\ {latex_inline(text)}")
    return "\n\n".join(line for line in lines if line)


def _render_education(education: list[dict]) -> str:
    if not education:
        return ""
    lines = [_section_heading("Education")]
    for edu in education:
        institution = latex_escape(edu.get("institution", ""))
        dates = latex_escape(_format_date_range(edu.get("start_date", ""), edu.get("end_date", "")))
        lines.append(_bold_line(institution, dates))
        degree = " ".join(part for part in [edu.get("degree", ""), edu.get("field", "")] if part)
        gpa_text = (edu.get("gpa") or "")
        gpa_text = str(gpa_text).strip()
        if gpa_text.lower() in {"", "none", "null", "n/a", "na", "0", "0.0", "0.00"}:
            gpa = ""
        else:
            gpa = f"GPA: {gpa_text}"
        details = _join_nonempty([degree, edu.get("location"), gpa])
        if details:
            lines.append(latex_escape(details))
        courses = edu.get("relevant_courses", [])
        course_names = ", ".join(c.get("name", "") for c in courses if isinstance(c, dict))
        if course_names:
            lines.append(latex_escape(f"Relevant coursework: {course_names}"))
    return "\n\n".join(line for line in lines if line)


def _render_skills(skills: dict[str, list[str]]) -> str:
    rows = [(label, skills.get(key, [])) for key, label in _skill_label_map().items()]
    rows.extend(
        (key.replace("_", " ").title(), values)
        for key, values in skills.items()
        if key not in _skill_label_map()
    )
    rows = [(label, values) for label, values in rows if values]
    if not rows:
        return ""
    lines = [_section_heading("Skills")]
    for label, values in rows:
        lines.append(rf"\textbf{{{latex_escape(label)}:}} {latex_escape(', '.join(values))}")
    return "\n\n".join(lines)


def _render_items(title: str, items: list) -> str:
    if not items:
        return ""
    lines = [_section_heading(title)]
    for item in items:
        if title == "Experience":
            heading = item.title or item.organization or item.name
            dates = _format_date_range(item.start_date, item.end_date)
            lines.append(_bold_line(latex_escape(heading), latex_escape(dates)))
            subtitle = _join_nonempty([item.organization or item.name, item.location])
        else:
            dates = latex_escape(_format_date_range(item.start_date, item.end_date))
            lines.append(_bold_line(latex_escape(item.name), dates))
            subtitle = _join_nonempty([", ".join(item.tech_stack), item.meta])
        if subtitle:
            lines.append(latex_escape(subtitle))
        bullets = [latex_inline(bullet.text) for bullet in item.bullets if bullet.text]
        if bullets:
            lines.append(_itemize(bullets))
    return "\n\n".join(line for line in lines if line)


def _render_cover_letter_body(document) -> str:
    paragraphs = [
        latex_inline(paragraph.text) for paragraph in document.paragraphs if paragraph.text
    ]
    return "\n\n".join(paragraphs)


def _latex_line_block(lines: list[str]) -> str:
    return "\\\\\n".join(latex_escape(line) for line in lines if line)


def _section_heading(title: str) -> str:
    return rf"\section*{{{latex_escape(title)}}}"


def _bold_line(left: str, right: str = "") -> str:
    if left and right:
        return rf"\textbf{{{left}}} \hfill {right}"
    if left:
        return rf"\textbf{{{left}}}"
    return right


def _itemize(items: list[str]) -> str:
    body = "\n".join(rf"\item {item}" for item in items)
    return "\n".join([r"\begin{itemize}", body, r"\end{itemize}"])


def _resolved_section_order(document) -> list[str]:
    # See src/documents/docx_engine.py::_resolved_section_order. ``summary``
    # is filtered out unconditionally -- this system never renders a
    # Summary section.
    default_order = ["header", "education", "skills", "experience", "projects"]
    explicit = [
        section
        for section in document.section_order
        if section in default_order and section != "summary"
    ]
    return explicit or default_order


def _format_date_range(start: str, end: str) -> str:
    if start and end:
        return f"{start} -- {end}"
    return start or end or ""


def _join_nonempty(values: list) -> str:
    cleaned: list[str] = []
    for value in values:
        text = _clean_field(value)
        if not text:
            continue
        cleaned.append(text)
    return " | ".join(cleaned)


def _skill_label_map() -> dict[str, str]:
    return {
        "languages": "Languages",
        "frameworks": "Frameworks",
        "databases": "Databases",
        "tools": "Tools & DevOps",
        "domains": "Domains",
        "soft_skills": "Soft Skills",
        "certifications": "Certifications",
    }
