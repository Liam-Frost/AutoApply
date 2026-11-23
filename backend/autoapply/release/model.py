"""Fragments and manifests as files: reading them, strictly, with the file and the line of what is wrong.

A fragment is `changes/fragments/<id>.md`: YAML front matter between two `---` lines (read with PyYAML's safe loader,
a key given twice is an error), then the details in Markdown. A manifest is `changes/releases/<version>.json`. Reading
does not judge the content (`validate` does, against the schemas); it only refuses what cannot be read at all.

PyYAML is imported when a fragment is read, not when this module is: the program imports the package at run time and
must start without it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

FRAGMENTS = "changes/fragments"
RELEASES = "changes/releases"
KEEP = {".gitkeep"}  # files a folder may hold that are not fragments or manifests
FIRST_LINE = 2  # the front matter's first line in the file (after the opening ---)


@dataclass(frozen=True)
class Problem:
    level: str      # "error" | "warning"
    path: str       # relative to the root, with / (or "" for the tree as a whole)
    message: str
    line: int | None = None

    def __str__(self) -> str:
        where = self.path + (f":{self.line}" if self.line else "")
        return f"{where}: {self.level}: {self.message}" if where else f"{self.level}: {self.message}"


class ReadError(Exception):
    def __init__(self, path: str, line: int | None, message: str):
        super().__init__(f"{path}{':' + str(line) if line else ''}: {message}")
        self.path, self.line, self.message = path, line, message


def content_hash(data: bytes) -> str:
    """sha256 of a file's bytes with CRLF read as LF (a checkout with Windows line ends is the same text)."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def rel(root: Path, p: Path) -> str:
    try:
        return p.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return p.as_posix()


# --- fragments ---------------------------------------------------------------------------------------------------------
@dataclass
class Fragment:
    id: str                       # the file name without .md (the front matter's `id` must equal it)
    path: str                     # relative to the root
    meta: dict[str, Any]          # the front matter as read
    details: str                  # the Markdown body, blank lines around it removed
    sha256: str
    lines: dict[tuple, int] = field(default_factory=dict)  # where each field is: ("summary", "en") -> line in the file
    details_line: int = 0         # the line `details` starts on

    @property
    def type(self) -> str:
        v = self.meta.get("type")
        return v if isinstance(v, str) else ""

    @property
    def scope(self) -> str:
        v = self.meta.get("scope")
        return v if isinstance(v, str) else ""

    @property
    def summary(self) -> dict[str, str]:
        v = self.meta.get("summary")
        return {k: s for k, s in v.items() if isinstance(k, str) and isinstance(s, str)} if isinstance(v, dict) else {}

    @property
    def highlight(self) -> bool:
        return self.meta.get("highlight") is True

    @property
    def bump(self) -> str | None:
        v = self.meta.get("bump")
        return v if isinstance(v, str) else None

    @property
    def pr(self) -> list[int]:
        v = self.meta.get("pr")
        items = v if isinstance(v, list) else [v]
        return [x for x in items if isinstance(x, int) and not isinstance(x, bool)]

    def line_of(self, at: tuple) -> int | None:
        """The line of the field at `at`, or of the nearest enclosing one."""
        while at:
            if at in self.lines:
                return self.lines[at]
            at = at[:-1]
        return self.lines.get((), None)


@lru_cache(maxsize=1)
def _yaml_loader():
    import yaml

    class Loader(yaml.SafeLoader):
        """The safe loader, refusing a key given twice (PyYAML would keep the last one without a word)."""

    def mapping(loader, node, deep=False):
        seen: dict[Any, int] = {}
        for key_node, _ in node.value:
            key = loader.construct_object(key_node, deep=deep)
            try:
                hash(key)
            except TypeError:
                raise yaml.constructor.ConstructorError(None, None, "a key that is not a plain value", key_node.start_mark)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while reading a mapping", node.start_mark, f"the key {key!r} is given twice (first on line {seen[key] + FIRST_LINE})", key_node.start_mark)
            seen[key] = key_node.start_mark.line
        return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)

    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return yaml, Loader


