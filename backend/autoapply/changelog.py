"""CHANGELOG.md, parsed for the about page's version timeline.

The file is Keep a Changelog: `## [x.y.z] - date` per version (newest first), `### Added / Changed / Fixed / ...` per
kind of change, bullets under them, and the versions' links as reference links at the bottom. Some versions have
headings of their own ("### The analysis page"): those are kind `other` with their title. Nothing is made up - a
version without a written date has none, a version without a link reference has no link - and an empty section, or an
`[Unreleased]` with nothing in it, is left out.

The text of an item, a summary or a section's paragraphs is markdown as written, with the lines the file wraps at its
width joined (a soft line break in markdown is a space): what reads it renders each paragraph as one, and sub-bullets
stay on lines of their own.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from . import config

KINDS = {
    "added": "added", "new": "added", "features": "added", "new features": "added",
    "changed": "changed", "changes": "changed", "improved": "changed", "improvements": "changed",
    "fixed": "fixed", "fixes": "fixed", "bug fixes": "fixed", "bugfixes": "fixed",
    "security": "security",
    "removed": "removed",
    "deprecated": "deprecated",
    "breaking": "breaking", "breaking changes": "breaking", "breaking change": "breaking",
    "known limits": "known", "known limitations": "known", "known issues": "known",
}

_VERSION = re.compile(r"^##\s+\[([^\]]+)\](.*)$")
_H2 = re.compile(r"^##\s")
_H3 = re.compile(r"^###\s+(.+?)\s*#*\s*$")
_REF = re.compile(r"^\s{0,3}\[([^\]]+)\]:\s*<?(\S+?)>?(?:\s+.*)?$")
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_BULLET = re.compile(r"^([-*+]|\d+[.)])(\s+)(.*)$")
_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_FENCE = re.compile(r"^\s*(```|~~~)")
_BLOCK = re.compile(r"^\s*(#{1,6}\s|>|\||(?:-{3,}|\*{3,})\s*$)")       # a line that is a block of its own: heading, quote, table row, rule


def kind_of(title: str) -> str:
    return KINDS.get(re.sub(r"\s+", " ", title.strip().lower()), "other")


def unwrap(lines: list[str]) -> str:
    """Markdown lines with the wrapping of the file taken out: a line that continues a paragraph or a list item is joined
    to it with a space. List items, blank lines, headings, quotes, tables, rules and fenced code keep their lines; a hard
    break (two spaces or a backslash at the end) keeps its line end."""
    out: list[str] = []
    fenced = False
    joinable = False      # may the next line be joined to the last one of `out`?
    for raw in lines:
        line = raw.rstrip("\n")
        if _FENCE.match(line):
            fenced = not fenced
            out.append(line.rstrip())
            joinable = False
            continue
        if fenced:
            out.append(line)
            continue
        if not line.strip():
            if out and out[-1] != "":
                out.append("")
            joinable = False
            continue
        hard = line.endswith("  ") or line.rstrip().endswith("\\")
        text = line.rstrip()
        if _LIST.match(line) or _BLOCK.match(line) or not joinable:
            out.append(text)
        else:
            out[-1] = out[-1].rstrip("\\").rstrip() + " " + text.strip()
        joinable = not hard and not _BLOCK.match(line)
    while out and out[-1] == "":
        out.pop()
    while out and out[0] == "":
        out.pop(0)
    return "\n".join(out)


def _section(title: str, lines: list[str]) -> dict[str, Any]:
    """One `###` section: its bullets (each with what is indented under it), and the paragraphs that are not bullets."""
    items: list[list[str]] = []
    text: list[str] = []
    cur: list[str] | None = None
    indent = 0
    blank = False
    for line in lines:
        if not line.strip():
            blank = True
            if cur is not None:
                cur.append("")
            elif text:
                text.append("")
            continue
        m = _BULLET.match(line)
        if m:                                             # a bullet at the left edge starts an item
            cur = [m.group(3)]
            indent = len(m.group(1)) + len(m.group(2))
            items.append(cur)
        elif cur is not None and (line[:1].isspace() or not blank):
            # indented under the item (a wrapped line, a sub-bullet, a paragraph of its own), or a lazy continuation
            lead = len(line) - len(line.lstrip(" "))
            cur.append(line[min(lead, indent):])
        else:                                             # a paragraph of the section, not a bullet
            if cur is not None and text and text[-1] != "":
                text.append("")                           # (one paragraph before the bullets, one after: two paragraphs)
            cur = None
            text.append(line)
        blank = False
    return {"kind": kind_of(title), "title": title.strip(), "items": [md for md in (unwrap(i) for i in items) if md], "text": unwrap(text)}


def parse(source: str) -> list[dict[str, Any]]:
    """Every `## [x]` heading of a changelog's text, in the order of the file (newest first, as the file has it)."""
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    refs: dict[str, str] = {}
    found: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    part: list[str] = []          # the lines of the summary (before the first ###) or of the section being read
    title: str | None = None      # that section's heading, None while in the summary
    fenced = False

    def close_part() -> None:
        if cur is None:
            return
        if title is None:
            cur["summary"] = unwrap(part)
        else:
            sec = _section(title, part)
            if sec["items"] or sec["text"]:
                cur["sections"].append(sec)

    for line in lines:
        if _FENCE.match(line):
            fenced = not fenced
        if not fenced:
            ref = _REF.match(line)
            if ref and not line.startswith("    "):
                refs.setdefault(ref.group(1).strip().lower(), ref.group(2))
                continue
            v = _VERSION.match(line)
            if v or _H2.match(line):
                close_part()
                cur, part, title = None, [], None
                if v:
                    name, rest = v.group(1).strip(), v.group(2)
                    inline = re.match(r"\((\S+?)\)", rest)           # ## [1.2.0](https://…) - date
                    date = _DATE.search(rest)
                    cur = {"version": name, "date": date.group(1) if date else "", "unreleased": name.lower() == "unreleased", "summary": "", "sections": [],
                           "url": inline.group(1) if inline else ""}
                    found.append(cur)
                continue
            h = _H3.match(line)
            if h and cur is not None:
                close_part()
                part, title = [], h.group(1)
                continue
        if cur is not None:
            part.append(line)
    close_part()
    for v in found:
        v["url"] = refs.get(v["version"].lower(), "") or v["url"]
    # an [Unreleased] that says nothing is not a version to show
    return [v for v in found if not (v["unreleased"] and not v["summary"] and not v["sections"])]


_cache: dict[str, Any] = {"key": None, "versions": []}


def versions(path: Path | None = None) -> list[dict[str, Any]]:
    """The versions of the program's CHANGELOG.md (the package carries it), newest first; [] when there is none. Read
    again only when the file changed."""
    p = Path(path) if path is not None else config.ROOT / "CHANGELOG.md"
    try:
        st = p.stat()
    except OSError:
        return []
    key = (str(p), st.st_mtime_ns, st.st_size)
    if _cache["key"] != key:
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        _cache["versions"] = parse(text)
        _cache["key"] = key
    return copy.deepcopy(_cache["versions"])
