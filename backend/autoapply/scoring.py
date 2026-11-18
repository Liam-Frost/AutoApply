"""Scoring: natural-language rules (knowledge/scoring.md) applied by the model
to the FULL job description. A job without a description stays unscored.

A posting whose source gave only a summary has its own page read first (fulltext.py); one whose page cannot be read is
scored on the summary, told that it is one, and its reason says so."""

from __future__ import annotations

import logging
from typing import Any

from . import db, knowledge, llm, messages, notify
from . import prompts
from .models import Job

log = logging.getLogger("autoapply.scoring")

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
    }
)
BRIEF = (
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
)
# The long overview is most of what the model writes for a posting (some 1,500 of 1,700 tokens) - and is read only for
# postings worth a look. It is written from scoring.brief_min_score up; for the rest on request (brief_job).
BRIEF_SCHEMA = llm.obj({"brief": {"type": "string", "description": BRIEF}})


def _schema(min_score: float) -> dict[str, Any]:
    props = dict(SCHEMA["properties"])
    props["brief"] = {"type": "string", "description": BRIEF + f" Write it ONLY when the posting is not excluded and its score is {min_score:g} or more; "
                                                               "otherwise give an empty string - nothing is lost, it is written later if the applicant asks."}
    return llm.obj(props)

SYSTEM = """You screen job postings for one applicant using the applicant's own rules.
Read the whole description. Apply hard exclusions first: if one applies, set excluded=true, name the rule, score 0.
Otherwise score fit 0-10 following the rubric. Base every statement on the description; do not guess from the title."""


PARTIAL = {"summary": "只有摘要：这个岗位的来源只给了摘要，岗位页面的全文没能读到；摘要里没提到的要求不等于没有。",
           "cut": "岗位说明很长，只读了前面一部分；后面写的内容不在评分里。"}


def _whole_text(job_id: int) -> None:
    """Before a posting is read for a score or an overview: when what is stored is only a summary, its own page is
    read for the whole text (fulltext.complete). What cannot be read stays a summary, and is scored as one."""
    from . import fulltext

    try:
        fulltext.complete(job_id)
    except Exception:  # noqa: BLE001 - a page that cannot be read does not stop the scoring
        log.exception("could not read the posting's page for its full text")


_SAYS_SO = {"summary": ("只有摘要", "only a summary", "summary only"), "cut": ("只读了前面", "beginning only", "only the beginning")}


def _said_partial(reason: str, partial: str) -> str:
    """The reason of a score that was given on a partial text says so, whatever the model wrote (in the language the
    reasons are written in: the interface's)."""
    from . import i18n

    note = PARTIAL.get(partial, "")
    if not note or any(m in (reason or "").lower() for m in _SAYS_SO[partial]):
        return reason
    return f"{i18n.tr(note)} {reason or ''}".strip()


def score_job(job_id: int) -> dict[str, Any] | None:
    from . import fulltext

    _whole_text(job_id)
    with db.session() as s:
        j = s.get(Job, job_id)
        if j is None or len((j.jd_text or "").strip()) < 200:
            return None  # no description: stay unscored rather than score from the title
        partial = j.jd_partial or ""
        note = fulltext.partial_note(partial)
        prompt = (
            f"<rules>\n{knowledge.read('scoring')}\n</rules>\n\n<applicant>\n{knowledge.read('profile')}\n</applicant>\n\n"
            f"<posting>\nCompany: {j.company}\nTitle: {j.title}\nLocation: {j.location} {j.work_type}\nTerm: {j.term} {j.months}\n"
            f"Salary: {j.salary}\nDeadline: {j.deadline}\nDocuments required: {j.docs_required}\n\n{note + chr(10) + chr(10) if note else ''}{j.jd_text}\n</posting>"
        )
    out = llm.json(prompt, _schema(float(db.get_setting("scoring.brief_min_score") or 0)), system=prompts.get("scoring"))
    out["reason"] = _said_partial(out["reason"], partial)
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


