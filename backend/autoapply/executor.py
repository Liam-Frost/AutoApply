"""Deterministic execution of an approved draft (plan section 6.5).

sign in -> duplicate check -> per page: structure check, fill, next -> read back
and compare with the draft -> submit -> keep evidence. Any mismatch stops the
run before Submit.

No LLM calls on the normal path. The fallback chain on every page (section 7.5):

1. the driver fills the page;
2. the program asks the form itself what is wrong (``ats.audit``: fields marked invalid, error messages, required
   fields still empty) and reads the values back against the draft;
3. whatever is left goes to the agent (``repair``), which finishes the page with the L0 tools, filling fields the
   draft did not know about from the applicant's profile only;
4. the audit and the read-back run again: the agent's word is not the evidence;
5. what is still open goes to the user in a visible window, listed by name. A run the agent touched is never
   submitted automatically.

What the agent found out is kept (site notes, the draft's own schema and answers), so the driver does it alone next time.
Forms mapped by the agent (no driver) run through ``GenericDriver`` and are always submitted by the user.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import logging
from pathlib import Path
from typing import Any

from . import answers as ans, messages
from . import auth, browser, config, db, fixtures, llm, notify, repair
from .ats import audit, registry
from .ats.base import AlreadyApplied, DriverError, FormSchema, JobRef, NeedsHuman, Question, blocking_drift, diff_schemas, norm_question, sensitivity, values_equal
from .drafts import _stat
from .models import Application, Draft, Run, now

log = logging.getLogger("autoapply.executor")


class Drifted(Exception):
    def __init__(self, page: int, diff: dict[str, Any]) -> None:
        super().__init__(f"form changed on page {page + 1}")
        self.page, self.diff = page, diff


class VerifyFailed(Exception):
    def __init__(self, mismatches: list[dict[str, Any]]) -> None:
        super().__init__(f"{len(mismatches)} value(s) on the form differ from the draft")
        self.mismatches = mismatches


def policy_for(ats: str) -> str:
    per = db.get_setting("policy.per_ats") or {}
    return per.get(ats) or str(db.get_setting("policy.default"))


def submit_mode(ats: str, company: str, answers: list[dict[str, Any]], *, has_driver: bool = True) -> dict[str, Any]:
    """How an approved draft gets submitted. An approved draft is submitted automatically unless the user
    asked to click Submit for this ATS or company, or something about the run is not well established.
    Returns {"mode": "auto" | "manual", "reasons": [...]} (reasons are shown to the user)."""
    reasons: list[str] = []
    if policy_for(ats) == "manual":
        reasons.append(f"你把 {ats} 设为人工提交" if (db.get_setting("policy.per_ats") or {}).get(ats) == "manual" else "默认提交方式是人工提交")
    hit = next((c for c in (db.get_setting("policy.manual_companies") or []) if c and c.strip().lower() in (company or "").lower()), None)
    if hit:
        reasons.append(f"你把 {hit} 设为人工提交")
    if not has_driver:
        reasons.append("这个 ATS 还没有专用驱动")
    level = str(db.get_setting("policy.manual_confidence") or "low")
    bar = {"none": set(), "low": {"low"}, "medium": {"low", "medium"}}.get(level, {"low"})
    shaky = [a["label"] for a in answers if a.get("value") not in ("", None, []) and a.get("confidence") in bar and a.get("type") != "file"]
    if shaky:
        reasons.append(f"有 {len(shaky)} 项答案把握不高（{'；'.join(x[:30] for x in shaky[:3])}{'…' if len(shaky) > 3 else ''}）")
    extra = [a["label"] for a in answers if a.get("source") == "agent_added" and a.get("value") not in ("", None, [])]
    if extra:
        reasons.append(f"有 {len(extra)} 项是填表时 AI 按你的资料补填的，你还没有看过（{'；'.join(x[:30] for x in extra[:3])}{'…' if len(extra) > 3 else ''}）")
    return {"mode": "manual" if reasons else "auto", "reasons": reasons}


DONE_RE = re.compile(r"thank(s| you) for (applying|your (application|interest|submission))|thank you|application (has been |was |is )?(received|submitted|sent|complete)|successfully (submitted|applied)|we(.ve| have) received|submission (received|complete)", re.I)
DONE_URL = re.compile(r"/(confirmation|thank[-_]?you|thanks|success|submitted|applied)(?=[/?#]|$)", re.I)


class NeedsVisibleRun(Exception):
    """The run turned out to need the user's eyes (the agent had to step in); repeat it in a visible window."""


def _expected(a: dict[str, Any]) -> Any:
    return Path(a["value"]).name if a["type"] == "file" else a["value"]


