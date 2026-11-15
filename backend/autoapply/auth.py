"""Accounts and sessions (plan section 5).

One entry point for everything else: ``ensure_session(page, driver, ref)``.
It tries, in order: saved session -> stored credentials -> registration.
If the site says the account already exists and we hold no password, it stops
and raises ``NeedsHuman`` (never resets the password).

Passwords and verification codes stay inside this module and the drivers; they
are not returned, logged, or shown to the LLM.
"""

from __future__ import annotations

import time

import csv
import io
import logging
import re
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Page

from . import browser, db, messages, notify, secrets
from .ats.base import Driver, JobRef, NeedsHuman, SiteDown, DriverError
from .models import Account, now

log = logging.getLogger("autoapply.auth")

MAX_LOGIN_FAILS = 2


# --- vault -----------------------------------------------------------------------


def upsert_account(tenant_key: str, *, ats: str = "", host: str = "", email: str | None = None, password: str | None = None,
                   status: str | None = None, created_by: str | None = None, error: str | None = None) -> None:
    with db.session() as s:
        a = s.get(Account, tenant_key)
        if a is None:
            a = Account(tenant_key=tenant_key, ats=ats or tenant_key.split(":")[0], host=host)
            s.add(a)
        if host:
            a.host = host
        if email is not None:
            a.login_email = email
        if status is not None:
            a.status = status
            if status == "ok":
                a.last_login_ok, a.fail_count, a.last_error = now(), 0, ""
        if created_by and not a.created_by:
            a.created_by = created_by
        if error is not None:
            a.last_error = error
        if password is not None:
            secrets.put_password(tenant_key, password)
            a.has_password = 1
    if status == "ok":      # the site is signed in to: a card that asked the applicant to sign in there has nothing left to ask
        from . import notify

        for kind in ("takeover", "login"):
            notify.close_todos(kind, f"account:{tenant_key}")


def key_for(tenant_key: str) -> str:
    """The key a site's sign-in is kept under: its own, or the one of the site it turned out to sign in on."""
    return str((db.get_setting("accounts.alias") or {}).get(tenant_key) or tenant_key)


def adopt(tenant_key: str, host: str) -> str | None:
    """A sign-in page on ``host`` was reached while working for ``tenant_key``, which has no sign-in of its own. If a
    sign-in for exactly that host is saved under another key (the same employer's postings were found under another
    address before), that is the account: remember the link and return its key. Only an exact host, only an account
    that has a password or a saved session, never across employers."""
    host = (host or "").lower().strip()
    if not host or key_for(tenant_key) != tenant_key or secrets.get_password(tenant_key):
        return None
    from . import browser

    with db.session() as s:
        rows = [(a.tenant_key, a.has_password) for a in s.query(Account).filter(Account.host == host, Account.tenant_key != tenant_key)]
    for key, has_pw in rows:
        if (has_pw and secrets.get_password(key)) or browser.load_state(key):
            db.set_setting("accounts.alias", {**(db.get_setting("accounts.alias") or {}), tenant_key: key})
            log.info("%s signs in on %s, where a sign-in is saved as %s: using it", tenant_key, host, key)
            return key
    return None


def account(tenant_key: str) -> dict[str, Any] | None:
    with db.session() as s:
        a = s.get(Account, tenant_key)
        if a is None:
            return None
        return {"tenant_key": a.tenant_key, "ats": a.ats, "host": a.host, "login_email": a.login_email,
                "has_password": bool(a.has_password), "status": a.status, "created_by": a.created_by,
                "last_login_ok": a.last_login_ok.isoformat() if a.last_login_ok else None,
                "last_error": a.last_error, "fail_count": a.fail_count, "created_at": a.created_at.isoformat() if a.created_at else None}


def list_accounts() -> list[dict[str, Any]]:
    with db.session() as s:
        keys = [a.tenant_key for a in s.query(Account).order_by(Account.tenant_key)]
    return [{**account(k), "session": browser.session_info(k)} for k in keys]  # type: ignore[dict-item]


def delete_account(tenant_key: str) -> None:
    secrets.delete_password(tenant_key)
    browser.clear_state(tenant_key)
    with db.session() as s:
        a = s.get(Account, tenant_key)
        if a:
            s.delete(a)


