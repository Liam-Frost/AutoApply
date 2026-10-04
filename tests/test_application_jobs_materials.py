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


def _stub_resume_pipeline(monkeypatch, tmp_path: Path) -> None:
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


async def test_application_materials_prefers_cover_letter_pdf_not_txt(
    monkeypatch, tmp_path: Path
) -> None:
    resume_pdf = tmp_path / "resume.pdf"
    cover_pdf = tmp_path / "cover.pdf"
    cover_docx = tmp_path / "cover.docx"
    cover_txt = tmp_path / "cover.txt"
    for path in (resume_pdf, cover_pdf, cover_docx, cover_txt):
        path.write_text("x", encoding="utf-8")

    monkeypatch.setattr(
        "src.generation.resume_builder.generate_resume",
        lambda **_kwargs: {"pdf": resume_pdf, "docx": tmp_path / "resume.docx"},
    )
    monkeypatch.setattr(
        "src.generation.cover_letter.generate_cover_letter",
        lambda **_kwargs: {"pdf": cover_pdf, "docx": cover_docx, "txt": cover_txt},
    )
    monkeypatch.setattr(
        "src.application.material_defaults.resolve_material_choice",
        lambda *, document_type, **_kwargs: {
            "strategy": "regenerate",
            "template_id": None,
            "document_id": None,
            "patch_aggressiveness": "balanced",
            "patch_allow_reorder_sections": True,
            "patch_allow_add_remove_bullets": True,
            "source": "test-default",
        },
    )

    resume_path, cover_letter_path, _qa = await jobs_app._generate_materials(
        {"qa_bank": []}, SimpleNamespace(company="Acme", title="Engineer")
    )

    assert resume_path == resume_pdf
    assert cover_letter_path == cover_pdf


async def test_application_materials_honor_patch_default_strategy(
    monkeypatch, tmp_path: Path
) -> None:
    patched_resume = tmp_path / "patched_resume.docx"
    patched_cover = tmp_path / "patched_cover.docx"
    patched_resume.write_text("resume", encoding="utf-8")
    patched_cover.write_text("cover", encoding="utf-8")
    calls: list[tuple[str, str, str | None]] = []

    def fake_choice(*, document_type, **_kwargs):
        return {
            "strategy": "patch_existing",
            "template_id": None,
            "document_id": f"{document_type}-doc-id",
            "patch_aggressiveness": "balanced",
            "patch_allow_reorder_sections": True,
            "patch_allow_add_remove_bullets": True,
            "source": "saved-default",
        }

    def fake_generate(_profile_data, _job, material_type, **kwargs):
        calls.append((material_type, kwargs["strategy"], kwargs["source_document_id"]))
        artifacts = jobs_app._empty_material_artifacts()
        if material_type == "resume_docx":
            artifacts["resume_docx"] = str(patched_resume)
        elif material_type == "cover_letter_docx":
            artifacts["cover_letter_docx"] = str(patched_cover)
        return {"artifacts": artifacts, "strategy_notes": []}

    monkeypatch.setattr("src.application.material_defaults.resolve_material_choice", fake_choice)
    monkeypatch.setattr(jobs_app, "_generate_selected_material", fake_generate)

    resume_path, cover_letter_path, _qa = await jobs_app._generate_materials(
        {"qa_bank": []}, SimpleNamespace(company="Acme", title="Engineer")
    )

    assert resume_path == patched_resume
    assert cover_letter_path == patched_cover
    assert calls == [
        ("resume_docx", "patch_existing", "resume-doc-id"),
        ("cover_letter_docx", "patch_existing", "cover_letter-doc-id"),
    ]


