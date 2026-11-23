"""scripts/release.py: every command on a copy of tests/fixtures/release - what it writes (and, in a dry run, that it
writes nothing), what it says, and its exit code (0 ok, 1 problems, 2 usage). `publish` runs only as the dry run, in a
throw-away git repository whose "origin" is a local copy: no tag is made and nothing is pushed.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from autoapply import release
from autoapply.release import cli, ops

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "release"
F = "changes/fragments"
CALENDAR = "2026-02-01-calendar-feed-5e6f"
VERSION_FILES = ("pyproject.toml", "uv.lock", "frontend/package.json", "frontend/package-lock.json")


@pytest.fixture()
def tree(tmp_path):
    dst = tmp_path / "repo"
    shutil.copytree(FIXTURE, dst)
    return dst


@pytest.fixture(autouse=True)
def plain(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(cli, "_tty", lambda: False)        # as an agent or CI runs it, unless a test says otherwise


def run(tree: Path, capsys, *args: str) -> tuple[int, str]:
    code = cli.main(list(args), root=tree)
    out = capsys.readouterr()
    return code, out.out + out.err


def snapshot(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


# --- change ----------------------------------------------------------------------------------------------------------------
def test_change_writes_a_valid_fragment_without_questions(tree, capsys):
    code, out = run(tree, capsys, "change", "--type", "fixed", "--scope", "calendar", "--summary-en", "Reminders are the right height",
                    "--summary-zh", "提醒的高度正确", "--details", "The chip is as tall as the buttons.\n\n- one\n- two", "--highlight",
                    "--bump", "minor", "--pr", "41", "--pr", "42,43")
    assert code == 0, out
    path = out.strip().splitlines()[-1]
    assert path.startswith(f"{F}/") and path.endswith(".md")
    fid = Path(path).stem
    assert fid[11:].startswith("reminders-right-height-") and len(fid.rsplit("-", 1)[1]) == 4
    text = (tree / path).read_text(encoding="utf-8")
    assert text == (f'---\nid: {fid}\ntype: fixed\nscope: calendar\nsummary:\n  en: "Reminders are the right height"\n'
                    f'  zh: "提醒的高度正确"\nhighlight: true\nbump: minor\npr: [41, 42, 43]\n---\n\n'
                    f"The chip is as tall as the buttons.\n\n- one\n- two\n")
    f = release.load(tree).fragments[fid]
    assert (f.type, f.scope, f.highlight, f.bump, f.pr, f.summary["zh"]) == ("fixed", "calendar", True, "minor", [41, 42, 43], "提醒的高度正确")
    assert release.validate(tree) == [] and fid in [x.id for x in release.load(tree).pending]


def test_change_quotes_what_yaml_would_misread(tree, capsys):
    tricky = 'Calendar: "quotes", a #hash, a \\backslash and yes'
    code, out = run(tree, capsys, "change", "--type", "changed", "--scope", "ui", "--summary-en", tricky, "--summary-fr", "Agenda : « oui »",
                    "--slug", "tricky-summary")
    assert code == 0, out
    fid = Path(out.strip().splitlines()[-1]).stem
    assert "-tricky-summary-" in fid
    f = release.load(tree).fragments[fid]
    assert f.summary == {"en": tricky, "fr": "Agenda : « oui »"} and f.details == ""


def test_change_details_from_a_file(tree, capsys, tmp_path):
    (tmp_path / "d.md").write_bytes(b"First line.\r\n\r\nSecond paragraph.  \r\n")
    code, out = run(tree, capsys, "change", "--type", "added", "--scope", "ui", "--summary-en", "A thing", "--details-file", str(tmp_path / "d.md"))
    assert code == 0, out
    assert release.load(tree).fragments[Path(out.strip().splitlines()[-1]).stem].details == "First line.\n\nSecond paragraph."


@pytest.mark.parametrize("args, code, words", [
    (["--scope", "ui", "--summary-en", "x"], 2, "missing --type"),
    (["--type", "fixed", "--summary-en", "x"], 2, "missing --scope"),
    (["--type", "fixed", "--scope", "everything", "--summary-en", "x"], 2, "--scope 'everything': one of postings"),
    (["--type", "improved", "--scope", "ui", "--summary-en", "x"], 2, "--type 'improved'"),
    (["--type", "fixed", "--scope", "ui", "--summary-en", "x", "--bump", "huge"], 2, "invalid choice"),
    (["--type", "fixed", "--scope", "ui", "--summary-en", "x", "--pr", "abc"], 2, "a pull request number"),
    (["--type", "fixed", "--scope", "ui", "--summary-en", "x", "--slug", "Not A Slug"], 2, "--slug"),
    (["--type", "fixed", "--scope", "ui", "--summary-en", "x" * 121], 1, "at most 120 characters"),
    (["--type", "fixed", "--scope", "ui", "--summary-en", "- a list"], 1, "Markdown block syntax"),
    (["--type", "fixed", "--scope", "ui", "--summary-en", "x", "--details", "[a](javascript:alert(1))"], 1, "links in the details"),
])
def test_change_refuses_and_writes_nothing(tree, capsys, args, code, words):
    before = snapshot(tree)
    got, out = run(tree, capsys, "change", *args)
    assert got == code and words in out, out
    assert snapshot(tree) == before


def test_change_asks_on_a_terminal(tree, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_tty", lambda: True)
    answers = iter(["improved", "fixed", "calendar", "", "Asked summary", "", "Résumé demandé", "y", "", "Details given at the prompt."])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    code, out = run(tree, capsys, "change")
    assert code == 0, out
    assert "one of: added" in out and "needed" in out
    f = release.load(tree).fragments[Path(out.strip().splitlines()[-1]).stem]
    assert (f.type, f.scope, f.summary, f.highlight, f.bump, f.details) == (
        "fixed", "calendar", {"en": "Asked summary", "fr": "Résumé demandé"}, True, None, "Details given at the prompt.")


def test_two_agents_at_the_same_moment_get_two_files(tree, monkeypatch):
    # the same summary, the same day, and (forced) the same random part: the second one takes another name
    draws = iter(["abcd", "abcd", "ef01"])
    monkeypatch.setattr(ops.secrets, "token_hex", lambda n: next(draws))
    a, _ = ops.new_fragment(tree, type="fixed", scope="ui", summary={"en": "Same words"}, date="2026-04-01")
    b, _ = ops.new_fragment(tree, type="fixed", scope="ui", summary={"en": "Same words"}, date="2026-04-01")
    assert (a.name, b.name) == ("2026-04-01-same-words-abcd.md", "2026-04-01-same-words-ef01.md")
    assert release.validate(tree) == []


def test_two_processes_at_once(tree):
    cmd = [sys.executable, str(ROOT / "scripts/release.py"), "--root", str(tree), "change", "--type", "fixed", "--scope", "ui",
           "--summary-en", "Written at the same time"]
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    procs = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env) for _ in range(4)]
    outs = [p.communicate(timeout=120) for p in procs]
    assert all(p.returncode == 0 for p in procs), outs
    paths = {o.strip().splitlines()[-1] for o, _ in outs}
    assert len(paths) == 4 and all((tree / p).is_file() for p in paths)
    assert release.validate(tree) == []


# --- validate / status ------------------------------------------------------------------------------------------------------
def test_validate_exit_codes_and_messages(tree, capsys, monkeypatch):
    code, out = run(tree, capsys, "validate")
    assert code == 0 and out.strip() == "ok: 7 fragments (2 pending), 2 releases; 0 error(s), 0 warning(s)"
    (tree / F / f"{CALENDAR}.md").write_bytes((tree / F / f"{CALENDAR}.md").read_bytes().replace(b"scope: calendar", b"scope: calender"))
    code, out = run(tree, capsys, "validate")
    assert code == 1
    assert f'{F}/{CALENDAR}.md:4: error: scope: "calender" is not one of' in out
    assert f"{F}/{CALENDAR}.md: error: changed after its release in 1.1.0" in out
    assert out.strip().endswith("FAILED: 7 fragments (2 pending), 2 releases; 2 error(s), 0 warning(s)")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    code, out = run(tree, capsys, "validate")
    assert f"::error file={F}/{CALENDAR}.md,line=4::scope: " in out


def test_validate_strict_and_release(tree, capsys):
    ops.new_fragment(tree, type="added", scope="ui", summary={"en": "A highlight in English only"}, highlight=True)
    assert run(tree, capsys, "validate")[0] == 0
    code, out = run(tree, capsys, "validate", "--strict")
    assert code == 1 and "without summary.zh" in out and "without details" in out
    code, out = run(tree, capsys, "validate", "--release", "1.1.0")
    assert code == 0 and "warning: 3 fragment(s) are not in any release" in out
    code, out = run(tree, capsys, "validate", "--release", "1.2.0")
    assert code == 1 and "no manifest for 1.2.0" in out


def test_status(tree, capsys):
    code, out = run(tree, capsys, "status")
    assert code == 0
    assert "Pending: 2 fragment(s)" in out and "  Changed\n    2026-03-01-dark-theme-menus-a1b2  [ui] highlight bump:minor  Menus" in out
    assert "Next version: 1.2.0 (1.1.0 (pyproject.toml and the newest manifest) + minor, declared by 2026-03-01-dark-theme-menus-a1b2)" in out
    assert "1.1.0        2026-02-05    3 change(s)" in out and "whether each is published is not known" in out
    assert "Validation: 0 error(s), 0 warning(s)" in out


# --- prepare -------------------------------------------------------------------------------------------------------------
def test_prepare_dry_run_writes_nothing(tree, capsys):
    before = snapshot(tree)
    code, out = run(tree, capsys, "prepare", "--dry-run")
    assert code == 0, out
    assert snapshot(tree) == before
    assert "Release 1.2.0, dated " in out and "pyproject.toml: [project] version 1.1.0 -> 1.2.0" in out
    assert 'frontend/package-lock.json: packages[""].version 1.1.0 -> 1.2.0' in out and "uv.lock: the project's [[package]] version 1.1.0 -> 1.2.0" in out
    assert "--- changes/releases/1.2.0.json\n{\n  \"version\": \"1.2.0\"" in out
    assert "--- CHANGELOG.md: the new section\n## [1.2.0] - " in out and "- **Menus and tooltips look the same in both themes**" in out
    assert '"url": "https://github.com/example-owner/example-repo/releases/tag/v1.2.0"' in out
    assert out.strip().endswith("Nothing was written (--dry-run).")
    code, out = run(tree, capsys, "prepare", "--dry-run", "--version", "1.3.0", "--title-en", "Later", "--date", "2026-03-09")
    assert code == 0 and snapshot(tree) == before and "Release 1.3.0, dated 2026-03-09" in out


def test_prepare_writes_the_release(tree, capsys, tmp_path):
    (tmp_path / "intro.md").write_text("Menus, tooltips and reminders.\n", encoding="utf-8")
    before = {rel: (tree / rel).read_text(encoding="utf-8") for rel in VERSION_FILES}
    code, out = run(tree, capsys, "prepare", "--title-en", "Menus everywhere", "--title-zh", "处处一致的菜单", "--date", "2026-03-05",
                    "--intro-file", str(tmp_path / "intro.md"), "--known-limit", "Touch screens are not measured.")
    assert code == 0, out
    assert "validate --release 1.2.0: ok" in out and "publish 1.2.0" in out
    m = json.loads((tree / "changes/releases/1.2.0.json").read_text(encoding="utf-8"))
    repo = release.load(tree)
    assert m == {"version": "1.2.0", "date": "2026-03-05", "title": {"en": "Menus everywhere", "zh": "处处一致的菜单"},
                 "intro": "Menus, tooltips and reminders.", "known_limits": ["Touch screens are not measured."],
                 "fragments": [{"id": fid, "sha256": repo.fragments[fid].sha256} for fid in ("2026-03-01-dark-theme-menus-a1b2", "2026-03-02-reminder-sizes-c3d4")],
                 "corrections": []}
    for rel in VERSION_FILES:                       # exactly the version fields changed
        new = (tree / rel).read_text(encoding="utf-8")
        assert new == before[rel].replace('version = "1.1.0"', 'version = "1.2.0"').replace('"version": "1.1.0"', '"version": "1.2.0"'), rel
    assert [c.value for c in release.versions.copies(tree)] == ["1.2.0"] * 5
    changelog = (tree / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [1.2.0] - 2026-03-05\n\nMenus, tooltips and reminders.\n\n### Changed\n" in changelog
    assert "### Known limits\n\n- Touch screens are not measured.\n\n## [1.1.0]" in changelog
    assert changelog.endswith("[1.2.0]: https://github.com/example-owner/example-repo/releases/tag/v1.2.0\n"
                              "[1.1.0]: https://github.com/example-owner/example-repo/releases/tag/v1.1.0\n"
                              "[1.0.0]: https://github.com/example-owner/example-repo/releases/tag/v1.0.0\n")
    data = json.loads((tree / "backend/autoapply/releases.json").read_text(encoding="utf-8"))
    assert [r["version"] for r in data["releases"]] == ["1.2.0", "1.1.0", "1.0.0"]
    assert release.load(tree).pending == [] and release.validate(tree, release="1.2.0") == []
    assert run(tree, capsys, "generate", "--check")[0] == 0
    assert run(tree, capsys, "prepare", "--title-en", "Again")[0] == 1          # nothing pending any more


@pytest.mark.parametrize("args, code, words", [
    (["--version", "1.1.0"], 1, "1.1.0 exists already"),
    (["--version", "1.0.5"], 1, "is not after the newest release 1.1.0"),
    (["--version", "1.1.1"], 1, "1.1.1 is not a minor release after 1.1.0, which 2026-03-01-dark-theme-menus-a1b2 declare(s): use 1.2.0"),
    (["--version", "1.2"], 2, "not a version"),
    (["--date", "2026-02-30"], 2, "--date"),
    ([], 2, "--title-en is needed"),
])
def test_prepare_refuses(tree, capsys, args, code, words):
    before = snapshot(tree)
    title = [] if not args else ["--title-en", "T"]
    got, out = run(tree, capsys, "prepare", *args, *title)
    assert got == code and words in out, out
    assert snapshot(tree) == before


def test_prepare_force_bump_says_why(tree, capsys):
    code, out = run(tree, capsys, "prepare", "--version", "1.1.1", "--force-bump", "A hotfix line", "--title-en", "Hotfix", "--dry-run")
    assert code == 0, out
    assert "note: --force-bump: released as 1.1.1 although 2026-03-01-dark-theme-menus-a1b2 declare(s) minor. Reason: A hotfix line" in out


def test_prepare_a_pre_release_then_its_release(tree, capsys):
    assert run(tree, capsys, "prepare", "--version", "1.2.0-rc.1", "--title-en", "Menus (candidate)", "--date", "2026-03-05")[0] == 0
    assert [c.value for c in release.versions.copies(tree)] == ["1.2.0-rc.1"] * 5
    ops.new_fragment(tree, type="fixed", scope="ui", summary={"en": "Found in the candidate"}, date="2026-03-06")
    assert release.suggest_version(tree)[0] == "1.2.0"
    assert run(tree, capsys, "prepare", "--title-en", "Menus", "--date", "2026-03-08")[0] == 0
    assert release.validate(tree, release="1.2.0") == []


def test_a_fragment_merged_after_prepare_and_the_candidate_made_again(tree, capsys):
    assert run(tree, capsys, "prepare", "--title-en", "Menus", "--date", "2026-03-05")[0] == 0
    late, _ = ops.new_fragment(tree, type="fixed", scope="ui", summary={"en": "Merged after prepare"}, date="2026-03-06")
    code, out = run(tree, capsys, "validate", "--release", "1.2.0")
    assert code == 0 and "warning: 1 fragment(s) are not in any release" in out
    # before its tag exists the candidate may be made again (docs/release-workflow.md, troubleshooting)
    (tree / "changes/releases/1.2.0.json").unlink()
    assert run(tree, capsys, "prepare", "--version", "1.2.0", "--title-en", "Menus", "--date", "2026-03-07")[0] == 0
    assert late.stem in release.load(tree).manifest("1.2.0").ids and release.validate(tree, release="1.2.0") == []


def test_prepare_refuses_on_errors_in_the_data(tree, capsys):
    (tree / F / f"{CALENDAR}.md").write_bytes(b"---\nbroken: [\n---\n")
    before = snapshot(tree)
    code, out = run(tree, capsys, "prepare", "--title-en", "T")
    assert code == 1 and "YAML" in out and "the release data has errors" in out
    assert snapshot(tree) == before


# --- generate / notes / correct ---------------------------------------------------------------------------------------------
def test_generate_and_check(tree, capsys):
    assert run(tree, capsys, "generate", "--check") == (0, "ok: CHANGELOG.md and backend/autoapply/releases.json are what the release data gives\n")
    (tree / "backend/autoapply/releases.json").unlink()
    with open(tree / "CHANGELOG.md", "a", encoding="utf-8") as fh:
        fh.write("\nA line written by hand.\n")
    code, out = run(tree, capsys, "generate", "--check")
    assert code == 1
    assert "CHANGELOG.md: differs from what the release data gives - run python scripts/release.py generate" in out
    assert "backend/autoapply/releases.json: missing" in out
    code, out = run(tree, capsys, "generate")
    assert code == 0 and "written: CHANGELOG.md, backend/autoapply/releases.json" in out
    first = snapshot(tree)
    assert run(tree, capsys, "generate")[0] == 0 and snapshot(tree) == first           # twice: the same bytes
    assert (tree / "CHANGELOG.md").read_bytes() == (FIXTURE / "CHANGELOG.md").read_bytes()
    # a checkout with Windows line ends is not "different"
    p = tree / "CHANGELOG.md"
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    assert run(tree, capsys, "generate", "--check")[0] == 0


def test_generate_check_in_ci_annotates(tree, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    (tree / "CHANGELOG.md").write_text("# hand-made\n", encoding="utf-8")
    code, out = run(tree, capsys, "generate", "--check")
    assert code == 1 and "::error file=CHANGELOG.md::CHANGELOG.md differs" in out


def test_generate_refuses_on_errors(tree, capsys):
    (tree / F / f"{CALENDAR}.md").write_bytes(b"---\nbroken: [\n---\n")
    before = snapshot(tree)
    code, out = run(tree, capsys, "generate")
    assert code == 1 and "not generated" in out and snapshot(tree) == before


def test_notes(tree, capsys):
    code, out = run(tree, capsys, "notes", "v1.1.0")
    assert code == 0 and out == release.release_notes("1.1.0", tree)
    assert out.startswith("### Added\n\n- **The calendar in your calendar app") and "## [" not in out and "]: https://" not in out
    assert run(tree, capsys, "notes", "9.9.9")[0] == 1
    (tree / F / f"{CALENDAR}.md").write_bytes((tree / F / f"{CALENDAR}.md").read_bytes() + b"\nmore\n")
    code, out = run(tree, capsys, "notes", "1.1.0")
    assert code == 1 and "changed after its release in 1.1.0" in out


def test_correct(tree, capsys):
    p = tree / F / f"{CALENDAR}.md"
    p.write_bytes(p.read_bytes().replace(b"read-only token", b"read-only key"))
    assert run(tree, capsys, "validate")[0] == 1
    assert run(tree, capsys, "generate", "--check")[0] == 1            # (errors: nothing compared)
    code, out = run(tree, capsys, "correct", "1.1.0", CALENDAR, "--reason", "It is a key, not a token")
    assert code == 0, out
    assert "changes/releases/1.1.0.json: correction of" in out and "regenerated: CHANGELOG.md, backend/autoapply/releases.json" in out
    m = json.loads((tree / "changes/releases/1.1.0.json").read_text(encoding="utf-8"))
    c = m["corrections"][-1]
    assert (c["id"], c["reason"], c["sha256"]) == (CALENDAR, "It is a key, not a token", release.load(tree).fragments[CALENDAR].sha256)
    assert run(tree, capsys, "validate")[0] == 0 and run(tree, capsys, "generate", "--check")[0] == 0
    assert "read-only key" in (tree / "CHANGELOG.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("args, code, words", [
    (["1.1.0", CALENDAR, "--reason", "nothing changed"], 1, "nothing to correct"),
    (["1.3.0", CALENDAR, "--reason", "r"], 1, "no release 1.3.0"),
    (["1.0.0", CALENDAR, "--reason", "r"], 1, "is not a fragment of 1.0.0"),
    (["1.1.0", CALENDAR, "--reason", "  "], 2, "--reason is needed"),
    (["1.1.0", CALENDAR], 2, "--reason"),
])
def test_correct_refuses(tree, capsys, args, code, words):
    before = snapshot(tree)
    got, out = run(tree, capsys, "correct", *args)
    assert got == code and words in out, out
    assert snapshot(tree) == before


# --- publish (dry run only) ------------------------------------------------------------------------------------------------
GIT_ENV = {"GIT_AUTHOR_NAME": "Release Test", "GIT_AUTHOR_EMAIL": "release-test@example.invalid",
           "GIT_COMMITTER_NAME": "Release Test", "GIT_COMMITTER_EMAIL": "release-test@example.invalid",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", *args], cwd=cwd, capture_output=True,
                       text=True, env={**os.environ, **GIT_ENV}, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.fixture()
def repo(tree, tmp_path):
    """The fixture as a git repository on master with an "origin" that is a local bare copy (made by cloning - nothing is
    pushed anywhere)."""
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    git(tree, "init", "-q", "-b", "master")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "fixture")
    git(tmp_path, "clone", "-q", "--bare", str(tree), str(tmp_path / "origin.git"))
    git(tree, "remote", "add", "origin", str(tmp_path / "origin.git"))
    git(tree, "fetch", "-q", "origin")
    return tree


def tags_of(path: Path) -> str:
    return git(path, "tag", "--list")


def test_publish_dry_run_is_ready_and_runs_nothing(repo, capsys, tmp_path):
    code, out = run(repo, capsys, "publish", "1.1.0")
    assert code == 0, out
    for label in ("on branch master", "a clean working tree", "up to date with origin", "no tag v1.1.0 on origin", "no tag v1.1.0 here",
                  "the manifest changes/releases/1.1.0.json", "every copy of the version is 1.1.0", "validate --release 1.1.0", "generate --check"):
        assert f"  ok   {label}" in out, (label, out)
    assert "Ready. The commands that publish the release (not run - this is a dry run):" in out
    assert '  git tag -a v1.1.0 -m "AutoApply 1.1.0"\n  git push origin v1.1.0\n' in out
    assert tags_of(repo) == "" and tags_of(tmp_path / "origin.git") == ""


def test_publish_refuses_on_a_dirty_tree_and_still_prints_the_commands(repo, capsys, tmp_path):
    (repo / "stray.txt").write_text("not committed\n", encoding="utf-8")
    code, out = run(repo, capsys, "publish", "1.1.0", "--no-fetch")
    assert code == 1
    assert "  FAIL a clean working tree - 1 changed or untracked file(s): stray.txt" in out
    assert "Refused: fix what FAILed above." in out
    assert '  git tag -a v1.1.0 -m "AutoApply 1.1.0"\n  git push origin v1.1.0\n' in out
    assert tags_of(repo) == "" and tags_of(tmp_path / "origin.git") == ""


def test_publish_refuses_what_is_not_ready(repo, capsys):
    git(repo, "checkout", "-q", "-b", "release-branch")
    git(repo, "commit", "-q", "--allow-empty", "-m", "ahead of origin")
    code, out = run(repo, capsys, "publish", "1.2.0", "--no-fetch")
    assert code == 1
    for line in ("FAIL on branch master - on release-branch", "FAIL the manifest changes/releases/1.2.0.json - missing",
                 "FAIL every copy of the version is 1.2.0", "FAIL validate --release 1.2.0", "FAIL up to date with origin"):
        assert line in out, (line, out)
    assert tags_of(repo) == ""


def test_publish_yes_needs_a_person(repo, capsys, monkeypatch):
    code, out = run(repo, capsys, "publish", "1.1.0", "--yes", "--no-fetch")
    assert code == 2 and "--yes needs a person at a terminal" in out
    monkeypatch.setattr(cli, "_tty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "1.1.1")          # typed wrong: nothing happens
    code, out = run(repo, capsys, "publish", "1.1.0", "--yes", "--no-fetch")
    assert code == 1 and "Not confirmed. Nothing was run." in out
    assert tags_of(repo) == ""


def test_publish_outside_git(tree, capsys):
    code, out = run(tree, capsys, "publish", "1.1.0")
    assert code == 1 and "FAIL a git repository" in out and "git tag -a v1.1.0" in out


# --- the script itself ------------------------------------------------------------------------------------------------------
def test_the_script(tree):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "GITHUB_ACTIONS")}
    script = [sys.executable, str(ROOT / "scripts/release.py")]
    ok = subprocess.run(script + ["--root", str(tree), "validate"], capture_output=True, text=True, env=env, timeout=120)
    assert ok.returncode == 0 and ok.stdout.startswith("ok: 7 fragments"), ok.stderr
    assert subprocess.run(script + ["--help"], capture_output=True, text=True, env=env, timeout=60).returncode == 0
    for bad in ([], ["frobnicate"], ["notes"], ["validate", "--nope"]):
        r = subprocess.run(script + ["--root", str(tree)] + bad, capture_output=True, text=True, env=env, timeout=60)
        assert r.returncode == 2, (bad, r.stdout, r.stderr)
    notes = subprocess.run(script + ["--root", str(tree), "notes", "1.1.0"], capture_output=True, env=env, timeout=60)
    assert notes.returncode == 0 and notes.stdout.decode("utf-8").replace("\r\n", "\n") == release.release_notes("1.1.0", tree)


def test_without_pyyaml_it_says_so(tree, capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, "yaml", None)
    code, out = run(tree, capsys, "validate")
    assert code == 2 and "PyYAML is needed" in out
