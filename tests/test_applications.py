"""One application, whole - and the applicant's own corrections to its record.

What was known about an application was spread over the jobs list, the draft, a card, the activity record and the
list of runs. Following one took a tour; correcting one (a phone call, an interview arranged elsewhere, a mail put on
the wrong application) could not be done at all.
"""
from datetime import datetime, timedelta

import pytest

from autoapply import db


@pytest.fixture()
def world(app_env, monkeypatch, tmp_path):
    from autoapply import notify
    from autoapply.models import Application, Contact, Document, Draft, Job, MailEvent, Run, Todo, now

    monkeypatch.setattr(notify, "send", lambda *a, **k: True)
    cv = tmp_path / "Liam_Resume.pdf"
    cv.write_bytes(b"%PDF-1.4")
    t = now()
    with db.session() as s:
        doc = Document(kind="resume_site", name=cv.name, path=str(cv))
        s.add(doc)
        ids = {}
        for key, company, status, sent in (("sent", "Acme Robotics", "confirmed", t - timedelta(days=9)), ("open", "Globex", "submit_unknown", None),
                                           ("draft", "Initech", "draft_ready", None), ("talks", "Hooli", "interview", t - timedelta(days=20))):
            j = Job(source="workday", source_id=f"R{len(ids) + 1}0001", company=company, title="Software Intern", location="Vancouver, BC", apply_url=f"https://x.test/{key}",
                    channel="employer site", jd_text="x" * 300, status="applied" if sent else "scored", deadline="2027-01-15 23:59")
            s.add(j)
            s.flush()
            a = Application(job_id=j.id, status=status, submitted_at=sent, created_at=t - timedelta(days=30),
                            evidence={"text": "Thank you for applying. REF-7", "url": f"https://x.test/{key}/done", "mail_id": "m-conf", "mail_ids": ["m-conf"]} if key == "sent" else {})
            s.add(a)
            s.flush()
            ids[key] = a.id
        s.flush()
        d = Draft(application_id=ids["sent"], version=1, review_status="closed", schema={}, answers=[],
                  materials=[{"slot": "resume", "slot_label": "Resume/CV", "document_id": doc.id, "name": cv.name, "kind": "resume_site", "path": str(cv)},
                             {"slot": "cl", "slot_label": "Cover letter", "document_id": 999, "name": "Acme.pdf", "kind": "cover_letter", "path": str(tmp_path / "gone.pdf")}])
        s.add(d)
        s.add(Draft(application_id=ids["open"], version=1, review_status="approved", schema={}, answers=[]))
        s.add(MailEvent(message_id="m-conf", sender="Acme <hr@acme.test>", subject="We received your application", received_at=t - timedelta(days=9), category="confirmation",
                        event="new", application_id=ids["sent"], summary="received", company_guess="Acme Robotics"))
        s.add(MailEvent(message_id="m-lost", sender="Acme <hr@acme.test>", subject="Interview invitation", received_at=t - timedelta(days=2), category="interview",
                        event="new", application_id=None, summary="invited for Thursday", company_guess="Akme"))
        s.add(Run(kind="execute", ref=f"application:{ids['sent']}", ats="workday", ok=1, steps=[]))
        s.add(Contact(name="Dana", company="Acme Robotics Inc.", role="Engineer", relation="校友", follow_up="2026-12-01", note="met at the fair"))
        s.add(Todo(kind="submit", ref=f"application:{ids['open']}", title="Globex · Software Intern：提交结果待确认", body="…", payload={"application_id": ids["open"]}))
    return ids


