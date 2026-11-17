"""An account whose e-mail address is not confirmed yet.

The story these tests come from: the program registered on an employer's Workday. The site answered "An email has been
sent to you. Please verify your account." in the banner it also uses for errors, so the registration was filed as failed
and the applicant was asked to sign in. The mail had arrived 22 seconds later, with a link on the site's own address.
Nobody opened it: every later run tried the password, was told "Verify your account before you sign in", and asked the
applicant to sign in again - to an account nobody could sign in to.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from autoapply import db

HOST = "tmx.wd3.myworkdayjobs.com"
JOB = f"https://{HOST}/en-US/TMX_Careers/job/Toronto/Security-Engineer_R-1"
SENT = "An email has been sent to you. Please verify your account."
NOT_YET = "Verify your account before you sign in or request a verification email."
FILL = '<i data-automation-id="a"></i><i data-automation-id="b"></i><i data-automation-id="c"></i><i data-automation-id="d"></i>'


class Site:
    """An employer's Workday as far as accounts go: sign up, be told to verify, follow the link, sign in."""

    def __init__(self, box, *, mails=True):
        self.box, self.mails = box, mails
        self.account = self.confirmed = self.signed_in = False
        self.token, self.sent = 0, 0

    def mail(self, when=None):
        self.token += 1
        self.sent += 1
        if self.mails:
            from autoapply import mailbox

            self.box.insert(0, mailbox.Message(id=f"v{self.token}", sender="TMX <do-not-reply@tmx.com>", subject="Verify your candidate account", date=when or datetime.now(timezone.utc),
                                               body=f"Verify your account: https://{HOST}/TMX_Careers/activate/tok{self.token}/?redirect=%2FTMX_Careers%2Flogin The link is valid for 24 hours."))

    def answer(self, route):
        path = route.request.url.split(HOST, 1)[1].split("?")[0]

        def html(body):
            route.fulfill(content_type="text/html", body=f"<html><body>{FILL}{body}</body></html>")

        if path.endswith("/apply/applyManually"):
            return html('''<input data-automation-id="email"><input data-automation-id="password" type="password"><input data-automation-id="verifyPassword" type="password">
                <input type="checkbox" data-automation-id="createAccountCheckbox"><button data-automation-id="createAccountSubmitButton"
                 onclick="fetch('/api/register').then(r=>r.json()).then(j=>{document.body.insertAdjacentHTML('beforeend','<div role=alert data-automation-id=errorMessage>'+j.say+'</div>')})">Create Account</button>''')
        if path == "/api/register":
            self.account = True
            self.mail()
            return route.fulfill(content_type="application/json", body=json.dumps({"say": SENT}))
        if path.endswith("/TMX_Careers/login"):
            return html('''<input data-automation-id="email"><input data-automation-id="password" type="password"><button data-automation-id="signInSubmitButton"
                 onclick="fetch('/api/login').then(r=>r.json()).then(j=>{ if(j.ok) location.href='/en-US/TMX_Careers/userHome'; else document.body.insertAdjacentHTML('beforeend',
                 '<div role=alert data-automation-id=errorMessage>'+j.say+' <a href=# onclick=&quot;fetch(\\'/api/resend\\');return false&quot;>request a verification email</a></div>')})">Sign In</button>''')
        if path == "/api/login":
            self.signed_in = self.account and self.confirmed
            return route.fulfill(content_type="application/json", body=json.dumps({"ok": self.signed_in, "say": NOT_YET}))
        if path == "/api/resend":
            self.mail()
            return route.fulfill(content_type="application/json", body="{}")
        if "/activate/" in path:
            self.confirmed = self.confirmed or path.rstrip("/").endswith(f"tok{self.token}")       # only the newest link works
            return html("<h1>Account</h1>")
        if path.endswith("/userHome"):
            return html('<button data-automation-id="utilityButtonAccountTasksMenu">me</button><h2 data-automation-id="welcomeMsgHeader">Welcome</h2>' if self.signed_in
                        else '<button data-automation-id="signInSubmitButton">Sign In</button>')
        return html("")


class Clock:
    """Waiting for a mail without waiting."""

    def __init__(self):
        self.t = 1000.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


