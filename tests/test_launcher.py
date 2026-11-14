"""The tray launcher: what it shows for a server state, how it starts again, and that it attaches to a running server."""
import http.server
import json
import sys
import threading


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
    out = backup.export()
    names = zipfile.ZipFile(out["path"]).namelist()
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
    from autoapply import backup

    assert backup._key("1.0.0") > backup._key("1.0.0a1") and backup._key("v1.2.0") > backup._key("1.1.9") and backup._key("1.0.0a2") > backup._key("1.0.0a1")
    assert "error" in backup.check_update("")                       # no repository configured: says so, asks no one

    class Boom:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k): raise OSError("offline")

    import httpx

    monkeypatch.setattr(httpx, "Client", Boom)
    out = backup.check_update("someone/project")
    assert out["current"] and "error" in out and "newer" not in out


def test_designed_tray_menu_renders_from_state_and_maps_clicks(app_env):
    """The Windows tray menu is a picture drawn from state: rows, badges and the switch follow it, and only enabled rows are clickable."""
    from autoapply import tray_menu
    from autoapply.launcher import TEXT

    st = tray_menu.demo_state(TEXT["zh"])
    img, regions = tray_menu.render(st, scale=1.0)
    keys = [r[0] for r in regions]
    assert keys == ["open", "todos", "drafts", "pause", "restart", "autostart", "shortcut", "log", "quit"]
    assert img.size[0] == tray_menu.W and all(0 <= x0 < x1 <= img.size[0] and 0 <= y0 < y1 <= img.size[1] for _, x0, y0, x1, y1 in regions)
    # twice the display scale: twice the pixels, the same rows
    img2, regions2 = tray_menu.render(st, scale=2.0, dark=True, hover="pause")
    assert img2.size == (img.size[0] * 2, img.size[1] * 2) and [r[0] for r in regions2] == keys
    # nothing waiting: no "needs you" rows; attached to a server started elsewhere: restart is not offered; server down: nothing to open or pause
    idle = tray_menu.demo_state(TEXT["en"], state="running", needs=0, drafts=0, attached=True, can_restart=False)
    assert [r[0] for r in tray_menu.render(idle)[1]] == ["open", "pause", "autostart", "shortcut", "log", "quit"]
    down = tray_menu.demo_state(TEXT["en"], state="stopped", up=False, needs=0, drafts=0)
    assert [r[0] for r in tray_menu.render(down)[1]] == ["restart", "autostart", "shortcut", "log", "quit"]
    assert tray_menu.render(idle)[0].size[1] < img.size[1]
    # every text the menu needs exists in both languages
    for lang in ("zh", "en"):
        for k in ("state_running", "state_attention", "state_paused", "state_stopped", "state_starting", "todo_row", "draft_row", "attached_short", "shortcut"):
            assert TEXT[lang][k]