async def test_application_materials_share_evidence_between_resume_and_cover(
    monkeypatch, tmp_path: Path
) -> None:
    resume_pdf = tmp_path / "resume.pdf"
    cover_pdf = tmp_path / "cover.pdf"
    resume_pdf.write_bytes(b"%PDF-1.7\n")
    cover_pdf.write_bytes(b"%PDF-1.7\n")
    shared_resume_evidence = [object()]
    shared_cover_evidence = ["At RelevantCo - Backend Intern, Built FastAPI services"]
    calls: list[tuple[str, list | None, list[str] | None]] = []

    monkeypatch.setattr(
        "src.application.material_defaults.resolve_material_choice",
        lambda *, document_type, **_kwargs: {
            "strategy": "regenerate",
            "template_id": None,
            "document_id": None,
            "patch_aggressiveness": "balanced",
            "patch_allow_reorder_sections": True,
            "patch_allow_add_remove_bullets": True,
            "source": "test-default",
        },
    )
    monkeypatch.setattr(
        jobs_app,
        "_build_shared_material_evidence",
        lambda _profile, _job: {
            "entities": ["RelevantCo - Backend Intern"],
            "resume_evidence": shared_resume_evidence,
            "cover_evidence": shared_cover_evidence,
        },
    )

    def fake_generate(_profile_data, _job, material_type, **kwargs):
        calls.append(
            (
                material_type,
                kwargs.get("shared_resume_evidence"),
                kwargs.get("shared_cover_evidence"),
            )
        )
        artifacts = jobs_app._empty_material_artifacts()
        if material_type == "resume_pdf":
            artifacts["resume_pdf"] = str(resume_pdf)
        elif material_type == "cover_letter_pdf":
            artifacts["cover_letter_pdf"] = str(cover_pdf)
        return {"artifacts": artifacts, "strategy_notes": []}

    monkeypatch.setattr(jobs_app, "_generate_selected_material", fake_generate)

    resume_path, cover_letter_path, _qa = await jobs_app._generate_materials(
        {"qa_bank": []}, SimpleNamespace(company="Acme", title="Engineer")
    )

    assert resume_path == resume_pdf
    assert cover_letter_path == cover_pdf
    assert calls == [
        ("resume_pdf", shared_resume_evidence, None),
        ("cover_letter_pdf", None, shared_cover_evidence),
    ]


async def test_application_materials_use_library_preserves_pdf_format(
    monkeypatch, tmp_path: Path
) -> None:
    resume_pdf = tmp_path / "library_resume.pdf"
    cover_pdf = tmp_path / "cover.pdf"
    resume_pdf.write_bytes(b"%PDF-1.7\n")
    cover_pdf.write_bytes(b"%PDF-1.7\n")
    calls: list[tuple[str, str, str | None]] = []

    def fake_choice(*, document_type, **_kwargs):
        if document_type == "resume":
            return {
                "strategy": "use_library",
                "template_id": None,
                "document_id": "resume-doc-id",
                "patch_aggressiveness": "balanced",
                "patch_allow_reorder_sections": True,
                "patch_allow_add_remove_bullets": True,
                "source": "saved-default",
            }
        return {
            "strategy": "regenerate",
            "template_id": None,
            "document_id": None,
            "patch_aggressiveness": "balanced",
            "patch_allow_reorder_sections": True,
            "patch_allow_add_remove_bullets": True,
            "source": "system-default",
        }

    def fake_generate(_profile_data, _job, material_type, **kwargs):
        calls.append((material_type, kwargs["strategy"], kwargs["source_document_id"]))
        artifacts = jobs_app._empty_material_artifacts()
        if material_type == "resume_pdf":
            artifacts["resume_pdf"] = str(resume_pdf)
        elif material_type == "cover_letter_pdf":
            artifacts["cover_letter_pdf"] = str(cover_pdf)
        return {"artifacts": artifacts, "strategy_notes": []}

    monkeypatch.setattr("src.application.material_defaults.resolve_material_choice", fake_choice)
    monkeypatch.setattr(jobs_app, "_library_document_source_type", lambda _doc_id: "pdf")
    monkeypatch.setattr(jobs_app, "_generate_selected_material", fake_generate)

    resume_path, cover_letter_path, _qa = await jobs_app._generate_materials(
        {"qa_bank": []}, SimpleNamespace(company="Acme", title="Engineer")
    )

    assert resume_path == resume_pdf
    assert cover_letter_path == cover_pdf
    assert calls == [
        ("resume_pdf", "use_library", "resume-doc-id"),
        ("cover_letter_pdf", "regenerate", None),
    ]


def test_application_material_type_maps_library_latex_to_tex(monkeypatch) -> None:
    monkeypatch.setattr(jobs_app, "_library_document_source_type", lambda _doc_id: "latex")

    material_type = jobs_app._application_material_type(
        "resume",
        {"strategy": "use_library", "document_id": "resume-doc-id"},
    )

    assert material_type == "resume_tex"


def test_pick_application_artifact_includes_txt_for_library() -> None:
    picked = jobs_app._pick_application_artifact(
        {"cover_letter_txt": "data/output/cover.txt"},
        "cover_letter",
        "use_library",
    )

    assert picked == Path("data/output/cover.txt")


def test_patch_existing_drops_stale_template_pdf_for_docx_request(
    monkeypatch, tmp_path: Path
) -> None:
    """When the caller asked for ``resume_docx``, the template PDF is
    stale relative to the patched DOCX and must be dropped so a UI
    download doesn't disagree with the patched output."""
    _stub_resume_pipeline(monkeypatch, tmp_path)

    result = jobs_app._generate_selected_material(
        {},
        SimpleNamespace(),
        "resume_docx",
        strategy="patch_existing",
        source_document_id=str(uuid4()),
    )

    assert result["artifacts"]["resume_docx"] == str(tmp_path / "patched.docx")
    assert result["artifacts"]["resume_pdf"] is None


