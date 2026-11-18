"""The overview of the settings says what the program does.

It is read-only text about rules that live in a dozen settings. Text of that kind goes stale the first time a rule
changes and the sentence about it does not - so each statement is held here against the code that acts on the rule.
"""
from autoapply import db


def _by(rows, key="key"):
    return {r[key]: r for r in rows}


def test_how_an_application_is_sent_is_what_a_run_is_told(app_env):
    """What the overview says about sending is what a run of the agent is told (agent/work.py: mode_for)."""
    from autoapply import rules
    from autoapply.agent import work

    said_by = {"auto": ("auto", "自己提交"), "approve": ("mixed", "你批准之后"), "hand_over": ("you", "把窗口交给你")}
    for policy, (who, words) in said_by.items():
        db.set_setting("submit.policy", policy)
        said = _by(rules.what_the_program_may_do())["submit"]
        assert said["who"] == who and words in said["text"] and work.mode_for("recon", None) == work.MODE_OF_POLICY[policy]
    db.set_setting("submit.policy", "auto")
    db.set_setting("policy.manual_companies", ["Acme"])
    said = _by(rules.what_the_program_may_do())["submit"]
    assert any("Acme" in m for m in said["more"]) and work.mode_for("recon", None, "Acme Robotics") == "hand_over" and work.mode_for("recon", None, "Beta") == "auto"
    # a résumé rewritten just now waits for the applicant under "send by itself" - said only while that is so
    assert any("改写的简历" in m for m in said["more"])
    db.set_setting("tailor.review", False)
    assert not any("改写的简历" in m for m in _by(rules.what_the_program_may_do())["submit"]["more"])


def test_the_rest_follows_the_settings(app_env):
    from autoapply import agentbudget, rules

    steps = _by(rules.what_the_program_may_do())
    b = agentbudget.for_kind("apply")
    assert str(b.steps) in steps["budget"]["text"] and str(int(b.seconds // 60)) in steps["budget"]["text"]
    db.set_setting("agent.budgets", {"apply": {"steps": 250, "minutes": 30}})
    assert "250" in _by(rules.what_the_program_may_do())["budget"]["text"] and "30" in _by(rules.what_the_program_may_do())["budget"]["text"]
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
    assert set(got) == {"apply", "allowed", "paused"} and [s["key"] for s in got["allowed"]] == ["discover", "prepare", "submit", "accounts", "budget"]
