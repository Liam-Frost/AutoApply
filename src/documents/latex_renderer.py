"""Phase 15.4: manifest-adapter LaTeX renderer.

The existing :mod:`src.documents.latex_engine` uses placeholder
substitution -- ``{{resume.sections}}`` etc. -- with the section
rendering logic baked into Python. This works for AutoApply's
shipped templates but does not extend to *arbitrary* user-uploaded
LaTeX, which uses custom commands like ``\\experienceitem{...}{...}``
that the engine cannot know about.

This module adds the manifest-adapter path:

* The template declares a single ``{{resume.commands}}`` block where
  the rendered commands land (the rest of the template is whatever
  the user wrote -- packages, geometry, custom commands).
* The manifest's ``latex.field_mappings`` lists every IR field that
  feeds a LaTeX command (Phase 15.3).
* :func:`render_resume_tex` iterates the mappings, builds the
  command block via :func:`src.documents.latex_manifest.render_command`,
  substitutes it into the template, and writes the ``.tex``.

Compilation: :func:`compile_via_manifest` selects the engine
declared in the manifest (``pdflatex`` / ``xelatex`` / ``lualatex``)
and copies any declared assets next to the rendered source before
compiling. Falls through to :func:`src.documents.latex_engine.compile_latex_to_pdf`
when the manifest does not pin an engine, so callers that do not
care about the engine keep working.

Per D024: the renderer is deterministic. The agent only produces
the resume IR; it never freely rewrites the final ``.tex``.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.documents.latex_engine import (
    _resume_template_variables,
    _substitute_placeholders,
    compile_latex_to_pdf,
)
from src.documents.latex_manifest import (
    render_command,
    validate_assets,
    validate_field_coverage,
)
from src.documents.templates import TemplateManifest
from src.generation.ir import ResumeDocument

logger = logging.getLogger(__name__)


# Placeholder the manifest-adapter template MUST contain.
_COMMANDS_PLACEHOLDER = "{{resume.commands}}"


class ManifestRenderError(Exception):  # noqa: N818 -- "Error" without the Render prefix is misleading
    """Raised when the template, manifest, or IR cannot be rendered."""


def render_resume_tex(
    template_path: Path,
    document: ResumeDocument,
    output_path: Path,
    manifest: TemplateManifest,
) -> Path:
    """Render ``document`` into ``output_path`` using the manifest's
    ``latex.field_mappings`` for the command block.

    The template at ``template_path`` MUST contain
    ``{{resume.commands}}`` exactly once. Header / standard
    variables (``{{header.name}}``, etc.) are filled in via the
    existing placeholder mechanism so a manifest-adapter template can
    mix free-form prelude (packages, geometry) with the generated
    command block.
    """
    if manifest.latex is None:
        raise ManifestRenderError(
            "manifest has no `latex` config; use build_resume_tex_from_ir for "
            "placeholder-only templates"
        )
    if not template_path.exists():
        raise ManifestRenderError(f"template file not found: {template_path}")

    template_text = template_path.read_text(encoding="utf-8")
    if _COMMANDS_PLACEHOLDER not in template_text:
        raise ManifestRenderError(
            f"manifest-adapter template must contain {_COMMANDS_PLACEHOLDER!r}"
        )

    # Strict field coverage check (opt-in; reports missing mappings).
    if manifest.latex.strict_field_coverage:
        ir_fields = _flatten_ir_fields(document)
        missing = validate_field_coverage(manifest, ir_fields)
        if missing:
            raise ManifestRenderError(
                f"manifest is strict but {len(missing)} IR field(s) lack mappings: "
                f"{missing[:10]}"
            )

    command_lines = []
    for mapping in manifest.latex.field_mappings:
        line = render_command(document, mapping, config=manifest.latex)
        if line:
            command_lines.append(line)
    command_block = "\n".join(command_lines)

    # The header-style placeholders ({{header.name}}, etc.) are still
    # honoured so an existing template can use either approach.
    variables = {**_resume_template_variables(document), "resume.commands": command_block}
    rendered = _substitute_placeholders(template_text, variables)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8", newline="\n")
    logger.info("Rendered manifest-adapter LaTeX resume to %s", output_path)
    return output_path


def compile_via_manifest(
    tex_path: Path,
    output_path: Path | None = None,
    *,
    manifest: TemplateManifest,
    package_dir: Path,
    timeout: int = 60,
) -> Path:
    """Compile ``tex_path`` to PDF using the engine + assets declared in
    the manifest.

    Falls through to :func:`compile_latex_to_pdf` when the manifest
    has no LaTeX block (placeholder templates) so existing callers do
    not need to branch on manifest type.
    """
    if manifest.latex is None:
        return compile_latex_to_pdf(tex_path, output_path, timeout=timeout)

    if not tex_path.exists():
        raise ManifestRenderError(f"LaTeX source not found: {tex_path}")

    asset_errors = validate_assets(manifest, package_dir)
    if asset_errors:
        raise ManifestRenderError(
            f"manifest assets failed validation: {asset_errors[:5]}"
        )

    engine = manifest.latex.compile_engine
    engine_bin = shutil.which(engine)
    if not engine_bin:
        # Fall back to the engine-agnostic path -- emits a clearer
        # error than silently using the wrong tool.
        raise ManifestRenderError(
            f"manifest pinned compile_engine={engine!r} but the binary is not on PATH"
        )

    output_path = output_path or tex_path.with_suffix(".pdf")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="autoapply_latex_manifest_") as temp_dir:
        workdir = Path(temp_dir)
        work_tex = workdir / "main.tex"
        shutil.copy2(tex_path, work_tex)
        # Copy assets next to the rendered .tex.
        for asset_rel in manifest.latex.assets:
            cleaned = (asset_rel or "").strip().replace("\\", "/").lstrip("/")
            src = (package_dir / cleaned).resolve()
            if not src.exists():
                continue  # validation already flagged this; soft-fail compile
            dst = workdir / src.name
            shutil.copy2(src, dst)

        result = subprocess.run(
            [engine_bin, "-interaction=nonstopmode", "main.tex"],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            tail = (result.stdout or "")[-2000:]
            raise ManifestRenderError(
                f"{engine} failed with exit {result.returncode}: {tail}"
            )
        produced = workdir / "main.pdf"
        if not produced.exists():
            raise ManifestRenderError(f"{engine} did not produce main.pdf")
        shutil.copy2(produced, output_path)

    return output_path


def render_and_compile(
    template_path: Path,
    document: ResumeDocument,
    *,
    manifest: TemplateManifest,
    package_dir: Path,
    tex_output: Path,
    pdf_output: Path | None = None,
    timeout: int = 60,
) -> tuple[Path, Path]:
    """Orchestrate render + compile; returns ``(tex_path, pdf_path)``.

    Phase 15.5's materials router calls this when the resolved
    template is a manifest-adapter LaTeX package."""
    render_resume_tex(template_path, document, tex_output, manifest)
    pdf_path = compile_via_manifest(
        tex_output,
        pdf_output,
        manifest=manifest,
        package_dir=package_dir,
        timeout=timeout,
    )
    return tex_output, pdf_path


# ---- Internal helpers ------------------------------------------------


def _flatten_ir_fields(document: Any) -> set[str]:
    """Best-effort flatten -- enumerate top-level Pydantic fields plus
    a few standard nested paths so :func:`validate_field_coverage`
    knows what to compare against."""
    fields: set[str] = set()
    try:
        # Use the class-level model_fields (Pydantic V2.11+ deprecated
        # instance access).
        for name in type(document).model_fields:  # type: ignore[attr-defined]
            fields.add(name)
    except Exception:  # noqa: BLE001
        pass
    # Header is dict-shaped in our IR; surface its keys.
    header = getattr(document, "header", None) or {}
    if isinstance(header, dict):
        for key in header:
            fields.add(f"header.{key}")
    # Experiences / projects -- common indexed fields.
    for collection_name in ("experiences", "projects", "education"):
        coll = getattr(document, collection_name, None) or []
        for idx, _ in enumerate(coll):
            fields.add(f"{collection_name}.{idx}")
    return fields


__all__ = [
    "ManifestRenderError",
    "compile_via_manifest",
    "render_and_compile",
    "render_resume_tex",
]
