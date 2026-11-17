"""Job sources with public JSON endpoints (no browser, no login)."""

from __future__ import annotations

import html
import re
from typing import Any, Iterator

import httpx

UA = {"User-Agent": "Mozilla/5.0 (job-search client)"}


def _text(h: str) -> str:
    t = re.sub(r"<(br|/p|/li|/h\d|/div)[^>]*>", "\n", html.unescape(h or ""), flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


def greenhouse(board: str) -> Iterator[dict[str, Any]]:
    r = httpx.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true", timeout=60, headers=UA)
    r.raise_for_status()
    for j in r.json().get("jobs", []):
        yield {
            "source": "greenhouse", "source_id": f"{board}:{j['id']}", "company": j.get("company_name") or board,
            "title": j.get("title", ""), "location": (j.get("location") or {}).get("name", ""),
            "apply_url": f"https://job-boards.greenhouse.io/{board}/jobs/{j['id']}", "ats": "greenhouse", "tenant": board,
            "jd_text": _text(j.get("content", "")), "channel": "employer site",
        }


def lever(company: str) -> Iterator[dict[str, Any]]:
    r = httpx.get(f"https://api.lever.co/v0/postings/{company}?mode=json", timeout=60, headers=UA)
    r.raise_for_status()
    for j in r.json():
        cats = j.get("categories") or {}
        body = "\n".join([j.get("descriptionPlain", "")] + [f"{x.get('text', '')}\n{_text(x.get('content', ''))}" for x in j.get("lists", [])] + [j.get("additionalPlain", "")])
        yield {
            "source": "lever", "source_id": f"{company}:{j['id']}", "company": company, "title": j.get("text", ""),
            "location": cats.get("location", ""), "work_type": cats.get("commitment", ""),
            "apply_url": j.get("applyUrl") or j.get("hostedUrl", ""), "ats": "lever", "tenant": company,
            "jd_text": body.strip(), "channel": "employer site",
        }


def ashby(board: str) -> Iterator[dict[str, Any]]:
    r = httpx.get(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true", timeout=60, headers=UA)
    r.raise_for_status()
    for j in r.json().get("jobs", []):
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        yield {
            "source": "ashby", "source_id": f"{board}:{j['id']}", "company": board, "title": j.get("title", ""),
            "location": j.get("location", ""), "work_type": j.get("employmentType", ""), "salary": comp,
            "apply_url": j.get("applyUrl") or j.get("jobUrl", ""), "ats": "ashby", "tenant": board,
            "jd_text": j.get("descriptionPlain") or _text(j.get("descriptionHtml", "")), "channel": "employer site",
        }


class Refused(RuntimeError):
    """The site's protection turned this computer's network away: a security check that wants a browser, not "busy" and not
    a sign-in. Asking again does not help and is not done - not for this address, and not for the others of the same service."""


_last: dict[str, float] = {}        # service -> when the last request to it was sent
_refused: dict[str, float] = {}     # service -> when it turned a request away with its security check
_locks: dict[str, Any] = {}
REFUSED_FOR = 6 * 3600              # seconds a service that refused is left alone
CHALLENGE = re.compile(r"security check|enable javascript and cookies|just a moment|attention required|cf-chl|verify you are human", re.I)


def service(host: str) -> str:
    """Whose servers a host is: "myworkdayjobs.com" for every employer's board on Workday. Requests are paced, and a refusal
    counts, for the service - an employer's board is only a name on it."""
    parts = (host or "").lower().split(":")[0].split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _send(c: httpx.Client, method: str, url: str, *, gap: float = 0.5, **kw: Any) -> httpx.Response:
    """One request, sent the way a site can live with: not sooner than ``gap`` seconds after the previous one to the same
    service - also when several sources are fetched side by side - and when the site says "too many requests" (429) or
    "busy" (503), wait as long as it asks (Retry-After), or longer each time when it does not say, and try again, three
    times at most. A security check in place of an answer is not "busy": it raises Refused at once, and the service is
    left alone for six hours."""
    import threading
    import time
    from urllib.parse import urlparse

    who = service(urlparse(url).netloc)
    since = _refused.get(who)
    if since is not None and time.monotonic() - since < REFUSED_FOR:
        raise Refused(f"{who} turned this computer's network away with a security check earlier; it is not asked again for a few hours")
    lock = _locks.setdefault(who, threading.Lock())
    r = None
    for attempt in range(4):
        with lock:
            wait = _last.get(who, 0) + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            r = c.request(method, url, **kw)
            _last[who] = time.monotonic()
        if r.status_code in (403, 429, 503) and "html" in r.headers.get("content-type", "") and CHALLENGE.search(r.text[:4000]):
            _refused[who] = time.monotonic()
            raise Refused(f"{who} answers with a security check (HTTP {r.status_code}) instead of its listing: its protection does not accept requests "
                          "from this computer's network address (often a proxy or VPN exit). This is not a sign-in problem and not a busy server")
        if r.status_code not in (429, 503) or attempt == 3:
            break
        asked = r.headers.get("Retry-After", "")
        time.sleep(min(90.0, float(asked)) if asked.replace(".", "", 1).isdigit() else 6.0 * 2 ** attempt)
    return r


def workday(host: str, tenant: str, site: str, *, search: str = "", limit: int = 200, keep=lambda *a: True, company: str = "") -> Iterator[dict[str, Any]]:  # noqa: ANN001
    """Workday candidate-experience JSON API (the same one the careers page calls).

    The list costs one request per twenty postings; a description costs one request each. Descriptions are fetched only
    for postings that are new here and that the intake rules would keep - a posting already in the library (with its
    description) is only marked as still online. A scan used to fetch all two hundred descriptions every time, back to
    back, and sites answered 429."""
    from .. import db
    from ..models import Job

    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    hdr = {**UA, "Accept": "application/json", "Content-Type": "application/json"}
    with db.session() as s:
        known = {j.source_id for j in s.query(Job.source_id).filter(Job.source == "workday", Job.source_id.like(f"{tenant}:%"), Job.jd_text != "")}
    offset = 0
    with httpx.Client(timeout=60, headers=hdr) as c:
        while offset < limit:
            r = _send(c, "POST", f"{base}/jobs", json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": search})
            r.raise_for_status()
            posts = r.json().get("jobPostings", [])
            if not posts:
                break
            for p in posts:
                path = p.get("externalPath", "")
                tail = path.rsplit("_", 1)[-1]
                ids = [f"{tenant}:{x}" for x in (*(str(b) for b in p.get("bulletFields") or []), tail, re.sub(r"-\d+$", "", tail)) if x]
                row = {"source": "workday", "title": p.get("title", ""), "location": p.get("locationsText", ""),
                       "apply_url": f"https://{host}/en-US/{site}{path}", "ats": "workday", "tenant": host.split(".myworkday")[0], "channel": "employer site"}
                have = next((i for i in ids if i in known), None)
                if have:      # already read: it is still online, and that is all a scan has to find out
                    yield {**row, "source_id": have}
                    continue
                if not keep(row["title"], row["location"]):      # not a posting the applicant's rules would take: no request for its text
                    yield {**row, "source_id": ids[0] if ids else f"{tenant}:{path}", "company": company or tenant}
                    continue
                d = _send(c, "GET", f"{base}{path}")
                info = d.json().get("jobPostingInfo", {}) if d.status_code == 200 else {}
                yield {
                    **row, "source_id": f"{tenant}:{info.get('jobReqId') or tail}",
                    "company": ((d.json().get("hiringOrganization") or {}).get("name") if d.status_code == 200 else "") or company or tenant,
                    "work_type": info.get("timeType", ""), "jd_text": _text(info.get("jobDescription", "")),
                }
            offset += 20


def smartrecruiters(company: str, keep=lambda *a: True, limit: int = 300) -> Iterator[dict[str, Any]]:  # noqa: ANN001
    """SmartRecruiters' public postings API. Descriptions are fetched only for postings the intake rules would keep."""
    base = f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
    offset = 0
    with httpx.Client(timeout=60, headers=UA) as c:
        while offset < limit:
            r = c.get(base, params={"limit": 100, "offset": offset})
            r.raise_for_status()
            rows = r.json().get("content", [])
            if not rows:
                break
            for p in rows:
                loc = p.get("location") or {}
                where = ", ".join(x for x in (loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()) if x)
                row = {"source": "smartrecruiters", "source_id": f"{company}:{p['id']}", "company": (p.get("company") or {}).get("name") or company, "title": p.get("name", ""),
                       "location": where, "apply_url": f"https://jobs.smartrecruiters.com/{company}/{p['id']}", "ats": "smartrecruiters", "tenant": company,
                       "channel": "employer site", "posted": (p.get("releasedDate") or "")[:10]}
                if keep(row["title"], where):
                    d = c.get(f"{base}/{p['id']}")
                    if d.status_code == 200:
                        sec = (d.json().get("jobAd") or {}).get("sections") or {}
                        row["jd_text"] = "\n\n".join(_text((v or {}).get("text", "")) for v in sec.values() if isinstance(v, dict))
                yield row
            offset += 100


# --- job feeds (RSS / Atom) -------------------------------------------------------------------
# Many field job boards (academic, medical, design, public job banks) publish their newest postings as a feed.
# A feed is read without a browser and without AI; one feed carries postings of many employers.

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_feed(xml_text: str) -> list[dict[str, str]]:
    """Items of an RSS or Atom document: title, link, summary (plain text), date (YYYY-MM-DD or ''), author, id."""
    import hashlib
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    root = ET.fromstring(xml_text.lstrip().encode("utf-8"))
    out = []
    for it in root.iter():
        if _local(it.tag) not in ("item", "entry"):
            continue
        d: dict[str, str] = {}
        for c in it:
            k = _local(c.tag)
            if k == "link":
                d.setdefault("link", (c.text or "").strip() or c.attrib.get("href", ""))
            elif k in ("title", "guid", "id", "pubdate", "published", "updated", "date", "description", "summary", "content", "encoded", "creator", "location"):
                d.setdefault(k, (c.text or "").strip())
            elif k == "author":
                d.setdefault("author", (c.text or "").strip() or next(((x.text or "").strip() for x in c if _local(x.tag) == "name"), ""))
        when = d.get("pubdate") or d.get("published") or d.get("updated") or d.get("date") or ""
        try:
            day = parsedate_to_datetime(when).date().isoformat() if when and not re.match(r"\d{4}-\d{2}-\d{2}", when) else when[:10]
        except (TypeError, ValueError):
            day = ""
        link = d.get("link", "")
        if not d.get("title") or not link.startswith("http"):
            continue
        out.append({"title": re.sub(r"\s+", " ", html.unescape(d["title"])).strip(), "link": link, "date": day, "author": d.get("creator") or d.get("author") or "",
                    "summary": _text(d.get("encoded") or d.get("content") or d.get("description") or d.get("summary") or "")[:8000], "location": d.get("location", ""),
                    "id": hashlib.sha1((d.get("guid") or d.get("id") or link).encode()).hexdigest()[:16]})
    return out


def split_title(title: str, style: str) -> tuple[str, str]:
    """(employer, job title) from a feed item's title. ``style`` says how the board writes it:
    "employer: title" (most boards), "title, employer", "employer is hiring title", or "" when the title is only the job."""
    if style == "employer: title" and ": " in title:
        emp, _, job = title.partition(": ")
        if 1 < len(emp) <= 90 and job:
            return emp.strip(), job.strip()
    if style == "title, employer" and ", " in title:
        job, _, emp = title.rpartition(", ")
        if job and 1 < len(emp) <= 90:
            return emp.strip(), job.strip()
    if style == "employer is hiring title":
        m = re.match(r"^(.{2,90}?) is (?:hiring|seeking|looking for)(?: for)?(?: an?| the)?(?: position of)? (.+)$", title, re.I)
        if m:
            return m.group(1).strip(), m.group(2).strip()
    return "", title


def feed(url: str, board: str, scope: str, style: str = "employer: title") -> Iterator[dict[str, Any]]:
    from urllib.parse import urlparse

    with httpx.Client(timeout=40, follow_redirects=True, headers={**UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}) as c:
        r = c.get(url)
        r.raise_for_status()
    body = r.text.lstrip()
    if not re.match(r"<\?xml|<rss|<feed|<rdf", body[:300], re.I):
        raise RuntimeError("这个地址返回的不是职位订阅源（RSS / Atom）")
    host = urlparse(url).netloc.removeprefix("www.")
    for it in parse_feed(body):
        emp, job = split_title(it["title"], style)
        yield {"source": "feed", "source_id": f"{scope}:{it['id']}", "company": emp or it["author"] or board, "title": job, "location": it["location"], "apply_url": it["link"],
               "tenant": scope, "channel": f"job board ({board or host})", "posted": it["date"], "jd_text": it["summary"]}
