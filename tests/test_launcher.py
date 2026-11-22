"""The tray launcher: what it shows for a server state, how it starts again, and that it attaches to a running server."""
import http.server
import json
import sys
import threading

import pytest


def test_status_line_and_icon_for_each_state(app_env):
    from autoapply import launcher as L

    t = L.TEXT["zh"]
    assert L.summarize(None, t, starting=True)["state"] == "starting" and L.summarize(None, t)["line"] == t["stopped"]
    idle = L.summarize({"open_todos": 0, "pending_drafts": 0, "running": [], "paused": False}, t)
    assert idle["state"] == "running" and idle["line"] == t["idle"] and idle["extra"] == []
    busy = L.summarize({"open_todos": 2, "pending_drafts": 1, "running": [{}, {}], "paused": False}, L.TEXT["en"])
    assert busy["state"] == "attention" and busy["line"] == "Running, 2 task(s) in progress" and busy["extra"] == ["2 item(s) need you", "1 draft(s) to review"] and busy["needs"] == 2
    assert L.summarize({"open_todos": 0, "pending_drafts": 0, "running": [], "paused": True}, t)["state"] == "paused"
    for state in ("running", "attention", "paused", "starting", "stopped"):
        img = L.make_icon(state)
        assert img.size == (64, 64) and img.getpixel((50, 50))[3] == 255   # the status dot is drawn
    assert set(L.TEXT["zh"]) == set(L.TEXT["en"])


def test_launch_command_has_no_console_on_windows(app_env):
    from autoapply import launcher as L

    cmd = L.launch_command()
    assert cmd[1:] == ["-m", "autoapply.launcher"]
    if sys.platform == "win32":
        assert cmd[0].lower().endswith("pythonw.exe")


