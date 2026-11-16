"""Answer resolution: decide WHAT to put in each form field (plan section 7.4).

Order per question: file slots (deterministic) -> answer cache -> LLM over the
profile. The LLM sees the profile rules, the job, and the questions; drivers
never see the profile and the LLM never drives the browser here.
"""

from __future__ import annotations

from typing import Any

from . import db, knowledge, llm
from . import prompts
from .ats.base import FormSchema, Question, options_hash, sensitivity
from .models import AnswerCache, Document, Job

CONF = ("high", "medium", "low")

SYSTEM = """You fill in job application forms on behalf of one applicant.
You are given the applicant's profile (rules written by the applicant, some with dates; later dates win),
the job, and a list of form questions. For each question decide the value to enter.

Rules:
- Use only facts from the profile. Never invent facts, dates, numbers, or experience.
- For select/radio/multiselect questions the value MUST be copied exactly from the listed options.
- For checkbox questions answer true or false.
- Follow the profile's conditional rules exactly (for example the name rules that depend on
  whether the form has a preferred-name field: look at the whole question list before answering name fields).
- Consent / privacy / terms acknowledgements: agree, unless the profile says otherwise.
- If the profile does not determine the answer, set resolved=false and leave value empty. Do not guess.
  Optional questions with no basis in the profile should be resolved=true with an empty value and basis "optional, left blank".
- basis: a short pointer to the profile line or rule you used.
- confidence: high when a profile rule answers it directly; medium when you inferred it from several facts;
  low when it is a judgment call.
- Free-text answers (why this company, describe a project): write them from the profile and the job description,
  concisely, in the applicant's voice; mark confidence medium.
- Questions that ask for a personal experience ("tell us about a time ...", "describe a situation / challenge / conflict",
  "give an example of ...") are answered ONLY from a story in <stories>, or from an experience entry in the profile that
  clearly covers it: pick the best one, keep its facts, fit the length the form asks for; basis names the story.
  If nothing there covers the question, set resolved=false - never make up an experience.
- A rule you had to assume that is not in the profile goes in new_rule (one sentence) so the applicant can confirm it."""

ANSWER_SCHEMA = llm.obj(
    {
        "answers": {
            "type": "array",
            "items": llm.obj(
                {
                    "id": {"type": "string"},
                    "resolved": {"type": "boolean"},
                    "value": {"type": "string", "description": "text / exact option / 'true'|'false'; multiselect: options joined with ' || '"},
                    "basis": {"type": "string", "description": "why this answer, in one short sentence. Write this in Simplified Chinese (it is shown to the applicant); keep company names, product names and quoted form text in their original language."},
                    "confidence": {"type": "string", "enum": list(CONF)},
                    "new_rule": {"type": "string", "description": "a rule worth saving to the profile, or empty. Write this in Simplified Chinese (it is shown to the applicant); keep company names, product names and quoted form text in their original language."},
                }
            ),
        }
    }
)


def _active_doc(kind: str) -> dict[str, Any] | None:
    with db.session() as s:
        d = s.query(Document).filter_by(kind=kind, active=1).order_by(Document.id.desc()).first()
        return {"id": d.id, "name": d.name, "path": d.path, "kind": d.kind} if d else None


# file fields beyond résumé / cover letter / transcript: (words in the field's label) -> the kind of document that goes there
EXTRA_SLOTS = [
    (("research statement", "research plan", "research proposal", "statement of research"), "research_statement"),
    (("teaching statement", "teaching philosophy", "statement of teaching"), "teaching_statement"),
    (("diversity statement", "dei statement", "equity statement"), "diversity_statement"),
    (("publication", "list of papers", "bibliography"), "publications"),
    (("writing sample", "work sample", "sample of work", "code sample"), "writing_sample"),
    (("portfolio",), "portfolio"),
    (("reference letter", "letter of recommendation", "recommendation letter", "letters of reference"), "reference"),
    (("certificate", "certification", "licence", "license"), "certificate"),
]


