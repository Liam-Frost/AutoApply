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


def test_my_applications_are_what_went_out_and_what_waits_for_its_outcome(world):
    from fastapi.testclient import TestClient

    from autoapply.api.main import app

    c = TestClient(app)
    got = c.get("/api/applications").json()
    by = {r["company"]: r for r in got["applications"]}
    assert set(by) == {"Acme Robotics", "Globex", "Hooli"}                    # the draft that is still being prepared is not one of them
    assert by["Globex"]["unknown"] and by["Globex"]["status_label"] == "提交结果待确认" and "告诉程序结果" in by["Globex"]["next"]
    assert by["Acme Robotics"]["sent"] and by["Acme Robotics"]["submitted_at"] and {g["key"] for g in got["groups"]} >= {"applied", "progress"}
    # a table of them, to keep
    r = c.get("/api/applications.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "applications-" in r.headers["content-disposition"]
    lines = r.text.lstrip("﻿").splitlines()
    assert lines[0].startswith("公司,岗位,地点,状态,投出日期") and len(lines) == 4 and any(ln.startswith("Acme Robotics,Software Intern,\"Vancouver, BC\",已收到确认信,") for ln in lines)


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
    assert r.status_code == 200 and r.json()["status"] == "rejected" and "你手动记为“已被拒”：phone call on Tuesday" in r.json()["explained"]["message"]
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
    assert said[2][:3] == ("interview", "interview", "user") and said[2][3].startswith("投出日期改为 2026-10-20")
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
