"""The profile, written from the résumé: a task that goes on while the applicant goes elsewhere, started by the upload
when there is no profile - and nothing that reads the profile is done for an applicant nothing is known about."""

from __future__ import annotations

import pytest

from autoapply import config, db, knowledge

WRITTEN = """# Applicant profile

## Identity & contact

- Name: Ada Example
- TODO: Legal name, if different

## Education

- University of Somewhere, BASc Computer Engineering, 2024 - 2029

## Experience

- Backend intern, Example Co (2026): built the billing service.
"""
JD = "Build and test backend services for the billing platform. " + "x " * 150


def _empty():
    """A program that has just been installed: no profile."""
    if config.PROFILE_MD.exists():
        config.PROFILE_MD.unlink()
    assert knowledge.blank()


def _client():
    from fastapi.testclient import TestClient

    from autoapply.api.main import app

    return TestClient(app)


def _job(n=1, status="new"):
    from autoapply.models import Job

    with db.session() as s:
        j = Job(source="greenhouse", source_id=f"g{n}", company=f"Co {n}", title=f"Backend Intern {n}", apply_url=f"https://boards.example/{n}", jd_text=JD, status=status, online=1)
        s.add(j)
        s.flush()
        return j.id


_FILES: dict[str, bytes] = {}


def _resume(c, name="resume.docx", kind="resume_docx", text="Ada Example\nBackend intern, Example Co"):
    import io

    import docx

    if text not in _FILES:
        doc = docx.Document()
        for ln in text.splitlines():
            doc.add_paragraph(ln)
        buf = io.BytesIO()
        doc.save(buf)
        _FILES[text] = buf.getvalue()
    return c.post("/api/documents", data={"kind": kind}, files={"file": (name, _FILES[text])}).json()


def _tasks(**where):
    from autoapply.models import Task

    with db.session() as s:
        return [(t.kind, t.status) for t in s.query(Task).filter_by(**where).order_by(Task.id)]


def test_headings_and_questions_to_the_applicant_are_not_a_profile(app_env):
    assert knowledge.blank(knowledge.EMPTY_PROFILE) and knowledge.blank("") and knowledge.blank("# Applicant profile\n\n## Identity & contact\n\n- TODO: legal name\n  * TODO work permit\n")
    assert not knowledge.blank("# Applicant profile\n\n## Identity & contact\n\n- Name: Ada\n") and not knowledge.blank(WRITTEN)
    assert not knowledge.blank()            # (the tests' own applicant, conftest)
    _empty()


def test_a_resume_uploaded_with_no_profile_has_the_profile_written_from_it_at_once(app_env, monkeypatch):
    """The first-run guide asked for a résumé and then for a second press of a button to make the profile of it - under
    a "skip, next" that was the page's main button. The guide was finished with an empty profile, the scan began, and
    every draft came back with its questions unanswered."""
    from autoapply import llm, tasks

    _empty()
    c = _client()
    read = []
    monkeypatch.setattr(llm, "text", lambda prompt, **kw: (read.append(prompt), "```markdown\n" + WRITTEN + "\n```")[1])
    up = _resume(c)
    assert up["profile_task"] and _tasks(kind="profile_init") == [("profile_init", "queued")]
    # the guide files a Word résumé a second time, as source material: the same task, and the file is read once
    assert _resume(c, kind="source")["profile_task"] == up["profile_task"] and len(_tasks(kind="profile_init")) == 1
    st = c.get("/api/profile/init").json()
    assert st["blank"] and st["task"]["status"] == "queued" and [d["kind"] for d in st["documents"]] == ["resume_docx"]
    assert tasks.drain() == 2                # (the profile, and the scoring that its arrival queues)
    assert len(read) == 1 and read[0].count("Backend intern, Example Co") == 1
    st = c.get("/api/profile/init").json()
    assert not st["blank"] and st["task"]["status"] == "done" and st["task"]["applied"] and st["task"]["todos"] == 1 and st["task"]["draft"] == ""
    assert knowledge.read("profile") == WRITTEN.strip() and knowledge.versions()[0]["source"] == "init"
    assert c.get("/api/persona").json()["has_profile"] is True      # (a profile with questions left open is a profile)
    # a transcript is not a résumé, and with a profile there a new résumé changes nothing by itself
    assert _resume(c, name="other.docx", text="Someone Else")["profile_task"] is None and len(_tasks(kind="profile_init")) == 1


