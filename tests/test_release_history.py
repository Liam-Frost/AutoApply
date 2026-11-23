"""The history moved from the hand-written CHANGELOG.md into change fragments and release manifests: nothing lost,
nothing invented.

`changes/legacy/CHANGELOG-2.0.2.md` is that changelog as it was before release engineering moved to `changes/` (frozen:
its hash is pinned here). Every list item and paragraph of it - of each released version and of [Unreleased] - is found
word for word (whitespace aside) in exactly one place of its own version: a fragment's details, the manifest's intro or
its known limits; and in no other version. A fragment that holds legacy text holds nothing else.

The files are read here with a small reader of the formats in docs/release-architecture.md, not with autoapply.release,
so that the data is checked against the contract on its own; `test_the_release_model_accepts_the_history` then asks the
model too, when it is there.

[Unreleased] became pending fragments. Other pending fragments may be added beside them (every change from now on is
one); the legacy ones stay together - all pending, or all in the one release that follows 2.0.2.
"""
import hashlib
import json
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
CHANGES = ROOT / "changes"
LEGACY = CHANGES / "legacy" / "CHANGELOG-2.0.2.md"
LEGACY_SHA256 = "9369045df61badff46897d37348573e8ebe06e04e0a22a1e75afca43ec98cdb3"
TAG_ERA = ["1.0.0", "1.0.1", "1.0.2", "1.0.3", "1.0.4", "2.0.0", "2.0.2"]   # the tags v1.0.0 - v2.0.2 (2.0.1 folded)
UNRELEASED = "Unreleased"
ID_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{4}$")
CONTRACT_TYPES = ["added", "changed", "deprecated", "removed", "fixed", "security"]
CONTRACT_SCOPES = ["postings", "applications", "agent", "mail", "calendar", "notifications", "profile", "files",
                   "accounts", "analytics", "ai", "settings", "updates", "ui", "i18n", "packages", "server", "release"]

VERSION_RE = re.compile(r"^## \[([^\]]+)\](?: - (\d{4}-\d{2}-\d{2}))?\s*$")
LINKREF_RE = re.compile(r"^\[[^\]]+\]: https?://")


def norm(text: str) -> str:
    return " ".join(text.split())


# --- the legacy changelog -----------------------------------------------------------------------------------------------
def parse_legacy(text: str) -> dict:
    """{version: {"date", "units": [{"section", "kind", "text"}]}}. A unit is a top-level list item (without its "- ",
    continuation lines and nested items included) or a paragraph outside a list; section None is the version's intro."""
    versions: dict = {}
    cur = unit = None
    section = None
    blanks = 0
    for line in text.split("\n"):
        m = VERSION_RE.match(line)
        if m:
            cur = versions[m.group(1)] = {"date": m.group(2) or "", "units": []}
            section, unit, blanks = None, None, 0
            continue
        if cur is None or LINKREF_RE.match(line):
            continue
        if line.startswith("### "):
            section, unit, blanks = line[4:].strip(), None, 0
            continue
        if not line.strip():
            blanks += 1
            continue
        if line.startswith("- "):
            unit = {"section": section, "kind": "bullet", "lines": [line[2:]]}
            cur["units"].append(unit)
        elif unit is not None and (line.startswith(" ") or not blanks):
            unit["lines"].append(line)          # continuation (indented, or a lazy line right after)
        else:
            unit = {"section": section, "kind": "para", "lines": [line]}
            cur["units"].append(unit)
        blanks = 0
    for v in versions.values():
        for u in v["units"]:
            u["text"] = norm(" ".join(u.pop("lines")))
    return versions


# --- fragments and manifests --------------------------------------------------------------------------------------------
def read_fragment(path: Path) -> dict:
    data = path.read_bytes()
    text = data.decode("utf-8").replace("\r\n", "\n")
    assert text.startswith("---\n"), f"{path.name}: no front matter"
    end = text.index("\n---\n", 3)
    meta = yaml.safe_load(text[4:end + 1])
    assert isinstance(meta, dict), f"{path.name}: front matter is not a mapping"
    return {"meta": meta, "details": text[end + 5:].strip(), "sha256": hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()}


@pytest.fixture(scope="module")
def legacy():
    return parse_legacy(LEGACY.read_bytes().decode("utf-8"))


@pytest.fixture(scope="module")
def fragments():
    return {p.name[:-3]: read_fragment(p) for p in sorted((CHANGES / "fragments").glob("*.md"))}


@pytest.fixture(scope="module")
def manifests():
    return {p.name[:-5]: json.loads(p.read_text(encoding="utf-8")) for p in sorted((CHANGES / "releases").glob("*.json"))}


