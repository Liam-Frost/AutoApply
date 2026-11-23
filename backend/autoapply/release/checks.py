"""The rules of the release data: what `release.py validate` says, and what every other command checks first.

Errors make `validate` fail; warnings are said and do not. `strict` turns the warnings about highlights (no Chinese
summary, no details) into errors.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any

from . import schema, versions
from .model import Fragment, Manifest, Problem, Repo

TYPE_ORDER = ("added", "changed", "deprecated", "removed", "fixed", "security")
MAX_HIGHLIGHTS = 6

_BLOCK = re.compile(r"^\s*(#{1,6}(\s|$)|>|[-*+]\s|\d+[.)]\s|```|~~~|\||={3,}\s*$|-{3,}\s*$)")
_HEADING = re.compile(r"^ {0,3}(#{1,3})\s", re.M)
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_INLINE_LINK = re.compile(r"!?\[(?:[^\[\]\n]|\[[^\]\n]*\])*\]\(\s*(<[^>\n]*>|[^)\s]*)")
_REF_DEF = re.compile(r"^ {0,3}\[[^\]\n]+\]:[ \t]*(<[^>\n]*>|\S+)", re.M)
_AUTOLINK = re.compile(r"<([a-zA-Z][a-zA-Z0-9+.-]*:[^>\s]*)>")
_HTML_ATTR = re.compile(r"""\b(?:href|src)\s*=\s*["']([^"']*)["']""", re.I)
_FENCE = re.compile(r"^ {0,3}(```|~~~).*?(?:^ {0,3}\1[^\n]*$|\Z)", re.M | re.S)
_CODE_SPAN = re.compile(r"(`+)(?:(?!\1).)+?\1", re.S)


def _blank(m: re.Match) -> str:
    """Code, blanked out with its line ends kept: links inside code are not links, and positions stay right."""
    return re.sub(r"[^\n]", " ", m.group(0))


def bad_links(markdown: str) -> list[tuple[int, str]]:
    """[(offset, url)] of every link target in Markdown that is neither http(s) nor relative."""
    text = _CODE_SPAN.sub(_blank, _FENCE.sub(_blank, markdown))
    found: list[tuple[int, str]] = []
    for rx in (_INLINE_LINK, _REF_DEF, _AUTOLINK, _HTML_ATTR):
        for m in rx.finditer(text):
            url = m.group(1).strip()
            if url.startswith("<") and url.endswith(">"):
                url = url[1:-1].strip()
            if not url:
                found.append((m.start(1), "(empty)"))
            elif url.startswith("//") or (_SCHEME.match(url) and not re.match(r"^https?://", url, re.I)):
                found.append((m.start(1), url))
    return sorted(set(found))


def _line_at(text: str, offset: int) -> int:
    return text.count("\n", 0, offset)


def summary_problems(lang: str, text: str) -> list[str]:
    """What is wrong with one summary beyond the schema (which checks one line and the length)."""
    out = []
    if text != text.strip():
        out.append(f"summary.{lang}: starts or ends with a space")
    if _BLOCK.match(text):
        out.append(f"summary.{lang}: Markdown block syntax (a heading, list, quote, table, rule or code fence) is not allowed in a summary")
    if "**" in text:
        out.append(f"summary.{lang}: no bold inside a summary (it is shown bold)")
    return out


class Context:
    """What the checks need from the schemas, read once."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.problems: list[Problem] = []
        self.fragment_schema: dict[str, Any] | None = None
        self.manifest_schema: dict[str, Any] | None = None
        for name in (schema.FRAGMENT, schema.MANIFEST):
            try:
                s = schema.load(self.root, name)
            except schema.SchemaError as e:
                self.problems.append(Problem("error", f"changes/schema/{name}", str(e).split(": ", 1)[-1]))
                continue
            if name == schema.FRAGMENT:
                self.fragment_schema = s
            else:
                self.manifest_schema = s
        if self.fragment_schema is not None:
            try:
                types = schema.enum_of(self.root, "type")
                if set(types) != set(TYPE_ORDER):
                    self.problems.append(Problem("error", f"changes/schema/{schema.FRAGMENT}",
                                                 f"the types ({', '.join(types)}) are not the ones the release notes have sections for "
                                                 f"({', '.join(TYPE_ORDER)}): a new type needs a section in autoapply/release/checks.py TYPE_ORDER"))
                schema.enum_of(self.root, "scope")
            except schema.SchemaError as e:
                self.problems.append(Problem("error", f"changes/schema/{schema.FRAGMENT}", str(e).split(": ", 1)[-1]))


