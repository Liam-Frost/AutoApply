"""Only forwards (2026-11-23): an installation running 2.1.0 showed "switching to 2.0.2" - a switch asked for on
2026-11-22 that a later version had overtaken. Nothing goes back to an older version unless the applicant asks to go
back; a state left by an earlier switch is not shown as a switch under way; and a version the tray switches to by a
rolling restart does the start a plain start does - it skipped all of it, so that state was never settled.
"""
from __future__ import annotations

import pytest

from autoapply import config, db


@pytest.fixture()
def managed(app_env, monkeypatch):
    from autoapply import updates

    monkeypatch.setattr(updates, "kind", lambda: "managed")
    monkeypatch.setattr(updates, "version", lambda: "2.1.0")
    told = []
    monkeypatch.setattr(updates, "_tell", lambda what, ver: told.append((what, ver)))
    rel = config.DATA / "releases"
    for name, ver in (("2.0.2", "2.0.2"), ("2026-11-23-v2.1.0", "2.1.0"), ("2026-11-22-calendar", "2.0.0"), ("2.2.0", "2.2.0")):
        (rel / name / "frontend" / "dist").mkdir(parents=True)
        (rel / name / "frontend" / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
        (rel / name / "pyproject.toml").write_text(f'[project]\nversion = "{ver}"\n', encoding="utf-8")
    return {"updates": updates, "told": told, "run": config.DATA / "run"}


def test_nothing_switches_to_an_older_or_the_same_version_by_itself(managed):
    updates = managed["updates"]
    for target in ("2.0.2", "2026-11-23-v2.1.0", "2026-11-22-calendar"):
        with pytest.raises(ValueError, match="not-newer"):
            updates.switch(target)
    assert not (managed["run"] / "restart-request").exists() and not (managed["run"] / "next-release").exists()
    db.set_setting("update.state", {"staged": "2.0.2"})
    with pytest.raises(ValueError, match="not-newer"):
        updates.switch()                               # (what was prepared, when it is behind what runs)
    st = updates.switch("2.2.0")                       # forwards: as before
    assert st["switching_to"] == "2.2.0" and (managed["run"] / "restart-request").read_text(encoding="utf-8") == "2.2.0"


def test_going_back_is_the_applicants_own_action(managed):
    updates = managed["updates"]
    db.set_setting("update.state", {"previous": "2026-11-22-calendar"})
    st = updates.rollback()
    assert st["switching_to"] == "2026-11-22-calendar" and updates.state()["switching_back"] is True


def test_a_switch_left_from_before_is_not_shown_as_one_under_way(managed):
    updates = managed["updates"]
    # the installation's own state on 2026-11-23: a switch to 2.0.2 asked for on 2026-11-22, and 2.1.0 running
    db.set_setting("update.state", {"latest": "2.0.2", "staged": "2.0.2", "status": "ready", "switching_to": "2.0.2", "previous": "2026-11-22-calendar",
                                    "history": [{"from": "2.0.0", "to": "2.0.2", "at": "2026-11-22T15:11"}]})
    st = updates.status()
    assert st["switching_to"] == "" and st["staged"] == "" and st["newer"] is False
    # a switch the tray has not taken yet is
    managed["run"].mkdir(parents=True, exist_ok=True)
    (managed["run"] / "restart-request").write_text("2.0.2", encoding="utf-8")
    assert updates.status()["switching_to"] == "2.0.2"


def test_at_start_an_overtaken_switch_is_forgotten_without_a_word(managed):
    updates = managed["updates"]
    db.set_setting("update.state", {"latest": "2.0.2", "staged": "2.0.2", "status": "ready", "switching_to": "2.0.2"})
    updates.after_start()
    s = updates.state()
    assert s["switching_to"] == "" and s["status"] == "idle" and s.get("failed_switch") == "" and s.get("error") == ""
    assert managed["told"] == []                       # (not "the new version did not start": nothing failed)
    # a switch forwards that did not happen is still said as a failure, and so is a way back that did not happen
    for to, back in (("2.2.0", False), ("2026-11-22-calendar", True)):
        managed["told"].clear()
        db.set_setting("update.state", {"status": "idle", "switching_to": to, "switching_back": back})
        updates.after_start()
        assert updates.state()["failed_switch"] == to and managed["told"] == [("failed", to)]


def test_update_when_idle_to_a_version_that_is_not_newer_is_dropped(managed, monkeypatch):
    updates = managed["updates"]
    monkeypatch.setattr(updates, "idle", lambda: True)
    db.set_setting("update.mode", "off")
    db.set_setting("update.state", {"staged": "2.0.2", "when_idle": "2.0.2"})
    assert updates.tick() == "" and updates.state()["when_idle"] == ""
    assert not (managed["run"] / "restart-request").exists()


def test_a_rolling_restart_makes_the_joining_worker_the_primary_with_its_whole_start(app_env, monkeypatch):
    from autoapply import access
    from autoapply.api import main

    ran = []
    monkeypatch.setattr(main, "_start_up", lambda: ran.append("start-up"))
    monkeypatch.setattr(main.net, "apply", lambda: ran.append("network"))
    import autoapply.bots as bots

    monkeypatch.setattr(bots, "start", lambda: ran.append("bots"))
    monkeypatch.setattr(main, "_primary", {"started": False, "bots": False})
    started = []

    class NowThread:          # (the endpoint starts it in the background; here it runs at once)
        def __init__(self, target, **k):
            self.target = target

        def start(self):
            started.append(1)
            self.target()

    monkeypatch.setattr(main.threading, "Thread", NowThread)
    monkeypatch.setattr(main.tasks, "activate_scheduler", lambda: ran.append("scheduler"))

    class Req:
        headers = {access.LOCAL_HEADER: access.local_token()}

    assert main.activate_scheduler(Req()) == {"ok": True}
    assert ran == ["scheduler", "start-up", "network", "bots"] and started == [1]
    ran.clear()
    main.activate_scheduler(Req())                      # (once per process: a second activation starts nothing again)
    assert ran == ["scheduler"]