@pytest.fixture(scope="module")
def released(manifests):
    """{fragment id: [versions whose manifest names it]}"""
    out: dict = {}
    for version, m in manifests.items():
        for e in m.get("fragments", []):
            out.setdefault(e["id"], []).append(version)
    return out


@pytest.fixture(scope="module")
def holds(legacy, fragments):
    """{fragment id: {version: [legacy unit texts its details hold]}} - fragments holding no legacy text left out."""
    out: dict = {}
    for fid, f in fragments.items():
        details = norm(f["details"])
        for version, v in legacy.items():
            texts = [u["text"] for u in v["units"] if u["text"] in details]
            if texts:
                out.setdefault(fid, {})[version] = texts
    return out


@pytest.fixture(scope="module")
def places(legacy, fragments, manifests, released):
    """{version: [(where, normalized text)]}: where a version's legacy text may be. A tag-era version: its manifest's
    fragments, intro and known limits; [Unreleased]: every fragment no tag-era manifest names."""
    out = {}
    for version in TAG_ERA:
        m = manifests.get(version, {})
        ps = [(f"fragment {e['id']}", norm(fragments[e["id"]]["details"]))
              for e in m.get("fragments", []) if e["id"] in fragments]
        if m.get("intro"):
            ps.append((f"{version} intro", norm(m["intro"])))
        ps += [(f"{version} known limit {i}", norm(t)) for i, t in enumerate(m.get("known_limits", []))]
        out[version] = ps
    out[UNRELEASED] = [(f"fragment {fid}", norm(f["details"])) for fid, f in fragments.items()
                       if not set(released.get(fid, [])) & set(TAG_ERA)]
    return out


# --- the tests ----------------------------------------------------------------------------------------------------------
def test_the_legacy_changelog_is_frozen():
    assert hashlib.sha256(LEGACY.read_bytes()).hexdigest() == LEGACY_SHA256, (
        "changes/legacy/CHANGELOG-2.0.2.md is the evidence of the migration and is never edited")


def test_every_tagged_version_has_a_manifest_with_the_legacy_date(legacy, manifests):
    assert [v for v in legacy if v != UNRELEASED] == list(reversed(TAG_ERA))
    for version in TAG_ERA:
        m = manifests.get(version)
        assert m is not None, f"changes/releases/{version}.json is missing"
        assert m["version"] == version
        assert m["date"] == legacy[version]["date"], version
        assert m["title"].get("en") and m["title"].get("zh"), f"{version}: a title in en and zh"


def test_intro_and_known_limits_are_the_legacy_ones(legacy, manifests):
    for version in TAG_ERA:
        units = legacy[version]["units"]
        intro = " ".join(u["text"] for u in units if u["section"] is None)
        limits = [u["text"] for u in units if u["section"] == "Known limits"]
        m = manifests[version]
        assert norm(m.get("intro", "")) == intro, version
        assert [norm(t) for t in m.get("known_limits", [])] == limits, version


@pytest.mark.parametrize("version", TAG_ERA + [UNRELEASED])
def test_every_legacy_item_is_in_exactly_one_place_of_its_version(version, legacy, places):
    all_texts = [u["text"] for v in legacy.values() for u in v["units"]]
    missing, twice = [], []
    for u in legacy[version]["units"]:
        found = [where for where, text in places[version] if u["text"] in text]
        inside_another = sum(1 for t in all_texts if u["text"] in t) > 1     # a short item another one quotes
        if not found:
            missing.append(u["text"][:100])
        elif len(found) > 1 and not inside_another:
            twice.append((u["text"][:100], found))
    assert not missing, f"{version}: legacy text found nowhere:\n" + "\n".join(missing)
    assert not twice, f"{version}: legacy text in more than one place: {twice}"


def test_no_legacy_item_is_in_another_version(legacy, places):
    wrong = []
    for version, v in legacy.items():
        for u in v["units"]:
            for other, ps in places.items():
                if other == version or any(u["text"] in w["text"] for w in legacy[other]["units"]):
                    continue
                wrong += [(version, other, where, u["text"][:80]) for where, text in ps if u["text"] in text]
    assert not wrong, wrong