def _bump_fail(tenant_key: str, err: str) -> int:
    with db.session() as s:
        a = s.get(Account, tenant_key)
        if a is None:
            return 0
        a.fail_count += 1
        a.last_error = err
        if a.fail_count >= MAX_LOGIN_FAILS:
            a.status = "needs_human"
        return a.fail_count


def login_email() -> str:
    return str(db.get_setting("account.email") or "")


APPLIED = ("submitted", "confirmed", "assessment", "interview", "offer", "rejected")


def likely_registered(ref: JobRef) -> str:
    """Why the user probably already has an account on this site ('' when there is no sign of one).

    The user registers by hand on sites they have applied on before, so an earlier application to the
    same employer is the signal. Sites with no such history are registered by the agent."""
    from .models import Application, Job

    acct = account(ref.tenant_key)
    if acct and "already exists" in (acct.get("last_error") or ""):
        return "这个邮箱在该网站上已经注册过"
    with db.session() as s:
        q = s.query(Job).filter(Job.ats == ref.ats, Job.tenant == ref.tenant) if ref.ats != "generic" else s.query(Job).filter(Job.apply_url.like(f"%{ref.host}%"))
        companies = {j.company for j in q if j.company}
        if not companies:
            return ""
        hit = s.query(Application).join(Job).filter(Application.status.in_(APPLIED), Job.company.in_(companies)).first()
        return f"你之前投过 {hit.job.company}，应该已经有账号" if hit else ""


def may_register(ref: JobRef, also: str = "") -> tuple[bool, str]:
    """(allowed, reason-when-not). The user's explicit "register for me" wins over the history guess. ``also``: the key
    the posting was found under, when its sign-in is on another site - the user's answer was given under that one."""
    if {ref.tenant_key, also} & set(db.get_setting("register.allow_keys") or []):
        return True, ""
    if not db.get_setting("register.auto") or (db.get_setting("register.per_ats") or {}).get(ref.ats) is False:
        return False, "自动注册已在设置里关闭"
    why = likely_registered(ref)
    return (False, why) if why else (True, "")


def sign_in_plan(ref: JobRef, offered: list[str] | None = None, also: str = "") -> dict[str, Any]:
    """How to get into a site that needs an account. One answer, in this order:

    1. an account this program already has for the site (stored password)      -> "password"
    2. a provider the user approved for this site, or any offered one in "auto" -> "sso"
    3. "ask" mode and an offered provider the user is signed in to              -> "ask_user"  (their choice is remembered per site)
    4. registration allowed                                                      -> "register"
    5. otherwise                                                                 -> "ask_user"
    Rule 2 comes before registering because it leaves no new password behind and needs no e-mail verification.
    """
    key = ref.tenant_key
    offered = [p for p in (offered or []) if p in browser.identities()]
    if offered:
        seen = dict(db.get_setting("sso.offered") or {})
        if seen.get(key) != offered:
            db.set_setting("sso.offered", {**seen, key: offered})
    signed_in = [p for p in (db.get_setting("sso.order") or []) if p in offered and (i := browser.session_info(f"idp:{p}")) and not i["expired"]]
    can_register, why = may_register(ref, also)
    acct = account(key) or {}
    base = {"login_email": login_email(), "has_password": bool(secrets.get_password(key)), "may_register": can_register, "why_not_register": why,
            "offered": offered, "signed_in_providers": signed_in}
    if acct.get("status") == "pending" and base["has_password"]:
        # registered in an earlier run that stopped before the address was confirmed
        return {**base, "do": "verify_then_password", "pending_verification": True}
    if base["has_password"]:
        return {**base, "do": "password"}
    mode, sites = db.get_setting("sso.mode") or "ask", db.get_setting("sso.sites") or {}
    chosen = sites.get(key) if key in sites else sites.get(also)
    if chosen and chosen in signed_in:
        return {**base, "do": "sso", "provider": chosen}
    if chosen == "" or mode == "never" or not signed_in:
        return {**base, "do": "register" if can_register else "ask_user"}
    if mode == "auto":
        return {**base, "do": "sso", "provider": signed_in[0]}
    return {**base, "do": "ask_user", "why": "the applicant has not yet chosen how to sign in to this site"}


