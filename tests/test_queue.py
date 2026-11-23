"""Getting through many postings: rules before the model, several at a time, and two workers."""

from __future__ import annotations

import threading
import time

import pytest

from autoapply import db, knowledge

PORTAL = """Job Description:
Build and test {what}. {filler}

Job Requirements:
Enrolled in an engineering programme.

Open To All Majors:

 {open}

Targeted Co-op Programs:

 View Targeted Programs

{programs}
"""
PROFILE = """# Profile

## Education

- University of British Columbia (Vancouver), Bachelor of Applied Science, Computer Engineering,
  Sept 2024 - May 2029 (user chose 2029). In a co-op program: Yes.
- Another University of Political Science and Law, BSc Psychology, Sept 2023 - May 2024.

## Work authorization

- Study permit.
"""


def _posting(what, programs, open_="No"):
    return PORTAL.format(what=what, filler="x " * 120, open=open_, programs="\n\n".join(" " + p for p in programs))


def test_a_posting_says_whom_it_is_for_and_the_applicants_field_is_the_programme_they_are_in(app_env):
    from autoapply import intake

    knowledge.write("profile", PROFILE)
    assert intake.field_of_study(PROFILE) == "Computer Engineering" and intake.my_fields() == {"computer"}      # not the earlier degree, not the notes
    civil = _posting("bridges", ["Civil", "Integrated", "Master of Engineering Civil", "UBC Okanagan Civil"])
    assert intake.targeted(civil) == (False, ["Civil", "Integrated", "Master of Engineering Civil", "UBC Okanagan Civil"])
    assert intake.not_for_me(civil) == "面向其他专业：Civil、Integrated、Master of Engineering Civil、UBC Okanagan Civil"
    assert intake.not_for_me(_posting("firmware", ["Electrical", "Computer", "Integrated"])) == ""
    assert intake.not_for_me(_posting("chips", ["EECE-Master of Engineering in Electrical and Computer", "Electrical"])) == ""
    assert intake.not_for_me(_posting("anything", ["Civil"], open_="Yes")) == ""                     # open to all majors
    assert intake.not_for_me("Job Description: no word about programmes " * 20) == ""               # says nothing: not set aside
    # what follows the list on the page is the next field, not a programme
    assert intake.targeted(_posting("x", ["Civil"]) + "\n Start Date: 05/03/2027\n End Date: 08/27/2027\n")[1] == ["Civil"]
    db.set_setting("intake.programs", ["Mechanical"])                                                 # the applicant's own word wins
    assert intake.not_for_me(_posting("firmware", ["Electrical", "Computer"])).startswith("面向其他专业") and intake.not_for_me(_posting("gears", ["Mechanical"])) == ""
    db.set_setting("intake.programs", [])
    knowledge.write("profile", "# Profile\n\n## Identity\n\n- Name: A\n")
    assert intake.my_fields() == set() and intake.not_for_me(civil) == ""                            # nothing known about the applicant's field: nothing is set aside


def _jobs(texts):
    from autoapply.models import Job

    ids = []
    with db.session() as s:
        for n, text in enumerate(texts):
            j = Job(source="pdportal", source_id=f"p{n}", company=f"Co {n}", title=f"Role {n}", apply_url=f"https://x.example/{n}", channel="PD Portal", jd_text=text, status="new", online=1)
            s.add(j)
            s.flush()
            ids.append(j.id)
    return ids


def test_postings_for_other_programmes_are_set_aside_without_the_model_and_the_rest_are_read_several_at_a_time(app_env, monkeypatch):
    """A scan of the co-op portal brought every faculty's postings; each was read by the large model, one after the
    other, some twenty seconds apiece - most of it spent writing a long overview of a posting nobody would open."""
    from autoapply import llm, scoring
    from autoapply.models import Job, Task

    knowledge.write("profile", PROFILE)
    knowledge.write("scoring", "# Rules\n\n- Score software roles high.\n")
    mine = [_posting(f"service {n}", ["Computer", "Electrical"]) for n in range(6)]
    others = [_posting(f"bridge {n}", ["Civil", "Integrated"]) for n in range(5)]
    ids = _jobs(mine + others)
    db.set_setting("scoring.parallel", 3)
    db.set_setting("queue.min_score_for_draft", 8.0)
    at_once, peak, asked = [0], [0], []
    lock = threading.Lock()

    def answer(prompt, schema, **kw):
        with lock:
            at_once[0] += 1
            peak[0] = max(peak[0], at_once[0])
            asked.append(schema["properties"]["brief"]["description"])
        time.sleep(0.15)
        with lock:
            at_once[0] -= 1
        good = "service 0" in prompt
        return {"excluded": False, "exclusion_rule": "", "score": 8.5 if good else 4.0, "direction": "backend", "reason": "r", "term": "", "months": "",
                "summary": "s", "brief": "#### 这个岗位做什么\n- x" if good else ""}

    monkeypatch.setattr(llm, "json", answer)
    out = scoring.score_pending()
    assert out == {"scored": 6, "set_aside_by_rule": 5, "no_description": 0, "queued_for_draft": 1, "remaining": 0}
    assert len(asked) == 6 and peak[0] == 3                                # five were never shown to the model; the rest three at a time
    assert all("ONLY when the posting is not excluded and its score is 6 or more" in d for d in asked)
    with db.session() as s:
        rows = {j.id: j for j in s.query(Job)}
        assert all(rows[i].status == "skipped" and rows[i].exclusion.startswith("面向其他专业：Civil") and rows[i].score == 0 for i in ids[6:])
        assert rows[ids[0]].status == "queued" and rows[ids[0]].brief and rows[ids[1]].status == "scored" and not rows[ids[1]].brief
        assert [t.kind for t in s.query(Task).filter_by(status="queued")] == ["apply"]
    # the overview of a posting that got none is written when it is asked for
    monkeypatch.setattr(llm, "json", lambda prompt, schema, **kw: {"brief": "#### 这个岗位做什么\n- written on request"})
    assert "written on request" in scoring.brief_job(ids[1])
    with db.session() as s:
        assert "written on request" in s.get(Job, ids[1]).brief


