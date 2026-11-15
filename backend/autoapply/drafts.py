"""Reconnaissance -> draft -> review -> approval (plan section 6).

A draft is everything a reviewer needs without seeing the live form: the
proposed answer for every question with its basis, the questions the agent
could not answer, the files and where they go, and the execution plan.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from . import answers as ans, messages
from . import prompts
from . import auth, browser, config, db, knowledge, llm, materials, metering, notify
from .ats import registry
from .ats.base import DriverError, FormSchema, JobRef, NeedsHuman, SiteDown
from .models import Application, Draft, DraftComment, DriverStat, Job, now

log = logging.getLogger("autoapply.drafts")


def _stat(ats: str, field: str, *, reset_streak: bool = False, streak: bool = False) -> None:
    with db.session() as s:
        d = s.get(DriverStat, ats)
        if d is None:
            d = DriverStat(ats=ats, recon_ok=0, recon_fail=0, exec_ok=0, exec_fail=0, consecutive_submits=0)
            s.add(d)
        setattr(d, field, (getattr(d, field) or 0) + 1)
        if streak:
            d.consecutive_submits = (d.consecutive_submits or 0) + 1
        if reset_streak:
            d.consecutive_submits = 0


def job_ref(job: Job) -> JobRef:
    ref = registry.detect(job.apply_url) if job.apply_url else None
    if ref is None:
        raise DriverError("job has no application URL", seen=job.apply_url or "")
    return ref


def recon(job: Job, run_dir) -> tuple[JobRef, FormSchema]:  # noqa: ANN001
    """Get the form schema. Opens a browser only when the driver needs one."""
    ref = job_ref(job)
    driver = registry.get(ref.ats)
    if driver is None:
        from . import generic

        return generic.recon(job, ref, run_dir)
    if not driver.requires_login and ref.tenant:
        if getattr(driver, "page_extras", False):  # the API misses blocks that only the page shows
            with browser.open_page() as page:
                return ref, driver.get_schema(ref, page)
        return ref, driver.get_schema(ref, None)
    with browser.open_page(ref.tenant_key if driver.requires_login else None) as page:
        if not ref.tenant and hasattr(driver, "resolve_board"):
            ref = driver.resolve_board(page, ref)  # type: ignore[attr-defined]
            return ref, driver.get_schema(ref, None)
        auth.ensure_session(page, driver, ref)
        # Walk with profile-derived answers so conditional questions appear.
        schema = driver.get_schema(ref, page, answers=_walk_answerer(job))
        browser.snapshot(page, run_dir, "recon_last_page")
        return ref, schema


def _walk_answerer(job: Job):
    """Callback a multi-page driver uses during the walk: questions -> fill map."""

    def answer(partial: FormSchema) -> dict[str, Any]:
        res = ans.resolve(partial, job)
        return ans.to_fill_map(res["answers"])

    return answer


def plan_steps(ref: JobRef, schema: FormSchema, fill: dict[str, Any], mats: list[dict[str, Any]], requires_login: bool) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    if requires_login:
        steps.append({"op": "ensure_session", "text": f"登录 {ref.tenant_key}（依次尝试：保存的登录态、保存的密码、注册；都不行时请你登录）"})
        steps.append({"op": "already_applied", "text": "检查这个岗位是否已经申请过，避免重复提交"})
    steps.append({"op": "open", "text": f"打开申请表（{schema.url or ref.url}）"})
    pages = schema.pages or ["Application"]
    for i, title in enumerate(pages):
        qs = [q for q in schema.questions if q.page == i]
        n_fill = sum(1 for q in qs if q.id in fill and q.type != "file")
        files = [m["name"] for m in mats if any(q.id == m["slot"] for q in qs)]
        txt = f"第 {i + 1} 页「{title}」：核对表单结构，填写 {n_fill} 项"
        if files:
            txt += f"，上传 {'、'.join(files)}"
        steps.append({"op": "fill_page", "page": i, "text": txt})
        if i < len(pages) - 1:
            steps.append({"op": "next", "page": i, "text": "保存并进入下一页"})
    steps.append({"op": "read_back", "text": "把每个值从页面读回来，和这份草案逐项比对；有任何不一致就停下，不提交"})
    if schema.source == "agent":
        steps.append({"op": "submit", "text": "这个 ATS 还没有驱动：填好后打开窗口，由你检查并点击提交；提交后保存确认页作为证据"})
    else:
        steps.append({"op": "submit", "text": "提交（策略为“人工提交”时由你在窗口里点击），然后保存确认页作为证据"})
    return steps


def build(job_id: int, *, run_dir=None, instructions: str = "") -> int:  # noqa: ANN001
    """Create (or refresh) the draft for a job. Returns the draft id."""
    with db.session() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise KeyError(job_id)
        app = job.application
        if app is None:
            app = Application(job_id=job.id, status="recon", channel=job.channel)
            s.add(app)
        elif app.status in ("submitted", "confirmed", "interview", "assessment", "offer", "rejected"):
            raise ValueError(f"job {job_id} already has an application in status {app.status}")
        else:
            app.status = "recon"
        s.flush()
        app_id = app.id
    run_dir = run_dir or (config.RUNS / f"recon_job_{job_id}")
    metering.stage("read_form")
    try:
        ref, schema = recon(job, run_dir)
    except NeedsHuman as e:
        _set_app(app_id, "needs_human", f"recon blocked: {e.reason}")
        raise
    except Exception as e:
        closed = isinstance(e, DriverError) and re.search(r"not found|closed|no longer", str(e), re.I)
        if closed:
            with db.session() as s:
                a = s.get(Application, app_id)
                if a is not None and not a.drafts:
                    s.delete(a)  # nothing was drafted: the job goes back to "not applied", with the reason on it
                j = s.get(Job, job_id)
                j.note = f"雇主官网上已找不到这个岗位，可能已关闭（{now().date().isoformat()} 核对）"
            raise DriverError("岗位在雇主官网上已关闭或链接失效，没有生成草案") from e
        if isinstance(e, SiteDown):  # the site is unreachable right now: leave the job as it was
            with db.session() as s2:
                a2 = s2.get(Application, app_id)
                if a2 is not None and not a2.drafts:
                    s2.delete(a2)
            raise
        _set_app(app_id, "failed", "recon failed")
        if (r := registry.detect(job.apply_url or "")) is not None:
            _stat(r.ats, "recon_fail")
        raise
    _stat(ref.ats, "recon_ok")
    with db.session() as s:
        j = s.get(Job, job_id)
        j.ats, j.tenant = ref.ats, ref.tenant
        if not j.jd_text and schema.extra.get("content"):
            import html as _html
            import re as _re

            j.jd_text = _re.sub(r"<[^>]+>", " ", _html.unescape(schema.extra["content"]))
        job = j
        s.expunge(j)

    cover = materials.existing_cover_letter(job.id) if not instructions else None
    new_letter = False
    if cover is None and materials.needs_cover_letter(job, [(q.label, q.required) for q in schema.questions if q.type == "file"]):
        cover = materials.make_cover_letter(job, instructions=instructions)
        new_letter = True
    from . import tailor

    resume, new_resume, tailor_note = None, False, ""
    if any(q.type == "file" and re.search(r"resume|résumé|\bcv\b", q.label, re.I) for q in schema.questions):
        try:
            resume, new_resume = tailor.for_job(job)
        except llm.LLMUnavailable:
            raise
        except Exception as e:  # noqa: BLE001 - the application goes ahead with the résumé as uploaded
            tailor_note = f"Tailored résumé was not written ({str(e)[:160]}); the uploaded résumé is attached instead."
    res = ans.resolve(schema, job, cover_letter=cover, resume=resume)
    notes = list(res["notes"])
    if tailor_note:
        notes.append(tailor_note)
    if cover is not None and not new_letter:
        notes_reuse = f"Cover letter '{cover['name']}' written earlier for this job is attached again."
        if any(m["kind"] == "cover_letter" for m in res["materials"]):
            res.setdefault("info", []).append(notes_reuse)
    prev = _last_approved(app_id)
    if prev is not None:
        n_delta = _carry_over(res, prev)
        if n_delta:
            notes.append(f"Form changed since the approved draft v{prev['version']}: {n_delta} new or changed question(s) need review; the other answers are carried over.")
    if cover and cover.get("problems"):
        notes.append("Cover letter still has open issues: " + "; ".join(cover["problems"]))
    if schema.source == "agent" and len(schema.pages) > 1:
        # A form with several steps often shows a step only after the ones before it are filled. Steps that had no
        # questions to read are named, so that the draft does not look complete when it is not.
        unseen = [str(name)[:80] for i, name in enumerate(schema.pages) if not any(q.page == i for q in schema.questions)
                  and not re.search(r"review|submit|summary|confirm", str(name), re.I)]
        if unseen:
            notes.append("Steps of this form that could not be read yet: " + "; ".join(unseen[:8]) + ". The form shows them only after the earlier steps are filled; "
                         "they are read the first time the form is filled, and what they ask is added to this draft.")
    driver = registry.get(ref.ats)
    requires_login = bool(driver and driver.requires_login)
    fill = ans.to_fill_map(res["answers"])
    steps = plan_steps(ref, schema, fill, res["materials"], requires_login)
    draft_dict = {"answers": res["answers"], "unresolved": res["unresolved"], "notes": notes}
    check = ans.auto_approve_check(draft_dict, job, ref.ats, ref.tenant_key, new_cover_letter=new_letter, new_resume=new_resume)

    with db.session() as s:
        app = s.get(Application, app_id)
        stale = []
        for old in app.drafts:
            if old.review_status in ("pending", "approved"):
                old.review_status = "superseded"
                stale.append(old.id)
        d = Draft(
            application_id=app_id,
            version=len(app.drafts) + 1,
            schema={**schema.to_dict(), "_ref": {"ats": ref.ats, "tenant": ref.tenant, "job_id": ref.job_id, "url": ref.url, "host": ref.host, "extra": ref.extra}},
            answers=res["answers"],
            unresolved=res["unresolved"],
            materials=res["materials"],
            plan=steps,
            notes=notes + [f"Proposed rule (confirm to save to profile): {r}" for r in res["new_rules"]],
            auto_approve_check=check,
        )
        s.add(d)
        app.status = "needs_input" if res["unresolved"] else "draft_ready"
        s.flush()
        draft_id = d.id
    for old_id in stale:  # their open questions belong to a draft that no longer exists
        notify.close_todos("answer", f"draft:{old_id}")
    if any("No résumé has been uploaded" in n for n in notes):
        notify.add_todo("config", "还没有上传简历", body="草案里的简历栏是空的。请在“个人资料 → 材料”里上传简历，然后重新生成草案。", ref="config:resume")
    if res["unresolved"]:
        qs = "\n".join("· " + str(u["label"])[:90] for u in res["unresolved"][:6])
        notify.add_todo("answer", f"{job.company} · {job.title}", body=f"{len(res['unresolved'])} 个问题没有答案：\n{qs}", ref=f"draft:{draft_id}", payload={"draft_id": draft_id})
    elif check["eligible"]:
        approve(draft_id, auto=True)
    else:
        from pathlib import Path

        files = [Path(str(v)).name for a in res["answers"] if a["type"] == "file" and (v := a.get("value"))]
        n_ans = sum(1 for a in res["answers"] if a["type"] != "file" and a.get("value") not in ("", None, []))
        notify.send("todo", messages.draft_ready(f"{job.company} · {job.title}", draft_id, answers=n_ans, files=files, why_not_auto=check["failed"]), ref=f"draft:{draft_id}")
    return draft_id


def dedupe_ids(d: Draft) -> int:
    """Older drafts of explored forms can hold several questions under one id (the form was described with selectors like
    "the 2nd drop-down" on each page). Give each its own, in the schema and in the answers alike. Returns how many changed."""
    from .generic import unique_ids

    sch = dict(d.schema)
    qs = [dict(q) for q in sch.get("questions", [])]
    old = [q["id"] for q in qs]
    if len(set(old)) == len(old):
        return 0
    new = unique_ids([((q.get("locator") or {}).get("selector") or q["id"], int(q.get("page") or 0), q["label"]) for q in qs])
    by_pair = {(o, q["label"]): n for o, n, q in zip(old, new, qs)}
    for q, n in zip(qs, new):
        q.setdefault("locator", {}).setdefault("selector", q["id"])
        q["id"] = n
    rows = [{**a, "id": by_pair.get((a["id"], a["label"]), a["id"])} for a in d.answers]
    sch["questions"] = qs
    d.schema, d.answers = sch, rows
    d.unresolved = [r for r in rows if r.get("source") == "unresolved" and r.get("required")]
    return sum(1 for o, n in zip(old, new) if o != n)


def reanswer(draft_id: int) -> dict[str, Any]:
    """Ask the AI again for the questions of a pending draft that have no answer (after the profile was filled in, or after
    a draft was built from a badly described form). Answers already there are not touched."""
    with db.session() as s:
        d = s.get(Draft, draft_id)
        if d is None or d.review_status != "pending":
            raise ValueError("只有待审批的草案可以重新回答")
        fixed = dedupe_ids(d)
        s.flush()
        raw = {k: v for k, v in dict(d.schema).items() if not k.startswith("_")}
        schema = FormSchema.from_dict(raw)
        todo = {a["id"] for a in d.answers if a.get("source") == "unresolved"}
        job = d.application.job
        s.expunge(job)
        app_id = d.application_id
    if not todo:
        return {"asked": 0, "answered": 0, "left": 0, "ids_fixed": fixed}
    res = ans.resolve(schema, job, only=todo)
    fresh = {r["id"]: r for r in res["answers"]}
    with db.session() as s:
        d = s.get(Draft, draft_id)
        rows = [fresh.get(a["id"], a) if a["id"] in todo else a for a in d.answers]
        d.answers = rows
        d.unresolved = [r for r in rows if r.get("source") == "unresolved" and r.get("required")]
        left = len(d.unresolved)
        d.notes = list(d.notes) + [f"Proposed rule (confirm to save to profile): {r}" for r in res["new_rules"]]
        a = s.get(Application, app_id)
        if a.status in ("needs_input", "draft_ready"):
            a.status = "needs_input" if left else "draft_ready"
        labels = [str(u["label"])[:90] for u in d.unresolved[:6]]
        title = f"{job.company} · {job.title}"
    notify.close_todos("answer", f"draft:{draft_id}")
    if left:
        notify.add_todo("answer", title, body=f"{left} 个问题没有答案：\n" + "\n".join("· " + x for x in labels), ref=f"draft:{draft_id}", payload={"draft_id": draft_id}, push=False)
    return {"asked": len(todo), "answered": len(todo) - sum(1 for i in todo if fresh.get(i, {}).get("source") == "unresolved" or i not in fresh), "left": left, "ids_fixed": fixed}


def refresh_files(d: Draft) -> list[str]:
    """Fill upload fields that are still empty from the files the user has now (a transcript uploaded after the draft was
    prepared, for instance). Fields that already have a file are left as they are. Returns the labels that were filled."""
    schema = FormSchema.from_dict({k: v for k, v in d.schema.items() if not k.startswith("_")})  # "_ref" is the draft's own bookkeeping
    empty = [a for a in d.answers if a["type"] == "file" and not a.get("value")]
    if not empty:
        return []
    job = d.application.job
    cover = materials.existing_cover_letter(job.id)
    found, mats, _ = ans.file_slots(schema, job, cover)
    filled = []
    new_answers, new_mats = [], list(d.materials)
    for a in d.answers:
        if a["type"] == "file" and not a.get("value") and found.get(a["id"]):
            a = {**a, "value": found[a["id"]], "basis": "matched to a file in the library", "confidence": "high", "source": "materials"}
            new_mats = [m for m in new_mats if m["slot"] != a["id"]] + [m for m in mats if m["slot"] == a["id"]]
            filled.append(a["label"])
        new_answers.append(a)
    if filled:
        d.answers, d.materials = new_answers, new_mats
        d.unresolved = [u for u in d.unresolved if u["id"] not in {a["id"] for a in new_answers if a["type"] == "file" and a.get("value")}]
        d.notes = [n for n in d.notes if not any(f"'{lab}' has no matching document" in n for lab in filled)]
    return filled


def swap_resume(d: Draft, doc: dict[str, Any] | None) -> int:
    """Point the résumé slot(s) of a draft at ``doc`` (None = the résumé as uploaded). Returns how many slots changed."""
    if doc is None:
        doc = ans._active_doc("resume_site") or ans._active_doc("resume_portal")
        if doc is None:
            return 0
    slots = [m["slot"] for m in d.materials if m["kind"] in ("resume_site", "resume_portal", "tailored_resume")]
    if not slots:
        return 0
    d.materials = [{**m, "document_id": doc["id"], "name": doc["name"], "kind": doc["kind"], "path": doc["path"]} if m["slot"] in slots else m for m in d.materials]
    d.answers = [{**a, "value": doc["path"]} if a["id"] in slots else a for a in d.answers]
    return len(slots)


def _last_approved(app_id: int) -> dict[str, Any] | None:
    with db.session() as s:
        # every draft the user approved counts, including one a form change has since superseded
        ds = [d for d in s.get(Application, app_id).drafts if d.approved_at is not None]
        if not ds:
            return None
        d = max(ds, key=lambda x: x.version)
        return {"version": d.version, "answers": list(d.answers)}


def _carry_over(res: dict[str, Any], prev: dict[str, Any]) -> int:
    """Delta draft: questions the user already approved keep their approved answers; each row gets
    ``delta`` = "" (unchanged) | "new" | "changed" (same label, different options). Returns the number of delta rows."""
    from .ats.base import norm_question, options_hash

    key = lambda a: (norm_question(a["label"]), options_hash(a.get("options") or []))  # noqa: E731
    old = {key(a): a for a in prev["answers"]}
    old_labels = {norm_question(a["label"]) for a in prev["answers"]}
    n = 0
    for r in res["answers"]:
        r["delta"] = ""
        if r["type"] == "file":
            continue
        p = old.get(key(r))
        if p is None:
            r["delta"] = "changed" if norm_question(r["label"]) in old_labels else "new"
            n += 1
        elif p["value"] not in ("", None, []):
            r.update(value=p["value"], basis=f"carried over from approved draft v{prev['version']}", confidence="high", source="profile",
                     sensitive_confirmed=bool(r.get("sensitive")))
    res["unresolved"] = [r for r in res["answers"] if r["required"] and r["type"] != "file" and r["value"] in ("", None, []) and (r["source"] == "unresolved" or r["delta"])]
    for r in res["unresolved"]:
        r["source"] = "unresolved"
    return n


def _set_app(app_id: int, status: str, event: str = "") -> None:
    with db.session() as s:
        a = s.get(Application, app_id)
        a.status = status
        if event:
            a.last_event = event


def _submit_mode(ats: str, company: str, answers: list[dict[str, Any]]) -> dict[str, Any]:
    from . import executor

    return executor.submit_mode(ats, company, answers, has_driver=registry.get(ats) is not None)


def get(draft_id: int) -> dict[str, Any]:
    with db.session() as s:
        d = s.get(Draft, draft_id)
        if d is None:
            raise KeyError(draft_id)
        app, job = d.application, d.application.job
        return {
            "id": d.id, "version": d.version, "review_status": d.review_status, "created_at": d.created_at.isoformat(),
            "application": {"id": app.id, "status": app.status, "last_event": app.last_event},
            "job": {"id": job.id, "company": job.company, "title": job.title, "deadline": job.deadline, "score": job.score,
                    "score_reason": job.score_reason, "apply_url": job.apply_url, "ats": job.ats, "source_id": job.source_id},
            "pages": d.schema.get("pages", []),
            "answers": d.answers, "unresolved": d.unresolved, "materials": d.materials, "plan": d.plan, "notes": d.notes,
            "auto_approve_check": d.auto_approve_check,
            "submit_mode": _submit_mode(d.schema.get("ats", ""), job.company, d.answers),
            "comments": [{"comment": c.comment, "result": c.result, "created_at": c.created_at.isoformat()} for c in d.comments],
        }


def edit_answer(draft_id: int, qid: str, value: Any, *, save_rule: str = "", remember: bool = False) -> None:
    """User edits one answer inline. The edit is authoritative: high confidence, user-confirmed."""
    with db.session() as s:
        d = s.get(Draft, draft_id)
        new = []
        label = next((a.get("label", "") for a in d.answers if a["id"] == qid), "")
        for a in d.answers:
            if a["id"] == qid:
                a = {**a, "value": value, "basis": "edited by user", "confidence": "high", "source": "profile", "sensitive_confirmed": bool(a.get("sensitive"))}
            new.append(a)
        d.answers = new
        d.unresolved = [u for u in d.unresolved if u["id"] != qid or value in ("", None, [])]
        resolved_all = not d.unresolved and d.application.status == "needs_input"
        if resolved_all:
            d.application.status = "draft_ready"
    if resolved_all:  # outside the session: SQLite allows one writer at a time
        notify.close_todos("answer", f"draft:{draft_id}")
    shown = "; ".join(map(str, value)) if isinstance(value, list) else {True: "Yes (tick the box)", False: "No (leave the box unticked)"}.get(value, str(value)) if isinstance(value, bool) else str(value)
    note = save_rule.strip()
    if remember or note:
        # a rule is only usable later if it says what was asked; a bare "No" means nothing on the next form
        rule = f'Form question "{label.strip()[:200]}": answer "{shown[:300]}".' + (f" Note: {note}" if note and note.lower() != shown.lower() else "")
        knowledge.append_rule(rule, source="user", section="Standard answers")


REVISE_SCHEMA = llm.obj(
    {
        "answer_edits": {"type": "array", "items": llm.obj({"id": {"type": "string"}, "value": {"type": "string"}, "basis": {"type": "string"}})},
        "rewrite_cover_letter": {"type": "boolean"},
        "cover_letter_instructions": {"type": "string"},
        "profile_rule": {"type": "string", "description": "a general rule to save to the profile, or empty if the comment is a one-off"},
        "reply": {"type": "string", "description": "one or two sentences telling the applicant what was changed. Write this in Simplified Chinese (it is shown to the applicant); keep company names, product names and quoted form text in their original language."},
    }
)


REVISE_RULES = """Apply the applicant's comment to this application draft. Change only what the comment asks for.
Upload fields are matched to the applicant's files by the program, not by you: when the comment says a file was uploaded or
asks to attach one that is listed under files_in_the_applicants_library, say that it has been attached (the program does it);
never ask the applicant for a file path.
The files under cover_letter_references (templates and example letters the applicant uploaded) are read automatically
whenever a cover letter is written; set rewrite_cover_letter to have one written and attached.
Select values must be copied exactly from the options. If the comment states a preference that should apply to
future applications too, put it in profile_rule as one sentence; otherwise leave profile_rule empty."""


def _library() -> list[str]:
    from .models import Document

    with db.session() as s:
        return [f"{x.kind}: {x.name}" for x in s.query(Document).filter(Document.active == 1, Document.job_id.is_(None)).order_by(Document.id)]


def revise(draft_id: int, comment: str) -> dict[str, Any]:
    """Apply a natural-language review comment; produces a new draft version."""
    with db.session() as s0:  # files the applicant uploaded since the draft was prepared go into their fields first
        d0 = s0.get(Draft, draft_id)
        if d0 is not None and d0.review_status == "pending":
            refresh_files(d0)
    cur = get(draft_id)
    listing = "\n".join(f"- id={a['id']} | {a['label']!r} | type={a['type']} | options={a.get('options') or ''} | current={a['value']!r}" for a in cur["answers"])
    prompt = (
        f"<profile>\n{knowledge.read('profile')}\n</profile>\n<draft_answers>\n{listing}\n</draft_answers>\n"
        f"<materials attached_to_this_draft>\n{[m['name'] for m in cur['materials']]}\n</materials>\n"
        f"<files_in_the_applicants_library>\n{_library()}\n</files_in_the_applicants_library>\n"
        f"<cover_letter_references>\n{materials.reference_names()}\n</cover_letter_references>\n<applicant_comment>\n{comment}\n</applicant_comment>\n"
    )
    out = llm.json(prompt, REVISE_SCHEMA, system=prompts.get("revise"))
    with db.session() as s:
        d = s.get(Draft, draft_id)
        app, job = d.application, d.application.job
        edits = {e["id"]: e for e in out["answer_edits"]}
        new_answers = []
        for a in d.answers:
            if a["id"] in edits:
                e = edits[a["id"]]
                val: Any = e["value"]
                if a["type"] == "checkbox":
                    val = val.strip().lower() in ("true", "yes", "1")
                elif a["type"] == "multiselect":
                    val = [v.strip() for v in val.split("||") if v.strip()]
                if a["type"] in ("select", "radio") and a.get("options") and val not in a["options"]:
                    new_answers.append(a)
                    continue
                a = {**a, "value": val, "basis": f"revised per comment: {e['basis']}", "confidence": "high", "source": "profile", "sensitive_confirmed": bool(a.get("sensitive"))}
            new_answers.append(a)
        mats = list(d.materials)
        s.expunge(job)
    if out["rewrite_cover_letter"]:
        cl = materials.make_cover_letter(job, instructions=out["cover_letter_instructions"] or comment)
        if not any(m["kind"] == "cover_letter" for m in mats):
            # The draft had no letter yet: put this one in the form's cover-letter slot (or, failing that, a free "other" file slot).
            taken = {m["slot"] for m in mats}
            free = [a for a in new_answers if a["type"] == "file" and a["id"] not in taken]
            slot = next((a for a in free if "cover" in a["label"].lower()), None) or next((a for a in free if re.search(r"other|additional|supporting", a["label"], re.I)), None)
            if slot is None:
                raise ValueError("the form has no free upload field for a cover letter")
            mats.append({"slot": slot["id"], "slot_label": slot["label"], "document_id": cl["id"], "name": cl["name"], "kind": "cover_letter", "path": cl["path"]})
        mats = [({**m, "document_id": cl["id"], "name": cl["name"], "path": cl["path"]} if m["kind"] == "cover_letter" else m) for m in mats]
        new_answers = [({**a, "value": cl["path"]} if a["type"] == "file" and any(m["slot"] == a["id"] and m["kind"] == "cover_letter" for m in mats) else a) for a in new_answers]
    with db.session() as s:
        d = s.get(Draft, draft_id)
        d.review_status = "superseded"
        s.add(DraftComment(draft_id=draft_id, comment=comment, result=out["reply"]))
        nd = Draft(application_id=d.application_id, version=d.version + 1, schema=d.schema, answers=new_answers,
                   unresolved=[u for u in d.unresolved if not (u["id"] in edits and edits[u["id"]]["value"])],
                   materials=mats, plan=d.plan, notes=d.notes, auto_approve_check={"eligible": False, "failed": ["revised_by_user"], "checks": {}})
        s.add(nd)
        d.application.status = "needs_input" if nd.unresolved else "draft_ready"
        s.flush()
        new_id = nd.id
    notify.close_todos("answer", f"draft:{draft_id}")
    return {"draft_id": new_id, "reply": out["reply"], "profile_rule": out["profile_rule"]}


def approve(draft_id: int, *, auto: bool = False) -> None:
    with db.session() as s:
        d = s.get(Draft, draft_id)
        if d.unresolved:
            raise ValueError("draft still has unanswered required questions")
        if any("No résumé has been uploaded" in n for n in d.notes or []):
            raise ValueError("no résumé has been uploaded: add one under Profile → Documents and rebuild the draft")
        if d.review_status not in ("pending",):
            raise ValueError(f"draft is {d.review_status}")
        d.review_status, d.approved_at = "approved", now()
        app, job = d.application, d.application.job
        app.status, app.auto_approved = "approved", int(auto)
        ats = d.schema.get("ats", "")
        answers_copy = list(d.answers)
        title = f"{job.company} · {job.title}"
        app_id = app.id
        deadline = job.deadline
    # A human approval confirms the answers (including sensitive ones) for reuse.
    ans.remember(ats, answers_copy, confirmed=not auto)
    from . import tasks

    tasks.enqueue("execute", ref=f"application:{app_id}", payload={"draft_id": draft_id}, priority=tasks.deadline_priority(deadline))
    if auto:
        notify.send("status_update", messages.auto_approved(title, draft_id), ref=f"draft:{draft_id}")


def reject(draft_id: int, *, withdraw: bool = False) -> None:
    with db.session() as s:
        d = s.get(Draft, draft_id)
        d.review_status = "rejected"
        d.application.status = "withdrawn" if withdraw else "draft_ready"