def _lines(node: Any, offset: int, at: tuple = (), out: dict[tuple, int] | None = None) -> dict[tuple, int]:
    """Where each key of a composed YAML node is, as file lines."""
    import yaml

    out = {} if out is None else out
    if isinstance(node, yaml.MappingNode):
        for k, v in node.value:
            key = k.value if isinstance(k, yaml.ScalarNode) else str(k.start_mark)
            out[at + (key,)] = k.start_mark.line + offset
            _lines(v, offset, at + (key,), out)
    elif isinstance(node, yaml.SequenceNode):
        for i, v in enumerate(node.value):
            out[at + (i,)] = v.start_mark.line + offset
            _lines(v, offset, at + (i,), out)
    return out


def split_front_matter(text: str, path: str) -> tuple[str, int, str, int]:
    """(front matter, its first line, body, the body's first line) of a fragment's text (LF line ends)."""
    if text.startswith("\ufeff"):
        raise ReadError(path, 1, "the file starts with a byte order mark: save it as UTF-8 without one")
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        raise ReadError(path, 1, "a fragment starts with a line '---' (YAML front matter, then '---', then the details)")
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return "\n".join(lines[1:i]) + "\n", 2, "\n".join(lines[i + 1:]), i + 2
    raise ReadError(path, 1, "the front matter is not closed: no second '---' line")


def body_text(body: str) -> tuple[str, int]:
    """The details: the body without the blank lines around it and without trailing spaces at its end; and how many
    lines were taken off its top."""
    lines = body.split("\n")
    skipped = 0
    while lines and not lines[0].strip():
        lines.pop(0)
        skipped += 1
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).rstrip(), skipped


def parse_fragment(data: bytes, path: str) -> Fragment:
    """A fragment from the bytes of its file. ReadError (with the line) when it cannot be read."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        line = data[:e.start].count(b"\n") + 1
        raise ReadError(path, line, "not UTF-8 text") from e
    text = text.replace("\r\n", "\n")
    front, first, body, body_line = split_front_matter(text, path)
    yaml, Loader = _yaml_loader()
    loader = Loader(front)
    try:
        node = loader.get_single_node()
        meta = loader.construct_document(node) if node is not None else None
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None) or getattr(e, "context_mark", None)
        problem = getattr(e, "problem", None) or str(e)
        context = getattr(e, "context", None)
        msg = f"YAML: {problem}" + (f" ({context})" if context and context != "while reading a mapping" else "")
        raise ReadError(path, (mark.line + first) if mark else first, msg) from e
    finally:
        loader.dispose()
    if not isinstance(meta, dict):
        raise ReadError(path, first, "the front matter is not a mapping of fields (id: ..., type: ..., ...)")
    stem = Path(path).name
    stem = stem[:-3] if stem.endswith(".md") else stem
    details, skipped = body_text(body)
    return Fragment(id=stem, path=path, meta=meta, details=details, sha256=content_hash(data),
                    lines=_lines(node, first) | {(): first}, details_line=body_line + skipped)


def read_fragment(root: Path, p: Path) -> Fragment:
    return parse_fragment(p.read_bytes(), rel(root, p))


# --- manifests ---------------------------------------------------------------------------------------------------------
@dataclass
class Manifest:
    version: str            # the file name without .json (the manifest's `version` must equal it)
    path: str
    data: dict[str, Any]

    @property
    def date(self) -> str:
        v = self.data.get("date")
        return v if isinstance(v, str) else ""

    @property
    def title(self) -> dict[str, str]:
        v = self.data.get("title")
        return {k: s for k, s in v.items() if isinstance(s, str)} if isinstance(v, dict) else {}

    @property
    def intro(self) -> str:
        v = self.data.get("intro")
        return v if isinstance(v, str) else ""

    @property
    def known_limits(self) -> list[str]:
        v = self.data.get("known_limits")
        return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []

    @property
    def entries(self) -> list[dict[str, Any]]:
        v = self.data.get("fragments")
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []

    @property
    def ids(self) -> list[str]:
        return [x["id"] for x in self.entries if isinstance(x.get("id"), str)]

    @property
    def corrections(self) -> list[dict[str, Any]]:
        v = self.data.get("corrections")
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []

    def recorded_hash(self, fid: str) -> str | None:
        """The hash the fragment must have now: its latest correction's, else the one recorded at release."""
        for c in reversed(self.corrections):
            if c.get("id") == fid and isinstance(c.get("sha256"), str):
                return c["sha256"]
        for e in self.entries:
            if e.get("id") == fid and isinstance(e.get("sha256"), str):
                return e["sha256"]
        return None


def _pairs(path: str):
    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in pairs:
            if k in out:
                raise ReadError(path, None, f"the key {k!r} is given twice in one object")
            out[k] = v
        return out
    return hook


