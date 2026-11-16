"""Task handlers: the glue between the queue and the modules."""

from __future__ import annotations

import re
from typing import Any

from . import config, db, discover, drafts, executor, mail, messages, notify, scoring, tasks
from .ats.base import NeedsHuman
from .models import Application, Job, Task
from .tasks import enqueue, handler


@handler("discover")
def _discover(t: Task) -> dict[str, Any]:
    return discover.run()


@handler("score")
def _score(t: Task) -> dict[str, Any]:
    if t.payload.get("job_id"):
        out = scoring.score_job(int(t.payload["job_id"]))
        return out or {"skipped": "no description"}
    out = scoring.score_pending()
    if out.get("remaining"):  # the per-run cap protects the model quota; the rest follows in a few minutes instead of waiting for the next scan
        tasks.enqueue_later("score", ref="unscored", minutes=5, priority=150)
    return out


@handler("recon")
def _recon(t: Task) -> dict[str, Any]:
    job_id = int(t.payload["job_id"])
    if not t.payload.get("instructions"):
        from .models import Draft

        with db.session() as s:  # another run for the same posting finished while this one was waiting: its draft stands
            a = s.query(Application).filter_by(job_id=job_id).first()
            newer = [d for d in (a.drafts if a else []) if d.review_status == "pending" and d.created_at >= t.created_at]
            if newer:
                return {"draft_id": newer[-1].id, "reused": True}
    try:
        draft_id = drafts.build(job_id, run_dir=config.RUNS / f"recon_job_{job_id}_t{t.id}", instructions=t.payload.get("instructions", ""))
    except NeedsHuman as e:
        from .ats import registry
        from .models import Job

        with db.session() as s:
            j = s.get(Job, job_id)
            company, url = j.company, j.apply_url
        ref = registry.detect(url) if url else None
        from .ats.base import host_is, url_host

        # where the run stopped, or an address the agent quoted in its notes: by host, not by a name somewhere in the text
        seen = [e.url or "", *re.findall(r"https?://[^\s\"'<>)]+", e.reason or ""), *re.findall(r"\b[a-z0-9.-]+\.[a-z]{2,}\b", (e.reason or "").lower())]
        if any(host_is(url_host(x), "accounts.google.com") for x in seen):
            notify.add_todo("blocked", f"{company}", body="google_sign_in: " + e.reason, ref=f"job:{job_id}", payload={"url": url, "job_id": job_id, "retry_task": t.id, "why": "google"})
        elif e.kind not in ("login", "captcha", "mfa", "account", "verification", "register"):
            # not a sign-in problem: the page does not work in this program's browser (blank page, site error, apply button leads nowhere)
            notify.add_todo("blocked", f"{company}", body=e.reason, ref=f"job:{job_id}", payload={"url": url, "job_id": job_id, "retry_task": t.id, "why": e.kind})
        elif e.kind == "captcha" or ref is None:
            notify.add_todo("login", f"{company}：需要你处理", body=e.reason, ref=f"job:{job_id}", payload={"url": e.url, "retry_task": t.id})
        else:  # signing in: the same card as every other login, with the choice to let the agent register instead
            notify.add_todo("takeover", f"{company}（{ref.host or ref.tenant_key}）", body=e.reason, ref=f"account:{ref.tenant_key}",
                            payload={"tenant_key": ref.tenant_key, "ats": ref.ats, "url": e.url or url, "job_url": url, "retry_task": t.id, "can_register": True})
        raise
    return {"draft_id": draft_id}


@handler("tailor")
def _tailor(t: Task) -> dict[str, Any]:
    """Write (or rewrite) the tailored résumé for one job and put it into the open draft, if there is one."""
    from . import tailor
    from .models import Draft, Job

    job_id = int(t.payload["job_id"])
    with db.session() as s:
        job = s.get(Job, job_id)
        s.expunge(job)
    doc = tailor.make(job, instructions=t.payload.get("instructions", ""))
    info = doc["tailor"]
    swapped = 0
    if not info["problems"]:
        with db.session() as s:
            for d in s.query(Draft).filter(Draft.review_status == "pending"):
                if d.application.job_id == job_id:
                    swapped += drafts.swap_resume(d, doc)
    notify.send("task_result", messages.tailored(f"{job.company} · {job.title}", focus=info["focus"], problems=info["problems"]), ref=f"job:{job_id}")
    return {"document_id": doc["id"], "changes": len(info["changes"]), "in_draft": bool(swapped), "problems": info["problems"]}


