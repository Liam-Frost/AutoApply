"""Archiving, repeat postings, the file endpoints and the analysis numbers."""
from datetime import timedelta


def test_repeat_posting_next_year_is_not_merged_and_old_rows_archive(app_env):
    from autoapply import db, discover
    from autoapply.models import Application, Job, now

    old = now() - timedelta(days=400)
    with db.session() as s:
        a = Job(source="pdportal", source_id="140001", company="NVIDIA", title="Software Engineer Intern", term="Summer 2026", status="applied", online=0, first_seen=old, last_seen=old)
        s.add(a)
        s.flush()
        s.add(Application(job_id=a.id, status="rejected", submitted_at=old, updated_at=old))
        s.add(Job(source="nvidia", source_id="JR999", company="NVIDIA", title="Software Engineer Intern", term="Summer 2027", status="new", online=1,
                  apply_url="https://nvidia.eightfold.ai/careers/job/999", jd_text="x" * 400))
        s.add(Job(source="amazon", source_id="1", company="Amazon", title="SDE Intern", status="scored", online=1, deadline=""))
    assert discover.link_duplicates() == 0  # same name, a year apart: two postings
    assert discover.archive_old() == 1
    with db.session() as s:
        rows = {j.source_id: j for j in s.query(Job)}
        assert rows["140001"].archived_at is not None and rows["JR999"].archived_at is None and rows["JR999"].duplicate_of is None
        new_id = rows["JR999"].id
    h = discover.history(new_id)
    assert len(h) == 1 and h[0]["applied"] and h[0]["archived"] and h[0]["same_title"]


def test_archive_and_unarchive_from_the_job_list(app_env):
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app
    from autoapply.models import Job

    with db.session() as s:
        j = Job(source="manual", source_id="m1", company="Acme", title="Dev Intern", status="scored", online=1)
        s.add(j)
        s.flush()
        jid = j.id
    c = TestClient(app)
    assert c.post("/api/jobs/bulk", json={"action": "archive", "ids": [jid]}).json()["done"] == 1
    d = c.get("/api/jobs").json()
    assert d["jobs"][0]["archived"] is True and sum(d["counts"].values()) == 0  # still listed, not counted as open work
    c.post("/api/jobs/bulk", json={"action": "unarchive", "ids": [jid]})
    assert c.get("/api/jobs/%d" % jid).json()["archived"] is False


