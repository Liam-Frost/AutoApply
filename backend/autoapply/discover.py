"""Discovery: pull every configured source, upsert jobs, track online/offline.

A failing source never fails the scan; its error is reported in the summary.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from . import db, intake, messages, notify
from .ats.base import NeedsHuman
from .models import Job, now
from .sources import bigtech, public

log = logging.getLogger("autoapply.discover")

FIELDS = ("company", "title", "location", "work_type", "salary", "apply_url", "ats", "tenant", "jd_text", "channel",
          "term", "months", "deadline", "docs_required", "posted")


def upsert(rows: Iterable[dict[str, Any]], *, source: str, scope: str | None = None, complete: bool = True, stale_days: int = 0) -> dict[str, int]:
    """Insert/update jobs for one source. ``scope`` narrows offline-marking to
    a tenant (so scanning board A does not mark board B's jobs offline).
    ``complete=False`` skips offline-marking (partial scan)."""
    new = back = offline = seen_n = 0
    seen: set[str] = set()
    rows = list(rows)  # read the source completely first: fetching inside the transaction would lock the database for minutes
    with db.session() as s:
        for r in rows:
            sid = str(r["source_id"])
            seen.add(sid)
            seen_n += 1
            j = s.query(Job).filter_by(source=source, source_id=sid).first()
            if j is None:
                if not r.get("title"):
                    continue  # a bare id only keeps a known posting online
                j = Job(source=source, source_id=sid, status="new")
                s.add(j)
                new += 1
            elif not j.online:
                j.online = 1
                if j.status == "offline":
                    j.status = "scored" if j.score is not None else "new"
                j.note = (f"back online {now().date().isoformat()}; " + (j.note or ""))[:2000]
                back += 1
            for f in FIELDS:
                v = r.get(f)
                if v:
                    setattr(j, f, v)
            j.last_seen = now()
        if complete:
            q = s.query(Job).filter(Job.source == source, Job.online == 1)
            if scope:
                q = q.filter(Job.tenant == scope)
            for j in q:
                if j.source_id not in seen:
                    j.online = 0
                    offline += 1
                    # keep applied jobs' status; only undecided ones become "offline"
                    if j.application is None and j.status in ("new", "scored", "queued"):
                        j.status = "offline"
        if stale_days:  # capped / filtered listings: a job is offline once it has not been listed for a while
            from datetime import timedelta

            cut = now() - timedelta(days=stale_days)
            for j in s.query(Job).filter(Job.source == source, Job.online == 1, Job.last_seen < cut):
                j.online = 0
                offline += 1
                if j.application is None and j.status in ("new", "scored", "queued"):
                    j.status = "offline"
    return {"seen": seen_n, "new": new, "back": back, "offline": offline}


_CORP = re.compile(r"\b(inc|incorporated|corp|corporation|ltd|limited|llc|co|company|canada|ulc|technologies|technology|systems)\b\.?", re.I)


def norm_company(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _CORP.sub(" ", (name or "").lower())).strip()


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def norm_url(url: str) -> str:
    """Posting address without tracking parameters, for comparing two listings of the same posting."""
    u = (url or "").strip().lower()
    if not u or "pdportal.apsc.ubc.ca" in u:
        return ""
    m = re.search(r"//([^/]+)/.*?(?:[?&]pid=|/careers/job/)(\d{9,})", u)
    if m:  # Eightfold: the search-page link (pid=...) and the posting link (/careers/job/...) name the same position
        return f"{m.group(1)}/job/{m.group(2)}"
    u = re.sub(r"^https?://(www\.)?", "", u)
    u = re.sub(r"[?#].*$", "", u) if not re.search(r"[?&](pid|jobid|career_job_req_id|gh_jid|opportunityid)=", u) else re.sub(r"#.*$", "", u)
    return u.rstrip("/")


REQ_ID = re.compile(r"(?=[A-Za-z0-9-]*\d)[A-Za-z]{0,4}-?\d{5,}(?:-\d+)?", re.I)  # JR2023495, R-31985, 200057714


def archive_old() -> int:
    """A posting leaves the working lists when its story is over and some time has passed:
    closed without an application (offline / past its deadline / skipped), rejected, or applied with no reply
    for a long time. Nothing is deleted - archived rows stay for the analysis page and for
    "you applied to this role before" hints - and they can be brought back from the job page."""
    from datetime import timedelta

    from . import stages

    closed = timedelta(days=int(db.get_setting("archive.closed_after_days") or 30))
    silent = timedelta(days=int(db.get_setting("archive.silent_after_days") or 150))
    n = 0
    with db.session() as s:
        for j in s.query(Job).filter(Job.archived_at.is_(None)):
            a = j.application
            st = stages.stage(j.status, bool(j.online), j.deadline or "", a.status if a else None)
            last = max(x.replace(tzinfo=None) for x in (j.last_seen, a.updated_at if a else None, a.submitted_at if a else None, j.first_seen) if x is not None)
            age = now().replace(tzinfo=None) - last
            if (st in ("offline", "expired", "skipped", "rejected") and age > closed) or (st in ("submitted", "confirmed") and age > silent):
                j.archived_at = now()
                n += 1
    return n


def history(job_id: int) -> list[dict[str, Any]]:
    """Earlier postings at the same employer with the same or a very similar title, and how they went."""
    from . import stages

    with db.session() as s:
        j = s.get(Job, job_id)
        if j is None:
            return []
        company, title = norm_company(j.company), set(norm_title(j.title).split())
        out = []
        for o in s.query(Job).filter(Job.id != j.id, Job.duplicate_of.is_(None)):
            if norm_company(o.company) != company or o.id == j.duplicate_of:
                continue
            ot = set(norm_title(o.title).split())
            sim = len(title & ot) / max(1, len(title | ot))
            if sim < 0.6:
                continue
            a = o.application
            out.append({"id": o.id, "title": o.title, "term": o.term, "first_seen": o.first_seen.date().isoformat(), "same_title": sim == 1.0, "archived": o.archived_at is not None,
                        "applied": bool(a and a.submitted_at), **stages.describe(stages.stage(o.status, bool(o.online), o.deadline or "", a.status if a else None))})
        return sorted(out, key=lambda r: r["first_seen"], reverse=True)[:8]


def link_duplicates() -> int:
    """The same posting often arrives twice: once from PD Portal and once from the employer's own site.
    Two jobs are the same posting when their application links match, or the employer and the title match.
    One row stays the main one (the one already applied to, else the PD Portal row, else the older one);
    the others point at it with ``duplicate_of`` and drop out of lists, scoring and drafting."""
    n = 0
    window = int(db.get_setting("dedupe.window_days") or 150)
    with db.session() as s:
        jobs = s.query(Job).filter(Job.duplicate_of.is_(None), Job.archived_at.is_(None)).order_by(Job.id).all()
        groups: dict[str, list[Job]] = {}
        req_ids: dict[tuple[str, str], Job] = {}
        for j in jobs:
            keys = []
            if norm_url(j.apply_url):
                keys.append("u:" + norm_url(j.apply_url))
            if norm_company(j.company) and norm_title(j.title):
                # the term is left out on purpose: sources word it differently ("Summer 2027" vs "2027")
                keys.append(f"t:{norm_company(j.company)}|{norm_title(j.title)}")
            if j.source not in ("pdportal", "manual") and REQ_ID.fullmatch(j.source_id.split(":")[-1] or ""):
                req_ids[(norm_company(j.company), j.source_id.split(":")[-1].lower())] = j
            for k in keys:
                groups.setdefault(k, []).append(j)
        # a requisition number quoted on another row (in its note or link) names the same posting
        for (company, rid), official in req_ids.items():
            pat = re.compile(rf"(?<![a-z0-9]){re.escape(rid)}(?![a-z0-9])", re.I)
            for j in jobs:
                if j is not official and norm_company(j.company) == company and pat.search(f"{j.note or ''} {j.apply_url or ''}"):
                    groups.setdefault(f"r:{company}|{rid}", [official]).append(j)
        done: set[int] = set()
        for k, g in groups.items():
            g = [j for j in g if j.id not in done and j.duplicate_of is None]
            if len({j.source for j in g}) < 2:  # two rows from one source are two postings (same title, different teams)
                continue
            main = sorted(g, key=lambda j: (j.application is None, j.source != "pdportal", j.id))[0]
            for j in g:
                if j is main or j.application is not None:
                    continue
                if abs((j.first_seen - main.first_seen).days) > window:
                    continue  # same title a season later is a new posting, not another listing of the old one
                j.duplicate_of = main.id
                done.add(j.id)
                n += 1
                # the main row takes whatever the other listing knows better
                if not norm_url(main.apply_url) and norm_url(j.apply_url):
                    main.apply_url, main.ats, main.tenant = j.apply_url, j.ats, j.tenant
                if len(j.jd_text or "") > len(main.jd_text or ""):
                    main.jd_text = j.jd_text
                for f in ("location", "salary", "work_type", "posted"):
                    if not getattr(main, f) and getattr(j, f):
                        setattr(main, f, getattr(j, f))
    return n


def run(*, notify_user: bool = True) -> dict[str, Any]:
    st = db.all_settings()
    summary: dict[str, Any] = {"sources": {}, "errors": {}}
    if notify_user:
        from . import employers as _emp

        _emp.migrate_legacy()
        n_src = sum(1 for e in _emp.listing() if e.get("enabled", True)) + (1 if st["sources.pdportal"] else 0)
        notify.send("task_started", messages.discover_started(n_src), ref="discover")

    summary["intake"] = {}

    def one(name: str, source: str, rows_fn, scope: str | None, _stats: dict[str, Any] | None = None, **kw: Any) -> None:  # noqa: ANN001
        try:
            # Filtered listings cannot tell "taken down" from "no longer matches the rules": age them out instead.
            kw.setdefault("complete", False)
            kw.setdefault("stale_days", 5)
            if _stats is not None:          # fetched and screened already (side by side, above)
                stats = _stats
                summary["sources"][name] = upsert(rows_fn(), source=source, scope=scope, **kw)
            else:
                stats = {}
                summary["sources"][name] = upsert(intake.apply(rows_fn(), stats), source=source, scope=scope, **kw)
            summary["intake"][name] = stats
        except NeedsHuman:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("source %s failed: %s", name, e)
            summary["errors"][name] = f"{type(e).__name__}: {str(e)[:200]}"

    from . import employers

    employers.migrate_legacy()
    terms = [t for t in (st["sources.search_terms"] or []) if t.strip()] or ["intern"]
    keep = intake.keeper()
    # Fetching a listing is waiting for its site, and the sites are different ones: several are fetched at once
    # (sources.parallel). Storing what came back is done here, one source after the other - the database has one writer.
    from concurrent.futures import ThreadPoolExecutor

    from . import metering

    todo = [e for e in employers.listing() if e.get("enabled", True)]

    def fetch(e: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, dict[str, Any], BaseException | None]:
        stats: dict[str, Any] = {}
        try:
            return list(intake.apply(employers.rows_for(e, terms, keep), stats)), stats, None
        except BaseException as err:  # noqa: BLE001 - reported per source below
            return None, stats, err

    workers = max(1, min(8, int(st.get("sources.parallel") or 1)))
    if workers > 1 and len(todo) > 1:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="source") as pool:
            fetched = list(pool.map(metering.carried(fetch), todo))
    else:
        fetched = [fetch(e) for e in todo]
    needs_someone: NeedsHuman | None = None
    for e, (rows, stats, err) in zip(todo, fetched):
        source, scope = employers.source_of(e)
        if isinstance(err, NeedsHuman):
            needs_someone = needs_someone or err
            continue
        if err is not None:
            log.warning("source %s failed: %s", e["name"], err)
            summary["errors"][e["name"]] = f"{type(err).__name__}: {str(err)[:200]}"
            continue
        # a feed shows only a board's newest postings: one that has scrolled off it is usually still open, so it is given much longer
        extra = {"stale_days": 45} if e["kind"] == "feed" else {}
        one(e["name"], source, lambda rows=rows: rows, scope, _stats=stats, **extra)
    if needs_someone is not None:
        raise needs_someone
    if st["sources.pdportal"]:
        try:
            from .sources import pdportal

            summary["sources"]["pdportal"] = upsert(pdportal.scan(), source="pdportal")
        except NeedsHuman as e:
            summary["errors"]["pdportal"] = f"needs login: {e.reason}"
        except Exception as e:  # noqa: BLE001
            log.warning("pdportal failed: %s", e)
            summary["errors"]["pdportal"] = f"{type(e).__name__}: {str(e)[:200]}"

    summary["duplicates"] = link_duplicates()
    summary["archived"] = archive_old()
    tot = {k: sum(v[k] for v in summary["sources"].values()) for k in ("seen", "new", "back", "offline")}
    tot["read"] = sum(v.get("read", 0) for v in summary["intake"].values())
    summary["total"] = tot
    if tot["new"] or tot["back"]:
        from . import tasks

        tasks.enqueue("score", ref="unscored", priority=150)
    if notify_user:
        notify.send("task_result", messages.discover_done(tot, {k: v["new"] for k, v in summary["sources"].items()}, summary["errors"]), ref="discover")
    return summary


def add_manual(url: str, *, company: str = "", title: str = "", jd_text: str = "") -> int:
    """Paste-a-link intake."""
    from .ats import registry

    ref = registry.detect(url)
    with db.session() as s:
        j = s.query(Job).filter_by(source="manual", source_id=url).first()
        if j is None:
            j = Job(source="manual", source_id=url, status="new")
            s.add(j)
        j.apply_url, j.company, j.title, j.jd_text, j.channel = url, company or j.company, title or j.title, jd_text or j.jd_text, "employer site"
        if ref:
            j.ats, j.tenant = ref.ats, ref.tenant
        s.flush()
        return j.id
