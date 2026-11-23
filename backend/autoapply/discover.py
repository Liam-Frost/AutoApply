"""Discovery: pull every configured source, upsert jobs, track online/offline.

A failing source never fails the scan; its error is reported in the summary.
"""

from __future__ import annotations

from .say import say as T

import logging
import re
from typing import Any, Iterable

from . import db, fulltext, intake, messages, notify
from .errors import NeedsHuman
from .models import Job, now
from .sources import bigtech, public

log = logging.getLogger("autoapply.discover")

FIELDS = ("company", "title", "location", "work_type", "salary", "apply_url", "ats", "tenant", "jd_text", "channel",
          "term", "months", "deadline", "docs_required", "posted")


def upsert(rows: Iterable[dict[str, Any]], *, source: str, scope: str | None = None, complete: bool = True, stale_days: int = 0) -> dict[str, int]:
    """Store what one listing showed, and take offline what it has stopped showing.

    A posting goes offline on the word of its own listing and of nothing else. ``scope`` names that listing among the
    ones a source has (a board, a tenant, a watched page); without it the source is one listing (PD Portal).

    - a ``complete`` listing: what it does not show is gone, now;
    - a capped or filtered one (``stale_days``): a posting it has not shown for that many days of looking is taken to
      be gone. The days run from the first reading that did not show it (``missed_since``), not from when it was last
      seen - a listing that could not be read for a week has said nothing in that week;
    - neither: a partial reading, which says nothing about what it does not show.

    Reading board A is not a reading of board B: both rules look only at the postings of this listing. (The second one
    did not: every successful reading of one employer aged out the postings of all the others on the same service,
    whether or not theirs had been read.)"""
    from datetime import timedelta

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
            # A source that gives only a summary lists the posting again at every scan - with the summary. Once the text
            # was read from the posting's own page (fulltext.complete says so on the posting: "whole", or "cut" when the
            # page was longer than is kept), the summary does not replace it. Nothing else is taken for that: a posting
            # from before texts were marked has no mark, and its text may be a teaser like any other.
            partial = str(r.get("jd_partial") or "")
            keep_text = partial == "summary" and j.jd_partial in fulltext.FROM_PAGE and bool((j.jd_text or "").strip())
            edited = dict(j.edited or {})
            for f in FIELDS:
                v = r.get(f)
                if not v or (f == "jd_text" and keep_text):
                    continue
                if f in edited:      # the applicant corrected it: theirs stays; what the source says now is kept to show them
                    edited[f] = v
                    continue
                setattr(j, f, v)
            if edited != (j.edited or {}):
                j.edited = edited
            if r.get("jd_text") and not keep_text and "jd_text" not in edited:
                j.jd_partial = partial
            if scope and not j.tenant:
                j.tenant = scope        # which listing it belongs to is how it is found again below
            j.last_seen = now()
            j.missed_since = None
        if complete or stale_days:
            q = s.query(Job).filter(Job.source == source, Job.online == 1)
            if scope:
                q = q.filter(Job.tenant == scope)
            cut = (now() - timedelta(days=stale_days)).replace(tzinfo=None)
            for j in q:
                if j.source_id in seen:
                    continue
                if not complete:
                    if j.missed_since is None:
                        j.missed_since = now()
                        continue
                    if j.missed_since.replace(tzinfo=None) > cut:
                        continue
                j.online = 0
                offline += 1
                # keep applied jobs' status; only undecided ones become "offline"
                if j.application is None and j.status in ("new", "scored", "queued"):
                    j.status = "offline"
    return {"seen": seen_n, "new": new, "back": back, "offline": offline}


_CORP = re.compile(r"\b(inc|incorporated|corp|corporation|ltd|limited|llc|co|company|canada|ulc|technologies|technology|systems)\b\.?", re.I)


def norm_company(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _CORP.sub(" ", (name or "").lower())).strip()


