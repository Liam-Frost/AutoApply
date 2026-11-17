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
    assert not (config.STATE & set(shown)) and "browser.rules" in shown and "schedule.execute_minutes" not in shown
    db.set_setting("browser.session_made_in", {"idp:google": "nodriver"})
    db.set_setting("accounts.alias", {"generic:www.google.com": "idp:google"})
    # a page loaded before this change sends everything back, the bookkeeping and two settings that no longer exist
    old_page = {**shown, "browser.session_made_in": {}, "accounts.alias": {}, "mail.gmail_history": "1", "schedule.execute_minutes": 5, "executor.concurrency": 1}
    assert c.put("/api/settings", json={"settings": old_page}).status_code == 200
    assert db.get_setting("browser.session_made_in") == {"idp:google": "nodriver"} and db.get_setting("accounts.alias") == {"generic:www.google.com": "idp:google"}
    assert c.put("/api/settings", json={"settings": {"no.such.setting": 1}}).status_code == 400


def test_there_is_one_list_of_the_states_in_which_an_application_has_gone_out():
    from autoapply import auth, drafts, lifecycle, mail, models

    assert drafts.SENT is models.SENT and lifecycle.SENT is models.SENT and auth.SENT is models.SENT
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


def test_an_answer_given_to_one_employer_is_only_a_suggestion_for_another(app_env):
    """Every site without a driver of its own shared one cache: "No" to "Have you worked for us before?", confirmed for
    one employer, went to the next as the applicant's confirmed answer."""
    from autoapply import answers as ans
    from autoapply.ats.base import FormSchema, Question
    from autoapply.models import Job

    q = Question(id="#w", label="Have you worked for us before?", type="radio", options=["Yes", "No"], required=True)
    sponsor = Question(id="#s", label="Will you require sponsorship?", type="radio", options=["Yes", "No"], required=True)
    for x in (q, sponsor):
        ans.cache_put("generic", x, "No", "approved", confirmed=True, tenant="jobs.acme.example")
    job = Job(source="manual", source_id="a1", company="Zeta", title="Intern", apply_url="https://careers.zeta.example/1", jd_text="x" * 300)

    def answered(tenant):
        schema = FormSchema(ats="generic", tenant=tenant, url="https://x", pages=["p"], questions=[q, sponsor])
        return {r["id"]: (r["value"], r["confidence"], r["sensitive_confirmed"]) for r in ans.resolve(schema, job)["answers"]}

    assert answered("jobs.acme.example") == {"#w": ("No", "high", False), "#s": ("No", "high", True)}            # the employer it was confirmed for
    assert answered("careers.zeta.example") == {"#w": ("No", "medium", False), "#s": ("No", "medium", False)}    # elsewhere: offered, not confirmed
    # a system with a driver of its own asks everyone the same: one scope, as before
    ans.cache_put("greenhouse", q, "No", "approved", confirmed=True, tenant="acme")
    assert ans._cache_get("greenhouse", q, "zeta").ats == "greenhouse"
    ans.correct("generic", {"id": "#w", "label": q.label, "type": "radio", "options": q.options, "value": "Yes", "basis": "edited by user"}, "jobs.acme.example")
    assert answered("jobs.acme.example")["#w"][0] == "Yes" and answered("careers.zeta.example")["#w"][0] == "Yes"


def test_what_is_the_portals_own_lives_in_the_portals_driver():
    from types import SimpleNamespace

    from autoapply.ats.base import Question
    from autoapply.ats.pdportal import PDPortalDriver

    job = SimpleNamespace(company="Acme Robotics Inc.", source_id="150971")
    assert PDPortalDriver.read_by_agent is False
    assert PDPortalDriver.fixed_answer(Question(id="package", label="Package name", type="text"), job) == ("Acme_Robotics_Inc_150971", "naming rule <Company>_<JobID>")
    assert PDPortalDriver.fixed_answer(Question(id="resume", label="Resume", type="select", options=["only.pdf"], required=True), job)[0] == "only.pdf"
    assert PDPortalDriver.fixed_answer(Question(id="x", label="Anything", type="text"), job) is None


def test_a_handler_that_lets_a_page_be_slow_does_not_let_a_mistake_in_the_program_pass():
    from autoapply.ats.base import tolerated

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


def test_a_page_that_says_it_in_words_the_program_does_not_know_is_read_by_the_model_and_has_to_be_quoted(app_env, monkeypatch):
    from autoapply import executor, llm

    page = {"url": "https://x.example/done", "title": "採用情報", "text": f"応募完了\n{JA_DONE}\nマイページへ"}
    calls = _model(monkeypatch, {"state": "submitted", "sentence": JA_DONE})
    assert executor._judge(page) == {"state": "submitted", "sentence": JA_DONE}
    assert executor._judge(page) == {"state": "submitted", "sentence": JA_DONE} and len(calls) == 1          # the same page is not asked about twice
    # a sentence that is not on the page is not believed, whatever state comes with it
    _model(monkeypatch, {"state": "submitted", "sentence": "Thank you, your application has been received."})
    assert executor._judge(page) is None
    _model(monkeypatch, {"state": "neither", "sentence": ""})
    assert executor._judge({**page, "text": "Sign in to continue your application"}) is None
    _model(monkeypatch, llm.LLMUnavailable("no model"))
    assert executor._judge(page) is None                    # no model: as before, the page stays unread
    assert executor._judge({"url": "", "title": "", "text": ""}) is None


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


