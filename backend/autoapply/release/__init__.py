"""Release data: change fragments and release manifests in changes/, and what is made from them.

    changes/fragments/<id>.md       one change each (YAML front matter + Markdown details), released or pending
    changes/releases/<version>.json one manifest per release: its fragments, in order, with their hashes
    changes/schema/*.schema.json    the schemas (the one source of the type and scope lists)

A fragment named by a manifest is released; every other one is pending. CHANGELOG.md, backend/autoapply/releases.json
and a release's GitHub notes are generated from released fragments only (scripts/release.py). The program reads
releases.json itself and asks `pending_entry()` for what is not released yet. See docs/release-architecture.md.

The program imports this package at run time: it imports nothing heavy, and PyYAML only when a fragment is read.
"""
from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

from . import checks, model, render, schema
from .checks import TYPE_ORDER
from .model import Fragment, Manifest, Problem, Repo

log = logging.getLogger(__name__)

TYPES = TYPE_ORDER  # the types, in the order of the release notes' sections

__all__ = ["TYPES", "TYPE_ORDER", "Fragment", "Manifest", "Problem", "Repo", "scopes", "load", "validate", "app_data",
           "pending_entry", "changelog_md", "release_notes", "suggest_version"]


def _root(root: Path | str | None) -> Path:
    if root is not None:
        return Path(root)
    from .. import config

    return Path(config.ROOT)


def scopes(root: Path | str | None = None) -> list[str]:
    """The scopes a fragment may have, from changes/schema/fragment.schema.json."""
    return schema.enum_of(_root(root), "scope")


def load(root: Path | str | None = None) -> Repo:
    """Every fragment and manifest; what cannot be read is in `.problems`."""
    return model.load(_root(root))


def validate(root: Path | str | None = None, *, release: str | None = None, strict: bool = False) -> list[Problem]:
    """Every problem of the release data (errors and warnings). `release`: also what publishing that version needs."""
    return checks.check_repo(model.load(_root(root)), release=release, strict=strict)


def app_data(root: Path | str | None = None) -> dict[str, Any]:
    """Exactly what backend/autoapply/releases.json holds (released versions, newest first)."""
    return render.app_data(model.load(_root(root)))


def changelog_md(root: Path | str | None = None) -> str:
    return render.changelog(model.load(_root(root)))


def release_notes(version: str, root: Path | str | None = None) -> str:
    """The GitHub release notes of `version`. KeyError when there is no such release."""
    return render.notes(model.load(_root(root)), version)


def suggest_version(root: Path | str | None = None) -> tuple[str, str]:
    """(the next version, why)."""
    from . import ops

    return ops.suggest(model.load(_root(root)))


# --- what is not released yet, for the program ---------------------------------------------------------------------
_cache: dict[str, Any] = {"key": None, "value": None}


def _stamp(root: Path) -> tuple | None:
    """What says whether the pending set may have changed: the names, times and sizes of the files it is read from."""
    out = []
    for sub in ("changes/fragments", "changes/releases", "changes/schema"):
        d = root / sub
        try:
            out.append((sub, tuple(sorted((e.name, e.stat().st_mtime_ns, e.stat().st_size) for e in d.iterdir()))))
        except OSError:
            out.append((sub, None))
    return (str(root), tuple(out))


def pending_entry(root: Path | str | None = None) -> dict[str, Any] | None:
    """An "Unreleased" release entry (the shape of one in releases.json) of the pending fragments; None when there is
    no changes/ folder (a package), nothing pending, PyYAML missing, or the release data cannot be read. A pending
    fragment that is not valid is left out (validate says why). Never raises."""
    try:
        r = _root(root)
        if not (r / "changes" / "fragments").is_dir():
            return None
        key = _stamp(r)
        if _cache["key"] != key:
            _cache["value"] = _pending(r)
            _cache["key"] = key
        return copy.deepcopy(_cache["value"])
    except Exception as e:  # noqa: BLE001 - the page shows the releases without the pending block rather than failing
        log.warning("the pending changes could not be read: %s", e)
        return None


def _pending(root: Path) -> dict[str, Any] | None:
    try:
        import yaml  # noqa: F401
    except ImportError:
        return None
    repo = model.load(root)
    if any(p.path.startswith(model.RELEASES) for p in repo.problems):
        log.warning("a release manifest cannot be read: what is released is not known, so nothing is shown as pending")
        return None
    ctx = checks.Context(root)
    if ctx.fragment_schema is None:
        return None
    frags = []
    for f in repo.pending:
        bad = checks.errors(checks.check_fragment(f, ctx))
        if bad:
            log.warning("%s left out of the pending changes: %s", f.path, bad[0].message)
            continue
        frags.append(f)
    if not frags:
        return None
    return {"version": "Unreleased", "date": "", "title": {}, "intro": "", "known_limits": [], "url": "",
            "changes": render.pending_changes(repo, frags)}
