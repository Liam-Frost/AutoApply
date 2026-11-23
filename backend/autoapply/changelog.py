"""The about page's release history (GET /api/about/changelog): what each version of the program changed.

The released versions are `releases.json` next to this file - generated from `changes/` by `python scripts/release.py
generate`, tracked in git and shipped with every package - read once per change of the file. What is not released yet
is the pending change fragments of a source checkout, which `autoapply.release.pending_entry()` reads with the release
model's own parser; a release package has none. The model is imported only when asked for, and anything wrong there
(not installed, PyYAML missing, a fragment it cannot read) leaves the history without an "Unreleased" entry instead of
without a history. Nothing is parsed out of CHANGELOG.md and nothing is fetched from GitHub: the page works offline.

Each version is a ReleaseEntry as releases.json holds it (docs/release-architecture.md) - { version, date, title: {en,
zh?, fr?}, intro, known_limits, url, changes: [{ id, type, scope, summary: {en, zh?, fr?}, details, highlight }] } -
plus `unreleased`; newest first, the pending entry (when there is one) before the releases.
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
RELEASES = Path(__file__).with_name("releases.json")


def _stat(p: Path) -> tuple[int, int] | None:
    try:
        st = p.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _load(p: Path) -> list[dict[str, Any]]:
    """releases.json's releases, as the file orders them (the generator writes them newest first); [] when the file
    cannot be read or is not in the expected shape - said once in the log, since the result is cached."""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        log.warning("%s not read (%s): the changelog shows no releases", p.name, e)
        return []
    found = data.get("releases") if isinstance(data, dict) else None
    if not isinstance(found, list):
        log.warning("%s has no list of releases: the changelog shows none", p.name)
        return []
    return [dict(r, unreleased=False) for r in found if isinstance(r, dict) and isinstance(r.get("version"), str) and r["version"]]


_cache: dict[str, Any] = {"key": None, "releases": []}


def released(path: Path | None = None) -> list[dict[str, Any]]:
    """The released versions (releases.json, or `path`), newest first; [] without the file. Read again only when the
    file changed (its mtime or size); what is handed out is a copy."""
    p = Path(path) if path is not None else RELEASES
    st = _stat(p)
    if st is None:
        return []
    key = (str(p), st)
    if _cache["key"] != key:
        _cache["releases"] = _load(p)
        _cache["key"] = key
    return copy.deepcopy(_cache["releases"])


def pending() -> dict[str, Any] | None:
    """What is not released yet, as one entry (`unreleased: true`), or None: in a release package, with nothing pending,
    or when the release model is not there or fails (it is said in the log; the history is shown without it)."""
    try:
        from . import release        # (lazily: the runtime needs only this one function of the release tooling)

        entry = release.pending_entry()
    except ImportError as e:
        log.debug("no release model (%s): no unreleased changes shown", e)
        return None
    except Exception as e:  # noqa: BLE001 - the history is shown whatever the pending fragments say
        log.warning("the pending changes were not read (%s): no unreleased changes shown", e)
        return None
    if not isinstance(entry, dict) or not entry.get("changes"):
        return None
    return dict(copy.deepcopy(entry), unreleased=True)


def versions(path: Path | None = None) -> list[dict[str, Any]]:
    """Every version for the about page's timeline: the unreleased entry (when there is one), then the releases."""
    entry = pending()
    return ([entry] if entry else []) + released(path)
