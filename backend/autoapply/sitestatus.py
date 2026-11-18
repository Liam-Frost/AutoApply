"""What the employer's own site says about the applications sent there.

An e-mail often does not say which application it is about ("Action required for your Amazon application"), while the
site's applicant page lists every application with its state. With the sign-in the program already has for the site, an
agent opens that page and reads it - reads only: it does not sign in, fill, submit, withdraw or start anything. What it
read is kept with each application, and is used to tell which application an e-mail belongs to.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import auth, browser, config, db, drafts, generic, llm, mail, notify
from .models import Application, MailEvent, Todo

log = logging.getLogger("autoapply.sitestatus")

# never pressed on an applicant page, whatever the goal: these change or end an application
DANGER = re.compile(r"withdraw|delete|remove|cancel|decline|reject|accept offer|start (the )?(assessment|test)|begin (the )?(assessment|test)|take (the )?(assessment|test)|"
                    r"sign ?out|log ?out|deactivate|撤回|撤销|删除|取消|放弃|开始测评|退出登录", re.I)

SYSTEM = """You read an employer's careers site on behalf of an applicant who is already signed in there. Your only job is to find
the page that lists the applicant's own applications (often "My applications", "Application status", "Candidate home", under the
account menu) and report what it says about each one. You only look: never fill a form, never apply, never withdraw or change an
application, never start an assessment, never sign in or out. If the site shows a sign-in page instead of the applicant's
account, report signed_in=false and stop - do not try to sign in. Report every application the page lists, with its title, the
job number if shown, the state exactly as the site words it, and any date shown with it; open an application's own page only when
the list does not show its state. Do not guess: an application you did not see is not reported."""


def _tools(page: Any, run_dir: Path, out: dict[str, Any], home: str) -> list[llm.Tool]:
    st = {"type": "string"}

    def report(applications: list[dict[str, Any]] | None = None, signed_in: bool = True, notes: str = "") -> str:
        out.update(signed_in=bool(signed_in), notes=str(notes)[:400],
                   applications=[{k: str(a.get(k) or "")[:200] for k in ("title", "job_id", "status", "date")} for a in (applications or [])[:60] if a.get("title")])
        return "recorded"

    done = llm.Tool("report", "Report the applications the site lists, each with its state, and stop.", {"type": "object", "properties": {
        "signed_in": {"type": "boolean"}, "notes": st,
        "applications": {"type": "array", "items": {"type": "object", "properties": {"title": st, "job_id": st, "status": st, "date": st},
                                                    "required": ["title", "status"], "additionalProperties": False}}},
        "required": ["signed_in", "applications"], "additionalProperties": False}, report)
    base = {t.name: t for t in generic.l0_tools(page, run_dir, {}, finish_tool=done)}

    def click(selector: str = "", text: str = "") -> str:
        loc = page.locator(selector).first if selector else page.get_by_role("button", name=text).or_(page.get_by_role("link", name=text)).first
        label = " ".join(str(x or "") for x in (loc.inner_text(), loc.get_attribute("value"), loc.get_attribute("aria-label"))).strip()
        if DANGER.search(label):
            raise PermissionError(f"refused: '{label[:60]}' changes an application or the account; this visit only reads")
        return base["click"].fn(selector=selector, text=text)

    def goto(url: str) -> str:
        host = (urlparse(url).hostname or "").lower()
        if urlparse(url).scheme != "https" or mail.site_domain(host) != home:
            raise PermissionError(f"refused: this visit stays on {home}")
        return base["goto"].fn(url=url)

    return [base["read_page"], base["screenshot"], llm.Tool("click", base["click"].description, base["click"].input_schema, click),
            llm.Tool("goto", f"Navigate to a URL on {home}.", base["goto"].input_schema, goto), done]


def read(tenant_key: str, start_url: str, run_dir: Path) -> dict[str, Any]:
    """Open the site with its saved sign-in and read the applicant's list of applications.
    Returns {"signed_in": bool, "applications": [{title, job_id, status, date}], "notes": str}."""
    out: dict[str, Any] = {"signed_in": False, "applications": [], "notes": ""}
    home = mail.site_domain((urlparse(start_url).hostname or "").lower())
    run_dir.mkdir(parents=True, exist_ok=True)
    with browser.open_page(tenant_key, url=start_url, operation="read") as page:
        page.goto(start_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        llm.agent(f"The site: {start_url}\nFind the applicant's list of applications and report it.", _tools(page, run_dir, out, home), system=SYSTEM, kind="site_status")
        try:
            browser.snapshot(page, run_dir, "applications")
        except Exception:  # noqa: BLE001
            pass
    return out


def _site_of(app: Application) -> tuple[str, str] | None:
    """(account key, address to start from) of the site an application was sent on - only where a sign-in is saved."""
    try:
        ref = drafts.job_ref(app.job)
    except Exception:  # noqa: BLE001
        return None
    key = auth.key_for(ref.tenant_key)
    if not browser.load_state(key):
        return None
    u = urlparse(ref.url)
    return key, f"https://{u.netloc}/"


WHICH = {"type": "object", "properties": {"application_ids": {"type": "array", "items": {"type": "integer"}}, "reason": {"type": "string"}},
         "required": ["application_ids", "reason"], "additionalProperties": False}


def resolve(message_id: str) -> dict[str, Any]:
    """An e-mail that names no posting: look on the employer's site which application(s) it is about, and link it.
    What the site says about each application is kept either way, and shown on the card when the e-mail stays open."""
    with db.session() as s:
        me = s.query(MailEvent).filter_by(message_id=message_id).first()
        if me is None or me.application_id is not None:
            return {"skipped": "already linked"}
        subject, summary, category, company, received = me.subject, me.summary, me.category, me.company_guess, me.received_at
        apps = {a.id: (a, _site_of(a)) for a in s.query(Application).filter(Application.id.in_(mail.candidates(company)))}
        rows = {i: {"title": a.job.title, "job_id": a.job.source_id or "", "status": a.status, "site": site} for i, (a, site) in apps.items()}
    sites = {r["site"] for r in rows.values() if r["site"]}
    if not sites:
        return {"skipped": "no saved sign-in for this employer's site"}
    seen: list[dict[str, Any]] = []
    for key, start in sorted(sites):
        try:
            got = read(key, start, config.RUNS / f"site_status_{re.sub(r'[^a-z0-9]+', '_', key.lower())}")
        except llm.LLMError:
            raise
        except Exception as e:  # noqa: BLE001 - a site that cannot be read leaves the e-mail to the applicant
            log.warning("could not read the applications on %s: %s", key, e)
            continue
        if not got["signed_in"]:
            log.info("the saved sign-in for %s is no longer good; its applications were not read", key)
            continue
        seen += got["applications"]
    if not seen:
        return {"read": 0}
    listing = "\n".join(f"- {a['title']} | job {a['job_id'] or '?'} | state on the site: {a['status']} | {a['date']}" for a in seen)
    mine = "\n".join(f"- id={i} | {r['title']} | job {r['job_id'] or '?'}" for i, r in rows.items())
    got = llm.json(
        f"An e-mail from an employer does not say which application it is about.\nE-mail ({category}, received {received}): {subject}\n{summary}\n\n"
        f"The applicant's applications at this employer, as this program knows them:\n{mine}\n\nWhat the employer's site lists:\n{listing}\n\n"
        "Which of the program's applications is the e-mail about? Go by the state on the site: an assessment invitation belongs to the application(s) the "
        "site shows as waiting for an assessment, a rejection to the one shown as closed, and so on. One e-mail can be about several applications. "
        "Return the ids, or an empty list when the site does not settle it. Also say in `reason`, in one sentence, what the site shows.",
        WHICH, small=True, max_tokens=600)
    ids = [int(i) for i in got.get("application_ids") or [] if int(i) in rows]
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db.session() as s:      # what the site says, kept with each application the listing can be matched to by title or number
        for i, r in rows.items():
            for a in seen:
                if (r["job_id"] and r["job_id"] == a["job_id"]) or mail._norm(a["title"]) == mail._norm(r["title"]):
                    app = s.get(Application, i)
                    app.evidence = {**(app.evidence or {}), "site_status": {"text": a["status"], "date": a["date"], "at": at}}
                    break
    if ids:
        mail.link(message_id, ids, by="site")
        return {"read": len(seen), "linked": ids, "reason": str(got.get("reason") or "")[:300]}
    with db.session() as s:      # still the applicant's call: the card shows what the site says
        for t in s.query(Todo).filter_by(kind="mail_unmatched", ref=f"mail:{message_id}", status="open"):
            t.payload = {**(t.payload or {}), "site": [f"{a['title']}：{a['status']}" for a in seen[:12]], "site_note": str(got.get("reason") or "")[:300]}
    return {"read": len(seen), "linked": []}
