"""What the commands of scripts/release.py do: write a fragment, suggest the version, prepare a release, regenerate the
artifacts, record a correction, check that a release can be published. No printing here (cli.py prints)."""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import checks, render, versions
from .model import FRAGMENTS, RELEASES, Fragment, Problem, Repo, dump_manifest, load, parse_fragment, parse_manifest, version_key


class OpError(Exception):
    """A command that cannot go on: the message says why; `code` is the exit code (1 problems, 2 usage)."""

    def __init__(self, message: str, code: int = 1, problems: list[Problem] | None = None):
        super().__init__(message)
        self.code = code
        self.problems = problems or []


def today() -> str:
    return _dt.date.today().isoformat()


def write_text(path: Path, text: str) -> None:
    """Write a whole file at once (a temporary file next to it, then renamed): a reader never sees half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.encode("utf-8"))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# --- a new fragment ----------------------------------------------------------------------------------------------------
_STOP = {"a", "an", "the", "of", "to", "and", "or", "in", "on", "for", "with", "is", "are", "be", "by", "at", "from", "as",
         "its", "it", "no", "not", "now", "when", "that", "this"}


def slug_of(text: str, words: int = 4) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    found = re.findall(r"[a-z0-9]+", plain)
    kept = [w for w in found if w not in _STOP] or found
    return "-".join(kept[:words]) or "change"


def fragment_text(meta: dict[str, Any], details: str) -> str:
    """The one way the tool writes a fragment. Strings are double-quoted (JSON escapes are YAML escapes)."""
    q = lambda s: json.dumps(s, ensure_ascii=False)  # noqa: E731
    lines = ["---", f"id: {meta['id']}", f"type: {meta['type']}", f"scope: {meta['scope']}", "summary:"]
    lines += [f"  {lang}: {q(meta['summary'][lang])}" for lang in render.LANGS if meta["summary"].get(lang)]
    if meta.get("highlight"):
        lines.append("highlight: true")
    if meta.get("bump"):
        lines.append(f"bump: {meta['bump']}")
    pr = meta.get("pr") or []
    if pr:
        lines.append(f"pr: {pr[0]}" if len(pr) == 1 else f"pr: [{', '.join(str(n) for n in pr)}]")
    lines.append("---")
    text = "\n".join(lines) + "\n"
    details = "\n".join(line.rstrip() for line in details.replace("\r\n", "\n").strip("\n").split("\n")).strip("\n")
    return text + ("\n" + details + "\n" if details.strip() else "")


def new_fragment(root: Path, *, type: str, scope: str, summary: dict[str, str], details: str = "", highlight: bool = False,
                 bump: str | None = None, pr: list[int] | None = None, slug: str | None = None, date: str | None = None) -> tuple[Path, list[Problem]]:
    """Write a new fragment and return its path (and its warnings). The file is created exclusively, so two people or
    agents writing one at the same moment get two files; OpError (with the problems) when it would not be valid."""
    root = Path(root)
    if slug is not None and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+){0,4}", slug):
        raise OpError(f"--slug {slug!r}: 1-5 words of a-z and 0-9, joined by -", 2)
    slug = slug or slug_of(summary.get("en", ""))
    date = date or today()
    summary = {k: v.strip() for k, v in summary.items() if v and v.strip()}
    ctx = checks.Context(root)
    if ctx.fragment_schema is None:
        raise OpError("the fragment schema cannot be read", 1, ctx.problems)
    folder = root / FRAGMENTS
    folder.mkdir(parents=True, exist_ok=True)
    for _ in range(50):
        fid = f"{date}-{slug}-{secrets.token_hex(2)}"
        meta = {"id": fid, "type": type, "scope": scope, "summary": summary, "highlight": highlight, "bump": bump, "pr": pr or []}
        text = fragment_text(meta, details)
        path = folder / f"{fid}.md"
        f = parse_fragment(text.encode("utf-8"), f"{FRAGMENTS}/{fid}.md")
        found = checks.check_fragment(f, ctx)
        if checks.errors(found):
            raise OpError("the fragment would not be valid; nothing was written", 1, found)
        try:
            with open(path, "x", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        except FileExistsError:
            continue
        return path, found
    raise OpError("could not find a free file name", 1)


# --- versions ------------------------------------------------------------------------------------------------------------
def git(root: Path, *args: str, timeout: float = 60) -> subprocess.CompletedProcess | None:
    """A git command in `root`; None when git is not there or `root` is not the top of a git work tree."""
    exe = shutil.which("git")
    if not exe:
        return None
    try:
        top = subprocess.run([exe, "rev-parse", "--show-toplevel"], cwd=root, capture_output=True, text=True, timeout=timeout)
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != Path(root).resolve():
            return None
        return subprocess.run([exe, *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def tags(root: Path) -> set[str] | None:
    """The version tags of the local repository, without the v ("2.0.2"); None without git."""
    r = git(root, "tag", "--list", "v*")
    if r is None or r.returncode != 0:
        return None
    return {t.strip()[1:] for t in r.stdout.splitlines() if t.strip()}


def _versions_of(names) -> list[versions.Version]:
    out = []
    for n in names:
        try:
            out.append(versions.parse(n))
        except ValueError:
            pass
    return out


def suggest(repo: Repo) -> tuple[str, str]:
    """(the next version, why): the newer of pyproject's version and the newest manifest, bumped by the largest bump a
    pending fragment declares (patch when none does)."""
    candidates: list[tuple[versions.Version, str]] = []
    current = versions.read_pyproject(repo.root)
    if current and versions.valid(current):
        candidates.append((versions.parse(current), "pyproject.toml"))
    released = _versions_of(m.version for m in repo.manifests)
    if released:
        candidates.append((max(released), "the newest manifest"))
    if not candidates:
        raise OpError("no version to start from: pyproject.toml has no valid [project] version", 1)
    base = max(v for v, _ in candidates)
    sources = " and ".join(s for v, s in candidates if v == base)
    declared = [f for f in repo.pending if f.bump in versions.LEVELS]
    level = versions.largest([f.bump for f in declared])
    by = [f.id for f in declared if f.bump == level]
    why = f"{base} ({sources}) + {level}"
    why += f", declared by {', '.join(by[:3])}{' and more' if len(by) > 3 else ''}" if by else ", the default (no pending fragment declares a bump)"
    return str(versions.bump(base, level)), why


# --- prepare -------------------------------------------------------------------------------------------------------------
@dataclass
class Plan:
    version: str
    why: str
    date: str
    manifest_path: str
    manifest: dict[str, Any]
    files: dict[str, str]                       # relative path -> the whole new text
    version_changes: list[tuple[str, str, str, str]] = field(default_factory=list)  # (file, field, old, new)
    notes: list[str] = field(default_factory=list)
    repo_after: Repo | None = None

    @property
    def section(self) -> str:
        """The release's section of the new CHANGELOG.md."""
        text = self.files[render.CHANGELOG]
        start = text.find(f"## [{self.version}]")
        end = text.find("\n## [", start + 1)
        refs = text.find("\n[", start + 1)
        end = min(x for x in (end, refs, len(text)) if x != -1)
        return text[start:end].rstrip() + "\n"

    @property
    def entry(self) -> dict[str, Any]:
        data = json.loads(self.files[render.APP_DATA])
        return next(r for r in data["releases"] if r["version"] == self.version)