def file_slots(schema: FormSchema, job: Job, cover_letter: dict[str, Any] | None, resume: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Map file questions to documents. Returns (answers, materials, notes)."""
    answers: dict[str, Any] = {}
    materials: list[dict[str, Any]] = []
    notes: list[str] = []
    resume = resume or _active_doc("resume_portal" if job.channel == "PD Portal" else "resume_site") or _active_doc("resume_site")
    transcript = _active_doc("transcript")
    file_qs = [q for q in schema.questions if q.type == "file"]
    has_transcript_slot = any("transcript" in q.label.lower() for q in schema.questions if q.type in ("file", "select"))
    needs_transcript = "transcript" in (job.docs_required or "").lower() or any(
        "transcript" in q.label.lower() for q in schema.questions
    )
    for q in file_qs:
        low = q.label.lower()
        doc = None
        if "resume" in low or "cv" in low.split() or "résumé" in low or low.startswith("cv"):
            doc = resume
        elif "transcript" in low:
            doc = transcript
        elif "summary sheet" in low or "summary_sheet" in low:
            doc = _active_doc("summary_sheet")
        elif (kind := next((k for words, k in EXTRA_SLOTS if any(w in low for w in words)), None)) is not None:
            doc = _active_doc(kind)  # research / teaching statements, publication list, writing sample, portfolio, references
        elif "cover" in low:
            if cover_letter:
                doc = cover_letter
            elif needs_transcript and not has_transcript_slot and transcript:
                doc = transcript
                notes.append("The form has no transcript field; the transcript goes in the Cover Letter slot.")
        if doc:
            answers[q.id] = doc["path"]
            materials.append({"slot": q.id, "slot_label": q.label, "document_id": doc["id"], "name": doc["name"], "kind": doc["kind"], "path": doc["path"]})
        elif q.required or (doc is None and resume is None and ("resume" in low or "cv" in low)):
            notes.append(f"{'Required file' if q.required else 'File'} '{q.label}' has no matching document." + (" No résumé has been uploaded yet (Profile → Documents)." if resume is None else ""))
    return answers, materials, notes


def _cache_get(ats: str, q: Question) -> AnswerCache | None:
    key, oh = q.key()
    with db.session() as s:
        return s.query(AnswerCache).filter_by(ats=ats, question_key=key, options_hash=oh).first()


def cache_put(ats: str, q: Question, value: Any, basis: str, *, confirmed: bool) -> None:
    key, oh = q.key()
    with db.session() as s:
        row = s.query(AnswerCache).filter_by(ats=ats, question_key=key, options_hash=oh).first()
        if row is None:
            row = AnswerCache(ats=ats, question_key=key, options_hash=oh, answer=value)
            s.add(row)
        row.answer, row.basis = value, basis
        row.sensitive = int(bool(sensitivity(q.label)))
        if confirmed:
            row.confirmed_by_user = 1


def _coerce(q: Question, raw: str) -> Any:
    if q.type == "checkbox":
        return raw.strip().lower() in ("true", "yes", "1", "checked")
    if q.type == "multiselect":
        return [v.strip() for v in raw.split("||") if v.strip()]
    return raw


def _valid(q: Question, value: Any) -> bool:
    if getattr(q, "searchable", False):      # the options are the list's first entries only: the applicant's own value is looked up when filling
        return value not in ("", None, [])
    if q.type in ("select", "radio") and q.options:
        return value in q.options
    if q.type == "multiselect" and q.options:
        return all(v in q.options for v in value)
    return True


def _pdportal_fixed(q: Question, job: Job) -> tuple[Any, str] | None:
    """PD Portal package form: document pickers and the package name need no model."""
    if q.id == "package":
        company = "".join(c if c.isalnum() else "_" for c in (job.company or "Application")).strip("_")[:40]
        return f"{company}_{job.source_id}", "naming rule <Company>_<JobID>"
    if q.type == "select":
        if not q.required:
            return "", "not required by this posting"
        if len(q.options) == 1:
            return q.options[0], "only document of this type in My Documents"
    return None


def resolve(schema: FormSchema, job: Job, *, cover_letter: dict[str, Any] | None = None, resume: dict[str, Any] | None = None,
            only: set[str] | None = None) -> dict[str, Any]:
    """Return {"answers": [...], "unresolved": [...], "materials": [...], "notes": [...], "new_rules": [...]}.
    ``only``: answer just these question ids (the whole form is still shown to the model as context)."""
    file_answers, materials, notes = file_slots(schema, job, cover_letter, resume)
    rows: list[dict[str, Any]] = []
    pending: list[Question] = []

    def row(q: Question, value: Any, basis: str, confidence: str, source: str, *, confirmed: bool = False) -> dict[str, Any]:
        tag = sensitivity(q.label)
        return {
            "id": q.id, "label": q.label, "type": q.type, "options": q.options, "required": q.required, "page": q.page, "searchable": bool(getattr(q, "searchable", False)),
            "value": value, "basis": basis, "confidence": confidence, "source": source,
            "sensitive": tag, "sensitive_confirmed": bool(tag) and confirmed,
        }

    for q in schema.questions:
        if only is not None and q.id not in only:
            continue
        if q.type == "file":
            if q.id in file_answers:
                rows.append(row(q, file_answers[q.id], "materials list", "high", "materials"))
            else:
                rows.append(row(q, "", "no document for this slot", "high", "materials"))
            continue
        if schema.ats == "pdportal":
            fixed = _pdportal_fixed(q, job)
            if fixed is not None:
                rows.append(row(q, fixed[0], fixed[1], "high", "profile"))
                continue
        hit = _cache_get(schema.ats, q)
        if hit is not None and _valid(q, hit.answer):
            rows.append(row(q, hit.answer, hit.basis or "answer cache", "high", "cache", confirmed=bool(hit.confirmed_by_user)))
        else:
            pending.append(q)

    new_rules: list[str] = []
    if pending:
        # The model gets a short key per question (k1, k2 ...), never the form's own identifiers: those are CSS selectors,
        # long, easy to mangle, and not the model's business. The answers are matched back by key.
        keys = {f"k{n}": q for n, q in enumerate(pending, 1)}
        listing = "\n".join(
            f"- id={k} | type={q.type} | required={q.required} | page={q.page + 1} | label={q.label!r}"
            + (f" | options={q.options}" if q.options else "")
            + (" | THIS LIST IS SEARCHED: the options shown are only its first entries. Answer with the applicant's own value as the profile states it "
               "(their city and country, their school); it is looked up in the list when the form is filled" if getattr(q, "searchable", False) else "")
            + (f" | at most {q.max_length} characters (the form refuses more)" if q.max_length else "")
            + (f" | help={q.help[:200]!r}" if q.help else "")
            for k, q in keys.items()
        )
        all_labels = "; ".join(q.label for q in schema.questions)
        prompt = (
            f"<profile>\n{knowledge.read('profile')}\n</profile>\n\n"
            + (f"<stories>\n{knowledge.stories()}\n</stories>\n\n" if knowledge.stories() else "")
            + f"<job>\nCompany: {job.company}\nTitle: {job.title}\nTerm: {job.term} {job.months}\nLocation: {job.location or job.work_type}\n"
            f"Salary posted: {job.salary}\n\n{job.jd_text or job.summary}\n</job>\n\n"
            f"<form ats=\"{schema.ats}\">\nAll field labels on this form: {all_labels}\n\nQuestions to answer:\n{listing}\n</form>"
        )
        docs = [f"{what}: {d['name']}" for kind, what in (("transcript", "transcript"), ("resume_site", "résumé")) if (d := _active_doc(kind))]
        if docs:
            prompt += ("\n\n<documents>\nOn file and attached where the form has a place for them: " + "; ".join(docs) + ". A question about a document "
                       "(\"Did you attach your transcript?\", \"Is your résumé up to date?\") is answered from this, not handed to the applicant.\n</documents>")
        from . import regions

        region = regions.for_location(job.location or "")
        if region:  # how forms in this country ask; it explains the questions, the answers still come from the profile only
            prompt += ("\n\n<region_notes>\nHow application forms in the country of this job usually ask. Use this to understand what a question means and "
                       "which format it wants. It is never a source of answers: those come from the profile.\n" + region + "\n</region_notes>")
        site = knowledge.playbook(f"site-{schema.tenant}") if schema.source == "agent" and schema.tenant else ""
        if site:  # what earlier applications on this site found out: limits the form enforces, how its lists are worded
            prompt += ("\n\n<site_notes>\nWhat earlier work on this employer's form found out. Use it for the shape of an answer: a length limit "
                       "the form enforces (keep the answer within it), a date format, the wording of a list's entries. It is never a source of "
                       "answers: those come from the profile.\n" + site[:4000] + "\n</site_notes>")
        out = llm.json(prompt, ANSWER_SCHEMA, system=prompts.get("answers"))
        by_key = {str(a["id"]).strip(): a for a in out["answers"]}
        missing = [k for k in keys if k not in by_key]
        if missing and len(missing) < len(keys):   # the model skipped some: ask once more for exactly those, instead of handing them to the applicant
            again = "\n".join(ln for ln in listing.splitlines() if ln.split(" | ")[0][5:] in missing)
            try:
                more = llm.json(prompt.replace(listing, again), ANSWER_SCHEMA, system=prompts.get("answers"))
                by_key.update({str(a["id"]).strip(): a for a in more["answers"] if str(a["id"]).strip() in missing})
            except llm.LLMError:
                pass
        # an answer over a limit the form is known to enforce: asked once more for exactly those, with the count
        long = [k for k, q in keys.items() if q.max_length and k in by_key and by_key[k].get("resolved") and isinstance(by_key[k].get("value"), str) and len(by_key[k]["value"]) > q.max_length]
        if long:
            again = "\n".join(ln + f" | YOUR ANSWER HAD {len(by_key[ln.split(' | ')[0][5:]]['value'])} CHARACTERS: REWRITE IT WITHIN THE LIMIT"
                              for ln in listing.splitlines() if ln.split(" | ")[0][5:] in long)
            try:
                more = llm.json(prompt.replace(listing, again), ANSWER_SCHEMA, system=prompts.get("answers"))
                by_key.update({str(a["id"]).strip(): a for a in more["answers"] if str(a["id"]).strip() in long})
            except llm.LLMError:
                pass
        by_id = {keys[k].id: a for k, a in by_key.items() if k in keys}
        for q in pending:
            a = by_id.get(q.id)
            if a is None or not a["resolved"]:
                rows.append(row(q, "", (a or {}).get("basis", "not answered"), "low", "unresolved"))
                continue
            value = _coerce(q, a["value"])
            if not _valid(q, value):
                rows.append(row(q, "", f"model proposed {a['value']!r}, which is not one of the options", "low", "unresolved"))
                continue
            rows.append(row(q, value, a["basis"], a["confidence"], "profile"))
            if a.get("new_rule"):
                new_rules.append(a["new_rule"])

    unresolved = [r for r in rows if r["source"] == "unresolved" and r["required"]]
    # optional + unresolved: leave blank, not blocking
    for r in rows:
        if r["source"] == "unresolved" and not r["required"]:
            r["source"], r["basis"], r["confidence"] = "profile", "optional, left blank", "high"
    return {"answers": rows, "unresolved": unresolved, "materials": materials, "notes": notes, "new_rules": new_rules}


def to_fill_map(answers: list[dict[str, Any]]) -> dict[str, Any]:
    return {a["id"]: a["value"] for a in answers if a["value"] not in ("", None, [])}


def remember(ats: str, answers: list[dict[str, Any]], *, confirmed: bool) -> None:
    """After a draft is approved, cache its non-file answers for the next form of this ATS."""
    for a in answers:
        if a["type"] == "file" or a["value"] in ("", None, []):
            continue
        if a["type"] in ("text", "textarea") and len(str(a["value"])) > 200:
            continue  # job-specific prose is not reusable
        q = Question(id=a["id"], label=a["label"], type=a["type"], options=a.get("options") or [])
        cache_put(ats, q, a["value"], a.get("basis", ""), confirmed=confirmed)


def correct(ats: str, answer: dict[str, Any]) -> None:
    """The applicant changed an answer after approving the draft. The approval had put the old value into the cache as
    theirs; the cache now holds the new one - or nothing, when the answer was cleared or is no longer reusable - so
    that the next form of this ATS is not answered with what they have just corrected."""
    q = Question(id=answer["id"], label=answer["label"], type=answer["type"], options=answer.get("options") or [])
    key, oh = q.key()
    with db.session() as s:
        s.query(AnswerCache).filter_by(ats=ats, question_key=key, options_hash=oh).delete()
    remember(ats, [answer], confirmed=True)


# --- auto-approve (plan section 6.6) -------------------------------------------------


def auto_approve_check(draft: dict[str, Any], job: Job, ats: str, tenant_key: str, *, new_cover_letter: bool, new_resume: bool = False) -> dict[str, Any]:
    """Evaluate the seven conditions. Returns {"eligible": bool, "failed": [reasons], "checks": {...}}."""
    from .models import Account, DriverStat

    st = db.all_settings()
    checks: dict[str, bool] = {}
    checks["enabled"] = bool(st["auto_approve.enabled"]) and bool((st["auto_approve.per_ats"] or {}).get(ats))
    checks["no_unresolved"] = not draft.get("unresolved")
    checks["all_high_from_rules"] = all(
        a["confidence"] == "high" and a["source"] in ("cache", "profile", "materials") for a in draft["answers"] if a["value"] not in ("", None, [])
    )
    checks["no_new_sensitive"] = all(not a["sensitive"] or a["sensitive_confirmed"] for a in draft["answers"] if a["value"] not in ("", None, []))
    checks["cover_letter_ok"] = (not new_cover_letter) or bool(st["auto_approve.allow_new_cover_letter"])
    checks["tailored_resume_ok"] = (not new_resume) or not bool(st["tailor.review"])
    checks["score_ok"] = job.score is not None and job.score >= float(st["auto_approve.min_score"])
    with db.session() as s:
        ds = s.get(DriverStat, ats)
        acct = s.get(Account, tenant_key)
        streak = ds.consecutive_submits if ds else 0
        acct_ok = acct is not None and acct.status == "ok"
    from .ats import registry

    drv = registry.get(ats)
    checks["driver_proven"] = streak >= int(st["auto_approve.min_driver_successes"])
    checks["session_ready"] = (drv is not None and not drv.requires_login) or acct_ok
    checks["no_unusual_notes"] = not draft.get("notes")
    failed = [k for k, v in checks.items() if not v]
    return {"eligible": not failed, "failed": failed, "checks": checks}