def test_asked_for_at_the_page_it_is_a_task_and_what_it_wrote_is_there_whenever_the_page_is_opened(app_env, monkeypatch):
    """"Generate from résumé" was one request the page waited a minute for; what came back lived in the page. Another
    page and back, and it was gone - with the minute, and the model's work."""
    from autoapply import llm, tasks

    c = _client()
    assert c.post("/api/profile/init", json={}).status_code == 400          # nothing uploaded, nothing written: nothing to read
    _resume(c, kind="source")
    before = knowledge.read("profile")
    monkeypatch.setattr(llm, "text", lambda prompt, **kw: WRITTEN)
    r = c.post("/api/profile/init", json={"notes": "Work permit: study permit"}).json()
    assert r["task"]["status"] == "queued" and r["task"]["notes"] == "Work permit: study permit"
    assert c.post("/api/profile/init", json={"notes": "Work permit: study permit"}).json()["task_id"] == r["task_id"]      # pressed twice: one task
    assert tasks.drain() == 1
    # there is a profile: what was written is a proposal, and the profile is as it was
    for _ in range(2):          # (the page opened, left, opened again)
        st = c.get("/api/profile/init").json()
        assert st["task"]["status"] == "done" and not st["task"]["applied"] and st["task"]["draft"] == WRITTEN.strip() and st["current"] == before
    row = next(t for t in c.get("/api/tasks").json() if t["kind"] == "profile_init")
    assert "draft" not in row["result"] and row["label"] == "从简历生成个人资料" and "等你在“个人资料”页查看" in row["summary"]      # the list of tasks does not carry a profile around
    # adopted as the applicant edited it; then it is not a proposal any more
    edited = WRITTEN.replace("- TODO: Legal name, if different", "- Legal name: Ada B. Example")
    assert c.post(f"/api/profile/init/{r['task_id']}/adopt", json={"markdown": edited}).json()["version"]
    assert knowledge.read("profile") == edited and c.get("/api/profile/init").json()["task"]["draft"] == ""
    assert c.post(f"/api/profile/init/{r['task_id']}/adopt", json={}).status_code == 409
    # another one, discarded: the profile stays
    r2 = c.post("/api/profile/init", json={}).json()
    assert r2["task_id"] != r["task_id"] and tasks.drain() == 1
    assert c.post(f"/api/profile/init/{r2['task_id']}/discard", json={}).json() == {"version": None}
    st = c.get("/api/profile/init").json()
    assert st["task"]["settled"] == "discarded" and st["task"]["draft"] == "" and knowledge.read("profile") == edited
    assert c.post("/api/profile/init/999/adopt", json={}).status_code == 404 and c.post(f"/api/profile/init/{r2['task_id']}/keep", json={}).status_code == 404


def test_it_does_not_stand_behind_a_form_being_read_or_a_scan(app_env):
    """The applicant is at the page, waiting to see it. A scan can take twenty minutes and a form five."""
    from autoapply import tasks
    from autoapply.models import Task

    with db.session() as s:
        for kind, prio in (("discover", 10), ("recon", 20), ("profile_init", 90)):
            s.add(Task(kind=kind, ref="x", payload={}, priority=prio))
    assert tasks._claim("forms").kind == "recon" and tasks._claim("background").kind == "discover"      # both of them busy
    assert tasks._claim("forms") is None and tasks._claim("background") is None
    mine = tasks._claim("desk")
    assert mine.kind == "profile_init" and tasks._claim("desk") is None
    assert {r["kind"]: r["lane"] for r in tasks.plan()["running"]} == {"recon": "forms", "discover": "background", "profile_init": "desk"}
    # asked for again while it is being written: that one, not a second that reads the same files and writes over it
    from autoapply import profile_init

    assert profile_init.start("some notes") == mine.id and profile_init.in_flight() == mine.id


