import pytest

from autoapply.ats.base import DriverError, FormSchema, Question, blocking_drift, diff_schemas, sensitivity, values_equal
from autoapply.ats.widgets import pick_option


def test_values_equal():
    assert values_equal("6045550142", "(604) 555-0142")
    assert values_equal("+1 604-555-0142", "6045550142")
    assert values_equal(" Yes ", "yes")
    assert values_equal(True, True) and not values_equal(True, False)
    assert values_equal(["b", "a"], ["a", "b"])
    assert not values_equal("Yes", "No")
    assert values_equal("https://x.com/", "https://x.com")


def test_pick_option():
    opts = ["Yes, I am legally authorized", "No, I am not legally authorized", "Yes"]
    assert pick_option(opts, "Yes") == 2  # exact beats prefix
    assert pick_option(["Canada (+1)", "Chad (+235)"], "Canada") == 0
    with pytest.raises(DriverError):
        pick_option(["Yes - Newcomer", "Yes - Refugee", "No"], "Yes")  # ambiguous: must not guess


def test_sensitivity():
    assert sensitivity("Will you now or in the future require sponsorship?") == "sponsorship"
    assert sensitivity("Do you own any intellectual property rights (patents)?") == "ip"
    assert sensitivity("What is your gender?") == "demographic"
    assert sensitivity("LinkedIn Profile") == ""


def _s(*qs):
    return FormSchema(ats="x", questions=list(qs))


def test_drift():
    a = _s(Question("n", "First Name", "text", True), Question("a", "Authorized?", "select", True, ["Yes", "No"]))
    blind = _s(Question("n", "First Name *", "textarea", True), Question("a", "Authorized?", "select", True, []))
    assert not blocking_drift(diff_schemas(a, blind))  # unknown options / text family are not drift
    new_required = _s(*a.questions, Question("s", "Salary expectation", "text", True))
    d = diff_schemas(a, new_required)
    assert blocking_drift(d) and d["added"][0]["label"] == "Salary expectation"
    new_optional = _s(*a.questions, Question("s", "Referral", "text", False))
    assert not blocking_drift(diff_schemas(a, new_optional))
    changed = _s(a.questions[0], Question("a", "Authorized?", "select", True, ["Yes", "No", "Unsure"]))
    assert blocking_drift(diff_schemas(a, changed))


def test_mail_extract():
    from autoapply.mail import extract_verification

    assert extract_verification("Your verification code", "Your verification code is 483920. It expires soon.") == "483920"
    link = extract_verification("Verify", "Click https://x.wd1.myworkdayjobs.com/activate?token=abc to verify your account")
    assert link.startswith("https://x.wd1")
    assert extract_verification("Newsletter", "Our office moved to 123456 Main St") is None


def test_workday_detect():
    from autoapply.ats.workday import WorkdayDriver

    r = WorkdayDriver().detect(
        "https://altera.wd1.myworkdayjobs.com/en-US/Altera/job/Toronto-Ontario-Canada/Software-Engineer----Intern_R03414/apply/applyManually"
    )
    assert (r.tenant, r.job_id, r.extra["site"], r.tenant_key) == ("altera.wd1", "R03414", "Altera", "workday:altera.wd1")
    assert r.extra["job_path"].endswith("_R03414")


def test_registry_detect():
    from autoapply.ats import registry

    assert registry.detect("https://job-boards.greenhouse.io/globalrelay/jobs/6241593004").ats == "greenhouse"
    assert registry.detect("https://www.globalrelay.com/careers/jobs/?gh_jid=6241593004").job_id == "6241593004"
    assert registry.detect("https://jobs.ashbyhq.com/solink/c973029a-83fa-449e-b4a9-0a1514165430/application").tenant == "solink"
    assert registry.detect("https://apply.workable.com/botpress/j/9B3CB646E8/apply/").ats == "workable"


def test_secrets_and_csv(app_env):
    from autoapply import auth, secrets

    pw = secrets.generate_password(16)
    assert len(pw) == 16 and any(c.isdigit() for c in pw) and any(c.isupper() for c in pw) and any(c in "!@#$%^&*" for c in pw)
    assert "hunter2" not in secrets.redact("login failed for hunter2", "hunter2")
    csv = (
        "name,url,username,password,note\n"
        "Altera,https://altera.wd1.myworkdayjobs.com/Altera/login,me@x.com,pw1,\n"
        "News,https://news.example.com,me,pw2,\n"
    )
    assert auth.import_chrome_csv(csv) == {"imported": ["workday:altera.wd1"], "skipped": 1}
    assert secrets.get_password("workday:altera.wd1") == "pw1"
    a = auth.account("workday:altera.wd1")
    assert a["has_password"] and a["login_email"] == "me@x.com" and "password" not in a


