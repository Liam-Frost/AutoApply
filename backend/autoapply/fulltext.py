"""The whole text of a posting, when its source gave only a summary.

Most sources hand over a posting's full description. Some do not: a job board's feed carries a teaser of a few lines,
and a text that was cut at a length is not the whole of it either. Such a posting is marked (``Job.jd_partial``:
"summary" or "cut") so that nothing downstream takes what it holds for the posting - a condition the summary does not
mention has not been shown to be absent. A text that was read from the posting's own page is marked too ("whole", or
"cut" when the page was longer than is kept): that mark is what keeps a later scan's teaser from replacing it.

Before such a posting is scored, or its overview written, its own page is read (``complete``): by a plain request
first, and in a browser page when that gives nothing to read (a page that is drawn by script). What comes back is
taken only when it is longer than the summary and is about this posting - not a sign-in wall, not a list of other
postings. When the page cannot be read the summary stays, the mark stays, and whoever uses the text says so.
"""

from __future__ import annotations

import logging
import re
import time
from html.parser import HTMLParser

log = logging.getLogger("autoapply.fulltext")

LIMIT = 30000           # characters kept of a posting's text
PARTIAL = ("summary", "cut")          # not the whole posting: whoever reads it is told
FROM_PAGE = ("whole", "cut")          # what complete() leaves on a posting whose page it read
ENOUGH = 600            # a page with less text than this is not a posting's description
AGAIN_AFTER = 6 * 3600  # seconds before a page that could not be read is tried again
_tried: dict[int, float] = {}


