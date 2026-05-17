"""Phase 15.5: materials router.

Routes a ``materials.generate`` request to the right rendering path:

* ``patch_existing`` -- the user picked a :class:`SourceResume` row
  whose ``editable`` is True (docx or latex). For docx we call the
  Phase 15.2 patcher; if it raises :class:`PatchFallback`, we route
  to ``generate_from_template`` per D024. For latex sources we leave
  the patcher off (Phase 15 ships docx patching; latex source patching
  is intentionally deferred -- the Phase 15.4 manifest renderer
  already covers "regenerate from a clean LaTeX template").
* ``generate_from_template`` -- the user picked a template package
  (docx or latex). Existing :mod:`src.generation.resume_builder`
  handles docx; the Phase 15.4 manifest-adapter renderer handles
  latex.

Every output binds to ``job_snapshot_id`` + ``source_id`` (when set)
+ ``template_package_id`` + ``profile_version`` + ``trace_id`` via
:class:`MaterialsOutcome.bindings`. Phase 17's review queue + the
existing application audit trail join through these IDs back to the
exact JD content and the exact source / template used.

The router is *the* entry point Phase 14.6's ``materials.generate``
Celery task should call once Phase 17 wires it. Today the task body
is a stub; this module is independently usable from the CLI and the
Web UI.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from src.core.config import PROJECT_ROOT
from src.documents.latex_renderer import (
    ManifestRenderError,
    render_and_compile,
)
from src.documents.templates import TemplateManifest, TemplatePackage
from src.generation.docx_patch import PatchFallback, PatchReport, patch_resume_docx
from src.generation.ir import ResumeDocument
from src.tasks.context import current_tenant_id

logger = logging.getLogger(__name__)


# ---- Public types ----------------------------------------------------


@dataclass(frozen=True)
class MaterialsBindings:
    """Provenance bindings persisted on the generated artifact.

    These are the IDs Phase 17's review queue and the trace viewer
    use to walk from a generated PDF back to the JD snapshot and the
    profile evidence the LLM was looking at when it produced the IR.
    """

    job_snapshot_id: uuid.UUID | None = None
    source_resume_id: uuid.UUID | None = None
    template_package_id: str | None = None
    profile_version: str | None = None
    trace_id: str | None = None
    tenant_id: str = "default"

    def to_dict(self) -> dict[str, str | None]:
        return {
            "job_snapshot_id": str(self.job_snapshot_id) if self.job_snapshot_id else None,
            "source_resume_id": (
                str(self.source_resume_id) if self.source_resume_id else None
            ),
            "template_package_id": self.template_package_id,
            "profile_version": self.profile_version,
            "trace_id": self.trace_id,
            "tenant_id": self.tenant_id,
        }


GenerationMode = Literal["patch_existing", "generate_from_template"]
RouteDecision = Literal[
    "patch_docx_ok",
    "patch_docx_fallback",
    "generate_docx",
    "generate_latex",
    "unsupported",
]


@dataclass
class MaterialsOutcome:
    """Returned from :func:`generate_materials`."""

    mode: GenerationMode
    decision: RouteDecision
    output_paths: list[Path] = field(default_factory=list)
    bindings: MaterialsBindings = field(default_factory=MaterialsBindings)
    warnings: list[str] = field(default_factory=list)
    patch_report: PatchReport | None = None
    failure: str | None = None
    finished_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class MaterialsRouterError(Exception):
    """Raised on programmer error (missing required argument, etc.)."""


# ---- Source / template adapter facade -------------------------------


@dataclass(frozen=True)
class SourceResumeView:
    """Minimal view of a :class:`src.core.models.SourceResume` row the
    router needs. Keeps the router decoupled from a live DB session
    so it can be unit-tested without Postgres."""

    id: uuid.UUID
    source_type: Literal["docx", "latex", "pdf"]
    editable: bool
    absolute_path: Path


# ---- Entry point -----------------------------------------------------


def generate_materials(
    *,
    document: ResumeDocument,
    mode: GenerationMode,
    output_dir: Path,
    source: SourceResumeView | None = None,
    template_package: TemplatePackage | None = None,
    bindings: MaterialsBindings | None = None,
) -> MaterialsOutcome:
    """Dispatch ``document`` to the right renderer.

    Required arguments per mode:
      * ``patch_existing``: ``source`` MUST be set and ``source.editable``
        MUST be True; else the call routes through to template
        generation with a warning.
      * ``generate_from_template``: ``template_package`` MUST be set.

    The function does not commit anything to the DB. Phase 17's
    plan_run task wraps it inside an :class:`AutoApplyTask` body
    that owns the audit row.
    """
    bindings = bindings or MaterialsBindings(tenant_id=current_tenant_id())
    output_dir.mkdir(parents=True, exist_ok=True)

    if mode == "patch_existing":
        return _route_patch_existing(
            document, source, template_package, output_dir, bindings
        )
    if mode == "generate_from_template":
        return _route_generate_from_template(
            document, template_package, output_dir, bindings
        )
    raise MaterialsRouterError(f"unknown mode: {mode!r}")


# ---- patch_existing dispatch ----------------------------------------


def _route_patch_existing(
    document: ResumeDocument,
    source: SourceResumeView | None,
    template_package: TemplatePackage | None,
    output_dir: Path,
    bindings: MaterialsBindings,
) -> MaterialsOutcome:
    if source is None:
        raise MaterialsRouterError("patch_existing requires source=...")

    if not source.editable:
        # PDF (or any source flagged as not editable) -- the router
        # must NOT silently try to patch. Per D024 we fall back to
        # generate_from_template if the caller also provided one.
        if template_package is None:
            return MaterialsOutcome(
                mode="patch_existing",
                decision="unsupported",
                bindings=_with_source(bindings, source),
                failure=(
                    f"source resume {source.id} is not editable "
                    f"(source_type={source.source_type}); pass template_package "
                    f"to fall back to generate_from_template"
                ),
            )
        outcome = _route_generate_from_template(
            document, template_package, output_dir, _with_source(bindings, source)
        )
        outcome.warnings.append(
            f"source {source.id} is {source.source_type}; routed to "
            f"generate_from_template per D024"
        )
        return outcome

    if source.source_type == "docx":
        return _patch_docx(document, source, template_package, output_dir, bindings)

    if source.source_type == "latex":
        # Latex source patching is deferred (Phase 15 ships docx patch
        # only); regenerate from the LaTeX template instead, which
        # produces a clean rendering of the same IR.
        if template_package is None:
            return MaterialsOutcome(
                mode="patch_existing",
                decision="unsupported",
                bindings=_with_source(bindings, source),
                failure=(
                    "latex source patching is not implemented in Phase 15; "
                    "pass template_package to regenerate from a clean LaTeX template"
                ),
            )
        outcome = _route_generate_from_template(
            document, template_package, output_dir, _with_source(bindings, source)
        )
        outcome.warnings.append(
            f"source {source.id} is latex; rendered fresh via template_package"
        )
        return outcome

    return MaterialsOutcome(
        mode="patch_existing",
        decision="unsupported",
        bindings=_with_source(bindings, source),
        failure=f"unsupported source_type {source.source_type!r}",
    )


def _patch_docx(
    document: ResumeDocument,
    source: SourceResumeView,
    template_package: TemplatePackage | None,
    output_dir: Path,
    bindings: MaterialsBindings,
) -> MaterialsOutcome:
    output_path = output_dir / "patched_resume.docx"
    try:
        report = patch_resume_docx(
            source.absolute_path, document, output_path=output_path
        )
    except PatchFallback as exc:
        logger.info("docx patch fell back: %s", exc)
        if template_package is None:
            return MaterialsOutcome(
                mode="patch_existing",
                decision="patch_docx_fallback",
                bindings=_with_source(bindings, source),
                failure=str(exc),
                warnings=["docx patch failed and no template_package was provided"],
            )
        # Fallback to template generation (per D024).
        fallback_outcome = _route_generate_from_template(
            document, template_package, output_dir, _with_source(bindings, source)
        )
        fallback_outcome.mode = "patch_existing"
        fallback_outcome.decision = "patch_docx_fallback"
        fallback_outcome.warnings.append(f"docx patch failed -> template: {exc}")
        return fallback_outcome

    return MaterialsOutcome(
        mode="patch_existing",
        decision="patch_docx_ok",
        output_paths=[report.output_path],
        bindings=_with_source(bindings, source),
        patch_report=report,
    )


# ---- generate_from_template dispatch --------------------------------


def _route_generate_from_template(
    document: ResumeDocument,
    template_package: TemplatePackage | None,
    output_dir: Path,
    bindings: MaterialsBindings,
) -> MaterialsOutcome:
    if template_package is None:
        raise MaterialsRouterError(
            "generate_from_template requires template_package=..."
        )

    manifest: TemplateManifest = template_package.manifest
    bindings = _with_template(bindings, template_package)

    if manifest.template_format == "latex":
        return _generate_latex(document, template_package, output_dir, bindings)
    if manifest.template_format == "docx":
        return _generate_docx(document, template_package, output_dir, bindings)
    return MaterialsOutcome(
        mode="generate_from_template",
        decision="unsupported",
        bindings=bindings,
        failure=f"unsupported template_format {manifest.template_format!r}",
    )


def _generate_latex(
    document: ResumeDocument,
    template_package: TemplatePackage,
    output_dir: Path,
    bindings: MaterialsBindings,
) -> MaterialsOutcome:
    manifest = template_package.manifest
    tex_path = output_dir / "resume.tex"
    pdf_path = output_dir / "resume.pdf"

    if manifest.latex is None:
        # Codex P2 fix: a LaTeX package created by the legacy upload
        # path (``create_latex_template_package``) has
        # ``template_format='latex'`` but no Phase 15.3 ``latex``
        # block. Fall back to the placeholder-based renderer in
        # :mod:`src.documents.latex_engine` rather than rejecting it
        # as "unsupported" -- that renderer's existing
        # ``{{resume.sections}}`` template path still works.
        try:
            tex, pdf = _render_placeholder_latex(
                template_package, document, tex_path, pdf_path
            )
        except ManifestRenderError as exc:
            return MaterialsOutcome(
                mode="generate_from_template",
                decision="generate_latex",
                bindings=bindings,
                failure=f"placeholder latex render/compile failed: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return MaterialsOutcome(
                mode="generate_from_template",
                decision="generate_latex",
                bindings=bindings,
                failure=f"placeholder latex render/compile failed: {exc!r}",
            )
        return MaterialsOutcome(
            mode="generate_from_template",
            decision="generate_latex",
            output_paths=[tex, pdf],
            bindings=bindings,
        )

    try:
        tex, pdf = render_and_compile(
            template_package.template_path,
            document,
            manifest=manifest,
            package_dir=template_package.directory,
            tex_output=tex_path,
            pdf_output=pdf_path,
        )
    except ManifestRenderError as exc:
        return MaterialsOutcome(
            mode="generate_from_template",
            decision="generate_latex",
            bindings=bindings,
            failure=f"latex render/compile failed: {exc}",
        )

    return MaterialsOutcome(
        mode="generate_from_template",
        decision="generate_latex",
        output_paths=[tex, pdf],
        bindings=bindings,
    )


def _render_placeholder_latex(
    template_package: TemplatePackage,
    document: ResumeDocument,
    tex_output: Path,
    pdf_output: Path,
) -> tuple[Path, Path]:
    """Codex P2 fallback path for legacy latex templates without a
    Phase 15.3 ``latex`` manifest block. Delegates to the original
    ``latex_engine`` helpers."""
    from src.documents.latex_engine import (
        build_resume_tex_from_ir,
        compile_latex_to_pdf,
    )

    tex = build_resume_tex_from_ir(
        template_package.template_path,
        document,
        tex_output,
        manifest=template_package.manifest,
    )
    pdf = compile_latex_to_pdf(tex, pdf_output)
    return tex, pdf


def _generate_docx(
    document: ResumeDocument,
    template_package: TemplatePackage,
    output_dir: Path,
    bindings: MaterialsBindings,
) -> MaterialsOutcome:
    """Delegates to the existing :mod:`src.generation.resume_builder`
    DOCX rendering pipeline. We do not import it eagerly because it
    pulls heavy dependencies (python-docx + the validator chain); a
    test that only exercises the LaTeX router should not have to
    fault those in."""
    from src.generation.resume_builder import build_resume_document_artifacts

    try:
        artifacts = build_resume_document_artifacts(
            document,
            template_path=template_package.template_path,
            output_dir=output_dir,
            template_id=template_package.template_id,
        )
    except Exception as exc:  # noqa: BLE001 -- surface any renderer fault
        logger.exception("docx template render failed")
        return MaterialsOutcome(
            mode="generate_from_template",
            decision="generate_docx",
            bindings=bindings,
            failure=f"docx render failed: {exc}",
        )

    paths: list[Path] = []
    for key in ("docx_path", "pdf_path", "preview_path"):
        path = artifacts.get(key) if isinstance(artifacts, dict) else None
        if path:
            paths.append(Path(path))

    return MaterialsOutcome(
        mode="generate_from_template",
        decision="generate_docx",
        output_paths=paths,
        bindings=bindings,
    )


# ---- Helpers --------------------------------------------------------


def _with_source(bindings: MaterialsBindings, source: SourceResumeView) -> MaterialsBindings:
    return MaterialsBindings(
        job_snapshot_id=bindings.job_snapshot_id,
        source_resume_id=source.id,
        template_package_id=bindings.template_package_id,
        profile_version=bindings.profile_version,
        trace_id=bindings.trace_id,
        tenant_id=bindings.tenant_id,
    )


def _with_template(
    bindings: MaterialsBindings, template_package: TemplatePackage
) -> MaterialsBindings:
    return MaterialsBindings(
        job_snapshot_id=bindings.job_snapshot_id,
        source_resume_id=bindings.source_resume_id,
        template_package_id=template_package.template_id,
        profile_version=bindings.profile_version,
        trace_id=bindings.trace_id,
        tenant_id=bindings.tenant_id,
    )


def source_resume_view_from_row(row: Any) -> SourceResumeView:
    """Build a :class:`SourceResumeView` from a live ORM row. Kept as
    a helper so the router stays decoupled from SQLAlchemy."""
    rel = (row.storage_path or "").replace("\\", "/").lstrip("/")
    return SourceResumeView(
        id=row.id,
        source_type=row.source_type,
        editable=bool(row.editable),
        absolute_path=PROJECT_ROOT / rel,
    )


__all__ = [
    "GenerationMode",
    "MaterialsBindings",
    "MaterialsOutcome",
    "MaterialsRouterError",
    "RouteDecision",
    "SourceResumeView",
    "generate_materials",
    "source_resume_view_from_row",
]