def brief_job(job_id: int) -> str:
    """Write the long overview of one posting, for the applicant who opens a posting that has none."""
    from . import fulltext

    _whole_text(job_id)
    with db.session() as s:
        j = s.get(Job, job_id)
        if j is None or len((j.jd_text or "").strip()) < 200:
            return ""
        note = fulltext.partial_note(j.jd_partial or "")
        prompt = (f"<applicant>\n{knowledge.read('profile')}\n</applicant>\n\n<posting>\nCompany: {j.company}\nTitle: {j.title}\nLocation: {j.location} {j.work_type}\n"
                  f"Term: {j.term} {j.months}\nDeadline: {j.deadline}\nDocuments required: {j.docs_required}\n\n{note + chr(10) + chr(10) if note else ''}{j.jd_text}\n</posting>")
    out = llm.json(prompt, BRIEF_SCHEMA, system="You write an overview of one job posting for one applicant. Base every statement on the posting and the applicant's profile.")
    brief = str(out.get("brief") or "")
    if brief:
        with db.session() as s:
            s.get(Job, job_id).brief = brief
    return brief


def set_aside_by_rule(ids: list[int]) -> list[int]:
    """Postings a plain rule decides - they say themselves that they are for other programmes of study (intake.not_for_me)
    - are set aside here, before the model reads anything. Returns the postings that are left to score."""
    from . import intake

    mine = intake.my_fields()
    if not mine:
        return ids
    left = []
    with db.session() as s:
        for jid in ids:
            j = s.get(Job, jid)
            why = intake.not_for_me(j.jd_text or "", mine) if j is not None else ""
            if why and j.application is None:
                j.status, j.score, j.exclusion, j.score_reason = "skipped", 0.0, why, "岗位自己写明了面向的专业，你的专业不在其中；没有交给 AI 评分。"
            else:
                left.append(jid)
    return left


def draft_line():  # noqa: ANN201
    """The score at which a posting gets a draft, as a function of the posting: ``line(company, source)``.

    The general line - or, for a posting of an employer the applicant marked as priority, the lower of that and the
    priority line. It is the posting's employer that counts, not the list it came in on: a job board marked as
    priority does not make every employer on it one. Asked here by everything that needs it - the queue when it
    starts drafts, and the page that explains how many postings of a source are above the line - so that the
    explanation is of what the queue does."""
    from . import employers

    general = float(db.get_setting("queue.min_score_for_draft"))
    names, priority = employers.priority_names(), float(db.get_setting("employers.priority_min_score") or 7.0)
    return lambda company, source="": min(general, priority) if employers.is_priority(company, source, names) else general


def score_pending(limit: int | None = None) -> dict[str, int]:
    from concurrent.futures import ThreadPoolExecutor

    from . import context

    limit = limit or int(db.get_setting("scoring.max_per_run") or 60)
    with db.session() as s:
        # only postings that can be scored (a description to read) and are not another listing of the same job
        rows = s.query(Job).filter(Job.status == "new", Job.online == 1, Job.duplicate_of.is_(None)).order_by(Job.id.desc()).all()
        # (a posting whose source gave only a summary may be too short to score as it stands: its page is read first)
        able = [j.id for j in rows if len((j.jd_text or "").strip()) >= 200 or j.jd_partial == "summary"]
    left = set_aside_by_rule(able)
    by_rule = len(able) - len(left)
    ids, remaining = left[:limit], max(0, len(left) - limit)
    for jid in ids:      # the pages of the postings that came as summaries, one after the other: not several browsers at once
        _whole_text(jid)
    scored = skipped = queued = 0
    # Reading a posting is waiting for the model: several are read at once (scoring.parallel). What is done with each
    # result - the status, queueing a draft - happens here, one after the other. A model that is out of quota ends the
    # run: what was read is kept, the rest stays unscored and the task says why.
    stopped: list[BaseException] = []

    def read(jid: int) -> dict[str, Any] | None:
        if stopped:
            return None
        try:
            return score_job(jid)
        except llm.LLMUnavailable as e:
            stopped.append(e)
            return None

    workers = max(1, min(8, int(db.get_setting("scoring.parallel") or 1)))
    if workers > 1 and len(ids) > 1:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="score") as pool:
            outs = list(pool.map(context.carried(read), ids))
    else:
        outs = [read(jid) for jid in ids]
    line = draft_line()
    high: list[str] = []
    from . import tasks

    fresh: set[int] = set()         # scored just now and at their threshold: they are among those the room is given to
    for jid, out in zip(ids, outs):
        if out is None:
            skipped += 1
            continue
        scored += 1
        with db.session() as s:
            j = s.get(Job, jid)
            if not out["excluded"] and j.score is not None and j.score >= line(j.company, j.source) and j.apply_url:
                high.append({"score": j.score, "company": j.company, "title": j.title, "deadline": j.deadline or ""})
                fresh.add(jid)
    # The room there is for drafts (drafts.max_pending) goes to the best of what qualifies - the postings scored just
    # now together with those that were scored before and still wait. It used to go to the batch in the order it was
    # read, newest first: with one place left, a posting scored 8 took it and one scored 10 in the same batch waited.
    # (as many as were found just now, at most: the rest of the backlog is started a few at a time - queue_qualifying)
    queued = _start_best(min(draft_room()["room"], len(fresh)), fresh)
    if high:
        notify.send("status_update", messages.high_scores(sorted(high, key=lambda r: -r["score"])), ref="score")
    if stopped:
        if not scored:
            raise stopped[0]
        return {"scored": scored, "set_aside_by_rule": by_rule, "queued_for_draft": queued, "remaining": remaining + skipped, "stopped": str(stopped[0])[:200]}
    return {"scored": scored, "set_aside_by_rule": by_rule, "no_description": skipped, "queued_for_draft": queued, "remaining": remaining}


