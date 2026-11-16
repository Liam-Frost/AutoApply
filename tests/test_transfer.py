"""Carrying a sign-in from the computer it was made on to the one that needs it."""

from __future__ import annotations

import pytest

from autoapply import browser, transfer

STATE = {"cookies": [{"name": "sid", "value": "very-secret-cookie", "domain": ".jobs.example.com", "path": "/"}], "origins": []}


def test_a_saved_sign_in_travels_as_a_file_only_the_passphrase_opens(app_env):
    from autoapply import db

    db.init_db()
    browser.write_state("workday:acme", STATE)
    blob = transfer.export("workday:acme", "correct horse battery", host="acme.wd1.myworkdayjobs.com")
    assert b"very-secret-cookie" not in blob and b"sid" not in blob
    with pytest.raises(transfer.Refused, match="口令不对"):
        transfer.read(blob, "wrong passphrase")
    browser.clear_state("workday:acme")                                  # "the other computer"
    assert transfer.put(blob, "correct horse battery") == {"tenant": "workday:acme", "host": "acme.wd1.myworkdayjobs.com"}
    assert browser.load_state("workday:acme") == STATE
    from autoapply import auth

    (account,) = [a for a in auth.list_accounts() if a["tenant_key"] == "workday:acme"]
    assert account["status"] == "ok" and account["host"] == "acme.wd1.myworkdayjobs.com"


def test_what_is_not_such_a_file_or_has_a_weak_passphrase_is_refused(app_env):
    with pytest.raises(transfer.Refused, match="没有保存的登录状态"):
        transfer.export("nobody:here", "long enough passphrase")
    browser.write_state("site:x", STATE)
    with pytest.raises(transfer.Refused, match="至少"):
        transfer.export("site:x", "short")
    for junk in (b"", b"not json", b'{"kind": "something else"}', b'{"kind": "autoapply-session", "v": 1}'):
        with pytest.raises(transfer.Refused):
            transfer.read(junk, "long enough passphrase")


def test_through_the_api_the_file_is_a_download_and_an_upload(app_env):
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app

    db.init_db()
    browser.write_state("idp:google", STATE)
    c = TestClient(app)
    assert c.get("/api/accounts/sessions").json() == [{"tenant_key": "idp:google", "name": "Google"}]
    r = c.post("/api/accounts/session/export", json={"tenant_key": "idp:google", "passphrase": "long enough passphrase"})
    assert r.status_code == 200 and r.headers["content-disposition"] == 'attachment; filename="idp-google.aasession"' and r.headers["cache-control"] == "no-store"
    assert c.post("/api/accounts/session/export", json={"tenant_key": "idp:google", "passphrase": "x"}).status_code == 400
    browser.clear_state("idp:google")
    bad = c.post("/api/accounts/session/import", files={"file": ("s.aasession", r.content)}, data={"passphrase": "another passphrase"})
    assert bad.status_code == 400 and browser.load_state("idp:google") is None
    ok = c.post("/api/accounts/session/import", files={"file": ("s.aasession", r.content)}, data={"passphrase": "long enough passphrase"})
    assert ok.status_code == 200 and ok.json()["tenant"] == "idp:google" and browser.load_state("idp:google") == STATE
