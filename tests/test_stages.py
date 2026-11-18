"""The single stage shown per job in the jobs table."""


def test_stage_mapping():
    from autoapply.stages import STAGES, stage

    far, past = "2099-01-01 23:59", "2020-01-01 23:59"
    assert stage("scored", True, far, None) == "not_applied"
    assert stage("queued", True, "", None) == "not_applied"  # "queued" is internal, not a state the user cares about
    assert stage("scored", True, past, None) == "expired"
    assert stage("skipped", True, far, None) == "skipped"
    assert stage("scored", True, far, "withdrawn") == "skipped"
    assert stage("offline", False, far, None) == "offline"
    assert stage("scored", True, far, "draft_ready") == "draft_ready"
    assert stage("scored", True, far, "needs_input") == "needs_input"
    assert stage("scored", True, far, "executing") == "applying"
    assert stage("scored", True, far, "ready_to_submit") == "needs_you"
    assert stage("scored", True, far, "failed") == "failed"
    assert stage("scored", True, past, "submitted") == "submitted"
    assert stage("scored", True, far, "confirmed") == "confirmed"
    # an application that was sent keeps its stage after the posting is taken down
    assert stage("offline", False, past, "interview") == "interview"
    assert stage("offline", False, past, "rejected") == "rejected"
    # a draft for a posting that has since gone offline is moot
    assert stage("offline", False, far, "draft_ready") == "offline"
    for app in ("recon", "revising", "approved", "drifted", "needs_human", "assessment", "offer"):
        assert stage("scored", True, far, app) in STAGES


def test_confirmation_check_is_scheduled_after_submit(app_env, monkeypatch):
    """The look for the confirmation mail some minutes after a submission is a task in the queue, waiting for its time."""
    from datetime import timedelta

    from autoapply import db, tasks
    from autoapply.models import Task, now

    ran = []
    monkeypatch.setitem(tasks._handlers, "mail", lambda t: ran.append(t.ref) or {})
    tid = tasks.enqueue_later("mail", ref="confirm:1", minutes=5)
    assert tasks.drain() == 0 and ran == []                  # not before its time
    with db.session() as s:
        s.get(Task, tid).due_at = now() - timedelta(seconds=1)
    assert tasks.drain() == 1 and ran == ["confirm:1"]


def test_a_draft_that_is_sent_back_leaves_a_posting_that_is_not_applied_for(app_env):
    """"Not now" on a draft sent it back: the draft was closed and could not be approved any more. And an application
    whose only draft was sent back stayed at "a draft is waiting for you", with no draft to open."""
    from autoapply import db, drafts, stages
    from autoapply.models import Application, Draft, Job

    with db.session() as s:
        ids = []
        for n in range(3):
            j = Job(source="manual", source_id=f"s{n}", company=f"Co{n}", title="Analyst", status="queued", online=1, apply_url="https://x.example/j")
            s.add(j)
            s.flush()
            a = Application(job_id=j.id, status="draft_ready")
            s.add(a)
            s.flush()
            d = Draft(application_id=a.id, version=1, schema={}, answers=[], unresolved=[], materials=[], plan=[], review_status="pending")
            s.add(d)
            s.flush()
            ids.append((j.id, a.id, d.id))
        # the second application has an earlier draft that was approved and a newer one waiting
        s.add(Draft(application_id=ids[1][1], version=2, schema={}, answers=[], unresolved=[{"id": "q"}], materials=[], plan=[], review_status="pending"))

    def stand(k):
        with db.session() as s:
            a = s.get(Application, ids[k][1])
            j = s.get(Job, ids[k][0])
            return a.status, stages.stage(j.status, bool(j.online), j.deadline or "", a.status), a.last_event or ""

    drafts.reject(ids[0][2])                       # sent back, and nothing else is waiting
    status, stage, said = stand(0)
    assert (status, stage) == ("returned", "not_applied") and "重新生成草案" in said
    drafts.reject(ids[1][2])                       # sent back, and another version still waits (with a question open)
    assert stand(1)[:2] == ("needs_input", "needs_input")
    drafts.reject(ids[2][2], withdraw=True)        # "I am not applying for this one"
    assert stand(2)[:2] == ("withdrawn", "skipped")
    with db.session() as s:
        assert [s.get(Draft, i[2]).review_status for i in ids] == ["rejected"] * 3
