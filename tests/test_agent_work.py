"""The program's side of the application agent: which run it starts, and what a run's outcome becomes.

What the agent does on a page is not tested here (that is measured on the evaluation forms, eval/). This is the part
the program is in charge of: the mode a run is given, the record and the cards it leaves, an application marked as
sent only with its evidence, an outcome that is not known, the budget of one application, the same place again.
"""
from __future__ import annotations

import contextlib
import json

import pytest

from autoapply import db


@pytest.fixture()
def agent(app_env, monkeypatch):
    """The agent pipeline, with the agent's run replaced: each test says how the run ends."""
    from autoapply import browser, handlers  # noqa: F401  (the handlers register themselves)
    from autoapply.agent import run, work
    from autoapply.models import Job

    monkeypatch.setattr(browser, "open_page", lambda *a, **k: contextlib.nullcontext(object()))
    seen: list[dict] = []
    ends: list = []

    def apply(page, posting, applicant, folder, *, mode="prepare", answers=None, job_id=None, record=None, budget=None, on_hand=None):
        seen.append({"mode": mode, "answers": answers, "record": record, "budget": budget, "files": dict(applicant.files)})
        folder.mkdir(parents=True, exist_ok=True)
        end = ends.pop(0)
        if end.get("during"):                              # something happens while the run is working
            end["during"]()
        if end.get("hands") and on_hand is not None:      # the run gives the window to the applicant
            on_hand()
            end["cards_then"] = [(t.kind, t.ref) for t in db.session().__enter__().query(__import__("autoapply.models", fromlist=["Todo"]).Todo).filter_by(status="open")]
        with open(folder / "journal.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": "2026-11-19T10:00:00", "kind": "run", "mode": mode}) + "\n")
            for line in end.get("journal", []):
                f.write(json.dumps({"at": "2026-11-19T10:00:01", **line}) + "\n")
            if end.get("outcome"):
                f.write(json.dumps({"at": "2026-11-19T10:00:02", "kind": "report", "outcome": end["outcome"], "not_sent": end.get("not_sent", "")}) + "\n")
        return run.Result(outcome=end.get("outcome", ""), record=end.get("record", {}), stopped=end.get("stopped", "end_turn"), steps=end.get("steps", 30), seconds=end.get("seconds", 100.0))

    monkeypatch.setattr(run, "apply", apply)
    with db.session() as s:
        j = Job(source="manual", source_id="a1", company="Acme", title="Backend Intern", apply_url="https://careers.acme.example/jobs/1", jd_text="x" * 300, status="queued", online=1)
        s.add(j)
        s.flush()
        job_id = j.id
    return type("A", (), {"job": job_id, "seen": seen, "ends": ends, "work": work})()


def _state(job_id):
    from autoapply.models import Job, Todo

    with db.session() as s:
        app = s.get(Job, job_id).application
        return (app.status, [(d.review_status, len(d.answers), len(d.unresolved)) for d in app.drafts], [(t.kind, t.ref) for t in s.query(Todo).filter_by(status="open").order_by(Todo.id)], dict(app.evidence or {}))


READY = {"outcome": "ready", "record": {"summary": "Everything is in; one press from sending.", "url": "https://careers.acme.example/apply/review",
                                         "answers": [{"question": "First name", "entered": "Alex", "from": "profile: Name", "sure": "yes"},
                                                     {"question": "Degree", "entered": "Bachelor of Engineering", "from": "BASc mapped to the nearest entry", "sure": "fairly"}],
                                         "files": [{"field": "Résumé", "file": "resume.pdf"}], "open": [], "asked": []}}
SENT = {"outcome": "submitted", "record": {"summary": "Sent.", "confirmation": {"words": "Thank you, your application was received. Reference AC-1", "url": "https://careers.acme.example/done", "ties_to_posting": "Backend Intern, reference AC-1"}}}