def test_patch_existing_generates_tailored_ir_with_rewrite(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict = {}

    monkeypatch.setattr(
        "src.documents.templates.ensure_template_package",
        lambda *_args, **_kwargs: _template_package(),
    )
    monkeypatch.setattr(
        "src.documents.templates.serialize_template_package",
        lambda package: {"template_id": package.template_id},
    )

    def fake_generate_resume(**kwargs):
        captured.update(kwargs)
        return {
            "pdf": str(tmp_path / "template.pdf"),
            "docx": str(tmp_path / "template.docx"),
            "ir": object(),
            "validation": None,
        }

    monkeypatch.setattr("src.generation.resume_builder.generate_resume", fake_generate_resume)
    monkeypatch.setattr(
        jobs_app,
        "_try_patch_docx_from_library",
        lambda **_kwargs: (tmp_path / "patched.docx", None),
    )

    jobs_app._generate_selected_material(
        {},
        SimpleNamespace(),
        "resume_docx",
        strategy="patch_existing",
        source_document_id=str(uuid4()),
        patch_aggressiveness="aggressive",
    )

    assert captured["rewrite"] is True
    assert captured["use_llm"] is True
    assert captured["rewrite_mode"] == "aggressive"


def test_patch_existing_preserves_pdf_when_pdf_was_requested(
    monkeypatch, tmp_path: Path
) -> None:
    """Regression: dropping ``resume_pdf`` indiscriminately during the
    patch flow nuked the artifact the user actually requested when
    they picked the PDF format, leading to "could not be generated"
    errors. Now the PDF stays put (we surface a strategy note instead
    explaining the patched DOCX is a side artifact)."""
    _stub_resume_pipeline(monkeypatch, tmp_path)

    result = jobs_app._generate_selected_material(
        {},
        SimpleNamespace(),
        "resume_pdf",
        strategy="patch_existing",
        source_document_id=str(uuid4()),
    )

    assert result["artifacts"]["resume_pdf"] == str(tmp_path / "template.pdf")
    assert result["artifacts"]["resume_docx"] == str(tmp_path / "patched.docx")
    assert any(
        "pick the docx format" in note.lower()
        for note in result["strategy_notes"]
    ), result["strategy_notes"]


def test_serialize_material_artifact_accepts_string_path(tmp_path: Path) -> None:
    """Regression: ``_serialize_material_artifact`` was typed to take
    a Path but the patch_existing flow stringifies before stashing the
    value in ``artifacts``, so the helper was being called with a
    plain string and crashed with
    ``AttributeError: 'str' object has no attribute 'name'``. The
    failure only surfaced after a successful patch -- which is why it
    sat undetected through the regenerate-only test path."""
    str_path = str(tmp_path / "patched_resume_xyz.docx")

    result = jobs_app._serialize_material_artifact("resume_docx", str_path)

    assert result["type"] == "resume_docx"
    assert result["filename"] == "patched_resume_xyz.docx"
    # Path string is preserved (normalized by pathlib, but stays a
    # plain string -- not converted into a Path object in the dict).
    assert isinstance(result["path"], str)
    assert "patched_resume_xyz.docx" in result["path"]


def test_serialize_material_artifact_accepts_path_object(tmp_path: Path) -> None:
    """The non-patch flow still passes a Path; that path must keep
    working."""
    p = tmp_path / "resume.docx"
    result = jobs_app._serialize_material_artifact("resume_docx", p)
    assert result["type"] == "resume_docx"
    assert result["filename"] == "resume.docx"
    assert result["path"] == str(p)


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

    def patch_resume_docx(_source, _ir, *, output_path, **_extra_kwargs):
        # Tolerate the Phase 18.x patch policy kwargs (``allow_reorder_sections``,
        # ``allow_add_remove_bullets``) the production caller now passes
        # through. This test only cares about the unique output path
        # logic, not the patch flags.
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
    # Phase 18.4: patch_resume_docx now writes through atomic_write,
    # so the path the patcher sees is a ``.tmp`` sibling of the
    # eventually-renamed final path. The unique-output guarantee is
    # what this test cares about, so we assert the two tmp paths
    # were distinct and the renamed final paths line up.
    assert len(outputs) == 2
    assert outputs[0] != outputs[1]
    for tmp_arg, final_path in zip(outputs, [first, second], strict=True):
        assert Path(tmp_arg).name.startswith(final_path.name)
    assert first.name.startswith("patched_resume_")
    assert second.name.startswith("patched_resume_")


# ---- use_library strategy --------------------------------------------


def test_use_library_strategy_copies_file_no_llm(
    monkeypatch, tmp_path: Path
) -> None:
    """The third strategy: take a library document and attach it as-is.

    No LLM, no template, no IR. The source bytes are copied to the
    output dir under a fresh filename and pinned in
    ``artifacts[material_type]``. The strategy_notes line names the
    source file so the operator audit trail can reconstruct what
    happened.
    """
    source = tmp_path / "Liam_Resume.docx"
    source.write_bytes(b"hello docx")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    @contextmanager
    def session_context():
        yield object()

    monkeypatch.setattr(jobs_app, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "src.core.database.get_session_factory",
        lambda *_args, **_kwargs: session_context,
    )
    monkeypatch.setattr(
        "src.documents.user_documents.get_document",
        lambda *_args, **_kwargs: SimpleNamespace(
            document_type="resume",
            source_type="docx",
            original_filename="Liam_Resume.docx",
        ),
    )
    monkeypatch.setattr(
        "src.documents.user_documents.resolve_storage_path",
        lambda _row: source,
    )

    result = jobs_app._generate_selected_material(
        {},
        SimpleNamespace(),
        "resume_docx",
        strategy="use_library",
        source_document_id=str(uuid4()),
    )

    copied = result["artifacts"]["resume_docx"]
    assert copied is not None
    assert Path(copied).exists()
    assert Path(copied).read_bytes() == b"hello docx"
    # The filename is *not* the source path -- it's a fresh copy in
    # the run's output directory so the audit trail mirrors the
    # regenerate/patch flows.
    assert Path(copied).resolve() != source.resolve()
    # Strategy note names the library file so the operator can grep
    # for it in the run history.
    assert any(
        "Liam_Resume.docx" in note for note in result["strategy_notes"]
    )
    # IR / validation / template are all absent for this strategy --
    # the route returns the file untouched, no metadata to surface.
    assert result["document"] is None
    assert result["validation"] is None
    assert result["template"] is None


def test_use_library_strategy_requires_source_document_id() -> None:
    """A use_library invocation with no document id is a programming
    error -- ``resolve_material_choice`` should already have
    downgraded it to ``regenerate``; if it leaks through, surface a
    loud ValueError rather than producing a copy of nothing."""
    import pytest

    with pytest.raises(ValueError, match="use_library"):
        jobs_app._generate_selected_material(
            {},
            SimpleNamespace(),
            "resume_docx",
            strategy="use_library",
            source_document_id=None,
        )


def test_use_library_strategy_rejects_wrong_source_format(
    monkeypatch, tmp_path: Path
) -> None:
    """If the user requested ``resume_docx`` but pointed at a PDF in
    their library, fail loudly rather than silently copying a PDF
    into a .docx slot."""
    import pytest

    source = tmp_path / "Liam_Resume.pdf"
    source.write_bytes(b"%PDF-1.7\n...")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    @contextmanager
    def session_context():
        yield object()

    monkeypatch.setattr(jobs_app, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "src.core.database.get_session_factory",
        lambda *_args, **_kwargs: session_context,
    )
    monkeypatch.setattr(
        "src.documents.user_documents.get_document",
        lambda *_args, **_kwargs: SimpleNamespace(
            document_type="resume",
            source_type="pdf",
            original_filename="Liam_Resume.pdf",
        ),
    )
    monkeypatch.setattr(
        "src.documents.user_documents.resolve_storage_path",
        lambda _row: source,
    )

    with pytest.raises(ValueError, match="DOCX"):
        jobs_app._generate_selected_material(
            {},
            SimpleNamespace(),
            "resume_docx",
            strategy="use_library",
            source_document_id=str(uuid4()),
        )


# ---- Patch knob plumbing ---------------------------------------------


def test_patch_knobs_threaded_into_patch_resume_docx(
    monkeypatch, tmp_path: Path
) -> None:
    """The two ``allow_*`` flags from ``material_defaults`` must
    reach ``patch_resume_docx`` so the policy can be honored. This
    test pins the plumbing -- the actual behaviour change for each
    flag lives in ``test_docx_patch``."""
    _stub_resume_pipeline(monkeypatch, tmp_path)

    captured: dict = {}

    def fake_try_patch(*, document_id, ir, output_dir, **kwargs):
        captured.update(kwargs)
        return tmp_path / "patched.docx", None

    monkeypatch.setattr(jobs_app, "_try_patch_docx_from_library", fake_try_patch)

    jobs_app._generate_selected_material(
        {},
        SimpleNamespace(),
        "resume_docx",
        strategy="patch_existing",
        source_document_id=str(uuid4()),
        patch_aggressiveness="conservative",
        patch_allow_reorder_sections=False,
        patch_allow_add_remove_bullets=False,
    )

    assert captured.get("allow_reorder_sections") is False
    assert captured.get("allow_add_remove_bullets") is False