def test_a_model_that_runs_out_keeps_what_was_read_and_leaves_the_rest_unscored(app_env, monkeypatch):
    from autoapply import llm, scoring
    from autoapply.models import Job

    knowledge.write("profile", PROFILE)
    knowledge.write("scoring", "# Rules\n")
    ids = _jobs([_posting(f"service {n}", ["Computer"]) for n in range(5)])
    db.set_setting("scoring.parallel", 1)
    n = [0]

    def answer(prompt, schema, **kw):
        n[0] += 1
        if n[0] > 2:
            raise llm.LLMUnavailable("usage limit reached")
        return {"excluded": False, "exclusion_rule": "", "score": 5.0, "direction": "", "reason": "r", "term": "", "months": "", "summary": "s", "brief": ""}

    monkeypatch.setattr(llm, "json", answer)
    out = scoring.score_pending()
    assert out["scored"] == 2 and out["remaining"] == 3 and "usage limit" in out["stopped"] and n[0] == 3      # asked once more, then not again
    with db.session() as s:
        assert sorted(j.status for j in s.query(Job)) == ["new", "new", "new", "scored", "scored"]
    n[0] = 99
    with pytest.raises(llm.LLMUnavailable):
        scoring.score_pending()                                              # nothing could be read at all: the task fails and is retried


def test_the_sources_are_fetched_side_by_side_and_stored_one_after_the_other(app_env, monkeypatch):
    from autoapply import discover, employers
    from autoapply.models import Job

    db.set_setting("sources.pdportal", False)
    db.set_setting("sources.parallel", 4)
    db.set_setting("intake.enabled", False)
    listed = [{"id": f"e{n}", "name": f"Employer {n}", "kind": "greenhouse", "ref": {"board": f"b{n}"}, "enabled": True} for n in range(4)]
    monkeypatch.setattr(employers, "listing", lambda: listed)
    monkeypatch.setattr(employers, "migrate_legacy", lambda: None)
    monkeypatch.setattr(employers, "source_of", lambda e: ("greenhouse", e["ref"]["board"]))
    at_once, peak = [0], [0]
    lock = threading.Lock()

    def rows_for(e, terms, keep):
        with lock:
            at_once[0] += 1
            peak[0] = max(peak[0], at_once[0])
        time.sleep(0.2)
        with lock:
            at_once[0] -= 1
        if e["id"] == "e3":
            raise RuntimeError("the board is not answering")
        board = e["ref"]["board"]
        return iter([{"source": "greenhouse", "source_id": f"{board}-{i}", "title": f"Intern {i}", "company": e["name"], "tenant": board,
                      "apply_url": f"https://x.example/{board}/{i}", "jd_text": "d" * 300} for i in range(2)])

    monkeypatch.setattr(employers, "rows_for", rows_for)
    out = discover.run(notify_user=False)
    assert peak[0] >= 3                                                      # several sites were being waited for at once
    assert {k: v["new"] for k, v in out["sources"].items()} == {"Employer 0": 2, "Employer 1": 2, "Employer 2": 2}
    assert "not answering" in out["errors"]["Employer 3"] and out["total"]["new"] == 6
    with db.session() as s:
        assert s.query(Job).count() == 6


def test_a_scan_does_not_hold_an_application_up(app_env):
    """One worker took the tasks in turn: a scan of twenty minutes kept every form waiting."""
    from autoapply import tasks
    from autoapply.models import Task

    with db.session() as s:
        for kind, prio in (("discover", 10), ("score", 20), ("execute", 50), ("recon", 60), ("mail", 70)):
            s.add(Task(kind=kind, ref=f"x:{kind}", payload={}, priority=prio))
    assert tasks._claim("forms").kind == "execute" and tasks._claim("background").kind == "discover"
    # the forms go on while the scan runs; the background work itself is one at a time, whichever process asks
    # (two generations of the service share the queue while one hands over to the other)
    assert tasks._claim("forms").kind == "recon" and tasks._claim("background") is None

    def finish(kind):
        with db.session() as s:
            s.query(Task).filter_by(kind=kind, status="running").one().status = "done"

    finish("discover")
    assert tasks._claim("background").kind == "score" and tasks._claim("forms") is None
    finish("score")
    assert tasks._claim("background").kind == "mail" and tasks._claim() is None


def test_several_applications_are_worked_at_once_but_not_two_on_one_application_or_one_site(app_env):
    """As many applications at a time as the applicant has set - three unless they say otherwise. An account and its
    sign-in are one, and so is an application: a second worker takes neither the application another is on nor another
    application on that site, and goes on to the next that is free."""
    from autoapply import tasks
    from autoapply.models import Job, Task

    assert tasks.parallel() == 3
    db.set_setting("agent.parallel", 5)
    assert tasks.parallel() == 5
    db.set_setting("agent.parallel", 40)
    assert tasks.parallel() == tasks.MOST
    db.set_setting("agent.parallel", 0)
    assert tasks.parallel() == 3                    # (nothing set is the default, not "none at all")
    with db.session() as s:
        ids = []
        for n, url in enumerate(("https://careers.acme.example/jobs/1", "https://careers.acme.example/jobs/2", "https://jobs.other.example/9")):
            j = Job(source="manual", source_id=f"p{n}", company="C", title=f"T{n}", apply_url=url, jd_text="x" * 300, status="queued", online=1)
            s.add(j)
            s.flush()
            ids.append(j.id)
            s.add(Task(kind="apply", ref=f"job:{j.id}", payload={"job_id": j.id}, priority=10 + n))
        s.add(Task(kind="apply", ref=f"job:{ids[0]}", payload={"job_id": ids[0], "record_changed": "later"}, priority=5))      # the same application, asked for again
    first = tasks._claim("forms")
    assert first.ref == f"job:{ids[0]}"
    second = tasks._claim("forms")                  # not the same application again, not the other posting on that site: the one on another site
    assert second.ref == f"job:{ids[2]}" and tasks._claim("forms") is None
    with db.session() as s:
        s.get(Task, first.id).status = "done"
    third = tasks._claim("forms")                   # the site is free again
    assert third.ref == f"job:{ids[0]}" and third.id != first.id
    # two addresses that turned out to sign in on the same one share an account and a saved sign-in: one site
    from autoapply import sites

    with db.session() as s:
        for t in s.query(Task):
            t.status = "done"
        j = Job(source="manual", source_id="p9", company="C", title="T9", apply_url="https://apply.acme-talent.example/7", jd_text="x" * 300, status="queued", online=1)
        s.add(j)
        s.flush()
        s.add(Task(kind="apply", ref=f"job:{ids[1]}", payload={"job_id": ids[1]}, priority=1))
        s.add(Task(kind="apply", ref=f"job:{j.id}", payload={"job_id": j.id}, priority=2))
    sites.link(sites.key_of("https://apply.acme-talent.example/7"), sites.key_of("https://careers.acme.example/jobs/2"))
    assert tasks._claim("forms").ref == f"job:{ids[1]}" and tasks._claim("forms") is None