def choose_sign_in(tenant_key: str, provider: str) -> None:
    """The user's answer for one site: a provider key, or "" for "do not use a provider here"."""
    db.set_setting("sso.sites", {**(db.get_setting("sso.sites") or {}), tenant_key: provider})
    if provider == "":
        allow_register(tenant_key)
    else:
        notify.close_todos("takeover", f"account:{tenant_key}")


def allow_register(tenant_key: str) -> None:
    """The user says they have no account on this site: let the agent create one."""
    keys = list(db.get_setting("register.allow_keys") or [])
    if tenant_key not in keys:
        db.set_setting("register.allow_keys", keys + [tenant_key])
    with db.session() as s:
        a = s.get(Account, tenant_key)
        if a is not None and a.status in ("needs_human", "locked") and not a.has_password:
            a.status, a.last_error, a.fail_count = "unknown", "", 0
    notify.close_todos("takeover", f"account:{tenant_key}")


# --- the one tool ------------------------------------------------------------------


def ensure_session(page: Page, driver: Driver, ref: JobRef) -> str:
    """Make ``page``'s context logged in for ``ref``. Returns 'not_required' | 'logged_in' | 'registered'.

    Raises NeedsHuman when a person has to act (CAPTCHA, MFA, SSO, existing
    account without stored credentials, repeated failures).
    """
    if not driver.requires_login:
        return "not_required"
    key = ref.tenant_key
    acct = account(key)

    # 1. saved session (already loaded into the context by browser.open_page)
    if driver.is_logged_in(page, ref):
        upsert_account(key, ats=ref.ats, host=ref.host, status="ok")
        browser.save_state(key, page.context)
        return "logged_in"

    if getattr(driver, "sso", False):
        _need_takeover(ref, driver, f"The {ref.ats} session has expired; please sign in (SSO / MFA).")

    email = (acct or {}).get("login_email") or login_email()
    if not email:
        raise NeedsHuman("No login e-mail configured. Set it in Settings.", kind="config")

    # 2. stored credentials
    pw = secrets.get_password(key)
    if pw:
        if acct and acct["fail_count"] >= MAX_LOGIN_FAILS:
            _need_takeover(ref, driver, "Login failed twice with the stored password; please sign in yourself.")
        try:
            driver.login(page, ref, email, pw)
        except (NeedsHuman, SiteDown):
            raise
        except Exception as e:  # noqa: BLE001
            msg = secrets.redact(str(e), pw)
            if isinstance(e, DriverError) and re.search(r"sign-in rejected|rejected|incorrect|invalid (password|credentials)|wrong password", str(e), re.I):
                # The site itself refused the stored password: that counts. Two refusals and the program stops trying it,
                # so that an account is not locked by the same wrong password being sent again and again.
                n = _bump_fail(key, msg)
                log.warning("the site refused the stored password for %s (%d): %s", key, n, msg)
            else:
                # The program could not work the sign-in page (a field that did not appear, a time-out). That says nothing
                # about the password, so it does not count towards "the stored password failed twice".
                upsert_account(key, ats=ref.ats, host=ref.host, error=msg[:300])
                log.warning("could not work the sign-in page of %s: %s", key, msg)
            _need_takeover(ref, driver, f"Automatic login failed: {msg[:200]}")
        if driver.is_logged_in(page, ref):
            upsert_account(key, ats=ref.ats, host=ref.host, email=email, status="ok")
            browser.save_state(key, page.context)
            return "logged_in"
        _bump_fail(key, "login did not result in a signed-in session")
        _need_takeover(ref, driver, "Login did not succeed; please sign in yourself.")

    # 3. registration: the agent registers on sites the user has not applied on before;
    #    where an account probably exists, the user signs in once and the credentials are saved.
    ok, why = may_register(ref)
    if acct and acct["status"] in ("needs_human", "locked") and key not in (db.get_setting("register.allow_keys") or []):
        _need_takeover(ref, driver, why or "这个账号需要你登录一次。")
    if not ok:
        _need_takeover(ref, driver, f"{why}。请登录一次，登录状态和密码会保存下来；如果你其实没有注册过，可以改让 agent 注册。")
    new_pw = secrets.generate_password(driver.password_policy.length, symbols=driver.password_policy.symbols)
    # Save BEFORE submitting so the password cannot be lost mid-flow.
    upsert_account(key, ats=ref.ats, host=ref.host, email=email, password=new_pw, status="pending", created_by="agent")
    try:
        outcome = driver.register(page, ref, email, new_pw)
    except SiteDown:
        delete_account(key)  # nothing was sent: do not keep a password for an account that does not exist
        raise
    except NeedsHuman:
        raise
    except Exception as e:  # noqa: BLE001
        outcome = f"error: {secrets.redact(str(e), new_pw)[:200]}"
    if outcome == "exists":
        # Account predates us: drop the unused password and hand over. No reset.
        secrets.delete_password(key)
        upsert_account(key, status="needs_human", error="account already exists")
        with db.session() as s:
            a = s.get(Account, key)
            if a:
                a.has_password = 0
        _need_takeover(ref, driver, "An account with this e-mail already exists. Sign in once and the credentials will be saved.", kind="takeover")
    if outcome == "verify_email":
        from . import mail

        link_or_code = mail.wait_for_verification(sender_hint=ref.host or ref.tenant, timeout=180)
        if link_or_code is None:
            raise NeedsHuman("Verification e-mail did not arrive within 3 minutes.", kind="login", url=driver.login_url(ref))
        if link_or_code.startswith("http"):
            page.goto(link_or_code, wait_until="domcontentloaded")
        else:
            driver.enter_verification_code(page, link_or_code)  # type: ignore[attr-defined]
        outcome = "ok"
    if outcome != "ok":
        upsert_account(key, status="needs_human", error=str(outcome))
        _need_takeover(ref, driver, f"Registration did not complete ({outcome}).")
    if not driver.is_logged_in(page, ref):
        driver.login(page, ref, email, new_pw)
    if driver.is_logged_in(page, ref):
        upsert_account(key, status="ok")
        browser.save_state(key, page.context)
        notify.send("task_result", messages.registered(key), ref=f"account:{key}")
        return "registered"
    upsert_account(key, status="needs_human", error="registered but could not sign in")
    _need_takeover(ref, driver, "Registered, but signing in failed.")
    raise AssertionError("unreachable")


