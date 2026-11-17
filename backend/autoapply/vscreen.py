"""A virtual screen, for a browser that has to have a window on a computer that has no screen.

Two cases need a real window, not the hidden browser:
  - a site that turns the hidden browser away (it is remembered with the site: sites.py, needs_window), and
  - the optional second backend, which drives an ordinary Chrome.
On a server the window goes onto a screen that exists only in memory (Xvfb). When a person has to use that window -
to sign in - the screen is shared through a VNC server (x11vnc) that only this program can reach, and shown in the
program's web page (the remote window, in its "screen" mode: api/main.py bridges the page's WebSocket to it).

Each window a person uses gets a screen of its own, so that one viewer never sees another site's window; windows
nobody looks at share one.

Kept to this computer and this user:
  - the X display takes no TCP connections and asks for a secret cookie (an Xauthority file readable by the owner),
    so other accounts on the computer cannot open windows on it or watch it;
  - the VNC server listens on 127.0.0.1 only and asks for a password made up for that one screen, which is handed
    to the signed-in viewer and to nobody else.

Both programs come from the system (apt install xvfb x11vnc; the container image has them). Without them the
program still works: pages that need a person are shown as pictures instead (remote.py), and a site that refuses the
hidden browser cannot be applied to - `autoapply doctor` says so.
"""

from __future__ import annotations

import atexit
import logging
import os
import secrets as _random
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("autoapply.vscreen")
SIZE = (1280, 800)
_lock = threading.Lock()
_shared: "Screen | None" = None
_live: list["Screen"] = []


def available() -> bool:
    return bool(shutil.which("Xvfb"))


def can_view() -> bool:
    return available() and bool(shutil.which("x11vnc"))


def _free_display() -> int:
    for n in range(90, 200):
        if not Path(f"/tmp/.X11-unix/X{n}").exists() and not Path(f"/tmp/.X{n}-lock").exists():  # noqa: S108 - where X keeps them
            return n
    raise RuntimeError("no free X display number")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _xauthority(path: Path, display: int, cookie: bytes) -> None:
    """An Xauthority file with one entry: this display, for a client on any host name (the format of xauth(1))."""
    def field(b: bytes) -> bytes:
        return struct.pack(">H", len(b)) + b

    entry = struct.pack(">H", 0xFFFF) + field(b"") + field(str(display).encode()) + field(b"MIT-MAGIC-COOKIE-1") + field(cookie)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(entry)


class Screen:
    def __init__(self, view: bool):
        self.folder = Path(tempfile.mkdtemp(prefix="autoapply-screen-"))
        self.number = _free_display()
        self.display = f":{self.number}"
        self.auth = self.folder / "Xauthority"
        _xauthority(self.auth, self.number, os.urandom(16))
        self.port: int | None = None
        self.password = ""
        self.procs: list[subprocess.Popen] = []
        quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        self.procs.append(subprocess.Popen(["Xvfb", self.display, "-screen", "0", f"{SIZE[0]}x{SIZE[1]}x24", "-nolisten", "tcp", "-auth", str(self.auth)], **quiet))
        self._wait(lambda: Path(f"/tmp/.X11-unix/X{self.number}").exists(), "the virtual screen did not start")  # noqa: S108
        if view:
            self.port = _free_port()
            self.password = _random.token_urlsafe(6)[:8]            # VNC passwords are 8 characters
            pw = self.folder / "vncpasswd"
            subprocess.run(["x11vnc", "-storepasswd", self.password, str(pw)], check=True, **quiet)
            self.procs.append(subprocess.Popen(["x11vnc", "-display", self.display, "-auth", str(self.auth), "-rfbport", str(self.port), "-localhost", "-rfbauth", str(pw),
                                                "-forever", "-shared", "-noxdamage", "-quiet", "-nolookup"], **quiet))
            self._wait(self._listening, "the screen's viewer did not start")
        _live.append(self)
        log.info("virtual screen %s started%s", self.display, " with a viewer" if view else "")

    def _listening(self) -> bool:
        with socket.socket() as s:
            s.settimeout(0.3)
            return s.connect_ex(("127.0.0.1", int(self.port or 0))) == 0

    def _wait(self, ready: Any, problem: str, seconds: float = 10.0) -> None:
        end = time.time() + seconds
        while time.time() < end:
            if any(p.poll() is not None for p in self.procs):
                break
            if ready():
                return
            time.sleep(0.1)
        self.stop()
        raise RuntimeError(problem)

    def env(self) -> dict[str, str]:
        """What a program needs in its environment to open its window on this screen."""
        return {"DISPLAY": self.display, "XAUTHORITY": str(self.auth)}

    def stop(self) -> None:
        for p in reversed(self.procs):
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001 - it is going away one way or another
                try:
                    p.kill()
                except Exception:  # noqa: BLE001
                    pass
        self.procs = []
        shutil.rmtree(self.folder, ignore_errors=True)
        if self in _live:
            _live.remove(self)


def shared() -> Screen:
    """The screen for windows nobody looks at. Started on first use, kept for as long as the program runs."""
    global _shared
    with _lock:
        if _shared is None or any(p.poll() is not None for p in _shared.procs):
            _shared = Screen(view=False)
        return _shared


def private() -> Screen:
    """A screen of its own, with a viewer, for one window a person will use. The caller stops it."""
    return Screen(view=True)


@atexit.register
def _stop_all() -> None:
    for s in list(_live):
        s.stop()
