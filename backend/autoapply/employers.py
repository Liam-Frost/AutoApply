"""The employers the user wants watched - their own list, not a fixed one.

An employer is added by name and careers-page address. From the address the program works out how to
read that employer's postings:

* one of the career sites with a purpose-built reader (``builtin``);
* a public job-board API: Greenhouse, Lever, Ashby, SmartRecruiters, Workday (``board``);
* anything else: the careers page is opened and the model picks the postings out of its links (``page``).

Employers can be marked as priority: their postings are starred, sorted first, and get an application
draft at a lower score than the rest.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Iterator
from urllib.parse import parse_qs, urlparse

from . import db

BUILTIN_HOSTS = {  # host suffix -> reader in sources/bigtech.py
    "amazon.jobs": "amazon", "jobs.apple.com": "apple", "google.com/about/careers": "google", "careers.google.com": "google",
    "careers.microsoft.com": "microsoft", "jobs.careers.microsoft.com": "microsoft", "metacareers.com": "meta",
    "nvidia.eightfold.ai": "nvidia", "nvidia.com": "nvidia", "careers.amd.com": "amd", "amd.com": "amd", "jobs.intel.com": "intel", "intel.com": "intel",
}
BUILTIN_NAMES = {"amazon": "Amazon", "apple": "Apple", "google": "Google", "microsoft": "Microsoft", "meta": "Meta", "nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel"}
KIND_LABEL = {"builtin": "官网（已专门适配）", "greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "smartrecruiters": "SmartRecruiters", "workday": "Workday",
              "page": "招聘页（由 AI 读取）", "feed": "职位站订阅源（RSS）"}
FEED_URL = re.compile(r"(/jobsrss/?|/rss/?|/feed/?|\.rss|\.atom|[?&](format|display)=rss|rss--|job-?feed|rssfeed)([?#]|$)", re.I)


def detect(url: str) -> dict[str, Any]:
    """How to read the postings behind a careers-page address: {"kind", "ref"}."""
    u = urlparse(url if "//" in url else "https://" + url)
    host, path = u.netloc.lower().removeprefix("www."), u.path.strip("/")
    parts = [p for p in path.split("/") if p]
    for suffix, key in BUILTIN_HOSTS.items():
        h, _, p = suffix.partition("/")
        if (host == h or host.endswith("." + h)) and (not p or path.startswith(p)):
            return {"kind": "builtin", "ref": {"key": key}}
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io") and parts:
        return {"kind": "greenhouse", "ref": {"board": parts[1] if parts[0] == "embed" and len(parts) > 1 else parts[0]}}
    if host == "jobs.lever.co" and parts:
        return {"kind": "lever", "ref": {"company": parts[0]}}
    if host == "jobs.ashbyhq.com" and parts:
        return {"kind": "ashby", "ref": {"board": parts[0]}}
    if host in ("careers.smartrecruiters.com", "jobs.smartrecruiters.com") and parts:
        return {"kind": "smartrecruiters", "ref": {"company": parts[0]}}
    m = re.match(r"^([a-z0-9-]+)\.(wd\d+)\.myworkday(?:jobs|site)\.com$", host)
    if m:
        site = next((p for p in parts if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", p) and p != "recruiting"), "")
        if site:
            return {"kind": "workday", "ref": {"host": host, "tenant": m.group(1), "site": site, "search": (parse_qs(u.query).get("q") or [""])[0]}}
    if FEED_URL.search(u.path + ("?" + u.query if u.query else "")):
        return {"kind": "feed", "ref": {"url": url if "//" in url else "https://" + url}}
    return {"kind": "page", "ref": {}}


def _catalog_rows() -> list[dict[str, Any]]:
    import json
    from pathlib import Path

    data = json.loads((Path(__file__).parent / "catalog.json").read_text(encoding="utf-8"))
    return [*data["employers"], *data.get("boards", [])]


def catalog(field: str = "", countries: list[str] | None = None) -> list[dict[str, Any]]:
    """Employers whose postings this program is known to be able to read (each address was checked against the employer's
    public job API on the date in catalog.json), best matches for the user first. Ones already on the list are left out."""
    import json
    from pathlib import Path

    rows = _catalog_rows()
    have = {(r["kind"], r["ref"].get("url") if r["kind"] == "feed" else str(sorted(r["ref"].items()))) for r in listing()}
    want = {c.upper() for c in countries or []}
    out = []
    for r in rows:
        d = detect(r["url"])
        if (d["kind"], d["ref"].get("url") if d["kind"] == "feed" else str(sorted(d["ref"].items()))) in have:
            continue
        fit = (2 if field and field in r["fields"] else 0) + (1 if not want or want & set(r["regions"]) else 0)
        out.append({**r, "kind_label": KIND_LABEL.get(d["kind"], d["kind"]), "fit": fit, "match": bool(field) and field in r["fields"], "board": d["kind"] == "feed"})
    return sorted(out, key=lambda r: (-r["fit"], r["name"].lower()))


def _id(name: str, url: str) -> str:
    return hashlib.sha1(f"{name.lower()}|{url}".encode()).hexdigest()[:10]


def listing() -> list[dict[str, Any]]:
    return list(db.get_setting("employers") or [])


def save(rows: list[dict[str, Any]]) -> None:
    db.set_setting("employers", rows)


def add(name: str, url: str, *, priority: bool = True) -> dict[str, Any]:
    name, url = name.strip(), url.strip()
    if url and "//" not in url:
        url = "https://" + url
    if not url or not urlparse(url).netloc:
        raise ValueError("请填写这家公司招聘页的网址")
    d = detect(url)
    if not name:
        name = BUILTIN_NAMES.get(d["ref"].get("key", ""), "") or next(iter(d["ref"].values()), "") if d["kind"] != "page" else ""
        name = str(name or urlparse(url).netloc.removeprefix("www.").split(".")[0]).replace("-", " ").title()
    rows = listing()
    for r in rows:
        if r["kind"] == d["kind"] and (r["ref"].get("url") == d["ref"].get("url") if d["kind"] == "feed" else r["ref"] == d["ref"]) and (d["kind"] != "page" or r["url"] == url):
            raise ValueError(f"「{r['name']}」已经在清单里了")
    if d["kind"] == "feed":   # how this board writes its titles, when the catalog knows it
        d["ref"]["style"] = next((r.get("style", "employer: title") for r in _catalog_rows() if r["url"] == url), "employer: title")
    row = {"id": _id(name, url), "name": name, "url": url, "kind": d["kind"], "ref": d["ref"], "priority": bool(priority), "enabled": True}
    save([*rows, row])
    return row


def update(emp_id: str, **changes: Any) -> None:
    rows = listing()
    for r in rows:
        if r["id"] == emp_id:
            r.update({k: v for k, v in changes.items() if k in ("name", "priority", "enabled")})
    save(rows)


def remove(emp_id: str) -> None:
    save([r for r in listing() if r["id"] != emp_id])


def source_of(e: dict[str, Any]) -> tuple[str, str]:
    """(source, scope) under which this employer's postings are stored."""
    k, ref = e["kind"], e["ref"]
    if k == "builtin":
        return ref["key"], ref["key"]
    if k == "workday":
        return "workday", ref["host"].split(".myworkday")[0]
    if k in ("page", "feed"):
        return k, e["id"]
    return k, next(iter(ref.values()))