# A posting's other fields glued to the company's name when a page's text ran together ("Ballard Power Systems" +
# "Department: Research ..." + "Work Term: ..."): the labels a co-op portal and career pages put before them.
_GLUED = re.compile(r"(?:Department|Division|Work Term|Co-op Work Term|Contact|Work Type|Job Title|Title|Job Location|Location|Organization|Address|"
                    r"Salary(?: \(\$\))?|Website|Application Deadline)\s*:", re.I)


def company_name(name: str) -> str:
    """A company as it is shown: the name before the first field of the posting glued to it, as written otherwise.
    What was kept is not changed - this is how it is read."""
    text = " ".join(str(name or "").split())
    m = _GLUED.search(text)
    return (text[: m.start()].strip(" -–—·|,;") if m and m.start() > 0 else text)[:200]


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

    from . import context

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
            fetched = list(pool.map(context.carried(fetch), todo))
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
            from .sources.public import Refused, Resting

            if isinstance(err, Refused):       # the same answer for every board of that service: said once
                who = str(err).split(" ", 1)[0]
                summary.setdefault("refused", {}).setdefault(who, []).append(e["name"])
                summary["errors"][e["name"]] = T("server.discover.theSitesSecurityCheck", p0=who)
            elif isinstance(err, Resting):     # the service asked for fewer requests: its boards wait for the next scan
                summary.setdefault("resting", {}).setdefault(err.who, []).append(e["name"])
                summary["errors"][e["name"]] = T("server.discover.theServiceAskedFor", p0=err.who)
            else:
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
    remember(summary)
    tot = {k: sum(v[k] for v in summary["sources"].values()) for k in ("seen", "new", "back", "offline")}
    tot["read"] = sum(v.get("read", 0) for v in summary["intake"].values())
    summary["total"] = tot
    if tot["new"] or tot["back"]:
        from . import tasks

        tasks.enqueue("score", ref="unscored", priority=150)
    if notify_user:
        notify.send("task_result", messages.discover_done(tot, {k: v["new"] for k, v in summary["sources"].items()}, summary["errors"]), ref="discover")
    return summary


def remember(summary: dict[str, Any]) -> None:
    """Keep, per source, what this scan read from it and why the rest was not taken in - and when it could last be read.

    The result of a scan lived in the task that ran it: the page showed the latest scan and nothing else, so a source
    that fails today showed an error and no sign of when it last worked or what it gave then. "It read a lot and there
    is nothing to apply for" could not be traced to a reason beyond the latest run either. Counts only: the postings
    that were dropped are not kept."""
    at = now().isoformat()
    hist = dict(db.get_setting("sources.history") or {})
    for name in set(summary.get("sources", {})) | set(summary.get("errors", {})) | set(summary.get("intake", {})):
        row = dict(hist.get(name) or {})
        err = summary.get("errors", {}).get(name, "")
        row["last_at"] = at
        if err:
            row.update(error=str(err)[:300], error_at=at, fails=int(row.get("fails", 0)) + 1)
        else:
            st, ik = summary.get("sources", {}).get(name, {}), summary.get("intake", {}).get(name, {})
            row.update(ok_at=at, error="", error_at="", fails=0, read=int(ik.get("read", st.get("seen", 0))), kept=int(ik.get("kept", st.get("seen", 0))),
                       new=int(st.get("new", 0)), dropped={k: int(v) for k, v in (ik.get("dropped") or {}).items()}, screened="read" in ik)
        hist[name] = row
    # a source that is gone from the list and was not read for a month is forgotten
    from datetime import timedelta

    old = (now() - timedelta(days=30)).isoformat()
    db.set_setting("sources.history", {k: v for k, v in hist.items() if str(v.get("last_at") or "") >= old})