@pytest.fixture()
def world(app_env, monkeypatch):
    from playwright.sync_api import sync_playwright

    from autoapply import browser, mail, mailbox
    from autoapply.ats.workday import WorkdayDriver

    db.set_setting("account.email", "me@example.test")
    monkeypatch.setattr(browser, "save_state", lambda *a, **k: None)
    monkeypatch.setattr(mail, "time", Clock())
    box: list = []
    asked: list = []

    def fetch(since, limit=50, **kw):
        asked.append((since, limit))
        return [m for m in box if m.date >= since][:limit]

    monkeypatch.setattr(mailbox, "fetch", fetch)
    driver = WorkdayDriver()
    ref = driver.detect(JOB)
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        site = Site(box)
        page.route("**/*", site.answer)
        yield type("W", (), {"page": page, "site": site, "driver": driver, "ref": ref, "box": box, "asked": asked})()
        b.close()


def _cards():
    from autoapply.models import Todo

    with db.session() as s:
        return [(t.status, t.body, t.payload) for t in s.query(Todo).filter_by(kind="takeover")]


def test_a_new_account_is_confirmed_from_the_mail_and_signed_in_to(world):
    """"Please verify your account" after sign-up is not a failed registration."""
    from autoapply import auth, secrets

    assert auth.ensure_session(world.page, world.driver, world.ref) == "registered"
    a = auth.account(world.ref.tenant_key)
    assert a["status"] == "ok" and a["created_by"] == "agent" and secrets.get_password(world.ref.tenant_key)
    assert world.site.confirmed and world.site.signed_in and world.site.sent == 1 and _cards() == []


def test_an_account_left_unconfirmed_is_confirmed_at_the_next_sign_in(world):
    """Hours later, with other mail on top of the site's: the password is stored, the site says "verify your account"."""
    from autoapply import auth, mailbox
    from autoapply.ats.base import NeedsHuman, Unconfirmed
    from autoapply.models import Account, Task, Todo

    key = world.ref.tenant_key
    long_ago = datetime.now(timezone.utc) - timedelta(hours=5)
    auth.upsert_account(key, ats="workday", host=HOST, email="me@example.test", password="pw-1", status="pending", created_by="agent")
    world.site.account = True
    world.site.mail(long_ago + timedelta(seconds=22))
    world.box[:0] = [mailbox.Message(id=f"n{i}", sender="News <n@example.org>", subject="Weekly", body="nothing", date=datetime.now(timezone.utc)) for i in range(30)]
    with db.session() as s:      # as earlier versions left it: "needs you to sign in", a card, a task waiting for the applicant
        a = s.get(Account, key)
        a.status, a.created_at, a.last_error = "needs_human", long_ago.replace(tzinfo=None), f"error: {SENT}"
        s.add(Todo(kind="takeover", ref=f"account:{key}", title="TMX", body=f"The account needs e-mail verification: {NOT_YET}", payload={}))
        s.add(Task(kind="recon", ref="job:1", status="waiting_human", payload={"waits_for": f"account:{key}"}))
    with pytest.raises(Unconfirmed):      # what the driver says is what the site said
        world.driver.login(world.page, world.ref, "me@example.test", "pw-1")
    assert issubclass(Unconfirmed, NeedsHuman)

    assert auth.requeue_unconfirmed() == [key]       # once, when the program starts after the update
    with db.session() as s:
        assert s.get(Account, key).status == "pending" and s.query(Task).one().status == "queued" and s.query(Todo).one().status != "open"

    assert auth.ensure_session(world.page, world.driver, world.ref) == "logged_in"
    assert auth.account(key)["status"] == "ok" and world.site.sent == 1          # the mail from back then was enough
    assert world.asked[-1][1] > 30 and world.asked[-1][0] < long_ago + timedelta(seconds=22)     # the look went back to when the account was made


def test_a_link_that_no_longer_works_is_asked_for_again(world):
    from autoapply import auth

    key = world.ref.tenant_key
    auth.upsert_account(key, ats="workday", host=HOST, email="me@example.test", password="pw-1", status="pending", created_by="agent")
    world.site.account = True
    world.site.mail(datetime.now(timezone.utc) - timedelta(minutes=30))
    world.site.token += 1                      # the site has since made that link worthless
    assert auth.ensure_session(world.page, world.driver, world.ref) == "logged_in"
    assert world.site.sent == 2 and world.site.confirmed       # it asked the site for another mail, and used that one