def test_attaches_to_a_server_that_is_already_running_and_can_pause_it(app_env):
    from autoapply import launcher as L

    state = {"paused": False, "puts": []}

    class H(http.server.BaseHTTPRequestHandler):
        def _send(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path == "/api/overview":
                self._send({"open_todos": 3, "pending_drafts": 0, "running": [], "paused": state["paused"]})
            else:
                self._send({"settings": {"ui.lang": "en"}})

        def do_PUT(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            state["puts"].append(body)
            state["paused"] = body["settings"]["schedule.paused"]
            self._send({"ok": True})

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        app = L.Launcher(srv.server_address[1])
        assert app.attached is True                      # it found the server and will not start a second one
        app.server.start()
        assert app.server.proc is None
        app.refresh()
        assert app.lang == "en" and app.view["state"] == "attention" and app.view["extra"] == ["3 item(s) need you"]
        app.toggle_pause()
        assert state["puts"] == [{"settings": {"schedule.paused": True}}] and app.view["line"] == "Auto-run is paused"
        app.quit()                                        # quitting an attached launcher leaves the server alone
        assert L.Server(srv.server_address[1]).up()
    finally:
        srv.shutdown()
    assert L.Launcher(1).attached is False and L.summarize(None, L.TEXT["zh"])["state"] == "stopped"


def test_export_and_restore_round_trip(app_env, tmp_path, monkeypatch):
    """An export holds the database, the documents and the knowledge folder; restoring it brings them back and keeps what was there."""
    import zipfile

    from autoapply import backup, config, db, knowledge

    db.set_setting("ui.lang", "en")
    knowledge.write("profile", "# Profile\n\n- Name: A B\n")
    (config.FILES / "resume.pdf").write_bytes(b"%PDF-1.4 demo")
    (config.RUNS / "exec_1").mkdir(parents=True, exist_ok=True)
    (config.RUNS / "exec_1" / "shot.png").write_bytes(b"x" * 100)
    (config.SESSIONS / "site.enc").write_bytes(b"secret-session")
    (config.DATA / "agent" / "app_1" / "shots").mkdir(parents=True, exist_ok=True)
    (config.DATA / "agent" / "app_1" / "journal.jsonl").write_text('{"kind": "run"}\n', encoding="utf-8")
    (config.DATA / "agent" / "app_1" / "shots" / "001.png").write_bytes(b"x" * 100)
    out = backup.export()
    names = zipfile.ZipFile(out["path"]).namelist()
    # what the agent wrote down about an application goes with it (the next run takes it up from there); its pictures do not
    assert "data/agent/app_1/journal.jsonl" in names and not any("shots" in n for n in names)
    assert "data/app.db" in names and "data/files/resume.pdf" in names and "knowledge/profile.md" in names and "manifest.json" in names
    assert not any(n.startswith(("data/runs", "data/sessions", "data/exports")) for n in names)       # no screenshots, no sign-ins unless asked
    with_sessions = backup.export(sessions=True)
    assert with_sessions["name"] != out["name"] or "data/sessions/site.enc" in zipfile.ZipFile(with_sessions["path"]).namelist()
    assert backup.path_of(out["name"]).is_file()
    try:
        backup.path_of("../app.db")
        raise AssertionError("a name outside the export folder was accepted")
    except FileNotFoundError:
        pass

    # change things, then restore
    knowledge.write("profile", "# Profile\n\n- Name: CHANGED\n")
    (config.FILES / "resume.pdf").unlink()
    db.reset_engine()   # restoring is done while the program is not running
    res = backup.restore(out["path"])
    assert "Name: A B" in (config.KNOWLEDGE / "profile.md").read_text(encoding="utf-8") and (config.FILES / "resume.pdf").read_bytes().startswith(b"%PDF")
    assert res["previous_kept_at"] and all(__import__("pathlib").Path(p).exists() for p in res["previous_kept_at"])

    # an archive that tries to write outside the data folders is refused
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("manifest.json", '{"app": "autoapply"}')
        z.writestr("data/app.db", "x")
        z.writestr("../outside.txt", "x")
    try:
        backup.restore(evil)
        raise AssertionError("an archive with a path outside the data folders was accepted")
    except ValueError:
        pass


def test_update_check_compares_versions_and_survives_no_network(app_env, monkeypatch):
    from autoapply import backup, db, updates

    assert backup._key("1.0.0") > backup._key("1.0.0a1") and backup._key("v1.2.0") > backup._key("1.1.9") and backup._key("1.0.0a2") > backup._key("1.0.0a1")
    db.set_setting("update.repo", "")
    assert updates.check()["error"] == "no-repo"                     # no repository configured: says so, asks no one

    class Boom:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k): raise OSError("offline")

    import httpx

    monkeypatch.setattr(httpx, "Client", Boom)
    db.set_setting("update.repo", "someone/project")
    out = updates.check()
    assert out["error"].startswith("network:") and not updates.status()["newer"]


def test_designed_tray_menu_renders_from_state_and_maps_clicks(app_env):
    """The Windows tray menu is a picture drawn from state: rows, badges and the switch follow it, and only enabled rows are clickable."""
    from autoapply import tray_menu
    from autoapply.launcher import TEXT

    st = tray_menu.demo_state(TEXT["zh"])
    img, regions = tray_menu.render(st, scale=1.0)
    keys = [r[0] for r in regions]
    assert keys == ["open", "todos", "drafts", "pause", "restart", "autostart", "shortcut", "log", "reset_admin", "quit"]
    assert img.size[0] == tray_menu.W and all(0 <= x0 < x1 <= img.size[0] and 0 <= y0 < y1 <= img.size[1] for _, x0, y0, x1, y1 in regions)
    # twice the display scale: twice the pixels, the same rows
    img2, regions2 = tray_menu.render(st, scale=2.0, dark=True, hover="pause")
    assert img2.size == (img.size[0] * 2, img.size[1] * 2) and [r[0] for r in regions2] == keys
    # nothing waiting: no "needs you" rows; attached to a server started elsewhere: restart is not offered; server down: nothing to open or pause
    idle = tray_menu.demo_state(TEXT["en"], state="running", needs=0, drafts=0, attached=True, can_restart=False)
    assert [r[0] for r in tray_menu.render(idle)[1]] == ["open", "pause", "autostart", "shortcut", "log", "reset_admin", "quit"]
    down = tray_menu.demo_state(TEXT["en"], state="stopped", up=False, needs=0, drafts=0)
    assert [r[0] for r in tray_menu.render(down)[1]] == ["restart", "autostart", "shortcut", "log", "reset_admin", "quit"]
    assert tray_menu.render(idle)[0].size[1] < img.size[1]
    # every text the menu needs exists in both languages
    for lang in ("zh", "en"):
        for k in ("state_running", "state_attention", "state_paused", "state_stopped", "state_starting", "todo_row", "draft_row", "attached_short", "shortcut"):
            assert TEXT[lang][k]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shortcuts")
def test_a_shortcut_is_written_without_another_program_and_carries_the_identity(tmp_path):
    from autoapply import winshell

    lnk = tmp_path / "AutoApply.lnk"
    winshell.make_shortcut(str(lnk), sys.executable, "-m autoapply.launcher", str(tmp_path), "", "AutoApply")
    got = winshell.read_shortcut(str(lnk))
    assert got["target"].lower() == sys.executable.lower() and got["arguments"] == "-m autoapply.launcher"
    assert got["workdir"] == str(tmp_path) and got["app_id"] == winshell.APP_ID

def test_staged_restart_preserves_queued_work_and_rolls_back_on_failed_health(app_env, monkeypatch):
    from pathlib import Path
    from autoapply import launcher, tasks

    class Server:
        owned = True

        def staged_release(self, marker="next-release"):
            return Path("candidate") if marker == "next-release" else None

        def preflight(self, release):
            calls.append(("check", release))

        def get(self, path):
            return {"stopped": True, "running": [], "next": [1]} if path == "/api/queue" else []

        def stop(self):
            calls.append(("stop", None))
            self.owned = False

        def start(self, release, *, standby=False):
            calls.append(("start", release))
            self.owned = release != Path("candidate")

        def up(self):
            return False

    calls = []
    monkeypatch.setattr(launcher, "Server", lambda port: Server())
    tray = launcher.Launcher()
    tasks.enqueue("mail", ref="preserved")
    tray._restart_lock.acquire()
    tray._restart_when_idle()
    assert calls == [("check", Path("candidate")), ("stop", None), ("start", Path("candidate")),
                     ("stop", None), ("start", launcher.config.ROOT)]
    assert tasks.plan()["next_total"] == 1


def test_a_fresh_start_takes_the_staged_release_and_falls_back_when_it_fails(app_env, monkeypatch):
    """Started with nothing running (start.bat, the shortcut, after the computer slept): a release staged for the next
    restart is used now, checked first; one that fails its check or does not come up is left, and the last one starts."""
    from pathlib import Path

    from autoapply import config, launcher

    class Server:
        owned = False

        def __init__(self):
            self.fails = ""

        def staged_release(self, marker="next-release"):
            return Path("candidate") if marker == "next-release" else Path("current")

        def preflight(self, release):
            calls.append(("check", release))
            if self.fails == "check":
                raise RuntimeError("import failed")

        def start(self, release, *, standby=False):
            calls.append(("start", release))
            self.owned = not (self.fails == "health" and release == Path("candidate"))

        def stop(self):
            calls.append(("stop", None))
            self.owned = False

        def up(self):
            return self.owned

    run = config.DATA / "run"
    run.mkdir(parents=True, exist_ok=True)
    for fails, want in (("", [("check", Path("candidate")), ("start", Path("candidate"))]),
                        ("check", [("check", Path("candidate")), ("start", Path("current"))]),
                        ("health", [("check", Path("candidate")), ("start", Path("candidate")), ("start", Path("current"))])):
        (run / "next-release").write_text("candidate", encoding="utf-8")
        (run / "active-release").write_text("current", encoding="utf-8")
        server = Server()
        server.fails = fails
        monkeypatch.setattr(launcher, "Server", lambda port, s=server: s)
        monkeypatch.setattr(launcher.time, "sleep", lambda s: None)
        calls = []
        tray = launcher.Launcher()
        got = tray.start_fresh()
        assert calls == want, (fails, calls)
        if fails:
            assert got == tray.release == Path("current") and (run / "next-release").exists()
            assert (run / "active-release").read_text(encoding="utf-8") == "current"
        else:
            assert got == tray.release == Path("candidate") and not (run / "next-release").exists()
            assert (run / "active-release").read_text(encoding="utf-8") == "candidate"


def test_a_restart_can_be_asked_for_from_outside_the_menu(app_env, monkeypatch):
    from autoapply import config, launcher

    tray = launcher.Launcher(1)
    calls = []
    monkeypatch.setattr(tray, "restart", lambda *a: calls.append(1))
    assert tray.asked_to_restart() is False and not calls
    asked = config.DATA / "run" / "restart-request"
    asked.parent.mkdir(parents=True, exist_ok=True)
    asked.write_text("x", encoding="utf-8")
    assert tray.asked_to_restart() is True and calls == [1] and not asked.exists()