# --- a service that turns this computer's network away ---


def test_a_security_check_is_not_a_busy_server_and_one_refusal_speaks_for_the_whole_service(app_env, monkeypatch):
    """Eight Workday boards failed on every scan with "429 Too Many Requests". It was not a rate limit: the answer was a
    page saying "Security Check - enable JavaScript and cookies". Each board was asked four times with growing pauses,
    and the next board of the same service was asked all over again."""
    import httpx

    from autoapply.sources import public

    for k in ("_refused", "_last", "_pace", "_rest", "_strikes", "_answered"):
        monkeypatch.setattr(public, k, {})
    asked = []

    def answer(request):
        asked.append(request.url.host)
        if request.url.host == "myworkdayjobs.com" or request.url.host.endswith(".myworkdayjobs.com"):
            return httpx.Response(429, headers={"content-type": "text/html; charset=UTF-8"}, text="<html><body>Security Check<br>Enable JavaScript and cookies to continue</body></html>")
        if request.url.path == "/busy":
            return httpx.Response(429, headers={"content-type": "application/json", "Retry-After": "0"}, json={"error": "slow down"})
        return httpx.Response(200, json={"jobPostings": []})

    with httpx.Client(transport=httpx.MockTransport(answer)) as c:
        with pytest.raises(public.Refused, match="security check"):
            public._send(c, "POST", "https://rbc.wd3.myworkdayjobs.com/wday/cxs/rbc/X/jobs", gap=0)
        assert asked == ["rbc.wd3.myworkdayjobs.com"]                       # once, not four times
        with pytest.raises(public.Refused, match="not asked again"):
            public._send(c, "POST", "https://td.wd3.myworkdayjobs.com/wday/cxs/td/Y/jobs", gap=0)
        assert len(asked) == 1                                              # another board of the same service: not asked at all
        # a server that really says "too many requests" is given the time it asks for and asked again - and when it keeps
        # saying it, it rests (below); another service is not affected
        monkeypatch.setattr("time.sleep", lambda s: None)
        with pytest.raises(public.Resting):
            public._send(c, "GET", "https://api.lever.co/busy", gap=0)
        assert asked.count("api.lever.co") == 4
        assert public._send(c, "GET", "https://api.example.org/v0/postings/x", gap=0).status_code == 200


def test_too_many_requests_rests_the_whole_service_and_it_is_asked_more_slowly(app_env, monkeypatch):
    """Seven Workday boards failed on every scan, for a week, with a real "429 Too Many Requests": one board's pages at
    1.5 s apart, the tenth refused; four quick retries refused; then every other board's first request refused - the
    service limits this computer's requests to all its employers together, and each new request kept it refusing. The
    rest after a refusal lived in memory, and a restart forgot it: it is kept now, and grows from one refusal to the next."""
    from datetime import datetime, timedelta, timezone

    import httpx

    from autoapply import db
    from autoapply.sources import public

    def time_passes():      # (the rest kept in the settings is over)
        kept = db.get_setting(public.RESTING) or {}
        db.set_setting(public.RESTING, {k: {**v, "until": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()} for k, v in kept.items()})

    for k in ("_refused", "_last", "_pace", "_rest", "_strikes", "_answered"):
        monkeypatch.setattr(public, k, {})
    clock = {"now": 1000.0}
    monkeypatch.setattr("time.monotonic", lambda: clock["now"])
    monkeypatch.setattr("time.sleep", lambda s: clock.__setitem__("now", clock["now"] + s))
    asked: list[tuple[str, float]] = []
    refusing = {"until": None}

    def answer(request):
        asked.append((request.url.host, clock["now"]))
        if refusing["until"] is None and len(asked) == 10:          # the tenth request in a row: the limit
            refusing["until"] = clock["now"] + 100
        if refusing["until"] is not None and clock["now"] < refusing["until"]:
            return httpx.Response(429, json={"error": "too many requests"})
        return httpx.Response(200, json={"jobPostings": []})

    wd = "https://{t}.wd3.myworkdayjobs.com/wday/cxs/{t}/X/jobs"
    with httpx.Client(transport=httpx.MockTransport(answer)) as c:
        for _ in range(9):
            assert public._send(c, "POST", wd.format(t="cibc")).status_code == 200
        gaps = [b[1] - a[1] for a, b in zip(asked, asked[1:])]
        assert min(gaps) >= public.PACE["myworkdayjobs.com"]                    # Workday is asked at its own pace, not every half second
        # refused: it rests a minute and is asked once more; refused again, it rests - kept: half an hour the first time
        with pytest.raises(public.Resting) as e:
            public._send(c, "POST", wd.format(t="cibc"))
        assert len(asked) == 11 and asked[10][1] - asked[9][1] >= 60 and e.value.who == "myworkdayjobs.com" and e.value.minutes == 30
        assert (db.get_setting(public.RESTING) or {})["myworkdayjobs.com"]["strikes"] == 1
        # the service's other boards in this scan: not asked at all, and said once for all of them
        with pytest.raises(public.Resting):
            public._send(c, "POST", wd.format(t="bmo"))
        # and after a restart (the program's memory empty): still not asked
        saved = {k: dict(getattr(public, k)) for k in ("_last", "_pace", "_rest", "_strikes", "_answered")}
        for k in saved:
            monkeypatch.setattr(public, k, {})
        with pytest.raises(public.Resting):
            public._send(c, "POST", wd.format(t="bmo"))
        for k, v in saved.items():
            monkeypatch.setattr(public, k, v)
        assert len(asked) == 11
        # after its rest it is asked again; an answer forgets what was kept
        clock["now"] += 121
        time_passes()
        assert public._send(c, "POST", wd.format(t="bmo")).status_code == 200
        assert not db.get_setting(public.RESTING)
        # a refusal before it answered again rests longer than the last one (an hour after half an hour)
        db.set_setting(public.RESTING, {"myworkdayjobs.com": {"until": datetime.now(timezone.utc).isoformat(), "strikes": 1}})
        assert round(public._rested("myworkdayjobs.com", 0) / 60) == 60
        db.set_setting(public.RESTING, {})
        public._send(c, "POST", wd.format(t="td"))
        assert asked[-1][1] - asked[-2][1] >= 4 * public.PACE["myworkdayjobs.com"]
        for _ in range(20):
            public._send(c, "POST", wd.format(t="td"))
        assert public._pace["myworkdayjobs.com"] == 3 * public.PACE["myworkdayjobs.com"]
        # an answer that says how long to wait is believed
        refusing["until"] = clock["now"] + public._pace["myworkdayjobs.com"] + 5
        monkeypatch.setattr(public, "_asked", lambda r: 5.0 if r.status_code == 429 else None)
        start = clock["now"]
        assert public._send(c, "POST", wd.format(t="td")).status_code == 200 and clock["now"] - start < 60


