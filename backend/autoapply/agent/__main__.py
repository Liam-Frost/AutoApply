"""Run the application agent on one posting of this program's own data, from the command line (phase 0).

    python -m autoapply.agent --job 789 [--mode prepare|auto|send|hand_over] [--hidden] [--answer "question=answer" ...]

It works in a window the applicant can watch, on the site's own saved session, with the applicant's profile and
files. What it leaves in the program's data: a folder for the application (data/agent/job_<id>/: its brief, journal,
record, questions, pictures), notes about the site, and - if it registered one - the account. It does not touch the
posting's or the application's status: phase 0 runs beside the program, not in it.
"""
from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m autoapply.agent")
    ap.add_argument("--job", type=int, required=True)
    ap.add_argument("--mode", default="prepare", choices=["prepare", "auto", "send", "hand_over"])
    ap.add_argument("--hidden", action="store_true", help="no window (default: a window the applicant can watch)")
    ap.add_argument("--answer", action="append", default=[], help='what the applicant answered: "question=answer" (repeatable)')
    ap.add_argument("--model", default="", help="the model for this run only (the program's setting is not changed)")
    ap.add_argument("--effort", default="", help="the effort for this run only")
    a = ap.parse_args()

    from .. import browser, config, db
    from ..models import Job
    from . import brief, run

    if not config.DB_PATH.exists():
        db.init_db()
    if a.model or a.effort:      # for this run only: nothing is written to the settings
        own, real = {k: v for k, v in (("llm.model", a.model), ("llm.effort", a.effort)) if v}, db.get_setting
        db.get_setting = lambda key, *rest, **kw: own[key] if key in own else real(key, *rest, **kw)
    with db.session() as s:
        j = s.get(Job, a.job)
        if j is None or not j.apply_url:
            sys.exit(f"posting {a.job} is not on record, or has no address to apply at")
        posting = brief.Posting(company=j.company, title=j.title, url=j.apply_url, text=j.jd_text or j.summary or "", deadline=j.deadline or "",
                                extra=" · ".join(x for x in (f"Term: {j.term} {j.months}".strip() if (j.term or j.months) else "", f"Place: {j.location or j.work_type}" if (j.location or j.work_type) else "",
                                                             f"Documents asked for: {j.docs_required}" if j.docs_required else "") if x))
        channel = j.channel or ""
    applicant = brief.applicant_on_file(channel)
    folder = config.DATA / "agent" / f"job_{a.job}"
    answers = dict(x.split("=", 1) for x in a.answer if "=" in x)
    asked = folder / "answers.json"
    if asked.exists():
        answers = {**json.loads(asked.read_text(encoding="utf-8")), **answers}
    site = brief.site_key(posting.url)
    print(f"{posting.company} · {posting.title}\n{posting.url}\nsite {site} · mode {a.mode} · folder {folder}\n", flush=True)
    with browser.open_page(site, headless=a.hidden, url=posting.url) as page:
        result = run.apply(page, posting, applicant, folder, mode=a.mode, answers=answers or None)
    print(f"ended: {result.outcome or 'no report'} · {result.steps} tool calls · {result.seconds:.0f} s · {result.stopped}")
    rec = result.record or {}
    if rec.get("summary"):
        print("\n" + str(rec["summary"]))
    for q in rec.get("asked") or []:
        print(f"\nasks ({q.get('about')}): {q.get('question')}" + (f"\n  options: {q['options']}" if q.get("options") else ""))
    if rec.get("open"):
        print("\nopen:\n" + "\n".join(f"- {x}" for x in rec["open"]))


if __name__ == "__main__":
    main()
