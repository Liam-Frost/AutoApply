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

A form with several steps that the AI explored (a wizard) is not walked page 1, page 2, page 3 of the draft: such forms
show their steps in their own order, skip the ones they already have, insert optional ones and resume where an earlier
attempt stopped. ``_walk_steps`` goes through the steps that are really there, fills on each the approved answers whose
controls are showing, lets the AI find the way forward when the button is not one of the usual ones, and stops at the
review step, where the user submits.

What the agent found out is kept (site notes, the draft's own schema and answers), so the driver does it alone next time.
Forms mapped by the agent (no driver) run through ``GenericDriver`` and are always submitted by the user.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

import logging
from pathlib import Path
from typing import Any

from . import answers as ans, messages
from . import auth, browser, config, db, fixtures, knowledge, learned, llm, metering, notify, repair, secrets, timing
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
    level = str(db.get_setting("policy.manual_confidence") or "low")
    bar = {"none": set(), "low": {"low"}, "medium": {"low", "medium"}}.get(level, {"low"})
    shaky = [a["label"] for a in answers if a.get("value") not in ("", None, []) and a.get("confidence") in bar and a.get("type") != "file"]
    if shaky:
        reasons.append(f"有 {len(shaky)} 项答案把握不高（{'；'.join(x[:30] for x in shaky[:3])}{'…' if len(shaky) > 3 else ''}）")
    # (Answers the agent added from the profile while reading the form are in the draft the applicant approves: approving
    # the draft is having seen them. What comes up after the approval is dealt with in the run - see needs_you there.)
    return {"mode": "manual" if reasons else "auto", "reasons": reasons}


DONE_RE = re.compile(r"thank(s| you) for (applying|your (application|interest|submission))|thank you|application (has been |was |is )?(received|submitted|sent|complete)|successfully (submitted|applied)|we(.ve| have) received|submission (received|complete)", re.I)
DONE_URL = re.compile(r"/(confirmation|thank[-_]?you|thanks|success|submitted|applied)(?=[/?#]|$)|[?&]result=(success|submitted|duplicate)\b", re.I)
# the site says an application for this posting exists already: there is no form to fill, and nothing to send again
ALREADY_RE = re.compile(r"you(.ve| have) already (applied|submitted)|already (applied|submitted an application) (for|to) this|"
                        r"you(.ve| have) previously applied (for|to) this|application (has )?already (been )?(received|submitted)|你已(经)?申请过", re.I)


def _seen(page: Any, limit: int = 6000) -> dict[str, str]:
    """What the window shows: its address, its title (many sites say "Thank you for your application" only there) and its text."""
    try:
        got = page.evaluate("(n) => ({ title: document.title || '', text: document.body ? document.body.innerText.slice(0, n) : '' })", limit)
    except Exception:  # noqa: BLE001 - between two pages there is nothing to read
        got = {"title": "", "text": ""}
    try:
        url = page.url
    except Exception:  # noqa: BLE001
        url = ""
    return {"url": url, "title": got["title"], "text": got["text"]}


def _already_applied(page: Any) -> dict[str, str] | None:
    """The page that opened instead of the form says this posting has been applied for already."""
    now_ = _seen(page, 3000)
    m = ALREADY_RE.search(now_["text"]) or ALREADY_RE.search(now_["title"])
    if not m and not re.search(r"[?&]result=duplicate\b", now_["url"], re.I):
        return None
    line = next((ln.strip() for ln in now_["text"].splitlines() if ALREADY_RE.search(ln)), now_["title"])
    return {"url": now_["url"], "text": line[:300], "already_applied": "yes"}


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


def execute(application_id: int, draft_id: int, *, task_id: int | None = None, force_manual: str = "", scout: bool = False) -> dict[str, Any]:
    """Fill the form of an approved draft. With ``scout``: walk the form of a draft that is still pending with its own
    answers, to read the steps that open only once the earlier ones are filled - in a hidden window, up to the review
    page at most, never submitting and never handing a window to the applicant. What the walk finds goes into the draft."""
    with db.session() as s:
        d = s.get(Draft, draft_id)
        app = s.get(Application, application_id)
        if d is None or app is None or d.application_id != application_id:
            raise KeyError("draft/application mismatch")
        if scout and d.review_status != "pending":
            return {"status": "skipped", "note": "the draft is no longer pending"}
        if not scout and d.review_status != "approved":
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
        s.expunge(job)
        if not scout:
            app.status = "executing"
    ref = JobRef(**ref_d)
    driver = registry.get(ref.ats)
    mode = submit_mode(ref.ats, title.split(" · ")[0], draft_answers, has_driver=driver is not None)
    if force_manual:
        mode = {"mode": "manual", "reasons": [force_manual]}
    policy = "manual" if mode["mode"] == "manual" else "approve_then_submit"
    signer = driver if (driver is not None and schema.source == "agent" and getattr(driver, "requires_login", False)) else None
    generic = driver is None or schema.source == "agent"      # a form the agent read is filled the way it was read
    if generic:
        if schema.source != "agent":
            raise DriverError(f"no driver for {ref.ats}")
        from .ats.generic_driver import GenericDriver

        driver = GenericDriver(schema)
        # A form the agent read is submitted the way the applicant decided, like any other: automatically once the draft is
        # approved, unless they keep the last click for this site or company, or the run leaves something that is theirs.
    if scout and not (generic and len(schema.pages or []) > 1):
        return {"status": "skipped", "note": "not an explored form with several steps"}
    fill = ans.to_fill_map(draft_answers)
    fill["_phone_country"] = "Canada"
    per_page = bool(getattr(driver, "verify_per_page", False))
    page_of = {a["id"]: int(a.get("page") or 0) for a in draft_answers}
    run_dir = config.RUNS / f"{'scout' if scout else 'exec'}_app_{application_id}_d{draft_id}"
    steps: list[dict[str, Any]] = []
    timing.begin()
    learned.begin([_site_of(schema), ref.ats])          # what was learned for this site and this system is in force
    last_mark = [time.monotonic()]
    def step(op: str, **kw: Any) -> None:
        steps.append({"op": op, "at": now().isoformat(), **kw})
        metering.stage(op)       # the task remembers how far it got
        # the stretch that ended with this step, as a whole: what lies inside it (fields, tools, requests, loads) is
        # recorded where it happens, and what is left over is the program's own work on that step
        whole = (time.monotonic() - last_mark[0]) * 1000.0
        timing.mark("human" if op in ("wait_user", "manual", "handover") else "driver", f"step:{op}", max(0.0, whole - timing.inside(last_mark[0])), started=last_mark[0],
                    page=kw.get("page"))
        last_mark[0] = time.monotonic()
    if not scout:
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

    def _mismatch_leftovers(mismatches: list[dict[str, Any]]) -> None:
        """Values that still differ from the draft go on the user's list, sorted into "cannot be read back" and "is something else"."""
        from .ats.generic_driver import value_visible

        by_id = {q.id: q for q in schema.questions}
        seen_ok, unsure, wrong = [], [], []
        for m in mismatches:
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

    def _checked(run_verify: Any) -> None:
        """Read-back differences never go out automatically: in a run the user submits they are listed for the user,
        otherwise the run is repeated in a visible window."""
        try:
            run_verify()
        except VerifyFailed as e:
            if policy != "manual":
                raise NeedsVisibleRun(f"表单上有 {len(e.mismatches)} 项和草案不一致，自动修正后仍然不对，改为在可见窗口里交给你处理") from e
            _mismatch_leftovers(e.mismatches)

    def _issues(i: int | None) -> list[dict[str, Any]]:
        """What the form itself reports on the open page, minus 'still empty' findings the driver's read-back contradicts
        (a custom control whose value only the driver knows how to read)."""
        found = audit.page_issues(page)
        if not found and not generic:
            return []
        try:
            back = driver.read_back(page, schema, i) if i is not None else driver.read_back(page, schema)
        except Exception:  # noqa: BLE001
            back = {}
        known = {norm_question(q.label): q for q in schema.questions if i is None or q.page == i}
        out = []
        if generic and not scout:
            # The form offers to create the applicant's account with the application and its password boxes are empty:
            # that is a part of the form still to be done (by the take-over, which has the tool that types the password).
            try:
                boxes = page.locator("input[type=password]:visible")
                empty = [k for k in range(boxes.count()) if not boxes.nth(k).input_value(timeout=2000)]
            except Exception:  # noqa: BLE001
                empty = []
            if empty and (secrets.get_password(ref.tenant_key) or auth.may_register(ref)[0]):
                out.append({"kind": "message", "label": "Account", "selector": "", "value": "",
                            "message": "the form's account section is not filled in: its password boxes are empty"})
        for it in found:
            q = known.get(norm_question(it["label"])) if it.get("label") else None
            if it["kind"] == "empty_required" and q is not None and (q.type == "file" or back.get(q.id) not in ("", None, [], False)):
                continue
            out.append(it)
        return out

    entered_by_agent: set[str] = set()   # approved answers the take-over entered on a step where the driver did not find their control
    adapted: list[dict[str, Any]] = []   # answers rewritten to fit a limit of the form: shown to the user, kept in the draft
    limits: dict[str, int] = {}          # question id -> the most characters the form accepts
    asked: list[dict[str, Any]] = []     # questions the form asks that neither the draft nor the profile answers: they join the draft as open questions
    held: list[dict[str, Any]] = []      # questions the site already holds an answer to (read on a walk): they join the draft as they stand
    located: dict[str, str] = {}         # question id -> where the take-over found its control (the driver fills it alone next time)
    read_now: list[str] = []             # steps read completely on this walk, by their title
    review_read: dict[str, bool] = {}    # the review page was read for the steps the form did not show again
    held_ids = {a["id"] for a in draft_answers if a.get("held")}
    reordered: set[str] = set()          # answers whose entries the form holds in another order: the draft takes the form's order   # answers that are the site's own: never set again, nothing to confirm

    def _apply(rep: dict[str, Any], i: int) -> None:
        """Take the agent's report into the state of this run."""
        lab = rep.get("labels") or {}
        entered_by_agent.update(x for x in rep.get("fixed") or [] if x in fill)
        for m in rep.get("mapped") or []:  # the form's own wording for an approved answer: from here on that is the value
            mapped.append({"label": lab.get(m["id"], m["id"]), "approved": m["approved"], "chosen": m["chosen"]})
            fill[m["id"]] = m["chosen"]
            for a in draft_answers:
                if a["id"] == m["id"]:
                    a["value"] = m["chosen"]
        for a in rep.get("adapted") or []:  # the form took the answer only in another shape: from here on that is the answer
            before = str(fill.get(a["id"], ""))
            fill[a["id"]] = a["value"]
            entered_by_agent.add(a["id"])
            if a.get("max_chars"):
                limits[a["id"]] = int(a["max_chars"])
            for row in draft_answers:
                if row["id"] == a["id"]:
                    row["value"] = a["value"]
                    row["basis"] = (f"填表时按表单的限制改写（最多 {a['max_chars']} 个字符；原答案 {len(before)} 个字符）" if a.get("max_chars") else "填表时按表单的要求改写")[:300]
                    row["confidence"] = "medium"
            adapted[:] = [x for x in adapted if x["id"] != a["id"]] + [{"id": a["id"], "label": lab.get(a["id"], a["id"]), "approved": before[:600], "entered": a["value"][:600],
                                                                       "max_chars": a.get("max_chars") or 0, "why": a.get("why", "")}]
        for qid in rep.get("absent") or []:  # not on the form for this applicant's choices: nothing to fill, nothing to verify
            fill.pop(qid, None)
            absent_ids.add(qid)
            for a in draft_answers:
                if a["id"] == qid:
                    a["value"] = ""
        for a in rep.get("added") or []:
            if not any(x["label"] == a["label"] for x in added):
                val = (rep.get("files") or {}).get(str(a["value"]), a["value"]) if a.get("type") == "file" else a["value"]      # a document: its place on disk
                added.append({"label": a["label"], "value": val, "basis": a.get("basis") or "", "type": a.get("type") or "text", "page": i, "selector": a.get("selector") or ""})
        for x in rep.get("located") or []:
            located[x["id"]] = x["selector"]
        for h in rep.get("held") or []:
            if not any(norm_question(x["label"]) == norm_question(h["label"]) for x in held):
                held.append({"label": str(h["label"])[:400], "value": h["value"], "type": h.get("type") or "text", "options": [str(o) for o in h.get("options") or []][:60],
                             "selector": h.get("selector") or "", "page": _page_index(str(h.get("section") or ""), i) if h.get("section") else i,
                             "profile_says": str(h.get("profile_says") or "").strip()[:300]})
        for n in rep.get("needs_user") or []:
            _left("fix", n["label"], "", n.get("why") or "资料里没有这一项，需要你来填")
            if n.get("type") and not any(norm_question(x["label"]) == norm_question(n["label"]) for x in asked):
                asked.append({"label": str(n["label"])[:400], "why": str(n.get("why") or "")[:300], "type": n["type"], "options": [str(o) for o in n.get("options") or []][:60], "page": i,
                              "selector": n.get("selector") or "", "provisional": str(n.get("provisional") or "")[:200] if scout else ""})
        for qid in rep.get("unfixed") or []:
            _left("fix", lab.get(qid, qid), str(fill.get(qid, ""))[:120], "表单上的选项和草案里的答案对不上，或控件没法自动操作")
        skip_verify.update(rep.get("unfixed") or [])

    def _takeover(i: int, problem: dict[str, Any], only: list[str] | None, issues: list[dict[str, Any]], on_ids: list[str] | None = None,
                  read: str = "", unread: list[str] | None = None) -> dict[str, Any] | None:
        _repair_note.clear()
        if page.is_closed():
            return None
        rep = _repair(page, schema, i, fill, problem, run_dir, only, title, application_id, issues=issues, on_ids=on_ids, read=read, unread=unread,
                      stand_in=scout and bool(db.get_setting("recon.provisional")), site=ref if generic else None)
        if rep is None:
            step("repair_skipped", why=_repair_note.get("why") or "repair is switched off")
            return None
        step("repair", page=i, fixed=len(rep["fixed"]), unfixed=len(rep["unfixed"]), mapped=len(rep.get("mapped") or []), added=len(rep.get("added") or []),
             needs_user=len(rep.get("needs_user") or []), held=len(rep.get("held") or []), located=len(rep.get("located") or []),
             form_still_reports=audit.texts(rep.get("left") or [])[:10], cause=rep.get("cause", "")[:200])
        _apply(rep, i)
        return rep

    user_done: dict[str, Any] = {}   # what the user did in the window while the program was still working on the form

    def _over() -> bool:
        """The user is at the same window. Has the application been sent meanwhile (the confirmation page is showing and
        the form is gone), or has the window been closed? Then there is nothing left to do on the form."""
        if user_done:
            return True
        if page.is_closed():
            user_done["closed"] = True
            step("window_closed")
            return True
        if _looks_submitted(page) and driver.form_gone(page, fill):
            try:
                conf = driver.confirmation(page)
            except Exception:  # noqa: BLE001
                conf = None
            try:
                seen_now = {"url": page.url, "text": page.evaluate("() => document.body.innerText.slice(0, 1500)")}
            except Exception:  # noqa: BLE001
                seen_now = {"url": "", "text": ""}
            user_done["evidence"] = conf or seen_now
            browser.snapshot(page, run_dir, "submitted_in_window")
            step("submitted_in_window", url=seen_now["url"])
            return True
        return False

    def _left_step(title0: str) -> bool:
        """Has the form moved to another step since this one was opened (told by its heading)?"""
        now = driver.step_title(page)
        return bool(title0) and bool(now) and now != title0

    def _page_index(step_title: str, fallback: int) -> int:
        """Which page of the draft a step of the live form is, by its name (the form shows its steps in its own order)."""
        t = norm_question(step_title or "")
        if t:
            for k, name in enumerate(schema.pages or []):
                nm = norm_question(str(name))
                if nm and (t in nm or nm in t):
                    return k
        return fallback

    def _needs_you(open_issues: list[dict[str, Any]]) -> list[str]:
        """What a run that would submit by itself has left that only the applicant can settle (empty: nothing)."""
        out = [f"{x['label'][:60]}（{x.get('why') or '没填上'}）" for x in leftovers if x.get("kind") in ("fix", "form", "check")]
        out += [f"{a['label'][:60]}（资料里没有答案）" for a in asked]
        out += [audit.describe(it)[:80] for it in open_issues if not _handed(it)]
        level = str(db.get_setting("policy.manual_confidence") or "low")
        if level == "medium":      # the applicant wants to look at anything that is not certain: an answer added from the profile is one
            out += [f"{a['label'][:60]}（AI 按资料补填，你还没看过）" for a in added]
        return out

    def _from_plan(title0: str, n: int) -> bool:
        """A step nobody has read on this posting, but that the site's plan knows (the agent read it on an earlier
        posting): take its questions from the plan, answer them from the profile, and let the driver fill them - no
        agent. Only when every place the plan names is on the page; otherwise the agent reads the step as before."""
        from . import siteplan

        known = siteplan.step(repair.site_key(schema), title0)
        if not known:
            return False
        have = {norm_question(q.label) for q in schema.questions}
        gone = []
        for k in known:
            try:
                if not page.locator(k["selector"]).count():
                    gone.append(k["label"])
            except Exception:  # noqa: BLE001
                gone.append(k["label"])
        if gone:
            siteplan.missed(repair.site_key(schema), title0, gone)
            step("plan_out_of_date", step=n, title=title0, missing=gone[:8])
            return False
        new = [k for k in known if norm_question(k["label"]) not in have]
        i = _page_index(title0, n)
        qs = [Question(id=f"@label:{k['label']}", label=k["label"], type=k["type"], options=k["options"], required=k["required"], page=i,
                       locator={"selector": k["selector"]}, max_length=k.get("max_length") or 0) for k in new]
        if qs:
            res = ans.resolve(FormSchema(ats=schema.ats, tenant=schema.tenant, source="agent", questions=qs), job)
            if any(r["required"] and r["type"] != "file" and r["value"] in ("", None, []) for r in res["answers"]):
                return False      # something here only the applicant can answer: the agent reads the step and asks properly
            for q, r in zip(qs, res["answers"]):
                if r["value"] in ("", None, []):
                    continue
                schema.questions.append(q)
                fill[q.id] = r["value"]
                draft_answers.append({**r, "id": q.id, "page": i})
                added.append({"label": q.label, "value": r["value"], "basis": str(r.get("basis") or "")[:200], "type": q.type, "page": i, "selector": q.locator["selector"]})
        read_now.append(title0)
        step("read_from_plan", step=n, title=title0, known=len(known), new=len(qs))
        return True

    def _unread() -> list[str]:
        """The steps of the draft that nobody has read yet, counting what this walk has read."""
        from . import drafts

        return drafts.unseen_steps(schema, also=read_now)

    def _is_read(step_title: str) -> bool:
        """Has this step of the live form been read completely - when the form was first read, or on a walk?"""
        from . import drafts

        t = norm_question(step_title or "")
        if not t:      # a step without a name cannot be remembered: not read again and again
            return True
        return any(x and (x in t or t in x) for x in (norm_question(str(r)) for r in [*drafts.read_titles(schema), *read_now]))

    def _read_review(n: int) -> None:
        """On a walk, at the review page: the steps the form did not show again (the site has them complete) are read from
        what the review shows of them."""
        left = _unread() if scout else []
        if not left:
            return
        rep = _takeover(max(0, len(schema.pages or []) - 1), {"message": "the review page: read what it shows of the steps that were not shown"}, [], [], on_ids=[],
                        read="review", unread=left)
        review_read["done"] = rep is not None
        step("read_review", step=n, steps=left[:8], found=len((rep or {}).get("held") or []))

    def _walk_steps() -> list[dict[str, Any]]:
        """A form with several steps: go through the steps that are really there. Returns what the form still reports at the end."""
        done_ids: set[str] = set()
        seen: dict[str, int] = {}
        still: list[dict[str, Any]] = []
        for n in range(40):
            if hasattr(driver, "settle"):
                driver.settle(page)      # the step as it is once it has finished loading
            sig = driver.signature(page)
            seen[sig] = seen.get(sig, 0) + 1
            if seen[sig] > 2:      # the same step for the third time: going round in circles
                step("stuck", step=n, title=driver.step_title(page))
                _left("form", f"表单停在「{driver.step_title(page) or '同一步'}」没法继续往下走", "", "请在窗口里把这一步处理好，再继续到最后提交")
                break
            still = []      # what the form reports belongs to the step it was read on
            if _over():
                break
            title0 = driver.step_title(page)
            if driver.is_review_step(page):     # a summary of the answers with the button that submits: nothing to fill in here
                step("review_step", step=n, title=title0)
                _read_review(n)
                still = _issues(None)
                break
            here = [q for q in driver.present(page, fill) if q.id not in done_ids and q.id not in held_ids]
            # a walk reads a step it has not read, whatever the form says about it (the page that submits is read as the review)
            to_read = scout and not _is_read(title0) and not driver.at_review(page)
            if to_read and _from_plan(title0, n):      # the site's plan knows this step: no agent needed to read it
                to_read = False
                here = [q for q in driver.present(page, fill) if q.id not in done_ids and q.id not in held_ids]
            ids = [q.id for q in here]
            # 1. the driver fills what this step shows
            fill_error: DriverError | None = None
            if here:
                try:
                    driver.fill_questions(page, here, fill, n)
                except DriverError as e:
                    browser.snapshot(page, run_dir, f"fill_failed_step_{n + 1}")
                    fill_error = e
                for qid, val in (getattr(driver, "kept", None) or {}).items():
                    # entries the form holds in another order than the draft listed them: the draft follows the form
                    for row in draft_answers:
                        if row["id"] == qid:
                            row["value"] = val
                    reordered.add(qid)
                if getattr(driver, "kept", None):
                    step("kept_as_on_form", step=n, fields=len(driver.kept))
            # 2. the form's own verdict; 3. the agent finishes what is left (also fields of this step the draft does not know)
            issues = _issues(None)
            for sf in getattr(driver, "stale_files", None) or []:
                # an older document is still attached beside the current one: the take-over removes it
                issues.append({"kind": "message", "label": sf["label"], "selector": "", "value": "",
                               "message": f"out-of-date document still attached: {', '.join(sf['old'])} (the current one is {sf['want']}); remove the old one"})
            if getattr(driver, "stale_files", None):
                step("old_documents", step=n, files=[x for sf in driver.stale_files for x in sf["old"]][:6])
                driver.stale_files = []
            if issues:
                step("form_reports", step=n, after="driver", issues=audit.texts(issues)[:12])
            rounds = 0
            told: list[dict[str, Any]] = []     # what a take-over of this step has been shown
            waits = False                       # a take-over has handed something on this step to the applicant
            # A question that got a stand-in answer on a walk does not hold the step: the walk reads on, the applicant is asked once.
            hands = lambda rep: bool(rep and (rep.get("unfixed") or any(not (scout and n.get("provisional")) for n in rep.get("needs_user") or [])))  # noqa: E731
            seen_before = lambda it: audit.describe(it) in {audit.describe(x) for x in told}  # noqa: E731
            if fill_error is not None or issues or to_read:
                failed = list(getattr(fill_error, "failures", [])) if fill_error is not None else []
                only = [f["id"] for f in failed] if (failed or fill_error is None) else None
                problem = (fill_error.to_dict() if fill_error is not None else {"message": "this step of the form reports problems"} if issues
                           else {"message": "this step has not been read before: read what it asks"})
                rep = _takeover(_page_index(title0, n), problem, only, issues, on_ids=ids, read="step" if to_read else "")
                rounds += 1
                if to_read and rep is not None:
                    read_now.append(title0)
                    step("read_step", step=n, title=title0, held=len(rep.get("held") or []), added=len(rep.get("added") or []), needs_user=len(rep.get("needs_user") or []))
                told += issues if rep is not None else []
                waits = waits or hands(rep)
                if rep is None and fill_error is not None:
                    for f in failed:
                        _left("fix", f["label"], str(fill.get(f["id"], ""))[:120], "没能自动填上")
            if _over():
                break
            step("fill_step", step=n, title=driver.step_title(page), questions=len(here))
            browser.snapshot(page, run_dir, f"step_{n + 1}_filled")
            # read back what was filled on this step
            if here and not _left_step(title0):
                scope = [a for a in draft_answers if a["id"] in ids and a["id"] not in skip_verify]
                bad = _really_different(page, schema, verify(schema, scope, driver.read_back(page, schema)))
                learned.read_back_differs([b["id"] for b in bad])
                if bad and rounds < 2 and _takeover(_page_index(title0, n), {"message": "values on the form differ from the approved draft", "mismatches": bad}, [b["id"] for b in bad], [], on_ids=ids) is not None:
                    rounds += 1
                    scope = [a for a in draft_answers if a["id"] in ids and a["id"] not in skip_verify]
                    bad = _really_different(page, schema, verify(schema, scope, driver.read_back(page, schema)))
                step("read_back", step=n, checked=len(scope), mismatches=len(bad))
                if bad:
                    browser.snapshot(page, run_dir, "verify_failed")
                    _mismatch_leftovers(bad)
            done_ids.update(ids)
            # 4. the form has the last word on this step
            # (an error text that was already there before the take-over stays on many forms until they are asked again:
            # pressing the forward button below is the test for it, not another take-over)
            # What a take-over has already been shown and could not settle is not new: asking again finds the same thing.
            still = audit.not_stale(_issues(None), told)
            fresh = [it for it in still if not _handed(it) and not seen_before(it)]
            if fresh and rounds < 2 and repair.enabled():
                step("form_reports", step=n, after="checks", issues=audit.texts(fresh)[:12])
                rep = _takeover(_page_index(title0, n), {"message": "this step was filled and compared with the draft, but the form still reports problems"}, [], fresh, on_ids=ids)
                if rep is not None:
                    rounds += 1
                    told += fresh
                    waits = waits or hands(rep)
                    still = audit.not_stale(_issues(None), told)
            if waits:      # what was handed to the applicant is on the list by its name; the form's raw marks for the same thing are not repeated
                still = [it for it in still if not seen_before(it)]
            # the last step is where the user submits
            if driver.at_review(page):
                step("review_step", step=n, title=driver.step_title(page))
                _read_review(n)
                break
            # on to the next step: the form's own button, else the agent finds the way
            if _over():
                break
            if _left_step(title0):      # a take-over went on to the next step by itself: that step is handled in the next round
                step("advance", step=n, how="take-over")
                continue
            moved, how, why, at_end = driver.forward(page), "button", "", False
            if not moved and waits:      # the step is waiting for an answer only the applicant has: no agent can move it on
                why = "这一步还有需要你回答的问题"
            for _ in range(2 if repair.enabled() and not waits else 0):
                if moved:
                    break
                # The form refused to go on, and now it says why (many forms report a missing answer only after "Continue"):
                # one more round of finishing this step, then its own button again.
                if _over():
                    break
                blockers = [it for it in _issues(None) if not _handed(it) and not seen_before(it)]
                if (blockers or why) and rounds < 3:
                    step("form_reports", step=n, after="next", issues=audit.texts(blockers)[:12], seen=why[:200])
                    rounds += 1
                    # what the navigator saw on the page counts like a message of the form, when the form's own marks show nothing
                    seen_there = blockers or [{"kind": "message", "label": "", "message": why[:240], "selector": "", "value": ""}]
                    rep = _takeover(_page_index(title0, n), {"message": "the form does not go on to the next step" + (f": {why}" if why else "")}, [], seen_there, on_ids=ids)
                    if rep is not None:
                        told += seen_there
                        if hands(rep):       # it is the applicant's to answer: stop here
                            waits, still = True, [it for it in _issues(None) if not seen_before(it)]
                            break
                        still = _issues(None)
                        moved = _left_step(title0) or driver.forward(page)
                        if moved:
                            how = "button after take-over"
                            break
                if _over():
                    break
                # no button the program knows: the agent finds the way
                before = driver.signature(page)
                try:
                    nav = repair.advance(page, schema, run_dir, step=n)
                except llm.LLMError as e:
                    nav = {"state": "blocked", "why": f"AI 没能接手：{str(e)[:160]}"}
                if nav["state"] == "review":
                    at_end = True
                    break
                moved, how, why = nav["state"] == "moved" and driver.signature(page) != before, "agent", nav.get("why", "")
                if not why:
                    break
            if at_end:
                step("review_step", step=n, title=driver.step_title(page), found_by="agent")
                _read_review(n)
                break
            if _over():
                break
            if not moved:
                step("cannot_advance", step=n, title=driver.step_title(page), why=why[:200])
                for it in still:
                    if not _handed(it):
                        _left("form", audit.describe(it), "", "表单自己的提示")
                _left("form", f"表单在「{driver.step_title(page) or '这一步'}」没法进入下一步" + (f"：{why[:120]}" if why else ""), "", "请在窗口里把这一步处理好，再继续到最后提交")
                break
            step("advance", step=n, how=how)
        # answers the form never asked for this time: usually saved by an earlier attempt, or not needed for this applicant
        rest = [q for q in schema.questions if q.id in fill and q.id not in done_ids and q.id not in entered_by_agent and q.id not in held_ids]
        if user_done:      # the user sent the application or closed the window: nothing on the form is left to compare
            return []
        if rest:
            try:
                browser.snapshot(page, run_dir, "review")      # what the review page showed, kept with the run
                opened = driver.open_summaries(page) if hasattr(driver, "open_summaries") else 0      # a review often keeps the answers folded
                if opened:
                    page.wait_for_timeout(600)
                    step("review_unfolded", sections=opened)
                shown = " ".join(page.inner_text("body", timeout=5000).lower().split())
            except Exception:  # noqa: BLE001
                shown = ""
            unseen = []
            for q in rest:
                val = fill[q.id]
                want = Path(str(val)).name if q.type == "file" else ", ".join(map(str, val)) if isinstance(val, list) else str(val)
                parts = [str(x).lower() for x in (val if isinstance(val, list) else [want])] if q.type != "file" else [want.lower()]
                if not (all(" ".join(x.split()) in shown for x in parts if x) and " ".join(q.label.lower().split())[:60] in shown):
                    unseen.append((q, want))
            step("not_asked", count=len(rest), shown_on_review=len(rest) - len(unseen), unconfirmed=[q.label for q, _ in unseen][:20])
            for q, want in unseen:
                if q.type == "checkbox":     # acknowledgements belong to steps that were passed; nothing to compare on a summary
                    continue
                _left("check", q.label, want[:120], "表单这次没有再问这一题（多半是上次已经保存了），确认页上也没找到这个答案，提交前请核对")
        return still

    def _after_verify_repair(rep: dict[str, Any], i: int) -> None:
        _apply(rep, i)

    try:
        headless = policy != "manual" or scout
        with browser.open_page(ref.tenant_key if (driver.requires_login or generic) else None, headless=headless, url=ref.url, operation="apply") as page:
            timing.timed_goto(page)
            learned.waits_on(page)                         # "after load": every time this page is sent somewhere
            st = auth.ensure_session(page, signer or driver, ref)      # a site with a coded sign-in uses it, whoever fills the form
            step("ensure_session", result=st)
            if driver.requires_login and driver.already_applied(page, ref):
                raise AlreadyApplied()
            driver.open_application(page, ref)
            step("open", url=page.url)
            if generic:
                from . import generic as gen

                if not gen.form_present(page, schema, wait_s=4) and (dup := _already_applied(page)):
                    # no form, and the site says why: it has this application already (sent in an earlier run whose
                    # confirmation page was not seen, or by the applicant themselves). Not a sign-in problem.
                    browser.snapshot(page, run_dir, "already_applied")
                    step("already_applied", url=dup["url"], text=dup["text"][:200])
                    raise AlreadyApplied(dup)
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
            wizard = generic and len(pages) > 1
            if wizard:
                step("walk", pages_in_draft=len(pages))
                open_issues = _walk_steps()
            for i in range(0 if wizard else len(pages)):
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
                    moved = _next_page(driver, page)
                    if not moved and rounds < 2 and repair.enabled():
                        # the form refused to go on: now it says why. One more round for the agent, then one more try.
                        blockers = _issues(i)
                        step("form_reports", page=i, after="next", issues=audit.texts(blockers)[:12])
                        if blockers and _takeover(i, {"message": "the form does not advance to the next page"}, [], blockers) is not None:
                            moved = _next_page(driver, page)
                    if not moved:
                        raise DriverError("could not advance to the next page", page=i, seen="; ".join(_errors(driver, page) or audit.texts(_issues(i)))[:400])
                    step("next", page=i)
            if not per_page and not wizard:
                _checked(lambda: _verify(driver, page, schema, [a for a in draft_answers if a["id"] not in skip_verify], fill, None, page_of, run_dir, step, title, application_id,
                                         after_repair=lambda rep: _after_verify_repair(rep, max(0, len(pages) - 1))))
            touched = any(st["op"] == "repair" for st in steps)
            if scout:
                # the walk ends here: at the review page, or at a step that needs the applicant. Nothing is submitted, nobody is handed a window.
                reached = any(st["op"] == "review_step" for st in steps)
                outcome = {"status": "scouted", "reached_review": reached, "stopped_at": "" if reached or page.is_closed() else driver.step_title(page),
                           "read": list(read_now), "all_read": reached and (review_read.get("done", False) or not _unread())}
                step("scouted", reached_review=reached, stopped_at=outcome["stopped_at"])
            elif policy != "manual" and (needs_you := _needs_you(open_issues)):
                # The agent having worked on the form is no reason to stop: the answers are the approved ones and were read
                # back. What stops an automatic submission is something that is the applicant's to settle.
                raise NeedsVisibleRun("有需要你处理的地方，这次填好后由你过目并提交：" + "；".join(needs_you[:4]))
            elif policy == "manual" and user_done.get("evidence"):
                # the user submitted in the window while the program was still on the form: the confirmation page was seen
                notify.close_todos("submit", f"application:{application_id}")
                outcome = {"status": "submitted", "evidence": user_done["evidence"]}
            elif policy == "manual":
                # 5. whatever the form still complains about goes to the user by the form's own words: never "filled" while it says otherwise
                for it in open_issues:
                    if not _handed(it):
                        _left("form", audit.describe(it), "", "表单自己的提示")
                if open_issues:
                    step("form_reports", page=len(pages) - 1, after="everything", issues=audit.texts(open_issues)[:12])
                    browser.snapshot(page, run_dir, "handed_over")
                if leftovers or mapped or added:
                    step("handed_over", left=[x["label"] for x in leftovers][:20], mapped=[m["label"] for m in mapped][:20], added=[a["label"] for a in added][:20])
                # the questions handed to the applicant are watched while they have the window: what they answer there is kept
                watch = [Question(id=f"@label:{a['label']}", label=a["label"], type=a["type"], options=a["options"], locator={"selector": f"@label:{a['label']}"}) for a in asked] if generic else []
                typed: dict[str, Any] = {}
                outcome = _wait_for_manual_submit(driver, page, title, application_id, draft_id, leftovers=leftovers, mapped=mapped, added=added, adapted=adapted, watch=watch, typed=typed)
                for a in asked:
                    a["value"] = typed.get(f"@label:{a['label']}", "")
            else:
                clicked_at = datetime.now(timezone.utc)
                try:
                    driver.submit(page)
                except DriverError as e:
                    if generic and re.search(r"not on the last step|could not tell which button", str(e)):
                        # Nothing was pressed: the program could not make out the button that sends. The form is filled
                        # and checked - that is not a failed run, it is one the applicant finishes with one click.
                        browser.snapshot(page, run_dir, "submit_not_found")
                        raise NeedsVisibleRun("表单已经填好并核对过，但程序没能确认哪个是提交按钮，这次由你点提交") from e
                    raise
                step("submit")
                if _email_code_step(driver, page, run_dir, clicked_at):
                    step("email_code")
                conf = driver.confirmation(page)
                shots = browser.snapshot(page, run_dir, "confirmation")
                if conf is None:
                    errs = _errors(driver, page)
                    raise DriverError("no confirmation after submit", seen="; ".join(errs)[:500] or page.url)
                outcome = {"status": "submitted", "evidence": {**conf, **shots}}
            if generic and outcome.get("status") == "submitted":
                _finish_account(page, ref, step, run_dir)
            if driver.requires_login:
                browser.save_state(ref.tenant_key, page.context)
        ok = outcome.get("status") == "submitted"
    except AlreadyApplied as e:
        seen_there = e.args[0] if e.args and isinstance(e.args[0], dict) else {"text": "The site shows this job as already applied."}
        outcome = {"status": "submitted", "evidence": seen_there, "note": "雇主网站显示这个岗位已经申请过了，没有再提交一次"}
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

    if scout:      # the application's status is not the walk's to change; what it found goes into the draft
        with db.session() as s:
            s.add(Run(task_id=task_id, kind="scout", ref=f"application:{application_id}", ats=ref.ats, ok=int(outcome.get("status") == "scouted"), steps=steps, spans=_scout_spans(), site=_site_of(schema), dir=str(run_dir)))
            if mapped or added or adapted or asked or held or located or reordered:
                _keep_learned(s.get(Draft, draft_id), schema, draft_answers, approved_values, absent_ids, added, generic=generic, limits=limits, asked=asked, send_back=False,
                              held=held, located=located)
        return {**{k: v for k, v in outcome.items() if k not in ("evidence", "driver_error", "mismatches", "diff")}, "added": len(added), "asked": len(asked), "adapted": len(adapted),
                "held": len(held),
                "mapped": len(mapped), "steps": sum(1 for st in steps if st["op"] == "fill_step")}
    with db.session() as s:
        app = s.get(Application, application_id)
        app.status = outcome["status"]
        was_auto = bool(app.auto_approved)
        app.last_event = outcome.get("error") or outcome.get("note") or ""
        if outcome["status"] == "submitted":
            app.submitted_at = now()
            app.evidence = outcome.get("evidence", {})
            app.detail = f"submitted {now().date().isoformat()} via {ref.ats}" + (" (auto-approved)" if app.auto_approved else "")
        spans = timing.end()
        run = Run(task_id=task_id, kind="execute", ref=f"application:{application_id}", ats=ref.ats, ok=int(ok), steps=steps, spans=spans, site=_site_of(schema),
                  learned=learned.in_force(), dir=str(run_dir))
        s.add(run)
        s.flush()
        run_id = run.id
        new_questions = 0
        if mapped or added or adapted or asked or located or reordered:
            back = outcome["status"] != "submitted"
            new_questions = _keep_learned(s.get(Draft, draft_id), schema, draft_answers, approved_values, absent_ids, added, generic=generic, limits=limits, asked=asked, send_back=back,
                                          located=located) or 0
            if new_questions and back:       # the draft goes back to the applicant: it has questions only they can answer
                app.status = "needs_input"
                app.last_event = f"填表时遇到 {new_questions} 个草案里没有、资料里也没有答案的问题，已加进草案；回答并批准后接着填"
    # outside the session: SQLite allows one writer at a time
    # What was learned and was in force is judged by this run; then the run itself is looked at for what to learn next.
    try:
        from . import improve

        changed = learned.end(ok=ok, working_ms=timing.working_ms(spans), interventions=len(leftovers), run_id=run_id)
        improve.after_run(run_id, changed)
    except Exception:  # noqa: BLE001 - learning from a run must never fail the run
        log.exception("could not look at the run for what to learn")
    for a in asked:      # answered by the applicant in the window: remembered, so that no form has to ask it again
        if a.get("value") not in ("", None, [], False):
            shown = "; ".join(map(str, a["value"])) if isinstance(a["value"], list) else str(a["value"])
            try:
                knowledge.append_rule(f'Form question "{a["label"].strip()[:200]}": answer "{shown[:300]}".', source="user", section="Standard answers")
                ans.cache_put(schema.ats, Question(id=f"@label:{a['label']}", label=a["label"], type=a["type"], options=a["options"]), a["value"], "answered by the applicant in the application window", confirmed=True)
            except Exception:  # noqa: BLE001 - remembering must not fail the run
                log.exception("could not remember an answer given in the window")
    if new_questions and outcome["status"] != "submitted":
        names = "\n".join("· " + a["label"][:90] for a in asked if a.get("value") in ("", None, [], False))[:600]
        notify.close_todos("submit", f"application:{application_id}")
        notify.add_todo("answer", title, ref=f"draft:{draft_id}", payload={"draft_id": draft_id},
                        body=f"填表时遇到 {new_questions} 个资料里没有答案的问题，已加进草案。在草案里回答一次（勾选“记住这个答案”），以后就会自动填：\n{names}")
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
                  added: list[dict[str, Any]], *, generic: bool, limits: dict[str, int] | None = None, asked: list[dict[str, Any]] | None = None,
                  send_back: bool = False, held: list[dict[str, Any]] | None = None, located: dict[str, str] | None = None) -> int:
    """Write back into the draft what the take-over established, so the next run of it needs no agent:
    the form's own wording for approved answers, and the questions the first reading of the form did not see.
    For explored forms the new questions also join the schema (found by their label), which is what the driver replays."""
    if d is None:
        return 0
    rows = []
    for a in draft_answers:
        row = dict(a)
        if row["id"] in absent_ids:  # missing on the page this time only: the approved answer stays
            row["value"] = approved_values.get(row["id"], row["value"])
        rows.append(row)
    sch = dict(d.schema)
    questions = [dict(q) for q in sch.get("questions", [])]
    for q in questions:      # a limit the form showed only after typing: the question remembers it
        if (limits or {}).get(q.get("id")):
            q["max_length"] = int(limits[q["id"]])
    for q in questions:      # where the take-over found a question the driver could only look for by its label
        sel = str((q.get("locator") or {}).get("selector") or q.get("id") or "")
        if generic and (located or {}).get(q.get("id")) and sel.startswith("@label:"):
            q["locator"] = {**(q.get("locator") or {}), "selector": located[q["id"]]}
    for a in held or []:     # the site has an answer to it already: shown in the draft as it stands, not set again
        qid = f"@label:{a['label']}"
        if any(norm_question(r.get("label", "")) == norm_question(a["label"]) for r in rows):
            continue
        typ = a["type"] if a["type"] in ("text", "textarea", "select", "radio", "checkbox", "date", "multiselect") else "text"
        differs = bool(a.get("profile_says")) and not values_equal(a["profile_says"], a["value"])
        rows.append({"id": qid, "label": a["label"], "type": typ, "options": a.get("options") or [], "required": False, "page": a["page"], "value": a["value"],
                     "basis": (f"雇主网站上存的是旧信息：你的资料里写的是「{a['profile_says']}」。要改就在这里改成新的，程序会按你改的去填"[:300] if differs
                               else "雇主网站上已经存着这个答案（来自以前的申请或你在那里的资料），程序没有改动"),
                     "confidence": "low" if differs else "high", "source": "site", "held": True, "conflict": differs,
                     "sensitive": sensitivity(a["label"]), "sensitive_confirmed": False})
        if generic and not any(q["id"] == qid for q in questions):
            questions.append(Question(id=qid, label=a["label"], type=typ, options=a.get("options") or [], required=False, page=a["page"],
                                      locator={"selector": a.get("selector") or qid}).__dict__)
    for a in added:
        qid = f"@label:{a['label']}"
        row = {"id": qid, "label": a["label"], "type": a["type"] if a["type"] in ("text", "textarea", "select", "radio", "checkbox", "date", "file", "multiselect") else "text", "options": [],
               "required": True, "page": a["page"], "value": a["value"], "basis": ("填表时 AI 按你的资料补填：" + a["basis"])[:300], "confidence": "medium",
               "source": "agent_added", "sensitive": sensitivity(a["label"]), "sensitive_confirmed": False}
        rows = [r for r in rows if r["id"] != qid] + [row]
        if generic and not any(q["id"] == qid for q in questions):
            questions.append(Question(id=qid, label=a["label"], type=row["type"], required=True, page=a["page"], locator={"selector": a.get("selector") or qid}).__dict__)
        try:
            ans.cache_put(schema.ats, Question(id=qid, label=a["label"], type=row["type"]), a["value"], row["basis"], confirmed=False)
        except Exception:  # noqa: BLE001
            log.debug("answer not cached", exc_info=True)
    # Questions the form asks that neither the draft nor the profile answers: open questions of the draft from now on.
    # Answered once in the program, they are filled by their label on the next run (and remembered, if the applicant says so).
    fresh = 0
    for a in asked or []:
        qid = f"@label:{a['label']}"
        typ = a["type"] if a["type"] in ("text", "textarea", "select", "radio", "checkbox", "date", "multiselect") else "text"
        given = a.get("value") not in ("", None, [], False)      # the applicant answered it in the window
        old = next((r for r in rows if norm_question(r.get("label", "")) == norm_question(a["label"])), None)
        if old is not None and (not given or old.get("value") not in ("", None, [])):
            continue
        row = {"id": qid, "label": a["label"], "type": typ, "options": a.get("options") or [], "required": True, "page": a["page"], "value": a["value"] if given else "",
               "basis": "你在申请窗口里填的" if given else (("填表时遇到的问题，资料里没有答案：" + a.get("why", ""))[:240]
                                                      + (f"（为了读完后面的步骤，表单里临时填了「{a['provisional']}」，不会提交；你回答后会换成你的答案）" if a.get("provisional") else "")),
               "confidence": "high" if given else "low",
               "source": "profile" if given else "unresolved", "sensitive": sensitivity(a["label"]), "sensitive_confirmed": given}
        rows = [r for r in rows if r is not old] + [row]
        if generic and not any(q["id"] == qid for q in questions):
            questions.append(Question(id=qid, label=a["label"], type=typ, options=a.get("options") or [], required=True, page=a["page"], locator={"selector": a.get("selector") or qid}).__dict__)
        fresh += 0 if given else 1
    sch["questions"] = questions
    d.answers = rows
    d.schema = sch
    if asked:
        d.unresolved = [r for r in rows if r.get("source") == "unresolved" and r.get("required")]
    if fresh and send_back:      # back to the applicant: answering and approving it starts the filling again
        d.review_status, d.approved_at = "pending", None
    return fresh


