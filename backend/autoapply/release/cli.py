"""python scripts/release.py <command> - the release data's commands. Exit codes: 0 ok, 1 problems found, 2 usage.

    change     write a new change fragment (interactive on a terminal; all options for agents and CI)
    validate   check fragments, manifests, versions [--release X] [--strict]
    status     what is pending, the next version, the releases and whether each is published
    prepare    make a release: its manifest, the version in every file, the generated files [--dry-run]
    generate   write CHANGELOG.md and backend/autoapply/releases.json [--check]
    notes X    print the GitHub release notes of X
    correct    record a change to a released fragment's text
    publish X  check everything and print the tag commands (--yes: run them, after typing the version)

docs/release-workflow.md says when and how to use each.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import checks, model, ops, render, schema, versions
from .model import Problem


class Usage(Exception):
    """A usage error: exit code 2."""


def _say(*lines: str) -> None:
    for line in lines:
        print(line)


def _annotate(p: Problem) -> str:
    """A problem as a GitHub Actions annotation (shown on the pull request's files)."""
    msg = p.message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    props = []
    if p.path:
        props.append("file=" + p.path.replace("%", "%25").replace(",", "%2C").replace(":", "%3A"))
    if p.line:
        props.append(f"line={p.line}")
    return f"::{p.level} {','.join(props)}::{msg}" if props else f"::{p.level}::{msg}"


def _report(problems: list[Problem]) -> None:
    gha = os.environ.get("GITHUB_ACTIONS") == "true"
    for p in problems:
        print(_annotate(p) if gha else str(p))


def _tty() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _ask(prompt: str, *, choices: list[str] | None = None, default: str = "", required: bool = False) -> str:
    while True:
        hint = f" [{default}]" if default else ""
        try:
            answer = input(f"{prompt}{hint}: ").strip()
        except EOFError as e:
            raise Usage("no answer (end of input)") from e
        answer = answer or default
        if choices and answer and answer not in choices:
            print(f"  one of: {', '.join(choices)}")
            continue
        if required and not answer:
            print("  needed")
            continue
        return answer


# --- change --------------------------------------------------------------------------------------------------------------
def cmd_change(a: argparse.Namespace, root: Path) -> int:
    types = schema.enum_of(root, "type")
    scopes = schema.enum_of(root, "scope")
    missing = [o for o, v in (("--type", a.type), ("--scope", a.scope), ("--summary-en", a.summary_en)) if not v]
    for opt, value, allowed in (("--type", a.type, types), ("--scope", a.scope, scopes)):
        if value and value not in allowed:
            raise Usage(f"{opt} {value!r}: one of {', '.join(allowed)}")
    if a.details is not None and a.details_file:
        raise Usage("--details and --details-file: give one")
    details = a.details or ""
    if a.details_file:
        try:
            details = Path(a.details_file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise Usage(f"--details-file {a.details_file}: {e}") from e
    pr = []
    for item in a.pr or []:
        for part in str(item).replace(",", " ").split():
            if not part.lstrip("#").isdigit() or int(part.lstrip("#")) < 1:
                raise Usage(f"--pr {item!r}: a pull request number")
            pr.append(int(part.lstrip("#")))
    interactive = bool(missing) and _tty()
    if missing and not interactive:
        raise Usage(f"missing {', '.join(missing)} (or run it at a terminal to be asked)")
    if interactive:
        print("A new change fragment. What a user notices; see docs/release-workflow.md.")
        a.type = a.type or _ask(f"Type ({', '.join(types)})", choices=types, required=True)
        a.scope = a.scope or _ask(f"Scope ({', '.join(scopes)})", choices=scopes, required=True)
        a.summary_en = a.summary_en or _ask("Summary in English (one line, at most 120 characters)", required=True)
        a.summary_zh = a.summary_zh or _ask("Summary in Simplified Chinese (optional)")
        a.summary_fr = a.summary_fr or _ask("Summary in French (optional)")
        if not a.highlight:
            a.highlight = _ask("One of the release's main changes? (y/N)", choices=["y", "n", "Y", "N"], default="n").lower() == "y"
        if not a.bump:
            a.bump = _ask("Version impact beyond patch (minor / major, empty for none)", choices=["", "minor", "major", "patch"]) or None
        if not details:
            details = _ask("Details (Markdown, optional - edit the file for more than a line)")
    summary = {"en": a.summary_en, "zh": a.summary_zh or "", "fr": a.summary_fr or ""}
    path, found = ops.new_fragment(root, type=a.type, scope=a.scope, summary=summary, details=details, highlight=a.highlight,
                                   bump=a.bump, pr=pr, slug=a.slug)
    _report(found)
    print(model.rel(root, path))
    return 0


# --- validate / status ---------------------------------------------------------------------------------------------------
def cmd_validate(a: argparse.Namespace, root: Path) -> int:
    repo = model.load(root)
    found = checks.check_repo(repo, release=a.release, strict=a.strict)
    _report(found)
    errs = len(checks.errors(found))
    warns = len(found) - errs
    what = f"{len(repo.fragments)} fragments ({len(repo.pending)} pending), {len(repo.manifests)} releases"
    if a.release:
        what += f"; release {a.release}"
    print(f"{'FAILED' if errs else 'ok'}: {what}; {errs} error(s), {warns} warning(s)")
    return 1 if errs else 0


def cmd_status(a: argparse.Namespace, root: Path) -> int:
    repo = model.load(root)
    pending = repo.pending
    print(f"Pending: {len(pending)} fragment(s)")
    for t in checks.TYPE_ORDER + ("",):
        items = [f for f in pending if (f.type if f.type in checks.TYPE_ORDER else "") == t]
        if not items:
            continue
        print(f"  {render.SECTIONS.get(t, 'Not valid')}")
        for f in items:
            flags = " ".join(x for x in (f"[{f.scope}]", "highlight" if f.highlight else "", f"bump:{f.bump}" if f.bump else "") if x)
            print(f"    {f.id}  {flags}  {f.summary.get('en', '')}")
    try:
        version, why = ops.suggest(repo)
        print(f"Next version: {version} ({why})")
    except ops.OpError as e:
        print(f"Next version: unknown ({e})")
    known = ops.tags(root)
    print(f"Releases: {len(repo.manifests)}" + ("" if known is not None else " (no git here: whether each is published is not known)"))
    for m in repo.manifests:
        state = "" if known is None else ("published (tag v%s)" % m.version if m.version in known else "candidate (no tag yet)")
        print(f"  {m.version:<12} {m.date:<10}  {len(m.ids):>3} change(s)  {state}".rstrip())
    if known is not None:
        orphans = sorted((t for t in known if versions.valid(t) and repo.manifest(t) is None), key=lambda t: versions.parse(t).key, reverse=True)
        if orphans:
            print(f"  tags without a manifest: {', '.join('v' + t for t in orphans)}")
    found = checks.check_repo(repo)
    errs = len(checks.errors(found))
    print(f"Validation: {errs} error(s), {len(found) - errs} warning(s)" + (" - python scripts/release.py validate" if found else ""))
    return 0


# --- prepare -------------------------------------------------------------------------------------------------------------
def cmd_prepare(a: argparse.Namespace, root: Path) -> int:
    intro = ""
    if a.intro_file:
        try:
            intro = Path(a.intro_file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise Usage(f"--intro-file {a.intro_file}: {e}") from e
    if not a.title_en and not a.dry_run and _tty():
        a.title_en = _ask("Title of the release in English (its short name in the timeline)", required=True)
    title = {"en": a.title_en or "", "zh": a.title_zh or "", "fr": a.title_fr or ""}
    plan = ops.plan_prepare(root, version=a.version, date=a.date, title=title, intro=intro, known_limits=a.known_limit,
                            force_bump=a.force_bump, known_tags=ops.tags(root) or set(), placeholder_title=a.dry_run)
    print(f"Release {plan.version}, dated {plan.date} ({plan.why})")
    print(f"  {len(plan.manifest['fragments'])} change(s): " + ", ".join(
        f"{n} {t}" for t in checks.TYPE_ORDER if (n := sum(1 for e in plan.manifest['fragments'] if plan.repo_after.fragments[e['id']].type == t))))
    for note in plan.notes:
        print(f"  note: {note}")
    print("Files:")
    print(f"  {plan.manifest_path} (new)")
    for file, fld, old, new in plan.version_changes:
        print(f"  {file}: {fld} {old} -> {new}")
    print(f"  {render.CHANGELOG} (generated)")
    print(f"  {render.APP_DATA} (generated)")
    if a.dry_run:
        print(f"\n--- {plan.manifest_path}")
        print(plan.files[plan.manifest_path], end="")
        print(f"\n--- {render.CHANGELOG}: the new section")
        print(plan.section, end="")
        print(f"\n--- {render.APP_DATA}: the new release")
        print(json.dumps(plan.entry, ensure_ascii=False, indent=1, sort_keys=True))
        print("\nNothing was written (--dry-run).")
        return 0
    written = ops.apply(root, plan.files)
    print("Written: " + (", ".join(written) or "nothing (already so)"))
    found = checks.check_repo(model.load(root), release=plan.version)
    _report(found)
    if checks.errors(found):
        print(f"validate --release {plan.version}: FAILED")
        return 1
    print(f"validate --release {plan.version}: ok")
    print(f"Next: review the diff, then open a pull request \"Release {plan.version}\" with these files. "
          f"After it is merged: python scripts/release.py publish {plan.version}")
    return 0


# --- generate / notes / correct --------------------------------------------------------------------------------------------
def cmd_generate(a: argparse.Namespace, root: Path) -> int:
    written, stale, found = ops.generate(root, check=a.check)
    if checks.errors(found):
        _report(checks.errors(found))
        print("not generated: the release data has errors (python scripts/release.py validate)")
        return 1
    if a.check:
        for f, why in stale:
            print(f"::error file={f}::{f} {why}: run python scripts/release.py generate" if os.environ.get("GITHUB_ACTIONS") == "true"
                  else f"{f}: {why} - run python scripts/release.py generate")
        if not stale:
            print(f"ok: {render.CHANGELOG} and {render.APP_DATA} are what the release data gives")
        return 1 if stale else 0
    print("written: " + ", ".join(written) if written else f"ok: {render.CHANGELOG} and {render.APP_DATA} were already up to date")
    return 0


def cmd_notes(a: argparse.Namespace, root: Path) -> int:
    repo = model.load(root)
    try:
        text = render.notes(repo, a.version.removeprefix("v"))
    except KeyError:
        print(f"no release {a.version} (changes/releases/{a.version.removeprefix('v')}.json)", file=sys.stderr)
        return 1
    bad = [p for p in checks.errors(checks.check_repo(repo)) if p.path.startswith(f"{model.RELEASES}/{a.version.removeprefix('v')}.json")
           or any(p.path == f"{model.FRAGMENTS}/{fid}.md" for fid in repo.manifest(a.version).ids)]
    if bad:
        _report(bad)
        print(f"the release {a.version} has errors", file=sys.stderr)
        return 1
    sys.stdout.write(text)
    return 0


def cmd_correct(a: argparse.Namespace, root: Path) -> int:
    path, entry = ops.correct(root, a.version.removeprefix("v"), a.id, a.reason)
    print(f"{path}: correction of {entry['id']} recorded ({entry['date']}, sha256 {entry['sha256'][:12]}...)")
    written, _, found = ops.generate(root)
    if checks.errors(found):
        _report(checks.errors(found))
        print("the generated files were not updated: the release data has errors")
        return 1
    print("regenerated: " + (", ".join(written) or "nothing changed"))
    return 0


# --- publish -------------------------------------------------------------------------------------------------------------
def cmd_publish(a: argparse.Namespace, root: Path) -> int:
    name = a.version.removeprefix("v")
    if not versions.valid(name):
        raise Usage(f"{a.version!r} is not a version")
    results = ops.publish_checks(root, name, fetch=not a.no_fetch)
    ok = all(c.ok for c in results)
    for c in results:
        mark = "ok  " if c.ok else "FAIL"
        print(f"  {mark} {c.label}" + (f" - {c.detail}" if c.detail else ""))
    commands = ops.publish_commands(name)
    shown = [" ".join(f'"{x}"' if " " in x else x for x in cmd) for cmd in commands]
    if not a.yes:
        print(("Ready. " if ok else "Refused: fix what FAILed above. ") + "The commands that publish the release (not run - this is a dry run):")
        for s in shown:
            print(f"  {s}")
        print("Pushing the tag starts .github/workflows/release.yml, which builds, checks and publishes the release.")
        return 0 if ok else 1
    if not ok:
        print("Refused: fix what FAILed above. Nothing was run.")
        return 1
    if not _tty():
        raise Usage("--yes needs a person at a terminal to type the version; nothing was run")
    typed = _ask(f"This tags and pushes v{name} - a public release. Type {name} to go on")
    if typed != name:
        print("Not confirmed. Nothing was run.")
        return 1
    for cmd, s in zip(commands, shown):
        print(f"$ {s}")
        r = ops.git(root, *cmd[1:], timeout=300)
        if r is None or r.returncode != 0:
            print((r.stderr if r else "git is not available").strip())
            return 1
    print(f"Published the tag v{name}: the release workflow runs now.")
    return 0


# --- the parser ------------------------------------------------------------------------------------------------------------
class Parser(argparse.ArgumentParser):
    def error(self, message: str):  # usage errors exit 2, said once
        raise Usage(message)


def parser() -> argparse.ArgumentParser:
    p = Parser(prog="python scripts/release.py", description=__doc__.split("\n\n")[0],
               formatter_class=argparse.RawDescriptionHelpFormatter, epilog="See docs/release-workflow.md.")
    p.add_argument("--root", help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command", metavar="<command>", parser_class=Parser)

    c = sub.add_parser("change", help="write a new change fragment")
    c.add_argument("--type", help="added, changed, deprecated, removed, fixed, security")
    c.add_argument("--scope", help="the part of the product (the list: changes/schema/fragment.schema.json)")
    c.add_argument("--summary-en", help="one line, at most 120 characters")
    c.add_argument("--summary-zh", help="Simplified Chinese (optional)")
    c.add_argument("--summary-fr", help="French (optional)")
    c.add_argument("--details", help="the details, Markdown")
    c.add_argument("--details-file", help="a file with the details, Markdown")
    c.add_argument("--highlight", action="store_true", help="one of the release's main changes")
    c.add_argument("--bump", choices=list(versions.LEVELS), help="the version impact when more than patch")
    c.add_argument("--pr", action="append", help="pull request number(s)")
    c.add_argument("--slug", help="1-5 words for the file name (default: from the English summary)")

    v = sub.add_parser("validate", help="check the release data")
    v.add_argument("--release", metavar="X", help="also what publishing X needs")
    v.add_argument("--strict", action="store_true", help="highlights need summary.zh and details")

    sub.add_parser("status", help="pending changes, the next version, the releases")

    pr = sub.add_parser("prepare", help="make a release from the pending fragments")
    pr.add_argument("--dry-run", action="store_true", help="show what would be written; write nothing")
    pr.add_argument("--version", help="instead of the suggested version")
    pr.add_argument("--date", help="YYYY-MM-DD (default: today)")
    pr.add_argument("--title-en", help="the release's short name")
    pr.add_argument("--title-zh")
    pr.add_argument("--title-fr")
    pr.add_argument("--intro-file", help="a Markdown file: what the release is about")
    pr.add_argument("--known-limit", action="append", default=[], help="a known limit (Markdown); repeat for more")
    pr.add_argument("--force-bump", metavar="REASON", help="release a smaller version than a fragment declares, and why")

    g = sub.add_parser("generate", help="write CHANGELOG.md and backend/autoapply/releases.json")
    g.add_argument("--check", action="store_true", help="only say whether they are up to date (exit 1 if not)")

    n = sub.add_parser("notes", help="print a release's GitHub notes")
    n.add_argument("version")

    co = sub.add_parser("correct", help="record a change to a released fragment")
    co.add_argument("version")
    co.add_argument("id")
    co.add_argument("--reason", required=True, help="one line: why the released text changed")

    pu = sub.add_parser("publish", help="check a release and print (or, with --yes, run) the tag commands")
    pu.add_argument("version")
    pu.add_argument("--yes", action="store_true", help="run the commands, after the version is typed at the terminal")
    pu.add_argument("--no-fetch", action="store_true", help="do not fetch origin first")
    return p


COMMANDS = {"change": cmd_change, "validate": cmd_validate, "status": cmd_status, "prepare": cmd_prepare,
            "generate": cmd_generate, "notes": cmd_notes, "correct": cmd_correct, "publish": cmd_publish}


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        a = parser().parse_args(argv)
        if not a.command:
            parser().print_help()
            return 2
        root = Path(a.root) if a.root else Path(root) if root else Path(__file__).resolve().parents[3]
        try:
            import yaml  # noqa: F401
        except ImportError:
            print("PyYAML is needed: `uv run python scripts/release.py ...` (it is a dependency of the program), or pip install pyyaml",
                  file=sys.stderr)
            return 2
        return COMMANDS[a.command](a, root)
    except Usage as e:
        print(f"usage error: {e}", file=sys.stderr)
        return 2
    except ops.OpError as e:
        _report(e.problems)
        print(f"{'usage error' if e.code == 2 else 'refused'}: {e}", file=sys.stderr)
        return e.code
    except schema.SchemaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
