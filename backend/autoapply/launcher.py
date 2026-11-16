"""The launcher: a small icon in the system tray that keeps AutoApply running.

It starts the server (or attaches to one that is already running on the port), shows at a glance whether it is up
and whether something is waiting for the user, opens the page, pauses / resumes automatic runs, restarts the server
and can register itself to start when the user signs in to the computer.

    autoapply tray [--port 8000]          (or: pythonw -m autoapply.launcher, without a console window)

Nothing here needs administrator rights: starting at sign-in is a per-user entry (the Run key on Windows, a
LaunchAgent on macOS, an autostart file on Linux) that the same menu removes again.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from . import config

log = logging.getLogger("autoapply.launcher")
NAME = "AutoApply"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # this computer only: never through a proxy

TEXT = {
    "zh": {"open": "打开 AutoApply", "starting": "正在启动…", "running": "运行中", "idle": "运行中，目前空闲", "working": "运行中，正在处理 {n} 个任务", "stopped": "服务没有运行",
           "needs": "{n} 件事等你处理", "drafts": "{n} 份草案等你审批", "pause": "暂停自动运行", "resume": "恢复自动运行", "paused": "已暂停自动运行",
           "restart": "重启服务", "start": "启动服务", "autostart": "开机时自动启动", "shortcut": "在桌面创建快捷方式", "log": "查看日志", "reset_admin": "重置管理员密码", "reset_done": "管理员密码已重置。请在这台电脑上打开 AutoApply 重新设置。", "quit": "退出（同时停止服务）", "quit_attached": "退出启动器",
           "notify_needs": "有 {n} 件事需要你处理", "attached": "（服务是在别处启动的）", "attached_short": "服务是在别处启动的",
           "state_running": "运行中", "state_attention": "有事等你", "state_paused": "已暂停", "state_stopped": "没有运行", "state_starting": "正在启动",
           "todo_row": "需要你处理", "draft_row": "草案等你审批", "failed": "服务启动失败，点“查看日志”看原因"},
    "en": {"open": "Open AutoApply", "starting": "Starting…", "running": "Running", "idle": "Running, idle", "working": "Running, {n} task(s) in progress", "stopped": "The server is not running",
           "needs": "{n} item(s) need you", "drafts": "{n} draft(s) to review", "pause": "Pause auto-run", "resume": "Resume auto-run", "paused": "Auto-run is paused",
           "restart": "Restart the server", "start": "Start the server", "autostart": "Start when I sign in", "shortcut": "Create a desktop shortcut", "log": "Show log", "reset_admin": "Reset the administrator password", "reset_done": "The administrator password was reset. Open AutoApply on this computer to set a new one.", "quit": "Quit (stops the server)", "quit_attached": "Quit the launcher",
           "notify_needs": "{n} item(s) need you", "attached": "(the server was started elsewhere)", "attached_short": "started elsewhere",
           "state_running": "Running", "state_attention": "Needs you", "state_paused": "Paused", "state_stopped": "Not running", "state_starting": "Starting",
           "todo_row": "Needs your attention", "draft_row": "Drafts to review", "failed": "The server did not start - see the log"},
}


# --- starting with the computer ------------------------------------------------------------------


def launch_command() -> list[str]:
    """How to start this launcher again, without a console window where the platform has that notion."""
    exe = Path(sys.executable)
    if sys.platform == "win32" and exe.name.lower() == "python.exe" and (exe.parent / "pythonw.exe").exists():
        exe = exe.parent / "pythonw.exe"
    return [str(exe), "-m", "autoapply.launcher"]


def create_shortcut(folders: list[str] | None = None) -> str:
    """A shortcut that starts the launcher, with the program's icon: on the desktop and in the Start menu (Windows), or in
    the applications menu (Linux). Returns where it was put. Nothing is installed and no administrator rights are needed."""
    cmd = launch_command()
    if sys.platform == "win32":
        ico = config.DATA / "autoapply.ico"
        make_icon("plain").save(ico, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
        from . import winshell

        if not folders:
            import ctypes
            from ctypes import wintypes

            def known(csidl: int) -> str:                     # 0x10 the desktop, 0x02 the Start menu's Programs
                buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
                ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
                return buf.value

            folders = [known(0x10), known(0x02)]
        made = []
        for folder in folders:
            lnk = str(Path(folder) / "AutoApply.lnk")
            winshell.make_shortcut(lnk, cmd[0], subprocess.list2cmdline(cmd[1:]), str(config.ROOT), str(ico), "AutoApply")
            made.append(lnk)
        return "; ".join(made)
    if sys.platform == "darwin":
        raise RuntimeError("On macOS use the menu-bar icon and its 'Start when I sign in' option; an app bundle is not provided yet.")
    png = config.DATA / "autoapply.png"
    make_icon("plain").resize((128, 128)).save(png)
    target = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications" / "autoapply.desktop"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"[Desktop Entry]\nType=Application\nName=AutoApply\nExec={' '.join(cmd)}\nPath={config.ROOT}\nIcon={png}\nTerminal=false\nCategories=Office;\n", encoding="utf-8")
    return str(target)


def _mac_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.autoapply.launcher.plist"


def _linux_desktop() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / "autoapply.desktop"


def autostart_enabled() -> bool:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                winreg.QueryValueEx(k, NAME)
            return True
        except OSError:
            return False
    return (_mac_plist() if sys.platform == "darwin" else _linux_desktop()).exists()


def set_autostart(on: bool) -> None:
    cmd = launch_command()
    env_root = str(config.ROOT)
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, subprocess.list2cmdline(cmd))
            else:
                try:
                    winreg.DeleteValue(k, NAME)
                except OSError:
                    pass
        return
    if sys.platform == "darwin":
        p = _mac_plist()
        if not on:
            p.unlink(missing_ok=True)
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        args = "".join(f"<string>{a}</string>" for a in cmd)
        p.write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                     f'<plist version="1.0"><dict><key>Label</key><string>com.autoapply.launcher</string><key>ProgramArguments</key><array>{args}</array>'
                     f'<key>WorkingDirectory</key><string>{env_root}</string><key>RunAtLoad</key><true/></dict></plist>\n', encoding="utf-8")
        return
    p = _linux_desktop()
    if not on:
        p.unlink(missing_ok=True)
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"[Desktop Entry]\nType=Application\nName={NAME}\nExec={' '.join(cmd)}\nPath={env_root}\nX-GNOME-Autostart-enabled=true\n", encoding="utf-8")


# --- the server ----------------------------------------------------------------------------------


class Server:
    """The AutoApply server as this launcher sees it: its own child process, or one that was already there."""

    def __init__(self, port: int) -> None:
        from . import access

        c = access.conf()
        self.port, self.host = port, c["host"]
        # the launcher itself always talks to the server on this computer, under the prefix it is served at
        local = "127.0.0.1" if c["host"] in ("0.0.0.0", "::", "localhost") else c["host"]  # noqa: S104
        self.url = f"http://{local}:{port}"
        self.proc: subprocess.Popen | None = None
        self.log_path = config.DATA / "launcher.log"

    def get(self, path: str, timeout: float = 4) -> Any:
        from . import access

        req = urllib.request.Request(self.url + path, headers={access.LOCAL_HEADER: access.local_token()})      # this computer's own program: no login
        with OPENER.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def put_settings(self, settings: dict[str, Any]) -> None:
        from . import access

        req = urllib.request.Request(self.url + "/api/settings", data=json.dumps({"settings": settings}).encode(), method="PUT",
                                     headers={"Content-Type": "application/json", access.LOCAL_HEADER: access.local_token()})
        OPENER.open(req, timeout=6).close()

    def up(self) -> bool:
        try:
            self.get("/api/overview", timeout=2)
            return True
        except Exception:  # noqa: BLE001
            return False

    @property
    def owned(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        if self.owned or self.up():
            return
        config.DATA.mkdir(parents=True, exist_ok=True)
        out = open(self.log_path, "ab")  # noqa: SIM115 - handed to the child for its lifetime
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.proc = subprocess.Popen([sys.executable, "-c", "from autoapply.cli import main; main()", "serve", "--port", str(self.port), "--host", self.host],
                                     cwd=str(config.ROOT), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags)

    def stop(self) -> None:
        if not self.owned:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc = None


def summarize(ov: dict[str, Any] | None, t: dict[str, str], *, starting: bool = False) -> dict[str, Any]:
    """What the icon and the menu say for a given server state."""
    if ov is None:
        return {"state": "starting" if starting else "stopped", "line": t["starting"] if starting else t["stopped"], "extra": [], "needs": 0}
    needs, drafts, busy = int(ov.get("open_todos") or 0), int(ov.get("pending_drafts") or 0), len(ov.get("running") or [])
    line = t["paused"] if ov.get("paused") else t["working"].format(n=busy) if busy else t["idle"]
    extra = ([t["needs"].format(n=needs)] if needs else []) + ([t["drafts"].format(n=drafts)] if drafts else [])
    return {"state": "attention" if needs else "paused" if ov.get("paused") else "running", "line": line, "extra": extra, "needs": needs}


def make_icon(state: str):  # noqa: ANN201
    """The brand mark with a status dot: green running, amber something needs the user, grey stopped / paused."""
    from PIL import Image, ImageDraw

    s = 64
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    mark = next((p for p in (config.ROOT / "frontend" / "dist" / "favicon.png", config.ROOT / "frontend" / "public" / "favicon.png") if p.exists()), None)
    if mark is not None:   # the brand mark on a white tile, so it reads on light and dark taskbars alike
        d.rounded_rectangle((1, 1, s - 2, s - 2), radius=14, fill=(255, 255, 255, 255))
        logo = Image.open(mark).convert("RGBA").resize((s - 14, s - 14), Image.LANCZOS)
        if state == "stopped":
            logo = Image.merge("RGBA", (*logo.convert("L").convert("RGB").split(), logo.getchannel("A")))
        img.paste(logo, (7, 7), logo)
    else:
        d.rounded_rectangle((2, 2, s - 3, s - 3), radius=14, fill=(31, 79, 216, 255) if state != "stopped" else (120, 128, 140, 255))
        d.line([(17, 48), (32, 14), (47, 48)], fill=(255, 255, 255, 255), width=7, joint="curve")   # the "A"
        d.line([(24, 37), (40, 37)], fill=(255, 255, 255, 255), width=6)
    if state == "plain":   # the icon of a shortcut: no status dot
        return img
    dot = {"running": (34, 170, 90), "attention": (240, 160, 20), "paused": (150, 156, 166), "starting": (150, 156, 166), "stopped": (200, 60, 60)}[state]
    d.ellipse((40, 40, 62, 62), fill=(255, 255, 255, 255))
    d.ellipse((43, 43, 59, 59), fill=(*dot, 255))
    return img


# --- the tray ------------------------------------------------------------------------------------


class Launcher:
    def __init__(self, port: int = 8000) -> None:
        self.server = Server(port)
        self.attached = self.server.up()
        self.lang = "zh"
        self.ov: dict[str, Any] | None = None
        self.view = summarize(None, TEXT["zh"], starting=True)
        self.started_at = time.time()
        self.icon = None
        self._stop = threading.Event()
        self._last_needs = 0

    @property
    def t(self) -> dict[str, str]:
        return TEXT[self.lang]

    def refresh(self) -> None:
        try:
            self.ov = self.server.get("/api/overview")
            try:
                self.lang = "en" if self.server.get("/api/settings")["settings"].get("ui.lang") == "en" else "zh"
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            self.ov = None
        starting = self.ov is None and self.server.owned and time.time() - self.started_at < 90
        self.view = summarize(self.ov, self.t, starting=starting)
        if self.ov is None and not starting and not self.attached and self.server.proc is not None and self.server.proc.poll() is not None:
            self.view["line"] = self.t["failed"]

    def _loop(self) -> None:
        while not self._stop.wait(5):
            before = (self.view["state"], self.view["line"], tuple(self.view["extra"]))
            self.refresh()
            if self.icon is None:
                continue
            if (self.view["state"], self.view["line"], tuple(self.view["extra"])) != before:
                self.icon.icon = make_icon(self.view["state"])
                self.icon.title = f"{NAME} - " + " · ".join([self.view["line"], *self.view["extra"]])
                self.icon.update_menu()
            if self.view["needs"] > self._last_needs:
                try:
                    self.icon.notify(self.t["notify_needs"].format(n=self.view["needs"]), NAME)
                except Exception:  # noqa: BLE001 - notifications are optional on some desktops
                    pass
            self._last_needs = self.view["needs"]

    # menu actions
    def open_page(self, *_: Any, path: str = "") -> None:
        webbrowser.open(self.server.url.rstrip("/") + path)

    # --- the designed menu (Windows) ---------------------------------------------------------------
    def menu_state(self) -> dict[str, Any]:
        ov = self.ov or {}
        return {"t": self.t, "state": self.view["state"], "line": self.view["line"], "up": self.ov is not None, "attached": self.attached,
                "needs": int(ov.get("open_todos") or 0), "drafts": int(ov.get("pending_drafts") or 0), "paused": bool(ov.get("paused")),
                "autostart": autostart_enabled(), "can_restart": not self.attached or self.ov is None}

    def menu_action(self, key: str) -> None:
        try:
            {"open": self.open_page, "todos": lambda: self.open_page(path="/todos"), "drafts": lambda: self.open_page(path="/drafts"), "pause": self.toggle_pause,
             "restart": self.restart, "autostart": self.toggle_autostart, "shortcut": self.make_shortcut, "log": self.show_log, "reset_admin": self.reset_admin, "quit": self.quit}[key]()
        except Exception:  # noqa: BLE001 - a failed action must not take the launcher down
            log.exception("menu action %s failed", key)

    def _icon_class(self):  # noqa: ANN202
        """pystray's icon; on Windows a right click opens the designed menu instead of the system one."""
        import pystray

        if sys.platform != "win32" or os.environ.get("AUTOAPPLY_NATIVE_MENU"):
            return pystray.Icon
        from . import tray_menu

        tray_menu.dpi_aware()
        popup = tray_menu.Popup(self.menu_state, self.menu_action)
        if not popup.ok:
            log.warning("the designed menu is not available (%s); using the system menu", popup.error or "timed out")
            return pystray.Icon
        self.popup = popup

        class Icon(pystray.Icon):
            def _on_notify(icon, wparam, lparam):  # noqa: N805, ANN001, ANN202
                if lparam == 0x0205:  # WM_RBUTTONUP
                    import ctypes
                    from ctypes import wintypes

                    pt = wintypes.POINT()
                    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                    popup.show(pt.x, pt.y)
                    return
                super()._on_notify(wparam, lparam)

        return Icon

    def toggle_pause(self, *_: Any) -> None:
        if self.ov is not None:
            self.server.put_settings({"schedule.paused": not self.ov.get("paused")})
            self.refresh()

    def restart(self, *_: Any) -> None:
        self.server.stop()
        self.attached = False
        self.started_at = time.time()
        self.server.start()

    def toggle_autostart(self, *_: Any) -> None:
        set_autostart(not autostart_enabled())

    def make_shortcut(self, *_: Any) -> None:
        try:
            where = create_shortcut()
            if self.icon is not None:
                self.icon.notify(where[:200], NAME)
        except Exception as e:  # noqa: BLE001
            if self.icon is not None:
                self.icon.notify(str(e)[:200], NAME)

    def show_log(self, *_: Any) -> None:
        p = self.server.log_path
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("", encoding="utf-8")
        if sys.platform == "win32":
            os.startfile(str(p))  # noqa: S606
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(p)])

    def reset_admin(self, *_: Any) -> None:
        """Forgotten password. Whoever can click this can read the data folder anyway."""
        from . import access

        access.reset_admin()
        self.open_page()
        try:
            if self.icon is not None:
                self.icon.notify(self.t["reset_done"], NAME)
        except Exception:  # noqa: BLE001
            pass

    def quit(self, *_: Any) -> None:
        self._stop.set()
        self.server.stop()
        if getattr(self, "popup", None) is not None:
            threading.Thread(target=self.popup.close, daemon=True).start()   # quit may be running in the menu's own thread
        if self.icon is not None:
            self.icon.stop()

    def menu(self):  # noqa: ANN201
        import pystray

        item, sep = pystray.MenuItem, pystray.Menu.SEPARATOR
        return pystray.Menu(
            item(lambda _i: self.t["open"], self.open_page, default=True, enabled=lambda _i: self.ov is not None),
            sep,
            item(lambda _i: self.view["line"] + (" " + self.t["attached"] if self.attached and self.ov is not None else ""), None, enabled=False),
            item(lambda _i: (self.view["extra"] or [""])[0], self.open_page, visible=lambda _i: len(self.view["extra"]) > 0),
            item(lambda _i: (self.view["extra"] + ["", ""])[1], self.open_page, visible=lambda _i: len(self.view["extra"]) > 1),
            sep,
            item(lambda _i: self.t["resume"] if self.ov and self.ov.get("paused") else self.t["pause"], self.toggle_pause, enabled=lambda _i: self.ov is not None),
            item(lambda _i: self.t["restart"] if self.ov is not None else self.t["start"], self.restart, enabled=lambda _i: not self.attached or self.ov is None),
            item(lambda _i: self.t["autostart"], self.toggle_autostart, checked=lambda _i: autostart_enabled()),
            item(lambda _i: self.t["shortcut"], self.make_shortcut, visible=lambda _i: sys.platform != "darwin"),
            item(lambda _i: self.t["log"], self.show_log),
            item(lambda _i: self.t["reset_admin"], self.reset_admin),
            sep,
            item(lambda _i: self.t["quit_attached"] if self.attached else self.t["quit"], self.quit),
        )

    def run(self, *, open_page: bool = True) -> None:
        import pystray

        if not self.attached:
            self.server.start()
        self.icon = self._icon_class()(NAME, make_icon("starting"), f"{NAME} - {self.t['starting']}", self.menu())
        threading.Thread(target=self._loop, daemon=True, name="launcher-status").start()
        if open_page:
            def when_up() -> None:
                for _ in range(90):
                    if self.server.up():
                        self.open_page()
                        return
                    time.sleep(1)

            threading.Thread(target=when_up, daemon=True).start()
        self.icon.run()


def main(argv: list[str] | None = None) -> None:
    from . import quiet

    quiet.install()
    from . import winshell

    winshell.set_app_id()          # the taskbar and notifications say AutoApply, not pythonw.exe
    import argparse

    ap = argparse.ArgumentParser(prog="autoapply tray")
    from . import access

    ap.add_argument("--port", type=int, default=int(os.environ.get("AUTOAPPLY_PORT") or access.conf()["port"]))
    ap.add_argument("--no-open", action="store_true", help="do not open the page when the server is up")
    a = ap.parse_args(argv)
    os.chdir(config.ROOT)
    logging.basicConfig(filename=str(config.DATA / "launcher.log") if config.DATA.exists() else None, level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    try:
        Launcher(a.port).run(open_page=not a.no_open)
    except ImportError as e:  # no tray support on this desktop: keep the program usable
        print(f"The tray icon is not available here ({e}). Starting the server in this window instead.")
        from .cli import main as cli

        sys.argv = ["autoapply", "serve", "--port", str(a.port)]
        cli()


if __name__ == "__main__":
    main()
