"""Accounts and sign-ins.

What is kept about the applicant's account on a site (the login name; whether a password is stored - the password
itself is in the keyring, secrets.py), the window in which the applicant signs in by hand, and what that window may
remember. Signing in while an application is worked is the agent's (agent/run.py: ``type_password`` types a stored
password where it belongs, without the agent seeing it); this module never drives a sign-in page.

Passwords and verification codes are not returned, logged, or shown to a model.
"""

from __future__ import annotations

from .say import say as T

import csv
import io
import json
import logging
import re
import time
from typing import Any
from urllib.parse import parse_qsl, urlparse

from . import browser, db, notify, secrets
from .models import Account, now

log = logging.getLogger("autoapply.auth")

# Sites whose sign-in is an institution's own (a university's login): the login name there is not the applicant's
# e-mail, and the program does not put the one in the other's place.
INSTITUTIONS = ("pdportal",)
# Where it is known what a finished sign-in looks like: the address the window is on then.
SIGNED_IN = {"pdportal": lambda url: "pdportal.apsc.ubc.ca/myAccount" in url}


# --- what is kept --------------------------------------------------------------------


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
            if status == "pending":
                a.created_at = now()        # the account as it is now is being made now: its confirmation mail is from now on
    if status == "ok":      # the site is signed in to: a card that asked the applicant to sign in there has nothing left to ask
        from . import notify

        for kind in ("takeover", "login"):
            notify.close_todos(kind, f"account:{tenant_key}")


def key_for(tenant_key: str) -> str:
    """The key a site's sign-in is kept under: its own, or the one of the site it turned out to sign in on."""
    from . import sites

    return sites.account(tenant_key)


def provider_at(*places: str) -> str:
    """The sign-in provider one of these addresses (or a text quoting addresses) is the sign-in page of, or ""."""
    hosts = set()
    for p in places:      # by host - of an address, or a host name quoted in a note - never by a name somewhere in the text
        for u in re.findall(r"https?://[^\s\"'<>)]+", p or ""):
            hosts.add((urlparse(u).hostname or "").lower())
        hosts.update(re.findall(r"\b[a-z0-9.-]+\.[a-z]{2,}\b", (p or "").lower()))
    for key, spec in browser.identities().items():
        at = (urlparse(spec["url"]).hostname or "").lower()
        if at and at in hosts:
            return key
    return ""


def ask_to_sign_in(site: str, title: str, reason: str, *, url: str = "", job_url: str = "", **payload: Any) -> str:
    """The one card that asks the applicant to sign in, wherever the need was met.

    It names whose sign-in is missing. When the site's sign-in is a provider's own (Google's careers site and Google),
    or the run stopped on a provider's sign-in page, what is missing is the provider's session: the card is the
    provider's, and signing in there is the whole of it. Otherwise it is the site's.
    Returns what the card is filed under ("account:idp:google") - what the task that met it now waits for."""
    key = key_for(site)
    provider = key[4:] if key.startswith("idp:") else provider_at(url, reason)
    spec = browser.identities().get(provider) if provider else None
    if spec:
        notify.add_todo("takeover", spec["name"], body=reason, ref=f"account:idp:{provider}",
                        payload={**payload, "tenant_key": f"idp:{provider}", "url": spec["url"], "job_url": job_url, "provider": spec["name"], "for": title})
        return f"account:idp:{provider}"
    notify.add_todo("takeover", title, body=reason, ref=f"account:{key}", payload={**payload, "tenant_key": key, "url": url or job_url, "job_url": job_url})
    return f"account:{key}"


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


def login_email() -> str:
    return str(db.get_setting("account.email") or "")


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


