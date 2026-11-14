"""The interface dictionary, used on the server for text that leaves the program (Telegram notifications).

The templates are written in Chinese; other languages are a dictionary ({"中文": "English"}) kept in
``frontend/src/i18n/<lang>.json`` and applied to finished text. This is the same procedure as the interface's
``frontend/src/i18n/index.js`` (whole entry, then patterns with {0} {1}, then parts joined by punctuation, then
phrases inside longer text), with the same rule at the end: all or nothing. Text that still contains Chinese after
translation is something the user, a website or the AI wrote, and is passed on exactly as it was.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from . import config

CJK = re.compile(r"[一-鿿]")
SEP = re.compile(r"(\s?·\s|；|; |，|, |：|: |（|）| / |、|\s?\|\s)")
PUNCT = {"；": "; ", "，": ", ", "：": ": ", "（": " (", "）": ") ", "、": ", "}
SLOT = re.compile(r"\{(\d+)\}")


class _Dict:
    def __init__(self, d: dict[str, str]) -> None:
        self.d = d
        pats = []
        for k in d:
            if SLOT.search(k):
                rx = re.compile("^" + SLOT.sub(lambda _m: "\x00", re.escape(k).replace(r"\{", "{").replace(r"\}", "}")).replace("\x00", r"([\s\S]*?)") + "$")
                pats.append((len(SLOT.sub("", k)), rx, [int(n) for n in SLOT.findall(k)], d[k]))
        self.patterns = sorted(pats, key=lambda p: -p[0])   # the most specific pattern first
        segs = sorted((k for k in d if not SLOT.search(k) and len(k) >= 4), key=len, reverse=True)
        self.seg = re.compile("|".join(re.escape(k) for k in segs)) if segs else None
        short = sorted((k for k in d if not SLOT.search(k) and len(k) < 4 and CJK.search(k)), key=len, reverse=True)
        self.short = re.compile(r"(^|[^一-鿿])(" + "|".join(re.escape(k) for k in short) + r")(?![一-鿿])") if short else None

    def tr(self, s: str, depth: int = 0) -> str:
        if not s or not CJK.search(s):
            return s
        lead, tail = re.match(r"^\s*", s).group(0), re.search(r"\s*$", s).group(0)
        core = re.sub(r"\s+", " ", s.strip())
        out = self.d.get(core)
        if out is None:
            for _w, rx, order, tpl in self.patterns:
                m = rx.match(core)
                if m:
                    out = SLOT.sub(lambda g: self.tr(m.group(order.index(int(g.group(1))) + 1) or "", depth + 1) if int(g.group(1)) in order else "", tpl)
                    break
        if out is None:
            parts = SEP.split(core)
            if len(parts) > 1 and depth < 3:
                out = "".join((PUNCT.get(x, x) if i % 2 else (self.tr(x, depth + 1) if CJK.search(x) else x)) for i, x in enumerate(parts))
        if out is None or CJK.search(out):
            o = core if out is None else out
            if self.seg:
                o = self.seg.sub(lambda m: self.d[m.group(0)], o)
            if self.short:
                o = self.short.sub(lambda m: m.group(1) + self.d[m.group(2)], o)
            out = o
        if CJK.search(out):   # all or nothing
            return s
        return lead + out + tail


@lru_cache(maxsize=4)
def _load(lang: str) -> _Dict | None:
    p = config.ROOT / "frontend" / "src" / "i18n" / f"{lang}.json"
    try:
        return _Dict(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


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
    """``text`` in the interface language (unchanged for Chinese, for non-strings, and when no dictionary is there)."""
    to = to or lang()
    if to == "zh" or not isinstance(text, str):
        return text
    d = _load(to)
    return d.tr(text) if d else text


def tr_lines(text: str, to: str | None = None) -> str:
    """Multi-line text (a list of reasons, a quoted detail): each line on its own, so one untranslatable line does not hold back the rest."""
    return "\n".join(tr(ln, to) for ln in text.split("\n"))
