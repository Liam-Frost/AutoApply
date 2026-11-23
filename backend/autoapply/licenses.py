"""The components the program runs on and their licences, as their installed packages say (importlib.metadata).

The list is the program's declared dependencies (pyproject.toml beside the program, else the installed package's own
metadata, else a fixed list of the main ones) and what they in turn depend on, as far as it is installed. Only a name
on that list can be read (`text`): nothing is looked up from a name or a path that comes from outside.
"""
from __future__ import annotations

import re
from importlib import metadata
from typing import Any

from . import config

# the main libraries, for when neither pyproject.toml nor the program's own package metadata can be read
WANTED = ("fastapi", "uvicorn", "sqlalchemy", "pydantic", "httpx", "playwright", "anthropic", "claude-agent-sdk", "pypdf", "python-docx", "keyring",
          "apscheduler", "cryptography", "pillow", "pystray", "websockets", "google-api-python-client", "nodriver", "openai-codex")
_LICENSE_FILE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE)", re.I)
_MAX_TEXT = 256_000          # one licence file is a few kB; a file this large is not one to show


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower().strip()


def _requirement(spec: str) -> tuple[str, set[str], str] | None:
    """`uvicorn[standard]>=0.54; python_version < "4"` -> ("uvicorn", {"standard"}, 'python_version < "4"')."""
    m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?[^;]*(?:;\s*(.*))?$", spec)
    if not m:
        return None
    return m.group(1), {e.strip().lower() for e in (m.group(2) or "").split(",") if e.strip()}, (m.group(3) or "").strip()


def _applies(marker: str, extras: set[str]) -> bool:
    """Does a requirement's marker hold here, for a package asked for with these extras?"""
    if not marker:
        return True
    try:
        from packaging.markers import Marker

        mk = Marker(marker)
        return any(mk.evaluate({"extra": e}) for e in (extras or {""}))
    except Exception:  # noqa: BLE001  (no packaging, or a marker it cannot read: by the extras alone)
        wanted = re.findall(r"extra\s*==\s*['\"]([^'\"]+)['\"]", marker)
        return not wanted or any(canonical(w) in extras for w in wanted)


def _declared() -> list[str]:
    """The program's own requirements: pyproject.toml where it runs from, else its package's metadata."""
    try:
        import tomllib

        project = tomllib.loads((config.ROOT / "pyproject.toml").read_text(encoding="utf-8")).get("project") or {}
        found = list(project.get("dependencies") or [])
        for extra in (project.get("optional-dependencies") or {}).values():
            found += list(extra)          # (an optional one is listed only when it is installed)
        if found:
            return found
    except (OSError, ValueError):
        pass
    try:
        req = metadata.requires("autoapply")
        if req:
            return [r.split(";")[0] for r in req]
    except metadata.PackageNotFoundError:
        pass
    return list(WANTED)


def _license_of(m: Any) -> str:
    """The licence's short name: the expression, else the License field when it is a name and not the whole text, else
    the classifiers."""
    expr = (m.get("License-Expression") or "").strip()
    if expr:
        return expr
    field = (m.get("License") or "").strip()
    if field and "\n" not in field and len(field) <= 80:
        return field
    named = [c.split("::")[-1].strip() for c in (m.get_all("Classifier") or []) if c.startswith("License ::")]
    named = [n for n in named if n not in ("OSI Approved",)]
    if named:
        return " / ".join(dict.fromkeys(named))
    return field.splitlines()[0][:80] if field else ""


def _homepage(m: Any) -> str:
    urls = {}
    for entry in m.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        urls[label.strip().lower()] = url.strip()
    for key in ("homepage", "home", "source", "source code", "repository", "documentation"):
        if urls.get(key, "").startswith(("https://", "http://")):
            return urls[key]
    home = (m.get("Home-page") or "").strip()
    return home if home.startswith(("https://", "http://")) else ""


_walked: list[tuple[metadata.Distribution, bool]] | None = None


def _walk() -> list[tuple[metadata.Distribution, bool]]:
    """The installed distributions of the program's requirements and theirs, each once: (distribution, direct?). Read
    once per process: what is installed changes only with an update, and an update restarts the program."""
    global _walked
    if _walked is None:
        _walked = _read_installed()
    return _walked


def _read_installed() -> list[tuple[metadata.Distribution, bool]]:
    seen: dict[str, tuple[metadata.Distribution, bool]] = {}
    todo: list[tuple[str, set[str], bool]] = []
    for spec in _declared():
        r = _requirement(spec)
        if r and _applies(r[2], set()):
            todo.append((r[0], r[1], True))
    while todo:
        name, extras, direct = todo.pop(0)
        key = canonical(name)
        if key in seen or key == "autoapply":
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        seen[key] = (dist, direct)
        for spec in dist.requires or []:
            r = _requirement(spec)
            if r and _applies(r[2], extras):
                todo.append((r[0], r[1], False))
    return list(seen.values())


def components() -> list[dict[str, Any]]:
    """Every component, sorted by name: { name, version, license, direct, summary, homepage }."""
    out = []
    for dist, direct in _walk():
        m = dist.metadata
        out.append({"name": (m.get("Name") or "").strip(), "version": dist.version or "", "license": _license_of(m), "direct": direct,
                    "summary": (m.get("Summary") or "").strip(), "homepage": _homepage(m)})
    return sorted((c for c in out if c["name"]), key=lambda c: canonical(c["name"]))


def text(name: str) -> dict[str, Any] | None:
    """One component's licence as its package carries it: { name, version, license, text, file, files }. `text` is ""
    when the package carries no licence file and no licence text; None when `name` is not one of the components."""
    key = canonical(name or "")
    found = next(((d, direct) for d, direct in _walk() if canonical(d.metadata.get("Name") or "") == key), None)
    if found is None:
        return None
    dist, _ = found
    m = dist.metadata
    parts: list[tuple[str, str]] = []
    for f in dist.files or []:
        if not _LICENSE_FILE.match(f.name):
            continue
        # the package's own licence files, not those of what it vendors deep inside (they are named in the text if at all)
        top = f.parts[0]
        if not (top.endswith(".dist-info") or len(f.parts) <= 2):
            continue
        try:
            if f.size is not None and int(f.size) > _MAX_TEXT:
                continue
            body = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if body.strip() and len(body) <= _MAX_TEXT:
            parts.append((str(f).replace("\\", "/"), body.strip()))
    field = (m.get("License") or "").strip()
    if not parts and "\n" in field:          # the whole licence written into the metadata
        parts.append(("", field))
    files = [p for p, _ in parts if p]
    body = parts[0][1] if len(parts) == 1 else "\n\n".join(f"── {p or 'METADATA'} ──\n\n{t}" for p, t in parts)
    return {"name": (m.get("Name") or "").strip() or key, "version": dist.version or "", "license": _license_of(m), "text": body, "file": files[0] if files else "", "files": files}