def _need_takeover(ref: JobRef, driver: Driver, reason: str, kind: str = "login") -> None:
    url = driver.login_url(ref) or ref.url
    notify.add_todo(
        "takeover",
        ref.tenant_key,
        body=reason,
        ref=f"account:{ref.tenant_key}",
        payload={"tenant_key": ref.tenant_key, "ats": ref.ats, "url": url, "job_url": ref.url, "can_register": True},
    )
    raise NeedsHuman(reason, kind=kind, url=url)


# --- human takeover ------------------------------------------------------------------

_CAPTURE_JS = """
(() => {
  if (window.__aaHooked) return; window.__aaHooked = true;
  const grab = () => {
    const pw = [...document.querySelectorAll('input[type=password]')].find(e => e.value);
    if (!pw) return;
    const form = pw.closest('form') || document;
    const user = [...form.querySelectorAll('input[type=email], input[type=text], input:not([type])')].find(e => e.value && e !== pw);
    try { window.aaCapture(user ? user.value : '', pw.value); } catch (e) {}
  };
  document.addEventListener('submit', grab, true);
  document.addEventListener('click', (ev) => {
    const b = ev.target.closest('button, [role=button], input[type=submit]');
    if (b) grab();
  }, true);
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') grab(); }, true);
})();
"""


