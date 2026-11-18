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


def _aged(days, **where):
    """Move a posting's dates back, as if that many days had passed."""
    from datetime import timedelta

    from autoapply import db
    from autoapply.models import Job

    with db.session() as s:
        for j in s.query(Job).filter_by(**where):
            j.last_seen = j.last_seen - timedelta(days=days)
            if j.missed_since is not None:
                j.missed_since = j.missed_since - timedelta(days=days)


def _online(**where):
    from autoapply import db
    from autoapply.models import Job

    with db.session() as s:
        return {j.source_id: (j.online, j.status) for j in s.query(Job).filter_by(**where)}


def test_a_filtered_listing_ages_out_its_own_postings_and_no_one_elses(app_env):
    """Reading Acme's board took Beta's postings offline: the rule for capped listings looked at the whole service.

    (F-07: "complete" was limited to the listing that was read, "stale_days" was not.)"""
    from autoapply import discover

    acme = [{"source_id": f"a{i}", "title": f"T{i}", "company": "Acme", "tenant": "acme"} for i in (1, 2, 3)]
    beta = [{"source_id": f"b{i}", "title": f"T{i}", "company": "Beta", "tenant": "beta"} for i in (1, 2)]
    filtered = {"source": "greenhouse", "complete": False, "stale_days": 5}
    discover.upsert(acme, scope="acme", **filtered)
    discover.upsert(beta, scope="beta", **filtered)
    # Beta's board has not been read for ten days (it was down, or switched off); Acme's is read every day
    _aged(10, tenant="beta")
    assert discover.upsert(acme, scope="acme", **filtered)["offline"] == 0
    assert _online(tenant="beta") == {"b1": (1, "new"), "b2": (1, "new")}
    # ...and when Beta's is read again it shows one of the two: the other has been missing for one reading, not for ten days
    assert discover.upsert(beta[:1], scope="beta", **filtered)["offline"] == 0
    assert _online(tenant="beta") == {"b1": (1, "new"), "b2": (1, "new")}
    # six days of readings that do not show it: gone - on Beta's word, while Acme's are as they were
    _aged(6, tenant="beta")
    assert discover.upsert(beta[:1], scope="beta", **filtered)["offline"] == 1
    assert _online(tenant="beta") == {"b1": (1, "new"), "b2": (0, "offline")}
    assert set(_online(tenant="acme").values()) == {(1, "new")}


def test_a_posting_a_filtered_listing_shows_again_starts_over(app_env):
    """A capped listing drops a posting for a day and shows it the next: the days it was missing are not kept against it."""
    from autoapply import db, discover
    from autoapply.models import Job

    rows = [{"source_id": str(i), "title": f"T{i}", "company": "Acme", "tenant": "acme"} for i in (1, 2, 3)]
    filtered = {"source": "greenhouse", "scope": "acme", "complete": False, "stale_days": 5}
    discover.upsert(rows, **filtered)
    assert discover.upsert(rows[:1], **filtered)["offline"] == 0                 # the first reading without 2 and 3
    with db.session() as s:
        assert [bool(j.missed_since) for j in s.query(Job).order_by(Job.source_id)] == [False, True, True]
    _aged(4, source="greenhouse")
    assert discover.upsert(rows[:2], **filtered)["offline"] == 0                 # 2 is back after four days; 3 is still missing
    with db.session() as s:
        assert [bool(j.missed_since) for j in s.query(Job).order_by(Job.source_id)] == [False, False, True]
    _aged(2, source="greenhouse")
    assert discover.upsert(rows[:1], **filtered)["offline"] == 1                 # 3: six days; 2: missing since today
    assert _online(source="greenhouse") == {"1": (1, "new"), "2": (1, "new"), "3": (0, "offline")}
    # a partial reading (neither rule) says nothing about what it does not show, however long ago that was
    _aged(30, source="greenhouse")
    assert discover.upsert(rows[:1], source="greenhouse", scope="acme", complete=False)["offline"] == 0
    assert _online(source="greenhouse")["2"] == (1, "new")
    # a posting stored without the name of its listing gets it from the reading, so that the rules above find it
    discover.upsert([{"source_id": "9", "title": "T9", "company": "Acme"}], **filtered)
    with db.session() as s:
        assert s.query(Job).filter_by(source_id="9").one().tenant == "acme"


def test_a_board_that_could_not_be_read_loses_nothing_to_one_that_could(app_env, monkeypatch):
    """A whole scan: Acme answers and Beta does not, for longer than the rule's days - Beta's postings stay."""
    from autoapply import db, discover, employers

    db.set_setting("sources.pdportal", False)
    db.set_setting("intake.enabled", False)
    listed = [{"id": n, "name": n.title(), "kind": "greenhouse", "ref": {"board": n}, "enabled": True} for n in ("acme", "beta")]
    monkeypatch.setattr(employers, "listing", lambda: listed)
    monkeypatch.setattr(employers, "migrate_legacy", lambda: None)
    down = set()

    def rows_for(e, terms, keep):
        board = e["ref"]["board"]
        if board in down:
            raise RuntimeError("the board is not answering")
        return iter([{"source": "greenhouse", "source_id": f"{board}-{i}", "title": f"Intern {i}", "company": e["name"], "tenant": board,
                      "apply_url": f"https://x.example/{board}/{i}", "jd_text": "d" * 300} for i in range(2)])

    monkeypatch.setattr(employers, "rows_for", rows_for)
    assert discover.run(notify_user=False)["total"]["new"] == 4
    down.add("beta")
    for _ in range(3):                                     # three scans, three days apart, with Beta down
        _aged(3, source="greenhouse")
        out = discover.run(notify_user=False)
        assert "not answering" in out["errors"]["Beta"] and out["total"]["offline"] == 0
    assert _online(tenant="beta") == {"beta-0": (1, "new"), "beta-1": (1, "new")}
    assert _online(tenant="acme") == {"acme-0": (1, "new"), "acme-1": (1, "new")}
    down.clear()
    assert discover.run(notify_user=False)["total"]["offline"] == 0   # Beta is back and still shows both


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