def parse_manifest(data: bytes, path: str) -> Manifest:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ReadError(path, data[:e.start].count(b"\n") + 1, "not UTF-8 text") from e
    if text.startswith("\ufeff"):
        raise ReadError(path, 1, "the file starts with a byte order mark: save it as UTF-8 without one")
    try:
        value = json.loads(text, object_pairs_hook=_pairs(path))
    except json.JSONDecodeError as e:
        raise ReadError(path, e.lineno, f"JSON: {e.msg} (column {e.colno})") from e
    if not isinstance(value, dict):
        raise ReadError(path, 1, "a manifest is a JSON object")
    name = Path(path).name
    return Manifest(version=name[:-5] if name.endswith(".json") else name, path=path, data=value)


def dump_manifest(data: dict[str, Any]) -> str:
    """The one way a manifest is written: 2-space indent, UTF-8 as it is, the fields in the schema's order, LF."""
    order = ["version", "date", "title", "intro", "known_limits", "fragments", "corrections"]
    ordered = {k: data[k] for k in order if k in data} | {k: v for k, v in data.items() if k not in order}
    return json.dumps(ordered, ensure_ascii=False, indent=2) + "\n"


# --- the tree ------------------------------------------------------------------------------------------------------------
@dataclass
class Repo:
    root: Path
    fragments: dict[str, Fragment]            # by id (file name), every fragment that could be read
    manifests: list[Manifest]                 # newest first (by version; unreadable versions last, by name)
    problems: list[Problem]                   # what could not be read
    unreadable: set[str] = field(default_factory=set)  # paths of fragments / manifests that could not be read

    @property
    def released(self) -> dict[str, str]:
        """{fragment id: the version whose manifest names it} (the newest, should one be named twice)."""
        out: dict[str, str] = {}
        for m in reversed(self.manifests):
            for fid in m.ids:
                out[fid] = m.version
        return out

    @property
    def pending(self) -> list[Fragment]:
        """Every fragment no manifest names, by id (the date it was written, then its slug)."""
        released = self.released
        return [f for fid, f in sorted(self.fragments.items()) if fid not in released]

    def manifest(self, version: str) -> Manifest | None:
        v = str(version).strip().removeprefix("v")
        return next((m for m in self.manifests if m.version == v), None)


def version_key(name: str) -> tuple:
    from . import versions

    try:
        return (1,) + versions.parse(name).key
    except ValueError:
        return (0, name)


def load(root: Path) -> Repo:
    """Every fragment and manifest of the tree at `root`. What cannot be read is a problem, not an exception."""
    root = Path(root)
    problems: list[Problem] = []
    unreadable: set[str] = set()
    fragments: dict[str, Fragment] = {}
    fdir = root / FRAGMENTS
    if fdir.is_dir():
        for p in sorted(fdir.iterdir()):
            r = rel(root, p)
            if p.name in KEEP:
                continue
            if p.is_dir():
                problems.append(Problem("error", r, "a folder inside changes/fragments/: fragments are files directly in it"))
                continue
            if not p.name.endswith(".md"):
                problems.append(Problem("error", r, "not a fragment: fragments are changes/fragments/<id>.md"))
                continue
            try:
                fragments[p.name[:-3]] = read_fragment(root, p)
            except ReadError as e:
                problems.append(Problem("error", e.path, e.message, e.line))
                unreadable.add(r)
            except OSError as e:
                problems.append(Problem("error", r, f"cannot be read ({e.strerror or e})"))
                unreadable.add(r)
    manifests: list[Manifest] = []
    mdir = root / RELEASES
    if mdir.is_dir():
        for p in sorted(mdir.iterdir()):
            r = rel(root, p)
            if p.name in KEEP:
                continue
            if p.is_dir() or not p.name.endswith(".json"):
                problems.append(Problem("error", r, "not a manifest: manifests are changes/releases/<version>.json"))
                continue
            try:
                manifests.append(parse_manifest(p.read_bytes(), r))
            except ReadError as e:
                problems.append(Problem("error", e.path, e.message, e.line))
                unreadable.add(r)
            except OSError as e:
                problems.append(Problem("error", r, f"cannot be read ({e.strerror or e})"))
                unreadable.add(r)
    manifests.sort(key=lambda m: version_key(m.version), reverse=True)
    return Repo(root=root, fragments=fragments, manifests=manifests, problems=problems, unreadable=unreadable)