def takeover(tenant_key: str, url: str, *, driver: Driver | None = None, ref: JobRef | None = None,
             save_credentials: bool = True, timeout_s: int = 600, done: Any = None) -> dict[str, Any]:
    """Open a headed window at ``url`` and wait for the user to sign in.

    On success the session is saved; if ``save_credentials`` is set, the e-mail
    and password the user typed are stored in the OS keyring (like a password
    manager would). Nothing typed is logged.
    """
    from .ats import registry
    from . import browser_policy

    selected = browser_policy.select(tenant_key, url, "login")
    if selected.backend == "nodriver":
        check = done or getattr(driver or registry.get(tenant_key.split(":")[0]), "signed_in_url", None)
        with browser.open_page(tenant_key, headless=False, url=url, operation="login") as page:
            page.goto(url, wait_until="domcontentloaded")
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                pages = page.context.pages
                if not pages:
                    return {"ok": False, "reason": "window closed before sign-in was verified"}
                if check and any(check(p.url) for p in pages):
                    browser.save_state(tenant_key, page.context)
                    upsert_account(tenant_key, host=urlparse(url).netloc, status="ok", created_by="takeover")
                    notify.close_todos("takeover", f"account:{tenant_key}")
                    return {"ok": True, "credentials_saved": False}
                if not check and driver and ref and driver.is_logged_in(page, ref, navigate=False):
                    browser.save_state(tenant_key, page.context)
                    upsert_account(tenant_key, host=urlparse(url).netloc, status="ok", created_by="takeover")
                    notify.close_todos("takeover", f"account:{tenant_key}")
                    return {"ok": True, "credentials_saved": False}
                time.sleep(1)
        return {"ok": False, "reason": "sign-in verification timed out"}

    plain = getattr(driver or registry.get(tenant_key.split(":")[0]), "signed_in_url", None)
    if plain is not None:  # this site refuses sign-in to an automated browser: plain window, human login
        res = browser.plain_login(tenant_key, url, plain)
        if not res["ok"]:
            return res
        upsert_account(tenant_key, host=urlparse(url).netloc, status="ok", created_by="takeover")
        notify.close_todos("takeover", f"account:{tenant_key}")
        return {"ok": True, "credentials_saved": False}
    captured: dict[str, str] = {}
    site = _site(urlparse(url).netloc)

    def on_capture(source: Any, user: str, pw: str) -> None:
        # only a password typed on the site itself is this site's password; one typed at Microsoft / Google / LinkedIn
        # during "Sign in with ..." belongs to that provider and is never stored
        try:
            where = _site(urlparse(source["frame"].url).netloc)
        except Exception:  # noqa: BLE001
            where = ""
        idp = any(where == d or where.endswith("." + d) for v in browser.identities().values() for d in v["domains"])
        if pw and (where == site or not idp):
            captured["user"], captured["pw"] = user, pw

    state: dict | None = None
    ok = closed = False
    waited = 0.0
    with browser.open_page(tenant_key, headless=False) as page:
        ctx = page.context
        if save_credentials:
            ctx.expose_binding("aaCapture", on_capture)
            ctx.add_init_script(_CAPTURE_JS)
        try:
            page.goto(url, wait_until="commit", timeout=120000)
        except Exception:  # noqa: BLE001 - slow or half-loaded page: the window stays open, the user can wait or reload
            pass
        while waited < timeout_s:
            try:
                page.wait_for_timeout(1500) if not page.is_closed() else time.sleep(1.5)
                pages = [p for p in ctx.pages if not p.is_closed()]
                if not pages:
                    closed = True
                    break
                # Keep the latest cookies: once the window is closed there is nothing left to read. Cookies only - asking the
                # browser for the full storage state opens a helper tab per site to read its local storage, which is what made
                # tabs flash open and shut and stole the keyboard focus from the sign-in form.
                origins = {o["origin"]: o for o in (state or {}).get("origins", [])}
                for p in pages:  # local storage of the pages that are open, read in place (no helper tabs)
                    try:
                        o, items = p.evaluate("() => [location.origin, Object.entries(localStorage).slice(0, 400)]")
                        if o.startswith("http") and items:
                            origins[o] = {"origin": o, "localStorage": [{"name": k, "value": v} for k, v in items]}
                    except Exception:  # noqa: BLE001 - navigating
                        pass
                state = {"cookies": ctx.cookies(), "origins": list(origins.values())}
            except Exception:  # noqa: BLE001 - window closed
                closed = True
                break
            waited += 1.5
            try:
                if done is not None:
                    ok = any(done(p.url) for p in pages)
                elif driver is not None and ref is not None:
                    ok = driver.is_logged_in(page, ref, navigate=False)  # type: ignore[call-arg]
                else:
                    ok = bool(captured) and page.locator("input[type=password]:visible").count() == 0
            except Exception:  # noqa: BLE001 - page navigating
                continue
            if ok:
                try:
                    page.wait_for_timeout(1500)
                    state = ctx.storage_state() if done is None else {"cookies": ctx.cookies(), "origins": []}  # once, at the end
                except Exception:  # noqa: BLE001
                    pass
                break
    unverified = False
    if not ok and closed and state is not None and done is None and (driver is None or ref is None):
        # A site this program has no sign-in check for (typically "Sign in with Microsoft / Google"): there is nothing to
        # detect, so the user closing the window is their "done". If they were not signed in, the next attempt asks again.
        ok = unverified = True
    if ok and state is not None:
        browser.write_state(tenant_key, state)
    if not ok:
        return {"ok": False, "reason": "窗口关闭前没有检测到登录成功" if closed else "等了 10 分钟没有检测到登录成功"}
    if done is not None:
        return {"ok": True, "credentials_saved": False}
    host = urlparse(url).netloc
    saved = False
    if save_credentials and captured.get("pw"):
        upsert_account(tenant_key, host=host, email=captured.get("user") or login_email(), password=captured["pw"], status="ok", created_by="takeover")
        saved = True
    else:
        upsert_account(tenant_key, host=host, status="ok", created_by="takeover")
    notify.close_todos("takeover", f"account:{tenant_key}")
    return {"ok": True, "credentials_saved": saved, "unverified": unverified}


