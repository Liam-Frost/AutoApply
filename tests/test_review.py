"""What a review of the whole program found: mechanisms that had been patched case by case, and what had gone stale."""

from __future__ import annotations

import pytest

from autoapply import db


def test_the_programs_own_bookkeeping_is_not_shown_to_or_saved_by_the_settings_page(app_env):
    """Which browser a sign-in lives in, which site signs in on which, how far the mailbox was read: the settings page
    got these with the settings and sent them back on Save - a page left open wrote an older copy over the newer record."""
    from fastapi.testclient import TestClient

    from autoapply import config
    from autoapply.api.main import app

    c = TestClient(app)
    shown = c.get("/api/settings").json()["settings"]
    from autoapply import sites

    assert not ((config.STATE | config.RETIRED) & set(shown)) and "browser.rules" in shown
    sites.set_fact("idp:google", "session_browser", "nodriver")
    sites.link("generic:www.google.com", "idp:google")
    db.set_setting("mail.gmail_history", "77")
    # a page loaded before this change sends everything back, the bookkeeping and two settings that no longer exist
    old_page = {**shown, "browser.session_made_in": {}, "accounts.alias": {}, "mail.gmail_history": "1", "schedule.execute_minutes": 5, "executor.concurrency": 1}
    assert c.put("/api/settings", json={"settings": old_page}).status_code == 200
    assert sites.fact("idp:google", "session_browser") == "nodriver" and sites.account("generic:www.google.com") == "idp:google"
    assert db.get_setting("mail.gmail_history") == "77"
    assert c.put("/api/settings", json={"settings": {"no.such.setting": 1}}).status_code == 400


def test_there_is_one_list_of_the_states_in_which_an_application_has_gone_out():
    from autoapply import drafts, lifecycle, mail, models
    from autoapply.agent import work

    assert drafts.SENT is models.SENT and lifecycle.SENT is models.SENT and work.SENT is models.SENT
    assert list(mail.RANK) == list(models.SENT) and mail.RANK["submitted"] < mail.RANK["interview"] < mail.RANK["rejected"]


def test_two_names_are_one_employer_when_one_is_inside_the_other_not_when_they_share_a_word():
    from autoapply.mail import _norm, _same_company

    same = lambda a, b: _same_company(_norm(a), _norm(b))  # noqa: E731
    assert same("Google", "Google LLC") and same("Amazon Web Services", "Amazon") and same("TD", "TD Bank Group") and same("4AG Robotics Inc.", "4AG Robotics")
    assert not same("4AG Robotics", "Global Robotics") and not same("Acme Technologies", "Zeta Technologies") and not same("", "Acme")