def draft_room() -> dict[str, int]:
    """How many applications wait for the applicant (being drafted, or drafted and not approved), the most the program
    lets wait before it stops starting drafts by itself, and how many more it may start. A scan can bring thousands of
    postings; without a limit the best hundred of them would each get a draft nobody has the time to read."""
    from .models import Application, Task

    cap = int(db.get_setting("drafts.max_pending") or 0)
    with db.session() as s:
        waiting = s.query(Application).filter(Application.status.in_(("recon", "revising", "needs_input", "draft_ready"))).count()
        # drafts that are about to be started and have no application yet
        for t in s.query(Task).filter(Task.kind == "recon", Task.status == "queued"):
            num = t.ref.partition(":")[2]
            if t.ref.startswith("job:") and num.isdigit():
                j = s.get(Job, int(num))
                if j is not None and j.application is None:
                    waiting += 1
    return {"waiting": waiting, "cap": cap, "room": max(0, cap - waiting) if cap else 10 ** 6}


def queue_qualifying(limit: int = 6) -> int:
    """Postings that are scored, still open, have no application and reach the score at which a draft is prepared: start
    their drafts. Scoring does this for a posting at the moment it is scored; this is for everything that came to qualify
    afterwards - the threshold was lowered, an employer became a priority one, the program was closed in between.
    A few at a time, best first, so that one change of a setting does not start dozens of forms at once."""
    if db.get_setting("schedule.paused") or db.get_setting("schedule.draining"):
        return 0
    return _start_best(min(limit, draft_room()["room"]))       # no more than the applicant has said they want waiting for them


def _start_best(limit: int, fresh: set[int] | frozenset[int] = frozenset()) -> int:
    """Start drafts for the best postings that qualify, at most ``limit`` of them: scored, open, with no application, at
    the score at which a draft is prepared - highest score first. ``fresh``: postings scored just now; they qualify
    whatever their source (a posting of the school portal gets its draft when it is scored, not later by the clock)."""
    from . import tasks
    from .models import Task

    if limit <= 0:
        return 0
    line = draft_line()
    todo: list[tuple[int, str]] = []
    with db.session() as s:
        busy = {t.ref for t in s.query(Task).filter(Task.kind == "recon", Task.status.in_(("queued", "running", "waiting_human", "held")))}
        rows = (s.query(Job).filter(Job.status == "scored", Job.online == 1, Job.duplicate_of.is_(None), Job.archived_at.is_(None), Job.score.isnot(None))
                .order_by(Job.score.desc(), Job.id.desc()).all())
        for j in rows:
            if j.application is not None or j.exclusion or not j.apply_url or (j.source == "pdportal" and j.id not in fresh) or f"job:{j.id}" in busy:
                continue
            if j.score >= line(j.company, j.source):
                j.status = "queued"
                todo.append((j.id, j.deadline or ""))
                if len(todo) >= limit:
                    break
    for jid, deadline in todo:
        tasks.enqueue("recon", ref=f"job:{jid}", payload={"job_id": jid}, priority=tasks.deadline_priority(deadline))
    return len(todo)


def unscored_count() -> int:
    """Postings that could be scored and have not been."""
    with db.session() as s:
        return sum(1 for j in s.query(Job).filter(Job.status == "new", Job.online == 1, Job.duplicate_of.is_(None), Job.archived_at.is_(None))
                   if len((j.jd_text or "").strip()) >= 200)
