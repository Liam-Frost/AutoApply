"""The about page's changelog and licences: the release history adapter (backend/autoapply/changelog.py - releases.json
and the pending change fragments), the components the program runs on with their licence texts (licenses.py), and the
endpoints that give them."""
import json
import os
import sys
import time
import types
from pathlib import Path

import pytest

import autoapply
from autoapply import changelog, licenses

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = Path(__file__).resolve().parent / "fixtures" / "releases.sample.json"      # made up, shaped as releases.json
RELEASE_ENTRY = {"version", "date", "title", "intro", "known_limits", "url", "changes"}
CHANGE_ENTRY = {"id", "type", "scope", "summary", "details", "highlight"}

PENDING = {"version": "Unreleased", "date": "", "title": {}, "intro": "", "known_limits": [], "url": "",
           "changes": [{"id": "2031-03-10-made-up-pending-ab12", "type": "added", "scope": "ui", "summary": {"en": "A made-up pending change"},
                        "details": "", "highlight": False}]}


def _release_model(monkeypatch, pending_entry):
    """`autoapply.release` as the runtime sees it: a module whose pending_entry() is the one given, or (None) missing."""
    if pending_entry is None:
        monkeypatch.setitem(sys.modules, "autoapply.release", None)          # (an import of it raises ImportError)
        monkeypatch.delattr(autoapply, "release", raising=False)
        return
    fake = types.ModuleType("autoapply.release")
    fake.pending_entry = pending_entry
    monkeypatch.setitem(sys.modules, "autoapply.release", fake)
    monkeypatch.setattr(autoapply, "release", fake, raising=False)


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(changelog, "_cache", {"key": None, "releases": []})


# ── releases.json ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_releases_in_the_order_of_the_file_each_marked_released(monkeypatch):
    _release_model(monkeypatch, None)
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    vs = changelog.versions(SAMPLE)
    assert [v["version"] for v in vs] == [r["version"] for r in data["releases"]] == ["9.2.0", "9.1.1", "9.1.0", "9.0.0"]
    for v, r in zip(vs, data["releases"]):
        assert v == dict(r, unreleased=False)                                # passed on as written, plus `unreleased`
        assert set(v) == RELEASE_ENTRY | {"unreleased"}
        assert all(set(c) == CHANGE_ENTRY for c in v["changes"])
    assert [c["id"] for c in vs[0]["changes"]] == [c["id"] for c in data["releases"][0]["changes"]]        # manifest order kept


def test_the_unreleased_entry_comes_first(monkeypatch):
    calls = []
    _release_model(monkeypatch, lambda root=None: calls.append(root) or json.loads(json.dumps(PENDING)))
    vs = changelog.versions(SAMPLE)
    assert [(v["version"], v["unreleased"]) for v in vs] == [("Unreleased", True), ("9.2.0", False), ("9.1.1", False), ("9.1.0", False), ("9.0.0", False)]
    assert vs[0] == dict(PENDING, unreleased=True) and calls == [None]       # (the program's own root: config.ROOT)
    # nothing pending - None, or an entry without changes - is no entry
    for nothing in (None, dict(PENDING, changes=[]), "not an entry"):
        _release_model(monkeypatch, lambda root=None, n=nothing: n)
        assert [v["version"] for v in changelog.versions(SAMPLE)] == ["9.2.0", "9.1.1", "9.1.0", "9.0.0"]


def test_without_the_release_model_or_when_it_fails_the_history_is_still_shown(monkeypatch, caplog):
    _release_model(monkeypatch, None)                                        # not there (a package without it, an old checkout)
    assert changelog.pending() is None
    assert [v["version"] for v in changelog.versions(SAMPLE)] == ["9.2.0", "9.1.1", "9.1.0", "9.0.0"]

    def broken(root=None):
        raise ValueError("a fragment it cannot read")
    _release_model(monkeypatch, broken)
    assert [v["unreleased"] for v in changelog.versions(SAMPLE)] == [False] * 4
    assert "pending changes were not read" in caplog.text


