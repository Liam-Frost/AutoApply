"""Phase 15.1 tests for the source-resume ingest pipeline.

Schema invariants are checked offline; the round-trip + dedupe paths
run against the live dev Postgres on a per-test tenant prefix.
"""

from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from docx import Document
from sqlalchemy import create_engine
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import get_db_url, load_config
from src.core.models import SourceResume
from src.generation import source_resume as sr


@pytest.fixture(scope="module")
def engine():
    return create_engine(get_db_url(load_config()))


@pytest.fixture
def db_session(engine) -> Session:
    s = sessionmaker(bind=engine)()
    yield s
    s.execute(sa_delete(SourceResume).where(SourceResume.tenant_id.like("test-sr-%")))
    s.commit()
    s.close()


def _make_docx_bytes(*paragraphs: tuple[str, str]) -> bytes:
    """Return a DOCX byte payload with the given (style, text) pairs."""
    buf = BytesIO()
    doc = Document()
    for style, text in paragraphs:
        para = doc.add_paragraph(text)
        try:
            para.style = doc.styles[style]
        except KeyError:
            pass  # unknown style names default to Normal
    doc.save(buf)
    return buf.getvalue()


# ---- Schema ----------------------------------------------------------


def test_source_resume_columns_present() -> None:
    cols = SourceResume.__table__.columns
    expected = {
        "id",
        "tenant_id",
        "source_type",
        "editable",
        "original_filename",
        "checksum",
        "storage_path",
        "extracted_structure",
        "size_bytes",
        "notes",
        "created_at",
        "updated_at",
    }
    assert expected <= set(cols.keys()), expected - set(cols.keys())


def test_source_resume_unique_per_tenant_checksum() -> None:
    constraint_names = {c.name for c in SourceResume.__table__.constraints}
    assert "uq_source_resumes_tenant_checksum" in constraint_names


# ---- Type detection --------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("resume.docx", "docx"),
        ("Resume.DOCX", "docx"),
        ("cv.tex", "latex"),
        ("export.pdf", "pdf"),
    ],
)
def test_detect_source_type_known(filename: str, expected: str) -> None:
    assert sr.detect_source_type(filename) == expected


def test_detect_source_type_rejects_unknown() -> None:
    with pytest.raises(sr.SourceResumeError):
        sr.detect_source_type("resume.odt")


def test_compute_checksum_is_stable() -> None:
    data = b"hello"
    expected = hashlib.sha256(data).hexdigest()
    assert sr.compute_checksum(data) == expected


# ---- Ingest happy paths ----------------------------------------------


def test_ingest_docx_records_paragraph_structure(db_session: Session) -> None:
    payload = _make_docx_bytes(
        ("Heading 1", "Summary"),
        ("Normal", "Built and shipped a thing."),
        ("List Bullet", "- Delivered project on schedule"),
    )
    result = sr.ingest(
        db_session,
        filename="resume-a.docx",
        data=payload,
        tenant_id="test-sr-docx",
    )
    db_session.commit()

    row = db_session.get(SourceResume, result.row_id)
    assert row is not None
    assert row.source_type == "docx"
    assert row.editable is True
    assert row.original_filename == "resume-a.docx"
    assert row.size_bytes == len(payload)
    assert row.checksum == sr.compute_checksum(payload)
    assert row.extracted_structure["format"] == "docx"
    # We captured at least the three paragraphs we added.
    para_texts = [p["text_head"] for p in row.extracted_structure["paragraphs"]]
    assert any("Summary" in t for t in para_texts)
    assert any("schedule" in t for t in para_texts)


def test_ingest_latex_records_sections(db_session: Session) -> None:
    body = (
        rb"\documentclass{article}\begin{document}"
        rb"\section{Education}Some text"
        rb"\section{Experience}More text"
        rb"\subsection{Internship}Details"
        rb"\end{document}"
    )
    result = sr.ingest(
        db_session,
        filename="resume.tex",
        data=body,
        tenant_id="test-sr-latex",
    )
    db_session.commit()
    row = db_session.get(SourceResume, result.row_id)
    assert row is not None
    assert row.source_type == "latex"
    assert row.editable is True
    titles = [s["title"] for s in row.extracted_structure["sections"]]
    assert titles == ["Education", "Experience", "Internship"]