def test_a_service_that_asked_for_fewer_requests_is_one_line_in_the_summary(app_env):
    from autoapply import messages
    from autoapply.say import say as T
    from autoapply.sources import public

    err = public.Resting("myworkdayjobs.com", 0)
    said = {name: T("server.discover.theServiceAskedFor", p0=err.who) for name in ("TD", "BMO", "CIBC")}
    card = messages.discover_done({"read": 0, "seen": 0, "new": 0, "back": 0, "offline": 0}, {}, said)
    assert len(card.detail.splitlines()) == 2 and "TD、BMO、CIBC" in card.detail and "HTTP 429" in card.detail


def test_boards_of_one_service_turned_away_are_told_as_one_thing(app_env):
    from autoapply import messages

    card = messages.discover_done({"read": 10, "seen": 2, "new": 1, "back": 0, "offline": 0}, {"Meta": 1},
                                  {"RBC": "网站的安全检查拒绝了这台电脑当前的网络（myworkdayjobs.com）", "TD": "网站的安全检查拒绝了这台电脑当前的网络（myworkdayjobs.com）",
                                   "Spotify": "HTTPStatusError: Server error '500 Internal Server Error'"})
    lines = card.detail.splitlines()
    assert lines[1].startswith("RBC、TD：网站的安全检查拒绝") and lines[2].startswith("Spotify：") and "代理或 VPN" in card.hint


# --- work that is for later ---


def test_work_that_is_for_later_is_in_the_queue_and_outlives_a_saved_setting_and_a_restart(app_env, monkeypatch):
    """"Try again in half an hour" was a timer in the program's memory. Saving any setting rebuilt the schedule and
    dropped every such timer; a restart dropped them too. The retry of a site that was down simply never came."""
    from datetime import timedelta

    from apscheduler.schedulers.background import BackgroundScheduler
    from fastapi.testclient import TestClient

    from autoapply import tasks
    from autoapply.api.main import app
    from autoapply.models import Task, now

    ran = []
    monkeypatch.setitem(tasks._handlers, "recon", lambda t: ran.append((t.ref, t.payload.get("_down_retries"))) or {})
    scheduler = BackgroundScheduler()
    scheduler.start(paused=True)
    monkeypatch.setattr(tasks, "_sched", scheduler)
    try:
        tid = tasks.enqueue_later("recon", ref="job:844", payload={"_down_retries": 1}, minutes=30, priority=40)
        assert not any(j.id.startswith("later:") for j in scheduler.get_jobs())       # nothing of it lives in the scheduler
        scheduler.add_job(lambda: None, "interval", minutes=5, id="someone-elses")
        tasks.reschedule()                                                            # a setting is saved
        assert scheduler.get_job("someone-elses") is not None                         # only its own jobs are replaced
        assert {j.id for j in scheduler.get_jobs()} >= {"upkeep", "unscored"}
    finally:
        scheduler.shutdown()
    tasks.recover()                                                                   # the program is started again
    with db.session() as s:
        t = s.get(Task, tid)
        assert t.status == "queued" and t.due_at is not None and t.priority == 40
    assert tasks.drain() == 0 and ran == []                                           # in the queue, and not before its time
    row = next(r for r in TestClient(app).get("/api/tasks").json() if r["id"] == tid)
    assert row["status"] == "queued" and row["due_at"]                                # and the list of tasks says when
    with db.session() as s:
        s.get(Task, tid).due_at = now() - timedelta(seconds=1)
    assert tasks.drain() == 1 and ran == [("job:844", 1)]


def test_the_same_work_asked_for_now_is_taken_forward_not_queued_twice(app_env, monkeypatch):
    from autoapply import tasks
    from autoapply.models import Task

    ran = []
    monkeypatch.setitem(tasks._handlers, "recon", lambda t: ran.append(t.ref) or {})
    monkeypatch.setitem(tasks._handlers, "mail", lambda t: ran.append(t.ref) or {})
    later = tasks.enqueue_later("recon", ref="job:7", minutes=30)
    assert tasks.enqueue("recon", ref="job:7", priority=10) == later                  # "draft it now" while a retry waits: that retry, now
    assert tasks.drain() == 1 and ran == ["job:7"]
    # after the same delay: the one that waits is moved; after another delay: another look
    a = tasks.enqueue_later("mail", ref="confirm:3", minutes=5)
    assert tasks.enqueue_later("mail", ref="confirm:3", minutes=5) == a
    b = tasks.enqueue_later("mail", ref="confirm:3", minutes=30)
    assert b != a
    with db.session() as s:
        assert s.query(Task).filter_by(kind="mail", status="queued").count() == 2
    assert tasks.drain() == 0


# --- what the applicant can do about the queue ---


def _job(s, n, status="scored", score=8.0, app=None):
    from autoapply.models import Application, Job

    j = Job(source="manual", source_id=f"q{n}", company=f"Co{n}", title="Intern", apply_url=f"https://x.test/{n}", channel="employer site", jd_text="x" * 300,
            status=status, score=score, online=1)
    s.add(j)
    s.flush()
    if app:
        s.add(Application(job_id=j.id, status=app))
        s.flush()
    return j.id