def test_knowledge_versions(app_env):
    from autoapply import knowledge

    knowledge.write("profile", "# P\n\n## Rules\n\n- a\n", source="user")
    knowledge.append_rule("GPA is 3.11/4.0", source="agent")
    md = knowledge.read("profile")
    assert "## Agent-added" in md and "GPA is 3.11/4.0 (agent," in md
    assert knowledge.agent_added()[0]["note"].startswith("GPA")
    assert knowledge.remove_line("GPA is 3.11") and "GPA" not in knowledge.read("profile")
    first = knowledge.versions()[-1]["id"]
    assert knowledge.restore(first).strip().endswith("- a")


def test_import_tsv(app_env, tmp_path):
    from autoapply import db, importer
    from autoapply.models import Application, Job

    hdr = "\t".join(["ID", "岗位", "公司", "方向", "评分", "学期", "月数", "薪资", "工作类型", "截止时间", "投递渠道", "登记状态", "投递情况", "岗位说明"])
    rows = [
        ["150001", "SWE Co-op", "Acme", "后端", "9", "Winter 2027", "4", "", "", "2026-11-20 23:59", "PD Portal", "已投递", "已投递（2026-11-11，PD Portal）", "d"],
        ["150002", "QA", "Beta", "QA", "5", "Winter 2027", "8", "", "", "", "雇主官网", "未登记", "未投递", "d"],
        ["150003", "X", "Gamma", "其他", "0", "Summer 2027", "16", "", "", "", "雇主官网", "不投递", "不投：仅12/16个月", "d"],
    ]
    p = tmp_path / "jobs.tsv"
    p.write_text("\n".join([hdr] + ["\t".join(r) for r in rows]), encoding="utf-8")
    assert importer.import_tsv(p) == {"added": 3, "updated": 0, "applications": 1, "rows": 3}
    assert importer.import_tsv(p)["updated"] == 3  # idempotent
    with db.session() as s:
        assert s.query(Job).count() == 3 and s.query(Application).one().status == "submitted"
        assert s.query(Job).filter_by(source_id="150003").one().exclusion == "仅12/16个月"


def test_discover_offline_and_back(app_env):
    from autoapply import db, discover
    from autoapply.models import Application, Job

    rows = [{"source_id": str(i), "title": f"T{i}", "company": "Acme", "tenant": "acme"} for i in (1, 2, 3)]
    assert discover.upsert(rows, source="greenhouse", scope="acme")["new"] == 3
    discover.upsert([{"source_id": "9", "title": "Other", "company": "Beta", "tenant": "beta"}], source="greenhouse", scope="beta")
    with db.session() as s:
        j2 = s.query(Job).filter_by(source_id="2").one()
        j2.status = "applied"
        s.add(Application(job_id=j2.id, status="submitted"))
    r = discover.upsert(rows[:1], source="greenhouse", scope="acme")
    assert r["offline"] == 2
    with db.session() as s:
        st = {j.source_id: (j.online, j.status) for j in s.query(Job).all()}
    assert st["1"] == (1, "new") and st["3"] == (0, "offline")
    assert st["2"] == (0, "applied")  # applied jobs keep their status
    assert st["9"][0] == 1  # another board's jobs are untouched
    assert discover.upsert(rows, source="greenhouse", scope="acme")["back"] == 2
    partial = discover.upsert(rows[:1], source="greenhouse", scope="acme", complete=False)
    assert partial["offline"] == 0


def test_mail_match_application(app_env):
    from autoapply import db, mail
    from autoapply.models import Application, Job

    with db.session() as s:
        ids = {}
        for sid, company, title in (("1", "Global Relay", "Co-op Java Developer"), ("2", "Global Relay", "Co-op QA Analyst"), ("3", "Acme Robotics Inc", "Software Intern")):
            j = Job(source="x", source_id=sid, company=company, title=title, status="applied")
            s.add(j)
            s.flush()
            a = Application(job_id=j.id, status="submitted")
            s.add(a)
            s.flush()
            ids[sid] = a.id
    assert mail.match_application("Global Relay", "Java Developer Co-op", None) == ids["1"]
    assert mail.match_application("Acme Robotics", "", None) == ids["3"]
    assert mail.match_application("Global Relay", "", None) is None  # two applications, nothing to tell them apart
    assert mail.match_application("Nobody Corp", "Engineer", None) is None