def test_a_history_fragment_holds_only_legacy_text_of_one_version(fragments, holds, released):
    for fid, by_version in holds.items():
        assert len(by_version) == 1, f"{fid} holds text of {sorted(by_version)}"
        (version, texts), = by_version.items()
        rest = norm(fragments[fid]["details"])
        for t in sorted(texts, key=len, reverse=True):
            rest = rest.replace(t, " ", 1)
        assert not rest.replace("-", "").strip(), f"{fid}: details that are not in the legacy changelog: {rest[:200]!r}"
        tagged = [r for r in released.get(fid, []) if r in TAG_ERA]
        if version == UNRELEASED:
            assert not tagged, f"{fid} is [Unreleased] text in the manifest of {tagged}"
        else:
            assert tagged == [version], f"{fid} holds {version} text and is in {released.get(fid, [])}"


def test_every_fragment_of_a_tagged_release_is_history(manifests, holds):
    for version in TAG_ERA:
        for e in manifests[version]["fragments"]:
            assert e["id"] in holds, f"{version} names {e['id']}, which holds no text of the legacy changelog"


def test_no_fragment_is_in_two_manifests_and_hashes_match(fragments, manifests, released):
    assert {fid: vs for fid, vs in released.items() if len(vs) > 1} == {}
    for version, m in manifests.items():
        corrected = {c["id"]: c["sha256"] for c in m.get("corrections", [])}
        for e in m["fragments"]:
            assert e["id"] in fragments, f"{version} names {e['id']}, which does not exist"
            assert fragments[e["id"]]["sha256"] == corrected.get(e["id"], e["sha256"]), f"{e['id']} changed after {version}"


def test_unreleased_became_pending_fragments_that_stay_together(holds, released):
    unreleased = sorted(fid for fid, by in holds.items() if UNRELEASED in by)
    assert unreleased, "[Unreleased] has no fragments"
    homes = {tuple(released.get(fid, [])) for fid in unreleased}
    assert len(homes) == 1, f"the [Unreleased] fragments are split: {homes}"
    home, = homes
    assert home == () or (len(home) == 1 and home[0] not in TAG_ERA), home


def test_fragment_fields(fragments, holds, legacy):
    schema = CHANGES / "schema" / "fragment.schema.json"
    types, scopes = CONTRACT_TYPES, CONTRACT_SCOPES
    if schema.exists():
        props = json.loads(schema.read_text(encoding="utf-8"))["properties"]
        types, scopes = props["type"]["enum"], props["scope"]["enum"]
    after_last = legacy["2.0.2"]["date"]
    for fid, by_version in holds.items():
        (version, _), = by_version.items()
        meta = fragments[fid]["meta"]
        m = ID_RE.match(fid)
        assert m and meta.get("id") == fid, fid
        if version == UNRELEASED:
            assert m.group(1) > after_last, fid
        else:
            assert m.group(1) == legacy[version]["date"], f"{fid}: dated as its release"
        assert meta.get("type") in types and meta.get("scope") in scopes, fid
        s = meta.get("summary") or {}
        assert s.get("en") and s.get("zh"), f"{fid}: a summary in en and zh"
        assert len(s["en"]) <= 120 and "\n" not in s["en"], fid
        assert not re.search(r"[一-鿿]", s["en"]) and re.search(r"[一-鿿]", s["zh"]), fid
        if meta.get("highlight"):
            assert s.get("fr"), f"{fid}: a highlight has its French summary"
        assert set(meta) <= {"id", "type", "scope", "summary", "highlight", "bump", "pr"}, fid


def test_three_to_six_highlights_per_version(fragments, holds):
    per: dict = {}
    for fid, by_version in holds.items():
        (version, _), = by_version.items()
        per.setdefault(version, []).append(fragments[fid]["meta"].get("highlight") is True)
    assert sorted(per) == sorted(TAG_ERA + [UNRELEASED])
    for version, flags in per.items():
        assert 3 <= sum(flags) <= 6, f"{version}: {sum(flags)} highlights"


def test_only_2_0_0_declares_a_bump(fragments, holds):
    bumps = {fid: fragments[fid]["meta"]["bump"] for fid in holds if fragments[fid]["meta"].get("bump")}
    assert list(bumps.values()) == ["major"], bumps
    fid, = bumps
    assert "2.0.0" in holds[fid] and fragments[fid]["meta"].get("highlight") is True


def test_the_release_model_accepts_the_history(holds):
    release = pytest.importorskip("autoapply.release")
    if not hasattr(release, "validate"):
        pytest.skip("autoapply.release has no validate() yet")
    mine ={f"changes/fragments/{fid}.md" for fid in holds} | {f"changes/releases/{v}.json" for v in TAG_ERA}
    errors = [p for p in release.validate(ROOT) if p.level == "error" and p.path in mine]
    assert not errors, "\n".join(str(p) for p in errors)
