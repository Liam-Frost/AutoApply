"""Version numbers: their form, their order, the next one, and the copies of the current one in the repository.

The version practice of the project: every release bumps the patch number unless a fragment declares more (`bump:
minor` / `bump: major`). Pre-releases are X.Y.Z-rc.N, X.Y.ZaN, X.Y.ZbN (what the release workflow treats as one).

`pyproject.toml` is the authority; the copies that must say the same are `frontend/package.json` (`version`),
`frontend/package-lock.json` (`version` and `packages[""].version`) and `uv.lock` (the project's own entry: the
in-program update runs `uv sync --locked`, which refuses a lock whose project version differs). `set_version` changes
exactly those fields and nothing else in the files, and checks that by reading them back.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PATTERN = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-rc\.(0|[1-9]\d*)|a(0|[1-9]\d*)|b(0|[1-9]\d*))?$"
_VERSION = re.compile(PATTERN)
LEVELS = ("patch", "minor", "major")  # the order of their size


@dataclass(frozen=True, order=False)
class Version:
    major: int
    minor: int
    patch: int
    pre: tuple[str, int] | None = None  # ("a" | "b" | "rc", n)

    @property
    def core(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    @property
    def key(self) -> tuple:
        # a pre-release comes before its release; a < b < rc
        return self.core + ((0, ("a", "b", "rc").index(self.pre[0]), self.pre[1]) if self.pre else (1, 0, 0))

    def __lt__(self, other: Version) -> bool:
        return self.key < other.key

    def __le__(self, other: Version) -> bool:
        return self.key <= other.key

    def __gt__(self, other: Version) -> bool:
        return self.key > other.key

    def __ge__(self, other: Version) -> bool:
        return self.key >= other.key

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if not self.pre:
            return base
        kind, n = self.pre
        return f"{base}-rc.{n}" if kind == "rc" else f"{base}{kind}{n}"


def parse(text: str) -> Version:
    """"2.0.3", "v2.0.3", "2.1.0-rc.1", "2.1.0a1" -> Version; ValueError for anything else."""
    m = _VERSION.match(str(text or "").strip().removeprefix("v"))
    if not m:
        raise ValueError(f"not a version: {text!r} (X.Y.Z, X.Y.Z-rc.N, X.Y.ZaN or X.Y.ZbN)")
    major, minor, patch, rc, a, b = m.groups()
    pre = ("rc", int(rc)) if rc is not None else ("a", int(a)) if a is not None else ("b", int(b)) if b is not None else None
    return Version(int(major), int(minor), int(patch), pre)


def valid(text: str) -> bool:
    try:
        parse(text)
    except ValueError:
        return False
    return True


def bump(v: Version, level: str) -> Version:
    """The next version at `level`. A pre-release's next patch is its own release (2.1.0-rc.1 -> 2.1.0)."""
    if level not in LEVELS:
        raise ValueError(f"not a bump level: {level!r}")
    if v.pre:
        if level == "patch" or (level == "minor" and v.patch == 0) or (level == "major" and v.minor == v.patch == 0):
            return Version(*v.core)
    if level == "major":
        return Version(v.major + 1, 0, 0)
    if level == "minor":
        return Version(v.major, v.minor + 1, 0)
    return Version(v.major, v.minor, v.patch + 1)


def satisfies(new: Version, base: Version, level: str) -> bool:
    """Is `new` at least a `level` bump over `base`? (Its pre-releases count: 2.1.0-rc.1 is a minor over 2.0.2.)"""
    return new > base and new.core >= bump(base, level).core


def largest(levels: list[str]) -> str:
    return max((x for x in levels if x in LEVELS), key=LEVELS.index, default="patch")


# --- the copies in the repository -------------------------------------------------------------------------------------
PYPROJECT = "pyproject.toml"
PACKAGE = "frontend/package.json"
LOCK = "frontend/package-lock.json"
UVLOCK = "uv.lock"


@dataclass(frozen=True)
class Copy:
    file: str        # relative to the root
    field: str       # how a person names it
    value: str | None  # None: the file or the field is not there


def _toml(path: Path) -> dict[str, Any]:
    import tomllib

    return tomllib.loads(path.read_text(encoding="utf-8"))


def read_pyproject(root: Path) -> str | None:
    try:
        v = _toml(Path(root) / PYPROJECT).get("project", {}).get("version")
    except (OSError, ValueError):
        return None
    return v if isinstance(v, str) else None


def _uv_project(data: dict[str, Any]) -> dict[str, Any] | None:
    for p in data.get("package") or []:
        src = p.get("source") or {}
        if isinstance(p, dict) and (src.get("editable") == "." or src.get("virtual") == "."):
            return p
    return None


def copies(root: Path) -> list[Copy]:
    """Every copy of the version, the authority first. A file that does not exist is left out (uv.lock and the
    frontend's files are optional for a tree that has none); a file that exists without its field gives value None."""
    root = Path(root)
    out = [Copy(PYPROJECT, "[project] version", read_pyproject(root))]
    for rel, fields in ((PACKAGE, (("version",),)), (LOCK, (("version",), ("packages", "", "version")))):
        p = root / rel
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        for path in fields:
            node: Any = data
            for k in path:
                node = node.get(k) if isinstance(node, dict) else None
            out.append(Copy(rel, _json_name(path), node if isinstance(node, str) else None))
    p = root / UVLOCK
    if p.exists():
        try:
            entry = _uv_project(_toml(p))
        except (OSError, ValueError):
            entry = None
        out.append(Copy(UVLOCK, "the project's [[package]] version", entry.get("version") if entry else None))
    return out