def verify(schema: FormSchema, draft_answers: list[dict[str, Any]], back: dict[str, Any]) -> list[dict[str, Any]]:
    bad = []
    for a in draft_answers:
        if a["value"] in ("", None, []) or a["id"] not in back:
            continue
        if not values_equal(_expected(a), back[a["id"]]):
            bad.append({"id": a["id"], "label": a["label"], "expected": _expected(a), "actual": back[a["id"]]})
    return bad


def execute(application_id: int, draft_id: int, *, task_id: int | None = None, force_manual: str = "") -> dict[str, Any]:
    with db.session() as s:
        d = s.get(Draft, draft_id)
        app = s.get(Application, application_id)
        if d is None or app is None or d.application_id != application_id:
            raise KeyError("draft/application mismatch")
        if d.review_status != "approved":
            raise PermissionError("draft is not approved")  # guard rail 4
        if app.status in ("submitted", "confirmed"):
            return {"status": app.status, "note": "already submitted"}  # idempotent
        raw = dict(d.schema)
        ref_d = raw.pop("_ref")
        schema = FormSchema.from_dict(raw)
        draft_answers = list(d.answers)
        job = app.job
        job_id = job.id
        title = f"{job.company} · {job.title}"
        app.status = "executing"
    ref = JobRef(**ref_d)
    driver = registry.get(ref.ats)
    mode = submit_mode(ref.ats, title.split(" · ")[0], draft_answers, has_driver=driver is not None)
    if force_manual:
        mode = {"mode": "manual", "reasons": [force_manual]}
    policy = "manual" if mode["mode"] == "manual" else "approve_then_submit"
    generic = driver is None
    if generic:
        if schema.source != "agent":
            raise DriverError(f"no driver for {ref.ats}")
        from .ats.generic_driver import GenericDriver

        driver = GenericDriver(schema)
        policy = "manual"  # guard rail: driverless forms are never submitted automatically
    fill = ans.to_fill_map(draft_answers)
    fill["_phone_country"] = "Canada"
    per_page = bool(getattr(driver, "verify_per_page", False))
    page_of = {a["id"]: int(a.get("page") or 0) for a in draft_answers}
    run_dir = config.RUNS / f"exec_app_{application_id}_d{draft_id}"
    steps: list[dict[str, Any]] = []
    step = lambda op, **kw: steps.append({"op": op, "at": now().isoformat(), **kw})  # noqa: E731
    notify.send("task_started", messages.execute_started(title, ats=ref.ats, policy=policy, pages=len(schema.pages or []), reasons=mode["reasons"]), ref=f"application:{application_id}")
    outcome: dict[str, Any] = {}
    ok = False
    leftovers: list[dict[str, str]] = []   # what is left for the user in a visible, user-submitted run
    mapped: list[dict[str, str]] = []      # approved answers entered in the form's own wording
    added: list[dict[str, Any]] = []       # fields the draft did not cover, filled by the agent from the profile
    skip_verify: set[str] = set()
    absent_ids: set[str] = set()
    approved_values = {a["id"]: a["value"] for a in draft_answers}

    def _left(kind: str, label: str, expected: str = "", why: str = "") -> None:
        if not any(x["label"] == label for x in leftovers):
            leftovers.append({"label": label, "expected": expected, "kind": kind, "why": why})

    def _handed(issue: dict[str, Any]) -> bool:
        """Is this finding of the form already on the user's list?"""
        label = norm_question(issue.get("label") or "")
        return bool(label) and any(label in norm_question(x["label"]) or norm_question(x["label"]) in label for x in leftovers if x["label"])

    def _checked(run_verify: Any) -> None:
        """Read-back differences never go out automatically: in a run the user submits they are listed for the user,
        otherwise the run is repeated in a visible window."""
        try:
            run_verify()
        except VerifyFailed as e:
            if policy != "manual":
                raise NeedsVisibleRun(f"表单上有 {len(e.mismatches)} 项和草案不一致，自动修正后仍然不对，改为在可见窗口里交给你处理") from e
            from .ats.generic_driver import value_visible

            by_id = {q.id: q for q in schema.questions}
            seen_ok, unsure, wrong = [], [], []
            for m in e.mismatches:
                q = by_id.get(m["id"])
                if m["actual"] in ("", None, []):   # the control gives nothing back: look at what the page shows instead
                    (seen_ok if q is not None and value_visible(page, q, m["expected"]) else unsure).append(m)
                else:
                    wrong.append(m)
            step("unverified", shown_on_page=len(seen_ok), unsure=[m["label"] for m in unsure][:20], different=[m["label"] for m in wrong][:20])
            for m in unsure:
                _left("check", m["label"], str(m["expected"])[:120], "这个控件的值程序读不回来，没法确认是否填上了，请看一眼")
            for m in wrong:
                _left("fix", m["label"], str(m["expected"])[:120], f"页面上现在是：{str(m['actual'])[:80]}")

    def _issues(i: int) -> list[dict[str, Any]]:
        """What the form itself reports on the open page, minus 'still empty' findings the driver's read-back contradicts
        (a custom control whose value only the driver knows how to read)."""
        found = audit.page_issues(page)
        if not found:
            return []
        try:
            back = driver.read_back(page, schema, i)
        except Exception:  # noqa: BLE001
            back = {}
        known = {norm_question(q.label): q for q in schema.questions if q.page == i}
        out = []
        for it in found:
            q = known.get(norm_question(it["label"])) if it.get("label") else None
            if it["kind"] == "empty_required" and q is not None and (q.type == "file" or back.get(q.id) not in ("", None, [], False)):
                continue
            out.append(it)
        return out

    def _apply(rep: dict[str, Any], i: int) -> None:
        """Take the agent's report into the state of this run."""
        lab = rep.get("labels") or {}
        for m in rep.get("mapped") or []:  # the form's own wording for an approved answer: from here on that is the value
            mapped.append({"label": lab.get(m["id"], m["id"]), "approved": m["approved"], "chosen": m["chosen"]})
            fill[m["id"]] = m["chosen"]
            for a in draft_answers:
                if a["id"] == m["id"]:
                    a["value"] = m["chosen"]
        for qid in rep.get("absent") or []:  # not on the form for this applicant's choices: nothing to fill, nothing to verify
            fill.pop(qid, None)
            absent_ids.add(qid)
            for a in draft_answers:
                if a["id"] == qid:
                    a["value"] = ""
        for a in rep.get("added") or []:
            if not any(x["label"] == a["label"] for x in added):
                added.append({"label": a["label"], "value": a["value"], "basis": a.get("basis") or "", "type": a.get("type") or "text", "page": i})
        for n in rep.get("needs_user") or []:
            _left("fix", n["label"], "", n.get("why") or "资料里没有这一项，需要你来填")
        for qid in rep.get("unfixed") or []:
            _left("fix", lab.get(qid, qid), str(fill.get(qid, ""))[:120], "表单上的选项和草案里的答案对不上，或控件没法自动操作")
        skip_verify.update(rep.get("unfixed") or [])

    def _takeover(i: int, problem: dict[str, Any], only: list[str] | None, issues: list[dict[str, Any]]) -> dict[str, Any] | None:
        _repair_note.clear()
        rep = _repair(page, schema, i, fill, problem, run_dir, only, title, application_id, issues=issues)
        if rep is None:
            step("repair_skipped", why=_repair_note.get("why") or "repair is switched off")
            return None
        step("repair", page=i, fixed=len(rep["fixed"]), unfixed=len(rep["unfixed"]), mapped=len(rep.get("mapped") or []), added=len(rep.get("added") or []),
             needs_user=len(rep.get("needs_user") or []), form_still_reports=audit.texts(rep.get("left") or [])[:10], cause=rep.get("cause", "")[:200])
        _apply(rep, i)
        return rep

    def _after_verify_repair(rep: dict[str, Any], i: int) -> None:
        _apply(rep, i)

    try:
        headless = policy != "manual"
        with browser.open_page(ref.tenant_key if (driver.requires_login or generic) else None, headless=headless) as page:
            st = auth.ensure_session(page, driver, ref)
            step("ensure_session", result=st)
            if driver.requires_login and driver.already_applied(page, ref):
                raise AlreadyApplied()
            driver.open_application(page, ref)
            step("open", url=page.url)
            if generic:
                from . import generic as gen

                if not gen.form_present(page, schema):
                    # the form is not there: almost always the saved sign-in has run out since the draft was prepared
                    run_dir.mkdir(parents=True, exist_ok=True)
                    got = gen.sign_in(page, ref, title, schema.url or ref.url, run_dir)
                    step("sign_in", ok=got["ok"], notes=got["notes"][:200])
                    if not got["ok"]:
                        raise NeedsHuman(f"{ref.ats}: login required. The saved sign-in for this site has expired and signing in again did not reach the form. {got['notes']}"[:300],
                                         kind="login", url=page.url)
                    # The agent reports it is at the form. Stay where it left the page; go back to the recorded address only if the
                    # form is not there. If the mapped controls still cannot be found, that is not a login problem: carry on, and the
                    # fill -> form's verdict -> take-over chain below deals with a form whose controls have moved.
                    if not gen.form_present(page, schema, wait_s=4):
                        driver.open_application(page, ref)
                        step("reopen", form_found=gen.form_present(page, schema, wait_s=6))
            pages = schema.pages or ["Application"]
            open_issues: list[dict[str, Any]] = []
            for i in range(len(pages)):
                rounds = 0  # agent take-overs on this page (at most two: one after the driver, one after the checks)
                live = FormSchema(ats=schema.ats, questions=[Question(**{**q.__dict__, "page": i}) for q in driver.live_questions(page, i)])
                diff = diff_schemas(_page_view(schema, i), live, page=i)
                # Controls the API schema does not list (phone country, etc.) are not drift
                # unless they are required AND empty after filling; re-check after fill.
                # 1. the driver
                fill_error: DriverError | None = None
                try:
                    driver.fill_page(page, schema, i, fill)
                except DriverError as e:
                    browser.snapshot(page, run_dir, f"fill_failed_page_{i + 1}")
                    fill_error = e
                # 2. the form's own verdict, 3. the agent finishes what is left
                issues = _issues(i)
                if issues:
                    step("form_reports", page=i, after="driver", issues=audit.texts(issues)[:12])
                if fill_error is not None or issues:
                    failed = [f for f in getattr(fill_error, "failures", [])] if fill_error is not None else []
                    only = [f["id"] for f in failed] if (failed or fill_error is None) else None
                    problem = fill_error.to_dict() if fill_error is not None else {"message": "the driver filled the page, but the form itself still reports problems"}
                    rep = _takeover(i, problem, only, issues)
                    rounds += 1
                    if rep is None and fill_error is not None:
                        if policy == "manual":  # the user is about to look at this window anyway: leave these fields to them
                            for f in failed:
                                _left("fix", f["label"], str(fill.get(f["id"], ""))[:120], "没能自动填上")
                            if not failed:
                                _left("fix", str(fill_error)[:120], "", "驱动在这一页出错，AI 也没能接手")
                        elif _repair_note.get("why"):
                            raise DriverError(f"{fill_error}; the AI take-over could not start: {_repair_note['why']}", page=i,
                                              question=getattr(fill_error, "question", ""), seen=getattr(fill_error, "seen", "")) from fill_error
                        else:
                            raise fill_error
                    elif rep is not None and policy != "manual" and (rep["unfixed"] or rep.get("needs_user")):
                        raise NeedsVisibleRun("有几项驱动和 AI 都没能填上，改为在可见窗口里交给你处理")
                step("fill_page", page=i, filled=sum(1 for q in schema.questions if q.page == i and q.id in fill))
                if blocking_drift(diff) and _unfilled_required(driver, page, schema, i, diff):
                    browser.snapshot(page, run_dir, f"drift_page_{i + 1}")
                    raise Drifted(i, diff)
                browser.snapshot(page, run_dir, f"page_{i + 1}_filled")
                if per_page:
                    _checked(lambda i=i: _verify(driver, page, schema, [a for a in draft_answers if a["id"] not in skip_verify], fill, i, page_of, run_dir, step, title, application_id,
                                                 after_repair=lambda rep, i=i: _after_verify_repair(rep, i)))
                # 4. the form has the last word on this page
                open_issues = _issues(i)
                fresh = [it for it in open_issues if not _handed(it)]  # what has already been handed to the user by name needs no second attempt
                if fresh and rounds < 2 and repair.enabled():
                    step("form_reports", page=i, after="checks", issues=audit.texts(fresh)[:12])
                    if _takeover(i, {"message": "the page was filled and compared with the draft, but the form itself still reports problems"}, [], fresh) is not None:
                        rounds += 1
                        open_issues = _issues(i)
                _keep_fixture(schema, page, i)
                if i < len(pages) - 1:
                    moved = driver.next_page(page)
                    if not moved and rounds < 2 and repair.enabled():
                        # the form refused to go on: now it says why. One more round for the agent, then one more try.
                        blockers = _issues(i)
                        step("form_reports", page=i, after="next", issues=audit.texts(blockers)[:12])
                        if blockers and _takeover(i, {"message": "the form does not advance to the next page"}, [], blockers) is not None:
                            moved = driver.next_page(page)
                    if not moved:
                        raise DriverError("could not advance to the next page", page=i, seen="; ".join(_errors(driver, page) or audit.texts(_issues(i)))[:400])
                    step("next", page=i)
            if not per_page:
                _checked(lambda: _verify(driver, page, schema, [a for a in draft_answers if a["id"] not in skip_verify], fill, None, page_of, run_dir, step, title, application_id,
                                         after_repair=lambda rep: _after_verify_repair(rep, max(0, len(pages) - 1))))
            touched = any(st["op"] == "repair" for st in steps)
            if policy != "manual" and touched:
                raise NeedsVisibleRun("驱动没能独自填完，AI 接手处理过，这次请你过目后再提交")
            if policy == "manual":
                # 5. whatever the form still complains about goes to the user by the form's own words: never "filled" while it says otherwise
                for it in open_issues:
                    if not _handed(it):
                        _left("form", audit.describe(it), "", "表单自己的提示")
                if open_issues:
                    step("form_reports", page=len(pages) - 1, after="everything", issues=audit.texts(open_issues)[:12])
                    browser.snapshot(page, run_dir, "handed_over")
                if leftovers or mapped or added:
                    step("handed_over", left=[x["label"] for x in leftovers][:20], mapped=[m["label"] for m in mapped][:20], added=[a["label"] for a in added][:20])
                outcome = _wait_for_manual_submit(driver, page, title, application_id, draft_id, leftovers=leftovers, mapped=mapped, added=added)
            else:
                clicked_at = datetime.now(timezone.utc)
                driver.submit(page)
                step("submit")
                if _email_code_step(driver, page, run_dir, clicked_at):
                    step("email_code")
                conf = driver.confirmation(page)
                shots = browser.snapshot(page, run_dir, "confirmation")
                if conf is None:
                    errs = _errors(driver, page)
                    raise DriverError("no confirmation after submit", seen="; ".join(errs)[:500] or page.url)
                outcome = {"status": "submitted", "evidence": {**conf, **shots}}
            if driver.requires_login:
                browser.save_state(ref.tenant_key, page.context)
        ok = outcome.get("status") == "submitted"
    except AlreadyApplied:
        outcome = {"status": "submitted", "evidence": {"text": "The site shows this job as already applied."}, "note": "already applied"}
        ok = True
    except NeedsHuman as e:
        outcome = {"status": "needs_human", "error": e.reason}
        if e.kind == "captcha":
            notify.add_todo("captcha", title, body=e.reason, ref=f"application:{application_id}", payload={"url": e.url})
        elif generic:  # say what is needed, with the same sign-in card as everywhere else; the approved draft runs again afterwards
            notify.add_todo("takeover", title, body=e.reason, ref=f"account:{ref.tenant_key}",
                            payload={"tenant_key": ref.tenant_key, "ats": ref.ats, "url": e.url or ref.url, "job_url": ref.url, "draft_id": draft_id, "can_register": auth.may_register(ref)[0]})
    except NeedsVisibleRun as e:
        outcome = {"status": "approved", "note": str(e)}
        from . import tasks

        tasks.enqueue("execute", ref=f"application:{application_id}:manual", payload={"draft_id": draft_id, "force_manual": str(e)}, priority=5)
    except Drifted as e:
        outcome = {"status": "drifted", "error": str(e), "diff": e.diff, "page": e.page}
        # Re-read the form and build a delta draft: answers already approved are carried over,
        # only the new or changed questions need a decision.
        from . import tasks

        tasks.enqueue("recon", ref=f"job:{job_id}", payload={"job_id": job_id, "after_drift": draft_id})
        notify.send("status_update", messages.drifted(title, _drift_text(e.diff).splitlines()), ref=f"application:{application_id}")
    except VerifyFailed as e:
        outcome = {"status": "failed", "error": str(e), "mismatches": e.mismatches}
    except DriverError as e:
        outcome = {"status": "failed", "error": str(e), "driver_error": e.to_dict()}
    except Exception as e:  # noqa: BLE001
        log.exception("execution crashed")
        outcome = {"status": "failed", "error": f"{type(e).__name__}: {e}"}

    with db.session() as s:
        app = s.get(Application, application_id)
        app.status = outcome["status"]
        was_auto = bool(app.auto_approved)
        app.last_event = outcome.get("error") or outcome.get("note") or ""
        if outcome["status"] == "submitted":
            app.submitted_at = now()
            app.evidence = outcome.get("evidence", {})
            app.detail = f"submitted {now().date().isoformat()} via {ref.ats}" + (" (auto-approved)" if app.auto_approved else "")
        s.add(Run(task_id=task_id, kind="execute", ref=f"application:{application_id}", ats=ref.ats, ok=int(ok), steps=steps, dir=str(run_dir)))
        if mapped or added:
            _keep_learned(s.get(Draft, draft_id), schema, draft_answers, approved_values, absent_ids, added, generic=generic)
    if outcome["status"] == "submitted":
        for kind in ("failed", "submit"):  # earlier attempts at this application are settled now
            notify.close_todos(kind, f"application:{application_id}")
        from . import tasks

        for m in db.get_setting("mail.confirm_check_minutes") or []:  # the confirmation e-mail turns "submitted" into "confirmed"
            tasks.enqueue_later("mail", ref=f"confirm:{application_id}", minutes=float(m), priority=40)
        _stat(ref.ats, "exec_ok", streak=True)
        notify.send("task_result", messages.submitted(title, evidence=outcome.get("evidence", {}).get("text") or "", auto=was_auto, note=outcome.get("note", "")), ref=f"application:{application_id}")
    elif outcome["status"] == "failed":
        _stat(ref.ats, "exec_fail", reset_streak=True)
        notify.add_todo("failed", f"{title}：执行失败", body=outcome.get("error", "")[:500], ref=f"application:{application_id}", payload={"draft_id": draft_id, **{k: v for k, v in outcome.items() if k in ("mismatches", "driver_error")}},
                        push=not db.get_setting("notify.task_result"))
        notify.send("task_result", messages.failed(title, error=outcome.get("error", "")), ref=f"application:{application_id}")
    if outcome.get("last_seen"):
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "last_seen.txt").write_text(f"{outcome['last_seen'].get('url', '')}\n\n{outcome['last_seen'].get('text', '')}", encoding="utf-8")
        except OSError:
            pass
    if outcome["status"] == "ready_to_submit" and outcome.get("error"):
        # Filled (and possibly clicked) but no confirmation: one card that says so and offers a re-run.
        # (A run that stopped for a login or a CAPTCHA already has its own card saying what is needed.)
        notify.close_todos("submit", f"application:{application_id}")
        notify.add_todo("failed", f"{title}：没有确认提交成功", body=outcome["error"][:500], ref=f"application:{application_id}",
                        payload={"draft_id": draft_id, "application_id": application_id, "maybe_submitted": outcome["status"] == "ready_to_submit"},
                        push=not db.get_setting("notify.task_result"))
        notify.send("task_result", messages.failed(title, error=outcome["error"]), ref=f"application:{application_id}")
    return outcome


