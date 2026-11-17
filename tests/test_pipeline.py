"""End-to-end pipeline in a real browser against a local form:
recon -> answers (LLM stubbed) -> draft -> review -> approve -> execute -> read-back -> submit -> evidence.
"""

import pytest

from fakes import FORM, FixtureDriver


@pytest.fixture()
def pipeline(app_env, monkeypatch, tmp_path):
    from autoapply import answers, db, handlers, knowledge, llm, notify, tasks  # noqa: F401
    from autoapply.ats import registry
    from autoapply.models import Document, Job

    drv = FixtureDriver()
    monkeypatch.setattr(registry, "drivers", lambda: {"fixture": drv})
    knowledge.write("profile", "# P\n\n## Identity & contact\n\n- First name: Liam\n- Email: liam@example.com\n")
    resume = tmp_path / "Liam_Resume.pdf"
    resume.write_bytes(b"%PDF-1.4 test")
    sent = []
    monkeypatch.setattr(notify, "_channels", lambda: [type("C", (), {"send": lambda self, t: sent.append(t)})()])

    calls = {"n": 0}

    def fake_json(prompt, schema, **kw):
        calls["n"] += 1
        assert "password" not in str(prompt).lower()
        table = {"first_name": "Liam", "email": "liam@example.com", "auth": "Yes", "sponsor": "Yes", "consent": "true"}
        from fakes import keys_in

        return {"answers": [{"id": k, "resolved": True, "value": table[i], "basis": "profile", "confidence": "high", "new_rule": ""} for k, i in keys_in(prompt).items() if i in table]}

    monkeypatch.setattr(llm, "json", fake_json)
    with db.session() as s:
        s.add(Document(kind="resume_site", name=resume.name, path=str(resume)))
        j = Job(source="manual", source_id="fx1", company="Acme", title="SWE Co-op", apply_url="https://fixture.local/job/1",
                channel="employer site", score=9.0, deadline="2027-01-01 23:59", jd_text="x" * 300)
        s.add(j)
        s.flush()
        jid = j.id
    return {"job_id": jid, "driver": drv, "sent": sent, "calls": calls}


def _status(job_id):
    from autoapply import db
    from autoapply.models import Job

    with db.session() as s:
        a = s.get(Job, job_id).application
        return a.status, dict(a.evidence or {}), a.last_event


def test_draft_review_execute(pipeline):
    from autoapply import db, drafts, tasks
    from autoapply.models import AnswerCache, DriverStat, Todo

    did = drafts.build(pipeline["job_id"])
    d = drafts.get(did)
    assert d["application"]["status"] == "draft_ready" and not d["unresolved"]
    by = {a["id"]: a for a in d["answers"]}
    assert by["auth"]["value"] == "Yes" and by["resume"]["value"].endswith("Liam_Resume.pdf")
    # sensitive questions are flagged and unconfirmed on first sight -> not auto-approvable
    assert by["sponsor"]["sensitive"] == "sponsorship" and not by["sponsor"]["sensitive_confirmed"]
    assert d["auto_approve_check"]["eligible"] is False
    assert [s["op"] for s in d["plan"]] == ["open", "fill_page", "read_back", "submit"]

    # executing an unapproved draft is refused (guard rail)
    from autoapply import executor

    with pytest.raises(PermissionError):
        executor.execute(d["application"]["id"], did)

    drafts.edit_answer(did, "first_name", "Alexander")
    drafts.approve(did)
    assert tasks.drain() == 1
    status, evidence, _ = _status(pipeline["job_id"])
    assert status == "submitted" and "Thank you for applying" in evidence["text"] and "REF-123" in evidence["text"]
    assert pipeline["driver"].submits == 1
    assert any("已提交" in t for t in pipeline["sent"])
    with db.session() as s:
        assert s.get(DriverStat, "fixture").consecutive_submits == 1
        cached = {(c.ats, c.question_key): c for c in s.query(AnswerCache)}
        assert cached["fixture:local", "will you require sponsorship?"].confirmed_by_user == 1      # confirmed for this employer
        assert cached["fixture", "will you require sponsorship?"].confirmed_by_user == 0            # offered to another, confirmed for none
        assert s.query(Todo).filter_by(status="open").count() == 0

    # executing again must not submit twice
    out = executor.execute(d["application"]["id"], did)
    assert out["note"] == "already submitted" and pipeline["driver"].submits == 1


