"""HTTP API + static frontend. Local, single-user: bind to 127.0.0.1 only."""

from __future__ import annotations

import logging
import os
import mimetypes
import re

import shutil
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func

# Windows takes file types from the registry, which does not know .mjs (the PDF viewer's worker) and on some
# machines maps .js to text/plain; browsers refuse to run module scripts served that way.
from .. import access, quiet

quiet.install()      # no console window for anything this server starts
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/javascript", ".js")

from .. import net, persona, prompts
from .. import auth, config, db, discover, drafts, handlers, humanize, knowledge, llm, mail, messages, notify, secrets, stages, tasks
from ..ats import registry
from ..models import Contact
from ..models import Application, Document, Draft, DriverStat, Job, MailEvent, Notification, Run, Task, Todo, now


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    persona.migrate()
    from .. import i18n as _i18n
    from ..sources import watch as _watch

    _i18n.first_run_lang()
    if not db.get_setting("migrated.page_ids"):
        _watch.migrate_ids()
        db.set_setting("migrated.page_ids", True)
    if not db.get_setting("migrated.llm_runs"):
        # per-task totals from before every model request was recorded: carried over once, marked as history
        from .. import metering as _metering

        _metering.import_legacy()
        db.set_setting("migrated.llm_runs", True)
    try:      # every start: confirmations read while an application was taken for unsent; cards of applications that are sent
        from .. import lifecycle as _lifecycle

        mail.reconcile()
        _lifecycle.settle_all()
    except Exception:  # noqa: BLE001 - never a reason not to start
        logging.getLogger("autoapply").exception("could not settle sent applications")
    try:      # a newer price list came with the program: requests that had no price, or an older one, are estimated again
        import json as _json

        from .. import metering as _metering2

        ver = str(_json.loads((Path(_metering2.__file__).parent / "pricing.json").read_text(encoding="utf-8")).get("version") or "")
        if ver and db.get_setting("migrated.pricing_version") != ver:
            _metering2.reprice()
            db.set_setting("migrated.pricing_version", ver)
    except Exception:  # noqa: BLE001
        logging.getLogger("autoapply").exception("could not apply the new price list")
    if not db.get_setting("migrated.agent_reads_all"):
        # the first version of "the agent reads the form" covered one system; a settings page saved since then has stored
        # that list. Every site is read by the agent now.
        if db.get_setting("agent.reads") == ["workday"]:
            db.set_setting("agent.reads", ["*"])
        db.set_setting("migrated.agent_reads_all", True)
    if not db.get_setting("migrated.sites"):
        from .. import sites as _sites_

        _sites_.migrate()
        db.set_setting("migrated.sites", True)
    if not db.get_setting("migrated.site_rules_whole"):
        from .. import browser_policy as _policy

        _policy.store_rules_whole()
        db.set_setting("migrated.site_rules_whole", True)
    if not db.get_setting("migrated.generic_patch_cards"):
        # "driver patch suggestion" cards for forms the AI explored: there is no driver to patch, so nobody could act on them
        from ..models import Todo, now

        with db.session() as s:
            for td in s.query(Todo).filter_by(kind="driver_patch", status="open"):
                if (td.payload or {}).get("ats") == "generic":
                    td.status, td.done_at = "done", now()
        db.set_setting("migrated.generic_patch_cards", True)
    net.apply()
    tasks.start()
    yield
    tasks.stop()


log = logging.getLogger("autoapply.api")

app = FastAPI(title="AutoApply", lifespan=lifespan)


# PD Portal import runs in the user's own browser on the portal's page and posts to this local server.
# Only that origin may call these two endpoints from another site.
PORTAL_ORIGIN = "https://pdportal.apsc.ubc.ca"


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}


def _own_hosts() -> set[str]:
    """Host names under which this server is the user's own: this computer, and the address the user set for links."""
    from urllib.parse import urlparse

    hosts = set(LOCAL_HOSTS)
    c = access.conf()
    hosts.update(c["allowed_hosts"])
    if access.exposed(c):      # it listens for other computers: they call it by one of this computer's addresses
        hosts.update(_own_addresses(c["host"]))
    try:
        h = urlparse(str(db.get_setting("app.base_url") or "")).hostname
        if h:
            hosts.add(h.lower())
    except Exception:  # noqa: BLE001
        pass
    return hosts


_addresses: dict[str, Any] = {"at": 0.0, "of": set()}


def _own_addresses(host: str) -> set[str]:
    """The addresses and the name of this computer (looked up once a minute), or the one address it listens on."""
    import socket
    import time as _time

    if host not in ("0.0.0.0", "::"):  # noqa: S104 - compared, not bound
        return {host.lower()}
    if _time.time() - _addresses["at"] > 60:
        found = set()
        try:
            name = socket.gethostname()
            found.add(name.lower())
            found.update(a.lower() for a in socket.gethostbyname_ex(name)[2])
        except OSError:
            pass
        _addresses.update(at=_time.time(), of=found)
    return set(_addresses["of"])


def _host_of(value: str) -> str:
    """'127.0.0.1:8000' -> '127.0.0.1'; '[::1]:8000' -> '::1'."""
    v = (value or "").strip().lower()
    if v.startswith("["):
        return v[1:].split("]", 1)[0]
    return v.rsplit(":", 1)[0] if ":" in v else v


def _foreign(request) -> str:  # noqa: ANN001
    return _foreign_at(request, request.scope["path"])


def _foreign_at(request, path: str) -> str:  # noqa: ANN001
    """Why this request does not come from the user's own pages ('' when it does).

    The server has no login: it listens on 127.0.0.1 and trusts whoever can reach it. A web page the user happens to
    have open can reach it too - the browser will send a request to 127.0.0.1 for any site - so two things are checked:
    the Host header is this computer's (a page cannot get around the browser's same-origin rule by pointing its own
    domain name at 127.0.0.1), and a request that changes something, or any API call the browser itself marks as
    cross-site, comes from one of this program's own pages. Programs on this computer (the tray launcher, the AI
    tool bridge, curl) send no Origin and are not affected."""
    from urllib.parse import urlparse

    own = _own_hosts()
    host = request.headers.get("host", "")
    if _host_of(host) not in own:
        return "host"
    if not (path.startswith("/api/") or path.startswith("/mcp/")):
        return ""
    origin = request.headers.get("origin")
    if path.startswith("/api/import/pdportal") and origin == PORTAL_ORIGIN:
        return ""          # the one deliberate exception: the importer the user runs on the portal's page
    if origin is not None:
        # The whole origin has to be ours - scheme, host and port. Another program on this computer can serve a page
        # at 127.0.0.1 on its own port; the same host name does not make that page this program's.
        mine = {f"{s}://{host}".lower().rstrip("/") for s in ("http", "https")} if access.conf()["https_by_proxy"] else {f"{request.url.scheme}://{host}".lower().rstrip("/")}
        base = str(db.get_setting("app.base_url") or "").strip().lower().rstrip("/")
        if base:
            u = urlparse(base)
            mine.add(f"{u.scheme}://{u.netloc}")
        mine.update(o.strip().lower().rstrip("/") for o in os.environ.get("AUTOAPPLY_DEV_ORIGINS", "").split(",") if o.strip())   # the interface's dev server, when developing
        if origin.lower().rstrip("/") not in mine:
            return "origin"
    elif request.headers.get("sec-fetch-site") in ("cross-site", "same-site"):
        return "cross-site"     # same-site covers another port of this computer
    return ""


class _SocketPrefix:
    """A WebSocket called with the path prefix the program is served under (a proxy that does not strip it): the
    prefix is taken off, as the HTTP middleware below does for requests - which does not see WebSockets."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "websocket":
            root = access.conf()["root_path"]
            if root and (scope["path"] == root or scope["path"].startswith(root + "/")):
                path = scope["path"][len(root):] or "/"
                scope = {**scope, "path": path, "raw_path": path.encode()}
        await self.inner(scope, receive, send)


app.add_middleware(_SocketPrefix)


@app.middleware("http")
async def _portal_cors(request, call_next):  # noqa: ANN001, ANN202
    from fastapi.responses import JSONResponse, Response

    root = access.conf()["root_path"]
    if root and (request.scope["path"] == root or request.scope["path"].startswith(root + "/")):
        # called with the prefix it is served under (a proxy that does not strip it, or the page opened directly)
        request.scope["path"] = request.scope["path"][len(root):] or "/"
        request.scope["raw_path"] = request.scope["path"].encode()
    why = _foreign(request)
    if not why:
        who = access.caller(request.client.host if request.client else "", request.headers)
        path = request.scope["path"]
        portal = path.startswith("/api/import/pdportal") and request.headers.get("origin") == PORTAL_ORIGIN and who["local"]
        if request.method != "OPTIONS" and not portal and not access.allowed(path, request.cookies.get(access.COOKIE), who, request.headers.get(access.LOCAL_HEADER)):
            return JSONResponse({"detail": "请先登录。", "login": True}, status_code=401)
    if why:
        log.warning("refused a request that did not come from this program's own pages (%s): %s %s", why, request.method, request.url.path)
        return JSONResponse({"detail": "This request did not come from AutoApply's own page and was refused."}, status_code=403)
    if request.scope["path"].startswith("/api/import/pdportal") and request.headers.get("origin") == PORTAL_ORIGIN:
        hdr = {"Access-Control-Allow-Origin": PORTAL_ORIGIN, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "content-type",
               "Access-Control-Allow-Private-Network": "true", "Access-Control-Max-Age": "600", "Vary": "Origin"}
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=hdr)
        resp = await call_next(request)
        for k, v in hdr.items():
            resp.headers[k] = v
        return resp
    return await call_next(request)


def _404(x: Any, what: str = "not found") -> Any:
    if x is None:
        raise HTTPException(404, what)
    return x


# --- jobs ------------------------------------------------------------------------------


SOURCE_LABEL = {"pdportal": "UBC PD Portal", "manual": "你手动添加的", "feed": "职位站订阅源", "greenhouse": "Greenhouse 看板", "ashby": "Ashby 看板", "lever": "Lever 看板", "workday": "Workday",
                "amazon": "Amazon 官网", "apple": "Apple 官网", "google": "Google 官网", "microsoft": "Microsoft 官网", "meta": "Meta 官网", "nvidia": "NVIDIA 官网",
                "amd": "AMD 官网", "intel": "Intel 官网", "smartrecruiters": "SmartRecruiters", "page": "雇主招聘页"}


def _job_row(j: Job, a: Application | None) -> dict[str, Any]:
    return {
        "id": j.id, "source": j.source, "source_id": j.source_id, "company": j.company, "title": j.title, "direction": j.direction,
        "score": j.score, "term": j.term, "months": j.months, "salary": j.salary, "work_type": j.work_type or j.location,
        "deadline": j.deadline, "channel": j.channel, "status": j.status, "online": bool(j.online), "exclusion": j.exclusion,
        "location": j.location, "has_brief": bool(j.brief), "has_jd": len(j.jd_text or "") >= 200, "source": j.source, "source_label": SOURCE_LABEL.get(j.source, j.source),
        "posted": j.posted, "first_seen": j.first_seen.date().isoformat() if j.first_seen else "",
        "summary": j.summary, "note": j.note, "apply_url": j.apply_url, "ats": j.ats, "ats_label": humanize.ats_name(j.ats),
        "channel_label": "UBC PD Portal" if (j.ats == "pdportal" or j.channel == "PD Portal") else (humanize.ats_name(j.ats) if j.ats and j.ats != "generic" else "雇主官网"),
        "app_status": a.status if a else None, "app_detail": (humanize.explain(a.last_event)["message"] if a.last_event else "") if a else "", "auto_approved": bool(a.auto_approved) if a else False,
        "submitted_at": a.submitted_at.isoformat() if a and a.submitted_at else None,
        **stages.describe(stages.stage(j.status, bool(j.online), j.deadline or "", a.status if a else None)),
    }


@app.get("/api/jobs")
def list_jobs() -> dict[str, Any]:
    with db.session() as s:
        rows = [{**_job_row(j, j.application), "archived": j.archived_at is not None} for j in s.query(Job).filter(Job.duplicate_of.is_(None)).all()]
        dup: dict[int, int] = {}
        for (main_id,) in s.query(Job.duplicate_of).filter(Job.duplicate_of.isnot(None)):
            dup[main_id] = dup.get(main_id, 0) + 1
        for r in rows:
            r["also_listed"] = dup.get(r["id"], 0)
    counts: dict[str, int] = {}
    from .. import employers as _emp

    _prio = _emp.priority_names()
    for r in rows:
        r["priority"] = _emp.is_priority(r["company"], r["source"], _prio)
        if not r["archived"]:
            counts[r["stage"]] = counts.get(r["stage"], 0) + 1
    return {"jobs": rows, "counts": counts, "groups": [{"key": k, "label": lab} for k, lab in stages.GROUPS],
            "stages": [{"key": k, "label": v[0], "group": v[1], "tone": v[2]} for k, v in stages.STAGES.items()]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int) -> dict[str, Any]:
    with db.session() as s:
        j = _404(s.get(Job, job_id))
        a = j.application
        out = _job_row(j, a)
        out["duplicates"] = [{"id": x.id, "source_label": SOURCE_LABEL.get(x.source, x.source), "title": x.title, "apply_url": x.apply_url, "online": bool(x.online)}
                             for x in s.query(Job).filter(Job.duplicate_of == j.id)]
        out["source_label"] = SOURCE_LABEL.get(j.source, j.source)
        from .. import employers as _emp2

        out["priority"] = _emp2.is_priority(j.company, j.source)
        out["contacts"] = _contacts_for(j.company)
        out["archived"] = j.archived_at is not None
        out["history"] = discover.history(j.id)
        out["posted"] = j.posted
        out.update(jd_text=j.jd_text, brief=j.brief, location=j.location, score_reason=j.score_reason, docs_required=j.docs_required,
                   first_seen=j.first_seen.isoformat() if j.first_seen else None, app_explained=humanize.explain(a.last_event if a else ""),
                   evidence=a.evidence if a else None,
                   drafts=[{"id": d.id, "version": d.version, "review_status": d.review_status} for d in (a.drafts if a else [])])
        return out


@app.post("/api/jobs/bulk")
def bulk_jobs(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """One action on many jobs: skip | restore | draft | score."""
    action, ids = body.get("action"), [int(i) for i in body.get("ids", [])][:500]
    if action in ("archive", "unarchive"):
        with db.session() as s:
            n = 0
            for jid in ids:
                j = s.get(Job, jid)
                if j is not None:
                    j.archived_at = now() if action == "archive" else None
                    n += 1
        return {"done": n, "skipped": 0}
    if action not in ("skip", "restore", "draft", "score"):
        raise HTTPException(400, "unsupported action")
    done, skipped = 0, 0
    todo: list[tuple[int, str]] = []
    with db.session() as s:
        for jid in ids:
            j = s.get(Job, jid)
            if j is None:
                continue
            a = j.application
            sent = a is not None and a.status in ("submitted", "confirmed", "assessment", "interview", "offer", "rejected")
            if action == "skip":
                if sent:
                    skipped += 1
                else:
                    j.status = "skipped"
                    done += 1
            elif action == "restore":
                if j.status == "skipped":
                    j.status = "scored" if j.score is not None else "new"
                    done += 1
                else:
                    skipped += 1
            elif action == "draft":
                if sent or not j.apply_url or not j.online:
                    skipped += 1
                else:
                    todo.append((jid, j.deadline or ""))
            elif action == "score":
                if len((j.jd_text or "").strip()) < 200:
                    skipped += 1
                else:
                    todo.append((jid, ""))
    for jid, deadline in todo:  # enqueue after the session closes (single SQLite writer)
        if action == "draft":
            tasks.enqueue("recon", ref=f"job:{jid}", payload={"job_id": jid}, priority=tasks.deadline_priority(deadline))
        else:
            tasks.enqueue("score", ref=f"job:{jid}", payload={"job_id": jid})
        done += 1
    return {"done": done, "skipped": skipped}


@app.patch("/api/jobs/{job_id}")
def patch_job(job_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    allowed = {"status", "score", "note", "apply_url", "deadline", "company", "title", "jd_text"}
    with db.session() as s:
        j = _404(s.get(Job, job_id))
        for k, v in body.items():
            if k in allowed:
                setattr(j, k, v)
    return {"ok": True}


@app.post("/api/jobs")
def add_job(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    jid = discover.add_manual(body["url"], company=body.get("company", ""), title=body.get("title", ""), jd_text=body.get("jd_text", ""))
    tasks.enqueue("score", ref=f"job:{jid}", payload={"job_id": jid})
    return {"id": jid}


@app.post("/api/jobs/{job_id}/draft")
def make_draft(job_id: int, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    with db.session() as s:
        j = _404(s.get(Job, job_id))
        if not j.apply_url:
            raise HTTPException(400, "job has no application URL")
        prio = tasks.deadline_priority(j.deadline)
    tid = tasks.enqueue("recon", ref=f"job:{job_id}", payload={"job_id": job_id, "instructions": body.get("instructions", "")}, priority=prio)
    return {"task_id": tid}


@app.post("/api/jobs/{job_id}/tailor")
def tailor_job(job_id: int, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Write a tailored résumé for this job now (also used to redo one with instructions)."""
    from .. import tailor

    with db.session() as s:
        j = _404(s.get(Job, job_id))
        if len(j.jd_text or "") < 200:
            raise HTTPException(400, "这个岗位没有岗位说明全文，没法按它调整简历")
    if tailor.base_doc() is None:
        raise HTTPException(400, "还没有上传 Word 版简历。请在材料库里上传，用途选“简历 Word 原稿”")
    return {"task_id": tasks.enqueue("tailor", ref=f"job:{job_id}", payload={"job_id": job_id, "instructions": body.get("instructions", "")}, priority=30)}