def test_the_applicants_policy_decides_what_a_run_may_do(agent):
    from autoapply import drafts, tasks

    for policy, mode in (("approve", "prepare"), ("auto", "auto"), ("hand_over", "hand_over")):
        db.set_setting("submit.policy", policy)
        agent.ends.append(READY)
        tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job}, dedupe=False)
        assert tasks.drain() == 1 and agent.seen[-1]["mode"] == mode
    status, records, cards, _ = _state(agent.job)
    assert status == "draft_ready" and records == [("superseded", 2, 0), ("superseded", 2, 0), ("pending", 2, 0)] and cards == []
    # the record is what the review page shows: a row per question, with what was entered and where it comes from
    from autoapply.models import Job

    with db.session() as s:
        d = s.get(Job, agent.job).application.drafts[-1]
        did = d.id
        assert [(a["label"], a["value"], a["basis"], a["confidence"]) for a in d.answers] == [("First name", "Alex", "profile: Name", "high"), ("Degree", "Bachelor of Engineering", "BASc mapped to the nearest entry", "medium")]
        assert d.materials[0]["name"] == "resume.pdf" and d.schema["extra"]["agent"] is True
    # approved: the next run is given the approved record and told to send - whatever the policy
    db.set_setting("submit.policy", "approve")
    drafts.edit_answer(did, "a2", "Bachelor's Degree - Other")
    drafts.approve(did)
    agent.ends.append(SENT)
    assert tasks.drain() == 1
    last = agent.seen[-1]
    assert last["mode"] == "send" and last["answers"] == {"Degree": "Bachelor's Degree - Other"}
    assert {a["question"]: a["entered"] for a in last["record"]["answers"]}["Degree"] == "Bachelor's Degree - Other"
    status, _, cards, evidence = _state(agent.job)
    assert status == "submitted" and cards == [] and "Reference AC-1" in evidence["text"] and evidence["ties_to_posting"] == "Backend Intern, reference AC-1"


def test_a_question_only_the_applicant_can_answer_is_a_card_and_their_answer_goes_into_the_next_run(agent):
    from autoapply import drafts, tasks
    from autoapply.models import Job

    db.set_setting("submit.policy", "auto")
    asked = {"question": "What is the earliest date you can start?", "about": "job", "options": [], "why": "Step 2, required"}
    agent.ends.append({"outcome": "needs_you", "record": {"summary": "One question is open; not sent.", "url": "https://careers.acme.example/apply/2", "answers": READY["record"]["answers"], "files": [], "open": ["start date"], "asked": [asked]}})
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1
    status, records, cards, _ = _state(agent.job)
    assert status == "needs_input" and records == [("pending", 3, 1)] and [k for k, _ in cards] == ["answer"]
    with db.session() as s:
        d = s.get(Job, agent.job).application.drafts[-1]
        did, row = d.id, d.unresolved[0]
        assert (row["label"], row["source"], row["about"], row["required"]) == ("What is the earliest date you can start?", "unresolved", "job", True)
    with pytest.raises(ValueError):
        drafts.approve(did)                                   # not while a question is open
    # answered: nothing is open, and under "send when nothing is open" the agent goes on by itself
    agent.ends.append(SENT)
    drafts.edit_answer(did, row["id"], "2027-01-04")
    assert tasks.drain() == 1
    assert agent.seen[-1]["mode"] == "auto" and agent.seen[-1]["answers"] == {"What is the earliest date you can start?": "2027-01-04"}
    assert _state(agent.job)[0] == "submitted" and _state(agent.job)[2] == []


def test_a_sign_in_only_the_applicant_can_make_is_a_card_the_task_waits_for(agent):
    from autoapply import handlers, tasks
    from autoapply.models import Task

    agent.ends.append({"outcome": "needs_you", "record": {"summary": "The site asks for a code on the applicant's phone.", "asked": []},
                       "journal": [{"kind": "needs_applicant", "why": "a code on the phone", "url": "https://login.acme.example/mfa"}]})
    tid = tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1
    status, _, cards, _ = _state(agent.job)
    assert status == "needs_human" and cards == [("takeover", "account:generic:careers.acme.example")]
    with db.session() as s:
        t = s.get(Task, tid)
        assert t.status == "waiting_human" and t.payload["waits_for"] == "account:generic:careers.acme.example"
    # signed in: the same task runs again
    agent.ends.append(READY)
    assert handlers.resume_waiting("account:generic:careers.acme.example") == 1 and tasks.drain() == 1
    assert _state(agent.job)[0] == "draft_ready"


