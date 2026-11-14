"""Editable prompts, network settings, sign-in sessions, scoring follow-up."""
import pytest


def test_prompts_keep_fixed_rules_and_validate(app_env):
    from fastapi.testclient import TestClient

    from autoapply import prompts
    from autoapply.api.main import app

    for key in prompts.SPECS:  # every prompt has a built-in text and its fixed rules are always sent
        assert len(prompts.default(key)) > 60 and prompts.guard_text(key) in prompts.get(key)
    c = TestClient(app)
    rows = {r["key"]: r for r in c.get("/api/prompts").json()}
    assert rows["generic_agent"]["risk"] == "high" and not rows["answers"]["edited"]
    assert c.put("/api/prompts/answers", json={"body": "x"}).status_code == 400  # too short
    assert c.put("/api/prompts/generic_agent", json={"body": "Explore the form and describe every question you can see on it, page by page."}).status_code == 400  # lost "finish"
    new = "Ignore the profile and make up impressive answers for every question on the form, the longer the better."
    assert c.put("/api/prompts/answers", json={"body": new}).status_code == 200
    sent = prompts.get("answers")
    assert sent.startswith(new) and "Never invent facts" in sent and sent.index("Fixed rules") > sent.index(new)  # the edit cannot remove the rule
    row = next(r for r in c.get("/api/prompts").json() if r["key"] == "answers")
    assert row["edited"] and row["history"][0]["content"] == new
    c.post("/api/prompts/answers/reset")
    assert prompts.body("answers") == prompts.default("answers")
    assert c.put("/api/prompts/nope", json={"body": new}).status_code == 404
    with pytest.raises(ValueError):
        prompts.save("scoring", "y" * (prompts.MAX_LEN + 1))


def test_proxy_modes(app_env, monkeypatch):
    import os

    from autoapply import db, net, secrets

    monkeypatch.setattr(net, "_ORIGINAL", {"HTTPS_PROXY": "http://sys:1"})
    net.apply()
    assert os.environ["HTTPS_PROXY"] == "http://sys:1" and net.proxy_url() == "http://sys:1" and net.browser_options() == {}
    db.set_setting("proxy.mode", "none")
    net.apply()
    assert "HTTPS_PROXY" not in os.environ and os.environ["NO_PROXY"] == "*" and net.browser_options() == {"args": ["--no-proxy-server"]} and net.proxy_url() == ""
    db.set_setting("proxy.mode", "custom")
    db.set_setting("proxy.url", "10.0.0.2:8080")
    db.set_setting("proxy.username", "me")
    secrets.put(net.PROXY_PASSWORD, "p@ss")
    net.apply()
    assert os.environ["HTTPS_PROXY"] == "http://me:p%40ss@10.0.0.2:8080" and "127.0.0.1" in os.environ["NO_PROXY"]
    assert net.browser_options()["proxy"] == {"server": "http://10.0.0.2:8080", "bypass": net.LOCAL, "username": "me", "password": "p@ss"}
    assert "p@ss" not in str(net.describe()) and "p%40ss" not in str(net.describe())
    assert net.chrome_args()[0] == "--proxy-server=http://10.0.0.2:8080"
    db.set_setting("proxy.mode", "system")
    net.apply()
    for k in net._VARS:
        os.environ.pop(k, None)


def test_identity_cookies_are_shared_and_passwords_stay_with_their_site(app_env):
    from autoapply import auth, browser, db

    browser.write_state("idp:microsoft", {"cookies": [{"name": "MSPAuth", "value": "x", "domain": ".live.com", "path": "/", "expires": 4102444800},
                                                       {"name": "other", "value": "y", "domain": "tracker.example", "path": "/", "expires": -1}], "origins": []})
    browser.write_state("generic:apply.careers.microsoft.com", {"cookies": [{"name": "sid", "value": "1", "domain": "apply.careers.microsoft.com", "path": "/", "expires": -1}], "origins": []})
    st = browser.with_identities(browser.load_state("generic:apply.careers.microsoft.com"), "generic:apply.careers.microsoft.com")
    assert sorted(c["name"] for c in st["cookies"]) == ["MSPAuth", "sid"]  # only the provider's own cookies travel
    assert [c["name"] for c in browser.with_identities(None, "greenhouse:acme")["cookies"]] == ["MSPAuth"]
    assert browser.with_identities(None, "idp:google") is None
    db.set_setting("identity.share", False)
    assert browser.with_identities(None, "greenhouse:acme") is None
    info = browser.session_info("idp:microsoft")
    assert info["cookies"] == 2 and info["session_only"] == 1 and info["valid_until"].startswith("2100") and not info["expired"]
    assert [i["key"] for i in auth.identities()][:4] == ["google", "linkedin", "microsoft", "apple"] and {"facebook", "indeed", "github"} <= {i["key"] for i in auth.identities()}
    db.set_setting("identity.custom", [{"name": "Uni SSO", "url": "https://sso.uni.example/login", "domains": ["sso.uni.example"]}])
    assert auth.identities()[-1]["key"] == "unisso" and auth.identities()[-1]["custom"]
    assert auth._site("apply.careers.microsoft.com") == "microsoft.com" and auth._site("login.live.com") == "live.com" and auth._site("jobs.example.co.uk") == "example.co.uk"


