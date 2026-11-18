"""Run the application agent on the evaluation forms and say how it did.

    python eval/run.py [--form profile_first] [--model claude-fable-5-2] [--headed] [--backend playwright|nodriver] [--out DIR]

One made-up applicant, local forms shaped like real ones, a fresh data folder each time. A run is judged by what the
form's server received. This spends the model allowance of whoever runs it; nothing leaves the machine but the model
requests.

What a form is run through (each run in a new browser window, with nothing but the application's folder carried over):
    1. "auto" with the applicant's files and profile: one question of the form is not in the profile, so the run must
       fill everything else, save it, ask - and NOT send.
    2. "auto" again, with the applicant's answer: the run must find what the site kept, finish and send, and bring
       back a confirmation that names the posting.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROFILE = """# Applicant profile

## Identity & contact

- Name: Alex Chen (legal name: Alexander Chen; goes by Alex)
- E-mail: alex.chen@example.com
- Phone: +1 604-555-0143 (Canada, mobile)
- Lives in: Vancouver, British Columbia, Canada. Address: 2100 Example Street, Vancouver, BC V6T 1Z4
- Links: portfolio https://alexchen.example ; GitHub https://github.com/alexchen-example

## Education

- University of British Columbia, Bachelor of Applied Science (BASc) in Computer Engineering, Sept 2024 - May 2029.
  The graduation date is May 2029 (an older résumé says 2028: that is out of date).

## Work authorization

- Canadian citizen. Needs no sponsorship in Canada.

## Availability

- Looking for a co-op term of four or eight months. Open to Toronto and Waterloo (Ontario); not looking in Vancouver for this search.

## Standard answers

- Has never worked for any employer other than those under Experience. Is over 18.
- Gender: man. Race / ethnicity: Asian (East Asian). No disability. Not a veteran. Answers these when asked.

## Experience

- Software Engineering Co-op, Contoso (May 2026 - Aug 2026): built the export API of the billing service (Go, PostgreSQL); cut report generation from 40 s to 6 s.
- Projects (NOT jobs): PaperTrail (Apr 2026 - present), a document search tool - TypeScript, React, Python.

## Skills

- Python, Go, TypeScript, React, PostgreSQL, Docker.

## Rules

- A project is never entered as a job.
"""
RESUME = """Alex Chen
alex.chen@example.com | +1 604-555-0143 | Vancouver, BC

EDUCATION
University of British Columbia - BASc Computer Engineering, expected May 2028

EXPERIENCE
Contoso - Software Engineering Co-op, May 2026 - Aug 2026
- Built the export API of the billing service in Go on PostgreSQL
- Cut report generation from 40 s to 6 s

PROJECTS
PaperTrail, Apr 2026 - present
- Document search tool in TypeScript, React and Python