def test_a_run_cut_off_after_it_said_it_was_sending_is_an_outcome_that_is_not_known(agent):
    """The employer may have the application; pressing the button again would be the worse mistake."""
    from autoapply import tasks
    from autoapply.models import UNKNOWN, Task

    db.set_setting("submit.policy", "auto")
    agent.ends.append({"outcome": "", "stopped": "timeout", "journal": [{"kind": "sending", "button": "Submit application", "url": "https://careers.acme.example/apply/review"}]})
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1
    status, _, cards, _ = _state(agent.job)
    assert status == UNKNOWN and [k for k, _ in cards] == ["submit"]          # one card: "the outcome is not known"
    with db.session() as s:      # what is queued next is a look, in its own time - not another go at the form
        later = [t for t in s.query(Task).filter_by(status="queued", kind="apply")]
        assert len(later) == 1 and later[0].due_at is not None
        later[0].due_at = None
    # the look finds it in the site's list of applications: it is sent, with that as its evidence
    agent.ends.append({"outcome": "submitted", "record": {"summary": "Listed as Submitted.", "confirmation": {"words": "Backend Intern - Submitted", "url": "https://careers.acme.example/applications", "ties_to_posting": "the entry Backend Intern in the applicant's list"}}})
    assert tasks.drain() == 1 and agent.seen[-1]["mode"] == "verify"
    status, _, cards, evidence = _state(agent.job)
    assert status == "submitted" and evidence["text"] == "Backend Intern - Submitted"


def test_a_look_that_finds_the_application_was_not_sent_lets_it_be_worked_again(agent):
    from autoapply import tasks
    from autoapply.models import UNKNOWN, Task

    db.set_setting("submit.policy", "auto")
    agent.ends += [{"outcome": "", "stopped": "timeout", "journal": [{"kind": "sending", "button": "Submit"}]},
                   {"outcome": "ready", "record": {"summary": "The site lists it under Drafts; nothing was sent."}}, SENT]
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1 and _state(agent.job)[0] == UNKNOWN
    with db.session() as s:
        for t in s.query(Task).filter_by(status="queued", kind="apply"):
            t.due_at = None
    assert tasks.drain() == 2 and [x["mode"] for x in agent.seen] == ["auto", "verify", "auto"]
    assert _state(agent.job)[0] == "submitted"


def test_three_kinds_of_stop(agent, monkeypatch):
    """The model's allowance, this application's budget, the same place again: each has its own answer."""
    from autoapply import llm, tasks
    from autoapply.models import Task, Todo

    db.set_setting("submit.policy", "approve")
    place = {"kind": "tool", "tool": "click", "output": "clicked [3]. Now on 'Apply' at https://careers.acme.example/apply/2."}

    def due_now():
        with db.session() as s:
            for t in s.query(Task).filter_by(status="queued", kind="apply"):
                t.due_at = None

    # 1. the allowance of the model ran out: the queue's own retry, no card about the application
    agent.ends.append({"outcome": "", "stopped": "LLMUnavailable: Claude subscription usage limit reached: resets 9pm"})
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1
    with db.session() as s:
        assert [(t.kind, t.ref) for t in s.query(Todo).filter_by(status="open")] == [("config", "config:llm-limit")]
        assert s.query(Task).filter_by(status="queued").count() == 1          # tried again later, by itself
    # 2. a run used its share and did not finish: the next goes on, while the application has budget left
    agent.ends += [{"outcome": "", "stopped": "max_steps", "steps": 190, "seconds": 900.0, "journal": [place]}, {"outcome": "", "stopped": "max_steps", "steps": 190, "seconds": 900.0, "journal": [place]}]
    due_now()
    assert tasks.drain() == 1
    due_now()
    assert tasks.drain() == 1 and agent.seen[-1]["budget"]["steps"] == 400 - 30 - 190
    # ... until it is used up: it stops, and the applicant decides
    due_now()
    assert tasks.drain() == 1 and len(agent.seen) == 3                           # no run was started
    status, _, cards, _ = _state(agent.job)
    assert status == "failed" and ("failed", f"application:{_app(agent.job)}") in cards
    # they give it another budget: it goes on
    agent.ends.append(READY)
    agent.work.grant(_app(agent.job))
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1 and _state(agent.job)[0] == "draft_ready" and [c for c in _state(agent.job)[2] if c[0] != "config"] == []


