"""Run the application agent on the evaluation forms and say how it did.

    python eval/run.py [--form profile_first] [--model claude-fable-5-2] [--headed] [--backend playwright|nodriver] [--out DIR]
    python eval/run.py --form account --queue        the same form through the program's queue, record and cards
    python eval/run.py --scan                        the agent reads a co-op portal: a sign-in, a list on two pages
    python eval/run.py --portal-apply                an application inside that portal: documents uploaded, a package made, sent
    python eval/run.py --all                         every form and the portal, one after the other

The forms (--form): profile_first (a profile sent first, a résumé parsed wrongly, a question the profile does not
answer), embedded (a form in a frame of another origin), account (an account to be made, steps saved one by one),
widgets (the page's own lists, cards and file window; an objection only when the form is sent), returning (an account
the applicant has, an old draft to be put right, a confirmation that is only a line in a list), closed (the posting has
been taken down), approve (the applicant approves the record before it is sent), hand_over (the last press is theirs).

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


def grade_widgets(saved: dict, sent: list, result, stage: int) -> list[tuple[str, bool, str]]:
    s = sent[-1] if sent else {}
    conf = (result.record or {}).get("confirmation") or {}
    return [
        ("sent, once (an objection made when the form was sent is not a second application)", len(sent) == 1, f"sent {len(sent)} time(s); outcome {result.outcome or result.stopped}"),
        ("name and e-mail", (s.get("first"), s.get("last"), s.get("email")) == ("Alex", "Chen", "alex.chen@example.com"), f"{s.get('first')} {s.get('last')} {s.get('email')}"),
        ("the phone number the way the site insists on it", s.get("phone") == "6045550143", f"{s.get('phone')} (the site objected {s.get('refused')} time(s))"),
        ("country and province, chosen in the page's own lists", (s.get("country"), s.get("province")) == ("Canada", "British Columbia"), f"{s.get('country')} / {s.get('province')}"),
        ("city", s.get("city") == "Vancouver", str(s.get("city"))),
        ("graduation date as the profile says, in the form's own format", s.get("grad") == "05/2029", str(s.get("grad"))),
        ("the length of term the posting is for", s.get("term") == "8 months", str(s.get("term"))),
        ("offices: Toronto, and not the ones the applicant is not looking at", s.get("offices") == ["Toronto"], str(s.get("offices"))),
        ("entitled to work, on what basis (asked only after 'Yes'), sponsorship", (s.get("entitled"), s.get("basis"), s.get("sponsorship")) == ("Yes", "Canadian citizen", "No"),
         f"{s.get('entitled')} / {s.get('basis')} / {s.get('sponsorship')}"),
        ("never employed there", s.get("before") == "No", str(s.get("before"))),
        ("résumé given through the file window", bool(s.get("resume")), str(s.get("resume"))),
        ("reported as submitted, with the reference", result.outcome == "submitted" and "ADT-77120" in json.dumps(conf), json.dumps(conf, ensure_ascii=False)[:200] or (result.outcome or result.stopped)),
    ]


# What the site kept of an application begun weeks ago: true then, not now.
OLD_DRAFT = {"account": {"email": "alex.chen@example.com"}, "step": 0, "contact": {"first": "Alex", "last": "Chen", "email": "alex.chen@example.com", "phone": "+1 778-555-0199", "city": "Burnaby"},
             "edu": {"school": "University of British Columbia", "degree": "BASc Computer Engineering", "grad": "05/2028", "office": "Vancouver", "adult": "Yes"},
             "resume": "Alex_Chen_Resume_2025.pdf", "submitted": False, "submitted_on": "", "created": 0}


def _written(folder: Path | None) -> str:
    return "".join(p.read_text(encoding="utf-8", errors="replace") for p in (folder.glob("*") if folder else []) if p.is_file())


def _journal(folder: Path | None) -> list[dict]:
    out = []
    if folder and (folder / "journal.jsonl").exists():
        for ln in (folder / "journal.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    return out


def grade_returning(saved: dict, sent: list, result, stage: int, folder: Path | None = None, site=None) -> list[tuple[str, bool, str]]:  # noqa: ANN001
    s = sent[-1] if sent else {}
    c, e = s.get("contact") or {}, s.get("edu") or {}
    acct = (site.logins.get("returning") if site is not None else None) or {}
    pw = str(acct.get("password") or "")
    conf = (result.record or {}).get("confirmation") or {}
    words = (str(conf.get("words", "")) + " " + str(conf.get("ties_to_posting", ""))).lower()
    return [
        ("signed in with the login on record, and the site never refused a password", acct.get("signed_in", 0) >= 1 and acct.get("refused", 0) == 0, f"signed in {acct.get('signed_in')}, refused {acct.get('refused')}"),
        ("no second account was tried", not (saved.get("created") or 0), f"tried {saved.get('created')} time(s)"),
        ("the password is nowhere in what the agent was told, did or wrote", bool(pw) and pw not in _written(folder), "found in the application's folder" if pw else "no password"),
        ("the old phone number was put right", _digits(c.get("phone"))[-10:] == "6045550143", str(c.get("phone"))),
        ("the old city was put right", c.get("city") == "Vancouver", str(c.get("city"))),
        ("the graduation date of the old résumé was put right", e.get("grad") == "05/2029", str(e.get("grad"))),
        ("the office the applicant is not looking at was changed", e.get("office") == "Toronto", str(e.get("office"))),
        ("the old résumé was replaced by the one on file now", s.get("resume") == "Alex_Chen_Resume.docx", str(s.get("resume"))),
        ("what was right was left as it was", (c.get("first"), c.get("last"), e.get("school"), e.get("adult")) == ("Alex", "Chen", "University of British Columbia", "Yes"),
         f"{c.get('first')} {c.get('last')} / {e.get('school')} / {e.get('adult')}"),
        ("sent, once", len(sent) == 1, f"sent {len(sent)} time(s); outcome {result.outcome or result.stopped}"),
        ("reported as submitted; the confirmation is this posting's line in the list of applications", result.outcome == "submitted" and "submitted" in words and "full-stack" in words,
         json.dumps(conf, ensure_ascii=False)[:220] or (result.outcome or result.stopped)),
    ]


def grade_closed(saved: dict, sent: list, result, stage: int, site=None) -> list[tuple[str, bool, str]]:  # noqa: ANN001
    everything = {k: len(v) for k, v in site.sent.items()} if site is not None else {}
    rec = result.record or {}
    return [
        ("nothing was sent - not to another opening of the same employer either", not any(everything.values()), str(everything)),
        ("reported that this cannot be applied for", result.outcome == "cannot", result.outcome or f"no report ({result.stopped})"),
        ("the applicant was not asked anything", not rec.get("asked"), str([q.get("question") for q in rec.get("asked") or []])[:200]),
    ]


def grade_approve(saved: dict, sent: list, result, stage: int, folder: Path | None = None) -> list[tuple[str, bool, str]]:
    import difflib

    rec = result.record or {}
    said = [e for e in _journal(folder) if e.get("kind") == "sending"]
    if stage == 1:
        return [
            ("NOT sent: this run prepares, and the applicant has not seen the record yet", not sent, f"sent {len(sent)} time(s)"),
            ("a press of the last button was not announced either", not said, f"announced {len(said)} time(s)"),
            ("reported as ready", result.outcome == "ready", result.outcome or f"no report ({result.stopped})"),
            ("the record says what was entered, question by question", len(rec.get("answers") or []) >= 8, f"{len(rec.get('answers') or [])} entries"),
        ]
    approved = json.loads((folder / "approved.json").read_text(encoding="utf-8")) if folder and (folder / "approved.json").exists() else {}
    longest = max((str(a.get("entered") or "") for a in approved.get("answers") or []), key=len, default="")
    why = str((sent[-1] if sent else {}).get("why") or "")
    same = difflib.SequenceMatcher(None, " ".join(longest.split()), " ".join(why.split())).ratio()
    return grade_embedded(saved, sent, result, stage) + [
        ("the written answer that went out is the one the applicant approved", same >= 0.9, f"{same:.0%} the same; approved {len(longest)} characters, sent {len(why)}"),
    ]


def grade_hand_over(saved: dict, sent: list, result, stage: int, folder: Path | None = None) -> list[tuple[str, bool, str]]:
    kinds = [e.get("kind") for e in _journal(folder)]
    return [
        ("the agent gave the window to the applicant, and announced no press of its own", "handed" in kinds and "sending" not in kinds, f"handed {kinds.count('handed')}, announced {kinds.count('sending')}"),
        *grade_embedded(saved, sent, result, stage),      # what the applicant sent with their press is what the agent had filled in; the agent then found out that it went
    ]


GRADERS = {"profile_first": grade_profile_first, "embedded": grade_embedded, "account": grade_account, "widgets": grade_widgets, "returning": grade_returning, "closed": grade_closed,
           "approve": grade_approve, "hand_over": grade_hand_over}
STAGES = {"profile_first": "1,2", "embedded": "1", "account": "1", "widgets": "1", "returning": "1", "closed": "1", "approve": "1,2", "hand_over": "1"}
FORM_OF = {"approve": "embedded", "hand_over": "embedded"}      # the same form, worked under another setting
WANTS = {"account": ("folder",), "returning": ("folder", "site"), "closed": ("site",), "approve": ("folder",), "hand_over": ("folder",)}      # what a grader looks at besides the form's state


def through_the_queue(a, home: Path, posting, applicant, state) -> None:  # noqa: ANN001
    """The same form, worked the way the program works a posting: the application's task in the queue, the agent's
    record in the drafts table, the applicant's answer given in the record, and - the policy being "send when nothing is open" -
    the agent going on by itself."""
    from autoapply import db, drafts, handlers, knowledge, tasks  # noqa: F401
    from autoapply.agent import run, work
    from autoapply.models import Document, Job

    knowledge.write("profile", applicant.profile)
    db.set_setting("account.email", applicant.login)
    db.set_setting("submit.policy", "auto")
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
    tasks.enqueue("apply", ref=f"job:{job_id}", payload={"job_id": job_id})
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
    checks = GRADERS[a.form](*state(), result, stage, **({"folder": work.folder_of(1)} if a.form == "account" else {}))      # (through the queue: the forms that need nothing set up on the site first)
    with db.session() as s:
        app = s.get(Job, job_id).application
        checks.append(("the application is recorded as sent, with its evidence", app.status == "submitted" and bool((app.evidence or {}).get("text")), f"{app.status} / {json.dumps(app.evidence or {}, ensure_ascii=False)[:160]}"))
    ok = sum(1 for _, good, _ in checks if good)
    for what, good, saw in checks:
        print(f"  {'ok  ' if good else 'MISS'} {what}" + ("" if good else f"   [saw: {saw}]"))
    print(f"score: {ok} / {len(checks)}")


def read_the_portal(a, home: Path, site, base: str) -> None:  # noqa: ANN001
    """The agent reads the evaluation site's co-op portal: behind a sign-in, listed on two pages, each posting opened
    by a POST with a token - shaped like the portals the agent's notes are about, and not identical to them. Judged by
    what the portal saw (the sign-in, the search, which postings were opened) and by what reached the program."""
    from autoapply import auth, browser, secrets, sites
    from autoapply.agent import scan as agent_scan
    from autoapply.sources import pdportal
    from server import PORTAL_POSTINGS, PORTAL_USER

    url = f"{base}/portal/postings"
    key = sites.key_of(url)
    site.portal_password = secrets.generate_password(16)       # made up for this run, kept in the keyring like any stored login, never printed
    auth.upsert_account(key, host=key.split(":", 1)[1], email=PORTAL_USER, password=site.portal_password, status="ok", created_by="evaluation")
    known = {PORTAL_POSTINGS[0][0]}                             # one posting the program has already
    keep, listed, rows = pdportal.collector(known)
    began = time.time()
    with browser.open_page(key, headless=not a.headed, backend=a.backend) as page:
        page.goto(url, wait_until="domcontentloaded")
        out = agent_scan.read(page, site=key, name="Contoso University co-op portal", url=url, known=known, keep=keep, system="orbis")
    saw = site.portal
    by_id = {r[0]: r for r in PORTAL_POSTINGS}
    new = [i for i in by_id if i not in known]
    wrong = [i for i in new if i not in rows or rows[i].get("title") != by_id[i][1] or rows[i].get("company") != by_id[i][2]]
    late = [i for i in new if i in rows and rows[i].get("deadline") != time.strftime("%Y-%m-%d %H:%M", time.strptime(by_id[i][3], "%B %d, %Y %I:%M %p"))]
    how = [i for i in new if i in rows and ((rows[i].get("channel") == "PD Portal") != (by_id[i][4] == "Online via system") or (by_id[i][5] and rows[i].get("apply_url") != by_id[i][5]))]
    checks = [
        ("signed in with the stored login, and the portal never refused a password", saw["signed_in"] >= 1 and saw["refused"] == 0, f"signed in {saw['signed_in']}, refused {saw['refused']}"),
        ("everything was listed (the search was made with an empty keyword)", "" in saw["searches"], f"searches {saw['searches']}"),
        ("every posting on both pages reached the program as listed", sorted(listed) == sorted(by_id), f"{sorted(listed)}"),
        ("each new posting was stored with its title and employer", not wrong, f"wrong or missing: {wrong}"),
        ("deadlines as the portal gives them", not late, f"{[(i, rows[i].get('deadline')) for i in late]}"),
        ("how each is applied for: in the portal, or on the employer's site with its address", not how, f"{[(i, rows[i].get('channel'), rows[i].get('apply_url')) for i in how]}"),
        ("the text of each new posting was read", all(len(rows[i].get("jd_text") or "") > 80 for i in new if i in rows) and not wrong, "short or missing text"),
        # (opening it once to see what a posting's page is like is looking; reading it again with every scan is what the list of known ids is for)
        ("the posting the program already had was not read again with the others", saw["opened"].count(PORTAL_POSTINGS[0][0]) <= 1, f"opened {saw['opened']}"),
        ("the run said how it ended", bool(out.get("ok")), f"{out.get('why')}"),
        ("it left a note for the next scan", bool(sites.notes(key)), "no note"),
    ]
    ok = sum(1 for _, good, _ in checks if good)
    print(f"--- scan: {'done' if out.get('ok') else 'not done'} · {out.get('steps')} tool calls · {time.time() - began:.0f} s")
    for what, good, seen in checks:
        print(f"  {'ok  ' if good else 'MISS'} {what}" + ("" if good else f"   [saw: {seen}]"))
    if out.get("why"):
        print("  the agent's own word:", str(out["why"])[:500])
    print(f"score: {ok} / {len(checks)}")


def apply_in_the_portal(a, home: Path, site, base: str, applicant) -> None:  # noqa: ANN001
    """A posting of the co-op portal that is applied for in the portal itself, worked the way the program works it: a
    posting in its database (found by a scan), the task in the queue, the stored sign-in. The portal wants a cover
    letter and a résumé, uploaded under My Documents first and then put into a package. Judged by what the portal has
    afterwards."""
    import docx

    from autoapply import auth, db, handlers, knowledge, secrets, sites, tasks  # noqa: F401
    from autoapply.agent import run
    from autoapply.models import Document, Job
    from server import PORTAL_POSTINGS, PORTAL_USER

    pid, title, org, deadline, _how, _url, docs, term, length, place = PORTAL_POSTINGS[0]
    url = f"{base}/portal/postings#posting={pid}"      # (as the program names a portal posting: the list's address, which opens the list and nothing more)
    key = sites.key_of(url)
    site.portal_password = secrets.generate_password(16)
    auth.upsert_account(key, host=key.split(":", 1)[1], email=PORTAL_USER, password=site.portal_password, status="ok", created_by="evaluation")
    knowledge.write("profile", applicant.profile)
    db.set_setting("account.email", applicant.login)
    db.set_setting("submit.policy", "auto")
    db.set_setting("browser.default_headless", not a.headed)
    letter = home / f"{org}_{pid}_Cover_Letter.docx"      # the letter for this posting is written already (the program's letter writer needs the applicant's own template)
    d = docx.Document()
    for ln in ("Alex Chen", "", f"Re: {title}, Job ID {pid}", "", "Dear Hiring Team:", "", "At Contoso I built the export API of the billing service in Go on PostgreSQL and cut report generation "
               "from 40 s to 6 s. I would like to bring that to Northwind's routing team for the winter term.", "", "Sincerely,", "Alex Chen"):
        d.add_paragraph(ln)
    d.save(str(letter))
    with db.session() as s:
        for name, path in applicant.files.items():
            s.add(Document(kind="resume_docx", name=name, path=path))
        j = Job(source="pdportal", source_id=pid, company=org, title=title, apply_url=url, channel="PD Portal", ats="pdportal", docs_required=docs, term=term, months=length, location=place,
                deadline=time.strftime("%Y-%m-%d %H:%M", time.strptime(deadline, "%B %d, %Y %I:%M %p")), status="queued", online=1,
                jd_text=f"{org} is hiring a {title} for the winter term. You will work with a small team, ship to production in your first month and present your work at the end of the term. "
                        "Requirements: enrolled in a co-op programme in engineering or computer science; one earlier work term or substantial project work.")
        s.add(j)
        s.flush()
        job_id = j.id
        s.add(Document(kind="cover_letter", name=letter.name, path=str(letter), job_id=job_id, meta={"problems": []}))
    results: list = []
    real = run.apply

    def seen(*args, **kw):  # noqa: ANN002, ANN003, ANN202
        results.append(real(*args, **kw))
        return results[-1]

    run.apply = seen
    began = time.time()
    tasks.enqueue("apply", ref=f"job:{job_id}", payload={"job_id": job_id})
    n = tasks.drain()
    result = results[-1] if results else run.Result()
    saw = site.portal
    with db.session() as s:
        app = s.get(Job, job_id).application
        status, evidence = (app.status, app.evidence or {}) if app else ("-", {})
    mine = [x for x in saw["applications"] if x["id"] == pid]
    package = (mine[-1]["documents"] if mine else {})
    conf = (result.record or {}).get("confirmation") or {}
    checks = [
        ("signed in with the stored login, and the portal never refused a password", saw["signed_in"] >= 1 and saw["refused"] == 0, f"signed in {saw['signed_in']}, refused {saw['refused']}"),
        ("the posting was found in the list and opened (it has no address of its own)", pid in saw["opened"], f"opened {saw['opened']}"),
        ("the résumé was uploaded under My Documents, as a résumé", any(x["type"] == "Resumes" and x["file"] == "Alex_Chen_Resume.docx" for x in saw["documents"]), str([(x["type"], x["file"]) for x in saw["documents"]])),
        ("the cover letter for this posting was uploaded, as a cover letter", any(x["type"] == "Cover letters" and x["file"] == letter.name for x in saw["documents"]), str([(x["type"], x["file"]) for x in saw["documents"]])),
        ("nothing was uploaded twice", len(saw["documents"]) == len({(x["type"], x["file"]) for x in saw["documents"]}), f"{len(saw['documents'])} uploads"),
        ("one application, for this posting and no other", len(mine) == 1 and len(saw["applications"]) == 1, str([(x["id"], x["package"]) for x in saw["applications"]])),
        ("the package holds this posting's letter and the résumé", (package.get("Cover Letter") or {}).get("file") == letter.name and (package.get("Resume") or {}).get("file") == "Alex_Chen_Resume.docx",
         str({k: v.get("file") for k, v in package.items()})),
        ("reported as submitted; the confirmation names the posting's job ID", result.outcome == "submitted" and pid in json.dumps(conf), json.dumps(conf, ensure_ascii=False)[:220] or (result.outcome or result.stopped)),
        ("the application is recorded as sent, with its evidence", status == "submitted" and bool(evidence.get("text")), f"{status} / {json.dumps(evidence, ensure_ascii=False)[:160]}"),
    ]
    ok = sum(1 for _, good, _ in checks if good)
    print(f"--- an application in the portal: {n} task(s) · {result.outcome or 'no report'} · {result.steps} tool calls · {time.time() - began:.0f} s · the portal refused the package {saw['apply_refused']} time(s)")
    for what, good, seen_ in checks:
        print(f"  {'ok  ' if good else 'MISS'} {what}" + ("" if good else f"   [saw: {seen_}]"))
    if (result.record or {}).get("summary"):
        print("  the agent's own summary:", str(result.record["summary"])[:700].replace("\n", " "))
    print(f"score: {ok} / {len(checks)}")


def forget_logins() -> None:
    """The accounts a run made on the evaluation site have passwords in this computer's keyring (under a service name
    of their own): taken out again when the run is over."""
    try:
        from autoapply import auth, secrets

        for acct in auth.list_accounts():
            secrets.delete_password(acct["tenant_key"])
    except Exception as e:  # noqa: BLE001 - a run that made no account has nothing to take out
        print(f"(could not clear the evaluation's logins from the keyring: {type(e).__name__})")


def every_form(args: list[str]) -> None:
    """Each form in a process of its own, one after the other, and the scores together at the end."""
    import subprocess

    scores = {}
    for form in sorted(GRADERS):
        print(f"===== {form} =====", flush=True)
        got = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--form", form, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(got.stdout, end="", flush=True)
        if got.returncode:
            print(got.stderr[-2000:], flush=True)
        last = [ln for ln in got.stdout.splitlines() if ln.startswith("score: ")]
        scores[form] = last[-1][7:] if last else f"no score (exit {got.returncode})"
    for flag, what in (("--scan", "reading the co-op portal"), ("--portal-apply", "an application inside the co-op portal")):
        print(f"===== {what} =====", flush=True)
        got = subprocess.run([sys.executable, str(Path(__file__).resolve()), flag, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(got.stdout, end="", flush=True)
        if got.returncode:
            print(got.stderr[-2000:], flush=True)
        last = [ln for ln in got.stdout.splitlines() if ln.startswith("score: ")]
        scores[what] = last[-1][7:] if last else f"no score (exit {got.returncode})"
    print("===== all forms =====")
    for form, score in scores.items():
        print(f"  {form}: {score}")


def main() -> None:
    if "--all" in sys.argv[1:]:
        every_form([x for x in sys.argv[1:] if x != "--all"])
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="every form, one after the other (each in a process of its own)")
    ap.add_argument("--form", default="profile_first", choices=sorted(GRADERS))
    ap.add_argument("--model", default="")
    ap.add_argument("--effort", default="")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--backend", default="playwright", choices=["playwright", "nodriver"])
    ap.add_argument("--out", default="")
    ap.add_argument("--stages", default="")
    ap.add_argument("--site", default="", help="a site that is already running (python eval/server.py PORT): it outlives this run")
    ap.add_argument("--kill-after", type=int, default=0, help="end this process abruptly after that many tool calls - as a crash would")
    ap.add_argument("--scan", action="store_true", help="not a form: the agent reads the evaluation site's co-op portal (a sign-in, a list on two pages)")
    ap.add_argument("--portal-apply", action="store_true", help="not a form: an application inside the evaluation site's co-op portal, through the program's queue")
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

    form = FORM_OF.get(a.form, a.form)      # the form's own name on the site

    def state() -> tuple[dict, list]:
        if site is not None:
            return site.saved.get(form) or {}, site.sent.get(form) or []
        import urllib.request

        got = json.loads(urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f"{base}/__/state?form={form}", timeout=10).read())
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
    if a.scan or a.portal_apply:
        if site is None:
            raise SystemExit("the portal needs the site in this process (its password is made up here): do not pass --site")
        try:
            (read_the_portal(a, home, site, base) if a.scan else apply_in_the_portal(a, home, site, base, applicant))
        finally:
            forget_logins()
            site.close()
        return
    p = POSTINGS[form]
    posting = brief.Posting(company=p["company"], title=p["title"], url=f"{base}/jobs/{form}", text=p["text"])
    folder = home / "applications" / a.form
    if "site" in WANTS.get(a.form, ()) and site is None:
        raise SystemExit(f"{a.form} needs the site in this process: do not pass --site")
    if a.form == "returning":      # the applicant has been here: an account (its password made up now, kept like any stored login, never printed) and a draft from then
        from autoapply import auth, secrets, sites

        key = sites.key_of(posting.url)
        pw = secrets.generate_password(16)
        site.logins["returning"] = {"email": applicant.login, "password": pw, "signed_in": 0, "refused": 0}
        site.saved["returning"] = json.loads(json.dumps(OLD_DRAFT))
        auth.upsert_account(key, host=key.split(":", 1)[1], email=applicant.login, password=pw, status="ok", created_by="evaluation")
    if a.queue:
        try:
            through_the_queue(a, home, posting, applicant, state)
        finally:
            forget_logins()
            if site is not None:
                site.close()
        return
    print(f"form {a.form} at {posting.url}\nmodel {db.get_setting('llm.model')} ({db.get_setting('llm.effort')}), browser {a.backend}\neverything this leaves behind: {home}\n", flush=True)
    total = passed = 0
    extra = {k: v for k, v in (("folder", folder), ("site", site)) if k in WANTS.get(a.form, ())}
    for stage in [int(x) for x in (a.stages or STAGES[a.form]).split(",")]:
        answers = None
        if stage == 2 and a.form in ANSWERS:
            answers = {q["question"]: ANSWERS[a.form] for q in json.loads((folder / "questions.json").read_text(encoding="utf-8"))} if (folder / "questions.json").exists() else {"earliest start date": ANSWERS[a.form]}
        mode, record, on_hand = "auto", None, None
        if a.form == "approve":      # the applicant's setting is "I approve it first": a run that prepares, then - the record approved as it stands - a run that sends
            mode = "prepare" if stage == 1 else "send"
            if stage == 2:
                from autoapply.drafts import NOT_TO_ANSWER

                record = {**json.loads((folder / "record.json").read_text(encoding="utf-8")), "approved_by_the_applicant": True}
                # A record with a question open cannot be approved (drafts.approve). What the agent asked about a box the form
                # does not require, this applicant settles the short way: not to be answered - and then approves.
                answers = {q["question"]: NOT_TO_ANSWER for q in record.get("asked") or []} or None
                record["asked"] = []
                (folder / "approved.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        began = time.time()
        with browser.open_page(None, headless=not a.headed, backend=a.backend) as page:      # a new window every time: nothing of the last run is in it
            if a.form == "hand_over":      # the applicant's setting is "the last press is mine": they press it when the window is given to them
                mode = "hand_over"

                def on_hand(page=page) -> None:  # noqa: ANN001
                    for fr in page.frames:
                        if fr.locator("#go").count():
                            fr.locator("#go").first.click()
                            break
                    time.sleep(1)
                    page.evaluate("() => { window.__aaDone = true; }")      # (what the program's own window does when the applicant says they are done)

            result = run.apply(page, posting, applicant, folder, mode=mode, answers=answers, record=record, on_hand=on_hand)
        checks = GRADERS[a.form](*state(), result, stage, **extra)
        ok = sum(1 for _, good, _ in checks if good)
        total, passed = total + len(checks), passed + ok
        print(f"--- run {stage}: {result.outcome or 'no report'} · {result.steps} tool calls · {result.seconds:.0f} s (wall {time.time() - began:.0f} s) · stopped: {result.stopped}")
        for what, good, seen in checks:
            print(f"  {'ok  ' if good else 'MISS'} {what}" + ("" if good else f"   [saw: {seen}]"))
        if result.record.get("summary"):
            print("  the agent's own summary:", str(result.record["summary"])[:700].replace("\n", " "))
        print(f"  {ok} / {len(checks)}\n", flush=True)
    print(f"score: {passed} / {total}")
    forget_logins()
    if site is not None:
        site.close()


if __name__ == "__main__":
    main()