def _already_sent(a: Application) -> HTTPException:
    """Someone asks to send, or to mark as sent, an application that is past that. The card they clicked is out of date:
    it is closed with everything else that waited on the application, and the answer says what the state is."""
    from .. import lifecycle

    label = lifecycle.LABEL.get(a.status, a.status)
    lifecycle.settle(a.id)      # its own session; the caller has only read so far
    return HTTPException(409, f"这份申请已经是“{label}”了，不需要再处理；相关的待办已经关掉")


@app.post("/api/jobs/{job_id}/mark-submitted")
def mark_job_submitted(job_id: int) -> dict[str, Any]:
    """The user applied on the employer's site themselves (the program could not operate it). Recorded as the user's word."""
    with db.session() as s:
        j = _404(s.get(Job, job_id))
        a = j.application
        if a is None:
            a = Application(job_id=j.id, channel=j.channel)
            s.add(a)
        elif a.status in ("confirmed", "interview", "assessment", "offer", "rejected"):
            raise _already_sent(a)
        a.status, a.submitted_at = "submitted", a.submitted_at or now()
        a.last_event = "你确认已自己在官网提交；等确认邮件核实"
        a.detail = f"submitted {now().date().isoformat()} (by the user on the employer's site)"
        j.status = "applied"
        s.flush()
        aid = a.id
        for t in s.query(Task).filter(Task.kind == "recon", Task.ref == f"job:{job_id}", Task.status.in_(("waiting_human", "queued"))):
            t.status = "cancelled"
    for kind in ("blocked", "login"):
        notify.close_todos(kind, f"job:{job_id}")
    with db.session() as s:  # older cards for the same posting are filed under the site, not the job
        url = s.get(Job, job_id).apply_url
        for td in s.query(Todo).filter_by(status="open"):
            if url and (td.payload or {}).get("job_url") == url:
                td.status, td.done_at = "done", now()
    for m in db.get_setting("mail.confirm_check_minutes") or []:
        tasks.enqueue_later("mail", ref=f"confirm:{aid}", minutes=float(m), priority=40)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/score")
def score_job(job_id: int) -> dict[str, Any]:
    return {"task_id": tasks.enqueue("score", ref=f"job:{job_id}", payload={"job_id": job_id})}


# --- drafts ----------------------------------------------------------------------------


@app.get("/api/drafts")
def list_drafts(all: bool = False) -> list[dict[str, Any]]:  # noqa: A002
    with db.session() as s:
        q = s.query(Draft).join(Application).join(Job)
        if not all:  # to review, plus approved ones that still have not been submitted
            from sqlalchemy import and_, or_

            q = q.filter(or_(Draft.review_status == "pending",
                             and_(Draft.review_status == "approved", Application.status.in_(("approved", "executing", "ready_to_submit", "failed", "needs_human")))))
        out = []
        for d in q.order_by(Job.deadline, Job.score.desc()).all():
            j = d.application.job
            out.append({"id": d.id, "version": d.version, "review_status": d.review_status, "app_status": d.application.status,
                        "company": j.company, "title": j.title, "score": j.score, "deadline": j.deadline, "ats": j.ats, "ats_label": humanize.ats_name(j.ats),
                        "unresolved": len(d.unresolved), "auto_eligible": bool(d.auto_approve_check.get("eligible")),
                        "sensitive_new": sum(1 for a in d.answers if a.get("sensitive") and not a.get("sensitive_confirmed") and a.get("value") not in ("", None, []))})
        return out


@app.get("/api/drafts/{draft_id}")
def get_draft(draft_id: int) -> dict[str, Any]:
    try:
        d = drafts.get(draft_id)
    except KeyError:
        raise HTTPException(404, "draft not found") from None
    if d["review_status"] == "pending":  # opening a draft picks up files uploaded since it was prepared
        with db.session() as s:
            dr = s.get(Draft, draft_id)
            try:
                changed = bool(dr is not None and drafts.dedupe_ids(dr))   # every question its own id (older drafts of explored forms)
                changed = bool(dr is not None and drafts.refresh_files(dr)) or changed
            except Exception:  # noqa: BLE001 - never let a convenience keep a draft from opening
                log.exception("refreshing the files of draft %s failed", draft_id)
                s.rollback()
                changed = False
        if changed:  # read again once the change is committed
            d = drafts.get(draft_id)
    # display fields: the stored draft keeps the engine's wording
    d["notes_display"] = [humanize.note(n) for n in d["notes"]]
    with db.session() as s:  # what was changed in a tailored résumé, for the review page
        for m in d["materials"]:
            if m.get("kind") == "tailored_resume" and (doc := s.get(Document, m["document_id"])) is not None:
                m["tailor"] = (doc.meta or {}).get("tailor", {})
    from .. import tailor as _tailor

    d["tailor"] = {"available": _tailor.base_doc() is not None, "mode": db.get_setting("tailor.mode"), "has_jd": True}
    d["review_label"] = humanize.REVIEW.get(d["review_status"], d["review_status"])
    d["application"]["status_label"] = humanize.APP_STATUS.get(d["application"]["status"], d["application"]["status"])
    d["application"]["explained"] = humanize.explain(d["application"]["last_event"])
    d["job"]["ats_label"] = humanize.ats_name(d["job"]["ats"])
    for a in d["answers"]:
        a["basis_display"] = humanize.basis(a.get("basis", ""))
    for u in d["unresolved"]:
        u["basis_display"] = humanize.basis(u.get("basis", ""))
    return d


