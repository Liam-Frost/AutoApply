from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from src.application import jobs as jobs_app


def _template_package() -> SimpleNamespace:
    return SimpleNamespace(
        template_id="resume-template",
        manifest=SimpleNamespace(renderer="docx", supported_outputs=["docx", "pdf"]),
    )


def test_patch_existing_drops_stale_template_pdf(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "src.documents.templates.ensure_template_package",
        lambda *_args, **_kwargs: _template_package(),
    )
    monkeypatch.setattr(
        "src.documents.templates.serialize_template_package",
        lambda package: {"template_id": package.template_id},
    )
    monkeypatch.setattr(
        "src.generation.resume_builder.generate_resume",
        lambda **_kwargs: {
            "pdf": str(tmp_path / "template.pdf"),
            "docx": str(tmp_path / "template.docx"),
            "ir": object(),
            "validation": None,
        },
    )
    monkeypatch.setattr(
        jobs_app,
        "_try_patch_docx_from_library",
        lambda **_kwargs: (tmp_path / "patched.docx", None),
    )

    result = jobs_app._generate_selected_material(
        {},
        SimpleNamespace(),
        "resume_pdf",
        strategy="patch_existing",
        source_document_id=str(uuid4()),
    )

    assert result["artifacts"]["resume_docx"] == str(tmp_path / "patched.docx")
    assert result["artifacts"]["resume_pdf"] is None


def test_patch_existing_uses_unique_output_paths(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    source.write_bytes(b"docx")
    outputs: list[Path] = []
    document_id = str(uuid4())

    @contextmanager
    def session_context():
        yield object()

    monkeypatch.setattr(
        "src.core.database.get_session_factory",
        lambda *_args, **_kwargs: session_context,
    )
    monkeypatch.setattr(
        "src.documents.user_documents.get_document",
        lambda *_args, **_kwargs: SimpleNamespace(document_type="resume", source_type="docx"),
    )
    monkeypatch.setattr(
        "src.documents.user_documents.resolve_storage_path",
        lambda _row: source,
    )

    def patch_resume_docx(_source, _ir, *, output_path):
        outputs.append(output_path)
        Path(output_path).write_bytes(b"patched")

    monkeypatch.setattr("src.generation.docx_patch.patch_resume_docx", patch_resume_docx)

    first, first_note = jobs_app._try_patch_docx_from_library(
        document_id=document_id,
        ir=object(),
        output_dir=tmp_path,
    )
    second, second_note = jobs_app._try_patch_docx_from_library(
        document_id=document_id,
        ir=object(),
        output_dir=tmp_path,
    )

    assert first_note is None
    assert second_note is None
    assert first != second
    assert outputs == [first, second]
    assert first.name.startswith("patched_resume_")
    assert second.name.startswith("patched_resume_")
