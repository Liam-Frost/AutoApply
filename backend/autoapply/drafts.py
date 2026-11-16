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


def recon(job: Job, run_dir, given: dict[str, Any] | None = None) -> tuple[JobRef, FormSchema]:  # noqa: ANN001
    """Get the form schema. Opens a browser only when the driver needs one. ``given``: answers the applicant has
    already given for this application (see _given) - a form that is read by filling it needs them to get on."""
    ref = job_ref(job)
    driver = registry.get(ref.ats)
    if driver is None:
        from . import generic

        return generic.recon(job, ref, run_dir)
    reads = db.get_setting("agent.reads") or []
    # (the university's portal does not allow programs to operate it: nothing reads it, coded or not)
    if ("*" in reads or ref.ats in reads) and ref.ats != "pdportal":
        # A form that is a walk through several steps is read by the agent: it looks at each page and decides what to do
        # there. The coded driver does what code does well - signing in with the saved session or password - and hands over.
        from . import generic

        if driver.requires_login:
            with browser.open_page(ref.tenant_key, url=ref.url, operation="read") as page:
                auth.ensure_session(page, driver, ref)
        return generic.recon(job, ref, run_dir)
    if not driver.requires_login and ref.tenant:
        if getattr(driver, "page_extras", False):  # the API misses blocks that only the page shows
            with browser.open_page(url=ref.url, operation="read") as page:
                return ref, driver.get_schema(ref, page)
        return ref, driver.get_schema(ref, None)
    with browser.open_page(ref.tenant_key if driver.requires_login else None, url=ref.url, operation="read") as page:
        if not ref.tenant and hasattr(driver, "resolve_board"):
            ref = driver.resolve_board(page, ref)  # type: ignore[attr-defined]
            return ref, driver.get_schema(ref, None)
        auth.ensure_session(page, driver, ref)
        # Walk with profile-derived answers so conditional questions appear.
        schema = driver.get_schema(ref, page, answers=_walk_answerer(job, given))
        browser.snapshot(page, run_dir, "recon_last_page")
        return ref, schema


def _walk_answerer(job: Job, given: dict[str, Any] | None = None):
    """Callback a multi-page driver uses during the walk: questions -> fill map. What the applicant has answered for this
    application before goes first: that is what lets the reading pass the step it stopped on last time."""

    def answer(partial: FormSchema) -> dict[str, Any]:
        res = ans.resolve(partial, job)
        _use_given(res, given)
        return ans.to_fill_map(res["answers"])

    return answer


def _answer_key(a: dict[str, Any]) -> tuple[str, str]:
    from .ats.base import norm_question, options_hash

    return norm_question(a["label"]), options_hash(a.get("options") or [])


