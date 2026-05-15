"""Phase 15.8: template adapter assistant.

A user uploads an arbitrary LaTeX resume template. Before the
materials router (Phase 15.5) can render IRs through it, we need a
matching :class:`TemplateManifest` with a ``latex`` block whose
``field_mappings`` cover the commands the template actually defines.

This module is the *machinery* used by:

* The CLI (``autoapply templates propose-manifest <tex>``).
* The Web UI's "Add LaTeX template" flow.
* The Phase 14.4 HITL gate -- proposing a manifest is a *bullet/
  story-bank mutation grade* irreversible event per the Phase 15.10
  policy, so the assistant emits a gate request and only the user's
  approval moves the manifest into the package.

We deliberately do NOT auto-persist a manifest. Per D024: "arbitrary
LaTeX may be imported, but it is not considered active until a
manifest exists and a sample compile passes."

The agent's role is to *propose* a manifest by scanning the
``.tex`` body. The proposal is deterministic when the template
follows the AutoApply naming conventions (``\\resumeheader`` /
``\\experienceitem`` / etc.); for unusual templates the proposal is
best-effort and the user fills in the gaps.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.documents.latex_manifest import validate_assets
from src.documents.latex_renderer import (
    ManifestRenderError,
    render_resume_tex,
)
from src.documents.templates import (
    LatexConfig,
    LatexFieldMapping,
    TemplateManifest,
)

logger = logging.getLogger(__name__)


# Conventional IR field -> command guesses. Used when the agent has
# no LLM available; deterministic scan matches command names against
# these patterns. A real template that does not follow conventions
# will still produce a proposal -- the LIST will simply be sparse and
# the user fills in the rest in the UI.
_CONVENTIONAL_MAPPINGS: dict[str, tuple[str, int]] = {
    # command name (without leading backslash) -> (ir_field, arity)
    "resumeheadername": ("header.name", 1),
    "headername": ("header.name", 1),
    "name": ("header.name", 1),
    "headeremail": ("header.email", 1),
    "email": ("header.email", 1),
    "headerphone": ("header.phone", 1),
    "phone": ("header.phone", 1),
    "summary": ("summary", 1),
    "professionalsummary": ("summary", 1),
    "targetrole": ("target_role", 1),
    "roleheader": ("target_role", 1),
    "skillsline": ("skills.must_have", 1),
    "mustskills": ("skills.must_have", 1),
    "preferredskills": ("skills.preferred", 1),
    "experiencename": ("experiences.0.name", 1),
    "experienceitem": ("experiences.0.name", 2),
    "projectname": ("projects.0.name", 1),
    "projectitem": ("projects.0.name", 2),
}


_DEFINE_RE = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|def)\\?(\w+)", re.MULTILINE
)
_USE_RE = re.compile(r"\\(\w+)(?:\s*\{|\s*\[)")
_DOCUMENTCLASS_RE = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{(\w+)\}")
_USEPACKAGE_RE = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}")


ProposalSeverity = Literal["info", "warning", "error"]


@dataclass
class ManifestProposalNote:
    severity: ProposalSeverity
    message: str


@dataclass
class ManifestProposal:
    """The artifact :func:`propose_manifest` emits.

    Persistence is gated: only :func:`finalize_proposal` (after the
    sample compile passes AND the user confirms) writes the manifest
    into the template package.
    """

    template_id: str
    manifest: TemplateManifest
    notes: list[ManifestProposalNote] = field(default_factory=list)
    detected_commands: list[str] = field(default_factory=list)
    declared_commands: list[str] = field(default_factory=list)
    suggested_field_coverage: float = 0.0  # 0..1
    sample_render_ok: bool = False
    sample_render_error: str | None = None


class TemplateAdapterError(Exception):
    """Raised on invalid input (missing template, traversal, etc.)."""


# ---- Public API -----------------------------------------------------


def propose_manifest(
    template_path: Path,
    *,
    template_id: str,
    package_dir: Path | None = None,
    compile_engine: Literal["pdflatex", "xelatex", "lualatex"] = "pdflatex",
    document_type: Literal["resume", "cover_letter"] = "resume",
) -> ManifestProposal:
    """Scan ``template_path`` and produce a :class:`ManifestProposal`.

    The proposal is non-destructive -- nothing is written to disk
    until :func:`finalize_proposal` is called with user confirmation.

    Detection heuristics:
      * Find every ``\\newcommand{\\foo}`` etc. (declared commands).
      * Find every ``\\foo{...}`` (used commands).
      * Map declared OR used commands to IR fields using
        :data:`_CONVENTIONAL_MAPPINGS`; unmapped commands get a
        ``warning`` note so the user knows the agent did not have a
        guess.
      * Record ``\\documentclass`` + ``\\usepackage`` lines in
        ``required_packages`` (advisory).
    """
    if not template_path.exists():
        raise TemplateAdapterError(f"template not found: {template_path}")
    text = template_path.read_text(encoding="utf-8")

    declared = set(_DEFINE_RE.findall(text))
    used = set(_USE_RE.findall(text))
    candidates = declared | used

    mappings: list[LatexFieldMapping] = []
    matched: set[str] = set()
    notes: list[ManifestProposalNote] = []

    for command in sorted(candidates):
        guess = _CONVENTIONAL_MAPPINGS.get(command.lower())
        if guess is None:
            continue
        ir_field, arity = guess
        mappings.append(
            LatexFieldMapping(
                ir_field=ir_field,
                command=command,
                arity=arity,  # type: ignore[arg-type]
                wrap_with_braces=True,
            )
        )
        matched.add(command.lower())

    unmatched = [c for c in sorted(candidates) if c.lower() not in matched]
    for cmd in unmatched:
        if cmd.startswith(("documentclass", "usepackage", "begin", "end")):
            continue
        if cmd in {"section", "subsection", "subsubsection", "paragraph", "item"}:
            continue
        notes.append(
            ManifestProposalNote(
                severity="warning",
                message=(
                    f"command \\{cmd} has no IR mapping guess; you will need "
                    f"to add one or confirm the template does not need it"
                ),
            )
        )

    # Required packages (advisory).
    required_packages: dict[str, str] = {}
    for match in _USEPACKAGE_RE.finditer(text):
        for pkg in match.group(1).split(","):
            pkg = pkg.strip()
            if pkg:
                required_packages[pkg] = ""
    doc_match = _DOCUMENTCLASS_RE.search(text)
    if doc_match:
        notes.append(
            ManifestProposalNote(
                severity="info",
                message=f"documentclass={doc_match.group(1)}",
            )
        )

    if not mappings:
        notes.append(
            ManifestProposalNote(
                severity="warning",
                message=(
                    "no commands matched any IR field; you may need to write "
                    "custom field_mappings or use the placeholder syntax "
                    "({{header.name}}) instead"
                ),
            )
        )

    coverage = len(matched) / max(1, len(candidates))

    has_placeholder = "{{resume.commands}}" in text
    if not has_placeholder and document_type == "resume":
        notes.append(
            ManifestProposalNote(
                severity="error",
                message=(
                    "template missing {{resume.commands}} placeholder -- the "
                    "manifest-adapter renderer cannot inject the command block "
                    "without it"
                ),
            )
        )

    manifest = TemplateManifest(
        template_id=template_id,
        document_type=document_type,
        template_format="latex",
        renderer="latex",
        latex=LatexConfig(
            compile_engine=compile_engine,
            field_mappings=mappings,
            required_packages=required_packages,
            assets=[],
            strict_field_coverage=False,  # opt-in only after user reviews
        ),
    )

    proposal = ManifestProposal(
        template_id=template_id,
        manifest=manifest,
        notes=notes,
        detected_commands=sorted(used),
        declared_commands=sorted(declared),
        suggested_field_coverage=round(coverage, 3),
    )

    if package_dir is not None and document_type == "resume":
        _try_sample_render(template_path, manifest, package_dir, proposal)

    return proposal


def finalize_proposal(
    proposal: ManifestProposal,
    *,
    package_dir: Path,
    manifest_filename: str = "manifest.json",
    require_sample_render_ok: bool = True,
) -> Path:
    """Persist the proposal's manifest to disk.

    By convention this is called *only* after:
      1. The Phase 15.10 HITL gate row was approved by the user, AND
      2. ``proposal.sample_render_ok`` is True (the renderer compiled
         a sample IR through this manifest without raising).

    Caller is responsible for the gate flow -- this function only
    enforces ``require_sample_render_ok``. Returns the path to the
    written manifest.
    """
    if require_sample_render_ok and not proposal.sample_render_ok:
        raise TemplateAdapterError(
            "manifest cannot be finalized: sample render did not succeed "
            f"({proposal.sample_render_error!r}). Set "
            "require_sample_render_ok=False to override (not recommended)."
        )
    if any(note.severity == "error" for note in proposal.notes):
        raise TemplateAdapterError(
            "manifest cannot be finalized: proposal has unresolved errors "
            f"({[n.message for n in proposal.notes if n.severity == 'error']})."
        )
    # Asset validation also gates persistence -- a manifest declaring
    # an asset that does not exist would break the renderer at runtime.
    asset_errors = validate_assets(proposal.manifest, package_dir)
    if asset_errors:
        raise TemplateAdapterError(
            f"manifest cannot be finalized: asset validation failed: {asset_errors[:5]}"
        )

    target = package_dir / manifest_filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        proposal.manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    return target


# ---- Sample render --------------------------------------------------


def _sample_resume_ir() -> Any:
    """Build a minimal ResumeDocument the renderer can drive. Kept
    inside the assistant so the proposal flow does not depend on
    the caller having a real applicant profile."""
    from src.generation.ir import ResumeBullet, ResumeDocument, ResumeItem

    return ResumeDocument(
        target_role="Sample Engineer",
        company="Sample Co",
        header={"name": "Sample Candidate", "email": "sample@example.com"},
        summary=["Sample summary for adapter validation."],
        skills={"must_have": ["python"]},
        experiences=[
            ResumeItem(
                source_id="sample-1",
                source_type="experience",
                name="Sample Role",
                bullets=[
                    ResumeBullet(
                        text="Sample bullet covering an evidence claim.",
                        source_id="sample-1",
                        source_type="experience",
                        source_entity="Sample Co",
                    )
                ],
            )
        ],
    )


def _try_sample_render(
    template_path: Path,
    manifest: TemplateManifest,
    package_dir: Path,
    proposal: ManifestProposal,
) -> None:
    """Attempt :func:`render_resume_tex` against a sample IR. Compile
    is intentionally NOT performed here -- compile requires a binary
    + several seconds and we want propose_manifest to stay snappy.
    :func:`finalize_proposal` is where the operator's flow runs the
    real compile."""
    import tempfile

    try:
        with tempfile.TemporaryDirectory(prefix="autoapply_sample_") as tmp:
            output = Path(tmp) / "sample.tex"
            render_resume_tex(template_path, _sample_resume_ir(), output, manifest)
            proposal.sample_render_ok = True
    except ManifestRenderError as exc:
        proposal.sample_render_ok = False
        proposal.sample_render_error = str(exc)
        proposal.notes.append(
            ManifestProposalNote(severity="warning", message=f"sample render failed: {exc}")
        )
    except Exception as exc:  # noqa: BLE001
        proposal.sample_render_ok = False
        proposal.sample_render_error = repr(exc)
        proposal.notes.append(
            ManifestProposalNote(
                severity="warning",
                message=f"sample render raised unexpectedly: {exc!r}",
            )
        )


__all__ = [
    "ManifestProposal",
    "ManifestProposalNote",
    "ProposalSeverity",
    "TemplateAdapterError",
    "finalize_proposal",
    "propose_manifest",
]