_repair_note: dict[str, str] = {}   # why the last take-over did not happen (shown with the failure)


def _repair(page: Any, schema: FormSchema, i: int, fill: dict[str, Any], problem: dict[str, Any], run_dir: Path,
            only_ids: list[str] | None, title: str, application_id: int, *, issues: list[dict[str, Any]] | None = None,
            on_ids: list[str] | None = None, read: str = "", unread: list[str] | None = None, stand_in: bool = False, site: Any = None) -> dict[str, Any] | None:
    """Agent takeover of one page. None when repair is off or no model is available (the caller re-raises)."""
    if not repair.enabled():
        return None
    try:
        return repair.fix_page(page, schema, i, fill, problem, run_dir, only_ids=only_ids, issues=issues, title=title, ref=f"application:{application_id}", on_ids=on_ids,
                               read=read, unread=unread, stand_in=stand_in, site=site)
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
    learned.read_back_differs([b["id"] for b in bad])      # before anything is repaired: what the revisions in force left behind
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
            bad = _really_different(page, schema, _not_vouched(verify(schema, scope, back), rep.get("fixed") or []))
    wanted = [a for a in scope if a["value"] not in ("", None, [])]
    step("read_back", page=i, checked=sum(1 for a in wanted if a["id"] in back), unverified=[a["label"] for a in wanted if a["id"] not in back][:20], mismatches=len(bad))
    if bad:
        browser.snapshot(page, run_dir, "verify_failed")
        raise VerifyFailed(bad)


