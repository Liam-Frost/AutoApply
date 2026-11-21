"""The applicant changed something about themselves: what is prepared and not sent may still say the old thing."""
from __future__ import annotations

from autoapply import db

from test_agent_work import READY, _app, _state, agent  # noqa: F401


PROFILE = "# Me\n- Name: Alex Chen\n- Earliest start: 2027-01-20\n- Work permit: open work permit\n"


def test_what_changed_in_the_profile_is_found_line_by_line():
    from autoapply import facts

    got = facts.changes(PROFILE, PROFILE.replace("2027-01-20", "2027-01-06").replace("- Work permit: open work permit\n", "") + "- Phone: 555\n")
    assert [(c["key"], c["old"], c["new"]) for c in got] == [("earliest start", "2027-01-20", "2027-01-06"), ("work permit", "open work permit", "")]
    assert facts.changes(PROFILE, PROFILE + "- Phone: 555\n") == []          # only added: nothing prepared rests on it


def test_a_changed_fact_stops_the_applications_that_use_it_until_the_applicant_decides(agent):  # noqa: F811
    from autoapply import knowledge, tasks
    from autoapply.api.main import facts_decide
    from autoapply.models import Draft, Job, Task, Todo

    knowledge.write("profile", PROFILE)
    db.set_setting("submit.policy", "approve")
    record = {"outcome": "ready", "record": {"summary": "Ready.", "url": "https://careers.acme.example/apply/review", "files": [], "open": [], "asked": [],
                                             "answers": [{"question": "Start date", "entered": "2027-01-20", "from": "profile: Earliest start", "sure": "yes"},
                                                         {"question": "Name", "entered": "Alex Chen", "from": "profile: Name", "sure": "yes"}]}}
    agent.ends.append(record)
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    assert tasks.drain() == 1
    with db.session() as s:      # approved, and its run queued to send it
        d = s.get(Job, agent.job).application.drafts[-1]
        did = d.id
    from autoapply import drafts

    drafts.approve(did)
    assert _state(agent.job)[0] == "approved"
    knowledge.write("profile", PROFILE.replace("2027-01-20", "2027-01-06"), source="user")
    status, records, cards, _ = _state(agent.job)
    assert status == "draft_ready" and records[-1][0] == "pending" and [k for k, _ in cards] == ["facts_changed"]
    with db.session() as s:
        assert s.query(Task).filter_by(kind="apply", status="queued").count() == 0          # the send is put aside
        card = s.query(Todo).filter_by(kind="facts_changed").one()
        row = card.payload["applications"][0]
        assert row["was_approved"] and [a["label"] for a in row["answers"]] == ["Start date"]      # the name does not rest on it
    # prepare again: the run is told what changed, and only that
    agent.ends.append(READY)
    assert facts_decide(card.id, {"action": "redo", "application_ids": [row["application_id"]]}) == {"decided": 1, "left": 0}
    assert tasks.drain() == 1
    said = " ".join(agent.seen[-1]["answers"].values())
    assert "2027-01-20" in said and "2027-01-06" in said and "不要重填" in said
    with db.session() as s:
        assert s.get(Todo, card.id).status == "done"


def test_keeping_the_old_value_gives_the_approval_back(agent):  # noqa: F811
    from autoapply import drafts, knowledge, tasks
    from autoapply.api.main import facts_decide
    from autoapply.models import Job, Task, Todo

    knowledge.write("profile", PROFILE)
    db.set_setting("submit.policy", "approve")
    agent.ends.append({"outcome": "ready", "record": {"summary": "Ready.", "files": [], "open": [], "asked": [],
                                                       "answers": [{"question": "Work authorization", "entered": "Open work permit", "from": "the profile", "sure": "yes"}]}})
    tasks.enqueue("apply", ref=f"job:{agent.job}", payload={"job_id": agent.job})
    tasks.drain()
    with db.session() as s:
        did = s.get(Job, agent.job).application.drafts[-1].id
    drafts.approve(did)
    knowledge.write("profile", PROFILE.replace("open work permit", "study permit"))      # found by the old value in what was entered
    with db.session() as s:
        card = s.query(Todo).filter_by(kind="facts_changed").one()
    facts_decide(card.id, {"action": "keep", "application_ids": [_app(agent.job)]})
    assert _state(agent.job)[0] == "approved"
    with db.session() as s:
        assert s.query(Task).filter_by(kind="apply", status="queued").count() == 1
