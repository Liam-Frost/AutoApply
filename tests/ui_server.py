"""The built interface in a browser, for the tests that measure what is drawn (test_ui_layout.py and the page tests).

One server and one browser for the whole run, started when the first test asks for them:

- the server is the program itself in a process of its own, on a free port, with a throw-away data folder filled by
  the demo's seed (scripts/demo.py: made-up applicant, employers, postings and mail; the first-run guide is done, so
  every page can be opened) and then by tests/ui_data.py (made-up records that are hard to draw: the longest and
  shortest names, site accounts in every state), its secrets in a file of that folder (never the computer's keyring),
  no sign-in, no background work and no AI;
- the browser is Playwright's Chromium, as in the other tests that drive one.

Without the built interface (`npm run build` in frontend/) or without the browser the tests are skipped - unless
AUTOAPPLY_REQUIRE_UI_TESTS is set (CI sets it), where a missing piece fails the run instead of quietly passing it.
"""

from __future__ import annotations

import atexit
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend" / "dist" / "index.html"
REQUIRED = bool(os.environ.get("AUTOAPPLY_REQUIRE_UI_TESTS"))

# (as the demo serves itself - scripts/demo.py SERVE: the data is made up and the page is opened by a test. The seed
# runs in the same process: the program is started once, not twice.)
SERVE = """
import sys, warnings
sys.path[:0] = [r'{backend}', r'{scripts}', r'{tests}']
warnings.simplefilter('ignore')
import demo
demo.seed('en')
import ui_data
ui_data.build()
import uvicorn
from autoapply import access
access.enforced = lambda: False
from autoapply import db, net
db.init_db(); net.apply()
uvicorn.run('autoapply.api.main:app', host='127.0.0.1', port={port}, log_level='warning', lifespan='off')
"""

_state: dict = {}


def missing(what: str) -> None:
    """A piece the tests need is not on this computer: skip, or fail where the run is meant to include them."""
    if REQUIRED:
        pytest.fail(what + " (AUTOAPPLY_REQUIRE_UI_TESTS is set: these tests may not be skipped here)", pytrace=False)
    pytest.skip(what)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def server() -> str:
    """The address of the running copy (started on first use, stopped when the run ends)."""
    if "base" in _state:
        return _state["base"]
    if not DIST.is_file():
        missing("the interface is not built: run `npm run build` in frontend/")
    home = Path(tempfile.mkdtemp(prefix="autoapply-ui-"))
    (home / "data").mkdir()
    (home / "knowledge").mkdir()
    env = {**os.environ, "AUTOAPPLY_DATA": str(home / "data"), "AUTOAPPLY_KNOWLEDGE": str(home / "knowledge"), "AUTOAPPLY_KEYRING_SERVICE": "autoapply-test",
           "AUTOAPPLY_SECRETS": "file", "PYTHONIOENCODING": "utf-8"}
    for k in ("AUTOAPPLY_ROOT", "AUTOAPPLY_STRICT_STATUS", "AUTOAPPLY_TEST_BROWSER"):      # nothing of the surrounding run reaches the copy
        env.pop(k, None)
    port = free_port()
    log = open(home / "server.log", "w", encoding="utf-8")      # noqa: SIM115 (it lives as long as the process it belongs to)
    proc = subprocess.Popen([sys.executable, "-c", SERVE.format(backend=str(ROOT / "backend"), scripts=str(ROOT / "scripts"), tests=str(ROOT / "tests"), port=port)], env=env, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)

    def stop() -> None:
        proc.kill()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            pass
        log.close()
        shutil.rmtree(home, ignore_errors=True)

    atexit.register(stop)
    base = f"http://127.0.0.1:{port}"
    end = time.time() + 60
    while time.time() < end:
        if proc.poll() is not None:
            break
        try:
            urllib.request.urlopen(base + "/api/persona", timeout=2)  # noqa: S310
            _state["base"] = base
            return base
        except OSError:
            time.sleep(0.2)
    log.flush()
    said = (home / "server.log").read_text(encoding="utf-8", errors="replace")[-2000:]
    stop()
    raise RuntimeError("the interface's server did not start:\n" + said)


def browser():
    """The one browser of the run (started on first use, closed when the run ends)."""
    if "browser" in _state:
        return _state["browser"]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        missing("Playwright is not installed")
    pw = sync_playwright().start()
    try:
        b = pw.chromium.launch()
    except Exception as e:  # noqa: BLE001 (no browser was downloaded: whatever it says, the tests cannot run)
        pw.stop()
        missing("Playwright's Chromium is not installed (`playwright install chromium`): " + str(e).splitlines()[0])

    def stop() -> None:
        try:
            b.close()
            pw.stop()
        except Exception:  # noqa: BLE001, S110 (the run is over)
            pass

    atexit.register(stop)
    _state["browser"] = b
    return b


def context(*, width: int = 1440, height: int = 900, theme: str = "light", lang: str = "en", reduced_motion: bool = True):
    """A fresh browser profile at one size, theme and language. Animations are off unless a test is about them: a
    measurement never lands in the middle of a transition."""
    ctx = browser().new_context(viewport={"width": width, "height": height}, color_scheme=theme, locale="zh-CN" if lang == "zh" else "en-US",
                                reduced_motion="reduce" if reduced_motion else "no-preference", base_url=server())
    # the page reads both before it draws (src/ui.js, src/i18n/catalog.js)
    ctx.add_init_script(f"try {{ localStorage.setItem('lang', '{lang}'); localStorage.setItem('theme', '{theme}') }} catch (e) {{}}")
    return ctx