def test_the_window_waits_for_a_confirmation_in_any_wording_and_does_not_ask_while_the_form_is_there(app_env, monkeypatch):
    from types import SimpleNamespace

    from autoapply import executor
    from autoapply.models import Application, Job

    with db.session() as s:
        job = Job(source="manual", source_id="j1", company="Kyoto Robotics", title="Intern", apply_url="https://x.example/1", channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        a = Application(job_id=job.id, status="approved")
        s.add(a)
        s.flush()
        app_id = a.id
    driver = SimpleNamespace(confirmation=lambda page: None)
    calls = _model(monkeypatch, lambda prompt: {"state": "submitted", "sentence": JA_DONE} if JA_DONE in prompt else {"state": "neither", "sentence": ""})
    # the form stays on the page for a while (nothing is asked), then the confirmation appears
    window = _Window(["応募フォーム"] * 5 + [f"応募完了\n{JA_DONE}"] * 8)
    window.fields = 6
    real_wait = window.wait_for_timeout
    window.wait_for_timeout = lambda ms: (real_wait(ms), setattr(window, "fields", 0 if JA_DONE in (window.shows[0] if window.shows else "") else 6))[0]
    out = executor._manual_submit_wait(driver, window, "Kyoto Robotics · Intern", app_id)
    assert out["status"] == "submitted" and out["evidence"] == {"url": window.url, "text": JA_DONE, "read_by": "model"} and len(calls) == 1
    # the applicant closes the window on that page before the loop looked: what it last showed is read
    calls = _model(monkeypatch, {"state": "submitted", "sentence": JA_DONE})
    closed = _Window([f"応募完了\n{JA_DONE}"], fields=3)
    closed.close_after = 1
    assert executor._manual_submit_wait(driver, closed, "Kyoto Robotics · Intern", app_id)["evidence"]["read_by"] == "model"
    # ... and a window closed on the form is still "not known", with nothing made up
    _model(monkeypatch, {"state": "neither", "sentence": ""})
    left = _Window(["応募フォーム"], fields=6)
    left.close_after = 1
    assert executor._manual_submit_wait(driver, left, "Kyoto Robotics · Intern", app_id)["status"] == "ready_to_submit"


def test_a_page_without_the_form_that_says_already_applied_in_other_words_is_not_taken_for_an_expired_sign_in(app_env, monkeypatch):
    from autoapply import executor

    class Page:
        url = "https://x.example/apply"

        def evaluate(self, js, *a):
            return {"title": "", "text": JA_DUP}

    _model(monkeypatch, {"state": "already_applied", "sentence": JA_DUP})
    assert executor._already_applied(Page()) is None                       # the phrases alone: nothing
    assert executor._already_applied(Page(), ask=True) == {"url": "https://x.example/apply", "text": JA_DUP, "already_applied": "yes", "read_by": "model"}


def test_a_field_let_through_on_the_agents_word_is_shown_to_the_applicant_and_not_sent_unseen(app_env, tmp_path, monkeypatch):
    """A list that shows "+1" for "+1 Canada" and does not mark its chosen entry cannot be checked by the program. The
    agent's word was taken silently. It is still taken - the form goes on - but the field is named as one to look at."""
    from types import SimpleNamespace

    from autoapply import executor
    from autoapply.ats.base import FormSchema, Question

    schema = FormSchema(ats="generic", url="https://x", pages=["p"], questions=[Question(id="code", label="Phone code", type="select", options=["+1 United States", "+1 Canada"])])
    answers = [{"id": "code", "label": "Phone code", "type": "select", "value": "+1 Canada", "options": schema.questions[0].options}]
    driver = SimpleNamespace(read_back=lambda page, schema, i=None: {"code": "+1"})
    monkeypatch.setattr(executor, "_really_different", lambda page, schema, bad: bad)
    monkeypatch.setattr(executor, "_repair", lambda *a, **k: {"fixed": ["code"], "unfixed": [], "cause": "chose the entry"})
    monkeypatch.setattr(executor.browser, "snapshot", lambda *a, **k: {})
    steps, seen = [], []
    executor._verify(driver, object(), schema, answers, {"code": "+1 Canada"}, 0, {"code": 0}, tmp_path, lambda op, **kw: steps.append((op, kw)), "Acme", 1, on_trust=seen.append)
    assert [b["label"] for b in seen] == ["Phone code"] and ("taken_on_trust", {"page": 0, "fields": ["Phone code"]}) in steps
    # without the agent having worked on that field, "+1" is a difference as before
    monkeypatch.setattr(executor, "_repair", lambda *a, **k: {"fixed": [], "unfixed": ["code"], "cause": ""})
    seen.clear()
    with pytest.raises(executor.VerifyFailed):
        executor._verify(driver, object(), schema, answers, {"code": "+1 Canada"}, 0, {"code": 0}, tmp_path, lambda op, **kw: None, "Acme", 1, on_trust=seen.append)
    assert seen == []
