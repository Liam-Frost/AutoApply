"""Scoring: natural-language rules (knowledge/scoring.md) applied by the model
to the FULL job description. A job without a description stays unscored."""

from __future__ import annotations

from typing import Any

from . import db, knowledge, llm, messages, notify
from . import prompts
from .models import Job

SCHEMA = llm.obj(
    {
        "excluded": {"type": "boolean"},
        "exclusion_rule": {"type": "string", "description": "the hard-exclusion rule that applies, or empty"},
        "score": {"type": "number", "description": "0-10 in steps of 0.5; 0 when excluded"},
        "direction": {"type": "string", "description": "short label, e.g. backend, full-stack, ML/AI, embedded, QA, other"},
        "reason": {"type": "string", "description": "two or three sentences citing what in the description drove the score. Write this in Simplified Chinese (it is shown to the applicant); keep company names, product names and quoted form text in their original language."},
        "term": {"type": "string", "description": "work term if stated, e.g. 'Winter 2027'; else empty"},
        "months": {"type": "string", "description": "term length(s) in months if stated, e.g. '4 or 8'; else empty"},
        "summary": {"type": "string", "description": "one-line summary of the role. Write this in Simplified Chinese (it is shown to the applicant); keep company names, product names and quoted form text in their original language."},
        "brief": {"type": "string", "description": (
            "A thorough overview of the posting for the applicant to read instead of the raw description, in Markdown, in Simplified Chinese "
            "(keep company, product, technology names and job titles in their original language). Use these level-4 headings, in order, "
            "skipping one only when the posting says nothing about it: "
            "'#### 这个岗位做什么' (the team, the product, day-to-day work; 3-6 bullets), "
            "'#### 要求' (must-haves, then nice-to-haves, as bullets; quote specific technologies and years), "
            "'#### 和你的匹配' (which of the applicant's experience fits which requirement, and where the gaps are; be specific and honest), "
            "'#### 需要注意' (work authorization / citizenship, location and on-site rules, term and dates, pay, application instructions such as "
            "required documents or essay prompts, deadlines), "
            "'#### 关于公司' (one or two sentences, only from the posting). "
            "Only state what the posting or the applicant profile says; do not add outside knowledge."
        )},
    }
)

SYSTEM = """You screen job postings for one applicant using the applicant's own rules.
Read the whole description. Apply hard exclusions first: if one applies, set excluded=true, name the rule, score 0.
Otherwise score fit 0-10 following the rubric. Base every statement on the description; do not guess from the title."""


def score_job(job_id: int) -> dict[str, Any] | None:
    with db.session() as s:
        j = s.get(Job, job_id)
        if j is None or len((j.jd_text or "").strip()) < 200:
            return None  # no description: stay unscored rather than score from the title
        prompt = (
            f"<rules>\n{knowledge.read('scoring')}\n</rules>\n\n<applicant>\n{knowledge.read('profile')}\n</applicant>\n\n"
            f"<posting>\nCompany: {j.company}\nTitle: {j.title}\nLocation: {j.location} {j.work_type}\nTerm: {j.term} {j.months}\n"
            f"Salary: {j.salary}\nDeadline: {j.deadline}\nDocuments required: {j.docs_required}\n\n{j.jd_text}\n</posting>"
        )
    out = llm.json(prompt, SCHEMA, system=prompts.get("scoring"))
    with db.session() as s:
        j = s.get(Job, job_id)
        j.score = 0.0 if out["excluded"] else float(out["score"])
        j.score_reason = out["reason"]
        j.exclusion = out["exclusion_rule"] if out["excluded"] else ""
        j.direction = out["direction"] or j.direction
        j.summary = out["summary"] or j.summary
        j.brief = out.get("brief") or j.brief
        j.term = j.term or out["term"]
        j.months = j.months or out["months"]
        if j.application is None:
            j.status = "skipped" if out["excluded"] else "scored"
    return out


def score_pending(limit: int | None = None) -> dict[str, int]:
    limit = limit or int(db.get_setting("scoring.max_per_run") or 60)
    with db.session() as s:
        # only postings that can be scored (a description to read) and are not another listing of the same job
        rows = s.query(Job).filter(Job.status == "new", Job.online == 1, Job.duplicate_of.is_(None)).order_by(Job.id.desc()).all()
        able = [j.id for j in rows if len((j.jd_text or "").strip()) >= 200]
        ids, remaining = able[:limit], max(0, len(able) - limit)
    scored = skipped = queued = 0
    min_score = float(db.get_setting("queue.min_score_for_draft"))
    from . import employers

    prio, prio_score = employers.priority_names(), float(db.get_setting("employers.priority_min_score") or 7.0)
    high: list[str] = []
    from . import tasks

    for jid in ids:
        out = score_job(jid)
        if out is None:
            skipped += 1
            continue
        scored += 1
        enqueue_deadline = None
        with db.session() as s:
            j = s.get(Job, jid)
            floor = min(min_score, prio_score) if employers.is_priority(j.company, j.source, prio) else min_score
            if not out["excluded"] and j.score is not None and j.score >= floor and j.apply_url:
                j.status = "queued"
                high.append({"score": j.score, "company": j.company, "title": j.title, "deadline": j.deadline or ""})
                enqueue_deadline = j.deadline or ""
        if enqueue_deadline is not None:  # enqueue after the session closes (single SQLite writer)
            tasks.enqueue("recon", ref=f"job:{jid}", payload={"job_id": jid}, priority=tasks.deadline_priority(enqueue_deadline))
            queued += 1
    if high:
        notify.send("status_update", messages.high_scores(sorted(high, key=lambda r: -r["score"])), ref="score")
    return {"scored": scored, "no_description": skipped, "queued_for_draft": queued, "remaining": remaining}


def unscored_count() -> int:
    """Postings that could be scored and have not been."""
    with db.session() as s:
        return sum(1 for j in s.query(Job).filter(Job.status == "new", Job.online == 1, Job.duplicate_of.is_(None), Job.archived_at.is_(None))
                   if len((j.jd_text or "").strip()) >= 200)
