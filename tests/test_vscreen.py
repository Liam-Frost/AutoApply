"""Where a browser's window goes on a computer without a screen, and the virtual screen itself.

The decisions are tested everywhere with a stand-in screen. The real thing - Xvfb, x11vnc, a browser window on it,
the bridge to the page - is tested where those programs exist (the Linux job of CI, the container); set
AUTOAPPLY_REQUIRE_SCREEN_TESTS=1 there so that a missing program fails the run instead of skipping it.
"""

from __future__ import annotations

import os
import shutil
import socket
import struct
import sys

import pytest

from autoapply import browser, remote, vscreen

HAVE = sys.platform.startswith("linux") and bool(shutil.which("Xvfb")) and bool(shutil.which("x11vnc"))
needs_screen = pytest.mark.skipif(not HAVE and not os.environ.get("AUTOAPPLY_REQUIRE_SCREEN_TESTS"), reason="Xvfb and x11vnc are not on this computer")


class FakeScreen:
    display, port, password = ":99", 5999, "pw"
    stopped = False

    def env(self):
        return {"DISPLAY": ":99", "XAUTHORITY": "/x"}

    def stop(self):
        self.stopped = True


@pytest.fixture
def server(app_env, monkeypatch):
    """No screen; a virtual one can be had."""
    from autoapply import db

    db.init_db()
    monkeypatch.setenv("AUTOAPPLY_NO_SCREEN", "1")
    monkeypatch.setattr(remote, "announce", lambda win: None)
    screens: list[FakeScreen] = []

    def make():
        screens.append(FakeScreen())
        return screens[-1]

    monkeypatch.setattr(vscreen, "available", lambda: True)
    monkeypatch.setattr(vscreen, "can_view", lambda: True)
    monkeypatch.setattr(vscreen, "private", make)
    monkeypatch.setattr(vscreen, "shared", make)
    yield screens
    remote._windows.clear()


def place(for_person, headless, tenant="site:x", needs_window=False):
    return browser._window_place(for_person, headless, tenant, "https://jobs.example.com/a", "login", needs_window=needs_window)


def test_with_a_screen_nothing_changes(app_env, monkeypatch):
    monkeypatch.delenv("AUTOAPPLY_NO_SCREEN", raising=False)
    monkeypatch.setattr(remote, "no_screen", lambda: False)
    p = place(True, False)
    assert (p.headless, p.pictures, p.env, p.window) == (False, False, {}, None)


def test_a_hidden_page_stays_hidden(server):
    p = place(False, True)
    assert (p.headless, p.pictures, p.env) == (True, False, {}) and server == []


def test_a_page_for_a_person_is_shown_as_pictures(server):
    p = place(True, False)
    assert (p.headless, p.pictures, p.window) == (True, True, None) and server == [] and p.title == "jobs.example.com"


def test_a_site_that_refuses_the_hidden_browser_gets_a_window_on_a_virtual_screen(server):
    from autoapply import db

    db.set_setting("browser.visible_sites", ["site:x"])
    p = place(False, False, needs_window=True)                      # nobody looks: the shared screen, no remote window
    assert p.headless is False and p.env == {"DISPLAY": ":99", "XAUTHORITY": "/x"} and "--window-size=1280,800" in p.args
    assert p.window is None and p.screen is None and remote.windows() == []
    with place(True, False) as q:                                   # a person must use it: a screen of its own, shown in the page
        assert q.headless is False and q.pictures is False
        (w,) = remote.windows()
        assert w["mode"] == "screen" and w["title"] == "jobs.example.com" and remote.get(w["id"]).vnc == {"port": 5999, "password": "pw"}
        screen = q.screen
    assert screen.stopped and remote.windows() == []                # closed with the page


def test_without_a_virtual_screen_it_stays_hidden_and_a_person_gets_pictures(server, monkeypatch):
    from autoapply import db

    db.set_setting("browser.visible_sites", ["site:x"])
    monkeypatch.setattr(vscreen, "available", lambda: False)
    monkeypatch.setattr(vscreen, "can_view", lambda: False)
    p = place(True, False)
    assert (p.headless, p.pictures) == (True, True) and server == []


