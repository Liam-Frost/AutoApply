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
    # the same on a system that has a driver of its own: its employers ask in the same words and each means itself.
    # ("Have you previously worked for us?" = Yes, confirmed on one Workday employer's form, went to the next one confirmed.)
    w = Question(id="employed", label="Have you previously worked for us?", type="select", options=["Yes", "No"], required=True)
    ans.cache_put("workday", w, "Yes", "worked there in 2025", confirmed=True, tenant="acme.wd1")
    own, other = ans._cache_get("workday", w, "acme.wd1"), ans._cache_get("workday", w, "zeta.wd5")
    assert (own.ats, own.answer, own.confirmed_by_user) == ("workday:acme.wd1", "Yes", 1)
    assert (other.ats, other.answer, other.confirmed_by_user, other.origin) == ("workday", "Yes", 0, "acme.wd1")      # offered, and said where from

    def on_workday(tenant):
        schema = FormSchema(ats="workday", tenant=tenant, url="https://x", pages=["p"], questions=[w])
        r = ans.resolve(schema, job)["answers"][0]
        return r["value"], r["confidence"], r["basis"]

    assert on_workday("acme.wd1")[:2] == ("Yes", "high")
    assert on_workday("zeta.wd5")[:2] == ("Yes", "medium") and "another employer's form (acme.wd1)" in on_workday("zeta.wd5")[2]
    # what was kept for the whole system before employers were told apart is still offered, and confirmed for nobody
    from autoapply.models import AnswerCache

    key, oh = sponsor.key()
    with db.session() as s:
        s.add(AnswerCache(ats="workday", question_key=key, options_hash=oh, answer="No", basis="approved", confirmed_by_user=1, sensitive=1))
    schema = FormSchema(ats="workday", tenant="zeta.wd5", url="https://x", pages=["p"], questions=[sponsor])
    r = ans.resolve(schema, job)["answers"][0]
    assert (r["value"], r["confidence"], r["sensitive_confirmed"]) == ("No", "medium", False)
    # a form whose employer is not known keeps the system as its scope
    assert ans._scope("workday") == "workday" and ans._scope("workday", "acme.wd1") == "workday:acme.wd1" == __import__("autoapply.sites", fromlist=["x"]).of_form(
        FormSchema(ats="workday", tenant="acme.wd1", source="agent"))
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


# --- what the site filled in by itself (an entry it made from the résumé) ---


def test_the_take_over_is_told_what_to_do_with_an_entry_the_site_made_and_can_report_it(app_env):
    from autoapply import repair

    assert "An entry the form made by itself" in repair.SYSTEM and "`removed`" in repair.SYSTEM and "@decision:" in repair.SYSTEM