def test_ingest_pdf_marks_not_editable(db_session: Session) -> None:
    """We do not need a real PDF to verify the editable flag; the
    extractor may report extraction_supported=False if pymupdf can't
    parse, but the row must still land with editable=False."""
    payload = b"%PDF-1.4 minimal placeholder"
    result = sr.ingest(
        db_session,
        filename="cv.pdf",
        data=payload,
        tenant_id="test-sr-pdf",
    )
    db_session.commit()
    assert result.editable is False
    row = db_session.get(SourceResume, result.row_id)
    assert row is not None
    assert row.source_type == "pdf"
    assert row.editable is False


# ---- Dedupe ----------------------------------------------------------


def test_ingest_dedupes_identical_uploads(db_session: Session) -> None:
    payload = _make_docx_bytes(("Normal", "exact same bytes"))
    first = sr.ingest(
        db_session,
        filename="dup.docx",
        data=payload,
        tenant_id="test-sr-dedupe",
    )
    db_session.commit()
    second = sr.ingest(
        db_session,
        filename="dup-renamed.docx",
        data=payload,
        tenant_id="test-sr-dedupe",
    )
    db_session.commit()

    assert first.row_id == second.row_id
    count = (
        db_session.query(SourceResume)
        .filter(SourceResume.tenant_id == "test-sr-dedupe")
        .count()
    )
    assert count == 1


def test_same_bytes_different_tenant_creates_two_rows(db_session: Session) -> None:
    payload = _make_docx_bytes(("Normal", "tenant isolation check"))
    a = sr.ingest(
        db_session,
        filename="r.docx",
        data=payload,
        tenant_id="test-sr-multi-a",
    )
    b = sr.ingest(
        db_session,
        filename="r.docx",
        data=payload,
        tenant_id="test-sr-multi-b",
    )
    db_session.commit()
    assert a.row_id != b.row_id


# ---- Error paths -----------------------------------------------------


def test_ingest_rejects_empty_data(db_session: Session) -> None:
    with pytest.raises(sr.SourceResumeError):
        sr.ingest(db_session, filename="r.docx", data=b"", tenant_id="test-sr-empty")


def test_ingest_rejects_unsupported_extension(db_session: Session) -> None:
    with pytest.raises(sr.SourceResumeError):
        sr.ingest(
            db_session,
            filename="resume.odt",
            data=b"abc",
            tenant_id="test-sr-bad",
        )


# ---- Path resolution + delete ----------------------------------------


def test_resolve_storage_path_returns_existing_file(db_session: Session) -> None:
    payload = _make_docx_bytes(("Normal", "path resolution"))
    result = sr.ingest(
        db_session,
        filename="path-check.docx",
        data=payload,
        tenant_id="test-sr-path",
    )
    db_session.commit()
    row = db_session.get(SourceResume, result.row_id)
    assert row is not None
    target = sr.resolve_storage_path(row)
    assert target.exists()
    assert target.read_bytes() == payload


def test_delete_removes_file_and_row(db_session: Session) -> None:
    payload = _make_docx_bytes(("Normal", "delete me"))
    result = sr.ingest(
        db_session,
        filename="delete-me.docx",
        data=payload,
        tenant_id="test-sr-delete",
    )
    db_session.commit()
    row = db_session.get(SourceResume, result.row_id)
    assert row is not None
    target = sr.resolve_storage_path(row)
    assert target.exists()

    sr.delete(db_session, row)
    db_session.commit()
    assert db_session.get(SourceResume, result.row_id) is None
    assert not target.exists()


def test_resolve_storage_path_rejects_traversal(db_session: Session) -> None:
    """Defense in depth: a tampered storage_path that resolves outside
    the storage root must raise rather than open a file."""
    row = SourceResume(
        tenant_id="test-sr-traverse",
        source_type="docx",
        editable=True,
        original_filename="x.docx",
        checksum="0" * 64,
        storage_path="../../../etc/passwd",
        size_bytes=1,
    )
    with pytest.raises(sr.SourceResumeError):
        sr.resolve_storage_path(row)
