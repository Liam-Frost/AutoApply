"""Phase 15.4: tests for the manifest-adapter LaTeX renderer.

We don't compile real LaTeX in unit tests (binary may not be on the
test runner). The compile path is covered by tests that monkey-patch
``subprocess.run`` and ``shutil.which``; the render path runs in pure
Python against a real template + real IR.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.documents.latex_renderer import (
    ManifestRenderError,
    compile_via_manifest,
    render_resume_tex,
)
from src.documents.templates import (
    LatexConfig,
    LatexFieldMapping,
    TemplateManifest,
)
from src.generation.ir import ResumeBullet, ResumeDocument, ResumeItem


def _ir() -> ResumeDocument:
    return ResumeDocument(
        target_role="Software Engineer Intern",
        company="Acme",
        header={"name": "Alice Smith", "email": "a@x.com"},
        summary=["Built and shipped FastAPI services serving 10k rps."],
        skills={"must_have": ["python", "fastapi"]},
        experiences=[
            ResumeItem(
                source_id="exp-1",
                source_type="experience",
                name="Initech",
                title="Software Engineer Intern",
                bullets=[
                    ResumeBullet(
                        text="Reduced latency by 40% with a distributed cache.",
                        source_id="exp-1",
                        source_type="experience",
                        source_entity="Initech",
                    )
                ],
            )
        ],
    )


def _manifest(
    *,
    mappings: list[LatexFieldMapping] | None = None,
    strict: bool = False,
    assets: list[str] | None = None,
    engine: str = "pdflatex",
) -> TemplateManifest:
    return TemplateManifest(
        template_id="resume-adapter",
        document_type="resume",
        template_format="latex",
        renderer="latex",
        latex=LatexConfig(
            compile_engine=engine,
            assets=assets or [],
            field_mappings=mappings or [],
            strict_field_coverage=strict,
        ),
    )


# ---- render_resume_tex -----------------------------------------------


def test_render_requires_latex_config(tmp_path: Path) -> None:
    template = tmp_path / "template.tex"
    template.write_text("{{resume.commands}}", encoding="utf-8")
    manifest = TemplateManifest(
        template_id="x", document_type="resume", template_format="latex", renderer="latex"
    )  # no latex config
    with pytest.raises(ManifestRenderError, match="no `latex` config"):
        render_resume_tex(template, _ir(), tmp_path / "out.tex", manifest)


def test_render_requires_commands_placeholder(tmp_path: Path) -> None:
    template = tmp_path / "template.tex"
    template.write_text("no placeholder here", encoding="utf-8")
    with pytest.raises(ManifestRenderError, match="resume.commands"):
        render_resume_tex(template, _ir(), tmp_path / "out.tex", _manifest())


def test_render_substitutes_command_block(tmp_path: Path) -> None:
    template = tmp_path / "template.tex"
    template.write_text(
        r"\documentclass{article}\begin{document}"
        + "\n{{resume.commands}}\n"
        + r"\end{document}",
        encoding="utf-8",
    )
    manifest = _manifest(
        mappings=[
            LatexFieldMapping(ir_field="header.name", command="resumeheadername", arity=1),
            LatexFieldMapping(ir_field="target_role", command="targetrole", arity=1),
        ]
    )
    out = tmp_path / "out.tex"
    render_resume_tex(template, _ir(), out, manifest)
    text = out.read_text(encoding="utf-8")
    assert r"\resumeheadername{Alice Smith}" in text
    assert r"\targetrole{Software Engineer Intern}" in text


def test_render_skips_empty_field_commands(tmp_path: Path) -> None:
    """A mapping pointing at a missing IR field must NOT emit
    ``\\cmd{}`` -- the template would render a visible empty line."""
    template = tmp_path / "template.tex"
    template.write_text("{{resume.commands}}", encoding="utf-8")
    manifest = _manifest(
        mappings=[
            LatexFieldMapping(ir_field="header.name", command="resumeheadername", arity=1),
            LatexFieldMapping(ir_field="header.missing", command="optional", arity=1),
        ]
    )
    out = tmp_path / "out.tex"
    render_resume_tex(template, _ir(), out, manifest)
    text = out.read_text(encoding="utf-8")
    assert r"\resumeheadername" in text
    assert r"\optional" not in text


def test_render_strict_mode_blocks_missing_mappings(tmp_path: Path) -> None:
    template = tmp_path / "template.tex"
    template.write_text("{{resume.commands}}", encoding="utf-8")
    manifest = _manifest(strict=True, mappings=[])
    with pytest.raises(ManifestRenderError, match="IR field"):
        render_resume_tex(template, _ir(), tmp_path / "out.tex", manifest)


def test_render_strict_mode_allows_full_coverage(tmp_path: Path) -> None:
    template = tmp_path / "template.tex"
    template.write_text("{{resume.commands}}", encoding="utf-8")
    # Build a manifest that covers every flattened IR field.
    ir = _ir()
    fields: set[str] = set()
    for name in type(ir).model_fields:
        fields.add(name)
    fields.update(f"header.{k}" for k in (ir.header or {}))
    for collection in ("experiences", "projects", "education"):
        for idx in range(len(getattr(ir, collection) or [])):
            fields.add(f"{collection}.{idx}")
    mappings = [
        LatexFieldMapping(ir_field=field, command=f"f_{field.replace('.', '_')}", arity=1)
        for field in fields
    ]
    manifest = _manifest(strict=True, mappings=mappings)
    out = tmp_path / "out.tex"
    render_resume_tex(template, _ir(), out, manifest)  # should not raise
    assert out.exists()


def test_render_missing_template_file_errors(tmp_path: Path) -> None:
    with pytest.raises(ManifestRenderError, match="template file not found"):
        render_resume_tex(
            tmp_path / "absent.tex", _ir(), tmp_path / "out.tex", _manifest()
        )


# ---- compile_via_manifest --------------------------------------------


class _FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _stub_subprocess_success(*_args: Any, **_kwargs: Any) -> _FakeCompletedProcess:
    # Create the main.pdf in the cwd so the renderer's check passes.
    cwd = Path(_kwargs.get("cwd") or ".")
    (cwd / "main.pdf").write_bytes(b"%PDF-1.4\n")
    return _FakeCompletedProcess(returncode=0)


def test_compile_falls_through_when_no_latex_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Placeholder-only templates with no latex config should call the
    engine-agnostic helper."""
    called: dict[str, bool] = {"fallthrough": False}

    def _stub(*_a: Any, **_kw: Any) -> Path:
        called["fallthrough"] = True
        return tmp_path / "out.pdf"

    from src.documents import latex_renderer as renderer

    monkeypatch.setattr(renderer, "compile_latex_to_pdf", _stub)
    manifest = TemplateManifest(
        template_id="t", document_type="resume", template_format="latex", renderer="latex"
    )
    tex = tmp_path / "in.tex"
    tex.write_text("ok", encoding="utf-8")
    compile_via_manifest(tex, manifest=manifest, package_dir=tmp_path)
    assert called["fallthrough"] is True


