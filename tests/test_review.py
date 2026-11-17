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
