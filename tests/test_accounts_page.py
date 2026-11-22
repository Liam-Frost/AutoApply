"""The site-accounts page: what the list says about an account (password, session and readiness are three things),
and the two things the page can now take away one at a time - the saved session, the stored password - without
deleting the account. Every value here is made up."""

import time

import pytest

PW = "hunter2-demo"


def _client():
    from fastapi.testclient import TestClient

    from autoapply.api.main import app

    return TestClient(app)


def _cookie(expires):
    return {"name": "sid", "value": "made-up", "domain": ".northwind.example", "path": "/", "expires": expires, "httpOnly": True, "secure": True, "sameSite": "Lax"}


def _session(key, expires):
    from autoapply import browser

    browser.write_state(key, {"cookies": [_cookie(expires)], "origins": []}, made_in="")


@pytest.mark.parametrize(("row", "session", "want"), [
    ({"status": "ok", "has_password": True}, None, "ready"),
    ({"status": "ok", "has_password": False}, {"expired": False}, "ready"),
    # a sign-in worked once, and nothing is left to repeat it with
    ({"status": "ok", "has_password": False}, None, "manual"),
    ({"status": "ok", "has_password": False}, {"expired": True}, "manual"),
    ({"status": "needs_human", "has_password": True, "last_error": "the site asks for a code sent by SMS"}, None, "manual"),
    ({"status": "pending", "has_password": True, "created_by": "agent"}, None, "verify"),
    ({"status": "pending", "has_password": True, "created_by": "agent", "last_error": "TimeoutError: Locator.click"}, None, "register_failed"),
    # it signed in before: what failed is a sign-in, not the registration
    ({"status": "unknown", "created_by": "agent", "last_login_ok": "2026-11-01T10:00:00", "last_error": "Error: refused"}, None, "signin_failed"),
    ({"status": "unknown", "created_by": "chrome_csv", "has_password": True, "last_error": "Error: refused"}, None, "signin_failed"),
    ({"status": "locked", "last_error": "too many attempts"}, None, "locked"),
    ({"status": "unknown", "has_password": True}, None, "never"),
    ({"status": "not_needed"}, None, "not_needed"),
    ({}, None, "never"),
])
def test_readiness_is_told_from_the_record(row, session, want):
    from autoapply import auth

    assert auth.readiness(row, session) == want


def test_the_list_says_password_session_and_readiness_apart(app_env):
    from autoapply import auth

    auth.upsert_account("workday:northwind.wd3", host="northwind.wd3.myworkdayjobs.com", email="alex@example.com", password=PW, status="ok", created_by="takeover")
    _session("workday:northwind.wd3", time.time() + 86400)
    auth.upsert_account("workday:globex.wd1", host="globex.wd1.myworkdayjobs.com", email="alex@example.com", status="ok", created_by="takeover")
    _session("workday:globex.wd1", time.time() - 86400)
    auth.upsert_account("workday:initech.wd5", host="initech.wd5.myworkdayjobs.com", email="alex@example.com", password=PW, status="pending", created_by="agent")

    answer = _client().get("/api/accounts")
    rows = {r["tenant_key"]: r for r in answer.json()}
    a, b, c = rows["workday:northwind.wd3"], rows["workday:globex.wd1"], rows["workday:initech.wd5"]
    assert (a["has_password"], a["session"]["expired"], a["automation"]) == (True, False, "ready")
    assert a["session"]["valid_until"] and a["session"]["saved_at"]
    assert (b["has_password"], b["session"]["expired"], b["automation"]) == (False, True, "manual")
    assert (c["has_password"], c["session"], c["automation"]) == (True, None, "verify")
    assert PW not in answer.text      # the list never carries a password


def test_clearing_the_session_leaves_the_account_and_its_password(app_env):
    from autoapply import auth, browser, secrets

    key = "workday:northwind.wd3"
    auth.upsert_account(key, host="northwind.wd3.myworkdayjobs.com", email="alex@example.com", password=PW, status="ok", created_by="takeover")
    _session(key, time.time() + 86400)
    c = _client()

    assert c.delete(f"/api/accounts/{key}/session").json() == {"ok": True}
    assert browser.session_info(key) is None
    assert secrets.get_password(key) == PW
    row = next(r for r in c.get("/api/accounts").json() if r["tenant_key"] == key)
    assert (row["session"], row["has_password"], row["login_email"], row["automation"]) == (None, True, "alex@example.com", "ready")
    # (nothing to clear is not an error: the account is there)
    assert c.delete(f"/api/accounts/{key}/session").status_code == 200


def test_removing_the_password_leaves_the_account_and_its_session(app_env):
    from autoapply import auth, browser, secrets

    key = "workday:northwind.wd3"
    auth.upsert_account(key, host="northwind.wd3.myworkdayjobs.com", email="alex@example.com", password=PW, status="ok", created_by="takeover")
    _session(key, time.time() + 86400)
    c = _client()

    assert c.delete(f"/api/accounts/{key}/password").json() == {"ok": True}
    assert secrets.get_password(key) is None
    assert browser.session_info(key) is not None
    row = next(r for r in c.get("/api/accounts").json() if r["tenant_key"] == key)
    assert (row["has_password"], row["login_email"], row["session"]["expired"]) == (False, "alex@example.com", False)
    assert c.post(f"/api/accounts/{key}/reveal", json={"confirm": key}).json() == {"password": None}


def test_neither_makes_an_account_that_is_not_there(app_env):
    from autoapply import auth

    c = _client()
    assert c.delete("/api/accounts/workday:nobody.wd1/session").status_code == 404
    assert c.delete("/api/accounts/workday:nobody.wd1/password").status_code == 404
    assert auth.list_accounts() == []


def test_a_password_is_given_only_to_who_names_the_site(app_env):
    """The boundary the page keeps: the password leaves the store through this one request, and only with the site's
    own key repeated in it."""
    from autoapply import auth

    key = "workday:northwind.wd3"
    auth.upsert_account(key, host="northwind.wd3.myworkdayjobs.com", email="alex@example.com", password=PW, status="ok", created_by="takeover")
    c = _client()
    assert c.post(f"/api/accounts/{key}/reveal", json={}).status_code == 400
    assert c.post(f"/api/accounts/{key}/reveal", json={"confirm": "yes"}).status_code == 400
    assert c.post(f"/api/accounts/{key}/reveal", json={"confirm": key}).json() == {"password": PW}