def test_when_it_cannot_be_done_the_applicant_is_asked_to_open_the_mail_not_to_sign_in(world):
    from autoapply import auth
    from autoapply.ats.base import NeedsHuman

    key = world.ref.tenant_key
    world.site.mails = False                   # the mail never reaches the mailbox the program reads
    with pytest.raises(NeedsHuman) as e:
        auth.ensure_session(world.page, world.driver, world.ref)
    assert e.value.waits_for == f"account:{key}"
    a = auth.account(key)
    assert a["status"] == "pending" and a["last_error"].startswith(auth.UNCONFIRMED)       # not "needs you to sign in"
    (status, body, payload), = _cards()
    assert status == "open" and "确认邮件" in body and "不需要你登录" in body and payload["can_register"] is False
    # the card the agent's way of reading a form makes for the same account says the same thing
    auth.ask_to_sign_in(world.ref, "TMX", "The site wants a sign-in.", can_register=True)
    assert len(_cards()) == 1 or all(b == body and p["can_register"] is False for _, b, p in _cards())

    world.site.confirmed = True                # the applicant opens the mail and follows the link
    assert auth.ensure_session(world.page, world.driver, world.ref) == "logged_in"
    assert auth.account(key)["status"] == "ok" and all(s != "open" for s, _, _ in _cards())


def test_the_account_agent_leaves_such_an_account_as_what_it_is(app_env, monkeypatch):
    """The agent's sign-in tools go the same way, and an account they could not confirm stays "waiting for its
    confirmation" - the next run begins with the mail instead of with the applicant."""
    from playwright.sync_api import sync_playwright

    from autoapply import auth, generic, mail, mailbox
    from autoapply.ats.base import JobRef

    db.set_setting("account.email", "me@example.test")
    monkeypatch.setattr(mail, "time", Clock())
    box: list = []
    monkeypatch.setattr(mailbox, "fetch", lambda since, limit=50, **kw: [m for m in box if m.date >= since][:limit])
    ref = JobRef("generic", "careers.acme.test", "1", "https://careers.acme.test/job/1", "careers.acme.test")
    key = ref.tenant_key
    made = datetime.now(timezone.utc) - timedelta(hours=2)
    auth.upsert_account(key, ats="generic", host=ref.host, email="me@example.test", password="pw", status="pending", created_by="agent")
    with db.session() as s:
        from autoapply.models import Account

        s.get(Account, key).created_at = made.replace(tzinfo=None)
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.route("**/*", lambda r: r.fulfill(content_type="text/html", body="<main><h1>Sign in</h1><input id=c></main>"))
        page.goto("https://careers.acme.test/login")
        tools = {t.name: t for t in generic.account_tools(page, ref, {})}
        assert tools["account_info"].fn(offered=[])["do"] == "verify_then_password"
        assert "no verification e-mail" in tools["email_verification"].fn()
        tools["account_result"].fn(outcome="failed", notes="could not sign in")
        a = auth.account(key)
        assert a["status"] == "pending" and auth.open_the_mail(key)            # still an account that waits for its mail
        # the mail from when the account was made - two hours before this run began - is the one that is found
        box.append(mailbox.Message(id="1", sender="Acme <no-reply@acme.test>", subject="Confirm your e-mail address", date=made + timedelta(seconds=30),
                                   body="Confirm: https://careers.acme.test/confirm?t=1&amp;u=2 thanks"))
        tools = {t.name: t for t in generic.account_tools(page, ref, {})}
        assert tools["email_verification"].fn().startswith("opened the confirmation link") and "/confirm" in page.url
        # a code is typed where the page asks for it; the mail is read once
        box[:] = [mailbox.Message(id="2", sender="Acme <no-reply@acme.test>", subject="Your verification code", date=datetime.now(timezone.utc), body="Your verification code is 483920.")]
        tools = {t.name: t for t in generic.account_tools(page, ref, {})}
        assert "call again with the selector" in tools["email_verification"].fn()
        box.clear()
        assert tools["email_verification"].fn(selector="#c") == "code entered (hidden)" and page.input_value("#c") == "483920"
        b.close()