def _given(app_id: int) -> dict[str, Any]:
    """Answers the applicant gave themselves in the drafts of this application that were never approved (typed into a
    draft, or into the application window), by question. A draft that is built again must not ask for them again."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    with db.session() as s:
        a = s.get(Application, app_id)
        for d in sorted(a.drafts if a else [], key=lambda x: x.version):
            for r in d.answers or []:
                mine = r.get("basis") in ("edited by user", "你在申请窗口里填的") or str(r.get("basis") or "").startswith("revised per comment")
                if mine and r.get("type") != "file" and r.get("value") not in ("", None, []):
                    out[_answer_key(r)] = {"value": r["value"], "basis": r["basis"]}
    return out


def _use_given(res: dict[str, Any], given: dict[str, Any] | None) -> int:
    """Put the applicant's own earlier answers into freshly resolved ones. Returns how many were used."""
    n = 0
    for r in res["answers"] if given else []:
        g = given.get(_answer_key(r))
        if g is not None and r["type"] != "file":
            r.update(value=g["value"], basis="edited by user", confidence="high", source="profile", sensitive_confirmed=bool(r.get("sensitive")))
            n += 1
    if n:
        res["unresolved"] = [r for r in res["answers"] if r["required"] and r["type"] != "file" and r["value"] in ("", None, []) and r["source"] == "unresolved"]
    return n


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
    given = _given(app_id)
    try:
        ref, schema = recon(job, run_dir, given)
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
    for kind in ("takeover", "login", "blocked"):      # the form was reached and read: a card that asked for a sign-in for it has nothing left to ask
        notify.close_todos(kind, f"account:{ref.tenant_key}")
        notify.close_todos(kind, f"job:{job_id}")
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
    _use_given(res, given)
    for r in res["answers"]:      # rows the form already holds from an earlier application and the reading left alone
        kept = (schema.extra.get("held") or {}).get(r["id"])
        if kept not in (None, ""):
            r.update(value=kept, basis="雇主网站上已经存着这个答案（来自以前的申请或你在那里的资料），程序没有改动", confidence="high", source="site", held=True)
    notes = list(res["notes"])
    stop = schema.extra.get("stopped_at") if schema.source == "walk" else None
    if stop:
        # The form was read by filling it step by step, and one step would not let go. Say how far the reading got: a
        # draft that covers two steps of six must not look complete.
        steps_all = [str(x) for x in schema.extra.get("steps") or []]
        left = [x for x in steps_all[int(stop.get("page", 0)) + 1:] if not re.search(r"^review$", x, re.I)]
        said = "; ".join(str(e).replace("\n", " ")[:160] for e in (stop.get("errors") or [])[:3])
        notes.append(f"This form was read up to its step \"{(schema.pages or ['?'])[-1]}\"; that step did not let the program go on"
                     + f" (the form said: {said or 'nothing'}). Not read yet: {'; '.join(left[:8]) or 'nothing'}"
                     + ". Answer the open questions and the reading goes on from there by itself.")
    for it in (schema.extra.get("walk_issues") or [])[:6]:
        notes.append(f"While reading the form, the field \"{it['label']}\" could not be filled in ({it['why'][:120]}).")
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
        schema.extra["read"] = [str(name) for i, name in enumerate(schema.pages) if any(q.page == i for q in schema.questions)]
        unseen = unseen_steps(schema)
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
        app.last_event = ""      # what an earlier attempt ended with is not what is true now
        s.flush()
        draft_id = d.id
        # With stand-ins allowed, an open question on the first step does not hold the reading back: the form is walked
        # to its end first, and the applicant is asked once, for everything.
        to_scout = bool(unseen_steps(schema)) and bool(db.get_setting("recon.walk")) and (not res["unresolved"] or bool(db.get_setting("recon.provisional")))
        if to_scout:
            app.status = "recon"      # still being read: the later steps are next
    for old_id in stale:  # their open questions belong to a draft that no longer exists
        notify.close_todos("answer", f"draft:{old_id}")
    if any("No résumé has been uploaded" in n for n in notes):
        notify.add_todo("config", "还没有上传简历", body="草案里的简历栏是空的。请在“个人资料 → 材料”里上传简历，然后重新生成草案。", ref="config:resume")
    if to_scout:
        # The form opens its later steps only once the earlier ones are filled: walk it with this draft's answers (no
        # submitting) to read them, before the applicant is asked to approve anything. The task finishes the draft.
        from . import tasks

        tasks.enqueue("scout", ref=f"draft:{draft_id}", payload={"draft_id": draft_id}, priority=tasks.deadline_priority(job.deadline))
        return draft_id
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
        if r["type"] == "file" or r.get("held"):      # a row the site holds is shown as it is there, whatever an earlier draft said
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
            "locked": locked(d),            # why nothing in it can be changed now; "" when the applicant can change it
            "application": {"id": app.id, "status": app.status, "last_event": app.last_event},
            "job": {"id": job.id, "company": job.company, "title": job.title, "deadline": job.deadline, "score": job.score,
                    "score_reason": job.score_reason, "apply_url": job.apply_url, "ats": job.ats, "source_id": job.source_id},
            "pages": d.schema.get("pages", []),
            # steps of the form that have not been read yet (they open only once the earlier ones are filled)
            "unseen": _unseen_of(d),
            "walk_open": bool((d.schema.get("extra") or {}).get("walk_open")),      # a walk stopped before the review page
            "answers": d.answers, "unresolved": d.unresolved, "materials": d.materials, "plan": d.plan, "notes": d.notes,
            "auto_approve_check": d.auto_approve_check,
            "submit_mode": _submit_mode(d.schema.get("ats", ""), job.company, d.answers),
            "comments": [{"comment": c.comment, "result": c.result, "created_at": c.created_at.isoformat()} for c in d.comments],
        }