def report() -> dict[str, Any]:
    """For every source that is read: when it last could be read, what it gave then, why the rest was dropped, and where
    the postings it gave stand now - enough for the line, not enough, ruled out, not scored yet."""
    from . import employers, intake

    st = db.all_settings()
    hist = dict(st["sources.history"] or {})
    from . import scoring

    line = scoring.draft_line()      # the queue's own line, posting by posting: what is counted here is what gets a draft there
    with db.session() as s:
        # (source, listing, score, status, ruled out, the line this posting is held to)
        jobs = [(j.source, j.tenant or "", j.score, j.status, bool(j.exclusion), line(j.company, j.source))
                for j in s.query(Job).filter(Job.online == 1, Job.duplicate_of.is_(None), Job.archived_at.is_(None))]

    def stand(mine: list[tuple[Any, ...]]) -> dict[str, int]:
        return {"total": len(mine), "unscored": sum(1 for j in mine if j[2] is None), "excluded": sum(1 for j in mine if j[2] is not None and (j[4] or j[3] == "skipped")),
                "below": sum(1 for j in mine if j[2] is not None and not (j[4] or j[3] == "skipped") and j[2] < j[5]),
                "above": sum(1 for j in mine if j[2] is not None and not (j[4] or j[3] == "skipped") and j[2] >= j[5])}

    def row(name: str, label: str, mine: list[tuple[Any, ...]], own: float, **more: Any) -> dict[str, Any]:
        """``own``: the line a posting of this employer is held to - what the row says when it has no postings now."""
        h = hist.get(name) or {}
        dropped = [{"key": k, "label": intake.REASONS.get(k, k), "n": n} for k, n in sorted((h.get("dropped") or {}).items(), key=lambda kv: -kv[1])]
        lines = sorted({j[5] for j in mine}) or [own]      # more than one on a board that lists several employers, some of them priority
        return {"name": name, "label": label, "ok_at": h.get("ok_at") or None, "error": h.get("error") or "", "error_at": h.get("error_at") or None, "fails": int(h.get("fails", 0)),
                "read": h.get("read"), "kept": h.get("kept"), "new": h.get("new"), "screened": bool(h.get("screened")), "dropped": dropped, "now": stand(mine),
                "line": lines[0], "lines": lines, **more}

    rows = []
    for e in employers.listing():
        if not e.get("enabled", True):
            continue
        src, scope = employers.source_of(e)
        mine = [j for j in jobs if j[0] == src and (scope is None or j[1] == scope)]
        rows.append(row(e["name"], employers.KIND_LABEL.get(e["kind"], e["kind"]), mine, line(e["name"], src), priority=bool(e.get("priority"))))
    if st["sources.pdportal"]:
        rows.append(row("pdportal", "UBC PD Portal", [j for j in jobs if j[0] == "pdportal"], line("", "pdportal"), priority=False, exempt=True))
    last = max((str(h.get("last_at") or "") for h in hist.values()), default="") or None
    total: dict[str, int] = {}
    for r in rows:
        for d in r["dropped"]:
            total[d["key"]] = total.get(d["key"], 0) + d["n"]
    return {"at": last, "sources": rows,
            "total": {"read": sum(int(r["read"] or 0) for r in rows), "kept": sum(int(r["kept"] or 0) for r in rows), "new": sum(int(r["new"] or 0) for r in rows),
                      "dropped": [{"key": k, "label": intake.REASONS.get(k, k), "n": n} for k, n in sorted(total.items(), key=lambda kv: -kv[1])],
                      "now": {k: sum(r["now"][k] for r in rows) for k in ("total", "unscored", "excluded", "below", "above")}}}


def add_manual(url: str, *, company: str = "", title: str = "", jd_text: str = "") -> int:
    """Paste-a-link intake."""
    from . import sites

    system, tenant = sites.where(url)
    with db.session() as s:
        j = s.query(Job).filter_by(source="manual", source_id=url).first()
        if j is None:
            j = Job(source="manual", source_id=url, status="new")
            s.add(j)
        j.apply_url, j.company, j.title, j.jd_text, j.channel = url, company or j.company, title or j.title, jd_text or j.jd_text, "employer site"
        j.ats, j.tenant = system or "generic", tenant
        s.flush()
        return j.id