def test_compile_engine_binary_missing_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    tex = tmp_path / "in.tex"
    tex.write_text("ok", encoding="utf-8")
    with pytest.raises(ManifestRenderError, match="not on PATH"):
        compile_via_manifest(tex, manifest=_manifest(), package_dir=tmp_path)


def test_compile_invokes_pinned_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[list[str]] = []

    def _which(name: str) -> str | None:
        return f"/usr/bin/{name}"

    def _run(cmd: list[str], **kwargs: Any) -> _FakeCompletedProcess:
        captured.append(cmd)
        return _stub_subprocess_success(**kwargs)

    monkeypatch.setattr("shutil.which", _which)
    monkeypatch.setattr("src.documents.latex_renderer.subprocess.run", _run)

    tex = tmp_path / "in.tex"
    tex.write_text(r"\documentclass{article}\begin{document}x\end{document}", encoding="utf-8")
    compile_via_manifest(
        tex,
        tmp_path / "out.pdf",
        manifest=_manifest(engine="xelatex"),
        package_dir=tmp_path,
    )
    assert captured and captured[0][0].endswith("xelatex")


def test_compile_rejects_missing_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}")
    tex = tmp_path / "in.tex"
    tex.write_text("ok", encoding="utf-8")
    manifest = _manifest(assets=["missing.png"])
    with pytest.raises(ManifestRenderError, match="assets failed"):
        compile_via_manifest(tex, manifest=manifest, package_dir=tmp_path)


def test_compile_propagates_engine_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}")

    def _run_fail(*_a: Any, **_kw: Any) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(returncode=1, stdout="! Undefined control sequence.")

    monkeypatch.setattr("src.documents.latex_renderer.subprocess.run", _run_fail)
    tex = tmp_path / "in.tex"
    tex.write_text("ok", encoding="utf-8")
    with pytest.raises(ManifestRenderError, match="exit 1"):
        compile_via_manifest(tex, manifest=_manifest(), package_dir=tmp_path)


def test_compile_copies_assets_alongside_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}")
    seen_files: list[str] = []

    def _run(cmd: list[str], **kwargs: Any) -> _FakeCompletedProcess:
        cwd = Path(kwargs.get("cwd") or ".")
        seen_files.extend(p.name for p in cwd.iterdir())
        (cwd / "main.pdf").write_bytes(b"%PDF-1.4\n")
        return _FakeCompletedProcess(0)

    monkeypatch.setattr("src.documents.latex_renderer.subprocess.run", _run)

    (tmp_path / "logo.png").write_bytes(b"\x89PNG")
    tex = tmp_path / "in.tex"
    tex.write_text("ok", encoding="utf-8")
    manifest = _manifest(assets=["logo.png"])
    compile_via_manifest(tex, manifest=manifest, package_dir=tmp_path)
    assert "logo.png" in seen_files
    assert "main.tex" in seen_files