def test_a_decision_about_an_entry_joins_the_draft_as_one_question_and_is_not_filled_as_a_control(app_env):
    """Google's form made a second "work experience" out of a personal project on the résumé and wanted its Job title
    and City. The applicant got two bare questions - "Job title", "City" - with no way to say: that entry should go."""
    from autoapply import db, executor
    from autoapply.ats.base import DriverError, FormSchema, Question
    from autoapply.ats.generic_driver import GenericDriver, set_value
    from autoapply.models import Application, Draft, Job

    schema = FormSchema(ats="generic", tenant="careers.example.test", url="https://x", source="agent", pages=["Profile"],
                        questions=[Question(id="#first", label="First name", type="text", page=0)])
    with db.session() as s:
        job = Job(source="manual", source_id="e1", company="Acme", title="Intern", apply_url="https://x", channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        a = Application(job_id=job.id, status="approved")
        s.add(a)
        s.flush()
        d = Draft(application_id=a.id, schema=schema.to_dict(), review_status="approved", notes=[], answers=[
            {"id": "#first", "label": "First name", "type": "text", "options": [], "required": True, "page": 0, "value": "Alex", "basis": "profile", "confidence": "high",
             "source": "profile", "sensitive": "", "sensitive_confirmed": False}])
        s.add(d)
        s.flush()
        asked = [{"label": "Work experience 2: AutoApply", "why": "The site made it from the résumé; the profile lists AutoApply under projects.", "type": "radio",
                  "options": ["Remove this entry", "Keep it - I will give the missing details"], "page": 0, "selector": "", "provisional": "", "decision": True, "entry": ""},
                 {"label": "Job title", "why": "Required in the entry.", "type": "text", "options": [], "page": 0, "selector": "", "provisional": "", "decision": False, "entry": "Work experience 1: Lenovo"},
                 {"label": "Job title", "why": "Required in the entry.", "type": "text", "options": [], "page": 0, "selector": "", "provisional": "", "decision": False, "entry": "Work experience 3: TCM"}]
        fresh = executor._keep_learned(d, schema, d.answers, {"#first": "Alex"}, set(), [], generic=True, asked=asked, send_back=True,
                                       removed=[{"what": "Work experience 4: Course project", "why": "the profile lists it under projects"}])
        did = d.id
    assert fresh == 3
    with db.session() as s:
        d = s.get(Draft, did)
        rows = {r["id"]: r for r in d.answers}
        decision = rows["@decision:Work experience 2: AutoApply"]
        assert decision["type"] == "radio" and decision["options"][0] == "Remove this entry" and decision["basis"].startswith("网站自己生成了这一条")
        # the same label in two entries is two questions, each saying which entry it is
        assert {rows[k]["entry"] for k in rows if k.startswith("@label:Job title")} == {"Work experience 1: Lenovo", "Work experience 3: TCM"}
        assert any("Course project" in n and "AI 删除了" in n for n in d.notes) and d.review_status == "pending"
        q = next(Question(**x) for x in d.schema["questions"] if x["id"].startswith("@decision:"))
    with db.session() as s:
        twin = next(Question(**x) for x in s.get(Draft, did).schema["questions"] if x["id"].startswith("@label:Job title"))
    with pytest.raises(DriverError, match="belongs to the entry"):
        set_value(object(), twin, "Intern")                    # not filled into whichever "Job title" comes first on the page
    with pytest.raises(DriverError, match="applicant's decision"):
        set_value(object(), q, "Remove this entry")           # handed to the take-over, never looked for as a control
    assert GenericDriver(FormSchema(ats="generic", url="x", questions=[q])).read_back(object(), FormSchema(ats="generic", url="x", questions=[q])) == {}


def test_a_question_the_filling_ran_into_can_be_taken_out_of_the_draft_and_an_answer_of_the_applicants_cannot(app_env):
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app
    from autoapply.models import Application, Draft, Job, Todo

    row = lambda qid, label, value, source: {"id": qid, "label": label, "type": "text", "options": [], "required": True, "page": 0, "value": value,  # noqa: E731
                                              "basis": "", "confidence": "low", "source": source, "sensitive": "", "sensitive_confirmed": False, "entry": "Work experience 2: AutoApply"}
    with db.session() as s:
        job = Job(source="manual", source_id="e2", company="Acme", title="Intern", apply_url="https://x", channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        a = Application(job_id=job.id, status="needs_input")
        s.add(a)
        s.flush()
        answers = [row("#first", "First name", "Alex", "profile"), row("@label:Job title", "Job title", "", "unresolved"), row("@label:City", "City", "", "unresolved")]
        d = Draft(application_id=a.id, review_status="pending", notes=[], answers=answers, unresolved=answers[1:],
                  schema={"ats": "generic", "tenant": "careers.example.test", "url": "https://x", "source": "agent", "pages": ["Profile"],
                          "questions": [{"id": r["id"], "label": r["label"], "type": "text", "page": 0} for r in answers]})
        s.add(d)
        s.flush()
        s.add(Todo(kind="answer", title="Acme", ref=f"draft:{d.id}", payload={"draft_id": d.id}))
        did, app_id = d.id, a.id
    c = TestClient(app)
    assert c.delete(f"/api/drafts/{did}/answers/%23first").status_code == 409                 # an answer of the applicant's stays
    got = c.delete(f"/api/drafts/{did}/answers/@label:Job title").json()
    assert [r["id"] for r in got["answers"]] == ["#first", "@label:City"] and len(got["unresolved"]) == 1
    c.delete(f"/api/drafts/{did}/answers/@label:City")
    with db.session() as s:
        d = s.get(Draft, did)
        assert d.unresolved == [] and [q["id"] for q in d.schema["questions"]] == ["#first"] and len(d.notes) == 2
        assert s.get(Application, app_id).status in ("draft_ready", "recon")                    # nothing left to answer: it goes on
        assert s.query(Todo).filter_by(kind="answer", status="open").count() == 0


# --- whose password a sign-in page takes ---


def test_a_site_that_sends_its_sign_in_to_another_address_gets_its_password_there(app_env):
    """amazon.jobs asks for the e-mail on its own page and sends the window to a host of amazon.com for the password. The
    program took that page for "another site, with an account of its own", found no password for it, and gave up at the
    password box - with the site's password saved all along."""
    from playwright.sync_api import sync_playwright

    from autoapply import auth, generic, secrets, sites
    from autoapply.ats.base import JobRef

    auth.upsert_account("generic:www.acme.jobs", ats="generic", host="www.acme.jobs", email="me@example.test", password="site-pw", status="ok")
    ref = JobRef("generic", "www.acme.jobs", "", "https://www.acme.jobs/en/jobs/1", "www.acme.jobs")
    form = '<main><h1>Sign in</h1><input id="e" type="email"><button id="go">Continue</button><input id="p" type="password"></main>'
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.route("**/*", lambda r: r.fulfill(content_type="text/html", body=form))
        # the sign-in begins on the site's own page ...
        page.goto("https://passport.acme.jobs/login")
        state: dict = {}
        tools = {t.name: t for t in generic.account_tools(page, ref, state)}
        assert tools["account_info"].fn(offered=[])["do"] == "password"
        tools["fill_account_email"].fn(selector="#e")
        # ... and the site sends the window elsewhere for the password
        page.goto("https://signin.idp-acme.com/?login_hint=me")
        assert tools["fill_account_password"].fn(selector="#p").startswith("filled") and page.input_value("#p") == "site-pw"
        tools["account_result"].fn(outcome="logged_in")
        assert sites.fact("generic:www.acme.jobs", "sign_in_hosts") == ["signin.idp-acme.com"]         # known from now on
        assert auth.account("generic:signin.idp-acme.com") is None                                    # no account invented for the other address
        # next time the window lands there directly (the session ran out mid-form): it is this site's sign-in, known
        tools = {t.name: t for t in generic.account_tools(page, ref, {})}
        assert tools["fill_account_password"].fn(selector="#p").startswith("filled")
        # a page the site did NOT lead to gets nothing: a sign-in that begins on another address is that address's own
        page.goto("https://login.other-system.com/")
        page.fill("#p", "")
        tools = {t.name: t for t in generic.account_tools(page, ref, {})}
        with pytest.raises((PermissionError, ValueError)):
            tools["fill_account_password"].fn(selector="#p")
        assert page.input_value("#p") == ""
        b.close()
    assert secrets.get_password("generic:www.acme.jobs") == "site-pw"


def test_a_sign_in_through_an_institution_is_gone_through_again_before_anyone_is_asked(app_env, monkeypatch):
    """The portal's session lasts about an hour; the university's login behind it much longer. An expired portal session
    went straight to "please sign in" - without the one step that needs nobody."""
    from autoapply import auth, browser
    from autoapply.ats.base import JobRef, NeedsHuman
    from autoapply.models import Todo

    monkeypatch.setattr(browser, "save_state", lambda *a, **k: None)
    ref = JobRef("pdportal", "ubc", "150971", "https://pdportal.apsc.ubc.ca/myAccount/co-op/postings.htm#posting=150971", "pdportal.apsc.ubc.ca")

    class Portal:
        requires_login, sso, ats = True, True, "pdportal"

        def __init__(self, holds):
            self.holds, self.signed_in, self.tried = holds, False, 0

        def is_logged_in(self, page, ref, navigate=True):
            return self.signed_in

        def resume(self, page, ref):
            self.tried += 1
            self.signed_in = self.holds
            return self.holds

        def login_url(self, ref):
            return "https://pdportal.apsc.ubc.ca/home.htm"

    page = type("P", (), {"context": None})()
    held = Portal(holds=True)
    assert auth.ensure_session(page, held, ref) == "logged_in" and held.tried == 1
    with db.session() as s:
        assert s.query(Todo).count() == 0                        # nobody was asked
    gone = Portal(holds=False)
    with pytest.raises(NeedsHuman) as e:
        auth.ensure_session(page, gone, ref)
    assert gone.tried == 1 and e.value.waits_for == "account:pdportal:ubc"
    with db.session() as s:
        card = s.query(Todo).one()
        assert card.kind == "takeover" and card.payload["can_register"] is False       # an institution's login is not something to register for


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
