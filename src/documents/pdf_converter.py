"""Word to PDF converter.

Uses docx2pdf (Windows COM / LibreOffice) to convert .docx to .pdf.
Falls back to LibreOffice CLI if docx2pdf is unavailable.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("autoapply.documents.pdf_converter")


def convert_to_pdf(docx_path: Path, output_path: Path | None = None) -> Path:
    """Convert a .docx file to PDF.

    Args:
        docx_path: Path to the .docx file.
        output_path: Optional explicit output path. Defaults to same dir, .pdf extension.

    Returns:
        Path to the generated PDF.
    """
    if not docx_path.exists():
        raise FileNotFoundError(f"Source file not found: {docx_path}")

    if output_path is None:
        output_path = docx_path.with_suffix(".pdf")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Try docx2pdf first (Word COM on Windows; on macOS it drives Microsoft
    # Word via AppleScript). Skip it outright on macOS when Word isn't
    # installed: a missing-Word AppleEvent doesn't raise a catchable Python
    # exception here, it kills the whole worker process
    # (``osascript``/AppleEvent "Message not understood" -> WorkerLostError),
    # so the `except Exception` below never gets a chance to fall through to
    # LibreOffice. Checking for Word.app first avoids the crash entirely.
    _MACOS_WORD_PATHS = (
        "/Applications/Microsoft Word.app",
        "/Applications/Microsoft Office/Microsoft Word.app",
    )
    word_available = sys.platform != "darwin" or any(
        Path(p).exists() for p in _MACOS_WORD_PATHS
    )
    if word_available:
        try:
            from docx2pdf import convert

            convert(str(docx_path), str(output_path))
            logger.info("Converted %s → %s (docx2pdf)", docx_path.name, output_path.name)
            return output_path
        except Exception as e:
            logger.warning("docx2pdf failed (%s), trying LibreOffice CLI", e)
    else:
        logger.info("Microsoft Word not found on macOS; using LibreOffice CLI directly")

    # Fall back to LibreOffice CLI
    libreoffice = _find_libreoffice()
    if libreoffice:
        return _convert_via_libreoffice(libreoffice, docx_path, output_path)

    raise RuntimeError(
        "Could not convert to PDF. Install Microsoft Word or LibreOffice. "
        "Alternatively: pip install docx2pdf"
    )


def _find_libreoffice() -> str | None:
    """Find LibreOffice executable."""
    candidates = ["libreoffice", "soffice"]
    for name in candidates:
        if shutil.which(name):
            return name

    # Windows paths
    windows_paths = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for p in windows_paths:
        if Path(p).exists():
            return p

    return None


def _convert_via_libreoffice(libreoffice: str, docx_path: Path, output_path: Path) -> Path:
    """Convert using LibreOffice headless CLI."""
    cmd = [
        libreoffice,
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_path.parent),
        str(docx_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"LibreOffice conversion failed: {result.stderr}")

    # LibreOffice outputs to same name with .pdf extension in outdir
    generated = output_path.parent / docx_path.with_suffix(".pdf").name
    if generated != output_path and generated.exists():
        generated.rename(output_path)

    if not output_path.exists():
        raise RuntimeError(f"PDF not found at expected path: {output_path}")

    logger.info("Converted %s → %s (LibreOffice)", docx_path.name, output_path.name)
    return output_path
