"""The installer's second half (scripts/prepare.py): files put in place, dependencies, browser - and the way back."""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("prepare", Path(__file__).resolve().parents[1] / "scripts" / "prepare.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def tree(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def fake_uv(tmp_path: Path, body: str) -> list[str]:
    """A stand-in for uv: a Python script that is given uv's arguments."""
    script = tmp_path / "fake_uv.py"
    script.write_text("import sys, time\nargs = sys.argv[1:]\n" + body, encoding="utf-8")
    return [sys.executable, str(script)]


class Job(prepare.Job):
    """The job with the tool replaced: `uv ...` becomes `python fake_uv.py ...`."""

    tool: list[str] = []

    def run(self, args, step, cwd):
        return super().run(self.tool + args[1:], step, cwd)


@pytest.fixture
def place(tmp_path):
    root = tmp_path / "app"
    tree(root, {"backend/old.py": "old", "pyproject.toml": "old", "data/app.db": "mine", "knowledge/me.md": "me", "left.txt": "stays"})
    tree(root / ".staged", {"backend/new.py": "new", "pyproject.toml": "new", "scripts/prepare.py": "x"})
    job = Job(root, root / ".staged", "uv", tmp_path / "status", tmp_path / "done", tmp_path / "cancel", tmp_path / "log.txt")
    return root, job, tmp_path


def test_a_new_version_replaces_the_old_and_leaves_the_data(place):
    root, job, tmp = place
    # the way Playwright reports a download: a line that names it, then a drawn bar redrawn with the percentage
    job.tool = fake_uv(tmp, "print('Downloading Chromium 150 from https://example.invalid/c.zip'); print('|#### |  40% of 180 MiB'); print('|#####| 100% of 180 MiB'); sys.exit(0)")
    assert job.go() == "ok"
    assert (root / "backend/new.py").exists() and not (root / "backend/old.py").exists()        # the folder as a whole: no leftovers
    assert (root / "pyproject.toml").read_text() == "new" and (root / "left.txt").read_text() == "stays"
    assert (root / "data/app.db").read_text() == "mine" and (root / "knowledge/me.md").read_text() == "me"
    assert not (root / ".previous").exists() and not (root / ".staged").exists()
    assert (tmp / "status").read_text() == "3 100 1"
    log = (tmp / "log.txt").read_text(encoding="utf-8")
    assert "sync --frozen --inexact" in log and "playwright install chromium" in log         # the browser is asked for every time


def test_dependencies_that_do_not_install_bring_the_old_version_back(place):
    root, job, tmp = place
    job.tool = fake_uv(tmp, "sys.exit(0 if '--offline' in args else 1)")          # the network is down; the cache has the old ones
    assert job.go() == "error deps_restored"
    assert (root / "backend/old.py").exists() and not (root / "backend/new.py").exists() and (root / "pyproject.toml").read_text() == "old"
    assert (root / ".staged/backend/new.py").exists()                              # still there for the next attempt
    assert (root / "data/app.db").read_text() == "mine"


def test_it_says_so_when_the_old_version_cannot_be_restored(place):
    root, job, tmp = place
    job.tool = fake_uv(tmp, "sys.exit(1)")
    assert job.go() == "error deps_broken"
    assert (root / "backend/old.py").exists()


def test_a_first_installation_that_fails_has_nothing_to_restore(tmp_path):
    root = tmp_path / "app"
    tree(root / ".staged", {"backend/new.py": "new"})
    job = Job(root, root / ".staged", "uv", log=tmp_path / "log.txt")
    job.tool = fake_uv(tmp_path, "sys.exit(1)")
    assert job.go() == "error deps"


def test_a_browser_that_does_not_download_is_reported_and_the_version_stays(place):
    root, job, tmp = place
    job.tool = fake_uv(tmp, "sys.exit(1 if 'playwright' in args else 0)")
    assert job.go() == "error browser"
    assert (root / "backend/new.py").exists()


def test_cancelling_stops_the_tool_and_returns_to_the_old_version(place):
    root, job, tmp = place
    job.tool = fake_uv(tmp, "sys.exit(0) if '--offline' in args else time.sleep(60)")
    threading.Timer(1.0, lambda: (tmp / "cancel").write_text("x")).start()
    began = time.time()
    assert job.go() == "cancelled"
    assert time.time() - began < 30
    assert (root / "backend/old.py").exists() and not (root / "backend/new.py").exists()


def test_a_file_that_cannot_be_moved_leaves_the_old_version_whole(place, monkeypatch):
    root, job, tmp = place
    real = prepare.os.replace

    def replace(a, b):
        if Path(a).name == "pyproject.toml" and ".staged" in str(a):
            raise PermissionError("in use")
        return real(a, b)

    monkeypatch.setattr(prepare.os, "replace", replace)
    assert job.go() == "error files"
    assert (root / "backend/old.py").exists() and (root / "pyproject.toml").read_text() == "old" and not (root / "backend/new.py").exists()


def test_main_writes_the_result_where_the_installer_reads_it(place, monkeypatch):
    root, job, tmp = place
    monkeypatch.setattr(prepare, "Job", lambda *a: Job(*a))
    Job.tool = fake_uv(tmp, "sys.exit(0)")
    try:
        code = prepare.main(["--root", str(root), "--staged", str(root / ".staged"), "--done", str(tmp / "done"), "--status", str(tmp / "status"), "--log", str(tmp / "log.txt")])
    finally:
        Job.tool = []
    assert code == 0 and (tmp / "done").read_text() == "ok"


def test_a_cancel_that_cannot_return_to_the_old_version_says_so(place):
    root, job, tmp = place
    job.tool = fake_uv(tmp, "sys.exit(1) if '--offline' in args else time.sleep(60)")
    threading.Timer(1.0, lambda: (tmp / "cancel").write_text("x")).start()
    assert job.go() == "error deps_broken"
    assert (root / "backend/old.py").exists() and not (root / ".previous").exists()


def test_a_browser_that_cannot_start_for_want_of_system_libraries_is_told_apart(place, monkeypatch):
    root, job, tmp = place
    monkeypatch.setattr(prepare.sys, "platform", "linux")
    job.tool = fake_uv(tmp, "if 'playwright' in args:\n    print('node: error while loading shared libraries: libatomic.so.1: cannot open shared object file')\n    sys.exit(127)\nsys.exit(0)")
    assert job.go() == "error browser_libs"
    assert "install-deps chromium" in (tmp / "log.txt").read_text(encoding="utf-8")


def test_the_browser_is_started_once_to_see_that_it_can(place):
    root, job, tmp = place
    job.tool = fake_uv(tmp, "sys.exit(1 if 'python' in args else 0)")       # downloaded, but it does not start
    assert job.go() == "error browser"


def test_a_stop_asked_for_by_signal_still_restores_the_old_dependencies(place):
    root, job, tmp = place
    job.tool = fake_uv(tmp, "open(sys.argv[0] + '.offline', 'w').close() if '--offline' in args else time.sleep(60)")
    threading.Timer(1.0, lambda: setattr(job, "stopped", True)).start()
    assert job.go() == "cancelled"
    assert (tmp / "fake_uv.py.offline").exists()         # the restore ran although the stop was still in force
    assert (root / "backend/old.py").exists()