def check_fragment(f: Fragment, ctx: Context, *, strict: bool = False) -> list[Problem]:
    """Everything about one fragment on its own (not whether it was changed after its release)."""
    out: list[Problem] = []

    def err(message: str, at: tuple = (), level: str = "error", line: int | None = None) -> None:
        out.append(Problem(level, f.path, message, line if line is not None else f.line_of(at)))

    if ctx.fragment_schema is not None:
        for at, message in schema.check(ctx.fragment_schema, f.meta):
            err(f"{schema.where(at)}: {message}" if at else message, at)
    id_rx = (ctx.fragment_schema or {}).get("properties", {}).get("id", {}).get("pattern")
    if id_rx and not re.search(id_rx, f.id):
        err(f"the file name {f.id}.md is not a fragment id (YYYY-MM-DD-slug-xxxx): create fragments with `python scripts/release.py change`")
    elif isinstance(f.meta.get("id"), str) and f.meta["id"] != f.id:
        err(f"id {f.meta['id']!r} is not the file name ({f.id})", ("id",))
    if re.match(r"^\d{4}-\d{2}-\d{2}", f.id):
        try:
            _dt.date.fromisoformat(f.id[:10])
        except ValueError:
            err(f"the id starts with {f.id[:10]}, which is not a date", ("id",))
    for lang, text in f.summary.items():
        for message in summary_problems(lang, text):
            err(message, ("summary", lang))
    for offset, url in bad_links(f.details):
        err(f"link {url!r}: links in the details are http(s) or relative", line=f.details_line + _line_at(f.details, offset))
    for m in _HEADING.finditer(_FENCE.sub(_blank, f.details)):
        err(f"a level-{len(m.group(1))} heading in the details: the release notes use those for their sections - use bold or a list",
            level="warning", line=f.details_line + _line_at(f.details, m.start()))
    if f.highlight:
        level = "error" if strict else "warning"
        if "zh" not in f.summary:
            err("a highlight without summary.zh (shown in English to Chinese readers)", ("summary",), level)
        if not f.details:
            err("a highlight without details (the full release notes have nothing more to say)", (), level)
    return out


def check_manifest(m: Manifest, ctx: Context) -> list[Problem]:
    """One manifest on its own."""
    out: list[Problem] = []

    def err(message: str, level: str = "error") -> None:
        out.append(Problem(level, m.path, message))

    if ctx.manifest_schema is not None:
        for at, message in schema.check(ctx.manifest_schema, m.data):
            err(f"{schema.where(at)}: {message}" if at else message)
    if not versions.valid(m.version):
        err(f"the file name {m.version}.json is not a version (X.Y.Z, X.Y.Z-rc.N, X.Y.ZaN, X.Y.ZbN)")
    elif isinstance(m.data.get("version"), str) and m.data["version"] != m.version:
        err(f"version {m.data['version']!r} is not the file name ({m.version})")
    release_date = _date(m.date)
    if m.date and release_date is None:
        err(f"date {m.date!r} is not a date (YYYY-MM-DD)")
    seen: set[str] = set()
    for fid in m.ids:
        if fid in seen:
            err(f"fragments: {fid} is listed twice")
        seen.add(fid)
    last: _dt.date | None = None
    for i, c in enumerate(m.corrections):
        cid, when = c.get("id"), _date(c.get("date"))
        if isinstance(cid, str) and cid not in seen:
            err(f"corrections[{i}]: {cid} is not a fragment of this release")
        if isinstance(c.get("date"), str) and when is None:
            err(f"corrections[{i}].date: {c['date']!r} is not a date")
        elif when and release_date and when < release_date:
            err(f"corrections[{i}].date: {c['date']} is before the release ({m.date})")
        if when and last and when < last:
            err(f"corrections[{i}]: listed after a later correction (they are kept oldest first)", "warning")
        last = when or last
    for name, text in [("intro", m.intro)] + [(f"known_limits[{i}]", t) for i, t in enumerate(m.known_limits)]:
        for _, url in bad_links(text):
            err(f"{name}: link {url!r}: links are http(s) or relative")
    return out


def _date(value: Any) -> _dt.date | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return _dt.date.fromisoformat(value)
    except ValueError:
        return None


