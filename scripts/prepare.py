"""The part of an installation that is not copying files: put a new version's files in place, get the Python
dependencies and the program's browser, and take everything back if that does not work.

The Windows installer copies a new version into `<root>/.staged` and then runs this file, with the uv it brought:

    uv run --no-project prepare.py --root <root> --staged <root>/.staged --uv <uv.exe> --status <file> --cancel <file>

It uses the standard library only (nothing is installed yet when it starts) and it never touches `data` or `knowledge`.

What it tells the installer, through small files it can read without knowing JSON:
  --status   "<step> <percent> <part>"   step 1 files, 2 dependencies, 3 browser; percent -1 while the tool reports
             none; part counts the downloads within a step (the browser comes in several)
  --done     "ok", "cancelled", or "error <code>"; the codes are in CODES below
The installer asks it to stop by creating the --cancel file.

An upgrade is taken back as a whole: the old files return, and the old dependencies are restored from uv's cache.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

KEEP = {"data", "knowledge", ".venv", "tools", ".staged", ".previous"}     # never moved, never removed
CODES = {
    "files": "the new files could not be put in place; the previous version is untouched",
    "deps": "the dependencies could not be installed; nothing was installed before, so nothing was restored",
    "deps_restored": "the dependencies could not be installed; the previous version was put back and works",
    "deps_broken": "the dependencies could not be installed, and the previous version's could not be restored: run setup again",
    "browser": "the program's browser could not be downloaded; everything else is installed - run setup again to finish",
}
PERCENT = re.compile(r"(\d{1,3})(?:\.\d+)?%")
COLOUR = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
LOGS_KEPT = 12


class Cancelled(Exception):
    pass


class Failed(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class Job:
    def __init__(self, root: Path, staged: Path, uv: str, status: Path | None = None, done: Path | None = None, cancel: Path | None = None, log: Path | None = None):
        self.root, self.staged, self.uv = root, staged, uv
        self.status, self.done, self.cancel, self.log = status, done, cancel, log
        self.previous = root / ".previous"
        self.moved: list[tuple[Path, Path | None]] = []        # (where it is now, where the old one went)
        self._last = ""

    # --- talking to the installer ---

    def note(self, text: str) -> None:
        if self.log is None:
            return
        try:
            self.log.parent.mkdir(parents=True, exist_ok=True)
            with self.log.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%H:%M:%S}  {text}\n")
        except OSError as e:                    # a log that cannot be written must not stop the installation
            print(f"(log) {text}  [{e}]", flush=True)

    def _put(self, path: Path | None, text: str) -> None:
        if path is None:
            return
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="ascii")
        for _ in range(20):                         # the installer may be reading it this instant
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                time.sleep(0.05)

    def tell(self, step: int, percent: int = -1, part: int = 0) -> None:
        text = f"{step} {percent} {part}"
        if text != self._last:
            self._last = text
            self._put(self.status, text)

    def check(self) -> None:
        if self.cancel is not None and self.cancel.exists():
            raise Cancelled

    # --- running a tool ---

    def run(self, args: list[str], step: int, cwd: Path) -> int:
        """Run a tool to its end, keeping its output in the log and its percentage in the status. Stops it, and
        everything it started, when the installer asks."""
        self.note("> " + " ".join(args))
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1", "UV_NO_PROGRESS": "1"}
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        p = subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags)

        def read() -> None:
            buf, seen, part = b"", -1, 0
            while True:
                chunk = p.stdout.read1(4096) if p.stdout else b""
                if not chunk:
                    break
                buf += chunk
                *lines, buf = re.split(rb"[\r\n]+", buf)
                for raw in lines:
                    line = COLOUR.sub("", raw.decode("utf-8", "replace")).strip()
                    if not line:
                        continue
                    if line.startswith("Downloading "):
                        part, seen = part + 1, -1
                    m = PERCENT.search(line)
                    if m and int(m.group(1)) <= 100:
                        pct = int(m.group(1))
                        self.tell(step, pct, part)
                        if pct // 10 == seen // 10:      # a progress bar redrawn: one line per ten percent is enough
                            continue
                        seen = pct
                        line = line.rsplit("|", 1)[-1].strip()      # the figures, without the drawn bar
                    self.note(line)
            if buf.strip():
                self.note(buf.decode("utf-8", "replace").strip())

        t = threading.Thread(target=read, daemon=True)
        t.start()
        try:
            while p.poll() is None:
                self.check()
                time.sleep(0.2)
        except Cancelled:
            self.stop(p)
            raise
        t.join(timeout=5)
        self.note(f"exit {p.returncode}")
        return p.returncode

    def stop(self, p: subprocess.Popen) -> None:
        self.note(f"stopping {p.pid}")
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            p.kill()
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.note("it did not stop in time")

    # --- the steps ---

    def swap(self) -> None:
        """Put every staged file and folder where it belongs, keeping what was there in .previous until the end."""
        if self.previous.exists():
            shutil.rmtree(self.previous)
        self.previous.mkdir(parents=True)
        for item in sorted(self.staged.iterdir()):
            if item.name in KEEP:
                continue
            place, old = self.root / item.name, None
            if place.exists():
                old = self.previous / item.name
                os.replace(place, old)
            self.moved.append((place, old))             # recorded before the move: a failure in it is undone too
            os.replace(item, place)
        self.note(f"{len(self.moved)} item(s) put in place")

    def restore(self) -> bool:
        """Undo swap(): the new files go back to the staging folder, the old ones return. True when there was an old version."""
        had = any(old is not None for _, old in self.moved)
        for place, old in reversed(self.moved):
            try:
                if place.exists():
                    os.replace(place, self.staged / place.name)
                if old is not None and old.exists():
                    os.replace(old, place)
            except OSError as e:
                self.note(f"could not put back {place.name}: {e}")
                had = False
        self.moved = []
        try:
            self.previous.rmdir()                # empty again when everything went back
        except OSError:
            pass
        return had

    def sync(self, offline: bool = False) -> int:
        # --inexact: optional components added later (the ChatGPT sign-in component) are kept
        return self.run([self.uv, "sync", "--frozen", "--inexact"] + (["--offline"] if offline else []), 2, self.root)

    def go(self) -> str:
        try:
            self.tell(1)
            self.check()
            try:
                self.swap()
            except OSError as e:
                self.note(f"ERROR while moving files: {e}")
                self.restore()
                raise Failed("files") from e
            self.tell(2)
            try:
                code = self.sync()
            except Cancelled:
                if self.back() == "deps_broken":            # stopped, but not back where it was: that is what to say
                    raise Failed("deps_broken") from None
                raise
            if code != 0:
                raise Failed(self.back())
            self.tell(3)
            if self.run([self.uv, "run", "--frozen", "--no-sync", "playwright", "install", "chromium"], 3, self.root) != 0:
                raise Failed("browser")
            shutil.rmtree(self.previous, ignore_errors=True)
            shutil.rmtree(self.staged, ignore_errors=True)
            return "ok"
        except Cancelled:
            self.note("cancelled")
            return "cancelled"
        except Failed as e:
            self.note(f"ERROR: {CODES[e.code]}")
            return f"error {e.code}"

    def back(self) -> str:
        """The dependencies did not install: return to the previous version. Says which of the three ends it came to."""
        if not self.restore():
            return "deps"
        cancel, self.cancel = self.cancel, None             # this must run to its end
        try:
            ok = self.sync(offline=True) == 0
        finally:
            self.cancel = cancel
        return "deps_restored" if ok else "deps_broken"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--staged", required=True)
    ap.add_argument("--uv", default="uv")
    ap.add_argument("--status")
    ap.add_argument("--done")
    ap.add_argument("--cancel")
    ap.add_argument("--log")
    a = ap.parse_args(argv)
    path = lambda v: Path(v) if v else None  # noqa: E731
    job = Job(Path(a.root), Path(a.staged), a.uv, path(a.status), path(a.done), path(a.cancel), path(a.log))
    try:
        result = job.go()
    except Exception as e:  # noqa: BLE001 - whatever it is, the installer must be told, and the log must say what
        job.note(f"ERROR (unexpected): {type(e).__name__}: {e}")
        result = "error " + (job.back() if job.moved else "files")
    if job.log is not None:                     # the logs stay with the data; the oldest make room
        old = sorted(job.log.parent.glob("setup-*.log"), key=lambda p: p.stat().st_mtime)[:-LOGS_KEPT]
        for p in old:
            p.unlink(missing_ok=True)
    job._put(job.done, result)
    return 0 if result == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