def _schema_of(d: Draft) -> FormSchema:
    return FormSchema.from_dict({k: v for k, v in d.schema.items() if not k.startswith("_")})


def _unseen_of(d: Draft) -> list[str]:
    try:
        return unseen_steps(_schema_of(d))
    except Exception:  # noqa: BLE001
        return []


def needs_walk(d: Draft) -> bool:
    """Is there still something of this form to read by walking it: steps nobody has read, or a walk that stopped
    before the review page?"""
    return bool(_unseen_of(d)) or bool((d.schema.get("extra") or {}).get("walk_open"))


def walk_pending(limit: int = 3) -> int:
    """Drafts that wait for approval while steps of their form are still unread, with nothing open for the applicant to
    answer: the reading is started for them. Nobody should have to press a button for the program to finish reading.
    A draft is not walked more than a few times by itself (a form that will not let the walk through stays as it is, with
    its note), and not while something else is already working on it. Returns how many walks were queued."""
    from . import tasks
    from .models import Task

    if not db.get_setting("recon.walk") or db.get_setting("schedule.paused"):
        return 0
    todo: list[tuple[int, str]] = []
    with db.session() as s:
        busy = {t.ref for t in s.query(Task).filter(Task.kind.in_(("scout", "recon", "execute")), Task.status.in_(("queued", "running")))}
        for d in s.query(Draft).filter_by(review_status="pending").order_by(Draft.id.desc()):
            app = d.application
            if app is None or app.status not in ("draft_ready", "recon", "needs_input") or (d.unresolved and not db.get_setting("recon.provisional")):
                continue
            if f"draft:{d.id}" in busy or f"job:{app.job_id}" in busy or f"application:{app.id}" in busy:
                continue
            if int((d.schema.get("extra") or {}).get("scouted") or 0) >= 3 or not needs_walk(d):
                continue
            app.status = "recon"
            todo.append((d.id, app.job.deadline or ""))
            if len(todo) >= limit:
                break
    for did, deadline in todo:
        tasks.enqueue("scout", ref=f"draft:{did}", payload={"draft_id": did}, priority=tasks.deadline_priority(deadline))
    return len(todo)


def read_titles(schema: FormSchema) -> list[str]:
    """The steps of an explored form that have been read completely: when the form was first read, or on a walk.
    A draft from before this was kept: the steps where the first reading found a control (a question that is known only
    by its label was met later, while filling)."""
    if "read" in schema.extra:
        return [str(t) for t in schema.extra["read"] or []]
    found = {q.page for q in schema.questions if not str((q.locator or {}).get("selector") or q.id).startswith("@label:")}
    return [str(name) for i, name in enumerate(schema.pages or []) if i in found]


def unseen_steps(schema: FormSchema, also: list[str] | None = None) -> list[str]:
    """Steps of an explored form that nobody has read yet (they open only once the earlier ones are filled).
    ``also``: steps read just now, by the title the form shows."""
    from .ats.base import norm_question

    if schema.source != "agent" or len(schema.pages or []) < 2:
        return []
    read = [t for t in (norm_question(str(x)) for x in [*read_titles(schema), *(also or [])]) if t]

    def was_read(name: str) -> bool:
        nm = norm_question(name)
        return any(t in nm or nm in t for t in read)

    return [str(name)[:80] for name in schema.pages if not re.search(r"review|submit|summary|confirm", str(name), re.I) and not was_read(str(name))]


SCOUT_NOTES = ("Steps of this form that could not be read yet", "The later steps of this form were read", "Reading the later steps")