def check_repo(repo: Repo, *, release: str | None = None, strict: bool = False) -> list[Problem]:
    ctx = Context(repo.root)
    out: list[Problem] = list(ctx.problems) + list(repo.problems)
    if not (repo.root / "changes").is_dir():
        return out + [Problem("error", "changes", "no changes/ folder: this is not a tree with release data")]

    for f in repo.fragments.values():
        out += check_fragment(f, ctx, strict=strict)

    # manifests: each on its own, then what they say together
    named: dict[str, str] = {}
    for m in sorted(repo.manifests, key=lambda m: m.path):
        out += check_manifest(m, ctx)
    for m in reversed(repo.manifests):            # oldest first: the later manifest is the one in the wrong
        highlights = 0
        for fid in dict.fromkeys(m.ids):
            if fid in named:
                out.append(Problem("error", m.path, f"fragments: {fid} is already released in {named[fid]}: a fragment is in one release"))
                continue
            named[fid] = m.version
            f = repo.fragments.get(fid)
            if f is None:
                if f"changes/fragments/{fid}.md" not in repo.unreadable:
                    out.append(Problem("error", m.path, f"fragments: {fid} is not in changes/fragments/ (a released fragment is never deleted or renamed)"))
                continue
            highlights += f.highlight
            recorded = m.recorded_hash(fid)
            if recorded and recorded != f.sha256:
                out.append(Problem("error", f.path,
                                   f"changed after its release in {m.version} (sha256 {recorded[:12]}... recorded, {f.sha256[:12]}... now): "
                                   f"undo the change, or record it with `python scripts/release.py correct {m.version} {fid} --reason \"...\"`"))
        if highlights > MAX_HIGHLIGHTS:
            out.append(Problem("warning", m.path, f"{highlights} highlights: the app shows at most {MAX_HIGHLIGHTS} when the release is opened"))
    pending_highlights = sum(f.highlight for f in repo.pending)
    if pending_highlights > MAX_HIGHLIGHTS:
        out.append(Problem("warning", "changes/fragments", f"{pending_highlights} pending highlights: a release shows at most {MAX_HIGHLIGHTS}"))

    # versions: one each, in step with their dates, and the copies of the current one agreeing
    by_version: dict[tuple, str] = {}
    ordered: list[tuple[versions.Version, Manifest]] = []
    for m in repo.manifests:
        try:
            v = versions.parse(m.version)
        except ValueError:
            continue
        if v.key in by_version:
            out.append(Problem("error", m.path, f"version {v} is also {by_version[v.key]}"))
        by_version[v.key] = m.path
        ordered.append((v, m))
    ordered.sort(key=lambda x: x[0].key)
    for (v1, m1), (v2, m2) in zip(ordered, ordered[1:]):
        d1, d2 = _date(m1.date), _date(m2.date)
        if d1 and d2 and d2 < d1:
            out.append(Problem("warning", m2.path, f"{v2} is dated {m2.date}, before {v1} ({m1.date})"))
    out += check_versions(repo, newest=ordered[-1][0] if ordered else None)

    if release is not None:
        out += check_release(repo, release)
    return out


def check_versions(repo: Repo, newest: versions.Version | None) -> list[Problem]:
    out: list[Problem] = []
    cps = versions.copies(repo.root)
    authority = cps[0].value
    if authority is None:
        return [Problem("error", versions.PYPROJECT, "no [project] version")]
    for c in cps[1:]:
        if c.value is None:
            out.append(Problem("error", c.file, f"no {c.field}"))
        elif c.value != authority:
            out.append(Problem("error", c.file, f"{c.field} is {c.value}, but pyproject.toml says {authority}: "
                                                f"the version changes with `python scripts/release.py prepare`"))
    try:
        current = versions.parse(authority)
    except ValueError as e:
        return out + [Problem("error", versions.PYPROJECT, str(e))]
    if newest is not None and current < newest:
        out.append(Problem("error", versions.PYPROJECT, f"version {current} is older than the newest release, {newest}"))
    elif newest is not None and current > newest and repo.manifest(str(current)) is None:
        out.append(Problem("warning", versions.PYPROJECT, f"version {current} has no manifest (changes/releases/{current}.json): "
                                                          f"the version changes with `python scripts/release.py prepare`"))
    return out


def check_release(repo: Repo, release: str) -> list[Problem]:
    """What must hold for the release `release` to be published from this tree."""
    out: list[Problem] = []
    name = str(release).strip().removeprefix("v")
    if not versions.valid(name):
        return [Problem("error", "", f"{release!r} is not a version")]
    if repo.manifest(name) is None:
        out.append(Problem("error", f"changes/releases/{name}.json", f"no manifest for {name}: run `python scripts/release.py prepare --version {name} ...`"))
    current = versions.read_pyproject(repo.root)
    if current != name:
        out.append(Problem("error", versions.PYPROJECT, f"version is {current}, not {name}"))
    if repo.pending:
        out.append(Problem("warning", "changes/fragments",
                           f"{len(repo.pending)} fragment(s) are not in any release ({', '.join(f.id for f in repo.pending[:5])}"
                           f"{', ...' if len(repo.pending) > 5 else ''}): this package would show them as not released yet"))
    return out


def errors(problems: list[Problem]) -> list[Problem]:
    return [p for p in problems if p.level == "error"]
