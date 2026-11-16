"""The remote window: a browser page that needs a person, shown in the program's own web page.

On a desktop, "this needs you" opens a browser window on the screen: to sign in, to press Submit yourself, to take
over a form. A server has no screen, and the person is at another computer or on a phone. So the page is kept in the
hidden browser and shown to them where they are: the web page fetches pictures of it and sends back clicks and keys.

How it fits the rest: `browser.open_page(headless=False)` is how the program asks for a window a person can see.
Where there is no screen that call attaches the page here instead (`attach`), and nothing else changes: the code that
waits for the person - `page.wait_for_timeout` in a loop, everywhere - is the code that serves them, because the
wait is replaced by one that, while it waits, carries out the clicks and keys that arrived and takes the next picture.
Playwright's objects belong to the thread that made them; this way they are only ever touched from it.

    the web page  --GET frame / POST input-->  api  --a queue, a picture-->  the thread that owns the page (pump)

What is typed here can be a password. Input is never logged, pictures are never written to disk, and neither is
shown to the AI. The API refuses to serve a remote window to another device over plain HTTP (api/main.py).
"""

from __future__ import annotations

import logging
import os
import secrets as _random
import threading
import time
from collections import deque
from typing import Any

log = logging.getLogger("autoapply.remote")

VIEWPORT = {"width": 1280, "height": 800}
WATCHED_S = 6.0         # a viewer that asked for a picture this recently is still looking
FRAME_GAP_S = 0.35      # between two pictures of a page nobody touched
KEYS = {"Enter", "Tab", "Backspace", "Delete", "Escape", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown", "Space",
        "F5", "Insert"}
MODS = {"Control", "Shift", "Alt", "Meta"}

_windows: dict[str, "Window"] = {}
_lock = threading.Lock()


def no_screen() -> bool:
    """Is there no screen here to open a window on? AUTOAPPLY_NO_SCREEN=1 says so on a computer that has one
    (trying the remote window out on a desktop)."""
    from . import doctor

    return bool(os.environ.get("AUTOAPPLY_NO_SCREEN")) or not doctor.has_screen()


class Window:
    def __init__(self, page: Any, title: str, purpose: str, tenant: str):
        self.id = _random.token_urlsafe(9)
        self.title, self.purpose, self.tenant = title, purpose, tenant
        self.created = time.time()
        self.context = page.context if page is not None else None      # None: a real window on a virtual screen
        self.tab = -1                               # which page of the context is shown: -1 the newest (a sign-in pop-up)
        self.inputs: deque[dict[str, Any]] = deque(maxlen=2000)
        self.cond = threading.Condition()
        self.frame: bytes | None = None
        self.seq = 0
        self.state: dict[str, Any] = {"url": "", "title": "", "tabs": []}
        self.viewed = 0.0
        self.shot = 0.0
        self.dirty = True
        self.closed = False
        self.vnc: dict[str, Any] | None = None      # set when the window is a real one on a virtual screen (vscreen.py)

    # --- the side of the web page (any thread) ---

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "purpose": self.purpose, "tenant": self.tenant, "since": int(self.created),
                "mode": "screen" if self.vnc else "frames", "page": self.state, **VIEWPORT}

    def send(self, events: list[dict[str, Any]]) -> None:
        for e in events[:200]:
            if isinstance(e, dict):
                self.inputs.append(e)
        self.viewed = time.time()

    def next_frame(self, after: int, wait_s: float = 8.0) -> tuple[int, bytes | None]:
        """The newest picture once it is newer than `after`; (seq, None) when nothing changed in `wait_s`."""
        self.viewed = time.time()
        end = time.time() + wait_s
        with self.cond:
            while self.seq <= after and not self.closed:
                left = end - time.time()
                if left <= 0:
                    return self.seq, None
                self.cond.wait(min(left, 1.0))
                self.viewed = time.time()
            return self.seq, self.frame

    # --- the side of the page (only the thread that owns it) ---

    def page(self) -> Any | None:
        if self.context is None:
            return None
        try:
            pages = [p for p in self.context.pages if not p.is_closed()]
        except Exception:  # noqa: BLE001 - the browser is going away
            return None
        if not pages:
            return None
        return pages[self.tab] if -len(pages) <= self.tab < len(pages) else pages[-1]

    def pump(self) -> None:
        """Carry out what arrived, and take a picture if someone is looking."""
        page = self.page()
        if page is None:
            return
        while self.inputs:
            event = self.inputs.popleft()
            try:
                self._do(page, event)
            except Exception as e:  # noqa: BLE001 - a click on a page that is navigating: the next picture shows what happened
                log.debug("remote input %s not carried out (%s)", event.get("t"), type(e).__name__)
            self.dirty = True
            page = self.page()
            if page is None:
                return
        now = time.time()
        if now - self.viewed > WATCHED_S or (not self.dirty and now - self.shot < FRAME_GAP_S):
            return
        try:
            shot = page.screenshot(type="jpeg", quality=60, timeout=4000, animations="disabled", caret="initial")
            pages = [p for p in self.context.pages if not p.is_closed()]
            state = {"url": page.url, "title": page.title()[:120], "tabs": [{"i": i, "title": (p.title() or p.url)[:60], "on": p is page} for i, p in enumerate(pages)]}
        except Exception as e:  # noqa: BLE001 - between two pages
            log.debug("no picture this time (%s)", type(e).__name__)
            self.shot = now
            return
        self.shot, self.dirty = time.time(), False
        if shot != self.frame or state != self.state:
            with self.cond:
                self.frame, self.state, self.seq = shot, state, self.seq + 1
                self.cond.notify_all()

    def _do(self, page: Any, e: dict[str, Any]) -> None:
        kind = e.get("t")
        x, y = _coord(e.get("x"), VIEWPORT["width"]), _coord(e.get("y"), VIEWPORT["height"])
        if kind == "click":
            page.mouse.click(x, y, button="right" if e.get("button") == "right" else "left", click_count=2 if e.get("count") == 2 else 1)
        elif kind == "move":
            page.mouse.move(x, y)
        elif kind == "down":
            page.mouse.move(x, y)
            page.mouse.down()
        elif kind == "up":
            page.mouse.move(x, y)
            page.mouse.up()
        elif kind == "wheel":
            page.mouse.move(x, y)
            page.mouse.wheel(_clamp(e.get("dx"), 2000), _clamp(e.get("dy"), 2000))
        elif kind == "text":
            text = str(e.get("s") or "")[:5000]
            if text:
                page.keyboard.insert_text(text)
        elif kind == "key":
            key = str(e.get("k") or "")
            if key in KEYS or (len(key) == 1 and key.isprintable()):
                mods = [m for m in (e.get("mods") or []) if m in MODS]
                page.keyboard.press("+".join([*mods, key]))
        elif kind == "nav":
            action = e.get("a")
            if action == "back":
                page.go_back(wait_until="commit", timeout=15000)
            elif action == "forward":
                page.go_forward(wait_until="commit", timeout=15000)
            elif action == "reload":
                page.reload(wait_until="commit", timeout=15000)
        elif kind == "tab":
            self.tab = int(e.get("i", -1))
        elif kind == "close":
            # "I am done": the same as closing the window on a desktop, which is what the waiting code looks for
            for p in list(self.context.pages):
                try:
                    p.close()
                except Exception:  # noqa: BLE001
                    pass


