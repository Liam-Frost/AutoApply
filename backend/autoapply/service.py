"""Running as a service on Linux: started with the computer, restarted when it fails, without a desktop.

A systemd *user* service - no root, nothing outside the home folder - kept running after you log out by "lingering"
(`loginctl enable-linger`, which on some systems asks for the administrator once).

    autoapply service install | uninstall | status
    autoapply service start | stop [--now] | restart

`stop` waits for the application that is being filled in to finish: automatic runs are paused, the running task ends,
then the service stops, and the pause is taken back so that the next start goes on as before. `--now` does not wait.
The installer uses this to upgrade a copy that runs as a service.

Variables the service should see (AUTOAPPLY_MASTER_KEY_FILE and the like) go into data/service.env, one NAME=value a
line; the file is read by systemd when the service starts.
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import config

NAME = "autoapply"


class NotHere(RuntimeError):
    """There is no systemd user session to register with (a container, WSL without systemd, another system)."""


def unit_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user" / f"{NAME}.service"


def unit_text() -> str:
    python = Path(sys.executable)
    return f"""[Unit]
Description=AutoApply - a job-search assistant that runs on your own computer
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={config.ROOT}
ExecStart="{python}" -m autoapply.cli serve
EnvironmentFile=-{config.DATA / 'service.env'}
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5
# an application that is being filled in gets time to come to an end
TimeoutStopSec=120

[Install]
WantedBy=default.target
"""


def _ctl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=60, check=check)


def available() -> bool:
    if not sys.platform.startswith("linux") or not shutil.which("systemctl"):
        return False
    try:
        return _ctl("show-environment").returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _linger(user: str) -> bool:
    try:
        out = subprocess.run(["loginctl", "show-user", user, "--property=Linger"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return out.strip().endswith("=yes")


def status() -> dict[str, Any]:
    user = getpass.getuser()
    if not available():
        return {"systemd": False, "installed": False, "active": False, "linger": False, "user": user}
    return {"systemd": True, "installed": unit_path().exists(), "active": _ctl("is-active", "--quiet", NAME).returncode == 0, "linger": _linger(user), "user": user}


def install() -> dict[str, Any]:
    """Register and start. Says whether lingering could be turned on; if not, the service stops when you log out."""
    if not available():
        raise NotHere("This system has no systemd user session (a container, or WSL without systemd). Keep the program running another way: a container's restart policy, or your own process manager.")
    path = unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit_text(), encoding="utf-8")
    _ctl("daemon-reload", check=True)
    _ctl("enable", "--now", NAME, check=True)
    user = getpass.getuser()
    if not _linger(user):
        try:
            subprocess.run(["loginctl", "enable-linger", user], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
    return status()


def uninstall() -> None:
    if available():
        _ctl("disable", "--now", NAME)
    unit_path().unlink(missing_ok=True)
    if available():
        _ctl("daemon-reload")


def start() -> None:
    _ctl("start", NAME, check=True)


def _busy() -> int:
    from . import db
    from .models import Task

    with db.session() as s:
        return s.query(Task).filter_by(status="running").count()


def stop(now: bool = False, wait_s: int = 1800, tell: Any = print) -> bool:
    """Stop the service. Unless `now`, first let the task that is running end. True when it stopped in order."""
    from . import db

    orderly = True
    if not now and status()["active"]:
        db.init_db()
        paused = bool(db.get_setting("schedule.paused"))
        db.set_setting("schedule.paused", True)         # nothing new starts
        try:
            began = time.time()
            while _busy():
                if time.time() - began > wait_s:
                    orderly = False
                    tell(f"A task was still running after {wait_s // 60} minutes; stopping anyway.")
                    break
                if int(time.time() - began) % 30 == 0:
                    tell("Waiting for the task that is running to finish...")
                time.sleep(1)
            _ctl("stop", NAME)
        finally:
            db.set_setting("schedule.paused", paused)   # the next start goes on as before
    else:
        _ctl("stop", NAME)
    return orderly