def test_the_screen_asks_for_a_cookie_only_its_owner_can_read(tmp_path):
    path = tmp_path / "Xauthority"
    vscreen._xauthority(path, 93, b"0123456789abcdef")
    data = path.read_bytes()
    assert data == struct.pack(">H", 0xFFFF) + b"\x00\x00" + b"\x00\x0293" + b"\x00\x12MIT-MAGIC-COOKIE-1" + b"\x00\x100123456789abcdef"
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


class FakeSocket:
    def __init__(self, headers, cookies=None, peer="127.0.0.1"):
        self.headers, self.cookies = headers, cookies or {}
        self.client = type("C", (), {"host": peer})()


def test_the_bridge_to_the_screen_is_for_this_programs_own_page_signed_in_and_encrypted(app_env, monkeypatch):
    from autoapply import access
    from autoapply.api import main

    path = "/api/remote/x/vnc"
    ok = {"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:8000"}
    assert main._ws_refusal(FakeSocket(ok), path) == ""
    assert main._ws_refusal(FakeSocket({**ok, "host": "evil.example"}), path) == "host"
    assert main._ws_refusal(FakeSocket({**ok, "origin": "https://evil.example"}), path) == "origin"
    assert main._ws_refusal(FakeSocket({"host": "127.0.0.1:8000"}), path) == "origin"           # a browser always says where from
    monkeypatch.setattr(access, "enforced", lambda: True)
    assert main._ws_refusal(FakeSocket(ok), path) == "login"
    monkeypatch.setattr(access, "session_ok", lambda cookie: cookie == "good")
    assert main._ws_refusal(FakeSocket(ok, {access.COOKIE: "good"}), path) == ""
    monkeypatch.setattr(access, "caller", lambda peer, headers: {"ip": "203.0.113.9", "https": False, "local": False, "near": False})
    assert main._ws_refusal(FakeSocket(ok, {access.COOKIE: "good"}), path) == "plain"
    monkeypatch.setattr(access, "caller", lambda peer, headers: {"ip": "172.17.0.1", "https": False, "local": False, "near": True})
    assert main._ws_refusal(FakeSocket(ok, {access.COOKIE: "good"}), path) == ""


def test_a_network_declared_trusted_counts_for_the_remote_window_only(app_env, monkeypatch):
    from autoapply import access

    assert access.caller("172.17.0.1", {})["near"] is False
    monkeypatch.setenv("AUTOAPPLY_TRUSTED_NETWORKS", "172.16.0.0/12, nonsense")
    who = access.caller("172.17.0.1", {})
    assert who["near"] is True and who["local"] is False            # near, but still not "this computer itself"
    assert access.caller("172.17.0.1", {"x-forwarded-for": "1.2.3.4"})["near"] is False
    assert access.caller("8.8.8.8", {})["near"] is False


# --- the real thing ---


@needs_screen
def test_a_real_virtual_screen_starts_is_viewable_and_goes_away():
    screen = vscreen.private()
    try:
        assert os.path.exists(f"/tmp/.X11-unix/X{screen.number}") and len(screen.password) == 8
        with socket.create_connection(("127.0.0.1", screen.port), timeout=5) as s:
            assert s.recv(12).startswith(b"RFB 003.")                # the viewer answers, on this computer only
    finally:
        number, port = screen.number, screen.port
        screen.stop()
    assert not os.path.exists(f"/tmp/.X11-unix/X{number}")
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1).close()


@needs_screen
def test_a_real_browser_window_on_the_virtual_screen_reaches_the_page_through_the_bridge(app_env, monkeypatch):
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app

    db.init_db()
    db.set_setting("browser.visible_sites", ["site:x"])
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(remote, "announce", lambda win: None)
    with browser.real_open_page("site:x", headless=False, url="https://jobs.example.com/a", operation="login") as page:
        page.set_content("<title>on the screen</title><h1>hello</h1>")
        assert page.evaluate("() => [window.outerWidth > 0, navigator.webdriver !== undefined]")[0]
        (w,) = remote.windows()
        assert w["mode"] == "screen"
        c = TestClient(app, base_url="http://127.0.0.1:8000")
        assert len(c.get(f"/api/remote/{w['id']}/screen").json()["password"]) == 8
        assert c.get(f"/api/remote/{w['id']}/frame").status_code == 409
        with c.websocket_connect(f"/api/remote/{w['id']}/vnc", headers={"origin": "http://127.0.0.1:8000"}, subprotocols=["binary"]) as ws:
            assert ws.receive_bytes().startswith(b"RFB 003.")
    assert remote.windows() == []