def test_second_application_uses_cache_and_auto_approves(pipeline):
    from autoapply import db, drafts, tasks
    from autoapply.models import Job

    drafts.approve(drafts.build(pipeline["job_id"]))
    tasks.drain()
    for _ in range(2):  # reach the "driver proven" threshold
        with db.session() as s:
            from autoapply.models import DriverStat

            s.get(DriverStat, "fixture").consecutive_submits += 1
    db.set_setting("auto_approve.enabled", True)
    db.set_setting("auto_approve.per_ats", {"fixture": True})
    with db.session() as s:
        j = Job(source="manual", source_id="fx2", company="Beta", title="Backend Co-op", apply_url="https://fixture.local/job/2",
                channel="employer site", score=9.5, deadline="2027-01-01 23:59", jd_text="y" * 300)
        s.add(j)
        s.flush()
        jid2 = j.id
    before = pipeline["calls"]["n"]
    did = drafts.build(jid2)
    assert pipeline["calls"]["n"] == before  # every answer came from the cache: no LLM call
    d = drafts.get(did)
    assert d["auto_approve_check"]["eligible"] is True, d["auto_approve_check"]
    assert d["review_status"] == "approved"
    tasks.drain()
    status, _, _ = _status(jid2)
    assert status == "submitted"
    with db.session() as s:
        assert s.get(Job, jid2).application.auto_approved == 1
    assert any("自动通过" in t for t in pipeline["sent"])


def test_auto_approve_blocked_by_low_score(pipeline):
    from autoapply import db, drafts, tasks
    from autoapply.models import DriverStat, Job

    drafts.approve(drafts.build(pipeline["job_id"]))
    tasks.drain()
    with db.session() as s:
        s.get(DriverStat, "fixture").consecutive_submits = 5
        j = Job(source="manual", source_id="fx3", company="C", title="T", apply_url="https://fixture.local/job/3", channel="employer site", score=7.0, jd_text="z" * 300)
        s.add(j)
        s.flush()
        jid = j.id
    db.set_setting("auto_approve.enabled", True)
    db.set_setting("auto_approve.per_ats", {"fixture": True})
    d = drafts.get(drafts.build(jid))
    assert d["review_status"] == "pending" and d["auto_approve_check"]["failed"] == ["score_ok"]


def test_verify_failure_blocks_submit(pipeline, monkeypatch):
    """A value that differs from the draft is never submitted automatically. The run is not thrown away either:
    it is repeated in a visible window, and the difference is named on the card for the user."""
    from autoapply import drafts, executor, tasks

    handed = {}

    def window_closed_without_submitting(driver, page, title, app_id, draft_id=None, **kw):
        handed.update(kw)
        return {"status": "ready_to_submit", "error": "window closed"}

    monkeypatch.setattr(executor, "_wait_for_manual_submit", window_closed_without_submitting)
    did = drafts.build(pipeline["job_id"])
    drafts.approve(did)
    pipeline["driver"].corrupt = "email"  # the site changes a value after we fill it
    tasks.drain()
    status, _, _ = _status(pipeline["job_id"])
    assert status == "ready_to_submit"
    assert pipeline["driver"].submits == 0  # never clicked Submit
    left = handed["leftovers"]
    assert [x["kind"] for x in left] == ["fix"] and "mail" in left[0]["label"].lower() and "页面上现在是" in left[0]["why"]