def rows_for(e: dict[str, Any], terms: list[str], keep: Callable[..., bool]) -> Iterator[dict[str, Any]]:
    from .sources import bigtech, public, watch

    k, ref = e["kind"], e["ref"]
    if k == "builtin":
        return bigtech.scan(ref["key"], terms, keep)
    if k == "greenhouse":
        return public.greenhouse(ref["board"])
    if k == "lever":
        return public.lever(ref["company"])
    if k == "ashby":
        return public.ashby(ref["board"])
    if k == "smartrecruiters":
        return public.smartrecruiters(ref["company"], keep)
    if k == "workday":
        return public.workday(ref["host"], ref["tenant"], ref["site"], search=ref.get("search", ""), keep=keep, company=e.get("name", ""))
    if k == "feed":
        return public.feed(ref["url"], e["name"], e["id"], ref.get("style", "employer: title"))
    return watch.scan(e, keep)


def priority_names() -> set[str]:
    from .discover import norm_company

    return {norm_company(e["name"]) for e in listing() if e.get("priority") and e.get("enabled", True)}


def is_priority(company: str, source: str = "", names: set[str] | None = None) -> bool:
    from .discover import norm_company

    names = priority_names() if names is None else names
    c = norm_company(company or "")
    return bool(c) and (c in names or any(n and (c.startswith(n + " ") or n.startswith(c + " ")) for n in names))