def test_nothing_is_scored_or_drafted_for_an_applicant_nothing_is_known_about(app_env, monkeypatch):
    """With the profile empty, postings were scored against an applicant block with nothing in it - scores that stood,
    since nothing scores a posting twice - and the best of them had their forms read: minutes at the employer's site
    for a draft in which every question was "no answer", and a card for each."""
    from autoapply import handlers, llm, scoring, tasks
    from autoapply.agent import work
    from autoapply.models import Job, Task, Todo

    _empty()
    ids = [_job(1), _job(2)]
    asked = []
    monkeypatch.setattr(llm, "json", lambda prompt, schema, **kw: (asked.append(prompt), {"excluded": False, "exclusion_rule": "", "score": 9.0, "direction": "backend", "reason": "r",
                                                                                      "term": "", "months": "", "summary": "s", "brief": ""})[1])
    monkeypatch.setattr(work, "work", lambda job_id, **kw: 1 / 0)       # no form is opened
    db.set_setting("queue.min_score_for_draft", 8.0)
    tasks.enqueue("score", ref="unscored", priority=150)
    tasks.enqueue("score", ref=f"job:{ids[0]}", payload={"job_id": ids[0]})
    recon = tasks.enqueue("apply", ref=f"job:{ids[1]}", payload={"job_id": ids[1]})
    assert tasks.drain() == 3 and asked == []
    assert scoring.score_job(ids[0]) is None and scoring.score_pending() == {"waits_for_profile": True} and scoring.queue_qualifying() == 0
    with db.session() as s:
        assert [j.status for j in s.query(Job).order_by(Job.id)] == ["new", "new"] and all(j.score is None for j in s.query(Job))
        assert [(t.kind, t.ref, t.title) for t in s.query(Todo).filter_by(status="open")] == [("config", "config:profile", "个人资料还是空的")]      # one card, whatever met it
        t = s.get(Task, recon)
        assert t.status == "waiting_human" and t.payload["waits_for"] == "config:profile" and "个人资料还是空的" in t.error
        assert [x.result for x in s.query(Task).filter_by(kind="score").order_by(Task.id)] == [{"waits_for_profile": True}] * 2
    assert tasks.plan()["waiting"][0]["waits_for"] == "个人资料还是空的"
    # the card ticked off with the profile still empty: the draft finds it empty again, and says so again
    assert handlers.resume_waiting("config:profile") == 1 and tasks.drain() == 1 and asked == []
    # the applicant writes one line about themselves: the card closes, the draft goes back in the queue, scoring is queued
    monkeypatch.setattr(work, "work", lambda job_id, **kw: {"draft_id": 77})
    knowledge.write("profile", "# Applicant profile\n\n## Identity & contact\n\n- Name: Ada Example\n")
    with db.session() as s:
        assert s.query(Todo).filter_by(status="open").count() == 0
        assert sorted((t.kind, t.ref) for t in s.query(Task).filter_by(status="queued")) == [("apply", f"job:{ids[1]}"), ("score", "unscored")]
    assert tasks.drain() >= 2 and len(asked) == 2
    with db.session() as s:
        assert s.get(Task, recon).result == {"draft_id": 77} and all(j.score == 9.0 for j in s.query(Job))
    # (a later change of the profile is not its arrival)
    knowledge.write("profile", WRITTEN)
    assert _tasks(status="queued") == []


def test_while_the_profile_is_being_written_there_is_no_card_and_a_failure_makes_one(app_env, monkeypatch):
    """The guide's last step starts a scan while the profile is still being written from the résumé: scoring waits for
    it without a word. If the writing fails, the applicant is told what is waiting."""
    from autoapply import llm, tasks
    from autoapply.models import Task, Todo

    _empty()
    c = _client()
    _resume(c)
    _job(1)
    with db.session() as s:      # the scan of the guide's last step has finished while the profile is still in the queue
        s.add(Task(kind="score", ref="unscored", payload={}, priority=1))
    scored = []
    monkeypatch.setattr(llm, "json", lambda prompt, schema, **kw: (scored.append(1), {"excluded": False, "exclusion_rule": "", "score": 5.0, "direction": "", "reason": "r", "term": "",
                                                                                      "months": "", "summary": "s", "brief": ""})[1])
    monkeypatch.setattr(llm, "text", lambda prompt, **kw: WRITTEN)
    tasks.run_one(tasks._claim("background"))
    with db.session() as s:
        assert s.query(Todo).count() == 0 and scored == []                 # on its way: nothing to tell
    assert tasks.drain() == 2 and scored == [1]                            # written, and what waited for it was scored
    # the same again, and the writing fails
    _empty()
    monkeypatch.setattr(llm, "text", lambda prompt, **kw: "# Applicant profile\n\n## Identity & contact\n\n- TODO: everything\n")
    assert c.post("/api/profile/init", json={}).json()["task"]["status"] == "queued" and tasks.drain() == 1
    st = c.get("/api/profile/init").json()
    assert st["blank"] and st["task"]["status"] == "failed" and st["task"]["error"].startswith("AI 没有从这些资料里整理出内容")
    with db.session() as s:
        assert [(t.kind, t.ref) for t in s.query(Todo).filter_by(status="open")] == [("config", "config:profile")]


def test_a_scanned_resume_is_said_in_words(app_env, monkeypatch):
    from pypdf import PdfWriter

    from autoapply import tasks

    _empty()
    c = _client()
    import io

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    assert c.post("/api/documents", data={"kind": "resume_site"}, files={"file": ("scan.pdf", buf.getvalue())}).json()["profile_task"]
    assert tasks.drain() == 1
    st = c.get("/api/profile/init").json()["task"]
    assert st["status"] == "failed" and st["error"] == "「scan.pdf」里读不出文字（可能是扫描件）。请上传文字版的 PDF 或 Word 文件。"


