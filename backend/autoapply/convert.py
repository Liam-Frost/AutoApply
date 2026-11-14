"""Word document -> PDF, with whatever this computer has.

1. Microsoft Word (Windows): the most faithful layout, and what the files were written in.
2. LibreOffice (Windows / macOS / Linux): headless conversion; close, not always identical.
Nothing else is tried: a converter that changes the layout silently would make "one page" checks meaningless.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import config

SCRIPTS = config.ROOT / "scripts"


class NoConverter(RuntimeError):
    pass


def _soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        if (p := shutil.which(name)):
            return p
    candidates = [r"C:\Program Files\LibreOffice\program\soffice.exe", r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                  "/Applications/LibreOffice.app/Contents/MacOS/soffice", "/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice", "/opt/libreoffice/program/soffice"]
    return next((c for c in candidates if Path(c).exists()), None)


def _has_word() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Word.Application"))
        return True
    except OSError:
        return False


def available() -> dict[str, object]:
    """What can be used here (shown in Settings)."""
    word, lo = _has_word(), _soffice()
    return {"word": word, "libreoffice": bool(lo), "using": "word" if word else "libreoffice" if lo else "", "ok": bool(word or lo)}


def docx_to_pdf(docx: str | Path, *, timeout: int = 180) -> Path:
    """Writes <name>.pdf next to the .docx and returns its path."""
    docx = Path(docx)
    pdf = docx.with_suffix(".pdf")
    pdf.unlink(missing_ok=True)
    err = ""
    if _has_word():
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPTS / "docx_to_pdf.ps1"), "-docx", str(docx)],
                           capture_output=True, text=True, timeout=timeout)
        if pdf.exists():
            return pdf
        err = (r.stderr or r.stdout)[-300:]
    if (lo := _soffice()):
        # its own profile folder, so a LibreOffice window the user has open does not block the conversion
        prof = config.DATA / "tmp" / "lo-profile"
        prof.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([lo, "--headless", f"-env:UserInstallation={prof.as_uri()}", "--convert-to", "pdf", "--outdir", str(docx.parent), str(docx)],
                           capture_output=True, text=True, timeout=timeout, env={**os.environ, "HOME": os.environ.get("HOME", str(prof))})
        if pdf.exists():
            return pdf
        err = (r.stderr or r.stdout)[-300:] or err
    if not _has_word() and not _soffice():
        raise NoConverter("这台电脑上没有 Microsoft Word，也没有 LibreOffice，没法把 Word 文件转成 PDF。装一个免费的 LibreOffice 就可以（libreoffice.org）。")
    raise RuntimeError(f"PDF export failed: {err}")
