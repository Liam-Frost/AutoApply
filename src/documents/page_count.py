"""Rendered document page counting helpers."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from xml.etree import ElementTree

logger = logging.getLogger("autoapply.documents.page_count")


def get_pdf_page_count(path: Path | None) -> int | None:
    """Return the actual number of pages in a PDF when readable."""
    if path is None or not path.exists():
        return None

    try:
        import fitz

        with fitz.open(str(path)) as document:
            return int(document.page_count)
    except Exception as exc:
        logger.debug("PDF page count skipped for %s: %s", path, exc)
        return None


def get_docx_page_count(path: Path | None, *, rendered_pdf_path: Path | None = None) -> int | None:
    """Return a DOCX page count.

    Word page counts are only reliable after layout. In the DOCX-first flow, the
    converted PDF is the rendered layout, so prefer its page count. If no PDF is
    available, fall back to docProps/app.xml when a producer has populated it.
    """
    pdf_count = get_pdf_page_count(rendered_pdf_path)
    if pdf_count is not None:
        return pdf_count
    if path is None or not path.exists():
        return None

    try:
        with zipfile.ZipFile(path) as archive:
            with archive.open("docProps/app.xml") as handle:
                root = ElementTree.parse(handle).getroot()
        for element in root.iter():
            if element.tag.endswith("Pages") and element.text:
                return int(element.text)
    except Exception as exc:
        logger.debug("DOCX metadata page count skipped for %s: %s", path, exc)
    return None