def _coord(v: Any, limit: int) -> float:
    try:
        return max(0.0, min(float(v), float(limit - 1)))
    except (TypeError, ValueError):
        return 0.0


def _clamp(v: Any, limit: int) -> float:
    try:
        return max(-float(limit), min(float(v), float(limit)))
    except (TypeError, ValueError):
        return 0.0


def attach(page: Any, *, title: str = "", purpose: str = "apply", tenant: str = "") -> Window:
    """Make `page` a remote window. From now on waiting on it serves whoever is looking at it."""
    win = Window(page, title, purpose, tenant)
    wait = page.wait_for_timeout

    def serving_wait(timeout: float) -> None:
        end = time.time() + float(timeout) / 1000.0
        while True:
            win.pump()
            left = end - time.time()
            if left <= 0:
                return
            watched = time.time() - win.viewed < WATCHED_S
            wait(min(left * 1000.0, 40.0 if watched else 250.0))

    page.wait_for_timeout = serving_wait          # the page's own wait, for everything that waits on it
    with _lock:
        _windows[win.id] = win
    log.info("remote window %s opened (%s)", win.id, purpose)
    return win


def attach_screen(screen: Any, *, title: str = "", purpose: str = "apply", tenant: str = "") -> Window:
    """A real browser window on a virtual screen (vscreen.py) as a remote window: the person sees and uses the screen
    itself, through its VNC server. Nothing has to be served by the thread that owns the page."""
    win = Window(None, title, purpose, tenant)
    win.vnc = {"port": screen.port, "password": screen.password}
    with _lock:
        _windows[win.id] = win
    log.info("remote window %s opened on virtual screen %s (%s)", win.id, screen.display, purpose)
    return win


def announce(win: Window) -> None:
    """Tell the person that a window is waiting for them, where they are: a window that opens on a server is not
    seen by anyone. A sign-in they started themselves needs no telling - the page they are on takes them there."""
    if win.purpose == "login":
        return
    try:
        from . import notify

        notify.send("todo", f"有一个窗口在等你操作：{win.title}", ref=f"remote:{win.id}", path=f"/remote/{win.id}", tag=f"remote:{win.id}")
    except Exception as e:  # noqa: BLE001 - a notification that fails must not stop the run
        log.info("could not announce the remote window (%s)", type(e).__name__)


def detach(win: Window | None) -> None:
    if win is None:
        return
    with _lock:
        _windows.pop(win.id, None)
    with win.cond:
        win.closed = True
        win.frame = None
        win.cond.notify_all()
    win.inputs.clear()
    log.info("remote window %s closed", win.id)


def idle(page: Any, seconds: float) -> None:
    """Wait on a page the way everything that waits for a person should: through the page, never time.sleep - a
    sleeping thread cannot serve the remote window."""
    try:
        page.wait_for_timeout(seconds * 1000.0)
    except Exception:  # noqa: BLE001 - the page is gone: wait without it
        time.sleep(seconds)


def get(window_id: str) -> Window | None:
    with _lock:
        return _windows.get(window_id)


def windows() -> list[dict[str, Any]]:
    with _lock:
        return [w.describe() for w in sorted(_windows.values(), key=lambda w: w.created)]