def test_file_endpoints(app_env):
    from fastapi.testclient import TestClient

    from autoapply import config, db
    from autoapply.api.main import app
    from autoapply.models import Document

    config.DATA.mkdir(parents=True, exist_ok=True)
    pdf, txt = config.DATA / "a.pdf", config.DATA / "b.txt"
    pdf.write_bytes(b"%PDF-1.4 test")
    txt.write_text("hello")
    with db.session() as s:
        s.add_all([Document(kind="summary_sheet", name="Summary Sheet", path=str(pdf)), Document(kind="other", name="notes", path=str(txt))])
    c = TestClient(app)
    docs = {d["name"]: d for d in c.get("/api/documents").json()}
    r = c.get("/api/documents/%d/bytes" % docs["Summary Sheet"]["id"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/octet-stream" and r.content.startswith(b"%PDF")
    assert "attachment" not in r.headers.get("content-disposition", "")
    assert c.get("/api/documents/%d/bytes" % docs["notes"]["id"]).status_code == 415
    assert c.post("/api/documents/bulk", json={"action": "stop", "ids": [docs["notes"]["id"]]}).json()["done"] == 1
    assert pdf.exists() and txt.exists()
    c.post("/api/documents/bulk", json={"action": "delete", "ids": [d["id"] for d in docs.values()]})
    assert not pdf.exists() and c.get("/api/documents").json() == []
    assert c.post("/api/documents/bulk", json={"action": "wipe", "ids": []}).status_code == 400


def test_analytics_numbers(app_env):
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app
    from autoapply.models import Application, Job, MailEvent, now

    t = now()
    with db.session() as s:
        for i, (score, status, seen) in enumerate([(9.0, "interview", 10), (8.0, "rejected", 10), (8.0, "confirmed", 10), (6.0, "submitted", -5)]):
            j = Job(source="manual", source_id=str(i), company="C%d" % i, title="Intern", status="applied", online=1, score=score, ats="greenhouse", first_seen=t - timedelta(days=20 + seen))
            s.add(j)
            s.flush()
            a = Application(job_id=j.id, status=status, submitted_at=t - timedelta(days=20))
            s.add(a)
            s.flush()
            if i == 0:
                s.add(MailEvent(message_id="m0", category="interview", application_id=a.id, received_at=t - timedelta(days=16)))
        s.add(Job(source="manual", source_id="x", company="Missed", title="Great Intern", status="scored", online=0, score=9.5, apply_url="https://x.example/job"))
    c = TestClient(app)
    d = c.get("/api/analytics").json()
    assert d["total"] == {"n": 4, "replied": 3, "decided": 2, "positive": 1, "progressed": 1, "rejected": 1, "offer": 0}
    # each step of the funnel is a part of the one before it
    vals = [f["value"] for f in d["funnel"]]
    assert vals == sorted(vals, reverse=True) and vals[0] == 4
    assert sum(x["value"] for x in d["states"]) == 4          # where each application stands now: the parts add up to the whole
    assert {r["label"]: r["n"] for r in d["by_score"]} == {"9–10": 1, "8–8.5": 2, "6–6.5": 1}
    assert d["median_wait_days"] == 4 and d["median_lead_days"] == 10  # the row first seen after it was sent has no lead time
    assert d["missed_total"] == 1 and d["missed"][0]["company"] == "Missed"
    assert c.get("/api/analytics?days=7").json()["total"]["n"] == 0
    # how much of what went out these figures speak about: an application known to be sent without a date is not among them
    assert {k: d["coverage"][k] for k in ("sent", "dated", "undated", "archived")} == {"sent": 4, "dated": 4, "undated": 0, "archived": 0}
    with db.session() as s:
        j = Job(source="manual", source_id="u", company="Undated", title="Intern", status="applied", online=1, score=8.0, ats="greenhouse")
        s.add(j)
        s.flush()
        s.add(Application(job_id=j.id, status="confirmed"))          # found through a mail: no day of sending
        j2 = Job(source="manual", source_id="d", company="Drafted", title="Intern", status="queued", online=1, score=8.0, ats="greenhouse")
        s.add(j2)
        s.flush()
        s.add(Application(job_id=j2.id, status="draft_ready"))       # not sent at all
    d = c.get("/api/analytics").json()
    assert {k: d["coverage"][k] for k in ("sent", "dated", "undated")} == {"sent": 5, "dated": 4, "undated": 1} and d["total"]["n"] == 4
    # the overview's "sent" is the same number, with the same three words from the same code
    with db.session() as s:
        s.query(Job).filter_by(company="C1").one().archived_at = now()      # its posting is over: out of the day-to-day lists, still an application that was sent
    whole = c.get("/api/analytics/sent").json()
    assert whole == c.get("/api/analytics").json()["coverage"]
    assert whole == {"sent": 5, "dated": 4, "undated": 1, "archived": 1, "heard": 4, "decided": 2, "progressed": 1}
    # the three words mean what they mean on the analytics page: the four dated ones gave replied 3, decided 2, progressed 1 there
    assert (whole["heard"] - 1, whole["decided"], whole["progressed"]) == (d["total"]["replied"], d["total"]["decided"], d["total"]["progressed"])
    assert [f["label"] for f in d["funnel"]][1:4] == ["收到回执（确认邮件或任何回复）", "有实质结果（进展或被拒）", "进入在线测评 / 面试"]


def test_a_task_that_ended_is_not_an_application_that_was_sent():
    """"Done" was a success for every task. A filling task that found the application already sent answers with where
    the application stands and has submitted nothing; one that pressed Submit and saw no confirmation has not
    succeeded either - both were counted among the successes or as "handed over to you"."""
    from autoapply import analytics

    o = analytics.outcome
    assert o("execute", "done", {"status": "submitted"}, "") == "success"
    assert o("execute", "done", {"status": "ready_to_submit"}, "") == "handed"
    assert o("execute", "done", {"status": "submit_unknown", "submit_clicked": True}, "") == "unknown"
    assert o("execute", "done", {"status": "confirmed", "note": "already submitted"}, "") == "skipped"
    assert o("execute", "done", {"status": "submitted", "note": "already submitted"}, "") == "skipped"
    assert o("execute", "done", {"status": "submit_unknown", "note": "waiting for the outcome of a submission"}, "") == "skipped"
    assert o("execute", "done", {"status": "failed"}, "") == "failed" and o("execute", "done", {"status": "needs_human"}, "") == "waiting"
    assert o("recon", "done", {"draft_id": 3}, "") == "success" and o("execute", "cancelled", None, "") == "cancelled"
    assert "unknown" in analytics.UNFINISHED and set(analytics.NOT_COUNTED) == {"cancelled", "skipped"}
    assert set(analytics.OUTCOMES) >= {"unknown", "skipped"} and all(analytics.OUTCOMES.values())


def _resume_docx(path):
    from docx import Document as Docx

    d = Docx()
    d.add_paragraph("Jane Doe")
    d.add_paragraph("TECHNICAL SKILLS")
    p = d.add_paragraph()
    p.add_run("Languages: ").bold = True
    p.add_run("Java, Python, Go")
    d.add_paragraph("WORK EXPERIENCE")
    d.add_paragraph("Acme | Developer Intern")
    for t in ["Built a Java service handling 500 requests per second.", "Wrote Python tooling for release checks.", "Fixed 30 bugs in the billing module."]:
        d.add_paragraph(t, style="List Bullet")
    d.add_paragraph("PROJECTS")
    d.add_paragraph("Chess Engine")
    d.add_paragraph("Wrote a chess engine in Go.", style="List Bullet")
    d.add_paragraph("Weather App")
    d.add_paragraph("Built a Python weather dashboard.", style="List Bullet")
    d.save(path)


def test_tailoring_only_reorders_and_rejects_invented_facts(app_env, tmp_path):
    from autoapply import tailor

    f = tmp_path / "r.docx"
    _resume_docx(f)
    st = tailor.parse(str(f))
    work, proj = st["sections"][1], st["sections"][2]
    b = [x["id"] for x in work["entries"][0]["bullets"]]
    e = [x["id"] for x in proj["entries"]]
    plan = {"skills": [{"id": st["sections"][0]["skills"][0]["id"], "items": ["Python", "Go", "Java", "Rust"]}],  # adds a skill: refused
            "entry_order": [{"section": proj["id"], "entries": e[::-1]}, {"section": work["id"], "entries": ["nope"]}],
            "bullets": [{"entry": work["entries"][0]["id"], "keep": [b[1]]}],  # tries to drop two bullets
            "rewrites": [{"id": b[1], "text": "Wrote Python and Kubernetes tooling for 900 release checks."}]}
    select = {"mode": "select", "reorder_skills": True, "reorder_entries": "projects", "allow_drop": False, "min_bullets": 2}
    changes = tailor.apply(st, plan, select)
    kinds = [c["type"] for c in changes]
    assert kinds == ["reorder_bullets", "reorder_entries"]  # no drop, no rewrite, no skill change
    body = [tailor._text(p).strip() for p in st["doc"].element.body.iter(tailor.W + "p")]
    assert body.index("Weather App") < body.index("Chess Engine") and "Java, Python, Go" in body[2]
    assert body.index("Wrote Python tooling for release checks.") < body.index("Built a Java service handling 500 requests per second.")
    assert len([t for t in body if t.startswith(("Built", "Wrote", "Fixed"))]) == 5  # every bullet is still there

    st = tailor.parse(str(f))
    changes = tailor.apply(st, plan, {**select, "mode": "rephrase"})
    rej = [c for c in changes if c["type"] == "rewrite_rejected"]
    assert len(rej) == 1 and not [c for c in changes if c["type"] == "rewrite"]
    assert tailor.rewrite_problem("Built a **Java** service handling 500 requests per second.", "Built a high-throughput **Java** service (500 requests per second).", "Java Python Go") == ""
    assert "900" in tailor.rewrite_problem("Wrote Python tooling for many checks.", "Wrote Python tooling for 900 checks.", "Python")


def test_todos_carry_job_and_urgency(app_env):
    from datetime import timedelta

    from fastapi.testclient import TestClient

    from autoapply import db, notify
    from autoapply.api.main import app
    from autoapply.models import Job, now

    with db.session() as s:
        j = Job(source="manual", source_id="1", company="Acme", title="Intern", status="scored", online=1, score=9.0, apply_url="https://x.example/1",
                deadline=(now() + timedelta(days=2)).strftime("%Y-%m-%d %H:%M"))
        s.add(j)
        s.flush()
        jid = j.id
    notify.add_todo("blocked", "Acme", body="page_not_loading", ref=f"job:{jid}", payload={"job_id": jid, "url": "https://x.example/1"}, push=False)
    notify.add_todo("driver_patch", "note", ref="x:1", push=False)
    c = TestClient(app)
    rows = {r["kind"]: r for r in c.get("/api/todos").json()}
    assert rows["blocked"]["job"]["company"] == "Acme" and rows["blocked"]["urgency"] == 1 and rows["blocked"]["category"] == "problem"
    assert rows["driver_patch"]["urgency"] == 3 and rows["driver_patch"]["category"] == "info"
    assert c.post(f"/api/jobs/{jid}/mark-submitted").json() == {"ok": True}
    assert [r["kind"] for r in c.get("/api/todos").json()] == ["driver_patch"]
    assert c.get(f"/api/jobs/{jid}").json()["app_status"] == "submitted"
    assert c.post("/api/todos/bulk", json={"ids": [rows["driver_patch"]["id"]]}).json()["done"] == 1


def test_contacts_show_up_next_to_the_employers_postings(app_env):
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app
    from autoapply.models import Job

    with db.session() as s:
        j = Job(source="manual", source_id="1", company="RBC Capital Markets", title="Analyst", status="scored", online=1)
        s.add_all([j, Job(source="manual", source_id="2", company="Other Co", title="Analyst", status="scored", online=1)])
        s.flush()
        jid = j.id
    c = TestClient(app)
    assert c.post("/api/contacts", json={"name": " ", "company": "RBC"}).status_code == 400
    r = c.post("/api/contacts", json={"name": "Dana Lee", "company": "RBC", "relation": "alumni", "status": "asked", "follow_up": "2020-01-01"}).json()
    c.post("/api/contacts", json={"name": "Sam", "company": "Zeta"})
    rows = c.get("/api/contacts").json()
    assert rows[0]["name"] == "Dana Lee" and rows[0]["open_jobs"] == 0  # overdue follow-ups first
    assert [x["name"] for x in c.get(f"/api/jobs/{jid}").json()["contacts"]] == ["Dana Lee"]  # "RBC" matches "RBC Capital Markets"
    c.put(f"/api/contacts/{r['id']}", json={"status": "referred", "follow_up": ""})
    assert c.get(f"/api/jobs/{jid}").json()["contacts"][0]["status"] == "referred"
    c.delete(f"/api/contacts/{r['id']}")
    assert c.get(f"/api/jobs/{jid}").json()["contacts"] == [] and len(c.get("/api/contacts").json()) == 1
