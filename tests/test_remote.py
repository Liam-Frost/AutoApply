"""The remote window: a page that needs a person, used from another computer."""

from __future__ import annotations

import threading
import time

import pytest

from autoapply import remote

PAGE = """<html><body style="margin:0">
<input id="name" style="position:absolute;left:100px;top:100px;width:300px;height:40px">
<button id="go" style="position:absolute;left:100px;top:200px;width:200px;height:60px" onclick="document.title='pressed:'+document.getElementById('name').value">Go</button>
</body></html>"""


@pytest.fixture(autouse=True)
def no_windows_left():
    yield
    remote._windows.clear()


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport=remote.VIEWPORT)
        pg = ctx.new_page()
        pg.set_content(PAGE)
        yield pg
        b.close()


def test_a_person_elsewhere_sees_the_page_and_their_clicks_and_keys_reach_it(page):
    win = remote.attach(page, title="example.com", purpose="login", tenant="t")
    assert [w["id"] for w in remote.windows()] == [win.id]
    seen: dict = {}

    def viewer():           # another thread, as a web request is: it never touches the page
        seq, frame = win.next_frame(0)
        seen["first"] = (seq, frame[:3] if frame else None)
        win.send([{"t": "click", "x": 150, "y": 120}, {"t": "text", "s": "p@ss word"}, {"t": "key", "k": "Backspace"}, {"t": "click", "x": 150, "y": 230},
                  {"t": "key", "k": "rm -rf"}, {"t": "nope"}])
        seen["second"] = win.next_frame(seq)[0]

    t = threading.Thread(target=viewer)
    t.start()
    end = time.time() + 20
    while t.is_alive() and time.time() < end:
        page.wait_for_timeout(100)          # the code that waits for the person is what serves them
    t.join(1)
    assert seen["first"][0] >= 1 and seen["first"][1] == b"\xff\xd8\xff"        # a JPEG
    assert page.title() == "pressed:p@ss wor"
    assert seen["second"] > seen["first"][0]                                     # the picture changed after the input
    assert win.describe()["title"] == "example.com" and win.state["title"] == "pressed:p@ss wor"
    remote.detach(win)
    assert remote.windows() == [] and win.next_frame(999, wait_s=0.2) == (win.seq, None)


def test_nothing_is_photographed_while_nobody_looks(page):
    win = remote.attach(page, title="x")
    page.wait_for_timeout(300)
    assert win.seq == 0 and win.frame is None
    remote.detach(win)


def test_done_closes_the_window_which_is_what_the_waiting_code_looks_for(page):
    win = remote.attach(page, title="x")
    win.send([{"t": "close"}])
    remote.idle(page, 0.1)
    assert page.is_closed()
    remote.idle(page, 0.05)                  # waiting on a page that is gone does not raise
    remote.detach(win)


def test_the_api_serves_the_window_only_over_https_to_another_device(app_env, page, monkeypatch):
    from fastapi.testclient import TestClient

    from autoapply import access
    from autoapply.api.main import app

    win = remote.attach(page, title="example.com", purpose="apply")
    c = TestClient(app)
    try:
        assert c.get("/api/remote").json()[0]["id"] == win.id
        assert c.get("/api/overview").json()["remote"] == [{"id": win.id, "title": "example.com", "purpose": "apply"}]
        assert c.post(f"/api/remote/{win.id}/input", json={"events": [{"t": "click", "x": 150, "y": 230}]}).json() == {"ok": True}
        page.wait_for_timeout(200)
        assert page.title() == "pressed:"
        assert c.get("/api/remote/nope/frame").status_code == 404
        got = c.get(f"/api/remote/{win.id}/frame", params={"after": 0})          # asked from a request's thread, served by the page's
        assert got.status_code in (200, 204) and got.headers["cache-control"] == "no-store" and "X-State" in got.headers
        monkeypatch.setattr(access, "caller", lambda peer, headers: {"ip": "203.0.113.9", "https": False, "local": False})
        r = c.post(f"/api/remote/{win.id}/input", json={"events": []})
        assert r.status_code == 403 and "HTTPS" in r.json()["detail"]
        monkeypatch.setattr(access, "caller", lambda peer, headers: {"ip": "203.0.113.9", "https": True, "local": False})
        assert c.get(f"/api/remote/{win.id}").status_code == 200
    finally:
        remote.detach(win)


def test_a_visible_page_on_a_computer_without_a_screen_becomes_a_remote_window(app_env, monkeypatch):
    from autoapply import browser, db

    db.init_db()
    monkeypatch.setenv("AUTOAPPLY_NO_SCREEN", "1")
    monkeypatch.setattr(remote, "announce", lambda win: None)
    with browser.real_open_page("site:x", headless=False, url="https://jobs.example.com/apply", operation="apply") as pg:
        (w,) = remote.windows()
        assert w["title"] == "jobs.example.com" and w["purpose"] == "apply" and pg.viewport_size == remote.VIEWPORT
    assert remote.windows() == []
    with browser.real_open_page("site:x") as pg:          # a hidden page is nobody's window
        assert remote.windows() == []