def test_the_same_place_three_times_is_brought_to_the_applicant(agent):
    from autoapply import tasks
    from autoapply.models import Task

    place = {"kind": "tool", "tool": "click", "output": "clicked [3]. Now on 'Apply' at https://careers.acme.example/apply/2."}
    agent.ends += [{"outcome": "", "stopped": "end_turn", "steps": 20, "seconds": 60.0, "journal": [place]}] * 3
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    for n in range(3):
        assert tasks.drain() == 1
        with db.session() as s:
            for t in s.query(Task).filter_by(status="queued"):
                t.due_at = None
    status, _, cards, _ = _state(agent.job)
    assert status == "failed" and len(agent.seen) == 3 and [k for k, _ in cards] == ["failed"]
    with db.session() as s:
        assert s.query(Task).filter_by(status="queued").count() == 0            # not a fourth time by itself


def _app(job_id):
    from autoapply.models import Job

    with db.session() as s:
        return s.get(Job, job_id).application.id


def test_an_employer_the_applicant_sends_to_themselves_and_an_installation_from_before(agent):
    from autoapply.models import Application, Job

    assert db.get_setting("submit.policy") == "auto" and agent.work.policy("Acme") == "auto"            # a new installation: send when nothing is open
    db.set_setting("policy.manual_companies", ["acme"])
    assert agent.work.policy("Acme Robotics") == "hand_over" and agent.work.policy("Northwind") == "auto"
    # what an installation's old settings come to - an update does not switch on sending without being asked
    assert agent.work.policy_from_before() is None                                                           # nothing was ever set, nothing was ever done
    db.set_setting("onboarding.done", True)
    assert agent.work.policy_from_before() == "approve"
    db.set_setting("auto_approve.enabled", True)
    assert agent.work.policy_from_before() == "auto"
    db.set_setting("policy.default", "manual")
    assert agent.work.policy_from_before() == "hand_over"
    db.set_setting("submit.policy", "approve")
    assert agent.work.policy_from_before() is None                                                           # it has the one setting: nothing to work out


def test_the_applicant_stops_the_agent_and_it_is_not_started_again_by_itself(agent):
    from autoapply import agentbudget, tasks
    from autoapply.agent import run
    from autoapply.models import Task

    # the run's own budget carries the word: with it said, the next action is not carried out
    folder = agent.work.folder_of(7)
    folder.mkdir(parents=True)
    b = run._Budget(10, 60.0, folder)
    b.spend()
    agent.work.stop(7)
    with pytest.raises(agentbudget.Spent) as e:
        b.spend()
    assert e.value.why == "stopped" and b.used == 1
    # a run that ended so: one card, nothing queued
    agent.ends.append({"outcome": "", "stopped": "stopped", "journal": [{"kind": "log", "text": "On step 2."}]})
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1
    status, _, cards, _ = _state(agent.job)
    assert status == "failed" and [k for k, _ in cards] == ["failed"]
    with db.session() as s:
        assert s.query(Task).filter_by(status="queued").count() == 0


def test_what_the_applicant_says_on_the_record_reaches_the_runs_after_it(agent):
    """A note about the whole, an entry put right, and what they said when they asked for the application: each is on
    the record for the agent - also what was said on a version a later one replaced."""
    from autoapply import drafts, tasks
    from autoapply.models import Job

    db.set_setting("submit.policy", "approve")
    agent.ends.append(READY)
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job, "instructions": "Use my legal first name on this one."})
    assert tasks.drain() == 1 and "Use my legal first name on this one." in agent.seen[-1]["answers"].values()
    with db.session() as s:
        first = s.get(Job, agent.job).application.drafts[-1].id
    agent.ends.append(READY)
    drafts.comment(first, "Say I can start in May.")
    assert _state(agent.job)[0] == "revising" and tasks.drain() == 1
    said = list(agent.seen[-1]["answers"].values())
    assert "Say I can start in May." in said and "Use my legal first name on this one." in said and agent.seen[-1]["mode"] == "prepare"
    status, records, _, _ = _state(agent.job)
    assert status == "draft_ready" and [r[0] for r in records] == ["superseded", "pending"]
    with db.session() as s:
        second = s.get(Job, agent.job).application.drafts[-1].id
    drafts.edit_answer(second, "a1", "Alexander")
    with db.session() as s:
        from autoapply.models import Task

        assert s.query(Task).filter_by(status="queued").count() == 0      # (approval is asked for: correcting an entry does not send it)
    drafts.approve(second)
    agent.ends.append(SENT)
    assert tasks.drain() == 1
    last = agent.seen[-1]
    assert last["mode"] == "send" and last["answers"]["First name"] == "Alexander" and "Say I can start in May." in last["answers"].values()
    assert _state(agent.job)[0] == "submitted"
    with pytest.raises(drafts.Locked):
        drafts.edit_answer(second, "a1", "Alex")                       # it has gone out: the record is what was sent