def test_the_plan_says_what_is_being_done_what_comes_next_and_what_waits(app_env, monkeypatch):
    from datetime import timedelta

    from fastapi.testclient import TestClient

    from autoapply.api.main import app
    from autoapply.models import Task, Todo, now

    with db.session() as s:
        s.add(Task(kind="execute", ref="application:1", status="running", started_at=now(), priority=10))
        s.add(Task(kind="recon", ref="job:5", status="queued", priority=50))
        s.add(Task(kind="recon", ref="job:6", status="queued", priority=20, payload={"_by_hand": True}))
        s.add(Task(kind="score", ref="unscored", status="queued", priority=150))
        s.add(Task(kind="mail", ref="confirm:1", status="queued", priority=40, due_at=now() + timedelta(minutes=30)))
        s.add(Task(kind="recon", ref="job:7", status="waiting_human", payload={"waits_for": "account:workday:acme"}, error="The site wants a sign-in."))
        s.add(Task(kind="recon", ref="job:8", status="held"))
        s.add(Todo(kind="takeover", ref="account:workday:acme", title="Acme（acme.wd1.myworkdayjobs.com）", body="please sign in"))
    c = TestClient(app)
    p = c.get("/api/queue").json()
    assert [t["ref"] for t in p["running"]] == ["application:1"]
    assert [(t["ref"], t["by_hand"], t["lane"]) for t in p["next"]] == [("job:6", True, "forms"), ("job:5", False, "forms"), ("unscored", False, "background")]      # the order it will be taken in
    assert [t["ref"] for t in p["later"]] == ["confirm:1"] and p["later"][0]["due_at"]
    assert [(t["ref"], t["waits_for"]) for t in p["waiting"]] == [("job:7", "Acme（acme.wd1.myworkdayjobs.com）")] and [t["ref"] for t in p["held"]] == ["job:8"]
    assert p["paused"] is False and p["draining"] is False and p["drafts"]["cap"] == 20
    assert all("eta" not in t and "finish" not in t for t in p["next"])            # no time of completion is promised


def test_a_task_can_be_put_first_set_aside_taken_up_and_cancelled_but_not_cut_off(app_env, monkeypatch):
    from fastapi.testclient import TestClient

    from autoapply import tasks
    from autoapply.api.main import app
    from autoapply.models import Application, Draft, Job, Task, now

    ran = []
    monkeypatch.setitem(tasks._handlers, "recon", lambda t: ran.append(t.ref) or {})
    monkeypatch.setitem(tasks._handlers, "execute", lambda t: ran.append(t.ref) or {})
    with db.session() as s:
        j1, j2, j3 = _job(s, 1), _job(s, 2, status="queued", app="recon"), _job(s, 3, status="queued", app="approved")
        a2, a3 = s.get(Job, j2).application.id, s.get(Job, j3).application.id
        s.add(Draft(application_id=a3, version=1, review_status="approved", schema={}, answers=[]))
        ids = {}
        for name, kind, ref, st, prio in (("a", "recon", f"job:{j1}", "queued", 50), ("b", "recon", f"job:{j2}", "queued", 60), ("c", "execute", f"application:{a3}", "queued", 70),
                                          ("run", "execute", "application:999", "running", 5), ("done", "score", "unscored", "done", 150)):
            t = Task(kind=kind, ref=ref, status=st, priority=prio, started_at=now() if st == "running" else None)
            s.add(t)
            s.flush()
            ids[name] = t.id
    c = TestClient(app)
    # first: ahead of everything queued
    assert c.post(f"/api/tasks/{ids['c']}/first").status_code == 200
    assert [t["ref"] for t in c.get("/api/queue").json()["next"]][0] == f"application:{a3}"
    # set aside: not started until taken up again
    assert c.post(f"/api/tasks/{ids['a']}/hold").status_code == 200
    assert tasks._claim("forms").id == ids["c"]
    with db.session() as s:
        s.get(Task, ids["c"]).status = "queued"
    assert c.post(f"/api/tasks/{ids['a']}/take-up").status_code == 200 and c.post(f"/api/tasks/{ids['a']}/take-up").status_code == 409
    # cancelled: out of the queue - and the application it was for does not go on saying "queued" or "being read"
    assert c.post(f"/api/tasks/{ids['c']}/cancel").status_code == 200
    assert c.post(f"/api/tasks/{ids['b']}/cancel").status_code == 200
    with db.session() as s:
        assert s.get(Application, a3).status == "failed" and "取消" in s.get(Application, a3).last_event      # the approved draft is still there to run again
        assert s.get(Application, a2) is None and s.get(Job, j2).application is None                          # nothing had been drafted: back to "not applied"
        assert [s.get(Task, ids[k]).status for k in "abc"] == ["queued", "cancelled", "cancelled"]
    # a running task is not cut off, and one that has ended cannot be cancelled
    r = c.post(f"/api/tasks/{ids['run']}/cancel")
    assert r.status_code == 409 and "完成当前任务后停止" in r.json()["detail"]
    assert c.post(f"/api/tasks/{ids['done']}/cancel").status_code == 409 and c.post("/api/tasks/99999/cancel").status_code == 404
    assert c.post(f"/api/tasks/{ids['a']}/explode").status_code == 404