def test_a_draft_written_while_there_was_no_profile_is_asked_again_when_there_is_one(app_env, monkeypatch):
    """Before forms waited for a profile, a form read for nobody gave a draft of unanswered questions. Those drafts
    are still there when the profile is written: their open questions are asked again, the others left alone."""
    from autoapply import tasks
    from autoapply.agent import work
    from autoapply.models import Application, Draft

    _empty()
    jobs = [_job(n, status="queued") for n in (1, 2, 3)]
    with db.session() as s:
        ids = []
        for job_id, (status, answers) in zip(jobs, [("pending", [{"id": "q1", "label": "Phone", "value": "", "source": "unresolved", "required": True}]),
                                                    ("pending", [{"id": "q1", "label": "Phone", "value": "604", "source": "profile", "required": True}]),
                                                    ("superseded", [{"id": "q1", "label": "Phone", "value": "", "source": "unresolved", "required": True}])]):
            a = Application(job_id=job_id, status="needs_input")
            s.add(a)
            s.flush()
            d = Draft(application_id=a.id, review_status=status, notes=[], answers=answers)
            s.add(d)
            s.flush()
            ids.append(d.id)
    asked = []
    monkeypatch.setattr(work, "work", lambda job_id, **kw: (asked.append(job_id), {"status": "ready"})[1])
    knowledge.write("profile", "# Applicant profile\n\n## Identity & contact\n\n- Phone: 604 555 0100\n")
    assert _tasks(status="queued") == [("score", "queued"), ("apply", "queued")] and tasks.drain() == 2 and asked == [jobs[0]]      # the one whose question was asked of nothing


def test_a_profile_that_arrives_while_a_task_is_finding_it_empty_does_not_leave_the_task_waiting(app_env, monkeypatch):
    """The arrival looks for what waits, once. A draft that had just seen the empty profile was not yet recorded as
    waiting, and was recorded so a moment later - for good; scoring that was just ending as "no profile" took the
    arrival's request to score for its own."""
    from autoapply import profile_init, scoring, tasks
    from autoapply.agent import work
    from autoapply.models import Task, Todo

    _empty()
    job = _job(1)
    real = profile_init.wanted

    def arrives_now():       # between the look at the empty profile and the record of waiting
        knowledge.write("profile", "# Applicant profile\n\n## Identity & contact\n\n- Name: Ada Example\n")
        return real()

    monkeypatch.setattr(profile_init, "wanted", arrives_now)
    monkeypatch.setattr(work, "work", lambda job_id, **kw: {"draft_id": 77})
    recon = tasks.enqueue("apply", ref=f"job:{job}", payload={"job_id": job})
    tasks.run_one(tasks._claim("forms"))
    with db.session() as s:
        assert s.get(Task, recon).status == "queued" and s.query(Todo).filter_by(status="open").count() == 0
        for t in s.query(Task).filter_by(kind="score"):
            s.delete(t)
    # the same for scoring
    _empty()
    monkeypatch.setattr(scoring, "score_pending", lambda *a, **k: 1 / 0)
    first = tasks.enqueue("score", ref="unscored", priority=150)
    tasks.run_one(tasks._claim("background"))
    with db.session() as s:
        assert s.get(Task, first).result == {"waits_for_profile": True}
        assert [(t.kind, t.status) for t in s.query(Task).filter(Task.kind == "score", Task.id != first)] == [("score", "queued")]
        assert s.query(Todo).filter_by(status="open").count() == 0


def test_postings_that_came_as_short_summaries_are_scored_when_the_profile_arrives(app_env):
    """They do not count as unscored until their page has been read - which is the scoring task's first step."""
    from autoapply import scoring
    from autoapply.models import Job

    _empty()
    with db.session() as s:
        s.add(Job(source="rss", source_id="r1", company="Co", title="Intern", apply_url="https://x.example/1", jd_text="A two-line teaser.", jd_partial="summary", status="new", online=1))
    assert scoring.unscored_count() == 0
    knowledge.write("profile", "# Applicant profile\n\n## Identity & contact\n\n- Name: Ada Example\n")
    assert _tasks(status="queued") == [("score", "queued")]


def test_two_documents_of_one_name_and_one_length_are_two_documents(app_env):
    from autoapply import profile_init

    c = _client()
    for kind, body in (("resume_site", b"Ada Example, backend."), ("source", b"Ada Example, frontend"), ("cl_example", b"Ada Example, backend.")):
        assert c.post("/api/documents", data={"kind": kind}, files={"file": ("me.txt", body)}).status_code == 200
    assert [d.kind for d in profile_init.documents_for_init()] == ["resume_site", "source"]      # the third is a copy of the first


@pytest.mark.parametrize("kind", ["transcript", "cl_template", "other"])
def test_only_a_resume_starts_it(app_env, kind):
    _empty()
    assert _resume(_client(), kind=kind)["profile_task"] is None and _tasks(kind="profile_init") == []