def test_mail_from_an_employer_applied_to_is_read_whatever_words_it_uses(app_env):
    from autoapply import mailbox
    from autoapply.models import Application, Job

    with db.session() as s:
        job = Job(source="manual", source_id="m1", company="Kyoto Robotics", title="Intern", apply_url="https://x.example/1", channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        s.add(Application(job_id=job.id, status="submitted"))
    msg = lambda sender, subject, body="": type("M", (), {"sender": sender, "subject": subject, "body": body})()  # noqa: E731
    assert mailbox._relevant(msg("news@shop.example", "Your application was received"))                 # the words such mail uses
    assert mailbox._relevant(msg("Kyoto Robotics <saiyo@kyoto-robotics.example>", "次のステップについて"))        # no such word, but from an employer applied to
    assert not mailbox._relevant(msg("news@shop.example", "Ten recipes for autumn"))


def test_a_handler_that_lets_a_page_be_slow_does_not_let_a_mistake_in_the_program_pass():
    from autoapply.errors import tolerated

    tolerated(TimeoutError("the page is busy"))
    tolerated(RuntimeError("Element is covered by another element"))
    with pytest.raises(AttributeError):
        tolerated(AttributeError('"Tab" has no attribute "closed"'))


def test_a_rule_for_a_site_saved_with_operations_is_stored_as_what_it_means_now(app_env):
    from autoapply import browser_policy

    db.set_setting("browser.rules", [{"tenant": "pdportal:ubc", "backend": "nodriver", "operations": ["login"]},
                                     {"domain": "accounts.google.com", "backend": "nodriver", "operations": ["login"]}])
    browser_policy.store_rules_whole()
    assert db.get_setting("browser.rules") == [{"tenant": "pdportal:ubc", "backend": "nodriver", "operations": []},
                                               {"domain": "accounts.google.com", "backend": "nodriver", "operations": ["login"]}]


# --- "has it gone out?" and "was it applied for before?": the model reads the page where the known phrases find nothing ---

JA_DONE = "ご応募ありがとうございました。応募を受け付けました。"
JA_DUP = "この求人にはすでに応募済みです。"


def _model(monkeypatch, answer):
    from autoapply import executor, llm

    calls = []

    def json(prompt, schema, **kw):
        calls.append(prompt)
        if isinstance(answer, Exception):
            raise answer
        return answer(prompt) if callable(answer) else answer

    monkeypatch.setattr(llm, "json", json)
    executor._judged.clear()
    return calls


class _Window:
    """A window as the waiting loop sees it: what it shows, tick by tick, and whether it is still open."""

    def __init__(self, shows, fields=0):
        self.shows, self.fields, self.url, self.ticks = list(shows), fields, "https://x.example/apply", 0

    def is_closed(self):
        return not self.shows

    def evaluate(self, js, *a):
        if "querySelectorAll('input" in js:
            return self.fields
        return {"title": "", "text": self.shows[0] if self.shows else ""}

    def wait_for_timeout(self, ms):
        self.ticks += 1
        if len(self.shows) > 1 or self.close_after is not None and self.ticks >= self.close_after:
            self.shows.pop(0)

    close_after = None


# --- what the site filled in by itself (an entry it made from the résumé) ---


# --- whose password a sign-in page takes ---


# --- found in review of the pull requests ---


def test_a_providers_card_is_finished_the_providers_way(app_env, monkeypatch):
    """The card for an expired Google sign-in is opened by the same button as a site's card. That call names no check
    for "signed in", and a provider has no driver to ask: the window could be signed in and nothing noticed it."""
    from contextlib import contextmanager

    from autoapply import auth, browser, browser_policy

    spec = browser.identities()["google"]
    seen = {}

    class Ctx:
        def __init__(self):
            self.pages = [type("P", (), {"url": "https://myaccount.google.com/"})()]

        def cookies(self):
            return []

    class Page:
        context = Ctx()

        def goto(self, url, **k):
            seen["opened"] = url

    @contextmanager
    def open_page(tenant, **kw):
        yield Page()

    assert spec["done"]("https://myaccount.google.com/")
    monkeypatch.setattr(browser_policy, "select", lambda *a, **k: type("S", (), {"backend": "nodriver"})())
    monkeypatch.setattr(browser, "open_page", open_page)
    monkeypatch.setattr(browser, "save_state", lambda key, ctx: seen.setdefault("saved", key))
    got = auth.takeover("idp:google", "", timeout_s=3)          # as the card's button calls it: no check given
    assert got["ok"] is True and got["credentials_saved"] is False and seen == {"opened": spec["url"], "saved": "idp:google"}


def test_a_forgotten_sign_in_takes_its_browser_with_it_and_a_carried_one_replaces_what_is_there(app_env):
    from autoapply import browser, sites, transfer

    state = {"cookies": [{"name": "sid", "value": "new", "domain": ".acme.wd1.myworkdayjobs.com", "path": "/"}], "origins": []}
    browser.write_state("workday:acme.wd1", state, made_in="nodriver")
    profile = browser._native_profile("workday:acme.wd1")
    profile.mkdir(parents=True)
    (profile / "Cookies").write_text("the old session", encoding="utf-8")
    assert sites.fact("workday:acme.wd1", "session_browser") == "nodriver"
    blob = transfer.export("workday:acme.wd1", "long enough passphrase", host="acme.wd1.myworkdayjobs.com")
    # carried in: the profile that would go on using the old session is gone, the new sign-in is what is there
    assert transfer.put(blob, "long enough passphrase")["tenant"] == "workday:acme.wd1"
    assert not profile.exists() and browser.load_state("workday:acme.wd1") == state and sites.fact("workday:acme.wd1", "session_browser") == ""
    # forgotten: the browser it was made in is forgotten with it
    browser.write_state("workday:acme.wd1", state, made_in="nodriver")
    browser.clear_state("workday:acme.wd1")
    assert browser.load_state("workday:acme.wd1") is None and sites.fact("workday:acme.wd1", "session_browser") == ""


def test_mail_is_dealt_with_in_the_order_it_was_written(app_env, monkeypatch):
    """A mailbox hands over the newest first. Read that way, "cancelled" then "new invitation" took the interview away."""
    from datetime import datetime, timedelta, timezone

    from autoapply import mail, mailbox, notify
    from autoapply.models import Application, Job

    with db.session() as s:
        job = Job(source="manual", source_id="r1", company="Acme", title="Software Intern", apply_url="https://x.example/1", channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        a = Application(job_id=job.id, status="interview", submitted_at=datetime(2026, 11, 1))
        s.add(a)
        s.flush()
        app_id = a.id
    now = datetime.now(timezone.utc)
    box = [mailbox.Message(id="newer", sender="Acme <hr@acme.test>", subject="Interview: new time", body="Your interview is now on Friday.", date=now),
           mailbox.Message(id="older", sender="Acme <hr@acme.test>", subject="Interview cancelled", body="Thursday's interview is cancelled.", date=(now - timedelta(hours=2)).replace(tzinfo=None))]
    monkeypatch.setattr(mailbox, "fetch", lambda *a, **k: box)        # newest first, as mailboxes do
    read = []

    def triage(subj, frm, body):
        read.append(subj)
        return {"category": "interview", "company": "Acme", "job_title": "Software Intern", "summary": subj, "event": "cancelled" if "cancelled" in subj else "new"}

    monkeypatch.setattr(mail, "triage", triage)
    monkeypatch.setattr(notify, "send", lambda *a, **k: None)
    mail.track()
    assert read == ["Interview cancelled", "Interview: new time"]
    with db.session() as s:
        assert s.get(Application, app_id).status == "interview"
