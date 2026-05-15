"""Phase 15 codex-review fix verification.

The Phase 15.10-close codex review surfaced three P2 issues:

* Materials router rejected legacy LaTeX templates with no Phase 15.3
  ``latex`` manifest block, even though the existing
  ``latex_engine.build_resume_tex_from_ir`` placeholder renderer
  could have handled them.
* PDF source-resume ingest computed ``len(doc)`` AFTER the
  ``pymupdf.open(...)`` context manager closed the Document.
* Manifest-adapter compile flattened ``images/logo.png`` to
  ``logo.png`` when copying assets into the temporary workdir.

These tests pin the fixes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.documents.latex_renderer import compile_via_manifest
from src.documents.templates import (
    LatexConfig,
    LatexFieldMapping,
    TemplateManifest,
    TemplatePackage,
)
from src.generation.ir import ResumeBullet, ResumeDocument, ResumeItem
from src.generation.materials_router import (
    generate_materials,
)


def _ir() -> ResumeDocument:
    return ResumeDocument(
        target_role="Software Engineer Intern",
        company="Acme",
        header={"name": "Alice", "email": "a@x.com"},
        summary=["short summary"],
        skills={"must_have": ["python"]},
        experiences=[
            ResumeItem(
                source_id="exp-1",
                source_type="experience",
                name="Initech",
                bullets=[
                    ResumeBullet(
                        text="Built things.",
                        source_id="exp-1",
                        source_type="experience",
                        source_entity="Initech",
                    )
                ],
            )
        ],
    )


# ---- P2: legacy latex template with no `latex` manifest block --------


def test_router_renders_legacy_latex_template_without_latex_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A LaTeX TemplatePackage whose manifest has no `latex` block
    (e.g. the legacy upload path that wrote one before Phase 15.3
    landed) must still render via the placeholder-based engine
    instead of returning decision='unsupported'."""
    pkg_dir = tmp_path / "legacy_pkg"
    pkg_dir.mkdir()
    template_tex = pkg_dir / "template.tex"
    # The placeholder renderer uses {{resume.sections}} -- we keep it
    # minimal so the build_resume_tex_from_ir helper produces a valid
    # .tex string. compile is monkey-patched.
    template_tex.write_text(
        "\\documentclass{article}\\begin{document}\n"
        "{{header.name}} -- {{header.email}}\n"
        "{{resume.sections}}\n"
        "\\end{document}",
        encoding="utf-8",
    )
    manifest = TemplateManifest(
        template_id="legacy-latex",
        document_type="resume",
        template_format="latex",
        renderer="latex",
        # NO `latex` block -- this is the legacy shape.
    )
    pkg = TemplatePackage(
        template_id="legacy-latex",
        document_type="resume",
        directory=pkg_dir,
        template_path=template_tex,
        manifest_path=pkg_dir / "manifest.json",
        manifest=manifest,
    )

    # Stub the compile so the test does not need a real LaTeX binary.
    def _stub_compile(tex_path: Path, output_path: Path | None = None, **_: Any) -> Path:
        out = output_path or tex_path.with_suffix(".pdf")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"%PDF-1.4\n")
        return out

    monkeypatch.setattr(
        "src.documents.latex_engine.compile_latex_to_pdf",
        _stub_compile,
    )
    # Also patch the imported alias inside materials_router so the
    # fallback path sees the stub.
    monkeypatch.setattr(
        "src.generation.materials_router._render_placeholder_latex",
        lambda tp, doc, tex_out, pdf_out: (
            (tex_out.write_text("placeholder ok", encoding="utf-8") or tex_out),
            (pdf_out.write_bytes(b"%PDF-1.4\n") or pdf_out),
        ),
    )

    outcome = generate_materials(
        document=_ir(),
        mode="generate_from_template",
        output_dir=tmp_path / "out",
        template_package=pkg,
    )
    assert outcome.decision == "generate_latex"
    assert outcome.failure is None
    assert len(outcome.output_paths) == 2


