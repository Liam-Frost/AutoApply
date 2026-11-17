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
        assert [t.kind for t in s.query(Task).filter_by(status="queued")] == ["recon"]
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
            s.add(Task(kind=kind, ref="x", payload={}, priority=prio))
    assert tasks._claim("forms").kind == "execute" and tasks._claim("background").kind == "discover"
    assert tasks._claim("forms").kind == "recon" and tasks._claim("background").kind == "score"
    assert tasks._claim("forms") is None and tasks._claim("background").kind == "mail" and tasks._claim() is None


# --- a service that turns this computer's network away ---


def test_a_security_check_is_not_a_busy_server_and_one_refusal_speaks_for_the_whole_service(monkeypatch):
    """Eight Workday boards failed on every scan with "429 Too Many Requests". It was not a rate limit: the answer was a
    page saying "Security Check - enable JavaScript and cookies". Each board was asked four times with growing pauses,
    and the next board of the same service was asked all over again."""
    import httpx

    from autoapply.sources import public

    monkeypatch.setattr(public, "_refused", {})
    monkeypatch.setattr(public, "_last", {})
    asked = []

    def answer(request):
        asked.append(request.url.host)
        if request.url.host.endswith("myworkdayjobs.com"):
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
        # a server that really is busy is still waited for and asked again; another service is not affected
        monkeypatch.setattr("time.sleep", lambda s: None)
        assert public._send(c, "GET", "https://api.lever.co/busy", gap=0).status_code == 429 and asked.count("api.lever.co") == 4
        assert public._send(c, "GET", "https://api.lever.co/v0/postings/x", gap=0).status_code == 200


def test_boards_of_one_service_turned_away_are_told_as_one_thing(app_env):
    from autoapply import messages

    card = messages.discover_done({"read": 10, "seen": 2, "new": 1, "back": 0, "offline": 0}, {"Meta": 1},
                                  {"RBC": "网站的安全检查拒绝了这台电脑当前的网络（myworkdayjobs.com）", "TD": "网站的安全检查拒绝了这台电脑当前的网络（myworkdayjobs.com）",
                                   "Spotify": "HTTPStatusError: Server error '500 Internal Server Error'"})
    lines = card.detail.splitlines()
    assert lines[1].startswith("RBC、TD：网站的安全检查拒绝") and lines[2].startswith("Spotify：") and "代理或 VPN" in card.hint