def _keep_learned(d: Any, schema: FormSchema, draft_answers: list[dict[str, Any]], approved_values: dict[str, Any], absent_ids: set[str],
                  added: list[dict[str, Any]], *, generic: bool) -> None:
    """Write back into the draft what the take-over established, so the next run of it needs no agent:
    the form's own wording for approved answers, and the questions the first reading of the form did not see.
    For explored forms the new questions also join the schema (found by their label), which is what the driver replays."""
    if d is None:
        return
    rows = []
    for a in draft_answers:
        row = dict(a)
        if row["id"] in absent_ids:  # missing on the page this time only: the approved answer stays
            row["value"] = approved_values.get(row["id"], row["value"])
        rows.append(row)
    sch = dict(d.schema)
    questions = [dict(q) for q in sch.get("questions", [])]
    for a in added:
        qid = f"@label:{a['label']}"
        row = {"id": qid, "label": a["label"], "type": a["type"] if a["type"] in ("text", "textarea", "select", "radio", "checkbox", "date") else "text", "options": [],
               "required": True, "page": a["page"], "value": a["value"], "basis": ("填表时 AI 按你的资料补填：" + a["basis"])[:300], "confidence": "medium",
               "source": "agent_added", "sensitive": sensitivity(a["label"]), "sensitive_confirmed": False}
        rows = [r for r in rows if r["id"] != qid] + [row]
        if generic and not any(q["id"] == qid for q in questions):
            questions.append(Question(id=qid, label=a["label"], type=row["type"], required=True, page=a["page"], locator={"selector": qid}).__dict__)
        try:
            ans.cache_put(schema.ats, Question(id=qid, label=a["label"], type=row["type"]), a["value"], row["basis"], confirmed=False)
        except Exception:  # noqa: BLE001
            log.debug("answer not cached", exc_info=True)
    sch["questions"] = questions
    d.answers = rows
    d.schema = sch