def _not_vouched(bad: list[dict[str, Any]], fixed: list[str]) -> list[dict[str, Any]]:
    """A control that shows less than it holds: a phone-code list whose entry is "+1 / Canada" shows "+1" once chosen, and
    "+1" cannot be told from the other countries' "+1" by reading it. When the agent was just sent to exactly this field,
    chose the approved entry and reports it done, and what the control shows is a part of that entry, the field holds the
    approved answer - the agent saw the choice being made; the read-back cannot see it. Anything the control shows
    that is NOT part of the approved entry stays a difference, whoever vouches for it."""
    def parts(v: Any) -> set[str]:
        return {x for x in (re.sub(r"\s+", " ", t).strip().lower() for t in re.split(r"[\n,;|/()]", str(v))) if x}

    return [b for b in bad if not (b["id"] in fixed and not isinstance(b["expected"], list) and len(parts(b["expected"])) > 1
                                   and str(b["actual"] or "").strip() and parts(b["actual"]) <= parts(b["expected"]))]


def _really_different(page: Any, schema: FormSchema, bad: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """On explored forms (always submitted by the user) a control that reads back empty is not yet a difference: custom
    widgets show the choice as a chip or put the uploaded file's name elsewhere. Look at what the page shows before
    calling the agent for it. Coded drivers know how to read their own controls and are taken at their word."""
    if schema.source != "agent" or not bad:
        return bad
    from .ats.generic_driver import value_visible

    by_id = {q.id: q for q in schema.questions}
    bad = [b for b in bad if not (b["actual"] in ("", None, []) and b["id"] in by_id and value_visible(page, by_id[b["id"]], b["expected"]))]
    # a ticked box is a ticked box, whatever the control calls it
    yes = {"true", "on", "yes", "checked", "1"}
    bad = [b for b in bad if not (b["id"] in by_id and by_id[b["id"]].type == "checkbox" and not isinstance(b["expected"], list)
                                  and (str(b["expected"]).strip().lower() in yes) == (str(b["actual"]).strip().lower() in yes))]
    if bad and repair.enabled():
        # What is left is looked at by the agent before anyone is told that the form differs from the draft: a program
        # reads a custom control badly ("on" for two ticked boxes, nothing for a row of pills); looking at the page settles it.
        try:
            seen = repair.confirm(page, bad, config.RUNS / "confirm")
        except llm.LLMError:
            seen = {}
        bad = [{**b, **({"actual": seen[b["id"]]["seen"]} if b["id"] in seen and seen[b["id"]]["seen"] else {})} for b in bad if not seen.get(b["id"], {}).get("same")]
    return bad


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


def _finish_account(page: Any, ref: JobRef, step: Any, run_dir: Any = None) -> None:
    """The application created the applicant's account on the site (a password was set on the form). Sites finish that
    with a confirmation mail: its link is opened when it is the site's own (mail.link_refusal), and the account is then
    ready for the next application there. Never a reason to fail a submission that went through.

    Some sites take the sign-in only now ("You can log in after submitting your application"): the page that confirms
    the application offers it. An account that is not known to work yet is signed in to, or created, right there."""
    try:
        from . import generic as _generic

        acct = auth.account(auth.key_for(ref.tenant_key)) or {}
        if run_dir is not None and acct.get("status") != "ok" and repair.enabled() and _generic.ACCOUNT_OFFER.search(page.inner_text("body")[:6000]):
            got = _generic.account_after_submit(page, ref, run_dir)
            step("account_after_submit", ok=got["ok"], notes=got["notes"][:200])
            if got["ok"]:
                return
    except Exception as e:  # noqa: BLE001
        log.info("the account offered after the submission was not completed: %s", e)
    try:
        acct = auth.account(ref.tenant_key) or {}
        if acct.get("status") != "pending" or not secrets.get_password(ref.tenant_key):
            return
        from . import mail

        since = datetime.now(timezone.utc) - timedelta(minutes=3)
        got = mail.wait_for_verification(sender_hint=ref.host, timeout=120, since=since, site_host=ref.host)
        if got and got.startswith("http"):
            page.goto(got, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            if not mail.link_refusal(page.url, ref.host):
                auth.upsert_account(ref.tenant_key, ats=ref.ats, host=ref.host, status="ok")
                browser.save_state(ref.tenant_key, page.context)
                step("account_confirmed", host=ref.host)
                return
        why = got[9:] if got and got.startswith("refused:") else ("没有收到确认邮件" if not got else "确认邮件里是验证码，不是链接")
        auth.upsert_account(ref.tenant_key, ats=ref.ats, host=ref.host, error=f"账号随申请建好了，邮箱确认还没完成：{why}"[:300])
        step("account_unconfirmed", why=why[:120])
    except Exception as e:  # noqa: BLE001
        log.info("account confirmation after the submission did not complete: %s", e)


def _scout_spans() -> list[dict[str, Any]]:
    learned.drop()          # a walk that only reads the form is no trial of what was learned
    return timing.end()


def _next_page(driver: Any, page: Any) -> bool:
    moved = driver.next_page(page)
    if moved:
        learned.wait_after(page, "step")
    return moved


def _site_of(schema: FormSchema) -> str:
    try:
        return repair.site_key(schema)
    except Exception:  # noqa: BLE001 - a run is recorded whether or not its site can be named
        return ""


def _wait_for_manual_submit(*a: Any, **kw: Any) -> dict[str, Any]:
    with timing.span("human", "window"):        # the applicant's time, never counted against the run
        return _manual_submit_wait(*a, **kw)


def _manual_submit_wait(driver: Any, page: Any, title: str, application_id: int, draft_id: int | None = None, *,
                            leftovers: list[dict[str, str]] | None = None, mapped: list[dict[str, str]] | None = None,
                            added: list[dict[str, Any]] | None = None, adapted: list[dict[str, Any]] | None = None,
                            watch: list[Any] | None = None, typed: dict[str, Any] | None = None) -> dict[str, Any]:
    """Manual policy: the form is filled in a visible window; the user clicks Submit."""
    payload: dict[str, Any] = {"draft_id": draft_id} if draft_id else {}
    if leftovers:
        payload["open_items"] = leftovers[:30]
    if mapped:
        payload["mapped"] = mapped[:30]
    if added:
        payload["added"] = [{"label": a["label"], "value": str(a["value"])[:120], "basis": a.get("basis", "")[:200]} for a in added[:30]]
    if adapted:
        payload["adapted"] = [{"label": a["label"], "approved": a["approved"], "entered": a["entered"], "max_chars": a.get("max_chars") or 0} for a in adapted[:30]]
    todo_n = sum(1 for m in leftovers or [] if m.get("kind") in ("fix", "form"))
    look_n = sum(1 for m in leftovers or [] if m.get("kind") == "check")
    if todo_n:
        payload["incomplete"] = True   # the card and the notification must not say "filled"
    parts = [f"还有 {todo_n} 处没填好，需要你在窗口里处理" if todo_n else "", f"{look_n} 项请你看一眼是否填上了" if look_n else "",
             f"{len(added)} 项是 AI 按你的资料补填的" if added else "", f"{len(adapted)} 项答案按表单的限制改写了，提交前请过目" if adapted else ""]
    notify.close_todos("submit", f"application:{application_id}")  # a fresh card: what is left to do differs from run to run
    notify.add_todo("submit", title, ref=f"application:{application_id}", payload=payload or None, body="；".join(x for x in parts if x))
    code_tried = False
    last: dict[str, str] = {}
    watched = FormSchema(ats="generic", questions=list(watch or [])) if watch else None
    for tick in range(1200):  # up to ~20 minutes
        if page.is_closed():
            break
        if watched is not None and typed is not None and tick % 2 == 0:
            # What the applicant enters for the questions that were handed to them: read while the field is on the page
            # (it is gone once they go on to the next step), kept for the draft and remembered.
            try:
                for qid, val in driver.read_back(page, watched).items():
                    if val not in ("", None, [], False):
                        typed[qid] = val
            except Exception:  # noqa: BLE001 - the page is theirs right now; a failed read must not disturb them
                pass
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
        # Remember what the window last showed: the user may close it right after the confirmation appears.
        # Pressing Submit loads another page, and for a moment there is nothing to read: that is not a closed window.
        # (It was taken for one, and the window was closed on the applicant in the middle of the submission.)
        now_ = _seen(page, 1500)
        if now_["text"] or now_["title"]:
            last = now_
        try:
            page.wait_for_timeout(1000)
        except Exception:  # noqa: BLE001
            if page.is_closed():
                break
            time.sleep(1)
    if last and (DONE_RE.search(last["text"]) or DONE_RE.search(last.get("title", "")) or DONE_URL.search(last["url"])):
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
    now_ = _seen(page)
    return bool(DONE_RE.search(now_["text"]) or DONE_RE.search(now_["title"]) or DONE_URL.search(now_["url"]))