def scout(draft_id: int, *, task_id: int | None = None) -> dict[str, Any]:
    """Walk the form with the draft's answers to read the steps that were not readable (see executor.execute, scout).
    Updates the draft with what was found and decides what the applicant sees next: the draft to approve, or the
    questions only they can answer. Answering those starts the walk again from where it stopped."""
    from . import executor

    with db.session() as s:
        d = s.get(Draft, draft_id)
        if d is None or d.review_status != "pending":
            return {"skipped": "the draft is no longer pending"}
        app_id = d.application_id
        rounds = int((d.schema.get("extra") or {}).get("scouted") or 0)
        read_before = read_titles(_schema_of(d))      # taken before the walk adds what it finds
    if rounds >= 6:      # answering starts the walk again by itself; this is the end of that, not of a walk asked for by hand
        with db.session() as s:
            d = s.get(Draft, draft_id)
            if d.application.status == "recon":      # not left as "being read" for ever
                d.application.status = "needs_input" if d.unresolved else "draft_ready"
        return {"skipped": "walked six times already"}
    try:
        out = executor.execute(app_id, draft_id, task_id=task_id, scout=True)
    except NeedsHuman:
        out = {"status": "needs_human"}
        raise
    except Exception as e:  # noqa: BLE001 - the draft must not stay "being read" for ever
        out = {"status": "failed", "error": f"{type(e).__name__}: {e}"[:300]}
    finally:
        with db.session() as s:
            d = s.get(Draft, draft_id)
            app, job = d.application, d.application.job
            sch = dict(d.schema)
            extra = dict(sch.get("extra") or {})
            extra["scouted"] = rounds + 1
            extra.pop("unseen", None)      # kept by an earlier version; what is unread is worked out from what was read
            if out.get("status") == "scouted":
                names = [str(x) for x in sch.get("pages") or []] if out.get("all_read") else []
                extra["read"] = list(dict.fromkeys([*read_before, *(out.get("read") or []), *names]))
                extra["walk_open"] = not out.get("reached_review")
                try:      # the site's plan: what the agent read on this posting is known for the next one
                    from . import repair, siteplan

                    siteplan.learn(repair.site_key(_schema_of(d)), [str(x) for x in sch.get("pages") or []], list(sch.get("questions") or []), list(extra["read"]))
                except Exception:  # noqa: BLE001 - never a reason to lose the walk's result
                    log.exception("could not update the site's plan")
            sch["extra"] = extra
            d.schema = sch
            notes = [n for n in (d.notes or []) if not n.startswith(SCOUT_NOTES)]
            open_n = len(d.unresolved or [])
            if out.get("status") == "scouted" and out.get("reached_review"):
                notes.append(f"The later steps of this form were read by filling in this draft's answers step by step, up to the review page; nothing was submitted. "
                             # the draft's totals, not this walk's: a later walk finds nothing new and must not say "0"
                             f"{sum(1 for a in d.answers if a.get('source') == 'agent_added')} answer(s) were added from your profile; "
                             f"{sum(1 for a in d.answers if a.get('held'))} answer(s) the employer's site already holds were "
                             f"read into the draft; {open_n} question(s) need your answer.")
            elif out.get("status") == "scouted":
                notes.append(f"Reading the later steps stopped at \"{out.get('stopped_at') or '?'}\": {open_n} question(s) there need your answer. "
                             "Answer them and the reading goes on from there; nothing was submitted.")
            elif out.get("status") != "skipped":
                notes.append("Reading the later steps did not work this time; they are read when the form is filled, and what they ask is added to this draft.")
            d.notes = notes
            d.auto_approve_check = {**(d.auto_approve_check or {}), "eligible": False}      # the check was made before these answers existed
            if d.review_status == "pending" and app.status in ("recon", "draft_ready", "needs_input"):
                app.status = "needs_input" if d.unresolved else "draft_ready"
            title, unresolved = f"{job.company} · {job.title}", list(d.unresolved or [])
            answers = list(d.answers)
        notify.close_todos("answer", f"draft:{draft_id}")
        if unresolved:
            qs = "\n".join("· " + str(u["label"])[:90] for u in unresolved[:6])
            notify.add_todo("answer", title, body=f"{len(unresolved)} 个问题没有答案：\n{qs}", ref=f"draft:{draft_id}", payload={"draft_id": draft_id})
        else:
            from pathlib import Path

            files = [Path(str(v)).name for a in answers if a["type"] == "file" and (v := a.get("value"))]
            n_ans = sum(1 for a in answers if a["type"] != "file" and a.get("value") not in ("", None, []))
            notify.send("todo", messages.draft_ready(title, draft_id, answers=n_ans, files=files, why_not_auto=["no_unusual_notes"]), ref=f"draft:{draft_id}")
    return out


SENT = ("submitted", "confirmed", "interview", "assessment", "offer", "rejected")


class Locked(ValueError):
    """The draft cannot be changed now; the message says why, for the applicant."""


