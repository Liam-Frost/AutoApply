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
    from autoapply import tasks

    seen = []
    monkeypatch.setattr(tasks, "enqueue", lambda kind, **kw: seen.append((kind, kw["ref"])))
    monkeypatch.setattr(tasks, "_sched", None)
    tasks.enqueue_later_for_real("mail", ref="confirm:1", minutes=0.001)
    import time

    time.sleep(0.5)
    assert seen == [("mail", "confirm:1")]