def test_pdportal_driver_wiring(app_env):
    from autoapply.ats.pdportal import PDPortalDriver

    from autoapply import answers
    from autoapply.ats import registry
    from autoapply.models import Job

    ref = registry.detect("https://pdportal.apsc.ubc.ca/myAccount/co-op/postings.htm#posting=149123")
    assert (ref.ats, ref.job_id, ref.tenant_key) == ("pdportal", "149123", "pdportal:ubc")
    assert getattr(registry.get("pdportal"), "sso", False)
    job = Job(source="pdportal", source_id="149123", company="Acme & Co.")
    assert PDPortalDriver.fixed_answer(Question("package", "Package Name", "text", True), job)[0] == "Acme___Co_149123"
    assert PDPortalDriver.fixed_answer(Question("13", "Transcript", "select", False, ["Student Transcript"]), job)[0] == ""
    assert PDPortalDriver.fixed_answer(Question("13", "Transcript", "select", True, ["Student Transcript"]), job)[0] == "Student Transcript"
    assert PDPortalDriver.fixed_answer(Question("12", "Resume", "select", True, ["A", "B"]), job) is None  # the model picks


def test_llm_backend_switch(app_env, monkeypatch):
    from autoapply import db, llm, llm_sdk

    seen = {}

    def fake_call(content, **kw):
        seen.update(kw, content=content)
        return llm_sdk.SDKResult(text="hi", structured={"a": 1} if kw.get("schema") else None, turns=2, input_tokens=10, output_tokens=3)

    monkeypatch.setattr(llm_sdk, "call", fake_call)
    assert llm.backend() == "subscription"  # default
    llm.reset_usage()
    assert llm.text("x", small=True) == "hi"
    assert seen["model"] == db.get_setting("llm.small_model") and seen["effort"] is None and seen["token"] is None
    assert llm.json("x", llm.obj({"a": {"type": "integer"}})) == {"a": 1}
    assert seen["effort"] == db.get_setting("llm.effort") and seen["max_turns"] > 1
    assert (llm.usage().calls, llm.usage().input_tokens) == (4, 20)

    def boom(content, **kw):
        raise llm_sdk.SDKError("Failed to authenticate", unavailable=True)

    monkeypatch.setattr(llm_sdk, "call", boom)
    with pytest.raises(llm.LLMUnavailable):
        llm.text("x")
    db.set_setting("llm.auth", "api_key")
    assert llm.backend() == "api_key"


def test_sdk_tool_content():
    from autoapply import llm_sdk

    assert llm_sdk._mcp_content("ok") == [{"type": "text", "text": "ok"}]
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}}
    assert llm_sdk._mcp_content([img]) == [{"type": "image", "data": "QUJD", "mimeType": "image/png"}]


def test_sites_are_told_apart_by_host_not_by_a_name_somewhere_in_the_address():
    from autoapply.ats import registry
    from autoapply.ats.base import host_is, url_host
    from autoapply.browser import IDENTITIES

    assert host_is("jobs.ashbyhq.com", "ashbyhq.com") and host_is("ashbyhq.com", "ashbyhq.com") and host_is("JOBS.ashbyhq.com:443", "ashbyhq.com")
    assert not host_is("notashbyhq.com", "ashbyhq.com") and not host_is("ashbyhq.com.evil.example", "ashbyhq.com") and not host_is("", "ashbyhq.com")
    assert url_host("https://Boards.Greenhouse.io/acme/jobs/1") == "boards.greenhouse.io" and url_host("boards.greenhouse.io/acme") == "boards.greenhouse.io"
    # look-alike addresses are ordinary sites, not the systems they imitate
    for url in ("https://evilgreenhouse.io/acme/jobs/123", "https://evil.example/?u=boards.greenhouse.io/acme/jobs/123", "https://myworkdayjobs.com.evil.example/x/job/1",
                "https://fakeashbyhq.com/acme/1"):
        ref = registry.detect(url)
        assert ref is None or ref.ats == "generic", url
    assert registry.detect("https://boards.greenhouse.io/acme/jobs/123").ats == "greenhouse"
    # "sign-in finished" is where the window is, not a name inside the address
    done = {k: v["done"] for k, v in IDENTITIES.items()}
    assert done["google"]("https://myaccount.google.com/") and not done["google"]("https://evil.example/?next=myaccount.google.com")
    assert done["linkedin"]("https://www.linkedin.com/feed/") and not done["linkedin"]("https://www.linkedin.com/login") and not done["linkedin"]("https://evil.example/linkedin.com/feed")
    assert done["microsoft"]("https://account.microsoft.com/?ref=x") and not done["microsoft"]("http://account.microsoft.com.evil.example/")
    assert done["indeed"]("https://ca.indeed.com/") and not done["indeed"]("https://secure.indeed.com/auth")