def test_every_application_is_listed_by_whose_move_it_is(world):
    """From the moment it is begun to its outcome: each application in one group, with whose move it is and what to press."""
    from fastapi.testclient import TestClient

    from autoapply.api.main import app

    c = TestClient(app)
    got = c.get("/api/applications").json()
    by = {r["company"]: r for r in got["applications"]}
    assert set(by) == {"Acme Robotics", "Globex", "Hooli", "Initech"}           # the one still being prepared too
    assert (by["Initech"]["group"], by["Initech"]["who"], by["Initech"]["act"]) == ("me", "me", "approve") and by["Initech"]["stage_label"] == "待批准"
    assert (by["Globex"]["group"], by["Globex"]["act"]) == ("me", "check_mail") and by["Globex"]["unknown"]
    assert by["Globex"]["next"] == "确认提交结果" and "告知程序结果" in by["Globex"]["next_why"]      # the task in a phrase; why, for the application's page
    assert (by["Acme Robotics"]["group"], by["Acme Robotics"]["who"]) == ("sent", "them") and by["Acme Robotics"]["submitted_at"]
    assert by["Hooli"]["group"] == "progress" and by["Hooli"]["deadline"] == "" and by["Initech"]["deadline"] == "2027-01-15 23:59"
    assert c.get("/api/overview").json()["apps_need_me"] == 2
    # put away, and back
    assert c.post("/api/applications/bulk", json={"action": "archive", "ids": [world["sent"]]}).json()["done"] == 1
    assert {r["company"]: r for r in c.get("/api/applications").json()["applications"]}["Acme Robotics"]["group"] == "archived"
    c.post("/api/applications/bulk", json={"action": "unarchive", "ids": [world["sent"]]})
    # a table of them, to keep (all of them, or the ones picked)
    r = c.get("/api/applications.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "applications-" in r.headers["content-disposition"]
    lines = r.text.lstrip("\ufeff").splitlines()
    assert lines[0].startswith("公司,岗位,地点,状态,投递日期") and len(lines) == 5 and any(ln.startswith("Acme Robotics,Software Intern,\"Vancouver, BC\",已收到确认邮件,") for ln in lines)
    assert len(c.get(f"/api/applications.csv?ids={world['sent']}").text.lstrip("\ufeff").splitlines()) == 2


def test_several_at_once_say_what_they_skipped(world):
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app
    from autoapply.models import Application, Draft, Job

    c = TestClient(app)
    with db.session() as s:
        s.add(Draft(application_id=world["draft"], version=1, review_status="pending", schema={}, answers=[{"id": "q1", "label": "Salary", "value": "30", "confidence": "low"}],
                    unresolved=[{"id": "q2", "label": "Start date"}]))
    seen = {r["id"]: r for r in c.get(f"/api/applications/review?ids={world['draft']},{world['sent']}").json()}
    assert seen[world["draft"]]["unresolved"] == 1 and not seen[world["draft"]]["can"] and seen[world["draft"]]["unsure"] == ["Salary：30"]
    assert seen[world["sent"]]["draft_id"] is None
    out = c.post("/api/applications/bulk", json={"action": "approve", "ids": [world["draft"]]}).json()
    assert out["done"] == 0 and out["skipped"] == 1 and "1" in out["errors"][str(world["draft"])]
    out = c.post("/api/applications/bulk", json={"action": "withdraw", "ids": [world["draft"], world["sent"]]}).json()
    assert out["done"] == 1 and out["skipped"] == 1                                # what went out is not withdrawn by a tick in a list
    with db.session() as s:
        a = s.get(Application, world["draft"])
        assert a.status == "withdrawn" and s.get(Job, a.job_id).status == "skipped"


def test_note_and_what_came_back(world):
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app
    from autoapply.models import Todo

    c = TestClient(app)
    assert c.put(f"/api/applications/{world['sent']}/note", json={"note": "Dana said to apply early"}).json()["ok"]
    a = c.post(f"/api/applications/{world['sent']}/outcome", json={"status": "interview", "date": "2027-02-03", "time": "10:30", "note": "phone screen"}).json()
    assert a["status"] == "interview" and a["note"] == "Dana said to apply early"
    assert any(e.get("note", "").startswith("2027-02-03 10:30 · phone screen") for e in a["timeline"])
    with db.session() as s:      # on the calendar too, about this application
        t = s.query(Todo).filter_by(kind="note").one()
        assert (t.payload or {}).get("application_id") == world["sent"] and t.due_at.hour == 10 and "Acme Robotics" in t.title
    assert c.post(f"/api/applications/{world['sent']}/outcome", json={"status": "withdrawn"}).status_code == 400


def test_postings_are_grouped_and_lead_to_their_application(world):
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app
    from autoapply.models import Job

    c = TestClient(app)
    with db.session() as s:
        s.add(Job(source="workday", source_id="N1", company="Umbrella", title="Analyst", apply_url="https://x.test/u", status="scored", deadline="2099-01-01"))
        s.add(Job(source="workday", source_id="N2", company="Wayne", title="Analyst", apply_url="https://x.test/w", status="skipped", exclusion="French required"))
        s.add(Job(source="workday", source_id="N3", company="Stark", title="Analyst", apply_url="https://x.test/s", status="scored", online=0))
    by = {j["company"]: j for j in c.get("/api/jobs").json()["jobs"]}
    assert by["Umbrella"]["group"] == "todo" and by["Umbrella"]["app"] is None
    assert by["Wayne"]["group"] == "skip" and by["Stark"]["group"] == "closed"
    assert by["Initech"]["group"] == "started" and by["Initech"]["app"]["id"] == world["draft"] and by["Initech"]["app"]["stage_label"] == "待批准"
    assert by["Hooli"]["group"] == "started"      # a posting taken down after its application went out still leads to it


def test_a_posting_corrected_by_hand_keeps_the_correction(app_env):
    from fastapi.testclient import TestClient

    from autoapply import db, discover
    from autoapply.api.main import app
    from autoapply.models import Job

    c = TestClient(app)
    discover.upsert([{"source_id": "77", "company": "Acme", "title": "Analyst", "deadline": "2027-01-10", "apply_url": "https://x.test/a"}], source="greenhouse", complete=False)
    with db.session() as s:
        jid = s.query(Job).one().id
    c.patch(f"/api/jobs/{jid}", json={"deadline": "2027-01-20", "title": "Analyst"})
    discover.upsert([{"source_id": "77", "company": "Acme", "title": "Data Analyst", "deadline": "2027-01-12", "apply_url": "https://x.test/a"}], source="greenhouse", complete=False)
    j = c.get(f"/api/jobs/{jid}").json()
    assert j["deadline"] == "2027-01-20" and j["edited"] == {"deadline": "2027-01-12"}      # theirs kept; what the source says now, to show
    assert j["title"] == "Data Analyst"                                                       # (not changed by hand: the source's)
    c.patch(f"/api/jobs/{jid}", json={"use_source": ["deadline"]})
    assert c.get(f"/api/jobs/{jid}").json()["deadline"] == "2027-01-12"
    assert c.delete(f"/api/jobs/{jid}").status_code == 409                                    # a scan found it: not deleted
    mine = c.post("/api/jobs", json={"url": "https://x.test/mine", "company": "Mine", "title": "Dev"}).json()["id"]
    assert c.get(f"/api/jobs/{mine}").json()["deletable"] and c.delete(f"/api/jobs/{mine}").json()["ok"]
    with db.session() as s:
        assert s.get(Job, mine) is None


def test_one_application_with_everything_about_it(world):
    from fastapi.testclient import TestClient

    from autoapply.api.main import app

    c = TestClient(app)
    a = c.get(f"/api/applications/{world['sent']}").json()
    assert a["status"] == "confirmed" and a["job"]["deadline"] == "2027-01-15 23:59" and a["job"]["source_id"] == "R10001"
    assert a["evidence"]["text"].startswith("Thank you for applying") and a["evidence"]["mail_ids"] == ["m-conf"]
    assert [(m["slot"], m["name"], m["exists"]) for m in a["materials"]] == [("Resume/CV", "Liam_Resume.pdf", True), ("Cover letter", "Acme.pdf", False)]     # what was sent, and whether it is still there
    assert [(m["subject"], m["label"], m["is_evidence"]) for m in a["mails"]] == [("We received your application", "收到申请确认", True)]
    assert [x["name"] for x in a["contacts"]] == ["Dana"]                                                    # who the applicant knows there
    kinds = [e["kind"] for e in a["timeline"]]
    assert "run" in kinds and "mail" in kinds and a["actions"] == [] and a["cards"] == []
    # one whose outcome is open: what can be done about it is there, with its card
    o = c.get(f"/api/applications/{world['open']}").json()
    assert o["actions"] == ["check_mail", "mark_submitted", "rerun_not_submitted"] and [x["kind"] for x in o["cards"]] == ["submit"] and o["materials_from_draft"]
    assert c.get("/api/applications/99999").status_code == 404
    # the jobs list leads to it
    assert c.get(f"/api/jobs/{a['job_id']}").json()["app_id"] == world["sent"]


def test_the_applicant_puts_the_record_right_and_it_is_kept_as_theirs(world):
    from fastapi.testclient import TestClient

    from autoapply.api.main import app
    from autoapply.models import Application, ApplicationEvent

    c = TestClient(app)
    aid = world["talks"]
    # a call: rejected. Forward, with a note.
    r = c.post(f"/api/applications/{aid}/correct", json={"status": "rejected", "note": "phone call on Tuesday"})
    assert r.status_code == 200 and r.json()["status"] == "rejected" and "你手动记为“被拒”：phone call on Tuesday" in r.json()["explained"]["message"]
    # a mistake: it was the other application. Back - which nothing but the applicant may do.
    r = c.post(f"/api/applications/{aid}/correct", json={"status": "interview"})
    assert r.json()["status"] == "interview"
    # the date it was sent
    r = c.post(f"/api/applications/{aid}/correct", json={"submitted_at": "2026-10-20"})
    assert r.json()["submitted_at"].startswith("2026-10-20")
    with db.session() as s:
        said = [(e.old, e.new, e.source, e.note) for e in s.query(ApplicationEvent).filter_by(application_id=aid).order_by(ApplicationEvent.id)]
        assert s.get(Application, aid).evidence["user"]["status"] == "interview"
    assert said[0] == ("interview", "rejected", "user", "phone call on Tuesday") and said[1][:3] == ("rejected", "interview", "user")
    assert said[2][:3] == ("interview", "interview", "user") and said[2][3].startswith("投递日期改为 2026-10-20")
    line = c.get(f"/api/applications/{aid}").json()["timeline"]
    assert sum(1 for e in line if e["kind"] == "status" and e["by"] == "你") == 3
    # what is the program's to keep is not the applicant's to set, and a draft has no date of sending
    assert c.post(f"/api/applications/{aid}/correct", json={"status": "executing"}).status_code == 400
    assert c.post(f"/api/applications/{world['draft']}/correct", json={"submitted_at": "2026-10-20"}).status_code == 400
    assert c.post(f"/api/applications/{aid}/correct", json={"submitted_at": "yesterday"}).status_code == 400
    # an application whose outcome is open is settled by the applicant's word
    assert c.post(f"/api/applications/{world['open']}/correct", json={"status": "submitted"}).json()["status"] == "submitted"


def test_which_application_a_mail_is_about_can_be_put_right_from_the_application(world):
    from fastapi.testclient import TestClient

    from autoapply.api.main import app
    from autoapply.models import Application, MailEvent

    c = TestClient(app)
    aid = world["sent"]
    # a mail the program could not place is offered, and placed by the applicant: the application moves as the mail says
    lost = c.get(f"/api/applications/{aid}/mail-candidates").json()
    assert [m["message_id"] for m in lost] == ["m-lost"] and lost[0]["label"] == "面试邀请"
    assert c.post(f"/api/applications/{aid}/mails/link", json={"message_id": "m-lost"}).json() == {"updated": 1}
    a = c.get(f"/api/applications/{aid}").json()
    assert a["status"] == "interview" and [m["linked_by"] for m in a["mails"] if m["message_id"] == "m-lost"] == ["user"]
    # and taken off again: the mail goes back to "which application?", the evidence no longer counts it, the status is the applicant's to correct
    assert c.post(f"/api/applications/{aid}/mails/unlink", json={"message_id": "m-conf"}).status_code == 200
    with db.session() as s:
        assert s.query(MailEvent).filter_by(message_id="m-conf").one().application_id is None
        ev = s.get(Application, aid).evidence
        assert ev["mail_ids"] == [] and ev["mail_id"] == "" and s.get(Application, aid).status == "interview"
    assert c.post(f"/api/applications/{aid}/mails/unlink", json={"message_id": "m-conf"}).status_code == 404


def test_news_about_an_application_leads_to_the_application(app_env, monkeypatch):
    from autoapply import messages, notify

    sent = []
    monkeypatch.setattr(notify, "_channels", lambda: [type("C", (), {"send_card": lambda self, card, base: sent.append((card.path, card.link))})()])
    notify.send("task_result", messages.submitted("Acme · Intern", evidence="Thank you"), ref="application:12")
    notify.send("task_result", messages.failed("Acme · Intern", error="x"), ref="application:12")            # what has to be done is on the to-do list
    notify.send("status_update", messages.mail_update("interview", "Acme · Intern", "invited"), ref="application:12:manual", tag="interview")
    assert [p for p, _ in sent] == ["/applications/12", "/todos", "/applications/12"]


def test_what_the_applicant_withdrew_is_not_filled_in_by_work_that_was_on_its_way(world):
    """"I am not applying for this one" changed a status. The draft stayed approved and its filling stayed in the
    queue: the next thing the program did was fill the form in and submit it. The same for "not applying" ticked on a
    posting, which did not touch the application at all."""
    from fastapi.testclient import TestClient

    from autoapply import browser, lifecycle
    from autoapply.agent import work
    from autoapply.api.main import app
    from autoapply.models import Application, Draft, Job, Task, Todo

    def under_way(key):
        """An approved draft with its filling queued, a reading that was put aside, and a card that asks for something."""
        with db.session() as s:
            a = s.get(Application, world[key])
            a.status = "approved"
            d = Draft(application_id=a.id, version=3, review_status="approved", schema={}, answers=[])
            s.add(d)
            s.flush()
            run = Task(kind="execute", ref=f"application:{a.id}", payload={"draft_id": d.id}, status="queued")
            read = Task(kind="scout", ref=f"draft:{d.id}", payload={"draft_id": d.id}, status="held")
            card = Todo(kind="answer", ref=f"draft:{d.id}", title="a question", body="", payload={"draft_id": d.id})
            s.add_all([run, read, card])
            s.flush()
            return a.id, a.job_id, d.id, run.id, read.id, card.id

    def now(app_id, draft_id, run, read, card):
        with db.session() as s:
            return s.get(Application, app_id).status, s.get(Draft, draft_id).review_status, s.get(Task, run).status, s.get(Task, read).status, s.get(Todo, card).status

    c = TestClient(app)
    # recorded by hand on the application
    app_id, job_id, did, run, read, card = under_way("draft")
    assert c.post(f"/api/applications/{app_id}/correct", json={"status": "withdrawn"}).status_code == 200
    assert now(app_id, did, run, read, card) == ("withdrawn", "closed", "cancelled", "cancelled", "done")
    # a task that runs all the same (started again from the list of what has run, with a draft that says "approved"): nothing is filled in
    with db.session() as s:
        s.get(Draft, did).review_status = "approved"
    def no_browser(*a, **k):
        raise AssertionError("the form was about to be opened")

    real_open, browser.open_page = browser.open_page, no_browser
    try:      # (the program does not work it again by itself; an application the applicant asks for does)
        assert work.work(job_id) == {"skipped": "the applicant is not applying for this one"}
    finally:
        browser.open_page = real_open
    assert "不投" in lifecycle.closed_to_work(lifecycle_app(app_id))
    # "not applying" on the posting: the application is withdrawn with it
    with db.session() as s:
        lifecycle.move(s.get(Application, app_id), "draft_ready", source="user", back=True)
    app_id, job_id, did, run, read, card = under_way("draft")
    assert c.patch(f"/api/jobs/{job_id}", json={"status": "skipped"}).status_code == 200
    assert now(app_id, did, run, read, card) == ("withdrawn", "closed", "cancelled", "cancelled", "done")
    with db.session() as s:
        assert s.get(Job, job_id).status == "skipped"
        sent_job = s.get(Application, world["sent"]).job_id
        unknown_job = s.get(Application, world["open"]).job_id
    # what went out, or may have, is not undone by a tick in a list
    assert c.patch(f"/api/jobs/{sent_job}", json={"status": "skipped"}).status_code == 409
    got = c.post("/api/jobs/bulk", json={"action": "skip", "ids": [sent_job, unknown_job]}).json()
    assert got == {"done": 0, "skipped": 2}
    with db.session() as s:
        assert s.get(Application, world["sent"]).status == "confirmed" and s.get(Application, world["open"]).status == "submit_unknown"


def lifecycle_app(app_id):
    from autoapply.models import Application

    with db.session() as s:
        a = s.get(Application, app_id)
        s.expunge(a)
        return a


def test_a_note_alone_is_a_correction(world):
    """The page sends no status when it is the one the application has: a note without one was answered "recorded" and thrown away."""
    from fastapi.testclient import TestClient

    from autoapply.api.main import app
    from autoapply.models import ApplicationEvent

    c = TestClient(app)
    assert c.post(f"/api/applications/{world['talks']}/correct", json={"note": "second round is on the 3rd"}).status_code == 200
    with db.session() as s:
        last = s.query(ApplicationEvent).filter_by(application_id=world["talks"]).order_by(ApplicationEvent.id.desc()).first()
        assert (last.old, last.new, last.source, last.note) == ("interview", "interview", "user", "second round is on the 3rd")
    n = lambda: db.session().__enter__().query(ApplicationEvent).filter_by(application_id=world["talks"]).count()  # noqa: E731
    before = n()
    assert c.post(f"/api/applications/{world['talks']}/correct", json={}).status_code == 200 and n() == before          # nothing said, nothing recorded


def test_a_mail_taken_off_an_application_asks_again_which_it_is_about(world):
    """"This mail is not about this application" left the mail about no application and asked nobody which: a mail the
    program matched itself never had the card, the mailbox is not read twice, and the page said it would wait among the to-dos."""
    from fastapi.testclient import TestClient

    from autoapply.api.main import app
    from autoapply.models import MailEvent, Todo

    c = TestClient(app)
    assert c.post(f"/api/applications/{world['sent']}/mails/unlink", json={"message_id": "m-conf"}).status_code == 200
    with db.session() as s:
        assert s.query(MailEvent).filter_by(message_id="m-conf").one().application_id is None
        card = s.query(Todo).filter_by(kind="mail_unmatched", ref="mail:m-conf", status="open").one()
        assert card.payload["message_id"] == "m-conf" and "We received your application" in card.title


def test_the_next_date_of_an_application_is_what_is_still_to_come_on_the_local_clock(world):
    """The column showed an information request that had been answered as what came next, and its time eight hours off:
    what is done is not next, and the time is the wall clock the calendar shows (no zone, never read as UTC)."""
    from autoapply import applications
    from autoapply.models import Todo

    soon = (datetime.now() + timedelta(days=2)).replace(hour=17, minute=0, second=0, microsecond=0)
    later = soon + timedelta(days=1, hours=-7)
    with db.session() as s:
        s.add(Todo(kind="followup", ref=f"followup:{world['talks']}:info", title="Hooli - information", status="done", due_at=soon,
                   payload={"application_id": world["talks"], "category": "info_request"}))
        s.add(Todo(kind="followup", ref=f"followup:{world['talks']}:interview", title="Hooli - interview", due_at=later,
                   payload={"application_id": world["talks"], "category": "interview"}))
    row = next(r for r in applications.listing() if r["id"] == world["talks"])
    assert row["next_date"]["kind"] == "interview"
    assert row["next_date"]["start"] == later.isoformat(timespec="minutes") and not row["next_date"]["start"].endswith("Z")


def test_a_row_says_the_next_step_and_the_latest_event_in_a_few_words(world):
    """A row of the list has room for a phrase, not for a mail's text: the next step is a task for whoever's move it is
    (in step with the stage the row shows), the latest event is a mail's heading or a first sentence - the whole of it
    stays for the application's page - and the company is the name alone."""
    from autoapply import applications, say
    from autoapply.models import Application

    long_mail = "Hooli moved the interview to Friday 10:00. Reply to confirm. " + "More about parking and badges. " * 30
    with db.session() as s:
        s.get(Application, world["talks"]).last_event = "interview (changed): " + long_mail
        s.get(Application, world["sent"]).last_event = "Globex Inc. asked for a transcript. It was uploaded from the library."
        s.get(Application, world["draft"]).job.company = "Initech  Location: Vancouver, BC  Work Term: Summer 2027"
    rows = {r["id"]: r for r in applications.listing(dates=False)}
    talks = rows[world["talks"]]
    assert talks["latest"] == "面试安排有变化" and say.render(talks["latest"], "en") == "Interview arrangements changed"
    assert talks["last_event"].startswith("面试安排有变化：") and "parking and badges" in talks["last_event"]
    assert say.render(talks["last_event"], "en").startswith("Interview arrangements changed: Hooli moved")      # the heading in the page's language
    assert rows[world["sent"]]["latest"] == "Globex Inc. asked for a transcript."      # ("Inc." does not end the sentence)
    assert "uploaded from the library" in rows[world["sent"]]["last_event"]
    assert rows[world["draft"]]["company"] == "Initech"
    assert applications.review([world["draft"]])[0]["company"] == "Initech"
    assert rows[world["talks"]]["next"] == "准备面试" and rows[world["talks"]]["next_why"] == ""
    # the stage a row shows and its next step say the same thing
    with db.session() as s:
        a = s.get(Application, world["draft"])
        j = a.job
        a.status = "recon"
        assert applications.next_of("recon", applications.stage_of(a, j))[0] == "Agent 正在处理"
        waits = applications.stage_of(a, j, waiting=True)
        assert (waits["who"], waits["act"]) == ("me", "handle") and applications.next_of("recon", waits)[0] == "处理待办"
        a.status = "failed"
        assert applications.next_of("failed", applications.stage_of(a, j))[0] == "让 Agent 重试"
        assert applications.next_of("failed", applications.stage_of(a, j, budget=True)) == ("追加预算", "")
        j.online = 0
        a.status = "recon"
        gone = applications.stage_of(a, j)
        assert gone["stage"] == "offline" and applications.next_of("recon", gone) == ("", "")
        s.rollback()


def test_what_is_still_to_come_is_next_before_what_was_earlier_today(world):
    """The interview of this morning is not "next" while an assessment waits tomorrow; alone, it is still shown."""
    from autoapply import applications
    from autoapply.models import Todo

    past = datetime.now().replace(hour=0, minute=1, second=0, microsecond=0)
    tomorrow = (datetime.now() + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
    with db.session() as s:
        s.add(Todo(kind="followup", ref=f"followup:{world['talks']}:am", title="Hooli - interview", due_at=past, payload={"application_id": world["talks"], "category": "interview"}))
    row = next(r for r in applications.listing() if r["id"] == world["talks"])
    assert row["next_date"]["start"] == past.isoformat(timespec="minutes")
    with db.session() as s:
        s.add(Todo(kind="followup", ref=f"followup:{world['talks']}:oa", title="Hooli - assessment", due_at=tomorrow, payload={"application_id": world["talks"], "category": "assessment"}))
    row = next(r for r in applications.listing() if r["id"] == world["talks"])
    assert (row["next_date"]["kind"], row["next_date"]["start"]) == ("assessment", tomorrow.isoformat(timespec="minutes"))