def locked(d: Draft) -> str:
    """Why this draft cannot be changed ('' when it can).

    The applicant can change anything in a draft for as long as the application has not gone out - before approving
    it and after. Approving is their word that the answers are right; changing an answer afterwards is their word
    again, so the draft stays approved and the next run fills in what it says now. A draft is closed only when
    changing it could no longer do what the applicant means: it is an old version, the application was sent (the
    draft is then the record of what was sent), or a run is filling the form from it this moment."""
    if d.review_status not in ("pending", "approved"):
        return "这是草案的旧版本，不能再改。请打开最新的那一版。"
    status = d.application.status
    if status in SENT:
        return "这份申请已经发出去了，草案保留作记录，不能再改。"
    if status == "executing":
        return "程序正在按这份草案填写表单，等这一次结束后再改。"
    return ""


def edit_answer(draft_id: int, qid: str, value: Any, *, save_rule: str = "", remember: bool = False) -> None:
    """User edits one answer inline. The edit is authoritative: high confidence, user-confirmed."""
    with db.session() as s:
        d = s.get(Draft, draft_id)
        why = locked(d)
        if why:
            raise Locked(why)
        new = []
        label = next((a.get("label", "") for a in d.answers if a["id"] == qid), "")
        corrected = d.review_status == "approved" and str(d.schema.get("ats") or "")       # the approval cached the old value as theirs
        if d.review_status == "approved":
            # after the approval: kept where the applicant's other changes to this draft are listed
            before = next((a.get("value") for a in d.answers if a["id"] == qid), None)
            s.add(DraftComment(draft_id=draft_id, comment=f"批准之后修改了“{label.strip()[:120]}”", result=f"{_shown(before)} → {_shown(value)}"))
        for a in d.answers:
            if a["id"] == qid:
                # an answer the site held becomes the applicant's own: from here on it is filled like any other
                a = {**a, "value": value, "basis": "edited by user", "confidence": "high", "source": "profile", "sensitive_confirmed": bool(a.get("sensitive")), "held": False}
            new.append(a)
        d.answers = new
        d.unresolved = [u for u in d.unresolved if u["id"] != qid or value in ("", None, [])]
        resolved_all = not d.unresolved and d.application.status == "needs_input"
        if resolved_all:
            d.application.status = "draft_ready"
        # every open question is answered and the form still has steps that were not read: the walk goes on from there
        walk_on = resolved_all and d.review_status == "pending" and needs_walk(d) and bool(db.get_setting("recon.walk"))
        # a form that is read by filling it (Workday) and stopped at a step: with the answers in, it is read again from there
        read_on = (resolved_all and d.review_status == "pending" and d.schema.get("source") == "walk" and bool((d.schema.get("extra") or {}).get("stopped_at"))
                   and bool(db.get_setting("recon.walk")))
        if walk_on or read_on:
            d.application.status = "recon"
        job_id, deadline = d.application.job_id, d.application.job.deadline
        edited = next((dict(a) for a in new if a["id"] == qid), None)
    if corrected and edited is not None and edited.get("type") != "file":
        ans.correct(corrected, edited)
    if resolved_all:  # outside the session: SQLite allows one writer at a time
        notify.close_todos("answer", f"draft:{draft_id}")
    if walk_on:
        from . import tasks

        tasks.enqueue("scout", ref=f"draft:{draft_id}", payload={"draft_id": draft_id}, priority=20)
    shown = _shown(value)
    note = save_rule.strip()
    if remember or note:
        # a rule is only usable later if it says what was asked; a bare "No" means nothing on the next form
        rule = f'Form question "{label.strip()[:200]}": answer "{shown[:300]}".' + (f" Note: {note}" if note and note.lower() != shown.lower() else "")
        knowledge.append_rule(rule, source="user", section="Standard answers")
    if read_on:
        from . import tasks

        tasks.enqueue("recon", ref=f"job:{job_id}", payload={"job_id": job_id, "read_on": draft_id}, priority=tasks.deadline_priority(deadline))


def _shown(value: Any) -> str:
    """An answer as words: a list joined, a tick box as what is done with it."""
    if isinstance(value, list):
        return "; ".join(map(str, value))
    if isinstance(value, bool):
        return "Yes (tick the box)" if value else "No (leave the box unticked)"
    return "" if value is None else str(value)


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
