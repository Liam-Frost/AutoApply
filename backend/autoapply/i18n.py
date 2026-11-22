"""The interface language on the server: which one the program is set to, the first-run choice of it, and saying a
message (say.Msg) in it where text leaves the program - a notification, a bot's answer, a table to download.

What the program says has a key (say.py, ``frontend/src/locales/server/<lang>.json``). Text without one - what the
applicant, an employer or the AI wrote - is passed on exactly as it was written.
"""

from __future__ import annotations

from typing import Any

from . import config


def first_run_lang() -> None:
    """On the very first start, set the interface language: the one chosen in the installer (it leaves ``data/ui-lang.txt``),
    else the system's - Chinese systems get Chinese, every other language English. An installation that is already in use
    is left alone, and so is a choice the user has made."""
    from . import db
    from .models import Job, Setting

    note = config.DATA / "ui-lang.txt"
    with db.session() as s:
        if s.get(Setting, "ui.lang") is not None:
            return
        fresh = s.query(Job.id).first() is None
    chosen = ""
    try:
        chosen = note.read_text(encoding="ascii").strip().lower() if note.exists() else ""
    except OSError:
        chosen = ""
    if chosen not in ("zh", "en"):
        if not fresh:
            return                      # an installation from before this existed: it stays as it was (Chinese)
        chosen = "zh" if system_lang().startswith("zh") else "en"
    db.set_setting("ui.lang", chosen)


def system_lang() -> str:
    """The system's language tag in lower case ("zh-cn", "en-us", ...), '' when it cannot be told."""
    import locale
    import os
    import sys

    if sys.platform == "win32":
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
                tags = [buf.value]
                lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
                name = locale.windows_locale.get(lid)
                if name:
                    tags.append(name)
                return next((t for t in tags if t.lower().startswith("zh")), tags[0]).replace("_", "-").lower()
        except Exception:  # noqa: BLE001
            pass
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var)
        if v:
            return v.split(".")[0].replace("_", "-").lower()
    try:
        return (locale.getlocale()[0] or "").replace("_", "-").lower()
    except Exception:  # noqa: BLE001
        return ""


def lang() -> str:
    from . import db

    return str(db.get_setting("ui.lang") or "zh")


def tr(text: Any, to: str | None = None) -> Any:
    """``text`` in language ``to`` (the page's when answering one, else the program's): a message is said in it; anything
    else is returned as it is."""
    from .say import Msg, page_lang

    if isinstance(text, Msg):
        return text.in_lang(to or page_lang())
    return text


def tr_lines(text: Any, to: str | None = None) -> Any:
    """Several lines (a list of reasons, a quoted detail): the same as ``tr`` - a message, joined ones too, is said whole."""
    return tr(text, to)
