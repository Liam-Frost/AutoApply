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


def workday(host: str, tenant: str, site: str, *, search: str = "", limit: int = 200) -> Iterator[dict[str, Any]]:
    """Workday candidate-experience JSON API (the same one the careers page calls)."""
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    hdr = {**UA, "Accept": "application/json", "Content-Type": "application/json"}
    offset = 0
    with httpx.Client(timeout=60, headers=hdr) as c:
        while offset < limit:
            r = c.post(f"{base}/jobs", json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": search})
            r.raise_for_status()
            posts = r.json().get("jobPostings", [])
            if not posts:
                break
            for p in posts:
                path = p.get("externalPath", "")
                d = c.get(f"{base}{path}")
                info = d.json().get("jobPostingInfo", {}) if d.status_code == 200 else {}
                yield {
                    "source": "workday", "source_id": f"{tenant}:{info.get('jobReqId') or path.rsplit('_', 1)[-1]}",
                    "company": (d.json().get("hiringOrganization") or {}).get("name", tenant) if d.status_code == 200 else tenant,
                    "title": p.get("title", ""), "location": p.get("locationsText", ""),
                    "work_type": info.get("timeType", ""),
                    "apply_url": f"https://{host}/en-US/{site}{path}", "ats": "workday", "tenant": host.split(".myworkday")[0],
                    "jd_text": _text(info.get("jobDescription", "")), "channel": "employer site",
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