_repair_note: dict[str, str] = {}   # why the last take-over did not happen (shown with the failure)


def _repair(page: Any, schema: FormSchema, i: int, fill: dict[str, Any], problem: dict[str, Any], run_dir: Path,
            only_ids: list[str] | None, title: str, application_id: int, *, issues: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Agent takeover of one page. None when repair is off or no model is available (the caller re-raises)."""
    if not repair.enabled():
        return None
    try:
        return repair.fix_page(page, schema, i, fill, problem, run_dir, only_ids=only_ids, issues=issues, title=title, ref=f"application:{application_id}")
    except llm.LLMError as e:
        log.warning("repair unavailable: %s", e)
        _repair_note["why"] = str(e)[:300]
        return None


def _verify(driver: Any, page: Any, schema: FormSchema, draft_answers: list[dict[str, Any]], fill: dict[str, Any], i: int | None,
            page_of: dict[str, int], run_dir: Path, step: Any, title: str, application_id: int, *, after_repair: Any = None) -> None:
    """Read back (page ``i``, or the whole form when None) and compare with the draft.
    One repair attempt on the page that is currently open; any remaining mismatch stops the run."""
    scope = [a for a in draft_answers if i is None or page_of.get(a["id"], 0) == i]
    back = driver.read_back(page, schema, i) if i is not None else driver.read_back(page, schema)
    bad = _really_different(page, schema, verify(schema, scope, back))
    current = i if i is not None else max(0, len(schema.pages or ["x"]) - 1)
    if bad and all(page_of.get(b["id"], 0) == current for b in bad):
        rep = _repair(page, schema, current, fill, {"message": "values on the form differ from the approved draft", "mismatches": bad},
                      run_dir, [b["id"] for b in bad], title, application_id)
        if rep is not None:
            step("repair", page=current, fixed=len(rep["fixed"]), unfixed=len(rep["unfixed"]), cause=rep.get("cause", "")[:200])
            if after_repair is not None:
                after_repair(rep)
                scope = [a for a in scope if a["id"] not in set(rep.get("unfixed") or [])]
            back = driver.read_back(page, schema, i) if i is not None else driver.read_back(page, schema)
            bad = _really_different(page, schema, verify(schema, scope, back))
    wanted = [a for a in scope if a["value"] not in ("", None, [])]
    step("read_back", page=i, checked=sum(1 for a in wanted if a["id"] in back), unverified=[a["label"] for a in wanted if a["id"] not in back][:20], mismatches=len(bad))
    if bad:
        browser.snapshot(page, run_dir, "verify_failed")
        raise VerifyFailed(bad)


def _really_different(page: Any, schema: FormSchema, bad: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """On explored forms (always submitted by the user) a control that reads back empty is not yet a difference: custom
    widgets show the choice as a chip or put the uploaded file's name elsewhere. Look at what the page shows before
    calling the agent for it. Coded drivers know how to read their own controls and are taken at their word."""
    if schema.source != "agent" or not bad:
        return bad
    from .ats.generic_driver import value_visible

    by_id = {q.id: q for q in schema.questions}
    return [b for b in bad if not (b["actual"] in ("", None, []) and b["id"] in by_id and value_visible(page, by_id[b["id"]], b["expected"]))]


def _keep_fixture(schema: FormSchema, page: Any, i: int) -> None:
    """A page the driver filled and verified is a known-good regression fixture."""
    try:
        fixtures.save(schema, page, i, reason="exec")
    except Exception:  # noqa: BLE001
        log.debug("fixture not saved", exc_info=True)


def _page_view(schema: FormSchema, i: int) -> FormSchema:
    return FormSchema(ats=schema.ats, questions=[q for q in schema.questions if q.page == i])


def _unfilled_required(driver: Any, page: Any, schema: FormSchema, i: int, diff: dict[str, Any]) -> bool:
    """Drift only blocks when a required control we did not plan for is still empty,
    or a planned question changed type/options."""
    if diff["changed"]:
        return True
    from .ats import widgets as w

    live = {c["label"].rstrip("*").strip().lower(): c for c in w.describe_inputs(page)}
    for q in diff["added"]:
        if not q.get("required"):
            continue
        c = live.get(q["label"].lower())
        if c is None:
            return True
        val = c["value"]
        if val in ("", None) and c.get("role") == "combobox" and c.get("id"):
            from .ats import widgets as _w

            val = _w.react_select_value(page.locator(f"[id='{c['id']}']").first)
        if val in ("", False, None, "Select One", "Select..."):
            return True
    return False


def _errors(driver: Any, page: Any) -> list[str]:
    return driver.form_errors(page) if hasattr(driver, "form_errors") else []


def _drift_text(diff: dict[str, Any]) -> str:
    parts = [f"新增必填：{q['label']}" for q in diff["added"] if q.get("required")]
    parts += [f"有变化：{c['after']['label']}" for c in diff["changed"]]
    return "\n".join(parts)[:800]


def _wait_for_manual_submit(driver: Any, page: Any, title: str, application_id: int, draft_id: int | None = None, *,
                            leftovers: list[dict[str, str]] | None = None, mapped: list[dict[str, str]] | None = None,
                            added: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Manual policy: the form is filled in a visible window; the user clicks Submit."""
    payload: dict[str, Any] = {"draft_id": draft_id} if draft_id else {}
    if leftovers:
        payload["open_items"] = leftovers[:30]
    if mapped:
        payload["mapped"] = mapped[:30]
    if added:
        payload["added"] = [{"label": a["label"], "value": str(a["value"])[:120], "basis": a.get("basis", "")[:200]} for a in added[:30]]
    todo_n = sum(1 for m in leftovers or [] if m.get("kind") in ("fix", "form"))
    look_n = sum(1 for m in leftovers or [] if m.get("kind") == "check")
    if todo_n:
        payload["incomplete"] = True   # the card and the notification must not say "filled"
    parts = [f"还有 {todo_n} 处没填好，需要你在窗口里处理" if todo_n else "", f"{look_n} 项请你看一眼是否填上了" if look_n else "",
             f"{len(added)} 项是 AI 按你的资料补填的" if added else ""]
    notify.close_todos("submit", f"application:{application_id}")  # a fresh card: what is left to do differs from run to run
    notify.add_todo("submit", title, ref=f"application:{application_id}", payload=payload or None, body="；".join(x for x in parts if x))
    code_tried = False
    last: dict[str, str] = {}
    for _ in range(1200):  # up to ~20 minutes
        if page.is_closed():
            break
        # After the user clicks Submit some sites e-mail a security code: read it from the inbox and enter it.
        try:
            wants_code = not code_tried and hasattr(driver, "needs_email_code") and driver.needs_email_code(page)
        except Exception:  # noqa: BLE001
            wants_code = False
        if wants_code:
            code_tried = True
            try:
                _email_code_step(driver, page, None, datetime.now(timezone.utc) - timedelta(minutes=2))
            except Exception as e:  # noqa: BLE001 - the user can still type it
                log.info("could not enter the e-mailed code automatically: %s", e)
        try:
            conf = driver.confirmation(page) if _looks_submitted(page) else None
        except Exception:  # noqa: BLE001
            conf = None
        if conf:
            notify.close_todos("submit", f"application:{application_id}")
            return {"status": "submitted", "evidence": conf}
        try:  # remember what the window last showed: the user may close it right after the confirmation appears
            last = {"url": page.url, "text": page.evaluate("() => document.body.innerText.slice(0, 1500)")}
            page.wait_for_timeout(1000)
        except Exception:  # noqa: BLE001 - window closed by the user
            break
    if last and (DONE_RE.search(last["text"]) or DONE_URL.search(last["url"])):
        notify.close_todos("submit", f"application:{application_id}")
        return {"status": "submitted", "evidence": last}
    return {"status": "ready_to_submit", "error": "窗口已关闭或超时，没有看到确认页；是否已提交不确定，请以确认邮件为准", "last_seen": last}


def _email_code_step(driver: Any, page: Any, run_dir: Path | None, since: datetime) -> bool:
    """Some sites e-mail a security code after Submit. Read it from the inbox (only mail newer than the
    click) and enter it. Returns False when the site did not ask. The code is never logged or stored."""
    if not hasattr(driver, "needs_email_code"):
        return False
    for _ in range(8):  # the code form appears a moment after the click
        if driver.needs_email_code(page) or _looks_submitted(page):
            break
        page.wait_for_timeout(1000)
    if not driver.needs_email_code(page):
        return False
    if run_dir is not None:
        browser.snapshot(page, run_dir, "email_code_step")
    from . import mail

    for attempt in (1, 2):
        code = mail.wait_for_verification(sender_hint=getattr(driver, "ats", ""), timeout=180, since=since - timedelta(seconds=20))
        if code is None:
            raise NeedsHuman("表单要求输入邮件验证码，但没有等到这封邮件", kind="login", url=page.url)
        driver.enter_email_code(page, code)
        page.wait_for_timeout(4000)
        err = driver.email_code_error(page) if hasattr(driver, "email_code_error") else ""
        if not err and not driver.needs_email_code(page):
            return True
        if _looks_submitted(page):
            return True
        if run_dir is not None:
            browser.snapshot(page, run_dir, f"email_code_rejected_{attempt}")
        since = datetime.now(timezone.utc)  # a rejected code usually triggers a fresh one
    raise NeedsHuman(f"网站没有接受邮件验证码（{err or '验证码页面仍在'}）", kind="login", url=page.url)


def _looks_submitted(page: Any) -> bool:
    try:
        return bool(DONE_RE.search(page.evaluate("() => document.body.innerText.slice(0, 6000)")) or DONE_URL.search(page.url))
    except Exception:  # noqa: BLE001
        return False
