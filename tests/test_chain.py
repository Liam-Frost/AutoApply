"""Every application that is not finished has work in the queue or a card with the applicant (chain.py).

Each of these is a way an application was found standing with nothing to move it, on a real installation.
"""
from __future__ import annotations

import pytest

from autoapply import db

from test_agent_work import READY, _app, _state, agent  # noqa: F401  (the pipeline with the agent's run replaced)


def _cards():
    from autoapply.models import Todo

    with db.session() as s:
        return [(t.kind, t.ref) for t in s.query(Todo).filter_by(status="open").order_by(Todo.id)]


def test_an_application_whose_task_failed_is_tried_again_and_then_says_so_on_a_card(agent):  # noqa: F811
    """"Being prepared", for ever: the task behind it had failed, and nothing said so or tried again."""
    from autoapply import chain, tasks
    from autoapply.models import Application, Task

    def boom():
        raise RuntimeError("This account's browser is already in use")

    agent.ends.extend({"during": boom} for _ in range(12))
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1
    with db.session() as s:      # an error is not the application's: it is tried again later, and until then nothing is wrong
        later = s.query(Task).filter_by(status="queued").one()
        assert later.due_at is not None and later.payload["_error_retries"] == 1
    assert _state(agent.job)[0] == "recon" and chain.look() == []
    runs = 1
    for _ in range(10):          # (time passes: what was put off comes due)
        with db.session() as s:
            s.query(Task).filter_by(status="queued").update({"due_at": None})
        n = tasks.drain()
        runs += n
        if not n:
            break
    # twice more by the queue, once more by the chain (with its own two tries) - and then it says so, on a card
    assert runs == 6
    status, _, cards, _ = _state(agent.job)
    assert status == "failed" and cards == [("failed", f"application:{_app(agent.job)}")]
    with db.session() as s:
        assert "browser" in s.get(Application, _app(agent.job)).last_event
    assert chain.look() == []


def test_a_card_that_work_waits_for_is_put_off_not_closed_and_one_that_is_gone_is_made_again(agent):  # noqa: F811
    """"Waiting for you", with nothing in the list of things to do: the card had been closed with "not now"."""
    from autoapply import chain, tasks
    from autoapply.api.main import todo_done
    from autoapply.models import Task, Todo

    agent.ends.append({"outcome": "needs_you", "record": {"summary": "The site's sign-in has no stored password.", "asked": []},
                       "journal": [{"kind": "needs_applicant", "why": "sign in", "url": "https://login.acme.example/"}]})
    tid = tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1
    ref = "account:generic:careers.acme.example"
    with db.session() as s:
        card = s.query(Todo).filter_by(ref=ref, status="open").one().id
    assert "snoozed_until" in todo_done(card, {"status": "dismissed", "resume": False})        # "not now": tomorrow, not never
    with db.session() as s:
        assert s.get(Todo, card).status == "open" and s.get(Todo, card).snoozed_until is not None
    assert chain.look() == []
    # an installation where it was closed: the need is said again, and the task waits for that card
    with db.session() as s:
        s.get(Todo, card).status = "dismissed"
    assert [f["what"] for f in chain.look()] == ["waits_for_nothing"]
    chain.mend()
    app_id = _app(agent.job)
    assert _cards() == [("resume", f"application:{app_id}:resume")] and chain.look() == []
    with db.session() as s:
        assert s.get(Task, tid).payload["waits_for"] == f"application:{app_id}:resume"
        again = s.query(Todo).filter_by(kind="resume", status="open").one().id
    agent.ends.append(READY)
    todo_done(again, {})
    assert tasks.drain() == 1 and _state(agent.job)[0] == "draft_ready"


def test_what_stands_with_nothing_to_press_gets_something_and_what_is_over_keeps_no_card(agent):  # noqa: F811
    from autoapply import chain, lifecycle, notify, tasks
    from autoapply.models import Application, Job, Outgoing, Task, Todo, now

    db.set_setting("submit.policy", "approve")
    agent.ends.append(READY)
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1
    app_id = _app(agent.job)

    def stand(status, old=True):
        from datetime import timedelta

        with db.session() as s:
            a = s.get(Application, app_id)
            lifecycle.move(a, status, source="recover", back=True)
            s.query(Todo).filter_by(status="open").update({"status": "dismissed"})
            s.query(Task).filter(Task.status.in_(("queued", "waiting_human"))).update({"status": "done"})
        if old:
            with db.session() as s:
                s.query(Application).filter_by(id=app_id).update({"updated_at": now() - timedelta(minutes=5)})

    stand("failed")                                    # failed, and the card was closed: nothing to press
    assert [f["what"] for f in chain.look()] == ["nothing_to_press"]
    chain.mend()
    assert _cards() == [("failed", f"application:{app_id}")]
    stand("recon", old=False)                          # in the middle of being changed by a run that is starting: left alone
    assert chain.look() == []
    stand("approved")                                  # approved, and nothing queued to send it
    chain.mend()
    with db.session() as s:
        assert s.query(Task).filter_by(kind="apply", status="queued").count() == 1
    stand("submitted")                                 # sent: a card about preparing it has nothing left to say
    notify.add_todo("failed", "x", ref=f"application:{app_id}", payload={"application_id": app_id, "job_id": agent.job}, push=False)
    notify.add_todo("code", "x", ref=f"application:{app_id}:code", payload={"application_id": app_id, "job_id": agent.job}, push=False)
    assert sorted(f["what"] for f in chain.look()) == ["card_of_a_finished_application", "card_without_run"]
    chain.mend()
    assert _cards() == [] and chain.look() == []
    # a mail that was being sent when the program stopped: not known to have gone, and said so
    from datetime import timedelta

    with db.session() as s:
        s.add(Outgoing(application_id=app_id, to="a@b.example", subject="s", body="b", status="sending", created_at=now() - timedelta(minutes=30)))
    chain.mend()
    with db.session() as s:
        o = s.query(Outgoing).one()
        assert o.status == "failed" and "已发送" in o.error
    with db.session() as s:
        assert s.get(Job, agent.job) is not None


def test_not_applying_after_all_takes_a_failed_application_out_of_what_is_under_way(agent):  # noqa: F811
    """A failed application stayed "under way" after its card was closed with "not applying, close"."""
    from autoapply import chain, lifecycle, tasks
    from autoapply.models import Job

    agent.ends.append({"outcome": "cannot", "record": {"summary": "The form cannot be reached.", "asked": []}})
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1 and _state(agent.job)[0] == "failed"
    with db.session() as s:
        assert lifecycle.not_applying(s.get(Job, agent.job)) is True
    chain.mend()
    assert _state(agent.job)[0] == "withdrawn" and _cards() == [] and chain.look() == []