@handler("reanswer")
def _reanswer(t: Task) -> dict[str, Any]:
    return drafts.reanswer(int(t.payload["draft_id"]))


@handler("scout")
def _scout(t: Task) -> dict[str, Any]:
    """Read the later steps of a form by walking it with the draft's answers (nothing is submitted)."""
    return drafts.scout(int(t.payload["draft_id"]), task_id=t.id)


@handler("revise")
def _revise(t: Task) -> dict[str, Any]:
    return drafts.revise(int(t.payload["draft_id"]), t.payload["comment"])


@handler("execute")
def _execute(t: Task) -> dict[str, Any]:
    app_id = int(t.ref.split(":")[1])
    out = executor.execute(app_id, int(t.payload["draft_id"]), task_id=t.id, force_manual=t.payload.get("force_manual", ""))
    if out["status"] == "needs_human":
        raise NeedsHuman(out.get("error", "needs human"))
    return {k: v for k, v in out.items() if k != "evidence"}


@handler("improve")
def _improve(t: Task) -> dict[str, Any]:
    """Look at a run that stood out and have the agent write what the program should do differently (improve.py)."""
    from . import improve

    return improve.propose(int(t.payload["run_id"]), driver=bool(t.payload.get("driver")))


@handler("mail")
def _mail(t: Task) -> dict[str, Any]:
    try:
        out = mail.track(days=int(t.payload.get("days", 3)))
        fixed = mail.reconcile()      # a confirmation read while the application was taken for unsent
        return {**out, "status_updates": out["status_updates"] + fixed} if fixed else out
    except mail.MailNotConfigured as e:
        return {"skipped": str(e)}


@handler("site_status")
def _site_status(t: Task) -> dict[str, Any]:
    """An e-mail that names no posting: read the employer's own list of the applicant's applications to tell which it is."""
    from . import sitestatus

    return sitestatus.resolve(str(t.payload["message_id"]))


@handler("canary")
def _canary(t: Task) -> dict[str, Any]:
    """The self-check: the coded reading of each system against an open posting, and the saved form pages against the
    current code. What it finds it deals with itself. Every form is read by the agent now, so a system whose coded
    reading fails holds nothing up and needs nobody; a saved page that no longer matches is out of date and is removed
    (the next run that fills and verifies that form saves it afresh). Cards that told the applicant "the self-check
    failed" asked them for something they cannot do; there are none any more, and old ones are closed."""
    from .ats import registry
    from .models import Todo, now

    out: dict[str, Any] = {}
    targets: list[tuple[str, Any, list[str]]] = []
    with db.session() as s:
        for ats, drv in registry.drivers().items():
            if drv.requires_login:
                continue
            urls = [j.apply_url for j in s.query(Job).filter(Job.ats == ats, Job.online == 1, Job.apply_url != "").order_by(Job.last_seen.desc()).limit(3)]
            if urls:
                targets.append((ats, drv, urls))
    for ats, drv, urls in targets:
        last = ""
        for url in urls:      # one posting that has just closed is not a finding about the system: try the next
            try:
                sc = drv.get_schema(registry.detect(url), None)
                out[ats] = {"ok": True, "questions": len(sc.questions)}
                break
            except Exception as e:  # noqa: BLE001
                last = str(e)[:200]
        else:
            out[ats] = {"ok": False, "error": last, "handled": "forms of this system are read by the agent; nothing waits on this"}
    from . import fixtures

    fx = fixtures.run_all()
    repaired = 0
    for r in fx["results"]:
        if not r["ok"]:
            repaired += fixtures.drop(r["ats"], r["fixture"])
    out["fixtures"] = {"total": fx["fixtures"], "failed": fx["failed"], "repaired": repaired}
    with db.session() as s:
        for td in s.query(Todo).filter_by(kind="driver", status="open"):
            td.status, td.done_at = "done", now()
    return out


def resume_waiting(ref_prefix: str = "") -> int:
    """After the user handles a login/takeover, put waiting tasks back in the queue."""
    n = 0
    with db.session() as s:
        for t in s.query(Task).filter_by(status="waiting_human"):
            if ref_prefix and not t.ref.startswith(ref_prefix):
                continue
            t.status, t.error = "queued", ""
            n += 1
        for a in s.query(Application).filter_by(status="needs_human"):
            a.status = "approved" if any(d.review_status == "approved" for d in a.drafts) else "recon"
    if n:
        from . import tasks

        tasks._wake.set()
    return n


__all__ = ["enqueue", "resume_waiting"]