@app.patch("/api/drafts/{draft_id}/answers/{qid:path}")
def edit_answer(draft_id: int, qid: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    with db.session() as s:
        _404(s.get(Draft, draft_id))
    try:
        drafts.edit_answer(draft_id, qid, body.get("value"), save_rule=body.get("save_rule", ""), remember=bool(body.get("remember")))
    except drafts.Locked as e:
        raise HTTPException(409, str(e)) from e
    return get_draft(draft_id)


@app.post("/api/drafts/{draft_id}/scout")
def scout_draft(draft_id: int) -> dict[str, Any]:
    """Read the steps of the form that open only once the earlier ones are filled, by walking it with this draft's
    answers in a hidden window. Nothing is submitted; what the steps ask is added to the draft."""
    with db.session() as s:
        d = _404(s.get(Draft, draft_id))
        if d.review_status != "pending":
            raise HTTPException(400, "只有待审批的草案可以接着读后面的步骤")
        if d.unresolved and not db.get_setting("recon.provisional"):
            raise HTTPException(400, "先回答草案里还没有答案的问题，程序才能带着答案往下走")
        sch = dict(d.schema)
        sch["extra"] = {**(sch.get("extra") or {}), "scouted": 0}      # asked for by hand: the count of automatic rounds starts over
        d.schema = sch
        d.application.status = "recon"
    return {"task_id": tasks.enqueue("scout", ref=f"draft:{draft_id}", payload={"draft_id": draft_id}, priority=10)}


@app.post("/api/drafts/{draft_id}/reanswer")
def reanswer_draft(draft_id: int) -> dict[str, Any]:
    """Ask the AI again for the questions of this draft that have no answer yet."""
    with db.session() as s:
        d = _404(s.get(Draft, draft_id))
        if d.review_status != "pending":
            raise HTTPException(400, "只有待审批的草案可以重新回答")
    return {"task_id": tasks.enqueue("reanswer", ref=f"draft:{draft_id}", payload={"draft_id": draft_id}, priority=10)}


@app.post("/api/drafts/{draft_id}/comment")
def comment_draft(draft_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    with db.session() as s:
        d = _404(s.get(Draft, draft_id))
        d.application.status = "revising"
    tid = tasks.enqueue("revise", ref=f"draft:{draft_id}", payload={"draft_id": draft_id, "comment": body["comment"]}, priority=10)
    return {"task_id": tid}


@app.post("/api/drafts/{draft_id}/approve")
def approve_draft(draft_id: int) -> dict[str, Any]:
    try:
        drafts.approve(draft_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return {"ok": True}


@app.post("/api/drafts/{draft_id}/execute")
def execute_again(draft_id: int) -> dict[str, Any]:
    """Run an approved draft again after a run that ended without submitting (window closed, timeout, failure)."""
    with db.session() as s:
        d = _404(s.get(Draft, draft_id))
        app = d.application
        if d.review_status != "approved":
            raise HTTPException(400, "draft is not approved")
        if app.status in ("submitted", "confirmed", "interview", "assessment", "offer", "rejected"):
            raise _already_sent(app)
        if app.status == "executing":
            raise HTTPException(400, "a run is in progress")
        app_id, deadline = app.id, app.job.deadline
        app.status = "approved"
    return {"task_id": tasks.enqueue("execute", ref=f"application:{app_id}", payload={"draft_id": draft_id}, priority=tasks.deadline_priority(deadline))}


@app.post("/api/applications/{application_id}/mark-submitted")
def mark_submitted(application_id: int) -> dict[str, Any]:
    """The user submitted by hand and the confirmation page was not captured. Recorded as the user's word, not as evidence."""
    with db.session() as s:
        a = _404(s.get(Application, application_id))
        if a.status in ("confirmed", "interview", "assessment", "offer", "rejected"):
            raise _already_sent(a)
        a.status, a.submitted_at = "submitted", a.submitted_at or now()
        a.last_event = "你确认已手动提交；没有保存到确认页，等确认邮件核实"
        a.detail = f"submitted {now().date().isoformat()} (confirmed by the user, no confirmation page captured)"
    for kind in ("failed", "submit"):
        notify.close_todos(kind, f"application:{application_id}")
    for m in db.get_setting("mail.confirm_check_minutes") or []:
        tasks.enqueue_later("mail", ref=f"confirm:{application_id}", minutes=float(m), priority=40)
    return {"ok": True}


@app.post("/api/drafts/{draft_id}/resume")
def draft_resume(draft_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """which = "base": use the résumé as uploaded; "tailored": use the tailored one written for this job."""
    from .. import tailor
    from ..models import Draft

    with db.session() as s:
        d = _404(s.get(Draft, draft_id))
        if (why := drafts.locked(d)):
            raise HTTPException(409, why)
        doc = None
        if body.get("which") == "tailored":
            doc = tailor.existing(d.application.job_id)
            if doc is None:
                raise HTTPException(400, "这个岗位还没有定制简历")
        n = drafts.swap_resume(d, doc)
    return {"changed": n}


@app.post("/api/drafts/approve")
def approve_many(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    done, errors = [], {}
    for i in body.get("ids", []):
        try:
            drafts.approve(int(i))
            done.append(i)
        except ValueError as e:
            errors[str(i)] = str(e)
    return {"approved": done, "errors": errors}


@app.post("/api/drafts/batch")
def drafts_batch(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """One action for several drafts that wait for approval: "withdraw" (not applying after all) or "rebuild" (read the
    form and write the draft again). Approving several is /api/drafts/approve."""
    action = body.get("action")
    if action not in ("withdraw", "rebuild"):
        raise HTTPException(400, "unsupported action")
    done, errors = [], {}
    for i in body.get("ids", []):
        try:
            with db.session() as s:
                d = _404(s.get(Draft, int(i)))
                if d.review_status != "pending":
                    raise ValueError("这份草案已经处理过")
                job_id, deadline = d.application.job_id, d.application.job.deadline
            if action == "withdraw":
                drafts.reject(int(i), withdraw=True)
                for kind in ("answer", "submit", "failed"):
                    notify.close_todos(kind, f"draft:{int(i)}")
            else:
                tasks.enqueue("recon", ref=f"job:{job_id}", payload={"job_id": job_id}, priority=tasks.deadline_priority(deadline))
            done.append(i)
        except (ValueError, HTTPException) as e:
            errors[str(i)] = str(getattr(e, "detail", e))
    return {"done": done, "errors": errors}


@app.post("/api/drafts/{draft_id}/reject")
def reject_draft(draft_id: int, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    drafts.reject(draft_id, withdraw=bool(body.get("withdraw")))
    return {"ok": True}


# --- to-dos, tasks, runs, notifications ---------------------------------------------------


@app.get("/api/todos")
def list_todos(status: str = "open") -> list[dict[str, Any]]:
    with db.session() as s:
        rows = [{"id": t.id, "kind": t.kind, "ref": t.ref, "title": t.title, "body": t.body, "payload": t.payload, "status": t.status,
                 "created_at": t.created_at.isoformat()} for t in s.query(Todo).filter_by(status=status).order_by(Todo.id.desc()).limit(200)]
    from datetime import datetime
    from ..models import Draft

    CAT = {"takeover": "login", "login": "login", "captcha": "login", "answer": "answer", "submit": "submit", "failed": "problem", "blocked": "problem", "config": "problem",
           "mail_unmatched": "answer"}
    with db.session() as s:
        by_url = {j.apply_url: j for j in s.query(Job).filter(Job.apply_url != "")}
        for r in rows:
            p, j = r["payload"] or {}, None
            if p.get("job_id") or r["ref"].startswith("job:"):
                j = s.get(Job, int(p.get("job_id") or r["ref"][4:]))
            elif p.get("draft_id") and (d := s.get(Draft, int(p["draft_id"]))) is not None:
                j = d.application.job
            elif p.get("application_id") and (a := s.get(Application, int(p["application_id"]))) is not None:
                j = a.job
            elif p.get("job_url"):
                j = by_url.get(p["job_url"])
            if r["kind"] == "mail_unmatched":      # the applications the applicant can say it belongs to
                from ..models import MailEvent

                me = s.query(MailEvent).filter_by(message_id=str(p.get("message_id") or r["ref"][5:])).first()
                ids = mail.candidates(me.company_guess) if me is not None else []
                near = bool(ids)
                if not ids:      # the employer was not recognised: every application that was sent, the latest first
                    ids = [a.id for a in s.query(Application).filter(Application.submitted_at.isnot(None)).order_by(Application.submitted_at.desc()).limit(60)]
                r["candidates"] = [{"id": a.id, "label": f"{a.job.company} · {a.job.title}", "status": a.status,
                                    "site_status": ((a.evidence or {}).get("site_status") or {}).get("text", "")}
                                   for a in (s.get(Application, i) for i in ids[:60]) if a is not None]
                r["candidates_near"] = near
            # cards made before "blocked" existed: a sign-in card whose reason is not about signing in
            m = re.match(r"^\w+: (\w+) required", r["body"] or "")
            if r["kind"] in ("takeover", "login") and m and m.group(1) not in ("login", "captcha", "mfa", "account", "verification", "register") and j is not None:
                r["kind"] = "blocked"
                r["title"] = j.company
                r["payload"] = {**p, "job_id": j.id, "url": p.get("job_url") or j.apply_url}
            r["category"] = CAT.get(r["kind"], "info")
            days = None
            if j is not None:
                r["job"] = {"id": j.id, "company": j.company, "title": j.title, "score": j.score, "deadline": j.deadline}
                try:
                    days = (datetime.fromisoformat(j.deadline.replace(" ", "T")) - datetime.now()).days if j.deadline else None
                except ValueError:
                    days = None
            r["days_left"] = days
            # 0 = now (a window is open and waiting), 1 = soon (deadline close), 2 = when you can, 3 = just so you know
            r["urgency"] = 3 if r["category"] == "info" else 0 if r["kind"] == "submit" else 1 if days is not None and days <= 3 else 2
    from .. import browser as _browser

    from .. import sites as _sites
    ready = {k: v["name"] for k, v in _browser.identities().items() if (i := _browser.session_info(f"idp:{k}")) and not i["expired"]}
    for r in rows:  # what the page shows: the employer's name and one plain sentence; raw text stays available as detail
        key = (r["payload"] or {}).get("tenant_key") or (r["ref"][8:] if r["ref"].startswith("account:") else "")
        if r["kind"] in ("takeover", "login") and key and not key.startswith("idp:"):  # ways to sign in that need nothing more from the user than a choice (not for a provider itself)
            offered = _sites.fact(key, "sso_offered")
            r["sso"] = [{"key": p, "name": ready[p]} for p in offered if p in ready]
            r["sso_offered"] = [_browser.identities()[p]["name"] for p in offered if p in _browser.identities() and p not in ready]
        r["site"] = humanize.site(key) if key else None
        r["explained"] = humanize.explain(r["body"])
        r["subject"] = humanize.subject(r["ref"])
    return rows


@app.post("/api/accounts/sign-in-choice")
def sign_in_choice(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """How to sign in to one site from now on: provider = microsoft | google | linkedin, or "" for "register with e-mail instead"."""
    from .. import browser

    key, provider = str(body["tenant_key"]), str(body.get("provider", ""))
    if provider and provider not in browser.identities():
        raise HTTPException(400, "unknown provider")
    auth.choose_sign_in(key, provider)
    return {"resumed": handlers.resume_waiting(f"account:{key}", f"account:{auth.key_for(key)}")}


@app.post("/api/todos/bulk")
def todos_bulk(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Close several to-dos without resuming anything (used for the "just so you know" kind)."""
    with db.session() as s:
        n = 0
        for i in body.get("ids", [])[:500]:
            t = s.get(Todo, int(i))
            if t is not None and t.status == "open":
                t.status, t.done_at = "dismissed", now()
                n += 1
    return {"done": n}


@app.post("/api/todos/{todo_id}/link")
def todo_link(todo_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """The applicant says which application(s) an e-mail is about."""
    ids = [int(i) for i in (body.get("application_ids") or [body.get("application_id")]) if i]
    with db.session() as s:
        t = _404(s.get(Todo, todo_id))
        if t.kind != "mail_unmatched" or not ids:
            raise HTTPException(400, "choose the application this e-mail belongs to")
        if any(s.get(Application, i) is None for i in ids):
            raise HTTPException(404, "no such application")
        mid = str((t.payload or {}).get("message_id") or t.ref[5:])
    return {"updated": mail.link(mid, ids, by="user")}


@app.post("/api/todos/{todo_id}/done")
def todo_done(todo_id: int, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    with db.session() as s:
        t = _404(s.get(Todo, todo_id))
        t.status, t.done_at = body.get("status", "done"), now()
        handled = t.ref
    return {"resumed": handlers.resume_waiting(handled) if body.get("resume", True) and handled else 0}


@app.get("/api/tasks")
def list_tasks(limit: int = 100) -> list[dict[str, Any]]:
    with db.session() as s:
        rows = [{"id": t.id, "kind": t.kind, "status": t.status, "ref": t.ref, "error": t.error, "result": t.result, "attempts": t.attempts,
                 "created_at": t.created_at.isoformat(), "started_at": t.started_at.isoformat() if t.started_at else None,
                 "finished_at": t.finished_at.isoformat() if t.finished_at else None,
                 "browser_stages": [x["stage"] for x in (t.stages or []) if x.get("stage", "").startswith("browser:")]}
                for t in s.query(Task).order_by(Task.id.desc()).limit(limit)]
    for r in rows:
        r["label"] = humanize.TASK.get(r["kind"], r["kind"])
        r["subject"] = humanize.subject(r["ref"])
        r["status_label"], r["tone"] = humanize.TASK_STATUS.get(r["status"], (r["status"], ""))
        r["explained"] = humanize.explain(r["error"])
        r["summary"] = humanize.result_summary(r["kind"], r["status"], r["result"])
    return rows


@app.get("/api/schedule")
def schedule() -> list[dict[str, Any]]:
    rows = tasks.schedule_status()
    for r in rows:
        r["label"] = humanize.TASK.get(r["kind"], r["kind"])
    return rows


@app.post("/api/tasks")
def run_task(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    kind = body["kind"]
    if kind not in ("discover", "score", "mail", "canary"):
        raise HTTPException(400, "unsupported task kind")
    return {"task_id": tasks.enqueue(kind, ref="manual", payload=body.get("payload", {}), priority=20, dedupe=False)}


@app.post("/api/tasks/{task_id}/retry")
def retry_task(task_id: int, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    backend = body.get("browser_backend")
    if backend:
        from .. import browser_policy
        try:
            browser_policy.select(None, override=backend)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        with db.session() as s:
            task = s.get(Task, task_id)
            if task is None:
                raise HTTPException(404, "Task not found")
            if task.status not in ("failed", "waiting_human") or task.kind not in ("recon", "discover", "revise"):
                raise HTTPException(400, "Backend retry is available for stopped discovery and draft-reading tasks")
            task.payload = {**task.payload, "browser_backend": backend}
            task.status, task.error = "queued", ""
        return {"ok": True}
    tasks.retry(task_id)
    return {"ok": True}


@app.get("/api/runs")
def list_runs(limit: int = 100) -> list[dict[str, Any]]:
    with db.session() as s:
        rows = [{"id": r.id, "kind": r.kind, "ref": r.ref, "ats": r.ats, "ok": bool(r.ok), "steps": r.steps, "llm_calls": r.llm_calls,
                 "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "dir": r.dir, "created_at": r.created_at.isoformat(), "task_id": r.task_id}
                for r in s.query(Run).order_by(Run.id.desc()).limit(limit)]
    for r in rows:
        r["subject"] = humanize.subject(r["ref"])
        r["ats_label"] = humanize.ats_name(r["ats"])
    return rows


@app.get("/api/notifications")
def list_notifications(limit: int = 100) -> list[dict[str, Any]]:
    with db.session() as s:
        return [{"id": n.id, "category": n.category, "text": n.text, "sent": bool(n.sent), "error": n.error, "created_at": n.created_at.isoformat()}
                for n in s.query(Notification).order_by(Notification.id.desc()).limit(limit)]


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    with db.session() as s:
        return {
            "pending_drafts": s.query(func.count(Draft.id)).filter(Draft.review_status == "pending").scalar(),
            "open_todos": s.query(func.count(Todo.id)).filter(Todo.status == "open").scalar(),
            "queued_tasks": s.query(func.count(Task.id)).filter(Task.status.in_(("queued", "running"))).scalar(),
            "paused": bool(db.get_setting("schedule.paused")),
            "remote": _open_remote_windows(),
            "drivers": [{"ats": d.ats, "recon_ok": d.recon_ok, "recon_fail": d.recon_fail, "exec_ok": d.exec_ok, "exec_fail": d.exec_fail,
                         "streak": d.consecutive_submits} for d in s.query(DriverStat).all()],
            "mail_recent": [_mail_row(s, m) for m in s.query(MailEvent).filter(MailEvent.category != "other").order_by(MailEvent.id.desc()).limit(10)],
            "stage_counts": _stage_counts(s),
            "weekly": _weekly(s),
            "closing_soon": _closing_soon(s),
            "running": [{"label": humanize.TASK.get(t.kind, t.kind), "subject": humanize.subject(t.ref)} for t in s.query(Task).filter(Task.status == "running")],
            "recent_applications": [{"job_id": a.job_id, "company": a.job.company, "title": a.job.title, "submitted_at": a.submitted_at.isoformat(),
                                     **stages.describe(stages.stage(a.job.status, bool(a.job.online), a.job.deadline or "", a.status))}
                                    for a in s.query(Application).filter(Application.submitted_at.isnot(None)).order_by(Application.submitted_at.desc()).limit(8)],
        }


def _open_remote_windows() -> list[dict[str, Any]]:
    from .. import remote

    return [{"id": w["id"], "title": w["title"], "purpose": w["purpose"]} for w in remote.windows()]


def _mail_row(s: Any, m: MailEvent) -> dict[str, Any]:
    a = s.get(Application, m.application_id) if m.application_id else None
    return {"subject": m.subject, "category": m.category, "summary": m.summary, "label": messages.mail_label(m.category, m.event or "new")[1], "event": m.event or "new",
            "received_at": m.received_at.isoformat() if m.received_at else None, "job": f"{a.job.company} · {a.job.title}" if a else ""}


def _weekly(s: Any, weeks: int = 12) -> list[dict[str, Any]]:
    """Applications sent per week (Monday-based), oldest first, for the last ``weeks`` weeks."""
    from datetime import timedelta

    today = now().date()
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)
    buckets = [0] * weeks
    for (ts,) in s.query(Application.submitted_at).filter(Application.submitted_at.isnot(None)):
        k = (ts.date() - start).days // 7
        if 0 <= k < weeks:
            buckets[k] += 1
    return [{"week": (start + timedelta(weeks=i)).isoformat(), "n": n} for i, n in enumerate(buckets)]


def _closing_soon(s: Any, limit: int = 6) -> list[dict[str, Any]]:
    """Jobs not applied to yet, soonest deadline first (with a link, so they can actually be applied to)."""
    rows = []
    for j in s.query(Job).filter(Job.online == 1, Job.deadline != "", Job.duplicate_of.is_(None)):
        if stages.stage(j.status, True, j.deadline or "", j.application.status if j.application else None) != "not_applied":
            continue
        rows.append({"id": j.id, "company": j.company, "title": j.title, "deadline": j.deadline, "score": j.score, "has_link": bool(j.apply_url),
                     "channel_label": "UBC PD Portal" if j.ats == "pdportal" else (humanize.ats_name(j.ats) if j.ats and j.ats != "generic" else "雇主官网")})
    rows.sort(key=lambda r: (r["deadline"], -(r["score"] or 0)))
    return rows[:limit]


def _stage_counts(s: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for j in s.query(Job).filter(Job.duplicate_of.is_(None), Job.archived_at.is_(None)):
        k = stages.stage(j.status, bool(j.online), j.deadline or "", j.application.status if j.application else None)
        out[k] = out.get(k, 0) + 1
    return out


# --- accounts ----------------------------------------------------------------------------


# --- persona and the first-run guide ---------------------------------------------------------
@app.get("/api/persona")
def get_persona() -> dict[str, Any]:
    p = persona.get()
    with db.session() as s:
        has_profile = "TODO" not in knowledge.read("profile") and len(knowledge.read("profile")) > 400
        docs = s.query(Document).filter(Document.active == 1, Document.kind.in_(("resume_site", "resume_docx", "source"))).count()
    return {"persona": p, "features": persona.features(p), "onboarding_done": bool(db.get_setting("onboarding.done")),
            "stages": [{"key": k, "name": v["name"]} for k, v in persona.STAGES.items()], "fields": [{"key": k, "name": v["name"]} for k, v in persona.FIELDS.items()],
            "has_profile": has_profile, "resume_uploaded": docs > 0, "ai": llm.provider()}


@app.post("/api/persona/suggest")
def persona_suggest(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Intake rules, scoring rules and example titles for a persona. Nothing is saved."""
    return persona.suggest({**persona.EMPTY, **(body.get("persona") or {})})


@app.post("/api/persona/apply")
def persona_apply(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Finish the guide: save the persona and the defaults the user confirmed."""
    p = {**persona.EMPTY, **(body.get("persona") or {})}
    if p["stage"] not in persona.STAGES or p["field"] not in persona.FIELDS:
        raise HTTPException(400, "请先选择求职阶段和领域")
    st = {k: v for k, v in (body.get("settings") or {}).items() if k in config.DEFAULT_SETTINGS and (k.startswith(("intake.", "sources.")) or k in ("queue.min_score_for_draft", "policy.default"))}
    persona.apply(p, st, str(body.get("scoring_md") or ""))
    if body.get("scan"):
        tasks.enqueue("discover", ref="manual", priority=20, dedupe=False)
    return {"ok": True, "features": persona.features()}


@app.put("/api/persona")
def persona_edit(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Change the persona later. Only display and wording follow; settings the user already has are left alone."""
    p = {**persona.get(), **{k: v for k, v in (body.get("persona") or {}).items() if k in persona.EMPTY}}
    db.set_setting("persona", p)
    return {"features": persona.features(p)}


@app.post("/api/persona/restart")
def persona_restart() -> dict[str, Any]:
    db.set_setting("onboarding.done", False)
    return {"ok": True}


@app.post("/api/persona/skip")
def persona_skip() -> dict[str, Any]:
    db.set_setting("onboarding.done", True)
    return {"ok": True}


# --- prompts ---------------------------------------------------------------------------------
@app.get("/api/prompts")
def list_prompts() -> list[dict[str, Any]]:
    return prompts.listing()


@app.put("/api/prompts/{key}")
def save_prompt(key: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if key not in prompts.SPECS:
        raise HTTPException(404, "unknown prompt")
    try:
        prompts.save(key, str(body.get("body", "")), note=str(body.get("note", ""))[:200])
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return {"ok": True}


@app.post("/api/prompts/{key}/reset")
def reset_prompt(key: str) -> dict[str, Any]:
    if key not in prompts.SPECS:
        raise HTTPException(404, "unknown prompt")
    prompts.reset(key)
    return {"ok": True}


# --- network ---------------------------------------------------------------------------------
@app.get("/api/system")
def system_state() -> dict[str, Any]:
    """What this computer offers that the program depends on."""
    import platform

    from .. import convert

    from .. import backup

    return {"platform": platform.system(), "pdf": convert.available(), "version": backup.version(), "data_dir": str(config.DATA), "knowledge_dir": str(config.KNOWLEDGE)}


@app.post("/api/system/export")
def system_export(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Everything the user has put into the program, as one zip (kept in data/exports and offered as a download)."""
    from .. import backup

    return backup.export(sessions=bool(body.get("sessions")))


@app.get("/api/system/export/{name}")
def system_export_download(name: str) -> FileResponse:
    from .. import backup

    try:
        return FileResponse(backup.path_of(name), filename=name, media_type="application/zip")
    except FileNotFoundError as e:
        raise HTTPException(404, "没有这个导出文件") from e


@app.get("/api/system/update")
def system_update() -> dict[str, Any]:
    """Looks at the releases of the publishing repository. Asked for by the user; nothing is downloaded or installed."""
    from .. import backup

    return backup.check_update(str(db.get_setting("update.repo") or ""))


@app.get("/api/proxy")
def proxy_state() -> dict[str, Any]:
    return net.describe()


@app.post("/api/proxy/test")
def proxy_test() -> dict[str, Any]:
    """Try the saved setting against a few sites the program depends on."""
    return {**net.describe(), "results": net.test()}


# --- the login to this program, and where it listens ---------------------------------------------
# where this server was started (the settings may have been changed since: that takes a restart)
_LISTENING = {"host": os.environ.get("AUTOAPPLY_LISTENING_HOST") or access.conf()["host"], "port": int(os.environ.get("AUTOAPPLY_LISTENING_PORT") or access.conf()["port"])}


def _who(request) -> dict[str, Any]:  # noqa: ANN001
    return access.caller(request.client.host if request.client else "", request.headers)


def _signed_in(request) -> bool:  # noqa: ANN001
    return not access.enforced() or access.session_ok(request.cookies.get(access.COOKIE))


def _start_session(request, response) -> None:  # noqa: ANN001
    c = access.conf()
    response.set_cookie(access.COOKIE, access.new_session(), max_age=int(c["session_days"]) * 86400, httponly=True, samesite="lax",
                        secure=_who(request)["https"], path=(c["root_path"] or "") + "/")


@app.get("/api/auth/state")
def auth_state(request: Request) -> dict[str, Any]:
    """What the page needs before anyone has signed in: is there an account yet, is this visitor signed in."""
    who = _who(request)
    return {"required": access.enforced(), "setup": not access.has_admin(), "can_setup": who["local"], "signed_in": _signed_in(request) and (access.has_admin() or not access.enforced()),
            "user": access.admin_name() if _signed_in(request) else "", "locked": access.locked_for(), "lang": db.get_setting("ui.lang") or "zh"}


@app.post("/api/auth/setup")
def auth_setup(request: Request, response: Response, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """The first visit, on the computer itself: the user chooses the administrator's name and password."""
    if access.has_admin():
        raise HTTPException(409, "管理员账号已经设置过了。忘记密码的话，在这台电脑的托盘图标里选“重置管理员密码”。")
    if not _who(request)["local"]:
        raise HTTPException(403, "第一次设置管理员账号要在运行 AutoApply 的那台电脑上打开页面完成。")
    try:
        access.set_admin(str(body.get("user") or ""), str(body.get("password") or ""))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    _start_session(request, response)
    return {"ok": True}


@app.post("/api/auth/login")
def auth_login(request: Request, response: Response, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    wait = access.locked_for()
    if wait:
        raise HTTPException(429, f"输错的次数太多了，请 {wait // 60 + 1} 分钟后再试。")
    ok = access.verify(str(body.get("user") or ""), str(body.get("password") or ""))
    access.note_login(ok)
    if not ok:
        log.warning("a login to this program was refused (from %s)", _who(request)["ip"])
        raise HTTPException(401, "用户名或密码不对。")
    _start_session(request, response)
    return {"ok": True}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    if body.get("everywhere") and _signed_in(request):
        access.end_all_sessions()
    else:
        access.end_session(request.cookies.get(access.COOKIE))
    response.delete_cookie(access.COOKIE, path=(access.conf()["root_path"] or "") + "/")
    return {"ok": True}


@app.post("/api/auth/password")
def auth_password(request: Request, response: Response, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """A new password (and, if wanted, a new name). Every other device is signed out; this one stays in."""
    if not _signed_in(request):
        raise HTTPException(401, "请先登录。")
    if not access.verify(access.admin_name(), str(body.get("current") or "")):
        raise HTTPException(400, "现在的密码不对。")
    try:
        access.set_admin(str(body.get("user") or access.admin_name()), str(body.get("password") or ""))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    _start_session(request, response)
    return {"ok": True}


@app.get("/api/access")
def get_access(request: Request) -> dict[str, Any]:
    c = access.conf()
    running = _LISTENING
    return {"settings": c, "running": running, "restart_needed": (running["host"], running["port"]) != (c["host"], c["port"]),
            "exposed": access.exposed(c), "https": _who(request)["https"], "user": access.admin_name(), "addresses": sorted(_own_addresses("0.0.0.0"))}  # noqa: S104


@app.put("/api/access")
def put_access(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return {"settings": access.save_conf(body.get("settings") or {})}
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e)) from e


# --- sign-in providers -----------------------------------------------------------------------
@app.get("/api/identities")
def list_identities() -> list[dict[str, Any]]:
    return auth.identities()


@app.post("/api/identities/{provider}/login")
def identity_login(provider: str) -> dict[str, Any]:
    from .. import browser

    if provider not in browser.identities():
        raise HTTPException(404, "unknown provider")

    def run() -> None:
        name = browser.identities()[provider]["name"]
        try:
            res = auth.identity_login(provider)
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "reason": type(e).__name__}
        _IDP_STATE[provider] = "" if res.get("ok") else res.get("reason", "没有成功")
        if res.get("ok"):
            handlers.resume_waiting(f"account:idp:{provider}")
            notify.send("task_result", messages.session_saved(f"{name} 账号", credentials=False), ref=f"account:idp:{provider}")

    _IDP_STATE[provider] = "trying"
    threading.Thread(target=run, daemon=True, name="identity").start()
    return {"started": True}


@app.get("/api/identities/state")
def identity_state() -> dict[str, str]:
    return dict(_IDP_STATE)


@app.delete("/api/identities/{provider}")
def identity_forget(provider: str) -> dict[str, Any]:
    from .. import browser

    browser.clear_state(f"idp:{provider}")
    _IDP_STATE.pop(provider, None)
    return {"ok": True}


_IDP_STATE: dict[str, str] = {}


@app.get("/api/accounts")
def accounts() -> list[dict[str, Any]]:
    rows = auth.list_accounts()
    for r in rows:
        r["site"] = humanize.site(r["tenant_key"])
        r["explained"] = humanize.explain(r["last_error"])
    return rows


@app.put("/api/accounts/{tenant_key}")
def save_account(tenant_key: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    auth.upsert_account(tenant_key, email=body.get("login_email"), password=body.get("password") or None, host=body.get("host", ""), created_by="manual",
                        status="unknown" if body.get("password") else None)
    with db.session() as s:  # a new password clears the failure counter
        from ..models import Account

        a = s.get(Account, tenant_key)
        if a and body.get("password"):
            a.fail_count = 0
    return {"ok": True}


@app.delete("/api/accounts/{tenant_key}")
def remove_account(tenant_key: str) -> dict[str, Any]:
    auth.delete_account(tenant_key)
    return {"ok": True}


@app.post("/api/accounts/{tenant_key}/reveal")
def reveal(tenant_key: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if body.get("confirm") != tenant_key:
        raise HTTPException(400, "confirmation text must equal the tenant key")
    return {"password": secrets.get_password(tenant_key)}


@app.post("/api/accounts/import-chrome-csv")
async def import_csv(file: UploadFile = File(...)) -> dict[str, Any]:
    content = (await file.read()).decode("utf-8-sig", errors="ignore")
    return auth.import_chrome_csv(content)


@app.get("/api/accounts/sessions")
def carried_sessions() -> list[dict[str, Any]]:
    """The saved sign-ins that can be carried to another computer: site accounts and sign-in providers."""
    from .. import browser as _browser

    out = []
    for r in auth.list_accounts():
        if _browser.session_info(r["tenant_key"]):
            out.append({"tenant_key": r["tenant_key"], "name": humanize.site(r["tenant_key"])["name"]})
    for key, spec in _browser.identities().items():
        if _browser.session_info(f"idp:{key}"):
            out.append({"tenant_key": f"idp:{key}", "name": spec["name"]})
    return out


@app.post("/api/accounts/session/export")
def export_session(body: dict[str, Any] = Body(...)):
    """One site's saved sign-in as a file encrypted with the passphrase. Not written anywhere here: it is the download."""
    from .. import transfer

    tenant = str(body.get("tenant_key") or "")
    with db.session() as s:
        from ..models import Account

        a = s.get(Account, tenant)
        host = a.host if a else ""
    try:
        blob = transfer.export(tenant, str(body.get("passphrase") or ""), host=host or "")
    except transfer.Refused as e:
        raise HTTPException(400, str(e)) from e
    name = "".join(c if c.isalnum() or c in "-." else "-" for c in tenant) + ".aasession"
    return Response(content=blob, media_type="application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@app.post("/api/accounts/session/import")
async def import_session(file: UploadFile = File(...), passphrase: str = Form("")) -> dict[str, Any]:
    from .. import transfer

    try:
        got = transfer.put(await file.read(), passphrase)
    except transfer.Refused as e:
        raise HTTPException(400, str(e)) from e
    return {**got, "name": humanize.site(got["tenant"])["name"] if not got["tenant"].startswith("idp:") else got["tenant"][4:], "resumed": handlers.resume_waiting(f"account:{got['tenant']}")}


@app.post("/api/accounts/allow-register")
def allow_register(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """The user has no account on this site: let the agent register, and resume the tasks that were waiting."""
    auth.allow_register(body["tenant_key"])
    return {"resumed": handlers.resume_waiting(f"account:{body['tenant_key']}", f"account:{auth.key_for(body['tenant_key'])}")}


@app.post("/api/accounts/takeover")
def takeover(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Open a visible browser window for the user to sign in. Runs in a thread; poll /api/accounts."""
    key, url = body["tenant_key"], body["url"]
    ats = key.split(":")[0]
    drv = registry.get(ats)
    ref = registry.detect(body.get("job_url") or url) if drv else None
    if ref is not None and ref.ats != ats:
        ref = None

    def run() -> None:
        try:
            res = auth.takeover(key, url, driver=drv if ref else None, ref=ref, save_credentials=bool(body.get("save_credentials", True)))
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "reason": f"登录窗口出错了：{type(e).__name__}"}
        with db.session() as s:  # tell the user on the card what happened to the window they opened
            for td in s.query(Todo).filter_by(ref=f"account:{key}", status="open"):
                td.payload = {**(td.payload or {}), "last_try": "" if res.get("ok") else res.get("reason", "没有成功"), "trying": False}
        if res.get("ok"):
            handlers.resume_waiting(f"account:{key}", f"account:{auth.key_for(key)}")
            notify.send("task_result", messages.session_saved(key, credentials=bool(res.get("credentials_saved"))), ref=f"account:{key}")

    with db.session() as s:
        for td in s.query(Todo).filter_by(ref=f"account:{key}", status="open"):
            td.payload = {**(td.payload or {}), "trying": True, "last_try": ""}
    threading.Thread(target=run, daemon=True, name="takeover").start()
    return {"started": True}


# --- profile & documents -----------------------------------------------------------------


@app.get("/api/profile")
def get_profile(doc: str = "profile") -> dict[str, Any]:
    md = knowledge.read(doc)
    return {"markdown": md, "sections": knowledge.split_sections(md), "versions": knowledge.versions(doc), "agent_added": knowledge.agent_added() if doc == "profile" else []}


@app.put("/api/profile")
def put_profile(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    doc = body.get("doc", "profile")
    md = body["markdown"] if "markdown" in body else knowledge.join_sections(body["sections"])
    vid = knowledge.write(doc, md, source="user", note=body.get("note", ""))
    return {"version": vid}


@app.get("/api/portals")
def get_portals() -> dict[str, Any]:
    """School career portals and how far each one is supported (portals.json)."""
    import json as _json
    from pathlib import Path as _Path

    rows = _json.loads((_Path(__file__).parents[1] / "portals.json").read_text(encoding="utf-8"))["portals"]
    return {"portals": rows}


@app.get("/api/regions")
def get_regions() -> dict[str, Any]:
    """What forms in the user's countries ask on top of a résumé (region packs)."""
    from .. import persona, regions

    countries = persona.get().get("countries") or db.get_setting("intake.countries") or []
    return {"countries": countries, "packs": regions.view(countries, str(db.get_setting("ui.lang") or "zh")), "available": sorted(regions.packs())}


@app.get("/api/profile/structured")
def get_profile_structured() -> dict[str, Any]:
    from .. import persona

    asks = " ".join(persona.profile_asks()).lower()
    return {**knowledge.structured(), "suggested": {"compensation": "salary" in asks or "compensation" in asks or "notice" in asks, "referees": "referee" in asks}}


@app.put("/api/profile/structured")
def put_profile_structured(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return {"version": knowledge.set_structured(body)}


@app.post("/api/profile/restore/{version_id}")
def restore_profile(version_id: int) -> dict[str, Any]:
    return {"markdown": knowledge.restore(version_id)}


@app.post("/api/profile/rule")
def add_rule(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return {"version": knowledge.append_rule(body["text"], source=body.get("source", "user"), section=body.get("section", "Rules"))}


@app.post("/api/profile/remove-line")
def remove_line(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return {"removed": knowledge.remove_line(body["fragment"])}


@app.post("/api/profile/init")
def init_profile(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    from .. import profile_init

    try:
        return {"draft": profile_init.draft_profile(body.get("notes", "")), "current": knowledge.read("profile")}
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except llm.LLMError as e:
        raise HTTPException(502, str(e)) from None


DOC_KINDS = {"resume_docx", "resume_site", "resume_portal", "transcript", "summary_sheet", "cl_template", "cl_example", "portfolio", "certificate", "reference", "source", "other",
             "research_statement", "teaching_statement", "publications", "writing_sample", "diversity_statement"}
SINGLETON = {"resume_docx", "resume_site", "resume_portal", "transcript", "summary_sheet", "cl_template"}


@app.get("/api/documents")
def list_documents() -> list[dict[str, Any]]:
    with db.session() as s:
        rows = []
        for d in s.query(Document).order_by(Document.id.desc()).limit(300):
            p = Path(d.path)
            job = s.get(Job, d.job_id) if d.job_id else None
            jstage = stages.describe(stages.stage(job.status, bool(job.online), job.deadline or "", job.application.status if job.application else None)) if job else {}
            rows.append({"id": d.id, "kind": d.kind, "name": d.name, "active": bool(d.active), "job_id": d.job_id, "created_at": d.created_at.isoformat(),
                         "job_stage": jstage.get("stage_label", ""), "job_tone": jstage.get("stage_tone", ""), "job_archived": bool(job and job.archived_at),
                         "job_sent": bool(job and job.application and (job.application.submitted_at is not None or job.application.status in mail.RANK)),
                         "problems": (d.meta or {}).get("problems", []), "ext": p.suffix.lower().lstrip("."), "size": p.stat().st_size if p.exists() else 0,
                         "missing": not p.exists(), "pages": (d.meta or {}).get("pages"), "for_job": f"{job.company} · {job.title}" if job else "",
                         "has_docx": bool((d.meta or {}).get("docx"))})
        return rows


@app.post("/api/documents")
async def upload_document(kind: str = Form(...), file: UploadFile = File(...)) -> dict[str, Any]:
    if kind not in DOC_KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(DOC_KINDS)}")
    name = Path(file.filename or "upload").name
    dest_dir = config.FILES / kind
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    with db.session() as s:
        if kind in SINGLETON:  # a new upload replaces the active one
            for old in s.query(Document).filter_by(kind=kind, active=1):
                old.active = 0
        d = Document(kind=kind, name=name, path=str(dest))
        s.add(d)
        s.flush()
        return {"id": d.id, "name": name}


@app.get("/api/documents/{doc_id}/file")
def document_file(doc_id: int):
    with db.session() as s:
        d = _404(s.get(Document, doc_id))
        path, name = d.path, d.name
    if not Path(path).exists():
        raise HTTPException(404, "file missing on disk")
    return FileResponse(path, filename=name, content_disposition_type="inline")


@app.get("/api/documents/{doc_id}/preview")
def document_preview(doc_id: int):
    """Something the browser can show in a frame: the PDF itself, a PDF made from a Word file, or plain text."""
    with db.session() as s:
        d = _404(s.get(Document, doc_id))
        path, name = Path(d.path), d.name
    if not path.exists():
        raise HTTPException(404, "file missing on disk")
    ext = path.suffix.lower()
    if ext == ".pdf":
        return FileResponse(path, media_type="application/pdf", content_disposition_type="inline", filename=name)
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return FileResponse(path, content_disposition_type="inline", filename=name)
    if ext in (".docx", ".doc"):
        out = config.DATA / "tmp" / "preview" / f"{doc_id}_{int(path.stat().st_mtime)}.pdf"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(ext)
            shutil.copyfile(path, tmp)  # convert a copy: Word writes the PDF next to its input
            from .. import convert

            try:
                convert.docx_to_pdf(tmp, timeout=120)
            except Exception:  # noqa: BLE001 - no converter or a failed export: fall through to the text view below
                pass
            tmp.unlink(missing_ok=True)
        if out.exists():
            return FileResponse(out, media_type="application/pdf", content_disposition_type="inline", filename=Path(name).stem + ".pdf")
    from fastapi.responses import PlainTextResponse

    from ..materials import _doc_text

    try:
        return PlainTextResponse(_doc_text(str(path))[:200000] or "（这个文件没有可以显示的文字内容）")
    except Exception:  # noqa: BLE001
        raise HTTPException(415, "这种文件不能在网页里预览，请下载后查看") from None


@app.get("/api/documents/{doc_id}/bytes")
def document_bytes(doc_id: int):
    """The previewable PDF as plain bytes for the in-page viewer. Served as a generic binary on purpose:
    download managers hook responses that look like a PDF file and pull them out of the page."""
    from fastapi.responses import Response

    resp = document_preview(doc_id)
    path = getattr(resp, "path", None)
    if path is None or not str(path).lower().endswith(".pdf"):
        raise HTTPException(415, "not a PDF")
    return Response(Path(path).read_bytes(), media_type="application/octet-stream", headers={"Cache-Control": "no-store"})


@app.post("/api/documents/bulk")
def bulk_documents(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """stop | delete several files at once."""
    action, ids = body.get("action"), [int(i) for i in body.get("ids", [])][:300]
    if action not in ("stop", "delete"):
        raise HTTPException(400, "unsupported action")
    for i in ids:
        try:
            delete_document(i, permanent=action == "delete")
        except HTTPException:
            pass
    return {"done": len(ids)}


@app.patch("/api/documents/{doc_id}")
def patch_document(doc_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Rename, switch on/off, or change what a file is used as."""
    with db.session() as s:
        d = _404(s.get(Document, doc_id))
        if "name" in body:
            name = Path(str(body["name"]).strip()).name
            if not name:
                raise HTTPException(400, "name is empty")
            if Path(name).suffix.lower() != Path(d.name).suffix.lower():
                name += Path(d.name).suffix  # the extension is part of the file, not of its label
            d.name = name
        if "kind" in body:
            if body["kind"] not in DOC_KINDS or d.kind == "cover_letter":
                raise HTTPException(400, "unsupported kind")
            d.kind = body["kind"]
        if "active" in body:
            d.active = int(bool(body["active"]))
        if d.active and d.kind in SINGLETON:  # one file in use per kind
            for other in s.query(Document).filter(Document.kind == d.kind, Document.active == 1, Document.id != d.id):
                other.active = 0
    return {"ok": True}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: int, permanent: bool = False) -> dict[str, Any]:
    """Stop using a file; with ``permanent`` also remove the record and the file itself."""
    with db.session() as s:
        d = _404(s.get(Document, doc_id))
        d.active = 0
        if permanent:
            path = Path(d.path)
            s.delete(d)
            try:
                if path.exists() and config.DATA in path.parents:
                    path.unlink()
            except OSError:
                pass
    return {"ok": True}


# --- settings ------------------------------------------------------------------------------

SECRET_FIELDS = {"anthropic_api_key": secrets.ANTHROPIC_KEY, "telegram_bot_token": secrets.TELEGRAM_TOKEN,
                 "claude_oauth_token": secrets.CLAUDE_OAUTH_TOKEN, "proxy_password": net.PROXY_PASSWORD, "imap_password": "imap_password"}


@app.get("/api/import/pdportal/known")
def pdportal_known() -> dict[str, Any]:
    """Posting ids whose details are already stored (the importer skips re-reading those)."""
    with db.session() as s:
        # "known" = has the full description; one-line rows from the old spreadsheet get re-read
        return {"ids": [j.source_id for j in s.query(Job).filter(Job.source == "pdportal") if len(j.jd_text or "") >= 200]}


@app.post("/api/import/pdportal")
def pdportal_import(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Postings read by the importer script in the user's browser. ``details`` are raw detail-page texts;
    the final call carries ``all_ids`` (everything listed on the portal) so missing ones go offline."""
    from ..sources import pdportal

    rows = [pdportal.parse_detail(str(d["id"]), str(d["text"])) for d in (body.get("details") or [])[:50] if d.get("text")]
    out = discover.upsert(rows, source="pdportal", complete=False) if rows else {"new": 0, "offline": 0}
    if body.get("done"):
        ids = [str(i) for i in body.get("all_ids") or []]
        if ids:
            fin = discover.upsert([{"source_id": i} for i in ids], source="pdportal", complete=True)
            out = {"new": fin["new"], "offline": fin["offline"], "listed": len(ids)}
        dups = discover.link_duplicates()
        tasks.enqueue("score", ref="unscored", priority=150)
        with db.session() as s:
            total_new = s.query(func.count(Job.id)).filter(Job.source == "pdportal", Job.status == "new").scalar()
        out.update(duplicates=dups, new=total_new)
        notify.send("task_result", messages.Card("📥", "PD Portal 岗位已导入", fields=[("门户上", f"{len(ids)} 个"), ("待评分的新岗位", f"{total_new} 个"), ("下线", str(out.get("offline", 0)))],
                                                 path="/jobs", link="查看岗位"), ref="discover")
    return out


BRIDGE_HTML = r"""<!doctype html><meta charset="utf-8"><title>AutoApply 导入</title>
<body style="font:14px/1.6 system-ui,sans-serif;margin:24px;color:#14233b">
<b>AutoApply 正在接收 PD Portal 的岗位</b><p id="s">等待门户页面发来数据…请不要关闭这个窗口，完成后会自动关闭。</p>
<script>
const PORTAL = "%s"; let n = 0;
window.addEventListener("message", async (ev) => {
  if (ev.origin !== PORTAL || !ev.data || !ev.data.aa) return;
  const { id, path, body } = ev.data;
  const reply = (m) => ev.source.postMessage({ aa: 1, id, ...m }, PORTAL);
  if (path === "ping") return reply({ result: "pong" });
  if (!/^\/api\/import\/pdportal(\/known)?$/.test(path)) return reply({ error: "not allowed" });
  try {
    const r = await fetch(path, body == null ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error("AutoApply 返回 " + r.status);
    if (body && body.details) { n += body.details.length; document.getElementById("s").textContent = "已收到 " + n + " 个新岗位的详情…"; }
    reply({ result: await r.json() });
  } catch (e) { reply({ error: String(e && e.message || e) }); }
});
</script>"""


@app.get("/pdportal-bridge")
def pdportal_bridge():
    """A tiny same-origin window the importer can talk to with postMessage when the browser refuses
    direct requests from the portal's page to this computer."""
    from fastapi.responses import HTMLResponse

    return HTMLResponse(BRIDGE_HTML % PORTAL_ORIGIN)


@app.get("/pdportal-import.js")
def pdportal_script():
    from fastapi.responses import Response

    code = (Path(__file__).resolve().parents[1] / "sources" / "pdportal_import.js").read_text(encoding="utf-8")
    return Response(code.replace("__APP__", str(db.get_setting("app.base_url")).rstrip("/")), media_type="text/javascript")


@app.get("/api/import/pdportal/bookmarklet")
def pdportal_bookmarklet() -> dict[str, Any]:
    """The importer as a bookmarklet (the whole script inline, so it does not depend on loading a script from another origin)."""
    from urllib.parse import quote

    code = (Path(__file__).resolve().parents[1] / "sources" / "pdportal_import.js").read_text(encoding="utf-8")
    code = code.replace("__APP__", str(db.get_setting("app.base_url")).rstrip("/"))
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    code = "\n".join(ln.strip() for ln in code.splitlines() if ln.strip())
    return {"href": "javascript:" + quote(code, safe="()[]{}=;:,.!*'~-_+/&|<>?$ "), "code": code}


@app.get("/api/analytics")
def analytics(days: int = 0, start: str = "", end: str = "") -> dict[str, Any]:
    """What came of the applications sent in the window: the last ``days`` days, or local dates ``start``..``end``
    (inclusive), or everything. The other two views of the analysis page are below."""
    from .. import analytics as an

    return an.applications(an.window(days, start, end))


@app.get("/api/analytics/automation")
def analytics_automation(days: int = 0, start: str = "", end: str = "", kind: str = "") -> dict[str, Any]:
    """What the program's tasks did: how they ended, how long they took, where they failed, what they cost in AI."""
    from .. import analytics as an

    return an.automation(an.window(days, start, end), kind=kind)


@app.get("/api/analytics/automation/runs")
def analytics_runs(days: int = 0, start: str = "", end: str = "", kind: str = "", outcome: str = "", offset: int = 0, limit: int = 15) -> dict[str, Any]:
    """The runs of the window, newest first, a page at a time."""
    from .. import analytics as an

    return an.runs(an.window(days, start, end), kind=kind, outcome=outcome, offset=offset, limit=limit)


@app.get("/api/analytics/timing")
def analytics_timing(days: int = 0, start: str = "", end: str = "", ats: str = "") -> dict[str, Any]:
    """Where the time of the form-filling runs went, per system over time, and what the program learned from it."""
    from .. import analytics as an

    return an.timing_overview(an.window(days, start, end), ats=ats)


@app.get("/api/analytics/timing/runs/{run_id}")
def analytics_timing_run(run_id: int) -> dict[str, Any]:
    from .. import analytics as an

    try:
        return an.timing_run(run_id)
    except KeyError:
        raise HTTPException(404, "这次运行没有耗时记录。") from None


@app.get("/api/learned/{rev_id}")
def learned_one(rev_id: str) -> dict[str, Any]:
    """One thing the program learned: what it is, why, its text (recipe or code), and how its trials went."""
    from .. import learned

    rev = learned.get(rev_id)
    if rev is None:
        raise HTTPException(404, "没有这一项。")
    return {**rev, "content": learned.content(rev)}


@app.get("/api/sites")
def sites_list() -> list[dict[str, Any]]:
    """Every site the program knows something about, with how much: notes, steps of its form, what was learned for it."""
    from .. import sites

    rows = sites.listing()
    for r in rows:
        r["employer"] = humanize.site(r["key"])["name"] if ":" in r["key"] and not r["key"].startswith("idp:") else ""
    return rows


@app.get("/api/sites/{key:path}")
def site_one(key: str) -> dict[str, Any]:
    """Everything the program knows about one site."""
    from .. import sites

    return sites.about(key)


@app.post("/api/sites/{key:path}/forget")
def site_forget(key: str) -> dict[str, Any]:
    """Drop what was learned about working one site (notes, steps; its revisions are taken out). Its sign-in is kept."""
    from .. import sites

    return sites.forget(key)


@app.post("/api/learned/{rev_id}/share")
def learned_share(rev_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """The applicant's answer to "report this driver to the project?": once, always, skip, never. For once and always
    the answer holds the address of GitHub's new-issue page with the text filled in - the applicant opens and submits it."""
    from .. import share

    try:
        return share.decide(rev_id, str(body.get("choice") or ""))
    except KeyError:
        raise HTTPException(404, "没有这一项。") from None
    except ValueError:
        raise HTTPException(400, "不认识的选择。") from None


@app.post("/api/learned/{rev_id}/{action}")
def learned_decide(rev_id: str, action: str) -> dict[str, Any]:
    """The applicant's word on something the program learned: approve, reject, revert, retry."""
    from .. import learned

    try:
        return learned.decide(rev_id, action)
    except KeyError:
        raise HTTPException(404, "没有这一项。") from None
    except learned.Refused as e:
        raise HTTPException(409, str(e)) from e


@app.get("/api/analytics/ai")
def analytics_ai(days: int = 0, start: str = "", end: str = "", group: str = "model", bucket: str = "", provider: str = "", model: str = "", feature: str = "") -> dict[str, Any]:
    """What the model calls used and cost: by time, model, service and feature, per result, and what failures cost."""
    from .. import analytics as an

    return an.ai(an.window(days, start, end), group=group, bucket=bucket, provider=provider, model=model, feature=feature)


@app.get("/api/analytics/ai/requests")
def analytics_ai_requests(task_id: int) -> dict[str, Any]:
    """The model requests of one task: from a total down to what it is made of."""
    from .. import analytics as an

    return {"requests": an.requests_of(task_id=task_id)}


@app.put("/api/analytics/ai/prices")
def analytics_ai_prices(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """The user's own prices (US dollars per million tokens) for models the built-in list does not cover. Saving them
    estimates again every request whose cost comes from a price list; a cost a service reported itself is left alone."""
    from .. import metering

    out = []
    for p in (body.get("prices") or [])[:100]:
        model = str((p or {}).get("model") or "").strip()
        try:
            row = {"model": model, "provider": str(p.get("provider") or ""), "input": float(p["input"]), "output": float(p["output"])}
            for k in ("cache_read", "cache_write"):
                if p.get(k) not in (None, ""):
                    row[k] = float(p[k])
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(400, f"「{model or '?'}」的价格不完整：输入和输出价格都要填数字") from e
        if not model or min(v for k, v in row.items() if k not in ("model", "provider")) < 0:
            raise HTTPException(400, "模型名不能为空，价格不能是负数")
        out.append(row)
    db.set_setting("llm.prices", out)
    return {"ok": True, "repriced": metering.reprice()}


@app.get("/api/sources/last-scan")
def last_scan() -> dict[str, Any]:
    """What the most recent scan read from each source and how much of it the intake rules kept."""
    from .. import intake as intake_mod

    with db.session() as s:
        t = s.query(Task).filter(Task.kind == "discover", Task.status == "done").order_by(Task.id.desc()).first()
        if t is None:
            return {"at": None, "sources": []}
        res, at = dict(t.result or {}), t.finished_at.isoformat() if t.finished_at else None
    rows = []
    names = set(res.get("sources", {})) | set(res.get("errors", {})) | set(res.get("intake", {}))
    for name in sorted(names):
        key, _, sub_name = name.partition(":")
        st, ik, err = res.get("sources", {}).get(name, {}), res.get("intake", {}).get(name, {}), res.get("errors", {}).get(name, "")
        rows.append({"name": SOURCE_LABEL.get(key, key) + (f"（{sub_name}）" if sub_name else ""), "read": ik.get("read", st.get("seen", 0)), "kept": ik.get("kept", st.get("seen", 0)),
                     "new": st.get("new", 0), "dropped": {intake_mod.REASONS.get(k, k): v for k, v in (ik.get("dropped") or {}).items()},
                     "error": humanize.explain(err)["message"] if err else "", "error_detail": err})
    return {"at": at, "sources": rows, "duplicates": res.get("duplicates", 0)}


@app.post("/api/sources/try-rules")
def try_rules(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Apply intake rules (as typed in the form, not yet saved) to a list of example titles."""
    from .. import intake as intake_mod

    r = {**intake_mod.rules(), **{k: v for k, v in (body.get("rules") or {}).items() if k in ("title_any", "title_role_any", "title_none", "countries", "max_age_days")}, "enabled": True}
    out = []
    for line in (body.get("examples") or [])[:60]:
        title, _, loc = str(line).partition("|")
        why = intake_mod.check({"source": "x", "title": title.strip(), "location": loc.strip()}, r)
        out.append({"title": title.strip(), "location": loc.strip(), "kept": not why, "why": intake_mod.REASONS.get(why, "")})
    return {"results": out}


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    # only what the settings page edits: the program's own bookkeeping (which one-time migrations have run) is not a setting
    return {"settings": {k: v for k, v in db.all_settings().items() if k in config.DEFAULT_SETTINGS and k not in config.STATE}, "secrets": {k: secrets.has(v) for k, v in SECRET_FIELDS.items()}, "gmail": mail.status(),
            "drivers": sorted(registry.drivers()), "playbooks": knowledge.list_playbooks()}


@app.get("/api/browser/status")
def browser_status() -> dict[str, Any]:
    import importlib.util
    from .. import browser

    return {"installed": importlib.util.find_spec("nodriver") is not None,
            "executable": db.get_setting("browser.executable") or browser.find_chrome()}


@app.post("/api/browser/test")
def browser_test() -> dict[str, Any]:
    from .. import browser, nodriver_backend

    status = browser_status()
    if not status["installed"] or not status["executable"]:
        raise HTTPException(400, "Install nodriver and Chrome / Edge first")
    try:
        with nodriver_backend.open_page(None, headless=True, executable=status["executable"], args=net.chrome_args()) as page:
            page.goto("data:text/html,<title>AutoApply browser test</title><input id='test'>")
            page.locator("#test").fill("AutoApply")
            if page.locator("#test").input_value() != "AutoApply":
                raise RuntimeError("Browser input verification failed")
    except Exception as exc:
        raise HTTPException(400, f"Browser test failed: {type(exc).__name__}: {exc}") from exc
    return {"ok": True}


@app.put("/api/settings")
def put_settings(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from .. import browser_policy

    try:
        browser_policy.validate(body.get("settings") or {})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    before = float(db.get_setting("queue.min_score_for_draft") or 0)
    for k, v in (body.get("settings") or {}).items():
        if k.startswith("migrated.") or k in config.STATE or k in config.RETIRED:
            continue        # the program's own bookkeeping, or a setting that is gone: sent back by a page loaded earlier
        if k not in config.DEFAULT_SETTINGS:
            raise HTTPException(400, f"unknown setting {k}")
        db.set_setting(k, v)
    for k, v in (body.get("secrets") or {}).items():
        if k not in SECRET_FIELDS:
            raise HTTPException(400, f"unknown secret {k}")
        if v:
            secrets.put(SECRET_FIELDS[k], v)
        else:
            secrets.delete(SECRET_FIELDS[k])
        if k == "anthropic_api_key":
            llm.reset_client()
    net.apply()
    llm.reset_client()
    tasks.reschedule()
    if float(db.get_setting("queue.min_score_for_draft") or 0) < before:
        # the score at which a draft is prepared was lowered: postings that are already scored and now qualify get theirs
        from .. import scoring

        scoring.queue_qualifying()
    return {"ok": True}


@app.get("/api/settings/claude-status")
def claude_status() -> dict[str, Any]:
    from .. import llm_sdk

    return llm_sdk.status(secrets.get(secrets.CLAUDE_OAUTH_TOKEN))


@app.post("/api/settings/llm-test")
def llm_test() -> dict[str, Any]:
    """One tiny call on the small model with the current backend."""
    try:
        reply = llm.text("Reply with the single word OK.", small=True, max_tokens=50)
    except llm.LLMError as e:
        raise HTTPException(400, str(e)) from None
    return {"ok": True, "backend": llm.backend(), "reply": reply[:80]}


@app.post("/mcp/run/{token}")
def mcp_run(token: str, msg: dict[str, Any] = Body(...)):  # noqa: ANN201
    """Tools of one agent run, for the ChatGPT (Codex) runtime. Only reachable with the run's one-off token."""
    from fastapi.responses import JSONResponse, Response

    from .. import toolbridge

    try:
        out = toolbridge.handle(token, msg)
    except KeyError:
        raise HTTPException(404, "no such run") from None
    return Response(status_code=202) if out is None else JSONResponse(out)


@app.post("/api/llm/chatgpt/login")
def chatgpt_login() -> dict[str, Any]:
    from .. import llm_codex

    try:
        return llm_codex.login()
    except (llm_codex.Unavailable, llm_codex.Failed) as e:
        raise HTTPException(400, str(e)) from None


@app.post("/api/llm/chatgpt/logout")
def chatgpt_logout() -> dict[str, Any]:
    from .. import llm_codex

    try:
        llm_codex.logout()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"{type(e).__name__}: {str(e)[:200]}") from None
    return {"ok": True}


@app.get("/api/llm/providers")
def llm_providers() -> dict[str, Any]:
    """The AI services that can be chosen, and what is saved for each (never the key itself)."""
    from .. import llm_codex, llm_openai

    saved = db.get_setting("llm.providers") or {}
    rows = [{"key": "claude_subscription", "name": "Claude 订阅（Pro / Max）", "kind": "login"},
            {"key": "anthropic", "name": "Claude API key", "kind": "anthropic", "has_key": secrets.has(secrets.ANTHROPIC_KEY), "keys": "https://console.anthropic.com/settings/keys"},
            {"key": "chatgpt", "name": "ChatGPT 订阅（Plus / Pro）", "kind": "codex", **llm_codex.status(), **{k: (saved.get("chatgpt") or {}).get(k, "") for k in ("model", "small_model")}}]
    for k, p in llm_openai.PRESETS.items():
        c = saved.get(k) or {}
        rows.append({"key": k, "name": p["name"], "kind": "openai", "default_base_url": p["base_url"], "keys": p["keys"], "base_url": c.get("base_url", ""),
                     "model": c.get("model", ""), "small_model": c.get("small_model", ""), "has_key": secrets.has(llm.key_name(k))})
    return {"current": llm.provider(), "providers": rows}


@app.get("/api/llm/failover")
def llm_failover() -> dict[str, Any]:
    """The service in use and its backups, in the order they are tried, with what each is doing right now."""
    return {"chain": llm.failover_status(), "saved": db.get_setting("llm.failover") or []}


@app.put("/api/llm/failover")
def llm_failover_save(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from .. import llm_openai

    rows = []
    for e in body.get("entries") or []:
        p = str(e.get("provider") or "")
        if not (p in ("claude_subscription", "anthropic", "chatgpt") or p in llm_openai.PRESETS):
            raise HTTPException(400, f"不认识的 AI 服务：{p}")
        rows.append({"provider": p, "model": str(e.get("model") or "").strip(), "small_model": str(e.get("small_model") or "").strip()})
    db.set_setting("llm.failover", rows)
    llm.reset_failover()
    return llm_failover()


@app.post("/api/llm/failover/reset")
def llm_failover_reset() -> dict[str, Any]:
    """Forget which services were set aside: every one is tried again from the next call."""
    llm.reset_failover()
    return llm_failover()


@app.post("/api/llm/failover/test")
def llm_failover_test(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """One short question to each of an entry's two models, so a backup is known to work before it is needed."""
    from .. import quota

    e = {"provider": str(body.get("provider") or ""), "model": str(body.get("model") or ""), "small_model": str(body.get("small_model") or "")}
    if not e["provider"]:
        raise HTTPException(400, "没有指定 AI 服务")
    out = llm.try_entry(e)
    for kind in ("main", "small"):   # what to show: one plain sentence; the service's own words go under "technical details"
        r = out[kind]
        if not r["ok"]:
            ex = humanize.explain(r["error"])
            r["message"], r["detail"] = ex["message"], ex["detail"] or r["error"]
    if not (out["main"]["ok"] and out["small"]["ok"]) and quota.supported(e["provider"]):
        q = quota.read(e["provider"], max_age=120)   # when it comes back, if the service says
        out["quota"] = {"level": q.get("level"), "lines": quota.describe(q)} if not q.get("error") else None
    return out


@app.get("/api/llm/quota")
def llm_quota(refresh: bool = False) -> dict[str, Any]:
    """The allowance of the service in use and of each backup, where the service reports one."""
    from .. import quota

    seen: list[str] = []
    for e in llm.chain():
        if e["provider"] not in seen:
            seen.append(e["provider"])
    rows = []
    for p in seen:
        q = quota.read(p, refresh=refresh)
        rows.append({**{k: v for k, v in q.items() if k != "stale"}, "lines": quota.describe(q) if q.get("supported") and not q.get("error") else []})
    return {"services": rows, "warn_percent": db.get_setting("llm.quota_warn_percent"), "warn_balance": db.get_setting("llm.quota_warn_balance"),
            "notify": bool(db.get_setting("llm.quota_notify")), "check_minutes": db.get_setting("llm.quota_check_minutes")}


@app.put("/api/llm/quota")
def llm_quota_save(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if "warn_percent" in body:
        db.set_setting("llm.quota_warn_percent", max(1.0, min(100.0, float(body["warn_percent"]))))
    if "warn_balance" in body:
        db.set_setting("llm.quota_warn_balance", max(0.0, float(body["warn_balance"])))
    if "notify" in body:
        db.set_setting("llm.quota_notify", bool(body["notify"]))
    return llm_quota()


@app.put("/api/llm/providers/{key}")
def llm_provider_save(key: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Save one service's settings (and its key, if one is given) and optionally make it the one in use."""
    from .. import llm_openai

    if key not in ("claude_subscription", "anthropic", "chatgpt") and key not in llm_openai.PRESETS:
        raise HTTPException(404, "unknown provider")
    if key in llm_openai.PRESETS or key == "chatgpt":
        base = str(body.get("base_url", "")).strip()
        if base and not re.match(r"^https?://", base):
            raise HTTPException(400, "接口地址要以 http:// 或 https:// 开头")
        allp = dict(db.get_setting("llm.providers") or {})
        allp[key] = {"base_url": base, "model": str(body.get("model", "")).strip(), "small_model": str(body.get("small_model", "")).strip()}
        db.set_setting("llm.providers", allp)
    if body.get("api_key"):
        secrets.put(secrets.ANTHROPIC_KEY if key == "anthropic" else llm.key_name(key), str(body["api_key"]).strip())
        llm.reset_client()
    if body.get("use"):
        db.set_setting("llm.provider", key)
        db.set_setting("llm.auth", "api_key" if key == "anthropic" else "subscription")
    return {"ok": True}


@app.post("/api/llm/providers/{key}/models")
def llm_provider_models(key: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Ask the service which models it has (with what is typed in the form, saved or not)."""
    from .. import llm_openai

    if key in ("claude_subscription", "anthropic"):
        known = ["claude-fable-5-2", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
        api_key = str(body.get("api_key") or "") or (secrets.get(secrets.ANTHROPIC_KEY) or "")
        if key == "anthropic" and api_key:
            try:
                import httpx

                r = httpx.get("https://api.anthropic.com/v1/models", params={"limit": 100}, headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"}, timeout=30)
                if r.status_code == 200:
                    return {"models": [m["id"] for m in r.json().get("data", [])] or known}
                if r.status_code in (401, 403):
                    raise HTTPException(400, "Anthropic 拒绝了这个 API key。")
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001 - unreachable: the built-in list still lets the user choose
                pass
        return {"models": known}
    if key == "chatgpt":
        from .. import llm_codex

        try:
            return {"models": llm_codex.models()}
        except (llm_codex.Unavailable, llm_codex.Failed) as e:
            raise HTTPException(400, str(e)) from None
    if key not in llm_openai.PRESETS:
        raise HTTPException(404, "unknown provider")
    base = str(body.get("base_url") or "").strip() or llm_openai.PRESETS[key]["base_url"]
    try:
        c = llm_openai.Client(base, str(body.get("api_key") or "") or secrets.get(llm.key_name(key)))
        return {"models": c.models()}
    except (llm_openai.Unavailable, llm_openai.Failed) as e:
        raise HTTPException(400, str(e)) from None


@app.post("/api/settings/telegram-test")
def telegram_test() -> dict[str, Any]:
    try:
        notify.test_message()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from None
    return {"ok": True}


@app.get("/api/mailbox")
def mailbox_state() -> dict[str, Any]:
    from .. import mailbox

    return {**mailbox.status(), "presets": [{"key": k, "name": v["name"], "host": v["host"], "port": v["port"], "how": v["how"], "oauth": bool(v.get("oauth"))} for k, v in mailbox.PRESETS.items()]}


@app.post("/api/mailbox/outlook/authorize")
def outlook_authorize(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Start Microsoft's device-code sign-in for reading mail. Returns the code to enter and the page to enter it on."""
    from .. import outlook

    if body.get("client_id"):
        db.set_setting("mail.outlook", {**(db.get_setting("mail.outlook") or {}), "client_id": str(body["client_id"]).strip()})
    try:
        return outlook.start()
    except outlook.NotReady as e:
        raise HTTPException(400, str(e)) from None


@app.delete("/api/mailbox/outlook")
def outlook_forget() -> dict[str, Any]:
    from .. import outlook

    outlook.forget()
    return {"ok": True}


@app.post("/api/mailbox/test")
def mailbox_test(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Try to read the mailbox - with what is typed in the form if given, else with what is saved."""
    from .. import mailbox

    cfg = None
    if body.get("imap"):
        i = body["imap"]
        p = mailbox.PRESETS.get(i.get("preset") or "", {})
        cfg = {"preset": i.get("preset") or "", "host": (i.get("host") or p.get("host") or "").strip(), "port": int(i.get("port") or p.get("port") or 993), "user": (i.get("user") or "").strip()}
    try:
        return mailbox.test(cfg, body.get("password") or None)
    except (mailbox.NotConfigured, mail.MailNotConfigured) as e:
        raise HTTPException(400, str(e)) from None
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"读取邮箱时出错：{type(e).__name__}: {str(e)[:160]}") from None


# --- people the user knows at employers -----------------------------------------------------
CONTACT_FIELDS = ("name", "company", "role", "relation", "how", "status", "follow_up", "note")


def _contact(c: Contact, open_jobs: int = 0) -> dict[str, Any]:
    return {"id": c.id, **{f: getattr(c, f) or "" for f in CONTACT_FIELDS}, "open_jobs": open_jobs}


def _contacts_for(company: str) -> list[dict[str, Any]]:
    key = discover.norm_company(company or "")
    if not key:
        return []
    with db.session() as s:
        return [_contact(c) for c in s.query(Contact) if (k := discover.norm_company(c.company)) and (k == key or k.startswith(key + " ") or key.startswith(k + " "))]


@app.get("/api/contacts")
def list_contacts() -> list[dict[str, Any]]:
    with db.session() as s:
        open_by: dict[str, int] = {}
        for (co,) in s.query(Job.company).filter(Job.online == 1, Job.duplicate_of.is_(None), Job.archived_at.is_(None)):
            k = discover.norm_company(co or "")
            open_by[k] = open_by.get(k, 0) + 1
        rows = [_contact(c, open_by.get(discover.norm_company(c.company), 0)) for c in s.query(Contact).order_by(Contact.company, Contact.name)]
    return sorted(rows, key=lambda r: (not (r["follow_up"] and r["follow_up"] <= now().date().isoformat()), r["company"].lower(), r["name"].lower()))


@app.post("/api/contacts")
def add_contact(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if not str(body.get("name", "")).strip():
        raise HTTPException(400, "请填写姓名")
    with db.session() as s:
        c = Contact(**{f: str(body.get(f, "") or "").strip()[:2000] for f in CONTACT_FIELDS})
        s.add(c)
        s.flush()
        return _contact(c)


@app.put("/api/contacts/{contact_id}")
def edit_contact(contact_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    with db.session() as s:
        c = _404(s.get(Contact, contact_id))
        for f in CONTACT_FIELDS:
            if f in body:
                setattr(c, f, str(body[f] or "").strip()[:2000])
        return _contact(c)


@app.delete("/api/contacts/{contact_id}")
def delete_contact(contact_id: int) -> dict[str, Any]:
    with db.session() as s:
        s.delete(_404(s.get(Contact, contact_id)))
    return {"ok": True}


# --- employers the user wants watched -------------------------------------------------------
@app.get("/api/employers")
def list_employers() -> dict[str, Any]:
    from .. import employers

    employers.migrate_legacy()
    with db.session() as s:
        counts: dict[tuple[str, str], int] = {}
        for src, ten in s.query(Job.source, Job.tenant).filter(Job.online == 1, Job.duplicate_of.is_(None)):
            counts[(src, ten or "")] = counts.get((src, ten or ""), 0) + 1
    rows = []
    for e in employers.listing():
        src, scope = employers.source_of(e)
        n = counts.get((src, scope), 0) if e["kind"] != "builtin" else sum(v for (a, _), v in counts.items() if a == src)
        rows.append({**e, "kind_label": employers.KIND_LABEL.get(e["kind"], e["kind"]), "open_jobs": n})
    return {"employers": rows, "priority_min_score": db.get_setting("employers.priority_min_score")}


@app.get("/api/employers/catalog")
def employer_catalog() -> dict[str, Any]:
    from .. import employers

    p = persona.get()
    return {"field": p.get("field") or "", "employers": employers.catalog(p.get("field") or "", p.get("countries") or [])}


@app.post("/api/employers")
def add_employer(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from .. import employers

    try:
        row = employers.add(str(body.get("name", "")), str(body.get("url", "")), priority=bool(body.get("priority", True)))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return {**row, "kind_label": employers.KIND_LABEL.get(row["kind"], row["kind"])}


@app.post("/api/employers/detect")
def detect_employer(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from .. import employers

    d = employers.detect(str(body.get("url", "")))
    return {**d, "kind_label": employers.KIND_LABEL.get(d["kind"], d["kind"])}


@app.patch("/api/employers/{emp_id}")
def edit_employer(emp_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from .. import employers

    employers.update(emp_id, **body)
    return {"ok": True}


@app.delete("/api/employers/{emp_id}")
def delete_employer(emp_id: str) -> dict[str, Any]:
    """Stop watching an employer. Postings already found stay."""
    from .. import employers

    employers.remove(emp_id)
    return {"ok": True}


@app.post("/api/settings/gmail-client")
async def gmail_client(file: UploadFile = File(...)) -> dict[str, Any]:
    try:
        mail.save_client_config((await file.read()).decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"not a valid OAuth client JSON: {e}") from None
    return mail.status()


@app.post("/api/settings/gmail-authorize")
def gmail_authorize() -> dict[str, Any]:
    def run() -> None:
        try:
            mail.authorize()
            notify.send("task_result", messages.gmail_authorized(), ref="config:gmail")
        except Exception as e:  # noqa: BLE001
            notify.add_todo("config", "Gmail 授权失败", body=str(e)[:300], ref="config:gmail")

    threading.Thread(target=run, daemon=True, name="gmail-oauth").start()
    return {"started": True}




# --- the remote window: a page that needs a person, shown here instead of on a screen the server does not have ---


def _remote(request: Request, window_id: str):
    """The window, for a caller who may have it. What is typed into it can be a password: another device gets it over
    HTTPS only."""
    from .. import remote

    who = access.caller(request.client.host if request.client else "", request.headers)
    if not who["local"] and not who["https"] and not who.get("near"):
        raise HTTPException(403, "远程窗口里可能要输入密码：从其他设备访问时必须通过 HTTPS。请在前面放一个负责 HTTPS 的反向代理，并在“访问与安全”里打开对应的开关。")
    win = remote.get(window_id)
    if win is None:
        raise HTTPException(404, "这个窗口已经关闭了。")
    return win


@app.get("/api/remote")
def remote_windows():
    from .. import remote

    return remote.windows()


@app.get("/api/remote/{window_id}")
def remote_window(request: Request, window_id: str):
    return _remote(request, window_id).describe()


@app.get("/api/remote/{window_id}/screen")
def remote_screen(request: Request, window_id: str):
    """For a window that is a real one on a virtual screen: the password of that screen's viewer, for the page that
    is about to connect to it. Given to a signed-in caller only (the login has been checked before this runs)."""
    win = _remote(request, window_id)
    if not win.vnc:
        raise HTTPException(409, "这个窗口不是虚拟屏幕上的窗口。")
    return {"password": win.vnc["password"]}


def _ws_refusal(ws: Any, path: str) -> str:
    """Why a WebSocket may not be opened ('' when it may). The HTTP middleware does not see WebSockets, so the same
    three questions are asked here: is it one of this program's own pages, is the caller signed in, and - what goes
    through can be a password - does it travel encrypted when it comes from another device."""
    from urllib.parse import urlparse

    host = ws.headers.get("host", "")
    if _host_of(host) not in _own_hosts():
        return "host"
    # A browser always says where a WebSocket is opened from. It has to be this program's own page - host and port:
    # a page served by another program on this computer, on its own port, is not ours although the host is the same.
    origin = ws.headers.get("origin")
    mine = {host.lower()}
    base = urlparse(str(db.get_setting("app.base_url") or ""))
    if base.netloc:
        mine.add(base.netloc.lower())
    if not origin or urlparse(origin).netloc.lower() not in mine:
        return "origin"
    who = access.caller(ws.client.host if ws.client else "", ws.headers)
    if not access.allowed(path, ws.cookies.get(access.COOKIE), who, ws.headers.get(access.LOCAL_HEADER)):
        return "login"
    if not who["local"] and not who["https"] and not who.get("near"):
        return "plain"
    return ""


async def _remote_vnc(ws: Any, window_id: str) -> None:
    """The page's VNC client talks WebSocket; the screen's VNC server talks TCP on this computer only. Bytes are passed
    both ways, unread and unlogged."""
    import asyncio

    from .. import remote

    why = _ws_refusal(ws, f"/api/remote/{window_id}/vnc")
    win = remote.get(window_id)
    if why or win is None or not win.vnc:
        log.warning("refused a remote screen connection (%s)", why or "no such window")
        await ws.close(code=1008)
        return
    asked = [p.strip() for p in (ws.headers.get("sec-websocket-protocol") or "").split(",") if p.strip()]
    await ws.accept(subprotocol="binary" if "binary" in asked else None)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", int(win.vnc["port"]))
    except OSError:
        await ws.close(code=1011)
        return

    async def up() -> None:
        while True:
            data = await ws.receive_bytes()
            writer.write(data)
            await writer.drain()

    async def down() -> None:
        while True:
            data = await reader.read(65536)
            if not data:
                return
            await ws.send_bytes(data)

    tasks = [asyncio.ensure_future(up()), asyncio.ensure_future(down())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        writer.close()
        try:
            await ws.close()
        except Exception:  # noqa: BLE001 - the other side closed it first
            pass


@app.websocket("/api/remote/{window_id}/vnc")
async def remote_vnc(ws: WebSocket, window_id: str):
    await _remote_vnc(ws, window_id)


@app.get("/api/remote/{window_id}/frame")
def remote_frame(request: Request, window_id: str, after: int = 0):
    """The newest picture of the page once it is newer than `after` (waits a few seconds for one). Never stored."""
    import json

    from fastapi.responses import Response

    win = _remote(request, window_id)
    if win.vnc:
        raise HTTPException(409, "这个窗口是虚拟屏幕上的窗口，通过屏幕连接查看。")
    seq, frame = win.next_frame(after)
    headers = {"X-Seq": str(seq), "Cache-Control": "no-store", "X-State": json.dumps(win.state, ensure_ascii=True)}
    if frame is None:
        return Response(status_code=204, headers=headers)
    return Response(content=frame, media_type="image/jpeg", headers=headers)


@app.post("/api/remote/{window_id}/input")
def remote_input(request: Request, window_id: str, body: dict[str, Any] = Body(...)):
    """Clicks and keys for the page. Their content is never logged: it can be a password."""
    events = body.get("events")
    if not isinstance(events, list):
        raise HTTPException(400, "events")
    _remote(request, window_id).send(events)
    return {"ok": True}


@app.get("/api/doctor")
def doctor_report(deep: bool = False):
    """What this computer lacks for the program to do its whole job, each with the command that fixes it."""
    from .. import doctor, i18n

    return [{**f, "title": i18n.tr(f["title"]), "detail": i18n.tr(f["detail"])} for f in doctor.run(deep=deep)]


# --- frontend ------------------------------------------------------------------------------

if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    def _interface_files() -> dict[str, Path]:
        """The files of the built interface, by the address they are served at. A request is answered by looking its
        address up in this list - no path is ever put together from what a request says, so nothing outside the folder
        can be named, however the address is written. A link in the folder that leads out of it is not one of them."""
        root = config.FRONTEND_DIST.resolve()
        return {f.relative_to(root).as_posix(): f for f in root.rglob("*") if f.is_file() and f.resolve().is_relative_to(root)}

    _files = {"all": _interface_files()}

    @app.get("/{path:path}")
    def spa(path: str):
        f = _files["all"].get(path)
        if f is None and path and "." in path.rsplit("/", 1)[-1]:      # a file that is not known: the interface may have been built again
            _files["all"] = _interface_files()
            f = _files["all"].get(path)
        if f is not None and f.is_file() and path != "index.html":
            return FileResponse(f)
        # The page itself. It is told the address it is served under, so that its files and its API calls are found
        # whatever path a proxy puts in front and however deep the address of the view that is open.
        from fastapi.responses import HTMLResponse

        index = _files["all"].get("index.html") or config.FRONTEND_DIST / "index.html"
        base = access.conf()["root_path"] + "/"
        html = index.read_text(encoding="utf-8").replace('<base href="/" />', f'<base href="{base}" />', 1)
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
