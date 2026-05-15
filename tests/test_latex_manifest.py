"""Phase 15.3: tests for the LaTeX manifest contract helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from src.documents.latex_manifest import (
    escape_latex,
    render_command,
    resolve_field,
    validate_assets,
    validate_field_coverage,
)
from src.documents.templates import (
    LatexConfig,
    LatexFieldMapping,
    TemplateManifest,
)

# ---- escape_latex ----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("hello", "hello"),
        ("a & b", r"a \& b"),
        ("100%", r"100\%"),
        ("a_b", r"a\_b"),
        ("$cost", r"\$cost"),
        ("{x}", r"\{x\}"),
        ("a~b", r"a\textasciitilde{}b"),
        ("a^b", r"a\textasciicircum{}b"),
        (r"a\b", r"a\textbackslash{}b"),
        ("", ""),
        (None, ""),
    ],
)
def test_escape_known_specials(raw: object, expected: str) -> None:
    assert escape_latex(raw) == expected


def test_escape_allowlist_passes_chars_through() -> None:
    # A template that prints percentages with \pct{N} can opt out of
    # escaping ``%`` because it owns the escaping for that token.
    assert escape_latex("100%", allowlist=["%"]) == "100%"
    assert escape_latex("a & b", allowlist=["&"]) == "a & b"


def test_escape_lists_become_newline_joined() -> None:
    assert escape_latex(["a", "b & c"]) == r"a" + "\n" + r"b \& c"


def test_escape_dicts_become_keyvalue_lines() -> None:
    out = escape_latex({"name": "Alice", "title": "Eng & Sci"})
    assert "name: Alice" in out
    assert r"title: Eng \& Sci" in out


# ---- resolve_field ---------------------------------------------------


class _Header(BaseModel):
    name: str
    email: str


class _Item(BaseModel):
    name: str


class _IR(BaseModel):
    target_role: str = ""
    header: _Header
    summary: list[str] = []
    experiences: list[_Item] = []
    metadata: dict[str, str] = {}


@pytest.fixture
def ir() -> _IR:
    return _IR(
        target_role="SWE Intern",
        header=_Header(name="Alice Smith", email="a@x.com"),
        summary=["line1", "line2"],
        experiences=[_Item(name="Acme"), _Item(name="Beta")],
        metadata={"tone": "neutral"},
    )


def test_resolve_field_top_level(ir: _IR) -> None:
    assert resolve_field(ir, "target_role") == "SWE Intern"


def test_resolve_field_nested(ir: _IR) -> None:
    assert resolve_field(ir, "header.name") == "Alice Smith"
    assert resolve_field(ir, "header.email") == "a@x.com"


def test_resolve_field_indexed(ir: _IR) -> None:
    assert resolve_field(ir, "experiences.0.name") == "Acme"
    assert resolve_field(ir, "experiences.1.name") == "Beta"


def test_resolve_field_dict_value(ir: _IR) -> None:
    assert resolve_field(ir, "metadata.tone") == "neutral"


def test_resolve_field_missing_returns_none(ir: _IR) -> None:
    assert resolve_field(ir, "nope") is None
    assert resolve_field(ir, "header.does_not_exist") is None
    assert resolve_field(ir, "experiences.42.name") is None


def test_resolve_field_empty_path_returns_none(ir: _IR) -> None:
    assert resolve_field(ir, "") is None


# ---- render_command --------------------------------------------------


def test_render_arity_one_command(ir: _IR) -> None:
    mapping = LatexFieldMapping(
        ir_field="header.name", command="resumeheadername", arity=1
    )
    assert render_command(ir, mapping) == r"\resumeheadername{Alice Smith}"


def test_render_arity_two_command(ir: _IR) -> None:
    mapping = LatexFieldMapping(
        ir_field="experiences.0.name",
        second_ir_field="experiences.1.name",
        command="experiencerow",
        arity=2,
    )
    assert render_command(ir, mapping) == r"\experiencerow{Acme}{Beta}"


def test_render_arity_zero_command(ir: _IR) -> None:
    mapping = LatexFieldMapping(
        ir_field="header.name", command="resumeseparator", arity=0
    )
    assert render_command(ir, mapping) == r"\resumeseparator"


def test_render_returns_empty_when_arity_one_field_missing(ir: _IR) -> None:
    """A missing field is the template's signal to skip the line --
    we never emit ``\\cmd{}`` because the template would then render
    an empty header / empty bullet visibly."""
    mapping = LatexFieldMapping(
        ir_field="does.not.exist", command="resumeheadername", arity=1
    )
    assert render_command(ir, mapping) == ""


def test_render_escapes_special_characters(ir: _IR) -> None:
    ir2 = _IR(
        target_role="SWE Intern",
        header=_Header(name="A & B", email="a@x.com"),
        summary=[],
        experiences=[],
    )
    mapping = LatexFieldMapping(
        ir_field="header.name", command="resumeheadername", arity=1
    )
    assert render_command(ir2, mapping) == r"\resumeheadername{A \& B}"


def test_render_respects_config_escape_allowlist(ir: _IR) -> None:
    ir2 = _IR(
        target_role="SWE Intern",
        header=_Header(name="100% remote", email="a@x.com"),
        summary=[],
        experiences=[],
    )
    config = LatexConfig(escape_allowlist=["%"])
    mapping = LatexFieldMapping(
        ir_field="header.name", command="resumeheadername", arity=1
    )
    assert render_command(ir2, mapping, config=config) == r"\resumeheadername{100% remote}"


# ---- validate_assets -------------------------------------------------


def _make_manifest(latex: LatexConfig | None) -> TemplateManifest:
    return TemplateManifest(
        template_id="t",
        document_type="resume",
        template_format="latex",
        renderer="latex",
        latex=latex,
    )


def test_validate_assets_empty_list_is_ok(tmp_path: Path) -> None:
    manifest = _make_manifest(LatexConfig(assets=[]))
    assert validate_assets(manifest, tmp_path) == []


def test_validate_assets_missing_file_reports_error(tmp_path: Path) -> None:
    manifest = _make_manifest(LatexConfig(assets=["logo.png"]))
    errors = validate_assets(manifest, tmp_path)
    assert len(errors) == 1
    assert "not found" in errors[0]


def test_validate_assets_traversal_is_rejected(tmp_path: Path) -> None:
    """A tampered manifest must not be allowed to mount /etc/passwd
    as an 'asset' (D013 mirror)."""
    manifest = _make_manifest(LatexConfig(assets=["../outside.txt"]))
    errors = validate_assets(manifest, tmp_path)
    assert len(errors) == 1
    assert "outside" in errors[0]


def test_validate_assets_present_file_passes(tmp_path: Path) -> None:
    (tmp_path / "logo.png").write_bytes(b"\x89PNG")
    manifest = _make_manifest(LatexConfig(assets=["logo.png"]))
    assert validate_assets(manifest, tmp_path) == []


def test_validate_assets_no_latex_config_is_noop(tmp_path: Path) -> None:
    manifest = _make_manifest(None)
    assert validate_assets(manifest, tmp_path) == []


# ---- field coverage --------------------------------------------------


def test_field_coverage_strict_lists_uncovered() -> None:
    manifest = _make_manifest(
        LatexConfig(
            strict_field_coverage=True,
            field_mappings=[
                LatexFieldMapping(ir_field="header.name", command="x", arity=1),
            ],
        )
    )
    missing = validate_field_coverage(
        manifest, {"header.name", "summary", "experiences.0.name"}
    )
    assert missing == sorted(["summary", "experiences.0.name"])


def test_field_coverage_non_strict_is_noop() -> None:
    manifest = _make_manifest(
        LatexConfig(strict_field_coverage=False, field_mappings=[])
    )
    assert validate_field_coverage(manifest, {"anything"}) == []


def test_field_coverage_no_latex_config_is_noop() -> None:
    manifest = _make_manifest(None)
    assert validate_field_coverage(manifest, {"anything"}) == []


# ---- LatexConfig defaults --------------------------------------------


def test_latex_config_defaults_to_pdflatex() -> None:
    cfg = LatexConfig()
    assert cfg.compile_engine == "pdflatex"
    assert cfg.assets == []
    assert cfg.field_mappings == []
    assert cfg.strict_field_coverage is False


def test_template_manifest_latex_field_is_optional() -> None:
    """DOCX-only templates must keep working without a latex block."""
    manifest = TemplateManifest(template_id="x", document_type="resume")
    assert manifest.latex is None


def test_template_manifest_round_trips_latex_config_json() -> None:
    manifest = TemplateManifest(
        template_id="x",
        document_type="resume",
        template_format="latex",
        renderer="latex",
        latex=LatexConfig(
            compile_engine="xelatex",
            assets=["logo.png"],
            field_mappings=[
                LatexFieldMapping(ir_field="header.name", command="X", arity=1)
            ],
        ),
    )
    blob = manifest.model_dump_json()
    parsed = TemplateManifest.model_validate_json(blob)
    assert parsed.latex is not None
    assert parsed.latex.compile_engine == "xelatex"
    assert parsed.latex.assets == ["logo.png"]
    assert parsed.latex.field_mappings[0].command == "X"