def test_drift_builds_delta_draft(pipeline, tmp_path):
    from autoapply import db, drafts, tasks
    from autoapply.ats.base import Question
    from autoapply.models import Draft, Job, Todo

    did = drafts.build(pipeline["job_id"])
    changed = tmp_path / "form_changed.html"
    changed.write_text(
        FORM.read_text(encoding="utf-8").replace("<!--EXTRA-->", '<label for="salary">Salary expectation</label><input id="salary" required>'),
        encoding="utf-8",
    )
    pipeline["driver"].form_path = changed
    pipeline["driver"].extra = [Question("salary", "Salary expectation", "text", True)]
    drafts.edit_answer(did, "first_name", "Alexander")  # a user edit that must survive the re-read
    drafts.approve(did)
    tasks.drain()  # execute -> drift -> new reconnaissance -> delta draft
    status, _, _ = _status(pipeline["job_id"])
    assert pipeline["driver"].submits == 0
    assert status == "needs_input"  # the new required question has no answer yet
    with db.session() as s:
        app = s.get(Job, pipeline["job_id"]).application
        new = max(app.drafts, key=lambda d: d.version)
        assert new.id != did and new.review_status == "pending"
        assert s.get(Draft, did).review_status == "superseded"
        new_id = new.id
    d = drafts.get(new_id)
    by = {a["id"]: a for a in d["answers"]}
    assert by["salary"]["delta"] == "new" and [u["id"] for u in d["unresolved"]] == ["salary"]
    assert by["first_name"]["value"] == "Alexander" and by["first_name"]["delta"] == "" and "carried over" in by["first_name"]["basis"]
    assert by["sponsor"]["sensitive_confirmed"]  # approved once already
    assert d["auto_approve_check"]["eligible"] is False
    assert any("changed since" in n for n in d["notes"])
    with db.session() as s:
        assert s.query(Todo).filter_by(kind="answer", status="open").count() == 1


def test_unresolved_question_blocks_approval(pipeline, monkeypatch):
    from autoapply import drafts, llm

    def partial(prompt, schema, **kw):
        from fakes import keys_in

        say = {
            "first_name": {"resolved": True, "value": "Liam", "basis": "p", "confidence": "high", "new_rule": ""},
            "email": {"resolved": True, "value": "liam@example.com", "basis": "p", "confidence": "high", "new_rule": ""},
            "auth": {"resolved": True, "value": "Maybe", "basis": "guess", "confidence": "low", "new_rule": ""},  # not an option
            "sponsor": {"resolved": False, "value": "", "basis": "profile is silent", "confidence": "low", "new_rule": ""},
            "consent": {"resolved": True, "value": "true", "basis": "consent rule", "confidence": "high", "new_rule": ""},
        }
        return {"answers": [{"id": k, **say[i]} for k, i in keys_in(prompt).items()]}

    monkeypatch.setattr(llm, "json", partial)
    did = drafts.build(pipeline["job_id"])
    d = drafts.get(did)
    assert d["application"]["status"] == "needs_input"
    assert sorted(u["id"] for u in d["unresolved"]) == ["auth", "sponsor"]  # invalid option is rejected, not passed through
    with pytest.raises(ValueError):
        drafts.approve(did)
    drafts.edit_answer(did, "auth", "Yes")
    drafts.edit_answer(did, "sponsor", "Yes")
    assert drafts.get(did)["application"]["status"] == "draft_ready"
    drafts.approve(did)


def test_a_run_keeps_where_its_time_went_and_is_looked_at_afterwards(pipeline):
    from autoapply import db, drafts, tasks, timing
    from autoapply.models import Run

    did = drafts.build(pipeline["job_id"])
    drafts.approve(did)
    assert tasks.drain() >= 1
    with db.session() as s:
        r = s.query(Run).filter_by(kind="execute").order_by(Run.id.desc()).first()
        spans, site, in_force = list(r.spans or []), r.site, r.learned
    kinds = {sp["k"] for sp in spans}
    assert "driver" in kinds and {"step:fill_page", "step:read_back", "step:submit"} <= {sp["n"] for sp in spans} and timing.working_ms(spans) > 0
    assert site and in_force == []                                                                # nothing learned yet: nothing in force
    assert not timing.active()                                                                    # the recorder ended with the run
