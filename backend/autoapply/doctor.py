"""What this computer has and lacks for the program to do its whole job, with the command that fixes each lack.

On a desktop everything is usually there. On a server - no screen, no keyring, a bare system - several things the
program leans on are missing, and each used to show up only when it was needed: on the first application, on the
first PDF. This says it up front:

    autoapply doctor [--deep]          and the same list on the settings page

Each finding: id, level ("ok", "info", "warn", "bad"), title, detail, fix (a command, or ""). "bad" means some
part of the program cannot work; "warn" means it works with a limit that is named.
"""

from __future__ import annotations

from .say import say as T

import os
import shutil
import subprocess
import sys
from typing import Any

from . import config

APT = "sudo apt-get install -y "


def has_screen() -> bool:
    """A display a window can be opened on: always on Windows and macOS, on Linux when a session is there."""
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _finding(id_: str, level: str, title: str, detail: str = "", fix: str = "") -> dict[str, str]:
    return {"id": id_, "level": level, "title": title, "detail": detail, "fix": fix}


def _secrets() -> dict[str, str]:
    from . import secrets

    d = secrets.describe()
    if d.get("problem"):
        return _finding("secrets", "bad", T("server.doctor.theSavedPasswordsAnd"), d["detail"])
    if d["backend"] == "keyring":
        return _finding("secrets", "ok", T("server.doctor.passwordsAndKeysAre2"), d["detail"])
    if d.get("key") == "beside":
        return _finding("secrets", "warn", T("server.doctor.passwordsAndKeysAre3"),
                        T("server.doctor.thisComputerHasNo"),
                        "AUTOAPPLY_MASTER_KEY_FILE=/path/outside/the/data/folder")
    return _finding("secrets", "ok", T("server.doctor.passwordsAndKeysAre"), d["detail"])


def _screen() -> dict[str, str]:
    if has_screen():
        return _finding("screen", "ok", T("server.doctor.thereIsADesktop"))
    if shutil.which("Xvfb"):
        return _finding("screen", "ok", T("server.doctor.noDesktopWindowsThat"))
    return _finding("screen", "warn", T("server.doctor.noDesktopAndNo"),
                    T("server.doctor.signingInAndThe"), APT + "xvfb x11vnc")


def _browser(deep: bool) -> dict[str, str]:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = p.chromium.executable_path
            if not path or not os.path.exists(path):
                return _finding("browser", "bad", T("server.doctor.theProgramsBrowserHas"), "", "uv run playwright install chromium")
            if deep:
                p.chromium.launch().close()
    except Exception as e:  # noqa: BLE001 - whatever stops the browser is the finding
        text = str(e)
        if sys.platform.startswith("linux") and ("shared libraries" in text or "missing dependencies" in text.lower()):
            return _finding("browser", "bad", T("server.doctor.theProgramsBrowserDoes2"), text.strip().splitlines()[0][:300],
                            f"sudo apt-get install -y libatomic1 && sudo {config.ROOT / '.venv' / 'bin' / 'playwright'} install-deps chromium")
        return _finding("browser", "bad", T("server.doctor.theProgramsBrowserDoes"), text.strip().splitlines()[0][:300] if text.strip() else type(e).__name__)
    return _finding("browser", "ok", T("server.doctor.theProgramsBrowserStarts") if deep else T("server.doctor.theProgramsBrowserIs"))


def _converter() -> dict[str, str]:
    from . import convert

    if convert._has_word():
        return _finding("converter", "ok", T("server.doctor.pdfsAreMadeWith"))
    if convert._soffice():
        return _finding("converter", "ok", T("server.doctor.pdfsAreMadeWith2"))
    fix = APT + "libreoffice-writer" if sys.platform.startswith("linux") else "https://www.libreoffice.org/"
    return _finding("converter", "warn", T("server.doctor.nothingHereCanTurn"), T("server.doctor.coverLettersTailoredR"), fix)


def _fonts() -> dict[str, str] | None:
    if not sys.platform.startswith("linux"):
        return None
    if not shutil.which("fc-list"):
        return _finding("fonts", "info", T("server.doctor.theFontsCouldNot"))
    try:
        out = subprocess.run(["fc-list", ":lang=zh", "family"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return _finding("fonts", "info", T("server.doctor.theFontsCouldNot2"))
    if out:
        return _finding("fonts", "ok", T("server.doctor.chineseFontsAreInstalled"))
    return _finding("fonts", "warn", T("server.doctor.noChineseFontIs"), T("server.doctor.chineseTextInDocuments"), APT + "fonts-noto-cjk")


def _disk() -> dict[str, str]:
    free = shutil.disk_usage(config.DATA if config.DATA.exists() else config.ROOT).free
    gb = free / 1e9
    if gb < 2:
        return _finding("disk", "warn", T("server.doctor.onlyGbOfDisk", p0=format(gb, '.1f')), T("server.doctor.runRecordsAndScreenshots"))
    return _finding("disk", "ok", T("server.doctor.gbOfDiskSpace", p0=format(gb, '.0f')))


def _service() -> dict[str, str] | None:
    if not sys.platform.startswith("linux"):
        return None
    from . import service

    st = service.status()
    if not st["systemd"]:
        return _finding("service", "info", T("server.doctor.thereIsNoSystemd"), T("server.doctor.somethingElseHasTo"))
    if st["active"]:
        return _finding("service", "ok", T("server.doctor.runsAsAService") if st["linger"] else T("server.doctor.runsAsAService2"),
                        "" if st["linger"] else T("server.doctor.lingeringIsOffThe"), "" if st["linger"] else f"sudo loginctl enable-linger {st['user']}")
    if st["installed"]:
        return _finding("service", "warn", T("server.doctor.theServiceIsRegistered"), "", "autoapply service start")
    if has_screen():
        return None
    return _finding("service", "info", T("server.doctor.notRegisteredAsA"), T("server.doctor.onceRegisteredItStarts"), "autoapply service install")


def _access() -> dict[str, str] | None:
    from . import access

    c = access.conf()
    if not access.exposed(c):
        return None
    if c.get("https_by_proxy"):
        return _finding("access", "ok", T("server.doctor.reachedFromOtherDevices"))
    return _finding("access", "warn", T("server.doctor.accessFromOtherDevices"), T("server.doctor.theLoginPasswordAnd"))


def run(deep: bool = False) -> list[dict[str, str]]:
    """Every finding. `deep` also starts the browser once (a few seconds)."""
    checks: list[Any] = [_secrets, _screen, lambda: _browser(deep), _converter, _fonts, _disk, _service, _access]
    out = []
    for check in checks:
        try:
            f = check()
        except Exception as e:  # noqa: BLE001 - a check that breaks must not hide the others
            f = _finding(getattr(check, "__name__", "check").lstrip("_"), "info", T("server.doctor.oneCheckCouldNot"), f"{type(e).__name__}: {e}")
        if f:
            out.append(f)
    return out
