"""Career sites of the large tech employers. Each has its own listing API, so each gets a small
adapter; they all yield the same row shape as ``sources.public``.

Every adapter searches the site with the user's search terms (``sources.search_terms``) and
de-duplicates by the site's own job id. What is kept is decided afterwards by the intake rules
(``intake.py``) - these sites list thousands of roles and almost none are relevant.

| key       | how the list is read                                              |
|-----------|-------------------------------------------------------------------|
| amazon    | amazon.jobs search JSON                                           |
| apple     | jobs.apple.com search API (+ detail API for the description)      |
| google    | careers results page; the jobs are embedded as JSON in the HTML   |
| microsoft | Eightfold "pcsx" API on apply.careers.microsoft.com               |
| nvidia    | Eightfold "pcsx" API on nvidia.eightfold.ai                       |
| amd       | careers.amd.com (Jibe) JSON                                       |
| intel     | Workday (intel.wd1) - via sources.public.workday                  |
| meta      | no public API: the rendered search page is read in a browser      |
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

import httpx

from .public import UA, _text, workday

NAMES = {"amazon": "Amazon", "apple": "Apple", "google": "Google", "microsoft": "Microsoft", "meta": "Meta", "nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel"}
Keep = Callable[[str, str], bool]


def _all(title: str, location: str = "") -> bool:
    return True


HDR = {**UA, "Accept": "application/json", "Accept-Language": "en-US,en;q=0.9"}
MAX_PER_TERM = 200  # per site and search term; the newest / most relevant come first


def _row(key: str, sid: str, title: str, url: str, *, location: str = "", jd: str = "", posted: str = "", ats: str = "", work_type: str = "") -> dict[str, Any]:
    return {"source": key, "source_id": str(sid), "company": NAMES[key], "title": re.sub(r"\s+", " ", title).strip(), "location": location, "work_type": work_type,
            "apply_url": url, "ats": ats or key, "tenant": key, "jd_text": jd, "channel": "employer site", "posted": posted}


def _client() -> httpx.Client:
    return httpx.Client(timeout=45, headers=HDR, follow_redirects=True)


def _get(c: httpx.Client, url: str, **kw: Any) -> httpx.Response:
    """GET with one polite retry on 429 / 5xx."""
    for attempt in (1, 2, 3):
        r = c.get(url, **kw)
        if r.status_code in (429, 500, 502, 503) and attempt < 3:
            time.sleep(4 * attempt)
            continue
        r.raise_for_status()
        return r
    raise AssertionError("unreachable")


# --- Amazon -----------------------------------------------------------------------------

def amazon(terms: list[str], keep: Keep = _all) -> Iterator[dict[str, Any]]:
    with _client() as c:
        for q in terms:
            for offset in range(0, MAX_PER_TERM, 100):
                d = _get(c, "https://www.amazon.jobs/en/search.json", params={"base_query": q, "result_limit": 100, "offset": offset, "sort": "recent"}).json()
                jobs = d.get("jobs", [])
                for j in jobs:
                    jd = "\n\n".join(x for x in (_text(j.get("description", "")), "Basic qualifications\n" + _text(j.get("basic_qualifications", "")),
                                                 "Preferred qualifications\n" + _text(j.get("preferred_qualifications", ""))) if x.strip())
                    yield _row("amazon", j.get("id_icims") or j["id"], j.get("title", ""), "https://www.amazon.jobs" + j.get("job_path", ""),
                               location=j.get("normalized_location") or j.get("location", ""), jd=jd, posted=_date(j.get("posted_date", "")), work_type=j.get("job_schedule_type", ""))
                if len(jobs) < 100:
                    break


# --- Eightfold (Microsoft, NVIDIA) ---------------------------------------------------------

def eightfold(key: str, host: str, domain: str, terms: list[str], keep: Keep = _all) -> Iterator[dict[str, Any]]:
    with _client() as c:
        for q in terms:
            start = 0
            while start < MAX_PER_TERM:
                d = _get(c, f"https://{host}/api/pcsx/search", params={"domain": domain, "query": q, "start": start, "sort_by": "timestamp"}).json().get("data", {})
                pos = d.get("positions", [])
                for p in pos:
                    jd = ""
                    loc0 = "; ".join(p.get("standardizedLocations") or p.get("locations") or [])
                    try:
                        if not keep(p.get("name", ""), loc0):
                            raise httpx.HTTPError("skipped")  # not a candidate: do not spend a request on its description
                        det = _get(c, f"https://{host}/api/pcsx/position_details", params={"position_id": p["id"], "domain": domain, "hl": "en"}).json().get("data", {})
                        jd = _text(det.get("jobDescription", ""))
                    except httpx.HTTPError:
                        pass  # the list row is still worth keeping; it stays unscored until a description is read
                    yield _row(key, p.get("displayJobId") or p["id"], p.get("name", ""), f"https://{host}{p.get('positionUrl', '')}",
                               location=loc0, jd=jd, posted=_ts(p.get("postedTs")), ats="eightfold", work_type=p.get("workLocationOption", ""))
                    if jd:
                        time.sleep(0.4)
                start += len(pos)
                if not pos or start >= int(d.get("count", 0)):
                    break
                time.sleep(1)


def microsoft(terms: list[str], keep: Keep = _all) -> Iterator[dict[str, Any]]:
    return eightfold("microsoft", "apply.careers.microsoft.com", "microsoft.com", terms, keep)


def nvidia(terms: list[str], keep: Keep = _all) -> Iterator[dict[str, Any]]:
    return eightfold("nvidia", "nvidia.eightfold.ai", "nvidia.com", terms, keep)


# --- AMD (Jibe) -----------------------------------------------------------------------------

def amd(terms: list[str], keep: Keep = _all) -> Iterator[dict[str, Any]]:
    with _client() as c:
        for q in terms:
            for page in range(1, MAX_PER_TERM // 100 + 1):
                d = _get(c, "https://careers.amd.com/api/jobs", params={"keywords": q, "limit": 100, "page": page, "sortBy": "posted_date", "descending": "true"}).json()
                jobs = d.get("jobs", [])
                for it in jobs:
                    j = it.get("data", {})
                    jd = "\n\n".join(_text(j.get(k, "")) for k in ("description", "responsibilities", "qualifications") if j.get(k))
                    yield _row("amd", j.get("req_id") or j["slug"], j.get("title", ""), f"https://careers.amd.com/careers-home/jobs/{j['slug']}",
                               location=j.get("full_location") or j.get("location_name", ""), jd=jd, posted=(j.get("posted_date") or "")[:10], ats="icims", work_type=j.get("employment_type", ""))
                if len(jobs) < 100:
                    break


# --- Apple ----------------------------------------------------------------------------------

def apple(terms: list[str], keep: Keep = _all) -> Iterator[dict[str, Any]]:
    fmt = {"longDate": "MMMM D, YYYY", "mediumDate": "MMM D, YYYY"}
    with _client() as c:
        for q in terms:
            for page in range(1, MAX_PER_TERM // 20 + 1):
                r = c.post("https://jobs.apple.com/api/v1/search", json={"query": q, "filters": {}, "page": page, "locale": "en-us", "sort": "relevance", "format": fmt})
                r.raise_for_status()
                res = r.json().get("res", {}).get("searchResults", [])
                for j in res:
                    jd = j.get("jobSummary", "")
                    locs = "; ".join(x.get("name", "") for x in j.get("locations") or [])
                    try:
                        if not keep(j.get("postingTitle", ""), locs):
                            raise httpx.HTTPError("skipped")
                        det = _get(c, f"https://jobs.apple.com/api/v1/jobDetails/{j['id']}", params={"locale": "en-us"}).json().get("res", {})
                        jd = "\n\n".join(x for x in (det.get("jobSummary", ""), det.get("description", ""), "Minimum qualifications\n" + (det.get("minimumQualifications") or ""),
                                                     "Preferred qualifications\n" + (det.get("preferredQualifications") or "")) if x.strip() and not x.strip().endswith("qualifications"))
                    except httpx.HTTPError:
                        pass
                    yield _row("apple", j.get("positionId") or j["id"], j.get("postingTitle", ""),
                               f"https://jobs.apple.com/en-us/details/{j.get('positionId') or j['id']}/{j.get('transformedPostingTitle', '')}",
                               location=locs, jd=_text(jd), posted=(j.get("postDateInGMT") or "")[:10])
                    time.sleep(0.2)
                if len(res) < 20:
                    break


# --- Google ---------------------------------------------------------------------------------

_GDATA = re.compile(r"AF_initDataCallback\(\{key: 'ds:1', hash: '[^']*', data:(.*?), sideChannel: \{\}\}\);", re.S)


def google(terms: list[str], keep: Keep = _all) -> Iterator[dict[str, Any]]:
    """The results page embeds the jobs as a JSON array: [id, title, apply link, responsibilities,
    qualifications, _, _, company, locale, locations, about, ..., [posted secs, nanos], ...]."""
    with _client() as c:
        for q in terms:
            for page in range(1, MAX_PER_TERM // 20 + 1):
                h = _get(c, "https://www.google.com/about/careers/applications/jobs/results/", params={"q": q, "page": page, "sort_by": "date"}, headers={"Accept": "text/html"}).text
                m = _GDATA.search(h)
                if not m:
                    break
                d = json.loads(m.group(1))
                jobs = d[0] or []
                for j in jobs:
                    part = lambda i: _text(j[i][1]) if len(j) > i and j[i] and len(j[i]) > 1 and j[i][1] else ""  # noqa: E731
                    jd = "\n\n".join(x for x in (part(10), "Responsibilities\n" + part(3), part(4), part(18)) if x.strip() and x.strip() != "Responsibilities")
                    slug = re.sub(r"[^a-z0-9]+", "-", j[1].lower()).strip("-")
                    yield _row("google", j[0], j[1], f"https://www.google.com/about/careers/applications/jobs/results/{j[0]}-{slug}",
                               location="; ".join(x[0] for x in (j[9] or []) if x), jd=jd, posted=_ts(j[12][0] if len(j) > 12 and j[12] else None))
                if len(jobs) < 20:
                    break
                time.sleep(1)


# --- Intel (Workday) ------------------------------------------------------------------------

def intel(terms: list[str], keep: Keep = _all) -> Iterator[dict[str, Any]]:
    seen: set[str] = set()
    for q in terms:
        for r in workday("intel.wd1.myworkdayjobs.com", "intel", "External", search=q, limit=MAX_PER_TERM):
            if r["source_id"] in seen:
                continue
            seen.add(r["source_id"])
            yield {**r, "source": "intel", "company": "Intel"}


# --- Meta -----------------------------------------------------------------------------------

def meta(terms: list[str], keep: Keep = _all) -> Iterator[dict[str, Any]]:
    """Meta has no public listing API; the search page fills in its results with scripts. Read the
    rendered page in an ordinary headless browser. If the site refuses it, the error says so."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            page = b.new_context(locale="en-US").new_page()
            found: dict[str, dict[str, str]] = {}
            for q in terms:
                for pg in range(1, MAX_PER_TERM // 20 + 1):
                    page.goto(f"https://www.metacareers.com/jobsearch/?q={q}&page={pg}", wait_until="domcontentloaded", timeout=45000)
                    try:
                        page.wait_for_selector("a[href*='/profile/job_details/']", timeout=20000)
                    except Exception as e:  # noqa: BLE001
                        if pg == 1 and not found:
                            raise RuntimeError("Meta's careers page did not show any results to an automated browser") from e
                        break
                    page.wait_for_timeout(800)
                    cards = page.evaluate(r"""() => [...document.querySelectorAll("a[href*='/profile/job_details/']")].map(a => {
                        const id = (a.getAttribute('href').match(/(\d{8,})/) || [])[1];
                        const lines = a.innerText.split('\n').map(x => x.trim()).filter(x => x && x !== '⋅');
                        return id ? { id, href: a.href, title: lines[0] || '', rest: lines.slice(1).join('; ') } : null; }).filter(Boolean)""")
                    new = [cdt for cdt in cards if cdt["id"] not in found]
                    for cdt in new:
                        found[cdt["id"]] = cdt
                    if not new:
                        break
            for cdt in found.values():
                jd = ""
                loc = cdt["rest"][:200]
                if keep(cdt["title"], loc):  # only candidates are opened for their description
                    try:
                        page.goto(cdt["href"], wait_until="domcontentloaded", timeout=45000)
                        page.wait_for_timeout(1500)
                        jd = _text(page.inner_text("body"))[:12000]
                    except Exception:  # noqa: BLE001
                        jd = ""
                yield _row("meta", cdt["id"], cdt["title"], cdt["href"].split("?")[0], location=loc, jd=jd)
        finally:
            b.close()


# --- registry -------------------------------------------------------------------------------

SITES: dict[str, Callable[..., Iterator[dict[str, Any]]]] = {
    "amazon": amazon, "apple": apple, "google": google, "microsoft": microsoft, "meta": meta, "nvidia": nvidia, "amd": amd, "intel": intel,
}


def scan(key: str, terms: list[str], keep: Keep = _all) -> Iterator[dict[str, Any]]:
    """Rows from one site for all search terms, each job once."""
    seen: set[str] = set()
    for r in SITES[key](terms, keep):
        if r["source_id"] in seen or not r["title"]:
            continue
        seen.add(r["source_id"])
        yield r


def _ts(sec: Any) -> str:
    try:
        return datetime.fromtimestamp(int(sec), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return ""


def _date(s: str) -> str:
    for f in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(re.sub(r"\s+", " ", s.strip()), f).date().isoformat()
        except ValueError:
            continue
    return ""