def test_an_answer_can_be_changed_after_approval_until_the_application_has_gone_out(pipeline):
    """A wrong answer noticed after approving - or after a run failed on it - is changed in place: the draft stays
    approved, and the next run fills in what it says now."""
    from fastapi.testclient import TestClient

    from autoapply import db, drafts, tasks
    from autoapply.api.main import app
    from autoapply.models import Application, Draft

    did = drafts.build(pipeline["job_id"])
    drafts.edit_answer(did, "first_name", "Alexandre")
    with db.session() as s:                              # approved, and the run did not get through
        d = s.get(Draft, did)
        d.review_status, d.application.status = "approved", "failed"
        app_id = d.application_id
    c = TestClient(app)
    got = c.get(f"/api/drafts/{did}").json()
    assert got["locked"] == "" and got["review_status"] == "approved"
    r = c.patch(f"/api/drafts/{did}/answers/first_name", json={"value": "Alexander"})
    assert r.status_code == 200 and r.json()["review_status"] == "approved"
    by = {a["id"]: a for a in r.json()["answers"]}
    assert by["first_name"]["value"] == "Alexander" and by["first_name"]["basis"] == "edited by user"
    note = r.json()["comments"][-1]                     # what was changed after the approval is kept with the draft
    assert note["comment"].startswith("批准之后修改了") and note["result"] == "Alexandre → Alexander"
    # the approval had cached the old value as the applicant's own for the next form of this system: the correction replaces it
    from autoapply import answers as ans
    from autoapply.ats.base import Question

    with db.session() as s:
        d = s.get(Draft, did)
        ats, tenant, first = d.schema["ats"], d.schema["tenant"], next(a for a in d.answers if a["id"] == "first_name")
    q = Question(id="first_name", label=first["label"], type=first["type"], options=first.get("options") or [])
    ans.cache_put(ats, q, "Alexandre", "approved", confirmed=True, tenant=tenant)       # (as approve() left it)
    assert c.patch(f"/api/drafts/{did}/answers/first_name", json={"value": "Alexander"}).status_code == 200
    assert ans._cache_get(ats, q, tenant).answer == "Alexander" and ans._cache_get(ats, q, tenant).confirmed_by_user == 1
    assert ans._cache_get(ats, q, "another-employer").answer == "Alexander"          # what another employer's form is offered is the corrected one too
    assert c.patch(f"/api/drafts/{did}/answers/first_name", json={"value": ""}).status_code == 200
    assert ans._cache_get(ats, q, tenant) is None and ans._cache_get(ats, q) is None   # cleared: nothing is left to reuse, here or elsewhere
    assert c.patch(f"/api/drafts/{did}/answers/first_name", json={"value": "Alexander"}).status_code == 200
    # the next run fills in what the draft says now
    assert c.post(f"/api/drafts/{did}/execute").status_code == 200 and tasks.drain() == 1
    assert _status(pipeline["job_id"])[0] == "submitted" and pipeline["driver"].submits == 1      # read back against the draft before it was sent
    from autoapply import lifecycle

    # (the scene is set back by hand, the way only a correction by the applicant may: a sent application does not go back by itself)
    lifecycle.move(app_id, "failed", source="user", back=True)

    # while a run fills the form from it, and once the application is out, it is closed - and says why
    for status, word in (("executing", "正在"), ("submitted", "已经发出去")):
        lifecycle.move(app_id, status, source="user", back=True)
        assert word in c.get(f"/api/drafts/{did}").json()["locked"]
        refused = c.patch(f"/api/drafts/{did}/answers/first_name", json={"value": "Someone else"})
        assert refused.status_code == 409 and word in refused.json()["detail"]
    with db.session() as s:
        assert next(a["value"] for a in s.get(Draft, did).answers if a["id"] == "first_name") == "Alexander"
        lifecycle.move(s.get(Application, app_id), "failed", source="user", back=True)
        s.get(Draft, did).review_status = "superseded"                                   # an old version
    assert c.patch(f"/api/drafts/{did}/answers/first_name", json={"value": "x"}).status_code == 409
    assert c.patch("/api/drafts/999999/answers/first_name", json={"value": "x"}).status_code == 404
