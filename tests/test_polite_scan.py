"""A scan asks a site for no more than it needs, and backs off when told to."""
import httpx


def test_a_workday_scan_reads_only_new_postings_it_would_keep_and_waits_when_told(app_env, monkeypatch):
    from autoapply import db
    from autoapply.models import Job
    from autoapply.sources import public

    with db.session() as s:
        s.add(Job(source="workday", source_id="acme:JR1", company="Acme", title="Known Intern", apply_url="https://acme.wd1.myworkdayjobs.com/en-US/Ext/job/x_JR1", jd_text="x" * 300))
    calls, slept = [], []
    monkeypatch.setattr("time.sleep", lambda t: slept.append(t))
    busy = {"n": 1}

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path))
        if req.method == "POST":
            if busy["n"]:      # the site says "too many requests" once, and how long to wait
                busy["n"] -= 1
                return httpx.Response(429, headers={"Retry-After": "7"})
            import json

            offset = json.loads(req.content)["offset"]
            posts = [{"title": "Known Intern", "externalPath": "/job/x_JR1", "bulletFields": ["JR1"]},
                     {"title": "Sales Director", "externalPath": "/job/y_JR2", "bulletFields": ["JR2"]},
                     {"title": "Software Intern", "externalPath": "/job/z_JR3-1", "bulletFields": ["JR3"]}] if offset == 0 else []
            return httpx.Response(200, json={"jobPostings": posts})
        return httpx.Response(200, json={"jobPostingInfo": {"jobReqId": "JR3", "jobDescription": "<p>Build things</p>"}, "hiringOrganization": {"name": "Acme Corp"}})

    real = httpx.Client
    monkeypatch.setattr(public.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"}))
    rows = list(public.workday("acme.wd1.myworkdayjobs.com", "acme", "Ext", keep=lambda title, where: "Intern" in title, company="Acme"))
    assert [r["source_id"] for r in rows] == ["acme:JR1", "acme:JR2", "acme:JR3"]
    assert "jd_text" not in rows[0] and "jd_text" not in rows[1] and "Build things" in rows[2]["jd_text"] and rows[2]["company"] == "Acme Corp"
    assert [c for c in calls if c[0] == "GET"] == [("GET", "/wday/cxs/acme/Ext/job/z_JR3-1")]      # one description, not three
    assert 7 in slept      # waited as long as the site asked, then went on
