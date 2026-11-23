"""The about page's changelog and licences: CHANGELOG.md parsed into versions (backend/autoapply/changelog.py), the
components the program runs on with their licence texts (licenses.py), and the endpoints that give them."""
import os
import re
import time
from pathlib import Path

import pytest

from autoapply import changelog, config, licenses

ROOT = Path(__file__).resolve().parents[1]


# ── the real CHANGELOG.md ─────────────────────────────────────────────────────────────────────────────────────────────
def test_the_real_changelog_every_version_with_its_date_kinds_and_link():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## \[([^\]]+)\](.*)$", text, re.M)
    vs = changelog.versions(ROOT / "CHANGELOG.md")
    unreleased_empty = not vs or not vs[0]["unreleased"]
    expected = [h for h, _ in headings if not (h == "Unreleased" and unreleased_empty)]
    assert [v["version"] for v in vs] == expected
    for (name, rest), v in zip([h for h in headings if h[0] in expected], vs):
        m = re.search(r"\d{4}-\d{2}-\d{2}", rest)
        assert v["date"] == (m.group(0) if m else "")                     # as written, and none where none is
        ref = re.search(r"^\[" + re.escape(name) + r"\]:\s*(\S+)", text, re.M)
        assert v["url"] == (ref.group(1) if ref else "")
        assert v["unreleased"] == (name == "Unreleased")
        for s in v["sections"]:
            assert s["items"] or s["text"]                                    # no empty section
            assert s["kind"] in ("added", "changed", "fixed", "security", "removed", "deprecated", "breaking", "known", "other")
    by = {v["version"]: v for v in vs}
    v202 = by["2.0.2"]
    assert v202["date"] == "2026-11-22" and v202["url"] == "https://github.com/Liam-Frost/AutoApply/compare/v2.0.0...v2.0.2"
    assert [(s["kind"], s["title"], len(s["items"])) for s in v202["sections"]] == [("added", "Added", 11), ("changed", "Changed", 7), ("fixed", "Fixed", 2), ("known", "Known limits", 2)]
    assert v202["summary"].startswith("2.0.2 brings what was planned for 2.0.1 and 2.0.2 in one release")
    assert v202["sections"][0]["items"][0].startswith("**Calendar** (sidebar, under *Needs you*)")
    # a section's bullets counted by hand: every "- " at the left edge between ### Fixed of 1.0.4 and the next version
    part = text.split("## [1.0.4]")[1].split("## [1.0.3]")[0].split("### Fixed")[1]
    assert len(by["1.0.4"]["sections"][2]["items"]) == len(re.findall(r"^- ", part, re.M)) == 61
    # headings of their own are kind "other" with their title; paragraphs that are not bullets are kept
    assert [(s["kind"], s["title"]) for s in by["1.0.1"]["sections"]][:2] == [("other", "The analysis page"), ("other", "Recording what the AI costs")]
    assert by["1.0.1"]["sections"][0]["text"].startswith("The page is now three views") and "\n\nThe cards of a row share its height" in by["1.0.1"]["sections"][0]["text"]
    assert by["1.0.0"]["url"].endswith("/releases/tag/v1.0.0")
    # sub-bullets stay in their item, on lines of their own; the file's wrapping is joined
    server = next(i for i in by["1.0.4"]["sections"][0]["items"] if i.startswith("**AutoApply can live on a server**"))
    lines = server.split("\n")
    assert lines[0].endswith("and be used from another computer or a phone.") and len(lines) == 7
    assert all(ln.startswith("- **") for ln in lines[1:])
    assert "\n" not in by["1.0.4"]["sections"][2]["items"][0]


# ── made-up changelogs ───────────────────────────────────────────────────────────────────────────────────────────────
MADE_UP = """# Changelog

Some words before any version.

## [Unreleased]

## [3.0.0] - 2031-02-03

The summary,
on two lines.

### Breaking changes

- The old format is gone.

### Added

- **A feature** that is
  described on two lines.
  - a sub-bullet
    that wraps
  - another one
- Second item.

### Fixed

### Deprecated

1. A numbered item.

### The way it looks

A paragraph of the section.

- A bullet under it.

Another paragraph after the bullets.

## [2.0.0]

### Security

- No date for this version.

## [1.0.0](https://example.org/one) - 2030-01-01

### Known issues

- An inline link in the heading, and no reference below.

```
### not a heading
## [9.9.9] - not a version
```

[Unreleased]: https://example.org/compare/v3.0.0...HEAD
[3.0.0]: https://example.org/compare/v2.0.0...v3.0.0
"""


def test_made_up_changelog():
    vs = changelog.parse(MADE_UP)
    assert [v["version"] for v in vs] == ["3.0.0", "2.0.0", "1.0.0"]           # an empty [Unreleased] is left out
    v3, v2, v1 = vs
    assert v3["date"] == "2031-02-03" and v3["summary"] == "The summary, on two lines." and not v3["unreleased"]
    assert v3["url"] == "https://example.org/compare/v2.0.0...v3.0.0"
    assert [(s["kind"], s["title"]) for s in v3["sections"]] == [("breaking", "Breaking changes"), ("added", "Added"), ("deprecated", "Deprecated"), ("other", "The way it looks")]
    added = v3["sections"][1]["items"]
    assert added == ["**A feature** that is described on two lines.\n- a sub-bullet that wraps\n- another one", "Second item."]
    assert v3["sections"][2]["items"] == ["A numbered item."]
    look = v3["sections"][3]
    assert look["items"] == ["A bullet under it."] and look["text"] == "A paragraph of the section.\n\nAnother paragraph after the bullets."
    assert v2["date"] == "" and v2["url"] == "" and v2["sections"][0]["kind"] == "security"      # nothing made up
    assert v1["url"] == "https://example.org/one" and v1["date"] == "2030-01-01"
    assert v1["sections"][0]["kind"] == "known"
    assert "```" not in v1["sections"][0]["items"][0]