class _Reader(HTMLParser):
    """The text of a page as a reader sees it: no scripts, no navigation, the main part when the page marks one."""

    SKIP = {"script", "style", "noscript", "svg", "template", "nav", "header", "footer", "aside", "button", "select", "iframe"}
    BLOCK = {"p", "div", "li", "br", "tr", "section", "article", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.inside = 0
        self.whole: list[str] = []
        self.main: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self.skip += 1
        if tag in ("main", "article") or dict(attrs).get("role") == "main":
            self.inside += 1
        if tag in self.BLOCK:
            self._add("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in ("main", "article") and self.inside:
            self.inside -= 1
        if tag in self.BLOCK:
            self._add("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self._add(data)

    def _add(self, text: str) -> None:
        self.whole.append(text)
        if self.inside:
            self.main.append(text)


def _tidy(parts: list[str]) -> str:
    t = re.sub(r"[ \t\xa0]+", " ", "".join(parts))
    return re.sub(r"\n\s*\n+", "\n", re.sub(r" *\n *", "\n", t)).strip()


def read_html(html: str) -> str:
    """The readable text of an HTML page: its main part when it has one with something in it, else all of it."""
    r = _Reader()
    try:
        r.feed(html or "")
    except Exception:  # noqa: BLE001 - markup that cannot be parsed has no text to offer
        return ""
    main = _tidy(r.main)
    return main if len(main) >= ENOUGH else _tidy(r.whole)


def _get(url: str) -> str:
    """The page as a plain request gives it ('' when it does not give one)."""
    import httpx

    from .sources.public import UA

    try:
        with httpx.Client(timeout=30, follow_redirects=True, headers={**UA, "Accept": "text/html,application/xhtml+xml"}) as c:
            r = c.get(url)
        if r.status_code >= 400 or "html" not in r.headers.get("content-type", "html"):
            return ""
        return r.text
    except Exception as e:  # noqa: BLE001 - a page that does not answer is a page that could not be read
        log.info("the posting's page did not answer a plain request: %s", type(e).__name__)
        return ""


def _in_browser(url: str) -> str:
    """The page's text as a browser shows it - for pages that are drawn by script."""
    from . import browser

    try:
        with browser.open_page(None, url=url, operation="scan") as page:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(1800)
            return re.sub(r"[ \t]+", " ", page.evaluate("() => (document.querySelector('main, [role=main], article') || document.body).innerText") or "").strip()
    except Exception as e:  # noqa: BLE001
        log.info("the posting's page did not open in a browser: %s", type(e).__name__)
        return ""


def fetch(url: str, *, browser_too: bool = True) -> str:
    """The text of a posting's own page, all of it (the caller keeps what it keeps); '' when there is nothing to read."""
    text = read_html(_get(url))
    if len(text) < ENOUGH and browser_too:
        text = _in_browser(url)
    return text if len(text) >= ENOUGH else ""


def about(text: str, title: str, company: str) -> bool:
    """Is this page's text about that posting? Its title is there (most of its words), or its employer is named - a
    sign-in wall, an error page or a list of other postings has neither."""
    low = text.lower()
    words = [w for w in re.findall(r"[a-z0-9]{4,}", (title or "").lower())]
    named = sum(1 for w in words if w in low)
    return (bool(words) and named * 2 >= len(words)) or (len((company or "").strip()) >= 3 and company.strip().lower() in low)


def due(job_id: int) -> bool:
    """May this posting's page be tried now? (Not when it was tried a short while ago and could not be read.)"""
    return time.monotonic() - _tried.get(job_id, -AGAIN_AFTER) >= AGAIN_AFTER


def complete(job_id: int, *, browser_too: bool = True) -> bool:
    """Read the posting's own page when what is stored is only a summary. True when the stored text is the whole
    posting afterwards (it was, or it is now); False when it is still a summary."""
    from . import db
    from .models import Job

    with db.session() as s:
        j = s.get(Job, job_id)
        if j is None:
            return False
        if j.jd_partial != "summary":
            return j.jd_partial not in PARTIAL
        url, had, title, company = j.apply_url or "", len((j.jd_text or "").strip()), j.title or "", j.company or ""
    if not url.startswith("http") or not due(job_id):
        return False
    _tried[job_id] = time.monotonic()
    text = fetch(url, browser_too=browser_too)
    if not text or len(text) < max(ENOUGH, int(had * 1.2)) or not about(text, title, company):
        return False
    with db.session() as s:
        j = s.get(Job, job_id)
        # (a page longer than is kept is not the whole posting either: it is said to be cut, as a source's would be)
        j.jd_text, j.jd_partial = text[:LIMIT], "whole" if len(text) <= LIMIT else "cut"
        j.note = (f"full text read from the posting's page {time.strftime('%Y-%m-%d')}; " + (j.note or ""))[:2000]
    _tried.pop(job_id, None)
    return len(text) <= LIMIT


def mark_stored_teasers() -> int:
    """The postings that were stored before texts were marked (once, at start): a feed's item that reads like a teaser -
    it trails off, or it is too short to be a posting - is marked as one, so that it is completed before it is scored
    again and said to be a summary until then. The ones that are listed again are marked by their next scan anyway;
    these are the ones that have scrolled off their feed."""
    from . import db
    from .models import Job
    from .sources.public import teaser

    n = 0
    with db.session() as s:
        for j in s.query(Job).filter(Job.source == "feed", Job.jd_partial == ""):
            if (j.jd_text or "").strip() and teaser(j.jd_text, from_content=False) == "summary":
                j.jd_partial = "summary"
                n += 1
    return n


def partial_note(kind: str) -> str:
    """What whoever reads a partial text is told about it (for a model that scores or summarises the posting)."""
    if kind == "summary":
        return ("NOTE: what follows is only a SUMMARY of this posting - its source did not give the full text and the posting's own page could not be read. "
                "A requirement or condition the summary does not mention may still be in the posting: do not take silence for absence, do not exclude the posting "
                "for something the summary does not say, and say in your reason that only a summary was read.")
    if kind == "cut":
        return "NOTE: this posting's text is long and what follows is its beginning only; something it says further down is not here."
    return ""


def forget_attempts() -> None:
    _tried.clear()


__all__ = ["complete", "fetch", "read_html", "about", "partial_note", "mark_stored_teasers", "LIMIT", "PARTIAL", "FROM_PAGE"]