def takeover(tenant_key: str, url: str, *, save_credentials: bool = True, timeout_s: int = 600, done: Any = None) -> dict[str, Any]:
    """Open a headed window at ``url`` and wait for the user to sign in.

    On success the session is saved; if ``save_credentials`` is set, the e-mail
    and password the user typed are stored in the OS keyring (like a password
    manager would). Nothing typed is logged.
    """
    from . import browser_policy

    known = SIGNED_IN.get(tenant_key.split(":")[0])
    if tenant_key.startswith("idp:") and done is None:
        # A sign-in provider (Google, LinkedIn ...) has no password to keep:
        # what tells that its sign-in is finished is the provider's own check. A card for a provider is opened by the
        # same button as a card for a site, so the difference is made here, not by whoever calls.
        spec = browser.identities().get(tenant_key[4:])
        if spec is not None:
            done, save_credentials, url = spec["done"], False, url or spec["url"]

    selected = browser_policy.select(tenant_key, url, "login")
    if selected.backend == "nodriver":
        check = done or known
        with browser.open_page(tenant_key, headless=False, url=url, operation="login") as page:
            try:      # the applicant takes it from here; a page that redirects while it loads is no reason to give up
                page.goto(url, wait_until="commit", timeout=30000)
            except Exception as e:  # noqa: BLE001
                log.info("sign-in window for %s: the first page did not report loading (%s)", tenant_key, type(e).__name__)

            # "Remember the password I type": in this browser it is heard from what the sign-in form sends (the
            # browser tells; nothing is put into the page). That also hears a form the browser's own password manager
            # filled in, where nothing was typed at all. (This window used to remember nothing, whatever was ticked.)
            sent: dict[str, str] = {}
            hears: set[int] = set()
            site_ = _site(urlparse(url).netloc)

            def heard(address: str, method: str, body: str) -> None:
                where = urlparse(address).netloc.lower()
                found = credentials_sent(body) if _this_sites_password(where, site_) else None
                # (a login without its name does not take the place of one that had it: what follows a sign-in -
                # a code, a confirmation - is not the sign-in sent again)
                if found and (found[0] or not sent.get("user")):
                    sent.update(user=found[0], pw=found[1], host=where)

            def listen() -> None:
                if not save_credentials or done is not None:
                    return
                for p in page.context.pages:
                    if id(p) not in hears and hasattr(p, "on_request"):
                        hears.add(id(p))
                        p.on_request(heard)

            try:
                listen()
            except Exception as e:  # noqa: BLE001 - the window is still for signing in
                log.info("sign-in window for %s: cannot hear what is sent (%s)", tenant_key, type(e).__name__)

            def keep() -> dict[str, Any]:
                """The window is signed in: keep its session. If a page cannot be read for its storage just now (it is
                still loading, or it is a provider's page that never settles), the cookies are what a session is."""
                try:
                    browser.save_state(tenant_key, page.context)
                except Exception as e:  # noqa: BLE001
                    log.info("session of %s kept from its cookies (%s)", tenant_key, type(e).__name__)
                    browser.write_state(tenant_key, {"cookies": page.context.cookies(), "origins": []})
                saved = False
                if done is None:      # a site's account; a sign-in told by the caller's own check (a provider's) is a session and no account
                    saved = _signed_in_by_hand(tenant_key, urlparse(url).netloc, sent if save_credentials else {})
                notify.close_todos("takeover", f"account:{tenant_key}")
                return {"ok": True, "credentials_saved": saved}

            # Nothing to tell a finished sign-in by (no check for this site): then the applicant closing the window
            # is their "done", as it is in the other browser - and what the window held has to be read while it is
            # open, for once it is closed there is nothing left to read.
            blind = not check
            held: list[dict[str, Any]] = []

            def closed() -> dict[str, Any]:
                if blind and held:
                    browser.write_state(tenant_key, {"cookies": held, "origins": []})
                    saved = _signed_in_by_hand(tenant_key, urlparse(url).netloc, sent if save_credentials else {})
                    notify.close_todos("takeover", f"account:{tenant_key}")
                    return {"ok": True, "credentials_saved": saved, "unverified": True}
                return {"ok": False, "reason": "window closed before sign-in was verified"}

            deadline, misses = time.monotonic() + timeout_s, 0
            while time.monotonic() < deadline:
                try:
                    listen()        # (a sign-in that opened a tab of its own is heard there too)
                    urls = [p.url for p in page.context.pages]
                    if blind and urls:
                        held = page.context.cookies() or held
                    misses = 0
                except Exception:  # noqa: BLE001 - between two pages, or the window is going away
                    misses += 1
                    if misses >= 5:
                        return closed()
                    browser.idle(page, 1)
                    continue
                if not urls:
                    return closed()
                if check and any(check(u) for u in urls):
                    return keep()
                browser.idle(page, 1)
        return {"ok": False, "reason": "sign-in verification timed out"}

    plain = known
    if plain is not None and browser.no_screen():
        done, plain = done or known, None        # an ordinary browser window needs a screen: here the sign-in goes through the remote window
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
            where = urlparse(source["frame"].url).netloc
        except Exception:  # noqa: BLE001
            where = ""
        if pw and _this_sites_password(where, site):
            captured["user"], captured["pw"] = user, pw
            try:
                captured["host"] = urlparse(source["frame"].url).netloc.lower()
            except Exception:  # noqa: BLE001
                pass

    state: dict | None = None
    ok = closed = False
    waited = 0.0
    with browser.open_page(tenant_key, headless=False, url=url, operation="login") as page:
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
                browser.idle(page, 1.5)
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
    if not ok and closed and state is not None and done is None:
        # A site this program has no sign-in check for (typically "Sign in with Microsoft / Google"): there is nothing to
        # detect, so the user closing the window is their "done". If they were not signed in, the next attempt asks again.
        ok = unverified = True
    if ok and state is not None:
        browser.write_state(tenant_key, state)
    if not ok:
        return {"ok": False, "reason": T("server.auth.noSuccessfulSignIn") if closed else T("server.auth.noSuccessfulSignIn2")}
    if done is not None:
        notify.close_todos("takeover", f"account:{tenant_key}")      # the card that asked for this sign-in has its answer, as in the other browser
        return {"ok": True, "credentials_saved": False}
    saved = _signed_in_by_hand(tenant_key, urlparse(url).netloc, captured if save_credentials else {})
    notify.close_todos("takeover", f"account:{tenant_key}")
    return {"ok": True, "credentials_saved": saved, "unverified": unverified}