def test_without_releases_json_only_what_is_pending(monkeypatch, tmp_path, caplog):
    _release_model(monkeypatch, lambda root=None: json.loads(json.dumps(PENDING)))
    assert [v["version"] for v in changelog.versions(tmp_path / "no-releases.json")] == ["Unreleased"]
    _release_model(monkeypatch, None)
    assert changelog.versions(tmp_path / "no-releases.json") == []
    # a file that is not the generator's: nothing from it, said in the log, and no error for the page
    f = tmp_path / "broken.json"
    for i, bad in enumerate(("{ not json", '["a list"]', '{"releases": "none"}', b"\xff\xfe\x00")):
        f.write_bytes(bad if isinstance(bad, bytes) else bad.encode("utf-8"))
        os.utime(f, (time.time() + 10 * (i + 1),) * 2)                     # (a new mtime each time: read again)
        assert changelog.versions(f) == [], bad
    assert "the changelog shows no" in caplog.text
    # entries that are not releases are left out, the others kept
    f.write_text(json.dumps({"releases": [{"version": "1.0.0", "changes": []}, "x", {"version": ""}, {"date": "2030-01-01"}]}), encoding="utf-8")
    os.utime(f, (time.time() + 99,) * 2)
    assert changelog.versions(f) == [{"version": "1.0.0", "changes": [], "unreleased": False}]


def test_releases_json_is_read_once_per_change_of_the_file(monkeypatch, tmp_path):
    _release_model(monkeypatch, None)
    f = tmp_path / "releases.json"
    f.write_text(SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    calls = []
    real = changelog._load
    monkeypatch.setattr(changelog, "_load", lambda p: calls.append(p) or real(p))
    assert changelog.versions(f)[0]["version"] == "9.2.0"
    got = changelog.versions(f)
    assert len(calls) == 1                                                    # the same file: not read again
    got[0]["changes"].clear()
    got[0]["version"] = "changed by a caller"
    again = changelog.versions(f)
    assert again[0]["version"] == "9.2.0" and len(again[0]["changes"]) == 9  # (what was handed out is a copy)
    data = json.loads(f.read_text(encoding="utf-8"))
    data["releases"] = data["releases"][1:]
    f.write_text(json.dumps(data), encoding="utf-8")
    os.utime(f, (time.time() + 5, time.time() + 5))
    assert changelog.versions(f)[0]["version"] == "9.1.1" and len(calls) == 2
    assert changelog.versions(tmp_path / "missing.json") == [] and len(calls) == 2


def test_the_default_file_is_the_one_next_to_the_module():
    assert changelog.RELEASES == ROOT / "backend" / "autoapply" / "releases.json"


def _semver(v):
    core, _, pre = v.partition("-")
    return tuple(int(x) for x in core.split(".")), (pre == "", pre)


def test_the_programs_own_release_data(monkeypatch):
    """The generated releases.json (the lead writes it with the release tool at integration): the shape the page reads,
    newest first, and what the adapter gives is that."""
    if not changelog.RELEASES.exists():
        pytest.skip("backend/autoapply/releases.json is not generated yet")
    _release_model(monkeypatch, None)
    data = json.loads(changelog.RELEASES.read_text(encoding="utf-8"))
    assert data["schema"] == 1 and isinstance(data["repo"], str) and data["releases"]
    for r in data["releases"]:
        assert set(r) == RELEASE_ENTRY and r["title"]["en"] and r["date"] and r["url"].startswith("https://"), r["version"]
        for c in r["changes"]:
            assert set(c) == CHANGE_ENTRY and c["summary"]["en"] and c["type"] in ("added", "changed", "deprecated", "removed", "fixed", "security"), c["id"]
    names = [r["version"] for r in data["releases"]]
    assert names == sorted(names, key=_semver, reverse=True)
    assert changelog.versions() == [dict(r, unreleased=False) for r in data["releases"]]


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


def test_endpoints(client, monkeypatch):
    monkeypatch.setattr(changelog, "RELEASES", SAMPLE)
    _release_model(monkeypatch, lambda root=None: json.loads(json.dumps(PENDING)))
    r = client.get("/api/about/changelog").json()
    assert set(r) == {"current", "repo", "versions"} and r["current"] and isinstance(r["repo"], str)
    assert [v["version"] for v in r["versions"]] == ["Unreleased", "9.2.0", "9.1.1", "9.1.0", "9.0.0"]
    assert r["versions"] == changelog.versions()
    _release_model(monkeypatch, None)
    assert [v["unreleased"] for v in client.get("/api/about/changelog").json()["versions"]] == [False] * 4
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
