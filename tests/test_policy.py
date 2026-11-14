"""How an approved draft is submitted: automatically, unless the user or the run says otherwise."""


def _a(conf="high", value="x", typ="text"):
    return {"label": "Q", "value": value, "confidence": conf, "type": typ}


def test_approved_draft_is_submitted_automatically_by_default(app_env):
    from autoapply import executor

    m = executor.submit_mode("greenhouse", "Acme", [_a(), _a("medium")])
    assert m == {"mode": "auto", "reasons": []}


def test_manual_when_the_user_or_the_answers_say_so(app_env):
    from autoapply import db, executor

    assert executor.submit_mode("greenhouse", "Acme", [_a("low")])["mode"] == "manual"  # a shaky answer
    assert executor.submit_mode("greenhouse", "Acme", [_a("low", value="")])["mode"] == "auto"  # empty answers do not count
    assert executor.submit_mode("someats", "Acme", [_a()], has_driver=False)["mode"] == "manual"  # no driver
    db.set_setting("policy.manual_confidence", "none")
    assert executor.submit_mode("greenhouse", "Acme", [_a("low")])["mode"] == "auto"
    db.set_setting("policy.manual_confidence", "medium")
    assert executor.submit_mode("greenhouse", "Acme", [_a("medium")])["mode"] == "manual"
    db.set_setting("policy.manual_confidence", "low")
    db.set_setting("policy.manual_companies", ["acme"])
    m = executor.submit_mode("greenhouse", "Acme Robotics Inc.", [_a()])
    assert m["mode"] == "manual" and "acme" in m["reasons"][0]
    assert executor.submit_mode("greenhouse", "Globex", [_a()])["mode"] == "auto"
    db.set_setting("policy.per_ats", {"workday": "manual"})
    assert executor.submit_mode("workday", "Globex", [_a()])["mode"] == "manual"
    assert executor.submit_mode("greenhouse", "Globex", [_a()])["mode"] == "auto"