SKILLS
Python, Go, TypeScript, React, PostgreSQL, Docker
"""
ANSWERS = {"profile_first": "2027-01-04"}      # what the applicant says when asked for the earliest start date


def _digits(s: str) -> str:
    return "".join(c for c in str(s) if c.isdigit())


def grade_profile_first(saved: dict, sent: list, result, stage: int) -> list[tuple[str, bool, str]]:
    """(what, ok, seen) for each thing a careful person would have got right."""
    p, role, me = saved.get("profile") or {}, saved.get("role") or {}, saved.get("self") or {}
    rec = result.record or {}
    jobs = p.get("jobs") or []
    checks = [
        ("the profile step was saved (the form went past 'Submit profile & continue')", int(saved.get("step") or 0) >= 1, f"step {saved.get('step')}"),
        ("name", (p.get("first"), p.get("last")) == ("Alex", "Chen"), f"{p.get('first')} {p.get('last')}"),
        ("country", p.get("country") == "Canada", str(p.get("country"))),
        ("phone code and number", p.get("code") == "Canada (+1)" and _digits(p.get("phone"))[-10:] == "6045550143", f"{p.get('code')} {p.get('phone')}"),
        ("school, picked from the suggestions", p.get("school") == "University of British Columbia", str(p.get("school"))),
        ("degree mapped to an entry of the list", p.get("degree") in ("Bachelor of Engineering", "Bachelor's Degree - Other"), str(p.get("degree"))),
        ("graduation date as the profile says, not as the résumé was parsed", "2029" in str(p.get("grad")) and "2028" not in str(p.get("grad")), str(p.get("grad"))),
        ("résumé attached", bool(p.get("resume")), str(p.get("resume"))),
        ("the project the parser took for a job is removed, the job is kept", len(jobs) == 1 and jobs[0].get("employer") == "Contoso" and bool(jobs[0].get("title")), json.dumps(jobs)[:160]),
        ("skills from the profile added", {"Python", "Go", "TypeScript", "React.js", "PostgreSQL", "Docker"} <= set(p.get("skills") or []), str(p.get("skills"))),
    ]
    if stage == 1:
        checks += [
            ("NOT sent while a question is open", not sent, f"sent {len(sent)} time(s)"),
            ("the question the profile does not answer was put to the applicant", any("start" in q.get("question", "").lower() for q in (rec.get("asked") or [])), str([q.get("question") for q in rec.get("asked") or []])[:200]),
            ("the run said how it ended", result.outcome in ("ready", "needs_you"), result.outcome or f"no report ({result.stopped})"),
        ]
    else:
        last = sent[-1] if sent else {}
        conf = rec.get("confirmation") or {}
        checks += [
            ("locations", set(role.get("locations") or []) == {"Toronto, ON, Canada", "Waterloo, ON, Canada"}, str(role.get("locations"))),
            ("the applicant's answer was used", role.get("start") == "2027-01-04", str(role.get("start"))),
            ("worked here before: No", role.get("worked_before") == "No", str(role.get("worked_before"))),
            ("voluntary questions as the profile says", (me.get("gender"), me.get("ethnicity")) == ("Man", "Asian"), f"{me.get('gender')} / {me.get('ethnicity')}"),
            ("sent, once", len(sent) == 1 and bool(last.get("certify")), f"sent {len(sent)} time(s)"),
            ("reported as submitted", result.outcome == "submitted", result.outcome or f"no report ({result.stopped})"),
            ("the confirmation is the list entry of this posting", "submitted" in str(conf.get("words", "")).lower() and "software developer intern" in (str(conf.get("words", "")) + str(conf.get("ties_to_posting", ""))).lower(),
             json.dumps(conf, ensure_ascii=False)[:220]),
        ]
    return checks


def grade_embedded(saved: dict, sent: list, result, stage: int) -> list[tuple[str, bool, str]]:
    s = sent[-1] if sent else {}
    conf = (result.record or {}).get("confirmation") or {}
    why = str(s.get("why") or "")
    return [
        ("sent, once (nothing was open: a run told to send when nothing is open sends)", len(sent) == 1, f"sent {len(sent)} time(s); outcome {result.outcome or result.stopped}"),
        ("name, e-mail, phone", (s.get("first"), s.get("last"), s.get("email")) == ("Alex", "Chen", "alex.chen@example.com") and _digits(s.get("phone"))[-10:] == "6045550143",
         f"{s.get('first')} {s.get('last')} {s.get('email')} {s.get('phone')}"),
        ("résumé attached; no cover letter (optional, none on file)", bool(s.get("resume")) and not s.get("cover"), f"{s.get('resume')} / {s.get('cover')}"),
        ("each link in its own field; none invented", s.get("website") == "https://alexchen.example" and s.get("github") == "https://github.com/alexchen-example" and not s.get("linkedin"),
         f"website {s.get('website')} | github {s.get('github')} | linkedin {s.get('linkedin')}"),
        ("the free-text answer is written, within the limit", 200 <= len(why) <= 1500, f"{len(why)} characters"),
        ("the free-text answer uses the applicant's own experience", any(w in why for w in ("Contoso", "billing", "PaperTrail", "export API")), why[:160]),
        ("work authorization and sponsorship", (s.get("authorized"), s.get("sponsorship")) == ("Yes", "No"), f"{s.get('authorized')} / {s.get('sponsorship')}"),
        ("voluntary questions as the profile says", s.get("gender") == "Male" and str(s.get("disability") or "").startswith("No"), f"{s.get('gender')} / {s.get('disability')}"),
        ("consent ticked", bool(s.get("consent")), str(s.get("consent"))),
        ("reported as submitted, with the reference number", result.outcome == "submitted" and "FBK-48213" in json.dumps(conf), json.dumps(conf, ensure_ascii=False)[:200] or (result.outcome or result.stopped)),
    ]


def grade_account(saved: dict, sent: list, result, stage: int, folder: Path | None = None) -> list[tuple[str, bool, str]]:
    acct, info, exp, q = saved.get("account") or {}, saved.get("info") or {}, saved.get("exp") or {}, saved.get("q") or {}
    conf = (result.record or {}).get("confirmation") or {}
    pw = str(acct.get("pw") or "")
    written = "".join(p.read_text(encoding="utf-8", errors="replace") for p in (folder.glob("*") if folder else []) if p.is_file())
    jobs, schools = exp.get("jobs") or [], exp.get("schools") or []
    return [
        ("an account was made with the applicant's e-mail", acct.get("email") == "alex.chen@example.com" and len(pw) >= 12, f"{acct.get('email')} / password of {len(pw)} characters"),
        ("the password is nowhere in what the agent was told, did or wrote", bool(pw) and pw not in written, "found in the application's folder" if pw and pw in written else "no password"),
        ("the legal name where the form asks for it", (info.get("first"), info.get("last")) == ("Alexander", "Chen"), f"{info.get('first')} {info.get('last')}"),
        ("address", "2100 Example" in str(info.get("address")) and info.get("city") == "Vancouver" and info.get("province") == "British Columbia" and str(info.get("postal")).replace(" ", "").upper() == "V6T1Z4",
         f"{info.get('address')}, {info.get('city')}, {info.get('province')} {info.get('postal')}"),
        ("phone", info.get("phone_type") == "Mobile" and _digits(info.get("phone"))[-10:] == "6045550143", f"{info.get('phone_type')} {info.get('phone')}"),
        ("résumé attached", bool(exp.get("resume")), str(exp.get("resume"))),
        ("the job is entered by hand, with its dates; the project is not entered as a job", len(jobs) == 1 and jobs[0].get("company") == "Contoso" and (jobs[0].get("from"), jobs[0].get("to")) == ("05/2026", "08/2026"), json.dumps(jobs)[:200]),
        ("education entered", len(schools) == 1 and "British Columbia" in schools[0].get("school", "") and schools[0].get("degree") == "Bachelor's Degree" and "Computer Engineering" in schools[0].get("field", ""), json.dumps(schools)[:200]),
        ("application questions", (q.get("adult"), q.get("onsite")) == ("Yes", "Yes"), f"{q.get('adult')} / {q.get('onsite')}"),
        ("sent, once", len(sent) == 1, f"sent {len(sent)} time(s); outcome {result.outcome or result.stopped}"),
        ("reported as submitted, with the application number", result.outcome == "submitted" and "R-20931" in json.dumps(conf), json.dumps(conf, ensure_ascii=False)[:200] or (result.outcome or result.stopped)),
    ]


GRADERS = {"profile_first": grade_profile_first, "embedded": grade_embedded, "account": grade_account}
STAGES = {"profile_first": "1,2", "embedded": "1", "account": "1"}


def through_the_queue(a, home: Path, posting, applicant, state) -> None:  # noqa: ANN001
    """The same form, worked the way the program works a posting: `recon` in the queue, the agent's record in the
    drafts table, the applicant's answer given in the record, and - the policy being "send when nothing is open" -
    the agent going on by itself."""
    from autoapply import db, drafts, handlers, knowledge, tasks  # noqa: F401
    from autoapply.agent import run, work
    from autoapply.models import Document, Job

    knowledge.write("profile", applicant.profile)
    db.set_setting("account.email", applicant.login)
    db.set_setting("policy.default", "auto_approve")
    db.set_setting("browser.default_headless", True)
    with db.session() as s:
        for name, path in applicant.files.items():
            s.add(Document(kind="resume_docx", name=name, path=path))
        j = Job(source="manual", source_id=a.form, company=posting.company, title=posting.title, apply_url=posting.url, jd_text=posting.text, status="queued", online=1, channel="employer site")
        s.add(j)
        s.flush()
        job_id = j.id

    def where() -> tuple[str, int, int]:
        with db.session() as s:
            app = s.get(Job, job_id).application
            d = app.drafts[-1] if app and app.drafts else None
            return (app.status if app else "-", d.id if d else 0, len(d.unresolved) if d else 0)

    results: list = []
    real = run.apply

    def seen(*args, **kw):  # noqa: ANN002, ANN003, ANN202
        results.append(real(*args, **kw))
        return results[-1]

    run.apply = seen
    began = time.time()
    tasks.enqueue("recon", ref=f"job:{job_id}", payload={"job_id": job_id})
    n = tasks.drain()
    status, draft_id, open_n = where()
    print(f"--- first pass: {n} task(s) · application {status} · {open_n} question(s) open · {results[-1].steps if results else 0} tool calls · {time.time() - began:.0f} s", flush=True)
    stage = 1
    if open_n:
        with db.session() as s:
            from autoapply.models import Draft

            rows = [(u["id"], u["label"]) for u in s.get(Draft, draft_id).unresolved]
        for qid, label in rows:
            print(f"  the applicant answers {label[:90]!r}: {ANSWERS[a.form]}")
            drafts.edit_answer(draft_id, qid, ANSWERS[a.form])
        began = time.time()
        n = tasks.drain()
        status, draft_id, open_n = where()
        stage = 2
        print(f"--- second pass: {n} task(s) · application {status} · {results[-1].steps} tool calls · {time.time() - began:.0f} s", flush=True)
    result = results[-1] if results else run.Result()
    checks = GRADERS[a.form](*state(), result, stage, **({"folder": work.folder_of(1)} if a.form == "account" else {}))
    with db.session() as s:
        app = s.get(Job, job_id).application
        checks.append(("the application is recorded as sent, with its evidence", app.status == "submitted" and bool((app.evidence or {}).get("text")), f"{app.status} / {json.dumps(app.evidence or {}, ensure_ascii=False)[:160]}"))
    ok = sum(1 for _, good, _ in checks if good)
    for what, good, saw in checks:
        print(f"  {'ok  ' if good else 'MISS'} {what}" + ("" if good else f"   [saw: {saw}]"))
    print(f"score: {ok} / {len(checks)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--form", default="profile_first", choices=sorted(GRADERS))
    ap.add_argument("--model", default="")
    ap.add_argument("--effort", default="")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--backend", default="playwright", choices=["playwright", "nodriver"])
    ap.add_argument("--out", default="")
    ap.add_argument("--stages", default="")
    ap.add_argument("--site", default="", help="a site that is already running (python eval/server.py PORT): it outlives this run")
    ap.add_argument("--kill-after", type=int, default=0, help="end this process abruptly after that many tool calls - as a crash would")
    ap.add_argument("--queue", action="store_true", help="through the program: a posting in its database, its queue, the record it keeps, the applicant answering in the record")
    a = ap.parse_args()

    home = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix="autoapply-eval-"))
    (home / "data").mkdir(parents=True, exist_ok=True)
    (home / "knowledge").mkdir(parents=True, exist_ok=True)
    os.environ.update(AUTOAPPLY_DATA=str(home / "data"), AUTOAPPLY_KNOWLEDGE=str(home / "knowledge"), AUTOAPPLY_KEYRING_SERVICE="autoapply-eval")
    sys.path.insert(0, str(ROOT / "backend"))
    sys.path.insert(0, str(ROOT / "eval"))
    import docx

    from autoapply import browser, db
    from autoapply.agent import brief, run
    from server import POSTINGS, Site

    db.init_db()
    if a.model:
        db.set_setting("llm.model", a.model)
    if a.effort:
        db.set_setting("llm.effort", a.effort)
    if a.backend == "nodriver":
        db.set_setting("browser.nodriver_enabled", True)
    resume = home / "Alex_Chen_Resume.docx"
    d = docx.Document()
    for ln in RESUME.splitlines():
        d.add_paragraph(ln)
    d.save(str(resume))
    applicant = brief.Applicant(profile=PROFILE, resume=RESUME, files={resume.name: str(resume)}, file_notes={resume.name: "résumé (Word)"}, login="alex.chen@example.com")
    site = None if a.site else Site()
    base = a.site.rstrip("/") or site.base

    def state() -> tuple[dict, list]:
        if site is not None:
            return site.saved.get(a.form) or {}, site.sent.get(a.form) or []
        import urllib.request

        got = json.loads(urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f"{base}/__/state?form={a.form}", timeout=10).read())
        return got["saved"], got["sent"]

    if a.kill_after:
        seen, real = [0], run.Desk.step

        def counted(self, step):  # noqa: ANN001, ANN202
            real(self, step)
            seen[0] += 1
            if seen[0] >= a.kill_after:
                print(f"(killed after {seen[0]} tool calls, as asked)", flush=True)
                os._exit(3)

        run.Desk.step = counted
    p = POSTINGS[a.form]
    posting = brief.Posting(company=p["company"], title=p["title"], url=f"{base}/jobs/{a.form}", text=p["text"])
    folder = home / "applications" / a.form
    if a.queue:
        through_the_queue(a, home, posting, applicant, state)
        if site is not None:
            site.close()
        return
    print(f"form {a.form} at {posting.url}\nmodel {db.get_setting('llm.model')} ({db.get_setting('llm.effort')}), browser {a.backend}\neverything this leaves behind: {home}\n", flush=True)
    total = passed = 0
    for stage in [int(x) for x in (a.stages or STAGES[a.form]).split(",")]:
        answers = None if stage == 1 else {q["question"]: ANSWERS[a.form] for q in json.loads((folder / "questions.json").read_text(encoding="utf-8"))} if (folder / "questions.json").exists() else {"earliest start date": ANSWERS[a.form]}
        began = time.time()
        with browser.open_page(None, headless=not a.headed, backend=a.backend) as page:      # a new window every time: nothing of the last run is in it
            result = run.apply(page, posting, applicant, folder, mode="auto", answers=answers)
        checks = GRADERS[a.form](*state(), result, stage, **({"folder": folder} if a.form == "account" else {}))
        ok = sum(1 for _, good, _ in checks if good)
        total, passed = total + len(checks), passed + ok
        print(f"--- run {stage}: {result.outcome or 'no report'} · {result.steps} tool calls · {result.seconds:.0f} s (wall {time.time() - began:.0f} s) · stopped: {result.stopped}")
        for what, good, seen in checks:
            print(f"  {'ok  ' if good else 'MISS'} {what}" + ("" if good else f"   [saw: {seen}]"))
        if result.record.get("summary"):
            print("  the agent's own summary:", str(result.record["summary"])[:700].replace("\n", " "))
        print(f"  {ok} / {len(checks)}\n", flush=True)
    print(f"score: {passed} / {total}")
    if site is not None:
        site.close()


if __name__ == "__main__":
    main()
