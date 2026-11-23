"""What the about page is told about releases (updates.status(), about.info()): every folder of data/releases named as
a person reads it - its version from its own pyproject.toml, its day, whether it was put there by hand - and the
fields the page read before, unchanged. Only the test's own data folder: fake releases are made under it."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

OLD_FIELDS = {"current", "kind", "mode", "channel", "window", "latest", "newer", "url", "notes", "published", "prerelease", "checked_at", "status",
              "progress", "error", "staged", "previous", "history"}


def _release(name: str, version: str | None, *, dist: bool = True) -> Path:
    """A release folder as the updater or scripts/stage_local_release.py leaves it: its pyproject.toml and its built
    interface."""
    from autoapply import config

    d = config.DATA / "releases" / name
    d.mkdir(parents=True)
    if version is not None:
        (d / "pyproject.toml").write_text(f'[project]\nname = "autoapply"\nversion = "{version}"\n', encoding="utf-8")
    if dist:
        (d / "frontend" / "dist").mkdir(parents=True)
        (d / "frontend" / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
    return d


@pytest.fixture()
def here(app_env, monkeypatch):
    """This copy is 2.0.2, managed by the tray."""
    from autoapply import updates

    monkeypatch.setattr(updates, "version", lambda: "2.0.2")
    monkeypatch.setattr(updates, "kind", lambda: "managed")
    return updates


def test_a_release_folder_is_named_by_its_version_its_day_and_how_it_came(here):
    from autoapply import updates

    _release("2026-11-22-calendar", "2.0.2")
    assert updates.release("2026-11-22-calendar") == {"name": "2026-11-22-calendar", "version": "2.0.2", "date": "2026-11-22", "local": True}
    d = _release("2.0.3", "2.0.3")                       # (the updater names the folder by the version it fetched)
    stamp = datetime(2026, 11, 20, 9, 30).timestamp()
    os.utime(d / "frontend" / "dist" / "index.html", (stamp, stamp))
    assert updates.release("2.0.3") == {"name": "2.0.3", "version": "2.0.3", "date": "2026-11-20", "local": False}      # (its day: when it was built or unpacked)
    _release("my-build", None)                           # no pyproject.toml: no version is made up
    assert updates.release("my-build")["version"] == "" and updates.release("my-build")["local"] is True
    _release("2026-13-45-odd", "2.0.2")                  # not a day: the file's time instead
    assert updates.release("2026-13-45-odd")["date"] == datetime.now().date().isoformat()
    assert updates.release("") is None and updates.release("gone") is None and updates.release("..") is None and updates.release("a/b") is None


def test_status_names_the_staged_and_the_previous_release(here):
    from autoapply import db, updates

    _release("2.0.3", "2.0.3")
    _release("2026-11-22-calendar", "2.0.2")
    db.set_setting(updates.STATE, {"latest": "2.0.3", "staged": "2.0.3", "status": "ready", "previous": "2026-11-22-calendar",
                                   "checked_at": "2026-11-23T10:00"})
    st = updates.status()
    assert st["staged"] == "2.0.3" and st["staged_release"] == {"name": "2.0.3", "version": "2.0.3", "date": st["staged_release"]["date"], "local": False}
    assert st["previous"] == "2026-11-22-calendar"                                    # (the raw name stays what it was)
    assert st["previous_release"] == {"name": "2026-11-22-calendar", "version": "2.0.2", "date": "2026-11-22", "local": True}
    assert st["switching_to"] == "" and st["switching_release"] is None and st["pending"] == "" and st["pending_release"] is None
    assert st["build"] == "" and st["build_release"] is None                          # (this copy runs from its own folder)


def test_a_previous_release_that_is_gone_is_not_named(here):
    from autoapply import db, updates

    _release("2026-11-22-calendar", "2.0.2", dist=False)          # its interface is gone: nothing to go back to
    db.set_setting(updates.STATE, {"previous": "2026-11-22-calendar"})
    st = updates.status()
    assert st["previous"] == "" and st["previous_release"] is None


def test_staged_equal_to_the_running_version_is_not_offered(here):
    from autoapply import db, updates

    _release("2.0.2", "2.0.2")
    db.set_setting(updates.STATE, {"latest": "2.0.2", "staged": "2.0.2", "status": "ready"})
    st = updates.status()
    assert st["staged"] == "" and st["staged_release"] is None and st["status"] == "idle" and st["newer"] is False


def test_the_running_build_is_named_when_it_runs_from_a_release_folder(here, monkeypatch):
    from fastapi.testclient import TestClient

    from autoapply import about, config, updates
    from autoapply.api.main import app

    d = _release("2026-11-23-design-system", "2.0.2")
    assert about.info()["build"] == "" and about.info()["build_release"] is None      # (a checkout or an installation's own folder)
    monkeypatch.setattr(config, "ROOT", d)
    info = about.info()
    assert info["build"] == "2026-11-23-design-system"
    assert info["build_release"] == {"name": "2026-11-23-design-system", "version": "2.0.2", "date": "2026-11-23", "local": True}
    st = updates.status()
    assert st["build"] == "2026-11-23-design-system" and st["build_release"]["date"] == "2026-11-23"
    # what the page read before is all still there, the same
    assert {"version", "commit", "kind", "python", "system", "data", "repo", "components"} <= set(info)
    c = TestClient(app)
    assert c.get("/api/about").json()["build"] == "2026-11-23-design-system"
    assert OLD_FIELDS <= set(c.get("/api/system/update").json())


def test_a_switch_under_way_and_a_release_staged_for_the_next_start(here, monkeypatch):
    from autoapply import config, db, updates

    _release("2.0.3", "2.0.3")
    db.set_setting(updates.STATE, {"latest": "2.0.3", "staged": "2.0.3", "status": "ready"})
    updates.switch()
    st = updates.status()
    assert st["switching_to"] == "2.0.3" and st["switching_release"]["version"] == "2.0.3"
    assert st["pending"] == ""                                     # (the marker names the switch under way: said once)
    db.set_setting(updates.STATE, {"latest": "2.0.3"})              # (the switch is over; a build of one's own is staged by hand)
    _release("2026-11-24-mine", "2.0.4")
    (config.DATA / "run" / "next-release").write_text("2026-11-24-mine", encoding="utf-8")
    st = updates.status()
    assert st["switching_to"] == "" and st["pending"] == "2026-11-24-mine" and st["pending_release"]["version"] == "2.0.4"
    (config.DATA / "run" / "next-release").write_text("../outside", encoding="utf-8")
    assert updates.status()["pending"] == ""                       # (a name the tray would refuse is not offered)
    db.set_setting(updates.STATE, {"latest": "2.0.3", "when_idle": "2.0.3"})
    assert updates.status()["when_idle"] == "2.0.3"


def test_the_fields_the_page_read_before_are_unchanged(here):
    from autoapply import db, updates

    db.set_setting(updates.STATE, {"latest": "2.0.3", "url": "https://example.test/r", "notes": "n", "published": "2026-11-22", "prerelease": False,
                                   "checked_at": "2026-11-23T10:00", "status": "downloading", "progress": 40, "error": ""})
    st = updates.status()
    assert OLD_FIELDS <= set(st)
    assert (st["current"], st["kind"], st["mode"], st["channel"], st["latest"], st["newer"], st["status"], st["progress"], st["staged"], st["previous"]) == \
        ("2.0.2", "managed", "notify", "stable", "2.0.3", True, "downloading", 40, "", "")