def order_for_release(frags: list[Fragment]) -> list[Fragment]:
    """The order a new manifest lists its fragments in: by type, the highlights first, then by id."""
    rank = {t: i for i, t in enumerate(checks.TYPE_ORDER)}
    return sorted(frags, key=lambda f: (rank.get(f.type, len(rank)), not f.highlight, f.id))


def plan_prepare(root: Path, *, version: str | None = None, date: str | None = None, title: dict[str, str] | None = None,
                 intro: str = "", known_limits: list[str] | None = None, force_bump: str | None = None,
                 known_tags: set[str] | None = None, placeholder_title: bool = False) -> Plan:
    """Everything `prepare` would write, computed and checked; nothing is written."""
    root = Path(root)
    repo = load(root)
    found = checks.check_repo(repo)
    if checks.errors(found):
        raise OpError("the release data has errors: fix them first (python scripts/release.py validate)", 1, checks.errors(found))
    pending = repo.pending
    if not pending:
        raise OpError("nothing to release: there are no pending fragments in changes/fragments/", 1)

    suggested, why = suggest(repo)
    notes: list[str] = []
    released = _versions_of([m.version for m in repo.manifests] + sorted(known_tags or ()))
    last = max(released) if released else None
    current = versions.read_pyproject(root)
    cur = versions.parse(current) if current and versions.valid(current) else None
    if version is None:
        chosen = versions.parse(suggested)
    else:
        try:
            chosen = versions.parse(version)
        except ValueError as e:
            raise OpError(str(e), 2) from e
        why = f"given (--version); suggested was {suggested}: {why}"
    name = str(chosen)
    if repo.manifest(name) is not None:
        raise OpError(f"{name} exists already (changes/releases/{name}.json): choose a later version", 1)
    if known_tags and name in known_tags:
        raise OpError(f"the tag v{name} exists already: choose a later version", 1)
    if last is not None and not chosen > last:
        raise OpError(f"{name} is not after the newest release {last}: versions never go back", 1)
    if cur is not None and chosen < cur:
        raise OpError(f"{name} is before pyproject.toml's version {cur}: versions never go back", 1)
    level = versions.largest([f.bump for f in pending if f.bump])
    reference = last or cur
    if reference is not None and not versions.satisfies(chosen, reference, level):
        by = ", ".join(f.id for f in pending if f.bump == level)
        if not force_bump:
            raise OpError(f"{name} is not a {level} release after {reference}, which {by} declare(s): "
                          f"use {versions.bump(reference, level)}, or --force-bump \"<reason>\" to release it as {name} anyway", 1)
        notes.append(f"--force-bump: released as {name} although {by} declare(s) {level}. Reason: {force_bump}")
    if chosen.pre and chosen.pre[0] in ("a", "b"):
        notes.append(f"{name}: npm reads X.Y.ZaN / bN as no version at all; X.Y.Z-rc.N works everywhere")

    when = date or today()
    if checks._date(when) is None:
        raise OpError(f"--date {when!r}: YYYY-MM-DD", 2)
    title = {k: v.strip() for k, v in (title or {}).items() if v and v.strip()}
    if "en" not in title:
        if not placeholder_title:
            raise OpError("--title-en is needed: the short name of the release (shown in the collapsed timeline)", 2)
        title["en"] = "(the title, given with --title-en)"
    manifest = {"version": name, "date": when, "title": {k: title[k] for k in render.LANGS if k in title},
                "intro": intro.replace("\r\n", "\n").strip(), "known_limits": [x.strip() for x in known_limits or [] if x.strip()],
                "fragments": [{"id": f.id, "sha256": f.sha256} for f in order_for_release(pending)], "corrections": []}
    mpath = f"{RELEASES}/{name}.json"
    m_text = dump_manifest(manifest)
    m = parse_manifest(m_text.encode("utf-8"), mpath)
    bad = checks.errors(checks.check_manifest(m, checks.Context(root)))
    if bad:
        raise OpError("the manifest would not be valid", 1, bad)

    after = Repo(root=root, fragments=repo.fragments, manifests=sorted(repo.manifests + [m], key=lambda x: version_key(x.version), reverse=True),
                 problems=[], unreadable=set())
    try:
        texts = versions.new_texts(root, name)
    except (versions.EditError, OSError, ValueError) as e:
        raise OpError(str(e), 1) from e
    changes = [(c.file, c.field, c.value or "", name) for c in versions.copies(root)]
    files = {mpath: m_text, **texts, render.CHANGELOG: render.changelog(after), render.APP_DATA: render.app_data_text(after)}
    return Plan(version=name, why=why, date=when, manifest_path=mpath, manifest=manifest, files=files, version_changes=changes,
                notes=notes, repo_after=after)