def test_router_failure_for_legacy_latex_is_surfaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the legacy placeholder renderer itself raises, the router
    reports it under decision='generate_latex' instead of
    'unsupported' so the operator UI shows the real error."""
    pkg_dir = tmp_path / "legacy_pkg_fail"
    pkg_dir.mkdir()
    template_tex = pkg_dir / "template.tex"
    template_tex.write_text("ok", encoding="utf-8")
    manifest = TemplateManifest(
        template_id="legacy-fail",
        document_type="resume",
        template_format="latex",
        renderer="latex",
    )
    pkg = TemplatePackage(
        template_id="legacy-fail",
        document_type="resume",
        directory=pkg_dir,
        template_path=template_tex,
        manifest_path=pkg_dir / "manifest.json",
        manifest=manifest,
    )

    def _stub_render(*args: Any, **kwargs: Any) -> tuple[Path, Path]:
        raise RuntimeError("placeholder renderer blew up")

    monkeypatch.setattr(
        "src.generation.materials_router._render_placeholder_latex", _stub_render
    )

    outcome = generate_materials(
        document=_ir(),
        mode="generate_from_template",
        output_dir=tmp_path / "out",
        template_package=pkg,
    )
    assert outcome.decision == "generate_latex"
    assert outcome.failure is not None and "placeholder" in outcome.failure


# ---- P2: PDF source resume page_count -------------------------------


def test_pdf_ingest_records_page_count_when_pymupdf_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replace pymupdf.open with a tiny stub that yields a 3-page
    Document; the extracted structure must record page_count=3 (the
    pre-fix code computed len(doc) after the with block closed it)."""

    class _Span:
        def __init__(self, text: str, size: float, font: str = "") -> None:
            self._text = text
            self._size = size
            self._font = font

        def get(self, key: str, default: Any = None) -> Any:
            if key == "text":
                return self._text
            if key == "size":
                return self._size
            if key == "font":
                return self._font
            return default

    class _Page:
        def get_text(self, _mode: str) -> dict[str, Any]:
            return {
                "blocks": [
                    {"lines": [{"spans": [_Span("Heading", 16, "Helvetica-Bold")]}]}
                ]
            }

    class _Doc:
        def __init__(self, pages: int) -> None:
            self._pages = pages
            self.closed = False

        def __enter__(self) -> _Doc:
            return self

        def __exit__(self, *args: Any) -> None:
            self.closed = True

        def __iter__(self) -> Any:
            return iter([_Page() for _ in range(self._pages)])

        def __len__(self) -> int:
            if self.closed:
                raise RuntimeError("len() on closed document")
            return self._pages

    class _PyMuPDF:
        @staticmethod
        def open(_path: str) -> _Doc:
            return _Doc(pages=3)

    monkeypatch.setitem(
        __import__("sys").modules, "pymupdf", _PyMuPDF()
    )

    from src.generation.source_resume import _extract_pdf_headings

    out = _extract_pdf_headings(tmp_path / "irrelevant.pdf")
    assert out["format"] == "pdf"
    assert out["page_count"] == 3
    assert out["extraction_supported"] is True
    assert "Heading" in out["headings"]


def test_pdf_ingest_no_pymupdf_returns_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    sys.modules.pop("pymupdf", None)

    original_import = (
        __builtins__["__import__"]
        if isinstance(__builtins__, dict)
        else __builtins__.__import__
    )
    monkeypatch.setattr(
        "builtins.__import__",
        _import_blocking("pymupdf", original=original_import),
    )

    from src.generation.source_resume import _extract_pdf_headings

    out = _extract_pdf_headings(Path("does-not-matter.pdf"))
    assert out == {"format": "pdf", "headings": [], "extraction_supported": False}


def _import_blocking(blocked: str, *, original: Any) -> Any:
    def _stub(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == blocked:
            raise ImportError(f"blocked {blocked}")
        return original(name, *args, **kwargs)

    return _stub


# ---- P2: asset subdirectories preserved during compile --------------


def test_compile_preserves_asset_subdirectory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest declaring ``images/logo.png`` must land at
    ``workdir/images/logo.png`` -- flattening to ``workdir/logo.png``
    breaks \\includegraphics{images/logo.png}."""
    images = tmp_path / "images"
    images.mkdir()
    (images / "logo.png").write_bytes(b"\x89PNG")

    tex = tmp_path / "main.tex"
    tex.write_text("ok", encoding="utf-8")

    manifest = TemplateManifest(
        template_id="x",
        document_type="resume",
        template_format="latex",
        renderer="latex",
        latex=LatexConfig(
            compile_engine="pdflatex",
            assets=["images/logo.png"],
            field_mappings=[
                LatexFieldMapping(ir_field="header.name", command="x", arity=1)
            ],
        ),
    )

    seen_paths: list[Path] = []

    def _stub_run(cmd: list[str], **kwargs: Any) -> Any:
        cwd = Path(kwargs.get("cwd") or ".")
        seen_paths.extend(p.relative_to(cwd) for p in cwd.rglob("*") if p.is_file())
        (cwd / "main.pdf").write_bytes(b"%PDF-1.4\n")

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        return _R()

    monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setattr("src.documents.latex_renderer.subprocess.run", _stub_run)

    compile_via_manifest(
        tex,
        tmp_path / "out.pdf",
        manifest=manifest,
        package_dir=tmp_path,
    )

    rel_paths = {str(p).replace("\\", "/") for p in seen_paths}
    assert "images/logo.png" in rel_paths, (
        f"asset must land at images/logo.png; got {rel_paths}"
    )
    assert "logo.png" not in rel_paths, (
        "asset must NOT be flattened to the workdir root"
    )
