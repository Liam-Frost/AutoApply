"""CHANGELOG.md, parsed for the about page's version timeline.

The file is Keep a Changelog: `## [x.y.z] - date` per version (newest first), `### Added / Changed / Fixed / ...` per
kind of change, bullets under them, and the versions' links as reference links at the bottom. Some versions have
headings of their own ("### The analysis page"): those are kind `other` with their title. Nothing is made up - a
version without a written date has none, a version without a link reference has no link - and an empty section, or an
`[Unreleased]` with nothing in it, is left out.

The text of an item, a summary or a section's paragraphs is markdown as written, with the lines the file wraps at its
width joined (a soft line break in markdown is a space): what reads it renders each paragraph as one, and sub-bullets
stay on lines of their own.

The page shows a release by its short title and a few highlights, and the full notes on request. Those are written by
hand, in every language of the interface, in `highlights.json` next to this file (the package carries it): each
version gets `title` ({en, zh, fr}) and `highlights` ([{kind, title, text?}], each text {en, zh, fr}). A version the
file has no entry for yet (a release before it is updated) gets its highlights from what its notes name - the bold
lead of each bullet, in English, marked `derived` - and no title. Nothing is summarised or cut here.
"""
from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any

from . import config

log = logging.getLogger(__name__)
HIGHLIGHTS = Path(__file__).with_name("highlights.json")
# the kinds a highlight can be (a derived one has its section's kind, which can also be one of the others)
HIGHLIGHT_KINDS = ("added", "changed", "fixed", "security", "removed", "known")
# what a reader of the release looks for first, when the highlights are taken from the notes
DERIVED_ORDER = ("added", "changed", "fixed", "security", "breaking", "removed", "deprecated", "known", "other")
DERIVED_MAX = 6

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


def norm(version: str) -> str:
    """"v2.0.2" and "2.0.2" are one version; "unreleased" is "Unreleased"."""
    return re.sub(r"^v(?=\d)", "", str(version or "").strip(), flags=re.I).lower()


def _words(value: Any) -> dict[str, str]:
    """A text in several languages ({en, zh, fr}), keeping only what is text."""
    if not isinstance(value, dict):
        return {}
    return {k: v.strip() for k, v in value.items() if isinstance(k, str) and isinstance(v, str) and v.strip()}


def read_highlights(data: Any) -> dict[str, dict[str, Any]]:
    """highlights.json's entries by version (normalised): {title, highlights}. What is not in the expected shape is left
    out (the file-honesty test says where); a highlight without a title is not one."""
    out: dict[str, dict[str, Any]] = {}
    entries = data.get("versions") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return out
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        items = []
        for h in entry.get("highlights") or []:
            if not isinstance(h, dict) or not _words(h.get("title")):
                continue
            item = {"kind": h["kind"] if isinstance(h.get("kind"), str) and h["kind"] else "other", "title": _words(h.get("title"))}
            if _words(h.get("text")):
                item["text"] = _words(h.get("text"))
            items.append(item)
        out[norm(name)] = {"title": _words(entry.get("title")), "highlights": items}
    return out


_LEAD = re.compile(r"^\*\*(.+?)\*\*")


def lead_of(item: str) -> str:
    """The bold lead of a bullet ("**Calendar** (sidebar) ..." -> "Calendar"), as plain words; "" when it has none."""
    m = _LEAD.match(item.strip())
    if not m:
        return ""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", m.group(1))          # a link: its words
    text = re.sub(r"[`*_]", "", text)
    return re.sub(r"\s+", " ", text).strip().rstrip(".:;,").strip()


def derive(version: dict[str, Any]) -> list[dict[str, Any]]:
    """What the notes of a version name, when highlights.json has nothing for it: the bold lead of each bullet, with its
    section's kind, taken in turns from the kinds a reader looks for first (added, changed, fixed, ...) so that one long
    section does not fill them all; at most DERIVED_MAX, English only (the notes are), marked `derived`."""
    by_kind: dict[str, list[str]] = {}
    for s in version.get("sections") or []:
        for item in s.get("items") or []:
            lead = lead_of(item)
            if lead and lead not in by_kind.setdefault(s["kind"], []):
                by_kind[s["kind"]].append(lead)
    queues = [(k, list(by_kind[k])) for k in DERIVED_ORDER if by_kind.get(k)]
    picked: list[tuple[str, str]] = []
    while queues and len(picked) < DERIVED_MAX:
        for k, q in queues:
            if q and len(picked) < DERIVED_MAX:
                picked.append((k, q.pop(0)))
        queues = [(k, q) for k, q in queues if q]
    # (shown grouped by kind: one kind's leads together, in the order of the notes)
    order = {k: i for i, k in enumerate(DERIVED_ORDER)}
    picked.sort(key=lambda p: order.get(p[0], len(order)))
    return [{"kind": k, "title": {"en": t}, "derived": True} for k, t in picked]


def merge(found: list[dict[str, Any]], hl: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Each version with `title` and `highlights` added: highlights.json's, or what its notes name."""
    for v in found:
        entry = hl.get(norm(v["version"])) or {}
        v["title"] = dict(entry.get("title") or {})
        v["highlights"] = copy.deepcopy(entry.get("highlights") or []) or derive(v)
    return found


def _stat(p: Path) -> tuple[int, int] | None:
    try:
        st = p.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


_cache: dict[str, Any] = {"key": None, "versions": []}


def versions(path: Path | None = None, highlights: Path | None = None) -> list[dict[str, Any]]:
    """The versions of the program's CHANGELOG.md (the package carries it), newest first, each with its title and
    highlights from highlights.json; [] when there is no changelog. Read again only when one of the files changed."""
    p = Path(path) if path is not None else config.ROOT / "CHANGELOG.md"
    h = Path(highlights) if highlights is not None else HIGHLIGHTS
    st = _stat(p)
    if st is None:
        return []
    key = (str(p), st, str(h), _stat(h))
    if _cache["key"] != key:
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        data: Any = {}
        if key[3] is not None:
            try:
                data = json.loads(h.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError) as e:
                log.warning("highlights.json not read (%s): the highlights come from the notes", e)
        _cache["versions"] = merge(parse(text), read_highlights(data))
        _cache["key"] = key
    return copy.deepcopy(_cache["versions"])