def apply(root: Path, files: dict[str, str]) -> list[str]:
    """Write the files that differ from what is there; the ones written, in order."""
    written = []
    for relpath, text in files.items():
        p = Path(root) / relpath
        if p.exists() and p.read_bytes() == text.encode("utf-8"):
            continue
        write_text(p, text)
        written.append(relpath)
    return written


# --- generate ------------------------------------------------------------------------------------------------------------
def artifacts(repo: Repo) -> dict[str, str]:
    return {render.CHANGELOG: render.changelog(repo), render.APP_DATA: render.app_data_text(repo)}


def stale(root: Path, texts: dict[str, str]) -> list[tuple[str, str]]:
    """[(file, how it differs)] of the generated files that are not what would be generated (CRLF read as LF)."""
    out = []
    for relpath, text in texts.items():
        p = Path(root) / relpath
        if not p.exists():
            out.append((relpath, "missing"))
            continue
        on_disk = p.read_bytes().replace(b"\r\n", b"\n")
        if on_disk != text.encode("utf-8"):
            out.append((relpath, "differs from what the release data gives"))
    return out


def generate(root: Path, *, check: bool = False) -> tuple[list[str], list[tuple[str, str]], list[Problem]]:
    """(files written, files stale, problems). With errors in the data nothing is generated or compared."""
    repo = load(root)
    found = checks.check_repo(repo)
    if checks.errors(found):
        return [], [], found
    texts = artifacts(repo)
    if check:
        return [], stale(root, texts), found
    return apply(root, texts), [], found