def _signed_in_by_hand(tenant_key: str, host: str, captured: dict[str, str]) -> bool:
    """The applicant has signed in to a site in the program's window: the account is good, and the login they used -
    when it was to be remembered and was seen - is kept in the keyring. True when it was kept. The same for both
    browsers' windows."""
    if not captured.get("pw"):
        upsert_account(tenant_key, host=host, status="ok", created_by="takeover")
        return False
    sso = tenant_key.split(":")[0] in INSTITUTIONS
    # (an institution's login name is its own - a CWL name: where none was seen, the applicant's e-mail is not put in its place)
    upsert_account(tenant_key, host=host, email=captured.get("user") or ("" if sso else login_email()), password=captured["pw"], status="ok", created_by="takeover")
    typed_on = captured.get("host") or ""
    if typed_on and _site(typed_on) != _site(host):
        # the site took its password on another address (its sign-in lives there): known from now on, so that the
        # program types it there too instead of taking that page for another site's
        from . import sites

        sites.set_fact(tenant_key, "sign_in_hosts", sorted({*(sites.fact(tenant_key, "sign_in_hosts") or []), typed_on}))
    return True


def remembers_login(tenant_key: str, url: str = "") -> bool:
    """Can the sign-in window for this site keep the login the applicant uses in it ("remember the password I type")?
    The card offers it only where this is so - what it offers is done. Not for a sign-in provider: its password is
    never stored, only its session. Not where the window is one the program does not look into until the sign-in is
    done (browser.plain_login - a site that refuses the automated browser, with the ordinary one switched off): there
    is nothing to hear. This follows takeover()'s own choice of window."""
    if tenant_key.startswith("idp:"):
        return False
    from . import browser_policy

    try:
        if browser_policy.select(tenant_key, url, "login").backend == "nodriver":
            return True
    except Exception:  # noqa: BLE001
        pass
    return SIGNED_IN.get(tenant_key.split(":")[0]) is None or browser.no_screen()


def _this_sites_password(where: str, site: str) -> bool:
    """Is a password given at the address ``where`` this site's (``site``: its registrable name)? One given on the site
    itself is, and so is one given at the site's own sign-in elsewhere (an institution's login). One given at
    Microsoft / Google / LinkedIn during "Sign in with ..." belongs to that provider and is never stored."""
    where = _site(where)
    idp = any(where == d or where.endswith("." + d) for v in browser.identities().values() for d in v["domains"])
    return bool(where) and (where == site or not idp)


_PASSWORD_FIELD = re.compile(r"pass|pwd|(?<![a-z])pw(?![a-z])", re.I)
_OTHER_PASSWORD = re.compile(r"new|confirm|repeat|again|retype|verify", re.I)
# what a second factor is sent as: used once, and never the account's password ("passcode" has "pass" in it)
_ONE_TIME = re.compile(r"code|otp|token|(?<![a-z])pin(?![a-z])|mfa|2fa|totp|challenge|answer", re.I)
_LOGIN_FIELD = re.compile(r"user|e-?mail|login|identifier|account", re.I)


def credentials_sent(body: str) -> tuple[str, str] | None:
    """(login name, password) from the body of a request a sign-in form sent - form fields or JSON - or None when it
    carries no password. Never logged, never kept anywhere but the keyring."""
    text = (body or "").strip()
    fields: list[tuple[str, str]] = []
    if text[:1] in "{[":
        def walk(node: Any, name: str = "") -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, str(k))
            elif isinstance(node, list):
                for v in node:
                    walk(v, name)
            elif isinstance(node, str):
                fields.append((name, node))

        try:
            walk(json.loads(text))
        except ValueError:
            return None
    else:
        fields = parse_qsl(text, keep_blank_values=False)
    pw = next((v for k, v in fields if v and _PASSWORD_FIELD.search(k) and not _OTHER_PASSWORD.search(k) and not _ONE_TIME.search(k)), "")
    if not pw:
        return None
    user = (next((v for k, v in fields if v and _LOGIN_FIELD.search(k) and not _PASSWORD_FIELD.search(k)), "")
            or next((v for k, v in fields if "@" in v and v != pw and not _PASSWORD_FIELD.search(k)), ""))
    return user, pw


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

WITH_ACCOUNTS = ("workday", "oracle", "eightfold", "icims")      # recruiting systems on which each employer's site has accounts of its own


def tenant_key_for_url(url: str) -> str | None:
    """The site a saved login belongs to, when it is an employer's site on a recruiting system that has accounts; None for
    everything else in a browser's export (it is the applicant's whole password list)."""
    from . import sites

    system, _ = sites.where(url)
    return sites.key_of(url) if system in WITH_ACCOUNTS else None


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
