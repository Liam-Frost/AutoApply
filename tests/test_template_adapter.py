"""Phase 15.8: tests for the template adapter assistant."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.documents.template_adapter import (
    TemplateAdapterError,
    finalize_proposal,
    propose_manifest,
)
from src.documents.templates import TemplateManifest

_CONVENTIONAL_TEMPLATE = r"""
\documentclass{article}
\usepackage{geometry}
\newcommand{\resumeheadername}[1]{\textbf{#1}}
\newcommand{\headeremail}[1]{#1}
\newcommand{\summary}[1]{#1}
\newcommand{\experienceitem}[2]{\textbf{#1} -- #2}
\begin{document}
\resumeheadername{Name placeholder}
\headeremail{a@x.com}
\summary{A sample summary.}
\experienceitem{Initech}{2024}
{{resume.commands}}
\end{document}
"""

_UNUSUAL_TEMPLATE = r"""
\documentclass{moderncv}
\newcommand{\myveryspecialheading}[1]{#1}
\newcommand{\custompad}[2]{#1 :: #2}
\begin{document}
\myveryspecialheading{Hello}
\custompad{a}{b}
{{resume.commands}}
\end{document}
"""

_MISSING_PLACEHOLDER = r"""
\documentclass{article}
\newcommand{\resumeheadername}[1]{#1}
\begin{document}
\resumeheadername{x}
\end{document}
"""


# ---- propose_manifest -----------------------------------------------


def test_proposal_matches_conventional_commands(tmp_path: Path) -> None:
    tex = tmp_path / "conventional.tex"
    tex.write_text(_CONVENTIONAL_TEMPLATE, encoding="utf-8")

    proposal = propose_manifest(tex, template_id="conv-test", package_dir=tmp_path)

    mapped_commands = {m.command for m in proposal.manifest.latex.field_mappings}  # type: ignore[union-attr]
    assert "resumeheadername" in mapped_commands
    assert "headeremail" in mapped_commands
    assert "summary" in mapped_commands
    assert "experienceitem" in mapped_commands


def test_proposal_records_coverage_fraction(tmp_path: Path) -> None:
    tex = tmp_path / "conv.tex"
    tex.write_text(_CONVENTIONAL_TEMPLATE, encoding="utf-8")

    proposal = propose_manifest(tex, template_id="conv2", package_dir=tmp_path)
    # 4 of 4 mappable conventional commands matched.
    assert proposal.suggested_field_coverage > 0


def test_proposal_warns_on_unmatched_commands(tmp_path: Path) -> None:
    tex = tmp_path / "unusual.tex"
    tex.write_text(_UNUSUAL_TEMPLATE, encoding="utf-8")

    proposal = propose_manifest(tex, template_id="unusual", package_dir=tmp_path)

    warnings = [n.message for n in proposal.notes if n.severity == "warning"]
    assert any("myveryspecialheading" in m for m in warnings)
    assert any("custompad" in m for m in warnings)


def test_proposal_errors_when_placeholder_missing(tmp_path: Path) -> None:
    tex = tmp_path / "no-placeholder.tex"
    tex.write_text(_MISSING_PLACEHOLDER, encoding="utf-8")

    proposal = propose_manifest(tex, template_id="x", package_dir=tmp_path)
    errors = [n for n in proposal.notes if n.severity == "error"]
    assert errors and "{{resume.commands}}" in errors[0].message


def test_proposal_records_required_packages(tmp_path: Path) -> None:
    tex = tmp_path / "with-packages.tex"
    tex.write_text(_CONVENTIONAL_TEMPLATE, encoding="utf-8")

    proposal = propose_manifest(tex, template_id="pkgs", package_dir=tmp_path)
    assert "geometry" in proposal.manifest.latex.required_packages  # type: ignore[union-attr]


def test_proposal_detects_documentclass_as_info(tmp_path: Path) -> None:
    tex = tmp_path / "with-class.tex"
    tex.write_text(_UNUSUAL_TEMPLATE, encoding="utf-8")

    proposal = propose_manifest(tex, template_id="cls", package_dir=tmp_path)
    info = [n for n in proposal.notes if n.severity == "info"]
    assert any("moderncv" in n.message for n in info)


def test_proposal_handles_missing_file(tmp_path: Path) -> None:
    with pytest.raises(TemplateAdapterError):
        propose_manifest(tmp_path / "absent.tex", template_id="x")


def test_proposal_sample_render_ok_when_template_valid(tmp_path: Path) -> None:
    tex = tmp_path / "conv.tex"
    tex.write_text(_CONVENTIONAL_TEMPLATE, encoding="utf-8")

    proposal = propose_manifest(tex, template_id="render-ok", package_dir=tmp_path)
    # The render path runs (pure Python, no compile). With placeholders
    # present and mappings populated, it should produce a .tex.
    assert proposal.sample_render_ok is True


def test_proposal_sample_render_fails_without_placeholder(tmp_path: Path) -> None:
    tex = tmp_path / "no-placeholder.tex"
    tex.write_text(_MISSING_PLACEHOLDER, encoding="utf-8")

    proposal = propose_manifest(tex, template_id="render-fail", package_dir=tmp_path)
    assert proposal.sample_render_ok is False
    assert proposal.sample_render_error is not None


def test_proposal_skips_sample_render_when_no_package_dir(tmp_path: Path) -> None:
    """propose_manifest without package_dir should still produce a
    proposal -- it just skips the sample render step."""
    tex = tmp_path / "conv.tex"
    tex.write_text(_CONVENTIONAL_TEMPLATE, encoding="utf-8")
    proposal = propose_manifest(tex, template_id="no-render")
    assert proposal.manifest.latex is not None
    assert proposal.sample_render_ok is False  # default


# ---- finalize_proposal ----------------------------------------------


def test_finalize_writes_manifest_when_sample_render_ok(tmp_path: Path) -> None:
    tex = tmp_path / "conv.tex"
    tex.write_text(_CONVENTIONAL_TEMPLATE, encoding="utf-8")
    proposal = propose_manifest(tex, template_id="write", package_dir=tmp_path)
    assert proposal.sample_render_ok

    target = finalize_proposal(proposal, package_dir=tmp_path)
    assert target.exists()
    parsed = TemplateManifest.model_validate_json(target.read_text(encoding="utf-8"))
    assert parsed.template_id == "write"
    assert parsed.template_format == "latex"


def test_finalize_refuses_when_sample_render_failed(tmp_path: Path) -> None:
    tex = tmp_path / "no-placeholder.tex"
    tex.write_text(_MISSING_PLACEHOLDER, encoding="utf-8")
    proposal = propose_manifest(tex, template_id="x", package_dir=tmp_path)
    with pytest.raises(TemplateAdapterError, match="sample render"):
        finalize_proposal(proposal, package_dir=tmp_path)


def test_finalize_can_override_sample_render_check(tmp_path: Path) -> None:
    """We allow the operator to override the sample-render gate but
    we still refuse to finalize a proposal that has explicit errors
    (like the missing placeholder error)."""
    tex = tmp_path / "no-placeholder.tex"
    tex.write_text(_MISSING_PLACEHOLDER, encoding="utf-8")
    proposal = propose_manifest(tex, template_id="x", package_dir=tmp_path)
    with pytest.raises(TemplateAdapterError, match="unresolved errors"):
        finalize_proposal(
            proposal, package_dir=tmp_path, require_sample_render_ok=False
        )


def test_finalize_refuses_missing_assets(tmp_path: Path) -> None:
    tex = tmp_path / "conv.tex"
    tex.write_text(_CONVENTIONAL_TEMPLATE, encoding="utf-8")
    proposal = propose_manifest(tex, template_id="assets", package_dir=tmp_path)
    # Inject a missing asset into the manifest and confirm finalize blocks.
    proposal.manifest.latex.assets = ["missing.png"]  # type: ignore[union-attr]
    with pytest.raises(TemplateAdapterError, match="asset"):
        finalize_proposal(proposal, package_dir=tmp_path)


# ---- Defensive --------------------------------------------------------


def test_proposal_empty_template_still_returns_manifest(tmp_path: Path) -> None:
    tex = tmp_path / "empty.tex"
    tex.write_text("", encoding="utf-8")
    proposal = propose_manifest(tex, template_id="empty", package_dir=tmp_path)
    # No mappings, but the assistant still emits a manifest skeleton so
    # the user can paste field_mappings into it manually.
    assert proposal.manifest.template_id == "empty"
    assert proposal.manifest.latex is not None
    assert proposal.manifest.latex.field_mappings == []
