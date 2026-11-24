"""The login to the program, and where it listens."""
import json

import pytest


@pytest.fixture
def door(app_env, monkeypatch):
    """The program with its login in force (the other tests run behind it)."""
    from fastapi.testclient import TestClient

    from autoapply import access
    from autoapply.api.main import app as api

    monkeypatch.setattr(access, "enforced", lambda: True)
    access._fails.clear()
    return lambda **kw: TestClient(api, **kw)


def test_nothing_is_readable_before_the_first_set_up_and_the_set_up_is_made_on_the_computer_itself(door):
    from autoapply import access, config

    c = door()
    assert c.get("/api/overview").status_code == 401 and c.get("/api/settings").status_code == 401 and c.get("/api/documents").status_code == 401
    st = c.get("/api/auth/state").json()
    assert st["setup"] and st["can_setup"] and not st["signed_in"] and st["user"] == ""
    # someone reaching the server through a proxy is not "this computer": they cannot make themselves the administrator
    far = {"X-Forwarded-For": "203.0.113.9"}
    assert c.get("/api/auth/state", headers=far).json()["can_setup"] is False
    assert c.post("/api/auth/setup", json={"user": "me", "password": "long enough pw"}, headers=far).status_code == 403
    assert c.post("/api/auth/setup", json={"user": "me", "password": "short"}).status_code == 400
    assert c.post("/api/auth/setup", json={"user": "me", "password": "long enough pw"}).json() == {"ok": True}
    assert c.get("/api/overview").status_code == 200      # the set-up signs this browser in
    assert c.get("/api/auth/state").json()["user"] == "me"
    assert c.post("/api/auth/setup", json={"user": "x", "password": "another long pw"}).status_code == 409      # once
    kept = (config.DATA / "access.json").read_text(encoding="utf-8")
    assert "long enough pw" not in kept and json.loads(kept)["admin"]["hash"]      # a hash, never the password
    cookie = c.cookies.get(access.COOKIE)
    assert cookie and cookie not in kept      # nor the cookie: a copy of the file signs nobody in


def test_signing_in_out_and_the_lock_after_wrong_passwords(door):
    from autoapply import access

    access.set_admin("me", "the right password")
    c = door()
    assert c.get("/api/overview").status_code == 401
    assert c.post("/api/auth/login", json={"user": "me", "password": "wrong"}).status_code == 401
    assert c.post("/api/auth/login", json={"user": "Me", "password": "the right password"}).json() == {"ok": True}
    assert c.get("/api/overview").status_code == 200
    other = door()      # another device
    assert other.get("/api/overview").status_code == 401
    assert c.post("/api/auth/logout", json={}).json() == {"ok": True}
    assert c.get("/api/overview").status_code == 401
    for _ in range(access.MAX_FAILS):
        assert other.post("/api/auth/login", json={"user": "me", "password": "guess"}).status_code == 401
    r = other.post("/api/auth/login", json={"user": "me", "password": "the right password"})
    assert r.status_code == 429      # the door is shut for a while, for the right password too


def test_a_new_password_ends_the_logins_on_other_devices(door):
    from autoapply import access

    access.set_admin("me", "the first password")
    here, there = door(), door()
    for c in (here, there):
        assert c.post("/api/auth/login", json={"user": "me", "password": "the first password"}).status_code == 200
    assert here.post("/api/auth/password", json={"current": "nope", "password": "the second password"}).status_code == 400
    assert here.post("/api/auth/password", json={"current": "the first password", "password": "the second password"}).json() == {"ok": True}
    assert here.get("/api/overview").status_code == 200 and there.get("/api/overview").status_code == 401
    assert access.verify("me", "the second password") and not access.verify("me", "the first password")
    access.reset_admin()      # forgotten: the tray menu / `autoapply reset-admin`
    assert here.get("/api/overview").status_code == 401 and here.get("/api/auth/state").json()["setup"] is True


def test_this_computers_own_programs_show_the_local_token_instead_of_a_login(door):
    from autoapply import access

    access.set_admin("me", "the right password")
    c = door()
    good = {access.LOCAL_HEADER: access.local_token()}
    assert c.get("/api/overview", headers=good).status_code == 200      # the tray icon
    assert c.get("/api/overview", headers={access.LOCAL_HEADER: "x" * 43}).status_code == 401
    assert c.get("/api/overview", headers={**good, "X-Forwarded-For": "203.0.113.9"}).status_code == 401      # forwarded by a proxy: not this computer


