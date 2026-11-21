"""Updates (updates.py): looking for a release, fetching and checking it, preparing it next to the running version,
switching through the tray's restart, and what the program does by itself in each mode."""
from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import datetime
from pathlib import Path

import pytest


def _package(ver: str, *, extra: dict[str, str] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in {"frontend/dist/index.html": "<html></html>", "uv.lock": "version = 1", "pyproject.toml": f'version = "{ver}"',
                           "CHANGELOG.md": f"## [{ver}] - 2026-11-30\n\n- new\n", **(extra or {})}.items():
            z.writestr(f"AutoApply-{ver}/{name}", text)
    return buf.getvalue()


@pytest.fixture()
def release(app_env, tmp_path, monkeypatch):
    """A release 9.9.9 on a fake GitHub: its package and checksums, downloaded from local files; uv and the browser
    install recorded, not run; this copy managed by the tray."""
    from autoapply import config, db, updates

    pkg = _package("9.9.9")
    files = {"AutoApply-9.9.9.zip": pkg, "SHA256SUMS.txt": f"{hashlib.sha256(pkg).hexdigest()}  AutoApply-9.9.9.zip\n".encode()}
    db.set_setting("update.state", {"latest": "9.9.9", "assets": {n: f"https://example.test/{n}" for n in files}, "checked_at": datetime.now().isoformat()})
    monkeypatch.setattr(updates, "_download", lambda url, target, progress=False: Path(target).write_bytes(files[url.rsplit("/", 1)[1]]))
    monkeypatch.setattr(updates, "_uv", lambda: "uv")
    monkeypatch.setattr(updates, "kind", lambda: "managed")
    ran: list[list[str]] = []
    monkeypatch.setattr(updates.subprocess, "run", lambda args, **k: ran.append([str(a) for a in args]))
    told: list[tuple[str, str]] = []
    monkeypatch.setattr(updates, "_tell", lambda what, ver: told.append((what, ver)))
    return {"files": files, "ran": ran, "told": told, "releases": config.DATA / "releases", "run": config.DATA / "run"}


def test_check_takes_the_newest_release_of_the_channel(app_env, monkeypatch):
    from autoapply import db, updates

    rels = [{"tag_name": "v9.0.0", "html_url": "https://x/9", "body": "notes", "published_at": "2026-12-01T00:00:00Z",
             "assets": [{"name": "AutoApply-9.0.0.zip", "browser_download_url": "https://x/a.zip"}]},
            {"tag_name": "v9.1.0-beta.1", "prerelease": True}, {"tag_name": "v10.0.0", "draft": True}]

    class Gh:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def get(self, url, **k):
            assert url == "https://api.github.com/repos/someone/project/releases"       # only the repository set, and nothing about the applicant
            import httpx

            return httpx.Response(200, json=rels, request=httpx.Request("GET", url))

    import httpx

    monkeypatch.setattr(httpx, "Client", Gh)
    db.set_setting("update.repo", "someone/project")
    s = updates.check()
    assert s["latest"] == "9.0.0" and s["assets"]["AutoApply-9.0.0.zip"] == "https://x/a.zip" and updates.status()["newer"]
    db.set_setting("update.channel", "beta")                # pre-releases too; a draft never
    assert updates.check()["latest"] == "9.1.0-beta.1"


def test_prepare_fetches_checks_and_unpacks_beside_the_running_version(release):
    from autoapply import updates

    s = updates.prepare()
    assert s["status"] == "ready" and s["staged"] == "9.9.9", s
    assert (release["releases"] / "9.9.9" / "frontend" / "dist" / "index.html").is_file()
    assert any(a[:3] == ["uv", "sync", "--locked"] for a in release["ran"])               # its dependencies, from its own lock file
    assert any("playwright" in a for a in release["ran"])
    assert not (release["run"] / "next-release").exists()                                 # prepared is not switched: that is pressed (or "auto")
    assert release["told"] == [("ready", "9.9.9")]


def test_a_package_that_does_not_match_its_checksum_is_thrown_away(release):
    from autoapply import updates

    release["files"]["SHA256SUMS.txt"] = b"0" * 64 + b"  AutoApply-9.9.9.zip\n"
    s = updates.prepare()
    assert s["status"] == "failed" and s["error"] == "checksum" and not (release["releases"] / "9.9.9").exists() and not release["ran"]


def test_a_package_cannot_write_outside_its_folder(tmp_path):
    from autoapply import updates

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("AutoApply-1.0.0/ok.txt", "x")
        z.writestr("AutoApply-1.0.0/../../outside.txt", "x")
    with pytest.raises(ValueError):
        updates._unpack(evil, tmp_path / "into")
    assert not (tmp_path / "outside.txt").exists()


def test_switch_asks_the_tray_and_a_switch_that_did_not_take_is_said_once(release):
    from autoapply import config, updates

    updates.prepare()
    updates.switch()
    assert (release["run"] / "next-release").read_text(encoding="utf-8") == "9.9.9" and (release["run"] / "restart-request").is_file()
    # the new version did not start: the old one runs on, says so, and does not try again at the next restart or by itself
    updates.after_start()
    s = updates.state()
    assert s["status"] == "failed" and s["error"] == "did-not-start" and s["failed_switch"] == "9.9.9" and not (release["run"] / "next-release").exists()
    assert release["told"][-1] == ("failed", "9.9.9")
    updates.after_start()
    assert release["told"][-1] == ("failed", "9.9.9") and len(release["told"]) == 2       # once
    assert config.DATA.exists()


def test_after_a_switch_the_new_version_says_so_and_keeps_the_one_before(release, monkeypatch):
    from autoapply import config, updates

    old = release["releases"] / "2.0.0" / "frontend" / "dist"
    old.mkdir(parents=True)
    (old / "index.html").write_text("x", encoding="utf-8")
    (release["releases"] / "1.0.0").mkdir()                    # older than the one before: cleared away
    monkeypatch.setattr(config, "ROOT", release["releases"] / "2.0.0")
    updates.prepare()
    updates.switch()
    assert updates.state()["previous"] == "2.0.0"
    monkeypatch.setattr(config, "ROOT", release["releases"] / "9.9.9")
    monkeypatch.setattr(updates, "version", lambda: "9.9.9")
    updates.after_start()
    assert release["told"][-1] == ("switched", "9.9.9") and updates.status()["previous"] == "2.0.0"
    assert not (release["releases"] / "1.0.0").exists() and (release["releases"] / "2.0.0").exists()


def test_by_itself_each_mode_does_what_it_says(release, monkeypatch):
    from autoapply import db, updates

    looked, prepared, switched = [], [], []
    monkeypatch.setattr(updates, "check", lambda: looked.append(1) or updates.state())
    monkeypatch.setattr(updates, "prepare_later", lambda ver=None: prepared.append(ver))
    monkeypatch.setattr(updates, "switch", lambda ver=None: switched.append(ver))
    monkeypatch.setattr(updates, "idle", lambda: True)
    night = datetime.now().replace(hour=3, minute=30)          # (looked at just now: not again within the day)

    db.set_setting("update.mode", "off")
    assert updates.tick(night) == "" and not looked and not release["told"]
    db.set_setting("update.mode", "notify")                 # said once per version; nothing fetched
    updates.tick(night)
    updates.tick(night)
    assert release["told"] == [("available", "9.9.9")] and not prepared and not looked          # (looked less than a day ago)
    db.set_setting("update.mode", "download")
    assert updates.tick(night) == "preparing" and prepared == ["9.9.9"] and not switched
    updates._save(staged="9.9.9", status="ready")
    db.set_setting("update.mode", "auto")
    assert updates.tick(night.replace(hour=14)) == "" and not switched                   # outside the window
    assert updates.tick(night) == "switching" and switched == ["9.9.9"]
    updates._save(failed_switch="9.9.9")                    # a switch to it did not take: not tried again by itself
    assert updates.tick(night) == "" and switched == ["9.9.9"]


def test_update_when_idle_from_the_phone(release, monkeypatch):
    from autoapply import actions, db, updates
    from autoapply.messages import Card

    db.set_setting("update.mode", "notify")
    acts = actions._decorate(Card("x", "y"), "update:9.9.9:available", None)
    assert acts == [{"label": acts[0]["label"], "data": "u:9.9.9:idle"}]
    prepared, switched = [], []
    monkeypatch.setattr(updates, "prepare_later", lambda ver=None: prepared.append(ver))
    monkeypatch.setattr(updates, "switch", lambda ver=None: switched.append(ver))
    assert actions.run("u:9.9.9:idle") and prepared == ["9.9.9"]
    monkeypatch.setattr(updates, "idle", lambda: False)
    updates._save(staged="9.9.9")
    assert updates.tick() == "" and not switched            # waits for nothing to be going on, whatever the mode and the hour
    monkeypatch.setattr(updates, "idle", lambda: True)
    assert updates.tick() == "switching" and switched == ["9.9.9"]
    with pytest.raises(actions.Done):
        actions.run("u:1.0.0:idle")                          # not newer than this one


def test_the_window_may_cross_midnight(app_env):
    from autoapply import db, updates

    db.set_setting("update.window", {"from": "23:00", "to": "02:00"})
    assert updates.in_window(datetime(2026, 1, 1, 23, 30)) and updates.in_window(datetime(2026, 1, 2, 1, 0)) and not updates.in_window(datetime(2026, 1, 2, 12, 0))


def test_about_and_update_endpoints(app_env):
    from fastapi.testclient import TestClient

    from autoapply.api.main import app

    c = TestClient(app)
    a = c.get("/api/about").json()
    assert a["version"] and a["kind"] in ("managed", "unmanaged", "source", "container") and any(x["name"] == "fastapi" for x in a["components"])
    u = c.get("/api/system/update").json()
    assert u["mode"] == "notify" and u["channel"] == "stable" and u["current"] == a["version"]
    r = c.post("/api/system/update/switch", json={})
    assert r.status_code == 409                              # nothing prepared
    assert "update" in c.get("/api/overview").json()
