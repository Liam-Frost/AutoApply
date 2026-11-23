"""The release data model (backend/autoapply/release): reading fragments and manifests, every validation rule, version
numbers and the copies of the current one, and the generated changelog, app data and notes.

Everything runs on a copy of tests/fixtures/release (a tiny repository: the schemas, seven fragments - two pending -
and the manifests of 1.0.0 and 1.1.0), never on the real changes/.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

from autoapply import release
from autoapply.release import checks, model, ops, render, schema, versions

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "release"
F = "changes/fragments"
PENDING = ["2026-03-01-dark-theme-menus-a1b2", "2026-03-02-reminder-sizes-c3d4"]
CALENDAR = "2026-02-01-calendar-feed-5e6f"       # released in 1.1.0, with details, a list and links


@pytest.fixture()
def tree(tmp_path):
    dst = tmp_path / "repo"
    shutil.copytree(FIXTURE, dst)
    return dst


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(release, "_cache", {"key": None, "value": None})


def write(tree: Path, rel: str, text: str) -> Path:
    p = tree / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))
    return p


def fragment(tree: Path, fid: str, front: str, body: str = "") -> Path:
    return write(tree, f"{F}/{fid}.md", f"---\n{front}---\n{body}")


GOOD = 'id: {id}\ntype: fixed\nscope: ui\nsummary:\n  en: "A good summary"\n'
NEW = "2026-04-01-something-new-0f0f"


def found(tree: Path, **kw) -> list[release.Problem]:
    return release.validate(tree, **kw)


def one(problems, level: str, path: str, text: str, line: int | None = None) -> release.Problem:
    """The problem of that level, on that path, saying that (and on that line) - or a failure listing them all."""
    hits = [p for p in problems if p.level == level and p.path == path and text in p.message and (line is None or p.line == line)]
    assert hits, "\n".join(map(str, problems)) or "no problems"
    return hits[0]


def errors(problems):
    return [p for p in problems if p.level == "error"]


# --- the fixture and the schemas ----------------------------------------------------------------------------------------
def test_the_fixture_carries_the_real_schemas():
    for name in ("fragment.schema.json", "manifest.schema.json"):
        assert (FIXTURE / "changes/schema" / name).read_bytes() == (ROOT / "changes/schema" / name).read_bytes(), name


def test_the_fixture_is_valid_and_loads(tree):
    assert found(tree) == []
    repo = release.load(tree)
    assert len(repo.fragments) == 7
    assert [m.version for m in repo.manifests] == ["1.1.0", "1.0.0"]          # newest first
    assert [f.id for f in repo.pending] == PENDING
    f = repo.fragments[CALENDAR]
    assert (f.type, f.scope, f.highlight, f.bump, f.pr) == ("added", "calendar", True, None, [12, 14])
    assert f.summary["fr"].startswith("Le calendrier")
    assert f.details.startswith("Download what the page shows") and f.details.endswith("`[x](javascript:void)`.")
    assert f.path == f"{F}/{CALENDAR}.md" and len(f.sha256) == 64


def test_types_and_scopes_come_from_the_schema(tree):
    assert release.TYPES == release.TYPE_ORDER == ("added", "changed", "deprecated", "removed", "fixed", "security")
    assert release.scopes(tree)[:3] == ["postings", "applications", "agent"] and "release" in release.scopes(tree)
    s = json.loads((tree / "changes/schema/fragment.schema.json").read_text(encoding="utf-8"))
    s["properties"]["scope"]["enum"].append("made-up-scope")
    write(tree, "changes/schema/fragment.schema.json", json.dumps(s))
    assert "made-up-scope" in release.scopes(tree)
    fragment(tree, NEW, GOOD.format(id=NEW).replace("scope: ui", "scope: made-up-scope"))
    assert errors(found(tree)) == []
    # a type the release notes have no section for is refused where it is declared
    s["properties"]["type"]["enum"].append("improved")
    write(tree, "changes/schema/fragment.schema.json", json.dumps(s))
    one(found(tree), "error", "changes/schema/fragment.schema.json", "not the ones the release notes have sections for")


def test_the_schemas_are_json_schema_and_the_validator_agrees_with_jsonschema():
    jsonschema = pytest.importorskip("jsonschema")
    frag_schema = json.loads((ROOT / "changes/schema/fragment.schema.json").read_text(encoding="utf-8"))
    man_schema = json.loads((ROOT / "changes/schema/manifest.schema.json").read_text(encoding="utf-8"))
    for s in (frag_schema, man_schema):
        jsonschema.Draft202012Validator.check_schema(s)
    ok = {"id": NEW, "type": "fixed", "scope": "ui", "summary": {"en": "x"}}
    docs = [ok, {**ok, "pr": 3}, {**ok, "pr": [3, 4]}, {**ok, "highlight": True, "bump": "minor"},
            {**ok, "pr": 0}, {**ok, "pr": [3, 3]}, {**ok, "pr": []}, {**ok, "pr": "3"}, {**ok, "pr": True},
            {**ok, "type": "improved"}, {**ok, "scope": "everything"}, {**ok, "summary": {"en": "x" * 121}},
            {**ok, "summary": {"en": "two\nlines"}}, {**ok, "summary": {"zh": "x"}}, {**ok, "summary": {"en": ""}},
            {**ok, "hightlight": True}, {**ok, "highlight": "yes"}, {**ok, "id": "not-an-id"}, {k: v for k, v in ok.items() if k != "scope"}]
    for d in docs:
        ours = schema.check(frag_schema, d)
        theirs = list(jsonschema.Draft202012Validator(frag_schema).iter_errors(d))
        assert bool(ours) == bool(theirs), (d, ours, [e.message for e in theirs])
    m = {"version": "1.2.0", "date": "2026-03-03", "title": {"en": "T"}, "fragments": [{"id": NEW, "sha256": "a" * 64}]}
    for d in [m, {**m, "version": "1.2"}, {**m, "version": "1.2.0-rc.1"}, {**m, "version": "1.2.0a1"}, {**m, "version": "01.2.0"},
              {**m, "fragments": []}, {**m, "title": {}}, {**m, "corrections": [{"id": NEW, "date": "2026-03-04", "reason": "r", "sha256": "b" * 64}]},
              {**m, "corrections": [{"id": NEW, "date": "2026-03-04", "sha256": "b" * 64}]}, {**m, "fragments": [{"id": NEW, "sha256": "x"}]}]:
        assert bool(schema.check(man_schema, d)) == bool(list(jsonschema.Draft202012Validator(man_schema).iter_errors(d))), d


def test_the_id_pattern_is_the_same_in_both_schemas():
    frag_schema = json.loads((ROOT / "changes/schema/fragment.schema.json").read_text(encoding="utf-8"))
    man_schema = json.loads((ROOT / "changes/schema/manifest.schema.json").read_text(encoding="utf-8"))
    assert frag_schema["properties"]["id"]["pattern"] == man_schema["$defs"]["id"]["pattern"]
    rx = man_schema["properties"]["version"]["pattern"]
    for v in ("1.2.3", "0.0.0", "10.20.30", "1.2.3-rc.1", "1.2.3a1", "1.2.3b0", "1.2", "01.2.3", "1.2.3-rc1", "1.2.3rc1", "1.2.3-beta.1"):
        assert bool(re.search(rx, v)) == versions.valid(v) == (v in ("1.2.3", "0.0.0", "10.20.30", "1.2.3-rc.1", "1.2.3a1", "1.2.3b0")), v


# --- reading: what cannot be read is said with its file and line ----------------------------------------------------------
@pytest.mark.parametrize("text, line, words", [
    ("id: x\n", 1, "starts with a line '---'"),
    ("---\nid: x\n", 1, "not closed"),
    ("---\nid: x\nsummary: [unclosed\n---\n", 4, "YAML"),
    ("---\nid: x\nsummary:\n  en: Calendar: the feed\n---\n", 4, "YAML: mapping values are not allowed here"),
    ("---\nid: x\ntype: fixed\ntype: added\n---\n", 4, "the key 'type' is given twice (first on line 3)"),
    ("---\n- a list\n---\n", 2, "not a mapping of fields"),
    ("\ufeff---\nid: x\n---\n", 1, "byte order mark"),
])
def test_a_fragment_that_cannot_be_read_says_where(tree, text, line, words):
    write(tree, f"{F}/{NEW}.md", text)
    p = one(found(tree), "error", f"{F}/{NEW}.md", words)
    assert p.line == line, str(p)
    assert str(p).startswith(f"{F}/{NEW}.md:{line}: error: ")


def test_a_fragment_that_is_not_utf8(tree):
    (tree / F / f"{NEW}.md").write_bytes(b"---\nid: x\nsummary:\n  en: caf\xe9\n---\n")
    assert one(found(tree), "error", f"{F}/{NEW}.md", "not UTF-8").line == 4


def test_crlf_is_read_as_lf_and_hashes_the_same(tree):
    p = tree / F / f"{CALENDAR}.md"
    before = release.load(tree).fragments[CALENDAR]
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    after = release.load(tree).fragments[CALENDAR]
    assert after.sha256 == before.sha256 and after.details == before.details and after.meta == before.meta
    assert found(tree) == []


def test_files_that_are_not_fragments_or_manifests(tree):
    write(tree, f"{F}/notes.txt", "x")
    write(tree, f"{F}/.gitkeep", "")
    (tree / F / "sub").mkdir()
    write(tree, "changes/releases/notes.md", "x")
    probs = found(tree)
    one(probs, "error", f"{F}/notes.txt", "not a fragment")
    one(probs, "error", f"{F}/sub", "a folder inside changes/fragments/")
    one(probs, "error", "changes/releases/notes.md", "not a manifest")
    assert not [p for p in probs if ".gitkeep" in p.path]


# --- a fragment's rules -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("front, line, words", [
    ('id: {id}\ntype: fixed\nscope: ui\n', 2, 'missing required field "summary"'),
    ('id: {id}\ntype: improved\nscope: ui\nsummary:\n  en: "x"\n', 3, '"improved" is not one of: added, changed, deprecated, removed, fixed, security'),
    ('id: {id}\ntype: fixed\nscope: everything\nsummary:\n  en: "x"\n', 4, '"everything" is not one of: postings'),
    ('id: {id}\ntype: fixed\nscope: ui\nsummary:\n  en: "x"\nhightlight: true\n', 7, 'unknown field "hightlight" (did you mean "highlight"?)'),
    ('id: {id}\ntype: fixed\nscope: ui\nsummary:\n  en: "x"\nhighlight: "yes"\n', 7, "highlight: expected true or false, found a string"),
    ('id: {id}\ntype: fixed\nscope: ui\nsummary:\n  en: "x"\nbump: huge\n', 7, '"huge" is not one of: major, minor, patch'),
    ('id: {id}\ntype: fixed\nscope: ui\nsummary:\n  en: "x"\npr: 0\n', 7, "pr: must be at least 1"),
    ('id: {id}\ntype: fixed\nscope: ui\nsummary:\n  en: "x"\npr: "12"\n', 7, "pr: expected an integer or a list, found a string"),
    ('id: {id}\ntype: fixed\nscope: ui\nsummary:\n  zh: "只有中文"\n', 5, 'summary: missing required field "en"'),
    ('id: {id}\ntype: fixed\nscope: ui\nsummary:\n  en: "x"\n  de: "y"\n', 7, 'unknown field "de"'),
    ('id: {id}\ntype: fixed\nscope: ui\nsummary:\n  en: "' + "x" * 121 + '"\n', 6, "summary.en: at most 120 characters (has 121)"),
    ('id: {id}\ntype: fixed\nscope: ui\nsummary:\n  en: >\n    folded\n    text\n', 6, "summary.en:"),
    ('id: {id}\ntype: fixed\nscope: ui\nsummary:\n  en: "- a list item"\n', 6, "Markdown block syntax"),
    ('id: {id}\ntype: fixed\nscope: ui\nsummary:\n  en: "## Heading"\n', 6, "Markdown block syntax"),
    ('id: {id}\ntype: fixed\nscope: ui\nsummary:\n  en: " spaced"\n', 6, "starts or ends with a space"),
    ('id: {id}\ntype: fixed\nscope: ui\nsummary:\n  en: "A **bold** claim"\n', 6, "no bold inside a summary"),
    ('id: {id}\ntype: fixed\nscope: ui\nsummary:\n  en: 2026-01-01\n', 6, "found date (quote it)"),
    ('id: 2026-04-01-another-name-0f0f\ntype: fixed\nscope: ui\nsummary:\n  en: "x"\n', 2, "is not the file name"),
])
def test_fragment_rules(tree, front, line, words):
    fragment(tree, NEW, front.format(id=NEW))
    p = one(found(tree), "error", f"{F}/{NEW}.md", words)
    assert p.line == line, str(p)


def test_the_file_name_must_be_an_id_with_a_real_date(tree):
    fragment(tree, "a-hand-made-name", GOOD.format(id="a-hand-made-name"))
    one(found(tree), "error", f"{F}/a-hand-made-name.md", "is not a fragment id")
    bad_date = "2026-02-30-impossible-day-0a0a"
    fragment(tree, bad_date, GOOD.format(id=bad_date))
    one(found(tree), "error", f"{F}/{bad_date}.md", "which is not a date")


def test_links_in_details_are_http_or_relative(tree):
    body = ("\nFine: [a](https://example.org), [b](docs/x.md#y), [c](#here), <http://example.org>,\n"
            "`[d](javascript:x)` in code.\n\n```\n[e](file:///etc/passwd)\n```\n\n"
            "Not fine: [f](javascript:alert(1)) and\n[g](mailto:someone@example.org), <ftp://example.org/x>,\n"
            "[h]: file:///c:/x and <a href=\"data:text/html,x\">i</a> and [j](//elsewhere.example/x).\n")
    fragment(tree, NEW, GOOD.format(id=NEW), body)
    probs = [p for p in found(tree) if p.path == f"{F}/{NEW}.md"]
    bad = {p.message.split("'")[1]: p.line for p in probs if "links in the details" in p.message}
    assert bad == {"javascript:alert(1": 16, "mailto:someone@example.org": 17, "ftp://example.org/x": 17,
                   "file:///c:/x": 18, "data:text/html,x": 18, "//elsewhere.example/x": 18}, probs


def test_a_heading_in_the_details_is_a_warning(tree):
    fragment(tree, NEW, GOOD.format(id=NEW), "\nText.\n\n## Not a section\n\n#### fine\n")
    p = one(found(tree), "warning", f"{F}/{NEW}.md", "level-2 heading")
    assert p.line == 11
    assert errors(found(tree)) == []


def test_a_highlight_wants_chinese_and_details_strict_makes_it_an_error(tree):
    fragment(tree, NEW, GOOD.format(id=NEW) + "highlight: true\n")
    plain = found(tree)
    one(plain, "warning", f"{F}/{NEW}.md", "without summary.zh")
    one(plain, "warning", f"{F}/{NEW}.md", "without details")
    assert errors(plain) == []
    strict = found(tree, strict=True)
    one(strict, "error", f"{F}/{NEW}.md", "without summary.zh")
    one(strict, "error", f"{F}/{NEW}.md", "without details")


def test_more_than_six_highlights_pending_is_a_warning(tree):
    for i in range(6):
        fid = f"2026-04-0{i + 1}-highlight-{i}-0a0{i}"
        fragment(tree, fid, GOOD.format(id=fid).replace("  en:", '  zh: "中文"\n  en:') + "highlight: true\n", "\nDetails.\n")
    one(found(tree), "warning", F, "7 pending highlights")


# --- manifests ----------------------------------------------------------------------------------------------------------
def manifest(tree: Path, version: str) -> dict:
    return json.loads((tree / f"changes/releases/{version}.json").read_text(encoding="utf-8"))


def put_manifest(tree: Path, version: str, data: dict, name: str | None = None) -> None:
    write(tree, f"changes/releases/{name or version}.json", model.dump_manifest(data))


def test_a_manifest_that_cannot_be_read(tree):
    write(tree, "changes/releases/1.2.0.json", '{\n  "version": "1.2.0",\n  "date": "2026-03-03"\n  "title": {}\n}\n')
    assert one(found(tree), "error", "changes/releases/1.2.0.json", "JSON: Expecting ',' delimiter").line == 4
    write(tree, "changes/releases/1.2.0.json", '{"version": "1.2.0", "version": "1.2.0"}')
    one(found(tree), "error", "changes/releases/1.2.0.json", "'version' is given twice")


def test_manifest_rules(tree):
    m = manifest(tree, "1.1.0")
    put_manifest(tree, "1.1.0", {**m, "version": "1.1.1", "date": "2026-02-30", "title": {"zh": "无英文"}, "extra": 1})
    probs = found(tree)
    path = "changes/releases/1.1.0.json"
    one(probs, "error", path, "version '1.1.1' is not the file name (1.1.0)")
    one(probs, "error", path, "date '2026-02-30' is not a date")
    one(probs, "error", path, 'title: missing required field "en"')
    one(probs, "error", path, 'unknown field "extra"')
    put_manifest(tree, "1.1.0", m, name="one-point-one")
    one(found(tree), "error", "changes/releases/one-point-one.json", "is not a version")


def test_manifest_references(tree):
    m = manifest(tree, "1.1.0")
    first = m["fragments"][0]
    m["fragments"] += [first, {"id": "2026-02-09-never-written-ffff", "sha256": "0" * 64}]
    put_manifest(tree, "1.1.0", m)
    probs = found(tree)
    one(probs, "error", "changes/releases/1.1.0.json", f"{CALENDAR} is listed twice")
    one(probs, "error", "changes/releases/1.1.0.json", "2026-02-09-never-written-ffff is not in changes/fragments/")


def test_a_fragment_is_in_one_release(tree):
    old = manifest(tree, "1.0.0")
    new = manifest(tree, "1.1.0")
    new["fragments"].append(old["fragments"][0])
    put_manifest(tree, "1.1.0", new)
    one(found(tree), "error", "changes/releases/1.1.0.json", "2026-01-10-first-release-1a2b is already released in 1.0.0")


def test_released_text_is_immutable_and_correct_records_a_change(tree):
    p = tree / F / f"{CALENDAR}.md"
    p.write_bytes(p.read_bytes().replace(b"read-only token", b"read-only key"))
    e = one(found(tree), "error", f"{F}/{CALENDAR}.md", "changed after its release in 1.1.0")
    assert f"python scripts/release.py correct 1.1.0 {CALENDAR}" in e.message
    path, entry = ops.correct(tree, "1.1.0", CALENDAR, "The token is a key", date="2026-02-10")
    assert path == "changes/releases/1.1.0.json"
    assert manifest(tree, "1.1.0")["corrections"] == [{"id": CALENDAR, "date": "2026-02-10", "reason": "The token is a key",
                                                        "sha256": release.load(tree).fragments[CALENDAR].sha256}]
    assert errors(found(tree)) == []
    # the latest correction holds: going back to the released text is a change again
    p.write_bytes(p.read_bytes().replace(b"read-only key", b"read-only token"))
    one(found(tree), "error", f"{F}/{CALENDAR}.md", "changed after its release in 1.1.0")


def test_correction_rules(tree):
    m = manifest(tree, "1.1.0")
    m["corrections"] = [{"id": "2026-01-10-local-data-3c4d", "date": "2026-02-06", "reason": "r", "sha256": "0" * 64},
                        {"id": CALENDAR, "date": "2026-01-01", "reason": "r", "sha256": m["fragments"][0]["sha256"]}]
    put_manifest(tree, "1.1.0", m)
    probs = found(tree)
    one(probs, "error", "changes/releases/1.1.0.json", "corrections[0]: 2026-01-10-local-data-3c4d is not a fragment of this release")
    one(probs, "error", "changes/releases/1.1.0.json", "corrections[1].date: 2026-01-01 is before the release (2026-02-05)")
    one(probs, "warning", "changes/releases/1.1.0.json", "listed after a later correction")


def test_links_in_intro_and_known_limits(tree):
    m = manifest(tree, "1.1.0")
    put_manifest(tree, "1.1.0", {**m, "intro": "See [x](javascript:alert(1)).", "known_limits": ["[y](file:///x)", "[z](https://ok.example)"]})
    probs = found(tree)
    one(probs, "error", "changes/releases/1.1.0.json", "intro: link 'javascript:alert(1'")
    one(probs, "error", "changes/releases/1.1.0.json", "known_limits[0]: link 'file:///x'")
    assert not [p for p in probs if "known_limits[1]" in p.message]


# --- versions -----------------------------------------------------------------------------------------------------------
def test_version_order_and_bumps():
    p = versions.parse
    order = ["1.0.0", "1.0.1", "1.1.0a1", "1.1.0a2", "1.1.0b1", "1.1.0-rc.1", "1.1.0-rc.2", "1.1.0", "1.10.0", "2.0.0"]
    assert sorted(order, key=lambda v: p(v).key) == order
    assert str(p("v2.0.3")) == "2.0.3" and str(p("2.1.0-rc.1")) == "2.1.0-rc.1" and str(p("2.1.0b2")) == "2.1.0b2"
    for bad in ("2.0", "2.0.3.1", "02.0.3", "2.0.3-beta", "2.0.3rc1", "", "x"):
        assert not versions.valid(bad), bad
    assert [str(versions.bump(p("2.0.2"), lv)) for lv in ("patch", "minor", "major")] == ["2.0.3", "2.1.0", "3.0.0"]
    assert [str(versions.bump(p("2.1.0-rc.1"), lv)) for lv in ("patch", "minor", "major")] == ["2.1.0", "2.1.0", "3.0.0"]
    assert str(versions.bump(p("3.0.0a1"), "major")) == "3.0.0"
    assert versions.satisfies(p("2.1.0-rc.1"), p("2.0.2"), "minor") and versions.satisfies(p("2.1.0"), p("2.0.2"), "minor")
    assert not versions.satisfies(p("2.0.3"), p("2.0.2"), "minor") and not versions.satisfies(p("2.0.2"), p("2.0.2"), "patch")
    assert versions.largest(["patch", "major", "minor"]) == "major" and versions.largest([]) == "patch"


def test_suggestion_default_patch_declared_bump_never_backwards(tree):
    assert release.suggest_version(tree)[0] == "1.2.0"                # a pending fragment declares minor
    assert "declared by 2026-03-01-dark-theme-menus-a1b2" in release.suggest_version(tree)[1]
    p = tree / F / f"{PENDING[0]}.md"
    p.write_bytes(p.read_bytes().replace(b"bump: minor\n", b""))
    assert release.suggest_version(tree) == ("1.1.1", "1.1.0 (pyproject.toml and the newest manifest) + patch, the default (no pending fragment declares a bump)")
    p.write_bytes(p.read_bytes().replace(b"pr: 30\n", b"bump: major\npr: 30\n"))
    assert release.suggest_version(tree)[0] == "2.0.0"
    # the newer of pyproject and the newest manifest is the base: never back to an older number
    write(tree, "pyproject.toml", (tree / "pyproject.toml").read_text(encoding="utf-8").replace('version = "1.1.0"', 'version = "1.4.0"'))
    assert release.suggest_version(tree)[0] == "2.0.0"
    p.write_bytes(p.read_bytes().replace(b"bump: major\n", b""))
    assert release.suggest_version(tree) == ("1.4.1", "1.4.0 (pyproject.toml) + patch, the default (no pending fragment declares a bump)")


def test_the_copies_of_the_version_must_agree(tree):
    assert found(tree) == []
    lock = tree / "frontend/package-lock.json"
    data = json.loads(lock.read_text(encoding="utf-8"))
    data["packages"][""]["version"] = "1.0.9"
    lock.write_text(json.dumps(data, indent=2), encoding="utf-8")
    one(found(tree), "error", "frontend/package-lock.json", 'packages[""].version is 1.0.9, but pyproject.toml says 1.1.0')
    shutil.copy(FIXTURE / "frontend/package-lock.json", lock)
    write(tree, "uv.lock", (tree / "uv.lock").read_text(encoding="utf-8").replace('version = "1.1.0"', 'version = "1.1.1"'))
    one(found(tree), "error", "uv.lock", "the project's [[package]] version is 1.1.1")
    shutil.copy(FIXTURE / "uv.lock", tree / "uv.lock")
    write(tree, "frontend/package.json", '{"name": "x"}\n')
    one(found(tree), "error", "frontend/package.json", "no version")


def test_the_version_is_not_behind_the_releases(tree):
    for v, level, words in (("1.0.5", "error", "older than the newest release, 1.1.0"),
                            ("1.3.0", "warning", "version 1.3.0 has no manifest")):
        for rel in ("pyproject.toml", "uv.lock", "frontend/package.json", "frontend/package-lock.json"):
            write(tree, rel, (FIXTURE / rel).read_text(encoding="utf-8").replace('"1.1.0"', f'"{v}"'))
        one(found(tree), level, "pyproject.toml", words)


def test_release_dates_follow_versions(tree):
    m = manifest(tree, "1.1.0")
    put_manifest(tree, "1.1.0", {**m, "date": "2026-01-01"})
    one(found(tree), "warning", "changes/releases/1.1.0.json", "1.1.0 is dated 2026-01-01, before 1.0.0 (2026-01-12)")


def test_validate_for_a_release(tree):
    probs = found(tree, release="1.1.0")
    assert errors(probs) == []
    one(probs, "warning", F, "2 fragment(s) are not in any release")
    probs = found(tree, release="v1.2.0")
    one(probs, "error", "changes/releases/1.2.0.json", "no manifest for 1.2.0")
    one(probs, "error", "pyproject.toml", "version is 1.1.0, not 1.2.0")


def test_set_version_changes_those_fields_only(tree):
    before = {rel: (tree / rel).read_text(encoding="utf-8") for rel in ("pyproject.toml", "uv.lock", "frontend/package.json", "frontend/package-lock.json")}
    (tree / "frontend/package.json").write_bytes(before["frontend/package.json"].replace("\n", "\r\n").encode())   # CRLF kept
    texts = versions.new_texts(tree, "1.2.0-rc.1")
    for rel, text in texts.items():
        old = (tree / rel).read_text(encoding="utf-8", newline="")
        changed = [(a, b) for a, b in zip(old.splitlines(True), text.splitlines(True)) if a != b]
        assert len(old.splitlines()) == len(text.splitlines())
        assert all("1.1.0" in a and b == a.replace("1.1.0", "1.2.0-rc.1") for a, b in changed), changed
        assert len(changed) == (2 if rel.endswith("package-lock.json") else 1), (rel, changed)
    assert "\r\n" in texts["frontend/package.json"] and '[tool.example]\nversion = "9.9.9"' in texts["pyproject.toml"]
    assert '"version": "3.5.13"' in texts["frontend/package-lock.json"]


# --- the generated artifacts -----------------------------------------------------------------------------------------------
EXPECTED_CHANGELOG = """# Changelog