def test_the_page_loads_without_a_login_and_knows_the_path_it_is_served_under(door):
    from autoapply import access, config

    if not config.FRONTEND_DIST.exists():
        pytest.skip("the interface is not built")
    c = door()
    home = c.get("/home")
    assert home.status_code == 200 and '<base href="/" />' in home.text      # the login page has to load
    access.save_conf({"root_path": "autoapply/"})
    assert access.conf()["root_path"] == "/autoapply"
    assert '<base href="/autoapply/" />' in c.get("/home").text
    assert '<base href="/autoapply/" />' in c.get("/autoapply/drafts/3").text      # called with the prefix as well
    assert c.get("/autoapply/api/auth/state").json()["setup"] is True
    assert c.get("/autoapply/api/overview").status_code == 401


def test_the_page_and_every_answer_say_which_build_of_the_interface_is_served(door, monkeypatch, tmp_path):
    """A page left open while the program was updated finds out from the answers that another build is served
    (frontend/src/fresh.js loads it then)."""
    import re

    from autoapply import config
    from autoapply.api import main

    if not config.FRONTEND_DIST.exists():
        pytest.skip("the interface is not built")
    c = door()
    page = c.get("/home").text
    m = re.search(r'<meta name="autoapply-build" content="([0-9a-f]{12})" />', page)
    assert m, "the page is told its build"
    assert c.get("/api/auth/state").headers["X-Build"] == m.group(1)
    # the program updated: another index.html (other files named in it) - another build, said by every answer
    (tmp_path / "index.html").write_text(page.replace("/assets/", "/assets/new-"), encoding="utf-8")
    monkeypatch.setattr(config, "FRONTEND_DIST", tmp_path)
    assert main.interface_build() not in ("", m.group(1))
    assert c.get("/api/auth/state").headers["X-Build"] == main.interface_build()
    # no built interface (the development server serves its own): nothing is said
    monkeypatch.setattr(config, "FRONTEND_DIST", tmp_path / "none")
    assert main.interface_build() == "" and "X-Build" not in c.get("/api/auth/state").headers


def test_where_it_listens_is_checked_before_it_is_saved(door):
    from autoapply import access

    access.set_admin("me", "the right password")
    c = door()
    c.post("/api/auth/login", json={"user": "me", "password": "the right password"})
    assert c.get("/api/access").json()["settings"]["host"] == "127.0.0.1" and not c.get("/api/access").json()["exposed"]
    for bad in ({"host": "not an address"}, {"port": 70000}, {"root_path": "/a b"}, {"trusted_proxies": ["proxy.local"]}, {"session_days": 0}, {"nonsense": 1}):
        assert c.put("/api/access", json={"settings": bad}).status_code == 400, bad
    out = c.put("/api/access", json={"settings": {"host": "0.0.0.0", "port": 8443, "https_by_proxy": True, "allowed_hosts": ["Jobs.Example.com"]}}).json()["settings"]
    assert (out["host"], out["port"], out["https_by_proxy"], out["allowed_hosts"]) == ("0.0.0.0", 8443, True, ["jobs.example.com"])
    seen = c.get("/api/access").json()
    assert seen["exposed"] and seen["restart_needed"]      # the running server still listens where it was started


def test_behind_a_proxy_that_does_the_https_the_login_is_only_sent_over_https(door):
    from autoapply import access

    access.set_admin("me", "the right password")
    access.save_conf({"https_by_proxy": True, "allowed_hosts": ["jobs.example.com"]})
    c = door()
    via = {"Host": "jobs.example.com", "X-Forwarded-For": "198.51.100.7", "X-Forwarded-Proto": "https"}
    r = c.post("/api/auth/login", json={"user": "me", "password": "the right password"}, headers=via)
    assert r.status_code == 200 and "secure" in r.headers["set-cookie"].lower() and "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/api/overview", headers={"Host": "elsewhere.example"}).status_code == 403      # a name it was not told about