def test_account_mail_is_told_by_its_subject_and_its_links_are_kept_whole():
    import base64

    from autoapply import mail
    from autoapply.ats.base import UNCONFIRMED_RE

    for subject in ("Verify your candidate account", "Confirm your  Career Profile  email address", "Your Amazon A to Z verification code", "Activate your account",
                    "Reset your password for your candidate account"):
        assert mail.ACCOUNT_MAIL.search(subject), subject        # never summarised, stored or shown to a model
    for subject in ("Thank you for applying at Arlo!", "Interview confirmation: Software Intern", "Your application was received"):
        assert not mail.ACCOUNT_MAIL.search(subject), subject
    assert UNCONFIRMED_RE.search(SENT) and UNCONFIRMED_RE.search(NOT_YET)
    assert not UNCONFIRMED_RE.search("ERROR: Invalid Username/Password") and not UNCONFIRMED_RE.search("Please verify you are human")
    # in HTML "&" in an address is written "&amp;": the address is kept as a browser would follow it
    part = base64.urlsafe_b64encode(b'<p><a href="https://www.acme.test/confirm?nonce=1&amp;email=2&amp;hash=3">Confirm</a></p>').decode()
    assert "https://www.acme.test/confirm?nonce=1&email=2&hash=3 " in mail._body({"mimeType": "text/html", "body": {"data": part}})


# --- an address that gave no answer ---

TIMED_OUT = 'Page.goto: net::ERR_TIMED_OUT at https://tmx.wd3.myworkdayjobs.com/en-US/TMX_Careers/userHome\nCall log:\n  - navigating to "..."'


def test_an_address_that_gives_no_answer_is_a_site_that_is_down_wherever_it_happens(app_env, monkeypatch):
    """The run that was to confirm the account stopped at its first page: the connection timed out. That was reported as
    a failed task and left there; a site that answers with an error page, three lines further on, was tried again."""
    from autoapply import auth, notify, tasks
    from autoapply.ats.base import NeedsHuman, SiteDown, unreachable
    from autoapply.models import Task, Todo

    assert unreachable(Exception(TIMED_OUT)) and unreachable(SiteDown("HTTP 521")) and unreachable(Exception("Page.goto: Timeout 30000ms exceeded."))
    assert not unreachable(Exception("Locator.wait_for: Timeout 20000ms exceeded.")) and not unreachable(NeedsHuman("net::ERR_TIMED_OUT"))

    later, told = [], []
    monkeypatch.setattr(tasks, "enqueue_later", lambda kind, **k: later.append((kind, k["ref"], k["minutes"], k["payload"].get("_down_retries"))))
    monkeypatch.setattr(notify, "send", lambda *a, **k: told.append(a))

    def recon(t):
        raise Exception(TIMED_OUT)

    monkeypatch.setitem(tasks._handlers, "recon", recon)
    with db.session() as s:
        s.add(Task(kind="recon", ref="job:844", status="running", payload={}))
        s.add(Task(kind="recon", ref="job:845", status="running", payload={"_down_retries": 1}))
    with db.session() as s:
        rows = s.query(Task).order_by(Task.id).all()
        s.expunge_all()
    for t in rows:
        tasks.run_one(t)
    with db.session() as s:
        errors = [t.error for t in s.query(Task).order_by(Task.id)]
    assert errors[0].startswith("网站暂时打不开") and "5 分钟后自动重试" in errors[0] and "Call log" not in errors[0] and "30 分钟后自动重试" in errors[1]
    assert later == [("recon", "job:844", 5, 1), ("recon", "job:845", 30, 2)] and told == []        # tried again; nobody is told to do anything

    # at a sign-in it is not "the password failed", not "the page could not be worked", and no card
    class Driver:
        requires_login, ats = True, "workday"

        def is_logged_in(self, page, ref, navigate=True):
            return False

        def login(self, page, ref, email, pw):
            raise Exception(TIMED_OUT)

        def login_url(self, ref):
            return "https://tmx.wd3.myworkdayjobs.com/en-US/TMX_Careers/login"

    from autoapply.ats.workday import WorkdayDriver

    ref = WorkdayDriver().detect(JOB)
    db.set_setting("account.email", "me@example.test")
    auth.upsert_account(ref.tenant_key, ats="workday", host=HOST, email="me@example.test", password="pw-1", status="pending", created_by="agent")
    with pytest.raises(Exception, match="ERR_TIMED_OUT") as e:
        auth.ensure_session(object(), Driver(), ref)
    assert not isinstance(e.value, NeedsHuman)
    a = auth.account(ref.tenant_key)
    with db.session() as s:
        assert a["status"] == "pending" and a["fail_count"] == 0 and s.query(Todo).count() == 0