def _json_name(path: tuple[str, ...]) -> str:
    return "".join(f'["{k}"]' if not k or not k.isidentifier() else (f".{k}" if i else k) for i, k in enumerate(path))


# --- changing them, and only them --------------------------------------------------------------------------------------
class EditError(Exception):
    """A version field could not be changed without touching anything else."""


def _set_pyproject(text: str, new: str) -> str:
    lines = text.split("\n")
    table = None
    for i, line in enumerate(lines):
        head = re.match(r"^\s*\[([^\[\]]+)\]\s*(?:#.*)?$", line)
        if head or re.match(r"^\s*\[\[", line):
            table = head.group(1).strip() if head else None
            continue
        m = re.match(r'^(\s*version\s*=\s*")([^"\\]*)(".*)$', line)
        if table == "project" and m:
            lines[i] = m.group(1) + new + m.group(3)
            return "\n".join(lines)
    raise EditError(f"{PYPROJECT}: no version = \"...\" line in [project]")


def _json_string_span(text: str, path: tuple[str, ...]) -> tuple[int, int]:
    """Where the JSON string at `path` is in `text` (inside its quotes): the file is not rewritten, only that value."""
    n = len(text)

    def ws(i: int) -> int:
        while i < n and text[i] in " \t\r\n":
            i += 1
        return i

    def string_end(i: int) -> int:  # i at the opening quote; the index after the closing one
        i += 1
        while i < n:
            if text[i] == "\\":
                i += 2
                continue
            if text[i] == '"':
                return i + 1
            i += 1
        raise EditError("unterminated string")

    def value_end(i: int) -> int:
        if text[i] == '"':
            return string_end(i)
        if text[i] in "{[":
            depth = 0
            while i < n:
                c = text[i]
                if c == '"':
                    i = string_end(i)
                    continue
                if c in "{[":
                    depth += 1
                elif c in "}]":
                    depth -= 1
                    if depth == 0:
                        return i + 1
                i += 1
            raise EditError("unterminated container")
        j = i
        while j < n and text[j] not in ",}] \t\r\n":
            j += 1
        return j

    i = ws(0)
    for key in path:
        if i >= n or text[i] != "{":
            raise EditError(f"no object where {_json_name(path)} should be")
        i = ws(i + 1)
        while True:
            if i >= n or text[i] == "}":
                raise EditError(f"no field {_json_name(path)}")
            k_end = string_end(i)
            name = json.loads(text[i:k_end])
            i = ws(k_end)
            if text[i] != ":":
                raise EditError("malformed JSON")
            i = ws(i + 1)
            if name == key:
                break
            i = ws(value_end(i))
            if i < n and text[i] == ",":
                i = ws(i + 1)
    if text[i] != '"':
        raise EditError(f"{_json_name(path)} is not a string")
    return i + 1, string_end(i) - 1


def _set_json(text: str, rel: str, paths: tuple[tuple[str, ...], ...], new: str) -> str:
    try:
        expected = json.loads(text)
    except ValueError as e:
        raise EditError(f"{rel}: not JSON ({e})") from e
    expected = copy.deepcopy(expected)
    for path in paths:
        node = expected
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = new
        start, end = _json_string_span(text, path)
        text = text[:start] + json.dumps(new)[1:-1] + text[end:]
    if json.loads(text) != expected:
        raise EditError(f"{rel}: changing the version would change more than the version")
    return text


def _set_uvlock(text: str, new: str) -> str:
    before = _toml_text(text)
    entry = _uv_project(before)
    if entry is None:
        raise EditError(f"{UVLOCK}: no entry for the project itself")
    pat = re.compile(r'(\[\[package\]\]\r?\nname = "' + re.escape(entry["name"]) + r'"\r?\nversion = ")([^"]*)(")')
    found = list(pat.finditer(text))
    if len(found) != 1:
        raise EditError(f"{UVLOCK}: the project's entry is not in the expected form")
    m = found[0]
    text = text[:m.start(2)] + new + text[m.end(2):]
    after = _toml_text(text)
    _uv_project(before)["version"] = new
    if after != before:
        raise EditError(f"{UVLOCK}: changing the version would change more than the version")
    return text


def _toml_text(text: str) -> dict[str, Any]:
    import tomllib

    return tomllib.loads(text)


def new_texts(root: Path, new: str) -> dict[str, str]:
    """The files with the version set to `new` ({relative path: text}); nothing is written. Each file's line ends and
    everything else are kept; EditError when a file cannot be changed that way."""
    root = Path(root)
    out: dict[str, str] = {}
    p = root / PYPROJECT
    text = p.read_bytes().decode("utf-8")
    changed = _set_pyproject(text, new)
    data = _toml_text(text)
    data.setdefault("project", {})["version"] = new
    if _toml_text(changed) != data:
        raise EditError(f"{PYPROJECT}: changing the version would change more than the version")
    out[PYPROJECT] = changed
    for rel, paths in ((PACKAGE, (("version",),)), (LOCK, (("version",), ("packages", "", "version")))):
        p = root / rel
        if p.exists():
            out[rel] = _set_json(p.read_bytes().decode("utf-8"), rel, paths, new)
    p = root / UVLOCK
    if p.exists():
        out[UVLOCK] = _set_uvlock(p.read_bytes().decode("utf-8"), new)
    return out