<!-- Generated by `python scripts/release.py generate` from changes/. Do not edit by hand - see docs/release-workflow.md. -->

All notable changes to AutoApply, newest first. Versions follow [Semantic Versioning](https://semver.org/); changes not released yet are pending fragments in `changes/fragments/`.

## [1.1.0] - 2026-02-05

### Added

- **The calendar in your calendar app: an .ics file or an address to subscribe to**

  Download what the page shows as an `.ics` file, or subscribe to an address your calendar app reads again by itself:

  - titles, times and links - never answers or mail text;
  - each item's reminders.

  The address has its own read-only token ([how it works](docs/calendar.md#feed), or
  <https://example.org/ics>). A fragment of code is not a link: `[x](javascript:void)`.

### Removed

- **The old CSV export (the backup covers it)**

### Fixed

- **Quiet hours follow your time zone, not the computer's clock**

  With the program running in another time zone (a server), quiet hours were someone else's night.

### Known limits

- The feed is read-only.

- A whole-day item has no time:

  - it is reminded of in the morning.

## [1.0.0] - 2026-01-12

The first release: postings found, scored and drafted on your own computer.

### Added

- **Postings found, scored and drafted on your own computer**

  The program finds postings, scores them against your profile and drafts each application. Nothing leaves your
  computer but what you send.

- **Your data in one folder you can back up**

[1.1.0]: https://github.com/example-owner/example-repo/releases/tag/v1.1.0
[1.0.0]: https://github.com/example-owner/example-repo/releases/tag/v1.0.0
"""


def test_the_changelog(tree):
    assert release.changelog_md(tree) == EXPECTED_CHANGELOG
    assert (FIXTURE / "CHANGELOG.md").read_bytes() == EXPECTED_CHANGELOG.encode("utf-8")      # the fixture's own, generated
    assert "dark-theme" not in EXPECTED_CHANGELOG and "Menus and tooltips" not in release.changelog_md(tree)   # released only


def test_the_notes_are_the_changelog_section(tree):
    notes = release.release_notes("1.1.0", tree)
    section = EXPECTED_CHANGELOG.split("## [1.1.0] - 2026-02-05\n\n")[1].split("\n## [1.0.0]")[0]
    assert notes == section
    assert release.release_notes("v1.0.0", tree).startswith("The first release: postings found")
    with pytest.raises(KeyError):
        release.release_notes("1.2.0", tree)


def test_the_app_data(tree):
    data = release.app_data(tree)
    assert data["_generated"].startswith("Generated by `python scripts/release.py generate`") and "do not edit" in data["_generated"].lower()
    assert (data["schema"], data["repo"]) == (1, "example-owner/example-repo")
    assert [r["version"] for r in data["releases"]] == ["1.1.0", "1.0.0"]
    r = data["releases"][0]
    assert set(r) == {"version", "date", "title", "intro", "known_limits", "url", "changes"}
    assert r["url"] == "https://github.com/example-owner/example-repo/releases/tag/v1.1.0"
    assert r["title"] == {"en": "A calendar feed", "zh": "日历订阅", "fr": "Un flux de calendrier"}
    assert [c["id"] for c in r["changes"]] == [CALENDAR, "2026-02-03-old-export-9c0d", "2026-02-02-quiet-hours-clock-7a8b"]   # manifest order
    c = r["changes"][0]
    assert set(c) == {"id", "type", "scope", "summary", "details", "highlight"}
    assert (c["type"], c["scope"], c["highlight"]) == ("added", "calendar", True) and c["details"].startswith("Download")
    assert data["releases"][1]["changes"][1] == {"id": "2026-01-10-local-data-3c4d", "type": "added", "scope": "files",
                                                 "summary": {"en": "Your data in one folder you can back up"}, "details": "", "highlight": False}
    text = render.app_data_text(release.load(tree))
    assert text == json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n" and "日历订阅" in text
    assert (FIXTURE / "backend/autoapply/releases.json").read_bytes() == text.encode("utf-8")


def test_generation_is_deterministic(tree, tmp_path):
    other = tmp_path / "other"
    shutil.copytree(FIXTURE, other)
    first = ops.artifacts(release.load(tree))
    assert first == ops.artifacts(release.load(tree)) == ops.artifacts(release.load(other))


# --- what the program reads at run time -------------------------------------------------------------------------------
def test_pending_entry(tree):
    entry = release.pending_entry(tree)
    assert {k: v for k, v in entry.items() if k != "changes"} == {"version": "Unreleased", "date": "", "title": {}, "intro": "",
                                                                  "known_limits": [], "url": ""}
    assert [c["id"] for c in entry["changes"]] == PENDING
    assert entry["changes"][0] == {"id": PENDING[0], "type": "changed", "scope": "ui", "highlight": True,
                                   "summary": {"en": "Menus and tooltips look the same in both themes", "zh": "菜单和提示在两种主题下外观一致",
                                               "fr": "Menus et infobulles identiques dans les deux thèmes"},
                                   "details": "One menu and one tooltip everywhere, with the keyboard, in light and dark."}
    entry["changes"].clear()                                      # a copy: the cache is not changed through it
    assert len(release.pending_entry(tree)["changes"]) == 2


def test_pending_entry_leaves_out_what_is_not_valid_and_follows_changes(tree):
    fragment(tree, NEW, GOOD.format(id=NEW).replace("scope: ui", "scope: everything"))
    assert [c["id"] for c in release.pending_entry(tree)["changes"]] == PENDING
    fragment(tree, NEW, GOOD.format(id=NEW))
    assert [c["id"] for c in release.pending_entry(tree)["changes"]] == PENDING + [NEW]
    write(tree, f"{F}/2026-04-02-broken-yaml-0a0a.md", "---\nsummary: [\n---\n")
    assert len(release.pending_entry(tree)["changes"]) == 3


def test_pending_entry_is_none_and_never_raises(tree, tmp_path, monkeypatch):
    assert release.pending_entry(tmp_path / "nowhere") is None                     # a package: no changes/ folder
    assert release.pending_entry(tree / "pyproject.toml") is None                  # nonsense
    write(tree, "changes/releases/1.2.0.json", "{ not json")
    assert release.pending_entry(tree) is None                                     # released and pending cannot be told apart
    (tree / "changes/releases/1.2.0.json").unlink()
    for fid in PENDING:
        (tree / F / f"{fid}.md").unlink()
    assert release.pending_entry(tree) is None                                     # nothing pending
    monkeypatch.setattr(release, "_cache", {"key": None, "value": None})
    monkeypatch.setitem(sys.modules, "yaml", None)                                  # PyYAML missing
    fragment(tree, NEW, GOOD.format(id=NEW))
    assert release.pending_entry(tree) is None
    monkeypatch.setattr(release, "_pending", lambda root: 1 / 0)
    monkeypatch.setattr(release, "_cache", {"key": None, "value": None})
    assert release.pending_entry(tree) is None


def test_pending_entry_reads_the_programs_root_by_default(tree, monkeypatch):
    from autoapply import config

    monkeypatch.setattr(config, "ROOT", tree)
    assert [c["id"] for c in release.pending_entry()["changes"]] == PENDING


def test_the_runtime_import_is_light():
    import subprocess

    code = ("import sys; sys.path.insert(0, 'backend'); from autoapply.release import pending_entry; "
            "heavy = sorted(m for m in ('yaml', 'fastapi', 'sqlalchemy', 'jsonschema', 'autoapply.config') if m in sys.modules); print(heavy)")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.strip() == "[]", out.stderr


def test_after_a_release_its_fragments_are_not_pending(tree):
    plan = ops.plan_prepare(tree, title={"en": "Menus"}, date="2026-03-05")
    ops.apply(tree, plan.files)
    repo = release.load(tree)
    assert repo.pending == [] and release.pending_entry(tree) is None
    assert [m.version for m in repo.manifests] == ["1.2.0", "1.1.0", "1.0.0"]
    assert set(repo.released) == set(repo.fragments)
    assert found(tree, release="1.2.0") == []