def test_a_prompt_key_cannot_name_another_file(app_env):
    import pytest

    from autoapply import config, prompts

    victim = config.KNOWLEDGE / "profile.md"
    victim.write_text("keep me", encoding="utf-8")
    for key in ("..\\profile", "../profile", "nope"):
        with pytest.raises(KeyError):
            prompts.reset(key)
    assert victim.read_text(encoding="utf-8") == "keep me"


def test_location_parsing_is_not_slowed_down_by_hostile_text():
    import time

    from autoapply.intake import countries_of

    assert countries_of("Vancouver, BC, CAN") >= {"CA"}
    t = time.time()
    countries_of("a" + ", " * 20000 + "x")
    countries_of("City" + " " * 40000 + ", Region, CA")
    assert time.time() - t < 2


def test_an_application_cut_off_while_being_filled_can_be_started_again(app_env):
    """The program was closed twice while filling a form. The task is given up - and the application must not go on
    showing "being filled" for ever."""
    from autoapply import db, tasks
    from autoapply.models import Application, Job, Task

    with db.session() as s:
        for i in (1, 2):
            j = Job(source="manual", source_id=f"cut{i}", company="Acme", title="Engineer", apply_url=f"https://jobs.example.test/{i}", jd_text="x")
            s.add(j)
            s.flush()
            s.add(Application(job_id=j.id, status="executing"))
        s.flush()
        a1, a2 = [a.id for a in s.query(Application).order_by(Application.id)]
        s.add(Task(kind="execute", ref=f"application:{a1}", status="running", attempts=2, payload={}))   # interrupted for the second time
        s.add(Task(kind="execute", ref=f"application:{a2}", status="running", attempts=1, payload={}))   # first time: it is run again
    tasks.recover()
    with db.session() as s:
        assert s.get(Application, a1).status == "failed" and "中断" in s.get(Application, a1).last_event
        assert s.get(Application, a2).status == "executing"
        assert {t.ref: t.status for t in s.query(Task)} == {f"application:{a1}": "failed", f"application:{a2}": "queued"}


def test_every_server_file_with_text_for_the_applicant_is_on_the_list_to_translate():
    """The list of server files whose text is translated was kept by hand. A new module's messages stayed Chinese in the
    English interface until someone read them there (lifecycle.py, quota.py, backup.py had been missing for a while)."""
    import ast
    import importlib.util
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("i18n_extract", root / "scripts" / "i18n_extract.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    cjk = re.compile(r"[\u4e00-\u9fff]")
    unknown = []
    for p in sorted((root / "backend" / "autoapply").rglob("*.py")):
        rel = p.relative_to(root / "backend" / "autoapply").as_posix()
        if rel in ex.SERVER or rel in ex.NOT_INTERFACE:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        if any(isinstance(n, ast.Constant) and isinstance(n.value, str) and cjk.search(n.value) for n in ast.walk(tree)):
            unknown.append(rel)
    assert unknown == []          # add it to SERVER in scripts/i18n_extract.py - or to NOT_INTERFACE, saying what its Chinese text is
    assert not set(ex.SERVER) & set(ex.NOT_INTERFACE)


def test_which_browser_a_task_worked_in_is_said_in_words():
    """The activity page showed "browser:nodriver (tenant: pdportal:ubc)" as it was written for the record."""
    from autoapply import humanize

    said = humanize.browser_stage
    assert said("browser:playwright (default)") == "" and said("open") == "" and said("") == ""          # the usual one is not worth a line
    assert "普通浏览器" in said("browser:nodriver (tenant: pdportal:ubc)") and "pdportal:ubc" in said("browser:nodriver (tenant: pdportal:ubc)")
    assert "站点规则" in said("browser:nodriver (domain: accounts.google.com)")
    assert "换浏览器重试" in said("browser:nodriver (task override)")
    assert "登录是在它里面做的" in said("browser:nodriver (where the sign-in for workday:acme was made)")
    assert "第三方账号" in said("browser:nodriver (signs in through google: tenant: idp:google)")
    assert "程序自带的浏览器" in said("browser:playwright (tenant: greenhouse:acme)")
    for s in ("browser:nodriver (tenant: x)", "browser:nodriver (something new)"):
        assert "browser:" not in said(s) and "nodriver" not in said(s)