def _site(host: str) -> str:
    """Registrable part of a host name, good enough to tell "the same site" from "a sign-in provider"."""
    parts = host.lower().split(":")[0].split(".")
    return ".".join(parts[-3:] if len(parts) >= 3 and len(parts[-1]) == 2 and len(parts[-2]) <= 3 else parts[-2:])


def identity_login(provider: str) -> dict[str, Any]:
    """The user signs in to Microsoft / Google / LinkedIn once, in this program's window; only the session is kept, never the password."""
    spec = browser.identities()[provider]
    return takeover(f"idp:{provider}", spec["url"], save_credentials=False, done=spec["done"])


def identity_email(provider: str) -> str:
    """The e-mail of the user's account at a sign-in provider, if they told us (it can differ from the application e-mail)."""
    return str((db.get_setting("identity.emails") or {}).get(provider) or "").strip()


def identities() -> list[dict[str, Any]]:
    return [{"key": k, "name": v["name"], "session": browser.session_info(f"idp:{k}"), "note": v.get("note", ""), "region": v.get("region", ""), "custom": bool(v.get("custom")), "email": identity_email(k)}
            for k, v in browser.identities().items()]


# --- Chrome password CSV import ------------------------------------------------------


def tenant_key_for_url(url: str) -> str | None:
    """Map a saved-login URL to a tenant key (same rule the drivers use)."""
    from .ats import registry

    host = urlparse(url if "//" in url else f"https://{url}").netloc.lower()
    if not host:
        return None
    from .ats.base import host_is

    if host_is(host, "myworkdayjobs.com") or host_is(host, "myworkdaysite.com"):
        return f"workday:{host.split('.myworkday')[0]}"
    for suffix, ats in registry.KNOWN_HOSTS.items():
        if host_is(host, suffix):
            return f"{ats}:{host.split('.')[0]}"
    if host_is(host, "ashbyhq.com") or host_is(host, "greenhouse.io"):
        return None  # no accounts on these
    return None


def import_chrome_csv(content: str, *, only_known: bool = True) -> dict[str, Any]:
    """Import logins from a Chrome password export (columns: name,url,username,password,note).

    Only rows whose URL maps to a known ATS tenant are imported. The CSV content
    is not stored; callers should delete the file afterwards.
    """
    imported, skipped = [], 0
    for row in csv.DictReader(io.StringIO(content)):
        url, user, pw = row.get("url", ""), row.get("username", ""), row.get("password", "")
        key = tenant_key_for_url(url)
        if not key or not pw:
            skipped += 1
            continue
        upsert_account(key, host=urlparse(url).netloc, email=user, password=pw, status="unknown", created_by="chrome_csv")
        imported.append(key)
    return {"imported": sorted(set(imported)), "skipped": skipped}