# --- correct -------------------------------------------------------------------------------------------------------------
def correct(root: Path, version: str, fid: str, reason: str, *, date: str | None = None) -> tuple[str, dict[str, Any]]:
    """Record that a released fragment's text was changed on purpose: a correction with its new hash in the manifest.
    Returns (the manifest's path, the correction)."""
    root = Path(root)
    reason = (reason or "").strip()
    if not reason or "\n" in reason:
        raise OpError("--reason is needed: one line saying why the released text was changed", 2)
    repo = load(root)
    m = repo.manifest(version)
    if m is None:
        raise OpError(f"no release {version} (changes/releases/{version}.json)", 1)
    if fid not in m.ids:
        raise OpError(f"{fid} is not a fragment of {m.version}", 1)
    f = repo.fragments.get(fid)
    if f is None:
        raise OpError(f"{FRAGMENTS}/{fid}.md cannot be read: a released fragment is corrected, never deleted", 1,
                      [p for p in repo.problems if fid in p.path])
    bad = checks.errors(checks.check_fragment(f, checks.Context(root)))
    if bad:
        raise OpError("the corrected fragment is not valid", 1, bad)
    if m.recorded_hash(fid) == f.sha256:
        raise OpError(f"nothing to correct: {fid} is as {m.version} recorded it (edit the fragment first)", 1)
    when = date or today()
    first = checks._date(m.date)
    if checks._date(when) is None or (first and checks._date(when) < first):
        raise OpError(f"--date {when!r}: a date (YYYY-MM-DD) not before the release ({m.date})", 2)
    data = json.loads(json.dumps(m.data))
    entry = {"id": fid, "date": when, "reason": reason, "sha256": f.sha256}
    data.setdefault("corrections", []).append(entry)
    write_text(root / m.path, dump_manifest(data))
    return m.path, entry