def test_a_question_the_applicant_says_is_not_to_be_answered_stops_being_open(agent):
    from autoapply import drafts, tasks
    from autoapply.models import Job

    db.set_setting("submit.policy", "auto")
    asked = {"question": "Employee ID of the person who referred you", "about": "job", "options": [], "why": "Step 1"}
    agent.ends.append({"outcome": "needs_you", "record": {"summary": "One question is open.", "url": "https://careers.acme.example/apply/1", "answers": READY["record"]["answers"], "files": [],
                                                           "open": ["referrer"], "asked": [asked]}})
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1
    with db.session() as s:
        d = s.get(Job, agent.job).application.drafts[-1]
        did, qid = d.id, d.unresolved[0]["id"]
    with pytest.raises(drafts.Locked):
        drafts.drop_question(did, "a1")                                # an entry the agent made is corrected, not taken out
    agent.ends.append(SENT)
    drafts.drop_question(did, qid)
    assert _state(agent.job)[2] == [] and tasks.drain() == 1           # nothing is open any more: the agent goes on
    assert agent.seen[-1]["answers"] == {"Employee ID of the person who referred you": drafts.NOT_TO_ANSWER}


def test_the_window_handed_to_the_applicant_is_a_card_while_it_is_open(agent):
    from autoapply import tasks

    db.set_setting("submit.policy", "hand_over")
    end = {"hands": True, **SENT}
    agent.ends.append(end)
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1 and agent.seen[-1]["mode"] == "hand_over"
    assert end["cards_then"] == [("submit", f"application:{_app(agent.job)}")]      # while the window was theirs
    status, _, cards, evidence = _state(agent.job)
    assert status == "submitted" and cards == [] and "Reference AC-1" in evidence["text"]


def test_an_application_the_applicant_withdrew_is_taken_up_only_when_they_ask(agent):
    from autoapply import lifecycle, tasks
    from autoapply.models import Job

    db.set_setting("submit.policy", "approve")
    agent.ends.append(READY)
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    tasks.drain()
    with db.session() as s:
        lifecycle.move(s.get(Job, agent.job).application, "withdrawn", source="user")
    runs = len(agent.seen)
    assert agent.work.work(agent.job) == {"skipped": "the applicant is not applying for this one"} and len(agent.seen) == runs      # a task that was on its way
    token = tasks._started_by_hand.set(True)                           # they ask for it again themselves
    try:
        agent.ends.append(READY)
        assert agent.work.work(agent.job)["status"] == "ready" and len(agent.seen) == runs + 1
    finally:
        tasks._started_by_hand.reset(token)


def test_what_waited_in_the_queue_under_the_kinds_of_earlier_versions_is_the_one_task_now(agent):
    from autoapply import tasks
    from autoapply.models import Application, Draft, DraftComment, Job, Task

    with db.session() as s:
        app = Application(job_id=agent.job, status="draft_ready")
        s.add(app)
        s.flush()
        d = Draft(application_id=app.id, version=1, review_status="pending", schema={}, answers=[])
        other = Job(source="manual", source_id="a2", company="Beta", title="Analyst", apply_url="https://beta.example/jobs/2", jd_text="x" * 300, status="queued", online=1)
        s.add_all([d, other])
        s.flush()
        s.add_all([Task(kind="revise", ref=f"draft:{d.id}", status="queued", payload={"draft_id": d.id, "comment": "ask for 35 an hour"}),
                   Task(kind="execute", ref=f"application:{app.id}", status="queued", payload={"draft_id": d.id}),
                   Task(kind="recon", ref=f"job:{other.id}", status="waiting_human", payload={"job_id": other.id, "waits_for": "account:generic:beta.example", "instructions": "mention the referral"}),
                   Task(kind="scout", ref="draft:999", status="queued", payload={"draft_id": 999}),
                   Task(kind="recon", ref="job:5", status="done", payload={"job_id": 5}), Task(kind="mail", ref="schedule", status="queued", payload={})])
        other_id, draft_id = other.id, d.id
    assert agent.work.tasks_from_before() == 4
    with db.session() as s:
        got = [(t.kind, t.ref, t.status) for t in s.query(Task).order_by(Task.id)]
        assert got == [("apply", f"job:{agent.job}", "queued"), ("execute", f"application:{_app(agent.job)}", "cancelled"), ("apply", f"job:{other_id}", "waiting_human"),
                       ("scout", "draft:999", "cancelled"), ("recon", "job:5", "done"), ("mail", "schedule", "queued")]
        kept = s.query(Task).filter_by(ref=f"job:{other_id}").one().payload
        assert kept == {"job_id": other_id, "waits_for": "account:generic:beta.example", "instructions": "mention the referral"}
        assert [c.comment for c in s.query(DraftComment).filter_by(draft_id=draft_id)] == ["ask for 35 an hour"]      # what they wrote is with the record
    assert agent.work.tasks_from_before() == 0
    assert tasks.lane_of("apply") == "forms"


