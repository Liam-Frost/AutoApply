"""The overview of the settings says what the program does.

It is read-only text about rules that live in a dozen settings. Text of that kind goes stale the first time a rule
changes and the sentence about it does not - so each statement is held here against the code that acts on the rule.
"""
from autoapply import db


def _by(rows, key="key"):
    return {r[key]: r for r in rows}


def test_who_presses_submit_is_what_the_executor_decides(app_env):
    from autoapply import executor, rules

    for default in ("approve_then_submit", "manual"):
        for per in ({}, {"workday": "manual"}, {"greenhouse": "approve_then_submit", "generic": "manual"}):
            db.set_setting("policy.default", default)
            db.set_setting("policy.per_ats", per)
            said = _by(rules.what_the_program_may_do())["submit"]
            modes = rules.submit_by_system()
            assert modes == {k: executor.submit_mode(k, "", [])["mode"] for k, _ in rules.SYSTEMS}
            # the sentence states the default; every system that departs from it is named, and no other
            assert ("由你检查后点提交" in said["text"]) == (default == "manual")
            named = {n for k, n in rules.SYSTEMS if any(m.startswith(n + "：") for m in said["more"])}
            assert named == {n for k, n in rules.SYSTEMS if modes[k] != ("manual" if default == "manual" else "auto")}
            assert all(x in " ".join(said["more"]) for x in executor.STOPS_ANYWAY)
    db.set_setting("policy.default", "approve_then_submit")
    db.set_setting("policy.per_ats", {})
    db.set_setting("policy.manual_companies", ["Acme"])
    db.set_setting("policy.manual_confidence", "medium")
    said = _by(rules.what_the_program_may_do())["submit"]
    assert said["who"] == "mixed" and any("Acme" in m for m in said["more"]) and any("把握中等" in m for m in said["more"])
    # and the reasons a draft gives lead to the section that decides them
    m = executor.submit_mode("greenhouse", "Acme Robotics", [{"label": "Why us", "value": "x", "confidence": "medium", "type": "text"}])
    assert m["mode"] == "manual" and m["reasons"] == [w["text"] for w in m["why"]] and len(m["why"]) == 2
    assert {w["where"] for w in m["why"]} == {said["where"]}


def test_approval_registration_and_the_rest_follow_the_settings(app_env):
    from autoapply import rules
    from autoapply.ats.base import JobRef
    from autoapply import auth

    steps = _by(rules.what_the_program_may_do())
    assert steps["approve"]["who"] == "you" and "每份草案都要你批准" in steps["approve"]["text"]
    db.set_setting("auto_approve.enabled", True)          # on, and no system allowed: nothing is approved automatically (answers.auto_approve_check: enabled AND per_ats)
    assert _by(rules.what_the_program_may_do())["approve"]["who"] == "you"
    db.set_setting("auto_approve.per_ats", {"greenhouse": True})
    db.set_setting("auto_approve.min_score", 8.5)
    a = _by(rules.what_the_program_may_do())["approve"]
    assert a["who"] == "mixed" and "Greenhouse" in a["text"] and any("8.5" in m for m in a["more"]) and a["where"].endswith("submit-auto")

    # creating accounts: what is said is what auth.may_register answers
    for auto, per in ((True, {}), (True, {"workday": False}), (False, {})):
        db.set_setting("register.auto", auto)
        db.set_setting("register.per_ats", per)
        r = _by(rules.what_the_program_may_do())["register"]
        for ats, name in rules.SYSTEMS:
            may = auth.may_register(JobRef(ats=ats, tenant="nobody-applied-here", job_id="1", url="https://example.com/job"))[0]
            says = auto and not any(m.startswith("这些招聘系统上不自己注册") and name in m for m in r["more"])
            assert may == says, (auto, per, ats)
        assert r["who"] == ("off" if not auto else "mixed" if per else "auto")

    # pausing stops what the program begins by itself, and the overview says so for those steps
    db.set_setting("schedule.paused", True)
    steps = _by(rules.what_the_program_may_do())
    assert steps["discover"]["who"] == "off" and steps["prepare"]["who"] == "off" and rules.summary()["paused"] is True
    db.set_setting("schedule.paused", False)
    db.set_setting("drafts.max_pending", 0)
    assert any("没有数量上限" in m for m in _by(rules.what_the_program_may_do())["prepare"]["more"])


def test_what_i_apply_to_is_read_where_the_program_reads_it(app_env):
    from fastapi.testclient import TestClient

    from autoapply import intake, knowledge, rules
    from autoapply.api.main import app

    db.set_setting("intake.enabled", True)
    db.set_setting("intake.title_any", ["intern", "co-op"])
    db.set_setting("intake.title_none", ["senior"])
    db.set_setting("intake.countries", ["CA"])
    db.set_setting("intake.max_age_days", 30)
    db.set_setting("intake.programs", ["Computer"])
    db.set_setting("queue.min_score_for_draft", 7.5)
    knowledge.write("scoring", "# Scoring\n- Backend and ML roles score high\n- Unpaid roles: exclude\n")
    rows = rules.what_i_apply_to()
    text = " | ".join(f"{r['kind']}:{r['text']}" for r in rows)
    r = intake.rules()
    assert all(w in text for w in (*r["title_any"], *r["title_none"], "CA", "30", "computer", "7.5", "Backend and ML roles score high", "Unpaid roles: exclude"))
    assert {x["kind"] for x in rows} >= {"fact", "filter", "preference", "threshold", "source"} and all(x["where"].startswith("/") and x["label"] for x in rows)
    # every statement about a filter is one the filter makes: a title the rules drop, a title they keep
    assert intake.check({"title": "Senior Software Engineer", "location": "Toronto, ON, CA"}, r) and not intake.check({"title": "Software Engineering Intern", "location": "Vancouver, BC, Canada"}, r)
    db.set_setting("intake.enabled", False)
    off = [x for x in rules.what_i_apply_to() if x["kind"] == "filter"]
    assert any("没有启用" in x["text"] for x in off) and not any("intern" in x["text"] for x in off)
    got = TestClient(app).get("/api/rules").json()
    assert set(got) == {"apply", "allowed", "paused"} and [s["key"] for s in got["allowed"]][:5] == ["discover", "prepare", "approve", "submit", "register"]