def test_finish_what_is_being_done_and_stop_then_say_so(app_env, monkeypatch):
    """Before closing or restarting the program the applicant had to watch the queue until nothing was running."""
    from fastapi.testclient import TestClient

    from autoapply import notify, tasks
    from autoapply.api.main import app
    from autoapply.models import Task, now

    told = []
    monkeypatch.setattr(notify, "send", lambda category, card, **kw: told.append(getattr(card, "heading", card)) or True)
    monkeypatch.setitem(tasks._handlers, "recon", lambda t: {})
    with db.session() as s:
        s.add(Task(kind="execute", ref="application:1", status="running", started_at=now()))
        s.add(Task(kind="recon", ref="job:1", status="queued"))
    c = TestClient(app)
    assert c.post("/api/queue/drain", json={"on": True}).json() == {"draining": True, "stopped": False}
    assert c.get("/api/overview").json()["draining"] is True and told == []          # something is still running: not yet
    tasks._tell_when_drained()
    assert told == []
    with db.session() as s:
        s.query(Task).filter_by(status="running").one().status = "done"
    tasks._tell_when_drained()
    tasks._tell_when_drained()
    assert told == ["手头的任务已完成，程序已停止"]                                    # once
    p = c.get("/api/queue").json()
    assert p["draining"] and p["stopped"] and [t["ref"] for t in p["next"]] == ["job:1"]      # what is queued stays queued
    assert c.post("/api/queue/drain", json={"on": False}).json() == {"draining": False, "stopped": False}
    # with nothing running it is said at once; and starting the program again ends it
    assert c.post("/api/queue/drain", json={"on": True}).json()["stopped"] is True
    monkeypatch.setattr(tasks, "_sched", None)
    monkeypatch.setattr(tasks.threading, "Thread", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    monkeypatch.setattr(tasks, "_schedule_jobs", lambda: None)
    try:
        tasks.start()
    except Exception:  # noqa: BLE001 - (the scheduler is not what this is about)
        pass
    assert db.get_setting("schedule.draining") is False


def test_a_pause_stops_what_the_program_does_by_itself_not_what_the_applicant_asks_for(app_env, monkeypatch):
    """Paused, nothing ran at all - also not "look in the mailbox now", pressed by the applicant."""
    from fastapi.testclient import TestClient

    from autoapply import tasks
    from autoapply.api.main import app
    from autoapply.models import Task

    ran = []
    monkeypatch.setitem(tasks._handlers, "mail", lambda t: ran.append(("mail", t.ref)) or {})
    monkeypatch.setitem(tasks._handlers, "discover", lambda t: ran.append(("discover", t.ref)) or {})
    db.set_setting("schedule.paused", True)
    tasks.enqueue("discover", ref="schedule", priority=10)                       # the clock
    c = TestClient(app)
    assert c.post("/api/tasks", json={"kind": "mail"}).status_code == 200         # the applicant, on the page
    with db.session() as s:
        by = {t.kind: bool((t.payload or {}).get("_by_hand")) for t in s.query(Task)}
    assert by == {"discover": False, "mail": True}
    t = tasks._claim("background", only_by_hand=True)
    assert t is not None and t.kind == "mail" and tasks._claim("background", only_by_hand=True) is None
    p = c.get("/api/queue").json()
    assert p["paused"] and [(x["kind"], x["held_by_pause"]) for x in p["next"]] == [("discover", True)]
    # the same work asked for by hand while the program had queued it itself: it is the applicant's from then on
    tasks.enqueue("recon", ref="job:9", priority=50)
    token = tasks.by_hand.set(True)
    try:
        again = tasks.enqueue("recon", ref="job:9", priority=10)
    finally:
        tasks.by_hand.reset(token)
    with db.session() as s:
        assert s.query(Task).filter_by(kind="recon").count() == 1 and s.get(Task, again).payload["_by_hand"] is True


def test_the_program_does_not_start_more_drafts_than_the_applicant_wants_waiting(app_env, monkeypatch):
    """A scan brings thousands of postings; the hundred best each got a draft, and nobody has the time to read a hundred."""
    from autoapply import scoring
    from autoapply.models import Job, Task

    db.set_setting("drafts.max_pending", 3)
    db.set_setting("queue.min_score_for_draft", 7.0)
    with db.session() as s:
        _job(s, 1, status="queued", app="draft_ready")
        _job(s, 2, status="queued", app="needs_input")
        _job(s, 3, status="applied", app="submitted")               # sent: it waits for nobody
        good = [_job(s, n, score=9.5 - n / 10) for n in (4, 5, 6, 7)]
    assert scoring.draft_room() == {"waiting": 2, "cap": 3, "room": 1}
    assert scoring.queue_qualifying(limit=6) == 1                    # one more, the best of them
    with db.session() as s:
        assert [t.ref for t in s.query(Task).filter_by(kind="apply")] == [f"job:{good[0]}"] and s.get(Job, good[0]).status == "queued"
        assert [s.get(Job, i).status for i in good[1:]] == ["scored"] * 3     # they keep their place: next when there is room
    assert scoring.draft_room()["room"] == 0 and scoring.queue_qualifying(limit=6) == 0
    db.set_setting("drafts.max_pending", 0)                           # no limit
    assert scoring.queue_qualifying(limit=6) == 3


def test_what_each_source_gave_and_why_the_rest_was_dropped_is_kept(app_env, monkeypatch):
    """"It read hundreds and there is nothing to apply for." The page showed the latest scan only, per source a line of
    reasons; a source that failed today showed its error and nothing of when it last worked or what it gave then, and
    where the postings it did give stand now - enough for the line, not enough, ruled out - was nowhere."""
    from fastapi.testclient import TestClient

    from autoapply import discover, employers
    from autoapply.api.main import app
    from autoapply.models import Job

    db.set_setting("employers", [{"id": "a", "name": "Alpha", "url": "https://a.example", "kind": "greenhouse", "ref": {"board": "alpha"}, "priority": False, "enabled": True},
                                 {"id": "b", "name": "Beta", "url": "https://b.example", "kind": "greenhouse", "ref": {"board": "beta"}, "priority": True, "enabled": True}])
    db.set_setting("sources.pdportal", False)
    db.set_setting("intake.enabled", True)
    db.set_setting("intake.title_any", ["intern"])
    db.set_setting("intake.title_role_any", [])
    db.set_setting("intake.title_none", ["sales"])
    db.set_setting("intake.countries", ["CA"])
    db.set_setting("queue.min_score_for_draft", 8.0)
    db.set_setting("employers.priority_min_score", 6.0)
    monkeypatch.setattr(employers, "migrate_legacy", lambda: None)
    down = {"Beta": False}
    titles = {"alpha": [("Software Intern", "Vancouver, BC, Canada"), ("Data Intern", "Toronto, ON, Canada"), ("Sales Intern", "Toronto, ON, Canada"),
                        ("Senior Engineer", "Vancouver, BC, Canada"), ("Staff Engineer", "Vancouver, BC, Canada"), ("ML Intern", "Austin, TX, US")],
              "beta": [("Hardware Intern", "Ottawa, ON, Canada"), ("Director", "Ottawa, ON, Canada")]}

    def rows_for(e, terms, keep):
        if down[e["name"]] if e["name"] in down else False:
            raise RuntimeError("the board is not answering")
        board = e["ref"]["board"]
        return iter([{"source": "greenhouse", "source_id": f"{board}-{i}", "title": t, "location": loc, "company": e["name"], "tenant": board,
                      "apply_url": f"https://x.example/{board}/{i}", "jd_text": "d" * 300} for i, (t, loc) in enumerate(titles[board])])

    monkeypatch.setattr(employers, "rows_for", rows_for)
    discover.run(notify_user=False)
    with db.session() as s:            # the scores come later: one of Alpha's is not enough for the line, one is ruled out; Beta's is enough for a priority employer's line
        by = {j.title: j for j in s.query(Job)}
        by["Software Intern"].score, by["Software Intern"].status = 7.0, "scored"
        by["Data Intern"].score, by["Data Intern"].status, by["Data Intern"].exclusion = 0.0, "skipped", "needs a clearance"
        by["Hardware Intern"].score, by["Hardware Intern"].status = 7.0, "scored"
    got = TestClient(app).get("/api/sources/report").json()
    a, b = (next(r for r in got["sources"] if r["name"] == n) for n in ("Alpha", "Beta"))
    assert (a["read"], a["kept"], a["new"], a["screened"]) == (6, 2, 2, True) and {d["key"]: d["n"] for d in a["dropped"]} == {"kind": 2, "excluded": 1, "country": 1}
    assert all(d["label"] and d["label"] != d["key"] for d in a["dropped"]) and a["ok_at"] and not a["error"]
    assert a["now"] == {"total": 2, "unscored": 0, "excluded": 1, "below": 1, "above": 0} and a["line"] == 8.0
    assert b["now"] == {"total": 1, "unscored": 0, "excluded": 0, "below": 0, "above": 1} and b["line"] == 6.0 and b["priority"] is True
    assert got["total"]["read"] == 8 and got["total"]["kept"] == 3 and {d["key"]: d["n"] for d in got["total"]["dropped"]} == {"kind": 3, "excluded": 1, "country": 1}
    # the postings that were dropped are counted, not kept
    with db.session() as s:
        assert s.query(Job).count() == 3
    assert "Sales Intern" not in str(db.get_setting("sources.history"))
    # the next scan cannot read Beta: what it gave when it last could be read is still there, with when that was
    ok_at = b["ok_at"]
    down["Beta"] = True
    discover.run(notify_user=False)
    b2 = next(r for r in TestClient(app).get("/api/sources/report").json()["sources"] if r["name"] == "Beta")
    assert b2["error"] and b2["fails"] == 1 and b2["ok_at"] == ok_at and (b2["read"], b2["kept"]) == (2, 1) and b2["error_at"] > ok_at
    down["Beta"] = False
    discover.run(notify_user=False)
    b3 = next(r for r in TestClient(app).get("/api/sources/report").json()["sources"] if r["name"] == "Beta")
    assert not b3["error"] and b3["fails"] == 0 and b3["ok_at"] > ok_at
    # it is the program's own record, not a setting: a settings page that sends everything back does not write it
    c = TestClient(app)
    assert c.put("/api/settings", json={"settings": {"sources.history": {}}}).status_code == 200 and db.get_setting("sources.history")


def test_work_that_is_asked_for_again_does_what_was_asked_last(app_env):
    """A revision that ran into the usage limit waits in the queue for half an hour with its comment. The applicant
    writes another comment meanwhile: the waiting task was taken forward - with the old comment - and the new one was
    answered "queued" and never carried out."""
    from autoapply import tasks
    from autoapply.models import Task

    old = tasks.enqueue_later("revise", ref="draft:7", payload={"draft_id": 7, "comment": "ask for 30 an hour", "_limit_retries": 1}, minutes=30, priority=10)
    new = tasks.enqueue("revise", ref="draft:7", payload={"draft_id": 7, "comment": "ask for 35 an hour"}, priority=10)
    with db.session() as s:
        t = s.get(Task, new)
        assert new == old and t.due_at is None and t.payload["comment"] == "ask for 35 an hour" and t.payload["_limit_retries"] == 1
        assert s.query(Task).filter_by(kind="revise").count() == 1
    # the same of one that simply waits its turn
    assert tasks.enqueue("revise", ref="draft:7", payload={"draft_id": 7, "comment": "and mention the start date"}, priority=10) == old
    with db.session() as s:
        t = s.get(Task, old)
        assert t.payload["comment"] == "and mention the start date"
        t.status = "running"
    # one that is being done cannot be told anything any more: the same request is that task, another one is a task after it
    assert tasks.enqueue("revise", ref="draft:7", payload={"draft_id": 7, "comment": "and mention the start date"}) == old
    assert tasks.enqueue("recon", ref="job:3", payload={"job_id": 3}) == tasks.enqueue("recon", ref="job:3", payload={"job_id": 3, "instructions": ""})
    later = tasks.enqueue("revise", ref="draft:7", payload={"draft_id": 7, "comment": "no, 40"})
    with db.session() as s:
        assert later != old and s.get(Task, later).status == "queued" and s.get(Task, old).payload["comment"] == "and mention the start date"


def test_what_was_put_aside_stays_put_aside_and_what_the_applicant_puts_back_is_theirs(app_env):
    """A task the applicant put aside ("not now") was not counted when the program asked whether the work was already
    queued: the next pass of the timer queued it a second time and did it. And a task the applicant put back - a card
    marked done, retry, take it up - went back as the program's own: held back again for the quiet hours, not taken
    while paused."""
    from autoapply import handlers, tasks
    from autoapply.models import Task

    tid = tasks.enqueue("scout", ref="draft:5", payload={"draft_id": 5})
    tasks.hold(tid)
    assert tasks.enqueue("scout", ref="draft:5", payload={"draft_id": 5}) == tid          # the program asks again: it stays where the applicant put it
    with db.session() as s:
        assert s.query(Task).filter_by(kind="scout").count() == 1 and s.get(Task, tid).status == "held"
    token = tasks.by_hand.set(True)
    try:
        assert tasks.enqueue("scout", ref="draft:5", payload={"draft_id": 5}) == tid      # the applicant asks: it is taken up
        with db.session() as s:
            t = s.get(Task, tid)
            assert t.status == "queued" and t.payload["_by_hand"] is True
            # what waits for the applicant, what failed, what was put aside: put back by them, they are theirs
            waits = Task(kind="recon", ref="job:9", payload={"job_id": 9, "waits_for": "account:idp:school"}, status="waiting_human")
            failed = Task(kind="recon", ref="job:10", payload={"job_id": 10}, status="failed", error="x")
            aside = Task(kind="recon", ref="job:11", payload={"job_id": 11}, status="held")
            s.add_all([waits, failed, aside])
            s.flush()
            ids = (waits.id, failed.id, aside.id)
        assert handlers.resume_waiting("account:idp:school") == 1
        tasks.retry(ids[1])
        tasks.take_up(ids[2])
    finally:
        tasks.by_hand.reset(token)
    with db.session() as s:
        assert [(s.get(Task, i).status, s.get(Task, i).payload.get("_by_hand")) for i in ids] == [("queued", True)] * 3
        # the program putting a task back by itself (the clock, a restart) does not make it the applicant's
        own = Task(kind="recon", ref="job:12", payload={"job_id": 12}, status="failed", error="x")
        s.add(own)
        s.flush()
        own_id = own.id
    tasks.retry(own_id)
    with db.session() as s:
        assert s.get(Task, own_id).status == "queued" and "_by_hand" not in s.get(Task, own_id).payload


def test_the_room_for_drafts_goes_to_the_best_postings(app_env, monkeypatch):
    """With one place left, the batch that was just scored got it in the order it was read - newest first: a posting
    scored 8 took the place, and one scored 10 in the same batch, and one scored 9.5 that had been waiting, did not."""
    from autoapply import notify, scoring
    from autoapply.models import Job, Task

    monkeypatch.setattr(notify, "send", lambda *a, **k: True)
    db.set_setting("queue.min_score_for_draft", 7.0)
    db.set_setting("drafts.max_pending", 1)
    with db.session() as s:
        waiting = _job(s, 1, score=9.5)                               # scored before, still waiting for room
        best = _job(s, 2, status="new", score=None)                   # read second (older), scores 10
        fine = _job(s, 3, status="new", score=None)                   # read first (newest), scores 8
    scores = {best: 10.0, fine: 8.0}

    def score_job(jid):
        with db.session() as s:
            j = s.get(Job, jid)
            j.score, j.status = scores[jid], "scored"
        return {"excluded": False}

    monkeypatch.setattr(scoring, "score_job", score_job)
    monkeypatch.setattr(scoring, "set_aside_by_rule", lambda ids: ids)
    out = scoring.score_pending()
    refs = lambda: sorted(t.ref for t in db.session().__enter__().query(Task).filter_by(kind="apply"))  # noqa: E731
    assert refs() == [f"job:{best}"] and out.get("queued_for_draft", out.get("queued")) == 1
    with db.session() as s:
        assert [s.get(Job, i).status for i in (best, waiting, fine)] == ["queued", "scored", "scored"]
    # room for more: the next places go by score as well - the one that waited at 9.5 before the 8
    db.set_setting("drafts.max_pending", 0)
    assert scoring.queue_qualifying(limit=1) == 1 and refs() == sorted([f"job:{best}", f"job:{waiting}"])


def test_the_sources_page_counts_with_the_line_the_queue_uses(app_env, monkeypatch):
    """How many postings of a source are above the line was counted with the source's line; the queue asks the posting's
    employer. A job board marked as priority does not make the employers on it priority - and a priority line above
    the general one does not raise the bar for anybody."""
    from autoapply import discover, employers, scoring
    from autoapply.models import Job

    db.set_setting("sources.pdportal", False)
    db.set_setting("queue.min_score_for_draft", 8.0)
    db.set_setting("employers.priority_min_score", 6.0)
    listed = [{"id": "board", "name": "Campus Board", "kind": "feed", "ref": {"url": "https://board.example/rss"}, "priority": True, "enabled": True},
              {"id": "acme", "name": "Acme", "kind": "greenhouse", "ref": {"board": "acme"}, "priority": True, "enabled": True}]
    monkeypatch.setattr(employers, "listing", lambda: listed)
    with db.session() as s:
        for n, (company, source, tenant, score) in enumerate([("Gamma", "feed", "board", 7.0), ("Acme", "feed", "board", 7.0), ("Delta", "feed", "board", 8.5),
                                                               ("Acme", "greenhouse", "acme", 6.5), ("Acme", "greenhouse", "acme", 8.5)]):
            s.add(Job(source=source, source_id=f"s{n}", title=f"Intern {n}", company=company, tenant=tenant, status="scored", score=score,
                      apply_url=f"https://x.example/{n}", jd_text="d" * 300))

    def rows():
        got = discover.report()["sources"]
        return [next(r for r in got if r["name"] == n) for n in ("Campus Board", "Acme")]

    board, acme = rows()
    # on the board: Acme's posting is held to the priority line, the other two employers' to the general one
    assert (board["now"]["above"], board["now"]["below"], board["lines"], board["line"]) == (2, 1, [6.0, 8.0], 6.0)
    assert (acme["now"]["above"], acme["now"]["below"], acme["lines"]) == (2, 0, [6.0])
    # a priority line above the general one: the general one still gets a draft (the lower of the two counts)
    db.set_setting("employers.priority_min_score", 9.0)
    board, acme = rows()
    assert (board["now"]["above"], board["now"]["below"], board["lines"]) == (1, 2, [8.0])
    assert (acme["now"]["above"], acme["now"]["below"], acme["lines"]) == (1, 1, [8.0])
    # and what the page counts as above the line is what the queue starts
    db.set_setting("employers.priority_min_score", 6.0)
    above = sum(r["now"]["above"] for r in rows())
    assert scoring._start_best(10) == above == 4
    with db.session() as s:
        assert sorted((j.company, j.score) for j in s.query(Job).filter_by(status="queued")) == [("Acme", 6.5), ("Acme", 7.0), ("Acme", 8.5), ("Delta", 8.5)]
    # an employer with nothing listed now still says which line its postings would be held to
    with db.session() as s:
        for j in s.query(Job).filter_by(source="greenhouse"):
            j.online = 0
    assert rows()[1]["lines"] == [6.0] and rows()[1]["now"]["total"] == 0