def test_unreleased_with_content_crlf_and_kinds():
    text = "## [Unreleased]\r\n\r\n### Changed\r\n\r\n- Something\r\n  wrapped.\r\n\r\n## [1.2.3] - 2026-01-02\r\n\r\n### Removed\r\n- Gone.\r\n\r\n[1.2.3]: https://x.org/r\r\n"
    vs = changelog.parse(text)
    assert [(v["version"], v["unreleased"], v["date"]) for v in vs] == [("Unreleased", True, ""), ("1.2.3", False, "2026-01-02")]
    assert vs[0]["sections"] == [{"kind": "changed", "title": "Changed", "items": ["Something wrapped."], "text": ""}]
    assert vs[1]["url"] == "https://x.org/r" and vs[0]["url"] == ""
    assert all("\r" not in i for v in vs for s in v["sections"] for i in s["items"])
    assert changelog.parse("") == [] and changelog.parse("# Changelog\n\nNothing yet.\n") == []
    assert changelog.kind_of(" Bug  Fixes ") == "fixed" and changelog.kind_of("Known limits") == "known" and changelog.kind_of("Repository") == "other"


def test_read_again_only_when_the_file_changed(tmp_path, monkeypatch):
    f = tmp_path / "CHANGELOG.md"
    f.write_text("## [1.0.0] - 2026-01-01\n\n### Added\n\n- One.\n", encoding="utf-8")
    calls = []
    real = changelog.parse
    monkeypatch.setattr(changelog, "parse", lambda t: calls.append(1) or real(t))
    assert changelog.versions(f)[0]["sections"][0]["items"] == ["One."]
    got = changelog.versions(f)
    assert len(calls) == 1                                                    # the same file: not read again
    got[0]["version"] = "changed by a caller"
    assert changelog.versions(f)[0]["version"] == "1.0.0"                     # (what was handed out is a copy)
    f.write_text("## [1.0.1] - 2026-01-02\n\n### Fixed\n\n- Two.\n", encoding="utf-8")
    os.utime(f, (time.time() + 5, time.time() + 5))
    assert changelog.versions(f)[0]["version"] == "1.0.1" and len(calls) == 2
    assert changelog.versions(tmp_path / "missing.md") == []


# ── licences ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_components_and_their_licence_texts():
    cs = licenses.components()
    names = {licenses.canonical(c["name"]): c for c in cs}
    assert "fastapi" in names and names["fastapi"]["direct"] and names["fastapi"]["version"]
    assert "starlette" in names and not names["starlette"]["direct"]           # what a dependency depends on, too
    assert "pytest" not in names                                                # a tool of the tests is not a component
    assert all(set(c) >= {"name", "version", "license", "direct", "summary", "homepage"} for c in cs)
    assert [licenses.canonical(c["name"]) for c in cs] == sorted(licenses.canonical(c["name"]) for c in cs)
    t = licenses.text("FastAPI")                                                # any spelling of a listed name
    assert t["name"].lower() == "fastapi" and t["version"] == names["fastapi"]["version"]
    assert "MIT" in t["license"] and "Permission is hereby granted" in t["text"] and t["file"].endswith("LICENSE") and t["file"] in t["files"]
    for bad in ("../../etc/passwd", "fastapi/../../x", "", "pytest", "not-a-package-at-all"):
        assert licenses.text(bad) is None


def test_licence_names_from_metadata():
    class M(dict):
        def get_all(self, k):
            return self.get("_" + k)
    assert licenses._license_of(M({"License-Expression": "MIT"})) == "MIT"
    assert licenses._license_of(M({"License": "Apache 2.0"})) == "Apache 2.0"
    assert licenses._license_of(M({"License": "Copyright (c) x\n\nPermission is...", "_Classifier": ["License :: OSI Approved :: BSD License"]})) == "BSD License"
    assert licenses._license_of(M({})) == ""
    assert licenses._requirement('uvicorn[standard]>=0.54; python_version < "4"') == ("uvicorn", {"standard"}, 'python_version < "4"')
    assert licenses._applies("extra == 'standard'", {"standard"}) and not licenses._applies("extra == 'test'", set())


# ── the endpoints ────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def client(app_env):
    from fastapi.testclient import TestClient

    from autoapply.api.main import app

    return TestClient(app)


def test_endpoints(client):
    r = client.get("/api/about/changelog").json()
    assert r["current"] and isinstance(r["repo"], str)
    assert r["versions"] == changelog.versions(config.ROOT / "CHANGELOG.md") and any(v["version"] == "2.0.2" for v in r["versions"])
    cs = client.get("/api/about/licenses").json()["components"]
    assert any(c["name"].lower() == "fastapi" for c in cs)
    one = client.get("/api/about/licenses/fastapi")
    assert one.status_code == 200 and "Permission is hereby granted" in one.json()["text"]
    for bad in ("not-a-component", "pytest", "%2E%2E", "fastapi..", "LICENSE"):
        r = client.get("/api/about/licenses/" + bad)
        assert r.status_code == 404 and r.json() == {"detail": "not-a-component"}, bad
    # a name with a slash in it is not a name: the address is not this endpoint's, and an API address that nothing
    # answers is a 404 (not the interface's page) - nothing is read from it
    for bad in ("..%2F..%2Fetc%2Fpasswd", "fastapi%2F..%2F..%2Fx", "fastapi/../../etc"):
        r = client.get("/api/about/licenses/" + bad)
        assert r.status_code == 404 and not r.headers["content-type"].startswith("text/html"), bad
        assert "Permission is hereby granted" not in r.text and '"text"' not in r.text