def ensure_builtin(keys: list[str]) -> None:
    """Make sure these purpose-built sites are on the list (used by the first-run guide)."""
    rows = listing()
    have = {r["ref"].get("key") for r in rows if r["kind"] == "builtin"}
    urls = {"amazon": "https://www.amazon.jobs", "apple": "https://jobs.apple.com", "google": "https://www.google.com/about/careers/applications/", "microsoft": "https://jobs.careers.microsoft.com",
            "meta": "https://www.metacareers.com/jobs", "nvidia": "https://nvidia.eightfold.ai/careers", "amd": "https://careers.amd.com", "intel": "https://jobs.intel.com"}
    for k in keys:
        if k in BUILTIN_NAMES and k not in have:
            rows.append({"id": _id(BUILTIN_NAMES[k], urls[k]), "name": BUILTIN_NAMES[k], "url": urls[k], "kind": "builtin", "ref": {"key": k}, "priority": True, "enabled": True})
    save(rows)
    db.set_setting("employers.migrated", True)


def migrate_legacy() -> int:
    """Once: turn the old fixed switches and per-system lists into entries of the one list."""
    if db.get_setting("employers") is not None and db.get_setting("employers.migrated"):
        return 0
    st = db.all_settings()
    rows = listing()
    have = {(r["kind"], str(sorted(r["ref"].items()))) for r in rows}

    def put(name: str, url: str, kind: str, ref: dict[str, Any], priority: bool) -> None:
        if (kind, str(sorted(ref.items()))) in have:
            return
        rows.append({"id": _id(name, url), "name": name, "url": url, "kind": kind, "ref": ref, "priority": priority, "enabled": True})

    urls = {"amazon": "https://www.amazon.jobs", "apple": "https://jobs.apple.com", "google": "https://www.google.com/about/careers/applications/", "microsoft": "https://jobs.careers.microsoft.com",
            "meta": "https://www.metacareers.com/jobs", "nvidia": "https://nvidia.eightfold.ai/careers", "amd": "https://careers.amd.com", "intel": "https://jobs.intel.com"}
    for key, on in (st.get("sources.bigtech") or {}).items():
        if on and key in BUILTIN_NAMES:
            put(BUILTIN_NAMES[key], urls[key], "builtin", {"key": key}, True)
    for b in st.get("sources.greenhouse") or []:
        put(b.replace("-", " ").title(), f"https://job-boards.greenhouse.io/{b}", "greenhouse", {"board": b}, False)
    for c in st.get("sources.lever") or []:
        put(c.replace("-", " ").title(), f"https://jobs.lever.co/{c}", "lever", {"company": c}, False)
    for b in st.get("sources.ashby") or []:
        put(b.replace("-", " ").title(), f"https://jobs.ashbyhq.com/{b}", "ashby", {"board": b}, False)
    for w in st.get("sources.workday") or []:
        put(w["tenant"].title(), f"https://{w['host']}/{w['site']}", "workday", {"host": w["host"], "tenant": w["tenant"], "site": w["site"], "search": w.get("search", "")}, False)
    save(rows)
    db.set_setting("employers.migrated", True)
    return len(rows)