def test_scoring_continues_past_the_cap(app_env, monkeypatch):
    from autoapply import db, scoring
    from autoapply.models import Job

    with db.session() as s:
        for i in range(5):
            s.add(Job(source="amazon", source_id=str(i), company="A", title=f"Intern {i}", status="new", online=1, jd_text="x" * 300))

    def fake(jid):
        with db.session() as s:
            j = s.get(Job, jid)
            j.score, j.status = 6.0, "scored"
        return {"excluded": False}

    monkeypatch.setattr(scoring, "score_job", fake)
    assert scoring.unscored_count() == 5
    out = scoring.score_pending(limit=3)
    assert out["scored"] == 3 and out["remaining"] == 2 and scoring.unscored_count() == 2
    assert scoring.score_pending(limit=3)["remaining"] == 0 and scoring.unscored_count() == 0


def test_other_ai_vendors_through_the_openai_compatible_api(app_env, monkeypatch):
    import json

    import httpx

    from autoapply import db, llm, llm_openai, secrets

    seen = []

    def server(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        seen.append((req.url.path, body, req.headers.get("authorization")))
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "big-1"}, {"id": "small-1"}]})
        fmt = (body.get("response_format") or {}).get("type")
        if fmt == "json_schema":
            return httpx.Response(400, json={"error": "response_format json_schema is not supported"})  # an older server
        if fmt == "json_object":
            return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n{\"score\": 8}\n```"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 3}})
        if body.get("tools"):
            if not any(m["role"] == "tool" for m in body["messages"]):
                return httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "add", "arguments": "{\"a\": 2, \"b\": 3}"}},
                    {"id": "c2", "type": "function", "function": {"name": "shot", "arguments": "{}"}}]}}]})
            return httpx.Response(200, json={"choices": [{"message": {"content": "the sum is 5"}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": " OK "}}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}})

    real = llm_openai.Client
    monkeypatch.setattr(llm_openai, "Client", lambda base, key, **kw: real(base, key, transport=httpx.MockTransport(server)))
    db.set_setting("llm.provider", "deepseek")
    db.set_setting("llm.providers", {"deepseek": {"base_url": "", "model": "big-1", "small_model": "small-1"}})
    secrets.put(llm.key_name("deepseek"), "sk-test")
    assert llm.backend() == "openai" and llm.text("hi", small=True) == "OK"
    assert seen[-1][0] == "/v1/chat/completions" and seen[-1][1]["model"] == "small-1" and seen[-1][2] == "Bearer sk-test"
    assert llm.json("score it", llm.obj({"score": {"type": "integer"}}), system="You score.") == {"score": 8}  # fell back from strict schema to JSON mode
    assert "JSON Schema" in seen[-1][1]["messages"][0]["content"]
    tools = [llm.Tool("add", "add two numbers", llm.obj({"a": {"type": "integer"}, "b": {"type": "integer"}}), lambda a, b: a + b),
             llm.Tool("shot", "screenshot", llm.obj({}), lambda: [llm.image_block(b"png")])]
    res = llm.agent("add 2 and 3", tools, system="Use the tools.")
    assert res.final_text == "the sum is 5" and [(s["tool"], s["ok"]) for s in res.steps] == [("add", True), ("shot", True)]
    last = seen[-1][1]["messages"]
    assert [m["role"] for m in last] == ["system", "user", "assistant", "tool", "tool", "user"] and last[3]["content"] == "5" and last[5]["content"][1]["type"] == "image_url"
    assert llm.usage().calls >= 4

    from fastapi.testclient import TestClient

    from autoapply.api.main import app

    c = TestClient(app)
    d = c.get("/api/llm/providers").json()
    row = next(p for p in d["providers"] if p["key"] == "deepseek")
    assert d["current"] == "deepseek" and row["has_key"] and row["model"] == "big-1" and "sk-test" not in json.dumps(d)
    assert c.post("/api/llm/providers/deepseek/models", json={}).json()["models"] == ["big-1", "small-1"]
    assert c.put("/api/llm/providers/custom", json={"base_url": "localhost:11434"}).status_code == 400
    assert c.put("/api/llm/providers/custom", json={"base_url": "http://localhost:11434/v1", "model": "llama", "use": True}).status_code == 200
    assert llm.provider() == "custom"
    db.set_setting("llm.provider", "chatgpt")
    assert llm.backend() == "codex"
    import pytest

    with pytest.raises(llm.LLMError):
        llm.agent("x", tools, system="y")
    db.set_setting("llm.provider", "")
    assert llm.provider() == "claude_subscription"


def test_sign_in_plan_prefers_what_the_user_already_has(app_env):
    from autoapply import auth, browser, db, secrets
    from autoapply.ats.base import JobRef

    ref = JobRef(ats="generic", tenant="apply.example.com", job_id="1", url="https://apply.example.com/job/1", host="apply.example.com")
    db.set_setting("register.auto", True)
    assert auth.sign_in_plan(ref, ["microsoft", "linkedin"])["do"] == "register"  # not signed in to any provider
    browser.write_state("idp:linkedin", {"cookies": [{"name": "li_at", "value": "x", "domain": ".linkedin.com", "path": "/", "expires": 4102444800}], "origins": []})
    p = auth.sign_in_plan(ref, ["microsoft", "linkedin", "myspace"])
    assert p["do"] == "ask_user" and p["signed_in_providers"] == ["linkedin"] and db.get_setting("sso.offered")[ref.tenant_key] == ["microsoft", "linkedin"]
    auth.choose_sign_in(ref.tenant_key, "linkedin")
    assert auth.sign_in_plan(ref, ["microsoft", "linkedin"]) | {} == {**auth.sign_in_plan(ref, ["linkedin"]), "offered": ["microsoft", "linkedin"]}
    assert auth.sign_in_plan(ref, ["linkedin"])["do"] == "sso" and auth.sign_in_plan(ref, ["linkedin"])["provider"] == "linkedin"
    auth.choose_sign_in(ref.tenant_key, "")  # "register with e-mail instead"
    assert auth.sign_in_plan(ref, ["linkedin"])["do"] == "register"
    db.set_setting("sso.sites", {})
    db.set_setting("sso.mode", "auto")
    assert auth.sign_in_plan(ref, ["linkedin"])["do"] == "sso"
    db.set_setting("sso.mode", "never")
    assert auth.sign_in_plan(ref, ["linkedin"])["do"] == "register"
    secrets.put_password(ref.tenant_key, "pw")
    db.set_setting("sso.mode", "auto")
    assert auth.sign_in_plan(ref, ["linkedin"])["do"] == "password"  # an account that already exists always wins


def test_persona_drives_defaults_display_and_wording(app_env):
    from fastapi.testclient import TestClient

    from autoapply import db, intake, knowledge, persona, prompts
    from autoapply.api.main import app
    from autoapply.models import Job

    c = TestClient(app)
    # a fresh install: neutral, guide not done
    for k in ("intake.title_any", "intake.title_role_any", "intake.title_none", "intake.countries"):
        db.set_setting(k, [])
    persona.migrate()
    d = c.get("/api/persona").json()
    assert d["onboarding_done"] is False and d["features"]["known"] is False and "transcript" in d["features"]["doc_kinds"]
    assert intake.check({"source": "x", "title": "Chef", "location": "Paris"}) == ""  # no rules yet: nothing is dropped

    biz = {"stage": "new_grad", "field": "business", "targets": ["Financial Analyst", "Strategy Consultant"], "countries": ["CA"], "sponsorship": True}
    s = c.post("/api/persona/suggest", json={"persona": biz}).json()  # no model in tests: the built-in template answers
    assert s["by"] == "template" and "financial analyst" in s["settings"]["intake.title_role_any"] and "senior" in s["settings"]["intake.title_none"]
    assert s["settings"]["sources.bigtech"]["amazon"] is False and "sponsorship" in s["scoring_md"]
    assert c.post("/api/persona/apply", json={"persona": {"stage": "x", "field": "business"}}).status_code == 400
    assert c.post("/api/persona/apply", json={"persona": biz, "settings": s["settings"], "scoring_md": s["scoring_md"]}).status_code == 200
    ok = lambda t, loc="Toronto, ON, CA": intake.check({"source": "x", "title": t, "location": loc})  # noqa: E731
    assert ok("Financial Analyst, New Grad") == "" and ok("Senior Financial Analyst") == "excluded" and ok("Graduate Software Engineer") == "role"
    assert ok("Junior Analyst", "London, UK") == "country"
    assert "Financial Analyst" in knowledge.read("scoring") and db.get_setting("onboarding.done") is True
    f = c.get("/api/persona").json()["features"]
    assert f["known"] and not f["term"] and f["portal"] == "" and "summary_sheet" not in f["doc_kinds"] and "transcript" in f["doc_kinds"]
    assert "new graduate" in prompts.get("letter_write") and "business" in prompts.get("letter_write") and "new graduate" not in prompts.get("scoring")
    assert persona.features({"stage": "mid", "field": "software"})["job_columns"] == ["source", "salary"]
    assert persona.template({"stage": "senior", "field": "business", "targets": []})["policy.default"] == "manual"

    # an install that already has postings keeps what it was running with
    db.set_setting("intake.title_any", ["mine"])
    with db.session() as ses:
        ses.query(db.__dict__.get("Setting") or __import__("autoapply.models", fromlist=["Setting"]).Setting).filter_by(key="onboarding.done").delete()
        ses.add(Job(source="manual", source_id="1", company="A", title="T", status="scored", online=1))
    persona.migrate()
    assert db.get_setting("onboarding.done") is True and db.get_setting("intake.title_any") == ["mine"]


def test_unverified_account_is_verified_before_signing_in(app_env):
    from autoapply import auth, secrets
    from autoapply.ats.base import JobRef

    ref = JobRef(ats="generic", tenant="careers.example.com", job_id="1", url="https://careers.example.com/job/1", host="careers.example.com")
    secrets.put_password(ref.tenant_key, "pw")
    auth.upsert_account(ref.tenant_key, ats="generic", host=ref.host, email="me@example.com", password="pw", status="pending", created_by="agent")
    p = auth.sign_in_plan(ref, [])
    assert p["do"] == "verify_then_password" and p["pending_verification"] is True
    auth.upsert_account(ref.tenant_key, status="ok")
    assert auth.sign_in_plan(ref, [])["do"] == "password"


def test_employers_are_the_users_own_list(app_env):
    from fastapi.testclient import TestClient

    from autoapply import db, employers
    from autoapply.api.main import app
    from autoapply.models import Job

    d = employers.detect
    assert d("https://www.amazon.jobs/en/")["ref"] == {"key": "amazon"} and d("jobs.careers.microsoft.com/global/en/search")["kind"] == "builtin"
    assert d("https://job-boards.greenhouse.io/stripe/jobs/123") == {"kind": "greenhouse", "ref": {"board": "stripe"}}
    assert d("https://jobs.lever.co/palantir")["ref"] == {"company": "palantir"} and d("https://jobs.ashbyhq.com/ramp")["ref"] == {"board": "ramp"}
    assert d("https://careers.smartrecruiters.com/Deloitte6")["kind"] == "smartrecruiters"
    w = d("https://rbc.wd3.myworkdayjobs.com/en-US/RBCGLOBAL1?q=analyst")
    assert w == {"kind": "workday", "ref": {"host": "rbc.wd3.myworkdayjobs.com", "tenant": "rbc", "site": "RBCGLOBAL1", "search": "analyst"}}
    assert d("https://www.mckinsey.com/careers/search-jobs")["kind"] == "page"

    # the old switches become entries once; after that the list is the user's
    c = TestClient(app)
    rows = c.get("/api/employers").json()["employers"]
    assert {r["name"] for r in rows} == {"Amazon", "Apple", "Google", "Microsoft", "Meta", "NVIDIA", "AMD", "Intel"} and all(r["priority"] for r in rows)
    assert c.post("/api/employers", json={"name": "", "url": "https://www.amazon.jobs"}).status_code == 400  # already there
    r = c.post("/api/employers", json={"name": "McKinsey & Company", "url": "https://www.mckinsey.com/careers/search-jobs"}).json()
    assert r["kind"] == "page" and r["priority"] is True
    g = c.post("/api/employers", json={"name": "", "url": "https://job-boards.greenhouse.io/stripe", "priority": False}).json()
    assert g["name"] == "Stripe" and g["kind_label"] == "Greenhouse"
    meta = next(x for x in rows if x["name"] == "Meta")
    c.delete("/api/employers/" + meta["id"])
    c.patch("/api/employers/" + g["id"], json={"priority": True, "kind": "hack"})
    now = {x["name"]: x for x in c.get("/api/employers").json()["employers"]}
    assert "Meta" not in now and now["Stripe"]["priority"] and now["Stripe"]["kind"] == "greenhouse" and len(now) == 9
    assert employers.is_priority("McKinsey & Company Canada") and employers.is_priority("Stripe, Inc.") and not employers.is_priority("Meta")
    with db.session() as s:
        s.add(Job(source="page", source_id="x", tenant=r["id"], company="McKinsey & Company", title="Business Analyst", status="scored", online=1))
        s.add(Job(source="manual", source_id="y", company="Unknown Ltd", title="Analyst", status="scored", online=1))
    jobs = {j["company"]: j for j in c.get("/api/jobs").json()["jobs"]}
    assert jobs["McKinsey & Company"]["priority"] is True and jobs["Unknown Ltd"]["priority"] is False
    assert next(x for x in c.get("/api/employers").json()["employers"] if x["name"].startswith("McKinsey"))["open_jobs"] == 1


def test_imap_mailbox_is_read_only_and_parsed(app_env, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from email.message import EmailMessage
    from email.utils import format_datetime

    from fastapi.testclient import TestClient

    from autoapply import db, mail, mailbox, secrets
    from autoapply.api.main import app

    now = datetime.now(timezone.utc)

    def make(subject, body, html=None, when=None, mid="<1@x>"):
        m = EmailMessage()
        m["From"], m["Subject"], m["Date"], m["Message-ID"] = "Careers <no-reply@acme.com>", subject, format_datetime(when or now), mid
        m.set_content(body)
        if html:
            m.add_alternative(html, subtype="html")
        return m.as_bytes()

    box = [make("Verify your Acme account", "", html='<p>Click <a href="https://acme.com/verify?token=abc123">here</a></p>', mid="<v@x>"),
           make("=?utf-8?b?5oSf6LCi5oKo55qE55Sz6K+3?=", "Thank you for applying to Acme.", mid="<a@x>"),
           make("Weekly newsletter", "Ten tips for gardening.", mid="<n@x>"),
           make("Old application", "Thank you for applying.", when=now - timedelta(days=30), mid="<o@x>")]
    calls = []

    class Fake:
        def __init__(self, host, port, timeout=None):
            calls.append(("connect", host, port))

        def login(self, user, pw):
            calls.append(("login", user, pw))

        def select(self, folder, readonly=False):
            calls.append(("select", folder, readonly))
            return "OK", [b"4"]

        def search(self, charset, *crit):
            return "OK", [b"1 2 3 4"]

        def fetch(self, num, what):
            calls.append(("fetch", what))
            return "OK", [(b"x", box[int(num) - 1])]

        def logout(self):
            calls.append(("logout",))

    monkeypatch.setattr(mailbox.imaplib, "IMAP4_SSL", Fake)
    with __import__("pytest").raises(mailbox.NotConfigured):
        mailbox.test({"host": "imap.qq.com", "port": 993, "user": "me@qq.com"}, None)
    db.set_setting("mail.kind", "imap")
    db.set_setting("mail.imap", {"preset": "qq", "user": "me@qq.com"})
    secrets.put(mailbox.IMAP_PASSWORD, "authcode")
    assert mailbox.status()["ready"] and mailbox.imap_config()["host"] == "imap.qq.com"
    msgs = mailbox.fetch(now - timedelta(days=3), 10)
    assert [m.id for m in msgs] == ["<n@x>", "<a@x>", "<v@x>"] and msgs[1].subject == "感谢您的申请"  # newest first, the 30-day-old one is cut
    assert ("select", "INBOX", True) in calls and all(c[1] == "(BODY.PEEK[])" for c in calls if c[0] == "fetch")  # never marks anything as read
    assert [m.id for m in mailbox.fetch(now - timedelta(days=3), 10, job_related=True)] == ["<a@x>"]  # the newsletter and the account e-mail are not about an application
    assert mail.wait_for_verification(sender_hint="careers.acme.com", timeout=2, since=now - timedelta(minutes=5)) == "https://acme.com/verify?token=abc123"
    c = TestClient(app)
    assert c.post("/api/mailbox/test", json={}).json() == {"ok": True, "recent": 3}
    d = c.get("/api/mailbox").json()
    assert d["kind"] == "imap" and d["imap"]["has_password"] and "authcode" not in str(d) and any(p["key"] == "163" for p in d["presets"])


def test_persona_shapes_profile_questions_writing_and_stories(app_env):
    from autoapply import config, db, knowledge, persona, prompts

    db.set_setting("persona", {"stage": "mid", "field": "business", "targets": ["Finance Manager"]})
    asks = persona.profile_asks()
    assert any("notice period" in a for a in asks) and any("CPA" in a for a in asks) and not any("work terms" in a for a in asks)
    assert "notice period" in prompts.get("profile_init") and "outcomes and scope" in prompts.get("letter_write") and "commercial judgement" in prompts.get("letter_write")
    db.set_setting("persona", {})
    assert "TODO: <question>' for each" not in prompts.get("profile_init") and "How to pitch" not in prompts.get("letter_write")

    knowledge.DOCS["stories"] = config.KNOWLEDGE / "stories.md"
    assert knowledge.stories() == "" and "example" in knowledge.read("stories")  # the empty template is not a story
    knowledge.write("stories", knowledge.EMPTY_STORIES + "\n## Fixing the release pipeline\n\n- Situation: builds took an hour and failed often.\n- What I did: split the build and added caching.\n- Result: ten minutes, failures near zero.\n")
    assert "Fixing the release pipeline" in knowledge.stories()
    assert "ONLY from a story" in prompts.get("answers")


def test_salary_and_referees_form_keeps_its_profile_sections(app_env):
    from autoapply import knowledge
    from autoapply.ats.base import sensitivity

    knowledge.write("profile", "# Profile\n\n## Identity\n\n- Name: A B\n")
    knowledge.set_structured({"compensation": {"policy": "state", "min": "70000", "max": "85000", "currency": "CAD", "period": "year", "negotiable": True,
                                               "current": "62000 CAD", "share_current": False, "notice": "2 weeks"},
                              "referees": [{"name": "Dana Wu", "title": "Manager", "org": "Acme", "email": "dana@example.com", "contact": "after_offer"}, {"name": " "}]})
    md = knowledge.read("profile")
    assert "- Name: A B" in md                                                    # the rest of the profile is untouched
    assert "**70000–85000 CAD per year**" in md and "negotiable" in md and "Notice period: 2 weeks" in md
    assert "62000" not in md and "does not disclose" in md                        # a current salary the user keeps private never reaches a prompt
    assert "**Dana Wu** (Manager, Acme)" in md and "only after an offer" in md and md.count("## Referees") == 1
    # saving again replaces the two sections instead of adding to them; emptying one removes it
    knowledge.set_structured({"compensation": {"policy": "ask"}, "referees": []})
    md = knowledge.read("profile")
    assert "do not state a figure" in md and "70000" not in md and "## Referees" not in md and md.count("## Compensation and notice period") == 1
    assert sensitivity("Please list two professional references") == "referee" and sensitivity("What is your notice period?") == "salary"
    assert sensitivity("Reference number") == ""


def test_region_packs_explain_forms_and_never_supply_answers(app_env):
    from autoapply import persona, regions
    from autoapply.intake import countries_of

    assert sorted(regions.packs()) == ["AU", "CA", "EU", "GB", "SG", "US"]
    assert regions.pack_for("de")[0] == "EU" and regions.pack_for("FR")[0] == "EU" and regions.pack_for("BR") is None
    # a job in Berlin gets the EU briefing once, however many EU countries are named
    assert countries_of("Berlin, Germany") == {"DE"}
    eu = regions.notes({"DE", "FR"})
    assert eu.count("European Union:") == 1 and "Gehaltsvorstellung" in eu and "talent pool" in eu and "Never fill in" in eu
    assert regions.for_location("London, UK").startswith("United Kingdom:") and regions.for_location("Lagos, Nigeria") == ""
    # every pack tells the applicant what to state, describes the sensitive extras, and names what is never filled in
    for code, p in regions.packs().items():
        assert p["profile"] and p["questions"] and p["never"] and p["name"]["zh"] and p["name"]["en"], code
    # the profile hints follow the countries the user chose
    asks = persona.profile_asks({"stage": "early", "field": "business", "countries": ["GB", "SG"]})
    assert any(a.startswith("United Kingdom: right to work") for a in asks) and any("Singapore" in a for a in asks) and not any("Canada" in a for a in asks)


def test_notifications_follow_the_interface_language(app_env, monkeypatch):
    """With the interface in English, what goes to Telegram is English; names and anything a site or the AI wrote stay as written."""
    from autoapply import db, i18n, messages, notify

    sent = []

    class Chan:
        def send_card(self, card, base):
            sent.append(card.plain(base))

    monkeypatch.setattr(notify, "_channels", lambda: [Chan()])
    db.set_setting("notify.todo", True)
    card = messages.todo("review", "Acme · 数据分析师 Intern", payload={"draft_id": 3})
    notify.send("todo", card)
    assert "草案等你审批" in sent[-1]                                   # Chinese interface: unchanged
    db.set_setting("ui.lang", "en")
    notify.send("todo", messages.todo("review", "Acme · 数据分析师 Intern", payload={"draft_id": 3}))
    en = sent[-1]
    import re
    head = en.splitlines()[0]
    assert not re.search(r"[\u4e00-\u9fff]", head) and "draft" in head.lower(), head     # the program's wording is translated
    assert "Acme · 数据分析师 Intern" in en                               # the posting's own title is not touched
    assert "：" not in en.replace("数据分析师", "")                         # no full-width punctuation left in an English message
    inc = messages.todo("submit", "Acme · Engineer", "还有 2 处没填好，需要你在窗口里处理", payload={"incomplete": True}).localized()
    assert not re.search(r"[\u4e00-\u9fff]", inc.heading + inc.hint), (inc.heading, inc.hint)
    # all or nothing: a sentence the dictionary only half knows is passed on as it was
    assert i18n.tr("草案等你审批，另外还有一句词典里没有的话", "en") == "草案等你审批，另外还有一句词典里没有的话"
    assert i18n.tr("plain ascii", "en") == "plain ascii" and i18n.tr("草案等你审批", "zh") == "草案等你审批"


FEED_XML = """<?xml version="1.0"?><rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>Board</title>
<item><title>Acme University: Assistant Professor &amp;amp; Lab Lead</title><link>https://jobs.example.test/job/1</link><guid>g1</guid>
  <pubDate>Fri, 13 Nov 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;Teach &lt;b&gt;two&lt;/b&gt; courses.&lt;/p&gt;</description></item>
<item><title>Data Analyst, Beta Corp</title><link>https://jobs.example.test/job/2</link><dc:creator>Beta Corp</dc:creator></item>
<item><title>No link here</title></item></channel></rss>"""


def test_job_feeds_are_read_as_postings_of_many_employers(app_env, monkeypatch):
    from autoapply import employers
    from autoapply.sources import public

    items = public.parse_feed(FEED_XML)
    assert [i["link"] for i in items] == ["https://jobs.example.test/job/1", "https://jobs.example.test/job/2"]      # an item without a link is not a posting
    assert items[0]["date"] == "2026-11-13" and items[0]["summary"] == "Teach two courses." and items[1]["author"] == "Beta Corp"
    assert public.split_title("Acme University: Assistant Professor", "employer: title") == ("Acme University", "Assistant Professor")
    assert public.split_title("Data Analyst, Beta Corp", "title, employer") == ("Beta Corp", "Data Analyst")
    assert public.split_title("Waveguard USA is hiring for a position of Brand Designer", "employer is hiring title") == ("Waveguard USA", "Brand Designer")
    assert public.split_title("Assistant Professor", "") == ("", "Assistant Professor")

    class Resp:
        text = FEED_XML
        def raise_for_status(self): pass

    class Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): return Resp()

    monkeypatch.setattr(public.httpx, "Client", Client)
    # a feed address is recognised as such; a careers page is not
    assert employers.detect("https://jobs.example.test/jobsrss/")["kind"] == "feed" and employers.detect("https://weworkremotely.com/categories/remote-design-jobs.rss")["kind"] == "feed"
    assert employers.detect("https://example.test/careers")["kind"] == "page" and employers.detect("https://boards.greenhouse.io/acme")["kind"] == "greenhouse"
    e = employers.add("Example Board", "https://jobs.example.test/jobsrss/")
    rows = list(employers.rows_for(e, [], lambda *a: True))
    assert [(r["company"], r["title"]) for r in rows] == [("Acme University", "Assistant Professor & Lab Lead"), ("Beta Corp", "Data Analyst, Beta Corp")]
    assert rows[0]["source"] == "feed" and rows[0]["tenant"] == e["id"] and rows[0]["jd_text"] == "Teach two courses." and rows[0]["posted"] == "2026-11-13"
    assert employers.source_of(e) == ("feed", e["id"])
    # every board in the catalog is a feed with a known title style, and is offered until it has been added
    boards = [r for r in employers.catalog("academic", ["US"]) if r.get("board")]
    assert len(boards) >= 10 and all(employers.detect(b["url"])["kind"] == "feed" for b in boards)


def test_every_question_gets_its_own_id_and_positional_selectors_are_refused(app_env):
    """A form described with "the 2nd drop-down" on every page gave several questions one id; their answers were then lost.
    Ids are unique whatever the description says, and the description itself is sent back once."""
    from autoapply import generic

    rows = [(":nth-match(select, 1)", 0, "Country/Region"), (":nth-match(select, 2)", 0, "Province/State"), (":nth-match(select, 1)", 2, "How did you hear about this role?"),
            ("#email", 0, "Email address"), (":nth-match(select, 1)", 2, "How did you hear about this role?")]
    ids = generic.unique_ids(rows)
    assert len(set(ids)) == 5 and ids[3] == "#email"                       # a selector of its own stays the id
    assert "Country/Region" in ids[0] and "p3" in ids[2] and ids[4].endswith("#2")
    assert generic.weak_selector(":nth-match(select, 3)") and generic.weak_selector("select") and generic.weak_selector("input >> nth=2")
    assert not generic.weak_selector("#input-16") and not generic.weak_selector("[name=q_phone]") and not generic.weak_selector("@label:Country/Region")
    qs = [{"label": "Country", "type": "select", "page": 0, "selector": ":nth-match(select, 1)"}, {"label": "A", "type": "text", "page": 0, "selector": "#a"},
          {"label": "B", "type": "text", "page": 0, "selector": "#a"}, {"label": "C", "type": "text", "page": 1, "selector": "#a"},
          {"label": "Legal name", "type": "text", "page": 0, "selector": "@label:Legal name"}, {"label": "Resume", "type": "file", "page": 0, "selector": "input[type=file]"}]
    assert generic.selector_problems(qs) == ["Country", "A", "B"]          # positional, and two on one page sharing a selector; the same selector on another page is fine


def test_answers_are_matched_by_short_keys_and_skipped_questions_are_asked_again(app_env, monkeypatch):
    from autoapply import answers, knowledge, llm
    from autoapply.ats.base import FormSchema, Question
    from autoapply.models import Job

    knowledge.write("profile", "# Profile\n\n- Country: Canada\n- Over 18: yes\n")
    q = lambda i, label: Question(id=i, label=label, type="select", required=True, options=["Yes", "No", "Canada"], locator={"selector": ":nth-match(select, 1)"})  # noqa: E731
    schema = FormSchema(ats="generic", tenant="x", url="", source="agent", pages=["a"], questions=[
        q(":nth-match(select, 1) | p1 | Country/Region", "Country/Region"), q(":nth-match(select, 1) | p5 | Are you 18 years of age or older?", "Are you 18 years of age or older?"),
        q("#visa", "Visa status")])
    calls = []

    def fake_json(prompt, schema_, *, system=None, small=False, **kw):
        calls.append(prompt)
        assert ":nth-match" not in prompt.split("Questions to answer:")[1]            # the model never sees the selectors
        if len(calls) == 1:                                                           # first reply leaves one question out
            return {"answers": [{"id": "k1", "resolved": True, "value": "Canada", "basis": "资料", "confidence": "high", "new_rule": ""},
                                {"id": "k3", "resolved": False, "value": "", "basis": "资料里没有签证类型", "confidence": "low", "new_rule": ""}]}
        assert "id=k2" in prompt and "id=k1 " not in prompt
        return {"answers": [{"id": "k2", "resolved": True, "value": "Yes", "basis": "资料", "confidence": "high", "new_rule": ""}]}

    monkeypatch.setattr(llm, "json", fake_json)
    job = Job(source="manual", source_id="k", company="Acme", title="Intern", apply_url="https://x.test/j", jd_text="x" * 300)
    res = answers.resolve(schema, job)
    got = {a["label"]: (a["value"], a["source"]) for a in res["answers"]}
    assert got == {"Country/Region": ("Canada", "profile"), "Are you 18 years of age or older?": ("Yes", "profile"), "Visa status": ("", "unresolved")}
    assert len(calls) == 2 and [u["label"] for u in res["unresolved"]] == ["Visa status"]
    # only: just the named questions are answered, the rest of the form is context
    calls.clear()
    res = answers.resolve(schema, job, only={"#visa"})
    assert [a["id"] for a in res["answers"]] == ["#visa"] and "Country/Region" in calls[0] and "id=k2" not in calls[0]


def test_an_old_draft_with_shared_ids_is_repaired_and_asked_again(app_env, monkeypatch):
    from autoapply import db, drafts, knowledge, llm
    from autoapply.models import Application, Draft, Job

    knowledge.write("profile", "# Profile\n\n- Country: Canada\n")
    sel = ":nth-match(select, 1)"
    mk = lambda label, page: {"id": sel, "label": label, "type": "select", "required": True, "options": ["Yes", "No", "Canada"], "page": page, "section": "", "help": "",  # noqa: E731
                              "locator": {"selector": sel}, "depends_on": "", "accept_text": False}
    row = lambda label, page, value, source: {"id": sel, "label": label, "type": "select", "options": ["Yes", "No", "Canada"], "required": True, "page": page, "value": value,  # noqa: E731
                                              "basis": "not answered" if not value else "资料", "confidence": "high", "source": source, "sensitive": "", "sensitive_confirmed": False}
    with db.session() as s:
        job = Job(source="manual", source_id="d1", company="Acme", title="Intern", apply_url="https://x.test/j", channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        app = Application(job_id=job.id, status="needs_input")
        s.add(app)
        s.flush()
        d = Draft(application_id=app.id, review_status="pending",
                  schema={"ats": "generic", "tenant": "x.test", "url": "https://x.test/j", "source": "agent", "pages": ["a", "b"], "extra": {}, "job_ref": "", "questions": [mk("Country/Region", 0), mk("Are you 18?", 1)],
                          "_ref": {"ats": "generic", "tenant": "x.test", "job_id": "", "url": "https://x.test/j", "host": "x.test", "extra": {}}},
                  answers=[row("Are you 18?", 1, "", "unresolved"), row("Country/Region", 0, "", "unresolved")], unresolved=[row("Are you 18?", 1, "", "unresolved")])
        s.add(d)
        s.flush()
        did, app_id = d.id, app.id

    def fake_json(prompt, schema_, **kw):
        keys = [ln.split(" | ")[0][5:] for ln in prompt.split("Questions to answer:")[1].splitlines() if ln.startswith("- id=")]
        labels = {ln.split(" | ")[0][5:]: ln for ln in prompt.split("Questions to answer:")[1].splitlines() if ln.startswith("- id=")}
        return {"answers": [{"id": k, "resolved": "Country" in labels[k], "value": "Canada" if "Country" in labels[k] else "", "basis": "资料", "confidence": "high", "new_rule": ""} for k in keys]}

    monkeypatch.setattr(llm, "json", fake_json)
    out = drafts.reanswer(did)
    assert out == {"asked": 2, "answered": 1, "left": 1, "ids_fixed": 2}
    with db.session() as s:
        d = s.get(Draft, did)
        ids = [q["id"] for q in d.schema["questions"]]
        assert len(set(ids)) == 2 and all(q["locator"]["selector"] == sel for q in d.schema["questions"])    # how the control is found does not change
        got = {a["label"]: (a["id"], a["value"]) for a in d.answers}
        assert got["Country/Region"] == (ids[0], "Canada") and got["Are you 18?"] == (ids[1], "")
        assert [u["label"] for u in d.unresolved] == ["Are you 18?"] and s.get(Application, app_id).status == "needs_input"


def test_mail_about_a_started_application_does_not_confirm_it(app_env, monkeypatch):
    """Amazon mails "Keep track of your application" as soon as an application is begun. That must not turn a draft into "confirmed"."""
    from datetime import datetime

    from autoapply import db, llm, mail, mailbox, notify
    from autoapply.models import Application, Job, MailEvent

    with db.session() as s:
        for i, (st, sub_at) in enumerate([("needs_input", None), ("submitted", datetime(2026, 11, 14))]):
            j = Job(source="manual", source_id=f"m{i}", company=f"Acme{i}", title="Engineer Intern", apply_url=f"https://x.test/{i}", channel="employer site", jd_text="x" * 300)
            s.add(j)
            s.flush()
            s.add(Application(job_id=j.id, status=st, submitted_at=sub_at))
    msgs = [mailbox.Message(id=f"id{i}", sender="noreply@x.test", subject=subj, body=body, date=datetime(2026, 11, 14, 13, i))
            for i, (subj, body) in enumerate([("Keep track of your application", "Acme0 started"), ("Thank you for applying", "Acme0 really received"), ("Thank you for applying", "Acme1 received")])]
    replies = {"Acme0 started": {"category": "confirmation", "company": "Acme0", "job_title": "Engineer Intern", "received": False, "summary": "application started"},
               "Acme0 really received": {"category": "confirmation", "company": "Acme0", "job_title": "Engineer Intern", "received": True, "summary": "received"},
               "Acme1 received": {"category": "confirmation", "company": "Acme1", "job_title": "Engineer Intern", "received": True, "summary": "received"}}
    monkeypatch.setattr(llm, "json", lambda prompt, schema, **kw: next(v for k, v in replies.items() if k in prompt))
    monkeypatch.setattr(mailbox, "fetch", lambda since, limit=50, job_related=False: msgs)
    sent = []
    monkeypatch.setattr(notify, "send", lambda category, card, **kw: sent.append(kw.get("ref")) or True)
    out = mail.track()
    with db.session() as s:
        a0, a1 = s.query(Application).order_by(Application.id).all()
        cats = {e.subject + "|" + (e.summary or ""): (e.category, e.application_id) for e in s.query(MailEvent)}
        # "started" is not a confirmation at all; a real-looking confirmation still does not confirm a draft nobody submitted, and says so
        assert cats["Keep track of your application|application started"] == ("other", None)
        assert a0.status == "needs_input" and "还没有提交过" in a0.last_event and not (a0.evidence or {}).get("mail_id")
        # an application that was submitted is confirmed as before
        assert a1.status == "confirmed" and a1.evidence["mail_id"] == "id2"
    assert out["status_updates"] == 1 and sent == [f"application:{a1.id}"]          # no "confirmed" notification for the draft
    assert "needs_input" in mail.PREPARING and "submitted" not in mail.PREPARING and "ready_to_submit" not in mail.PREPARING
    assert "started" in mail.TRIAGE_RULES and "received" in mail.TRIAGE_SCHEMA["properties"]


def test_first_start_language_follows_the_installer_then_the_system(app_env, monkeypatch):
    from autoapply import config, db, i18n
    from autoapply.models import Job

    # a fresh installation: the installer's choice wins
    (config.DATA / "ui-lang.txt").write_text("en", encoding="ascii")
    i18n.first_run_lang()
    assert db.get_setting("ui.lang") == "en"
    # once set (by setup or by the user) it is never touched again
    monkeypatch.setattr(i18n, "system_lang", lambda: "zh-cn")
    (config.DATA / "ui-lang.txt").write_text("zh", encoding="ascii")
    i18n.first_run_lang()
    assert db.get_setting("ui.lang") == "en"


def test_first_start_language_without_installer_uses_the_system_and_leaves_existing_installs_alone(app_env, monkeypatch):
    from autoapply import db, i18n
    from autoapply.models import Job, Setting

    def row():
        with db.session() as s:
            r = s.get(Setting, "ui.lang")
            return None if r is None else r.value

    for tag, want in (("zh-tw", "zh"), ("zh-cn", "zh"), ("en-us", "en"), ("de-de", "en"), ("", "en")):
        with db.session() as s:
            s.query(Setting).filter_by(key="ui.lang").delete()
        monkeypatch.setattr(i18n, "system_lang", lambda tag=tag: tag)
        i18n.first_run_lang()
        assert db.get_setting("ui.lang") == want, tag
    # an installation that already has jobs and never chose a language keeps the language it has been showing
    with db.session() as s:
        s.query(Setting).filter_by(key="ui.lang").delete()
        s.add(Job(source="manual", source_id="x", company="A", title="B", apply_url="https://x.test", jd_text="x"))
    monkeypatch.setattr(i18n, "system_lang", lambda: "en-us")
    i18n.first_run_lang()
    assert row() is None and db.get_setting("ui.lang") == "zh"
