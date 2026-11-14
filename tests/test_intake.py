"""Intake rules, duplicate linking, and the PD Portal import endpoint."""


def test_intake_rules(app_env):
    from autoapply import db, intake

    r = intake.rules()
    ok = lambda t, loc="": intake.check({"source": "amazon", "title": t, "location": loc}, r)  # noqa: E731
    assert ok("Software Development Engineer Intern - 2027", "Toronto, Ontario, CAN") == ""
    assert ok("Software Developer Co-op", "Vancouver, BC, Canada") == ""
    assert ok("Software Engineering Internship", "Seattle, WA, US") == ""  # "internship" counts as intern
    assert ok("Internal Tools Software Engineer", "Seattle, WA, US") == "kind"  # "internal" is not "intern"
    assert ok("Senior Software Engineer", "Toronto, ON, CA") == "kind"
    assert ok("MBA Intern", "New York, NY, US") == "role"
    assert ok("Software Engineering PhD Intern", "Mountain View, CA, USA") == "excluded"
    assert ok("Software Engineering Intern", "Singapore, Singapore") == "country"
    assert ok("Software Engineering Intern", "Madrid, MD, ES") == "country"  # MD here is a Spanish region, not Maryland
    assert ok("Software Engineering Intern", "") == ""  # unknown location is not a reason to drop
    assert intake.check({"source": "pdportal", "title": "Marketing Assistant", "location": "Tokyo"}, r) == ""  # exempt source
    assert intake.check({"source": "amazon", "title": "Software Engineer Intern", "location": "Seattle, WA, US", "posted": "2020-01-01"}, r) == "old"
    db.set_setting("intake.enabled", False)
    assert intake.check({"source": "amazon", "title": "Chef", "location": "Paris"}) == ""

    stats = {}
    db.set_setting("intake.enabled", True)
    kept = list(intake.apply([{"source": "x", "title": "Software Intern"}, {"source": "x", "title": "Sales Manager"}, {"source": "x", "title": "Data Engineer Intern", "location": "London, UK"}], stats))
    assert [k["title"] for k in kept] == ["Software Intern"] and stats == {"read": 3, "kept": 1, "dropped": {"kind": 1, "country": 1}}


def test_same_posting_from_two_sources_is_merged(app_env):
    from autoapply import db, discover
    from autoapply.models import Application, Job

    with db.session() as s:
        s.add(Job(source="pdportal", source_id="150001", company="Microsoft Corporation", title="Software Engineer Intern", term="Summer 2027", status="scored", online=1,
                  apply_url="https://pdportal.apsc.ubc.ca/myAccount/co-op/postings.htm#posting=150001", deadline="2026-12-01 23:59"))
        s.add(Job(source="microsoft", source_id="200057714", company="Microsoft", title="Software Engineer Intern", term="Summer 2027", status="new", online=1,
                  apply_url="https://apply.careers.microsoft.com/careers/job/1970393557007359", jd_text="x" * 500, location="Redmond, WA, US"))
        # same link listed twice with different tracking parameters
        s.add(Job(source="pdportal", source_id="150002", company="Acme", title="Developer Co-op (Winter)", status="scored", online=1, apply_url="https://jobs.ashbyhq.com/acme/abc?utm_source=ubc"))
        s.add(Job(source="ashby", source_id="acme:abc", company="acme", title="Developer Co-op", status="new", online=1, apply_url="https://jobs.ashbyhq.com/acme/abc"))
        # same title at the same company from ONE source: two real postings, not duplicates
        s.add(Job(source="amazon", source_id="1", company="Amazon", title="SDE Intern", status="new", online=1, apply_url="https://www.amazon.jobs/en/jobs/1/x"))
        s.add(Job(source="amazon", source_id="2", company="Amazon", title="SDE Intern", status="new", online=1, apply_url="https://www.amazon.jobs/en/jobs/2/x"))
    assert discover.link_duplicates() == 2
    with db.session() as s:
        ms_pd, ms_site = s.query(Job).filter_by(source_id="150001").one(), s.query(Job).filter_by(source_id="200057714").one()
        assert ms_site.duplicate_of == ms_pd.id and ms_pd.duplicate_of is None  # the PD Portal row stays the main one
        assert ms_pd.apply_url.startswith("https://apply.careers.microsoft.com") and len(ms_pd.jd_text) == 500 and ms_pd.location  # and takes the official link and description
        assert s.query(Job).filter_by(source_id="acme:abc").one().duplicate_of == s.query(Job).filter_by(source_id="150002").one().id
        assert all(j.duplicate_of is None for j in s.query(Job).filter_by(source="amazon"))
        # a listing that was already applied to is never demoted
        s.add(Job(source="google", source_id="g1", company="Acme", title="Developer Co-op (Winter)", status="scored", online=1, apply_url="https://x.example/job/9"))
        s.flush()
        s.add(Application(job_id=s.query(Job).filter_by(source_id="g1").one().id, status="submitted"))
    discover.link_duplicates()
    with db.session() as s:
        assert s.query(Job).filter_by(source_id="g1").one().duplicate_of is None
    assert discover.link_duplicates() == 0  # stable on a second pass


def test_pdportal_import_endpoint(app_env):
    from fastapi.testclient import TestClient

    from autoapply import db
    from autoapply.api.main import app
    from autoapply.models import Job

    text = ("Software Developer Co-op\nORGANIZATION INFORMATION\nOrganization:\nAcme Robotics\nJob Title:\nSoftware Developer Co-op\nApplication Deadline:\nDecember 1, 2026 11:59 PM\n"
            "Application Receipt Procedure:\nEmployer Website\nIf by Website, go to:\nhttps://jobs.ashbyhq.com/acme/abc\nJob Description:\n" + "Build things. " * 40)
    with db.session() as s:
        s.add(Job(source="pdportal", source_id="149000", company="Old", title="Old posting", status="scored", online=1, jd_text="y" * 300))
    c = TestClient(app)
    hdr = {"origin": "https://pdportal.apsc.ubc.ca"}
    pre = c.options("/api/import/pdportal", headers={**hdr, "access-control-request-method": "POST", "access-control-request-private-network": "true"})
    assert pre.status_code == 204 and pre.headers["access-control-allow-private-network"] == "true"
    assert c.options("/api/jobs", headers={"origin": "https://evil.example", "access-control-request-method": "GET"}).headers.get("access-control-allow-origin") is None
    assert c.get("/api/import/pdportal/known", headers=hdr).json() == {"ids": ["149000"]}
    c.post("/api/import/pdportal", json={"details": [{"id": "150999", "text": text}]}, headers=hdr)
    out = c.post("/api/import/pdportal", json={"details": [], "all_ids": ["150999"], "done": True}, headers=hdr).json()
    assert out["offline"] == 1 and out["listed"] == 1
    with db.session() as s:
        j = s.query(Job).filter_by(source_id="150999").one()
        assert j.online and j.deadline == "2026-12-01 23:59" and "ashbyhq" in j.apply_url
        assert not s.query(Job).filter_by(source_id="149000").one().online
        assert s.query(Job).count() == 2  # bare ids never create rows
