"""The figures that say where the applicant's time and the program's go: questions asked again and again, how long the
first record takes, what waits for the applicant, why good postings were missed, how long an unknown outcome stays
unknown."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from autoapply import db

NOW = datetime.now(timezone.utc).replace(tzinfo=None)


def _app(company, status="draft_ready", *, score=8.0, deadline="", url="https://jobs.example/1", found=None, begun=None):
    from autoapply.models import Application, Job

    with db.session() as s:
        j = Job(source="manual", source_id=company, company=company, title="Analyst", apply_url=url, jd_text="x" * 300, status="queued", online=1,
                score=score, deadline=deadline, first_seen=found or NOW - timedelta(days=2))
        s.add(j)
        s.flush()
        if status is None:
            return j.id, None
        a = Application(job_id=j.id, status=status, created_at=begun or NOW - timedelta(days=1))
        s.add(a)
        s.flush()
        return j.id, a.id


def _record(app_id, answers, at=None):
    from autoapply.models import Draft

    with db.session() as s:
        s.add(Draft(application_id=app_id, version=1, review_status="pending", schema={}, answers=answers, unresolved=[], created_at=at or NOW))


def test_a_question_asked_in_several_applications_is_listed_and_can_go_into_the_profile(app_env):
    from autoapply import analytics as an
    from autoapply import knowledge
    from autoapply.api.main import remember_answer

    for n, (company, label) in enumerate((("Acme", "What is your expected salary? *"), ("Globex", "what is your expected salary"), ("Initech", "Expected salary (optional)"))):
        _, a = _app(company)
        _record(a, [{"id": "q1", "label": label, "value": "$24" if n else "", "about": "applicant", "basis": "edited by user" if n else "", "source": "profile" if n else "unresolved"},
                    {"id": "a1", "label": "First name", "value": "Alex", "basis": "profile: Name", "source": "agent"}])
    got = an.asked_again(an.window())
    assert [(r["times"], r["answer"], r["in_profile"]) for r in got["rows"]] == [(2, "$24", False)]       # "Expected salary" is another question
    assert {x["company"] for x in got["rows"][0]["applications"]} == {"Acme", "Globex"}
    remember_answer({"question": got["rows"][0]["question"], "answer": "$24"})
    assert 'answer "$24"' in knowledge.read("profile")
    assert an.asked_again(an.window())["rows"][0]["in_profile"] is True


def test_how_long_an_unknown_outcome_stayed_unknown(app_env):
    from autoapply import analytics as an
    from autoapply.models import ApplicationEvent

    _, a = _app("Acme", "confirmed")
    _, b = _app("Globex", "submit_unknown")
    _, c = _app("Initech", "draft_ready")
    with db.session() as s:
        s.add_all([ApplicationEvent(application_id=a, at=NOW - timedelta(hours=10), old="executing", new="submit_unknown", source="run"),
                   ApplicationEvent(application_id=a, at=NOW - timedelta(hours=4), old="submit_unknown", new="confirmed", source="mail"),
                   ApplicationEvent(application_id=b, at=NOW - timedelta(hours=30), old="executing", new="submit_unknown", source="run"),
                   ApplicationEvent(application_id=c, at=NOW - timedelta(hours=8), old="executing", new="submit_unknown", source="run"),
                   ApplicationEvent(application_id=c, at=NOW - timedelta(hours=7), old="submit_unknown", new="draft_ready", source="user")])
    with db.session() as s:
        got = an._settled_after(s, an.window())
    assert (got["settled"], got["went_out"], got["by_mail"]) == (2, 1, 1)
    assert got["median_hours"] == 3.5                                     # (6 hours and 1 hour)
    assert [o["company"] for o in got["open"]] == ["Globex"] and round(got["open"][0]["hours"]) == 30


def test_the_first_record_the_backlog_and_why_good_postings_were_missed(app_env):
    from autoapply import analytics as an
    from autoapply.models import Todo

    _, a = _app("Acme", "draft_ready", found=NOW - timedelta(hours=10), begun=NOW - timedelta(hours=4))
    _record(a, [], at=NOW - timedelta(hours=1))
    past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    _app("Globex", "needs_input", deadline=past)
    _app("Initech", None, deadline=past)
    _app("Hooli", None, deadline=past, url="")
    _app("Umbrella", None, deadline=past, score=6.0)                       # below the bar: not a good posting missed
    with db.session() as s:
        s.add_all([Todo(kind="answer", title="Globex", status="done", created_at=NOW - timedelta(hours=5), done_at=NOW - timedelta(hours=2)),
                   Todo(kind="answer", title="Acme", status="done", created_at=NOW - timedelta(hours=3), done_at=NOW - timedelta(hours=2)),
                   Todo(kind="config", title="Gmail", status="open", created_at=NOW - timedelta(hours=50))])
    got = an.applications(an.window())
    assert got["first_record"]["n"] == 1 and round(got["first_record"]["from_found_hours"]) == 9 and round(got["first_record"]["from_begun_hours"]) == 3
    assert {r["key"]: r["n"] for r in got["missed_reasons"]} == {"no_link": 1, "not_started": 1, "waited_for_you": 1}
    b = got["backlog"]
    assert (b["handled"], b["median_hours"], b["open"]) == (2, 2.0, 1)
    assert b["by_kind"][0]["kind"] == "answer" and b["oldest"][0]["title"] == "Gmail" and round(b["oldest"][0]["hours"]) == 50