# --- publish -------------------------------------------------------------------------------------------------------------
@dataclass
class Check:
    ok: bool
    label: str
    detail: str = ""


def publish_commands(version: str) -> list[list[str]]:
    return [["git", "tag", "-a", f"v{version}", "-m", f"AutoApply {version}"], ["git", "push", "origin", f"v{version}"]]


def publish_checks(root: Path, version: str, *, fetch: bool = True) -> list[Check]:
    """Everything that must be true before the tag is made. Reads only (a fetch of origin updates what is known of it)."""
    root = Path(root)
    out: list[Check] = []
    name = str(version).strip().removeprefix("v")
    if git(root, "rev-parse", "HEAD") is None:
        return [Check(False, "a git repository", f"{root} is not the top of a git work tree (or git is missing)")]
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    b = branch.stdout.strip() if branch and branch.returncode == 0 else "?"
    out.append(Check(b == "master", "on branch master", f"on {b}"))
    st = git(root, "status", "--porcelain", "--untracked-files=normal")
    dirty = [line for line in (st.stdout.splitlines() if st else []) if line.strip()]
    out.append(Check(st is not None and st.returncode == 0 and not dirty, "a clean working tree",
                     f"{len(dirty)} changed or untracked file(s): " + ", ".join(line[3:] for line in dirty[:5]) if dirty else ""))
    remote = git(root, "remote", "get-url", "origin")
    if remote is None or remote.returncode != 0:
        out.append(Check(False, "up to date with origin", "no remote named origin"))
        out.append(Check(False, f"no tag v{name} on origin", "no remote named origin"))
    else:
        failed = ""
        if fetch:
            f = git(root, "fetch", "--quiet", "origin", "master", timeout=120)
            if f is None or f.returncode != 0:
                failed = "git fetch origin master failed: " + ((f.stderr or "").strip()[:200] if f else "")
        if failed:
            out.append(Check(False, "up to date with origin", failed))
        else:
            head = git(root, "rev-parse", "HEAD")
            up = git(root, "rev-parse", "origin/master")
            same = head and up and head.returncode == 0 and up.returncode == 0 and head.stdout.strip() == up.stdout.strip()
            out.append(Check(bool(same), "up to date with origin", "" if same else "HEAD is not origin/master"))
        ls = git(root, "ls-remote", "--tags", "origin", f"refs/tags/v{name}", timeout=120)
        out.append(Check(bool(ls and ls.returncode == 0 and not ls.stdout.strip()), f"no tag v{name} on origin",
                         "" if ls and ls.returncode == 0 and not ls.stdout.strip() else ("it exists" if ls and ls.returncode == 0 else "origin could not be asked")))
    local = git(root, "rev-parse", "-q", "--verify", f"refs/tags/v{name}")
    out.append(Check(bool(local) and local.returncode != 0, f"no tag v{name} here", "it exists" if local and local.returncode == 0 else ""))
    repo = load(root)
    out.append(Check(repo.manifest(name) is not None, f"the manifest changes/releases/{name}.json", "" if repo.manifest(name) else "missing"))
    cps = versions.copies(root)
    wrong = [f"{c.file} {c.field} = {c.value}" for c in cps if c.value != name]
    out.append(Check(not wrong, f"every copy of the version is {name}", "; ".join(wrong)))
    found = checks.check_repo(repo, release=name)
    errs = checks.errors(found)
    out.append(Check(not errs, f"validate --release {name}", "; ".join(str(p) for p in errs[:3]) + (" ..." if len(errs) > 3 else "")))
    warns = [p for p in found if p.level == "warning"]
    if warns:
        out.append(Check(True, "warnings", "; ".join(str(p) for p in warns[:3]) + (" ..." if len(warns) > 3 else "")))
    if not errs:
        st2 = stale(root, artifacts(repo))
        out.append(Check(not st2, "generate --check", "; ".join(f"{f}: {why}" for f, why in st2)))
    return out
