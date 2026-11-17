"""How an approved draft is submitted: automatically, unless the user or the run says otherwise."""


def _a(conf="high", value="x", typ="text"):
    return {"label": "Q", "value": value, "confidence": conf, "type": typ}


def test_approved_draft_is_submitted_automatically_by_default(app_env):
    from autoapply import executor

    m = executor.submit_mode("greenhouse", "Acme", [_a(), _a("medium")])
    assert (m["mode"], m["reasons"]) == ("auto", [])


def test_manual_when_the_user_or_the_answers_say_so(app_env):
    from autoapply import db, executor

    assert executor.submit_mode("greenhouse", "Acme", [_a("low")])["mode"] == "manual"  # a shaky answer
    assert executor.submit_mode("greenhouse", "Acme", [_a("low", value="")])["mode"] == "auto"  # empty answers do not count
    assert executor.submit_mode("someats", "Acme", [_a()])["mode"] == "auto"  # a form the agent read follows the same policy
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


def test_who_presses_submit_is_said_the_same_way_everywhere(app_env):
    """The plan of a draft said "this system has no driver yet: you press Submit" while the line above it said "submitted
    automatically", and the settings page promised a stop the program no longer makes. Who presses Submit is decided in
    one place; the plan's last step is that decision in words, made when the draft is looked at - not a sentence stored
    with the draft the day it was built."""
    from pathlib import Path

    from autoapply import db, drafts, executor
    from autoapply.ats.base import FormSchema, JobRef
    from autoapply.models import Application, Draft, Job

    ref = JobRef("generic", "careers.acme.test", "1", "https://careers.acme.test/1", "careers.acme.test")
    for source in ("agent", "walk"):          # read by the agent, or by a driver: the plan does not say who submits
        steps = drafts.plan_steps(ref, FormSchema(ats="generic", source=source), {}, [], False)
        assert steps[-1] == {"op": "submit", "text": ""}
    with db.session() as s:
        j = Job(source="manual", source_id="p1", company="Acme", title="Intern", apply_url=ref.url, channel="employer site", jd_text="x" * 300)
        s.add(j)
        s.flush()
        a = Application(job_id=j.id, status="draft_ready")
        s.add(a)
        s.flush()
        # a draft from before: its plan carries the old sentence
        d = Draft(application_id=a.id, version=1, review_status="pending", schema={"ats": "generic", "tenant": "careers.acme.test"}, answers=[_a()],
                  plan=[{"op": "open", "text": "打开申请表"}, {"op": "submit", "text": "这个 ATS 还没有驱动：填好后打开窗口，由你检查并点击提交"}])
        s.add(d)
        s.flush()
        did = d.id
    got = drafts.get(did)
    assert got["submit_mode"]["mode"] == "auto" and got["plan"][-1]["text"] == got["submit_mode"]["step"] == executor.submit_step("auto")
    assert "自动提交" in got["plan"][-1]["text"] and got["plan"][0]["text"] == "打开申请表"
    db.set_setting("policy.manual_companies", ["Acme"])                     # the applicant changes their mind: the same draft says so
    got = drafts.get(did)
    assert got["submit_mode"]["mode"] == "manual" and got["plan"][-1]["text"] == got["submit_mode"]["step"]
    assert "由你检查并点击提交" in got["plan"][-1]["text"] and "你把 Acme 设为人工提交" in got["plan"][-1]["text"]
    # what stops an automatic submission anyway is said on the settings page in the program's own words
    root = Path(executor.__file__).parents[2]
    page = (root / "frontend" / "src" / "views" / "SettingsView.vue").read_text(encoding="utf-8")
    assert all(why in page for why in executor.STOPS_ANYWAY) and got["submit_mode"]["stops_anyway"] == executor.STOPS_ANYWAY
    # and the promise that is no longer kept is made nowhere
    for f in [*(root / "backend" / "autoapply").rglob("*.py"), *(root / "frontend" / "src").rglob("*.vue")]:
        text = f.read_text(encoding="utf-8")
        assert "还没有驱动" not in text and "没有专门适配）" not in text and "always submitted by the user" not in text, f.name
