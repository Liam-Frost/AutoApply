"""Submit was pressed and no page said "received".

That used to be one of two things, both wrong: a failed run - with a card whose main button was "fill in and submit
again" - or "filled, not confirmed", the same card with a flag that only one path set. Whether the form was sent is a
fact about the run; the application then stands at "outcome of the submission not known" until a mail or the applicant
settles it, and is not filled in again by anything else.
"""
import pytest

from autoapply import db

from test_pipeline import pipeline  # noqa: F401  (the fixture: a real form in a real browser)


def _state(job_id):
    from autoapply.models import Job, Todo

    with db.session() as s:
        a = s.get(Job, job_id).application
        cards = [(t.kind, t.title, t.payload) for t in s.query(Todo).filter_by(status="open").order_by(Todo.id)]
        return a.id, a.status, cards


def test_pressed_by_the_program_and_no_page_says_received(pipeline, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from autoapply import drafts, executor, mail, tasks
    from autoapply.api.main import app
    from autoapply.models import UNKNOWN, Task

    monkeypatch.setattr(pipeline["driver"], "confirmation", lambda page: None)      # a page worded in no way the program knows
    monkeypatch.setattr(executor, "_judge", lambda seen: None)
    did = drafts.build(pipeline["job_id"])
    drafts.approve(did)
    tasks.drain()
    app_id, status, cards = _state(pipeline["job_id"])
    assert status == UNKNOWN and pipeline["driver"].submits == 1
    assert [(k, t) for k, t, _ in cards] == [("submit", "Acme · SWE Co-op：提交结果待确认")] and cards[0][2] == {"draft_id": did, "application_id": app_id}
    assert any("提交结果待确认" in t for t in pipeline["sent"]) and not any("申请没有提交" in t for t in pipeline["sent"])
    c = TestClient(app)
    # the card says where the application stands; what it offers follows from that
    assert [r["application"] for r in c.get("/api/todos").json()] == [{"id": app_id, "status": UNKNOWN}]
    # nothing fills the form in again by itself: not a stray task, not "run again" without the applicant's word
    assert executor.execute(app_id, did)["note"] == "waiting for the outcome of a submission" and pipeline["driver"].submits == 1
    assert c.post(f"/api/drafts/{did}/execute", json={}).status_code == 409
    # "look in the mailbox now" is a mail pass, now
    assert c.post(f"/api/applications/{app_id}/check-mail").status_code == 200
    with db.session() as s:
        assert s.query(Task).filter_by(kind="mail", status="queued").count() == 1
    # the employer's confirmation settles it - it is not "too early to believe" for a form the program filled and sent
    assert mail._record(app_id, "confirmation", "we have received your application", None, "m1")[:2] == (1, False)
    assert _state(pipeline["job_id"])[1:] == ("confirmed", [])


def test_the_applicants_word_settles_it_either_way(pipeline, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from autoapply import drafts, executor, lifecycle, tasks
    from autoapply.api.main import app
    from autoapply.models import UNKNOWN

    did = drafts.build(pipeline["job_id"])
    drafts.approve(did)
    with db.session() as s:
        from autoapply.models import Job

        app_id = s.get(Job, pipeline["job_id"]).application.id
    c = TestClient(app)
    lifecycle.move(app_id, UNKNOWN, source="run")
    # "it did not go through": only then is it filled in again - and this time the page says so
    assert c.post(f"/api/drafts/{did}/execute", json={"not_submitted": True}).status_code == 200
    tasks.drain()
    assert _state(pipeline["job_id"])[1] == "submitted" and pipeline["driver"].submits == 1
    # "I did submit it"
    lifecycle.move(app_id, UNKNOWN, source="user", back=True)
    assert c.post(f"/api/applications/{app_id}/mark-submitted").status_code == 200 and _state(pipeline["job_id"])[1] == "submitted"


def test_a_form_that_answers_the_click_with_complaints_was_not_sent(pipeline, monkeypatch):  # noqa: F811
    from autoapply import drafts, executor, tasks

    monkeypatch.setattr(pipeline["driver"], "confirmation", lambda page: None)
    monkeypatch.setattr(pipeline["driver"], "form_errors", lambda page: ["E-mail address is not valid"])
    monkeypatch.setattr(executor, "_judge", lambda seen: None)
    did = drafts.build(pipeline["job_id"])
    drafts.approve(did)
    tasks.drain()
    _, status, cards = _state(pipeline["job_id"])
    assert status == "failed" and [k for k, _, _ in cards] == ["failed"]           # known not to be sent: this one can be done again
    assert "did not accept the submission" in (cards[0][2].get("driver_error") or {}).get("message", "")


@pytest.mark.parametrize("presses", [True, False])
def test_in_the_applicants_window_it_is_seen_whether_submit_was_pressed(pipeline, monkeypatch, presses):  # noqa: F811
    """The window closes without a page that says "received". Pressed: the outcome is not known. Not pressed: the form is
    filled and waits - and opening the window again is the right thing to offer."""
    from autoapply import drafts, executor, submitwatch, tasks
    from autoapply.models import UNKNOWN

    db.set_setting("policy.default", "manual")
    monkeypatch.setattr(executor, "_judge", lambda seen: None)
    monkeypatch.setattr(pipeline["driver"], "confirmation", lambda page: None)
    real, calls = submitwatch.seen, {"n": 0}

    def applicant(page):
        calls["n"] += 1
        if calls["n"] == 1 and presses:
            # the site takes the form and shows a spinner; nothing that says "received" ever comes
            page.evaluate("""() => document.addEventListener('submit', (ev) => { ev.preventDefault(); ev.stopImmediatePropagation();
                             document.querySelector('h1').textContent = 'Processing'; }, true)""")
            page.get_by_role("button", name="Submit application").click()
        got = real(page)
        if calls["n"] == 2:
            page.close()
        return got

    monkeypatch.setattr(submitwatch, "seen", applicant)
    monkeypatch.setattr(executor, "_wait_for_manual_submit", executor.wait_for_the_applicant)      # the real window; "applicant" above is who sits at it
    did = drafts.build(pipeline["job_id"])
    drafts.approve(did)
    tasks.drain()
    _, status, cards = _state(pipeline["job_id"])
    if presses:
        assert status == UNKNOWN and [(k, t.split("：")[1]) for k, t, _ in cards] == [("submit", "提交结果待确认")]
    else:
        assert status == "ready_to_submit" and [(k, t.split("：")[1]) for k, t, _ in cards] == [("failed", "填好了，还没有提交")]
        assert "maybe_submitted" not in cards[0][2]


def test_what_older_versions_filed_as_failed_is_re_filed(app_env):
    from autoapply import lifecycle
    from autoapply.models import UNKNOWN, Application, Draft, Job, Todo

    with db.session() as s:
        rows = []
        for i, (status, body, payload) in enumerate([("failed", "no confirmation after submit", {}), ("ready_to_submit", "window closed", {"maybe_submitted": True}),
                                                     ("failed", "Locator.click: Timeout", {}), ("confirmed", "no confirmation after submit", {})]):
            j = Job(source="manual", source_id=f"u{i}", company=f"Co{i}", title="Intern", apply_url=f"https://x.test/{i}", channel="employer site", jd_text="x" * 300)
            s.add(j)
            s.flush()
            a = Application(job_id=j.id, status=status)
            s.add(a)
            s.flush()
            d = Draft(application_id=a.id, version=1, review_status="approved", schema={}, answers=[])
            s.add(d)
            s.flush()
            s.add(Todo(kind="failed", ref=f"application:{a.id}", title=f"Co{i}：执行失败", body=body, payload={"draft_id": d.id, "application_id": a.id, **payload}))
            rows.append(a.id)
    assert lifecycle.unknown_from_before() == rows[:2]
    with db.session() as s:
        assert [s.get(Application, i).status for i in rows] == [UNKNOWN, UNKNOWN, "failed", "confirmed"]
        open_cards = sorted((t.kind, t.ref) for t in s.query(Todo).filter_by(status="open"))
    assert open_cards == sorted([("submit", f"application:{rows[0]}"), ("submit", f"application:{rows[1]}"), ("failed", f"application:{rows[2]}"), ("failed", f"application:{rows[3]}")])
    assert lifecycle.unknown_from_before() == []          # once