def test_an_approval_is_of_the_record_and_does_not_change_who_presses_the_last_button(agent):
    from autoapply import drafts, tasks
    from autoapply.models import Job

    db.set_setting("submit.policy", "hand_over")
    agent.ends.append(READY)
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1 and agent.seen[-1]["mode"] == "hand_over"
    with db.session() as s:
        did = s.get(Job, agent.job).application.drafts[-1].id
    drafts.approve(did)
    agent.ends.append({"hands": True, **SENT})
    assert tasks.drain() == 1
    last = agent.seen[-1]
    assert last["mode"] == "hand_over" and last["record"]["approved_by_the_applicant"] is True      # still theirs to press, with the record they approved
    with db.session() as s:
        app = s.get(Job, agent.job).application
        assert app.status == "submitted" and app.submitted_at is not None      # an application sent in this run has the time it was sent


def test_an_entry_the_applicant_emptied_is_told_to_the_next_run_as_that(agent):
    from autoapply import drafts, tasks
    from autoapply.models import Job

    db.set_setting("submit.policy", "approve")
    agent.ends.append(READY)
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    tasks.drain()
    with db.session() as s:
        did = s.get(Job, agent.job).application.drafts[-1].id
    drafts.edit_answer(did, "a2", "")
    drafts.approve(did)
    agent.ends.append(SENT)
    tasks.drain()
    last = agent.seen[-1]
    assert last["answers"] == {"Degree": agent.work.CLEARED} and "Degree" not in {a["question"] for a in last["record"]["answers"]}


def test_a_run_that_said_it_was_sending_and_did_not_confirm_it_leaves_the_outcome_unknown_whatever_else_it_reports(agent):
    from autoapply import tasks

    db.set_setting("submit.policy", "auto")
    said = [{"kind": "sending", "button": "Submit application"}]
    # it pressed, and then could not find a confirmation: the press may have gone through
    agent.ends.append({"outcome": "cannot", "journal": said, "record": {"summary": "After the press the page went blank; I could not find a confirmation."}})
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1
    status, _, cards, _ = _state(agent.job)
    assert status == "submit_unknown" and [k for k, _ in cards] == ["submit"]      # the card of an outcome that is not known
    # the next run only looks. It finds the application is not out - and the run after that says what shows the press did not send it
    with db.session() as s:
        from autoapply.models import Task

        for t in s.query(Task).filter_by(status="queued", kind="apply"):
            t.due_at = None
    agent.ends.append({"outcome": "ready", "record": {"summary": "The site lists it as a draft."}})
    agent.ends.append({"outcome": "cannot", "journal": said, "not_sent": "The form answered 'Résumé is required' and stayed on the page; the site lists the application as a draft.",
                       "record": {"summary": "The form will not take the file."}})
    assert tasks.drain() == 2 and [x["mode"] for x in agent.seen] == ["auto", "verify", "auto"]
    assert _state(agent.job)[0] == "failed"      # known not to be out: it did not get there, and can be worked again


def test_a_record_is_not_changed_under_a_run_that_is_working_from_it(agent):
    from autoapply import drafts, tasks
    from autoapply.models import Job

    db.set_setting("submit.policy", "approve")
    agent.ends.append(READY)
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    tasks.drain()
    with db.session() as s:
        did = s.get(Job, agent.job).application.drafts[-1].id
    db.set_setting("submit.policy", "auto")
    tried = []

    def edits_meanwhile():
        try:
            drafts.edit_answer(did, "a1", "Alexander")
        except drafts.Locked as e:
            tried.append(str(e))

    agent.ends.append({"during": edits_meanwhile, **SENT})
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1 and len(tried) == 1 and "叫停" in tried[0]      # said, instead of taken and then not used

