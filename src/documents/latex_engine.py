"""Single-file LaTeX rendering and PDF compilation helpers."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

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
    """Escape user/generated text for safe insertion into LaTeX content."""
    text = "" if value is None else str(value)
    return "".join(LATEX_ESCAPE_MAP.get(char, char) for char in text)


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
    contact = _join_nonempty([applicant.get("email"), applicant.get("phone")])
    return {
        "applicant.name": latex_escape(name),
        "applicant.contact": latex_escape(contact),
        "recipient.company": latex_escape(recipient.get("company") or ""),
        "signature": latex_escape(name),
    }


def _render_resume_sections(document) -> str:
    rendered = []
    seen = set()
    for section in _resolved_section_order(document):
        if section == "header" or section in seen:
            continue
        seen.add(section)
        section_text = _render_resume_section(section, document)
        if section_text:
            rendered.append(section_text)
    return "\n\n".join(rendered)


def _render_resume_section(section: str, document) -> str:
    if section == "summary":
        return _render_summary(document.summary)
    if section == "education":
        return _render_education(document.education)
    if section == "skills":
        return _render_skills(document.skills)
    if section == "experience":
        return _render_items("Experience", document.experiences)
    if section == "projects":
        return _render_items("Projects", document.projects)
    return ""


def _render_summary(summary: list[str]) -> str:
    lines = [latex_escape(line) for line in summary if line]
    if not lines:
        return ""
    return "\n\n".join([_section_heading("Summary"), *lines])


def _render_education(education: list[dict]) -> str:
    if not education:
        return ""
    lines = [_section_heading("Education")]
    for edu in education:
        institution = latex_escape(edu.get("institution", ""))
        dates = latex_escape(_format_date_range(edu.get("start_date", ""), edu.get("end_date", "")))
        lines.append(_bold_line(institution, dates))
        degree = " ".join(part for part in [edu.get("degree", ""), edu.get("field", "")] if part)
        gpa = f"GPA: {edu.get('gpa')}" if edu.get("gpa") else ""
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
        bullets = [latex_escape(bullet.text) for bullet in item.bullets if bullet.text]
        if bullets:
            lines.append(_itemize(bullets))
    return "\n\n".join(line for line in lines if line)


def _render_cover_letter_body(document) -> str:
    paragraphs = [
        latex_escape(paragraph.text) for paragraph in document.paragraphs if paragraph.text
    ]
    return "\n\n".join(paragraphs)


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
    default_order = ["header", "summary", "education", "skills", "experience", "projects"]
    order = [section for section in document.section_order if section in default_order]
    order.extend(section for section in default_order if section not in order)
    return order


def _format_date_range(start: str, end: str) -> str:
    if start and end:
        return f"{start} -- {end}"
    return start or end or ""


def _join_nonempty(values: list) -> str:
    return " | ".join(str(value) for value in values if value)


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
