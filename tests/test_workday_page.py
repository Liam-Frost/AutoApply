"""Workday boards read through their own pages in the program's browser (2026-11-24).

Workday refused the program's requests from the owner's network - "too many requests" or a security check, whatever their
pace - and "read again at the next scan" meant never: every scan's first request was refused, for a week. The same
board is served to a browser. Here the page is a stand-in: what the program asks of it, and at what pace.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from autoapply import db

POSTS = [{"title": f"Software Intern {i}", "externalPath": f"/job/Toronto/Software-Intern_R{i}", "bulletFields": [f"R{i}"], "locationsText": "Toronto"} for i in range(21)]


class Board:
    """As much of a browser page as the reading uses: goto, title, inner_text, wait_for_timeout, evaluate."""

    def __init__(self, posts=POSTS, check_for: int = 0, refuse_after: int | None = None):
        self.posts, self.check_for, self.refuse_after = posts, check_for, refuse_after
        self.visited: list[str] = []
        self.asked: list[tuple[str, str, float]] = []
        self.clock = 0.0

    def goto(self, url, **k):
        self.visited.append(url)

    def title(self):
        return "Just a moment..." if self.clock < self.check_for else "Careers"

    def inner_text(self, sel):
        return "Checking your browser" if self.clock < self.check_for else "Search for jobs"

    def wait_for_timeout(self, ms):
        self.clock += ms / 1000

    def evaluate(self, js, arg):
        self.asked.append((arg["method"], arg["url"], self.clock))
        if self.refuse_after is not None and len(self.asked) > self.refuse_after:
            return {"status": 429, "json": None}
        if arg["method"] == "POST":
            off = arg["body"]["offset"]
            return {"status": 200, "json": {"jobPostings": self.posts[off:off + 20]}}
        rid = arg["url"].rsplit("_", 1)[-1]
        return {"status": 200, "json": {"jobPostingInfo": {"jobReqId": rid, "jobDescription": f"<p>About {rid}</p>"}, "hiringOrganization": {"name": "Acme Bank"}}}


def test_a_board_is_read_through_its_own_page_at_a_persons_pace(app_env):
    from autoapply.models import Job
    from autoapply.sources import public

    with db.session() as s:
        s.add(Job(source="workday", source_id="acme:R0", company="Acme", title="Software Intern 0", jd_text="x" * 300))
    page = Board(check_for=3)      # (its check of the browser passes by itself after three seconds)
    rows = list(public.workday_in_page(page, "acme.wd3.myworkdayjobs.com", "acme", "Careers", search="intern", keep=lambda t, w: not t.endswith("7"), company="Acme"))
    assert page.visited == ["https://acme.wd3.myworkdayjobs.com/en-US/Careers?q=intern"]
    assert len(rows) == 21 and rows[0]["source_id"] == "acme:R0" and "jd_text" not in rows[0]          # known: only "still online"
    r5 = next(r for r in rows if r["source_id"] == "acme:R5")
    assert r5["jd_text"] == "About R5" and r5["company"] == "Acme Bank" and r5["apply_url"].endswith("/en-US/Careers/job/Toronto/Software-Intern_R5")
    details = [u for m, u, _ in page.asked if m == "GET"]
    assert len(details) == 18 and not any(u.endswith("_R7") or u.endswith("_R17") or u.endswith("_R0") for u in details)   # not read: kept out, or known
    assert [u for m, u, _ in page.asked if m == "POST"] == ["/wday/cxs/acme/Careers/jobs"] * 2
    gaps = [b[2] - a[2] for a, b in zip(page.asked, page.asked[1:])]
    assert min(gaps) >= public.PAGE_GAP_MS / 1000                                                    # one request every few seconds


def test_a_check_only_a_person_can_answer_is_not_answered_and_a_429_rests_the_service(app_env):
    from autoapply.sources import public

    with pytest.raises(public.Challenged):
        list(public.workday_in_page(Board(check_for=10**6), "acme.wd3.myworkdayjobs.com", "acme", "Careers"))
    page = Board(refuse_after=2)
    with pytest.raises(public.Resting):
        list(public.workday_in_page(page, "acme.wd3.myworkdayjobs.com", "acme", "Careers"))
    assert db.get_setting(public.RESTING)["myworkdayjobs.com"]["strikes"] == 1


@pytest.fixture
def boards(app_env, monkeypatch):
    from autoapply import browser, employers

    employers.save([{"id": "td", "name": "TD", "kind": "workday", "enabled": True, "priority": False,
                     "ref": {"host": "td.wd3.myworkdayjobs.com", "tenant": "td", "site": "TD_Bank_Careers", "search": ""}, "url": "https://td.wd3.myworkdayjobs.com/TD_Bank_Careers"}])
    opened: list[tuple[str, Board]] = []
    pages = {"next": [Board()]}

    @contextmanager
    def open_page(tenant_key=None, **k):
        page = pages["next"].pop(0) if pages["next"] else Board()
        opened.append((tenant_key, page))
        yield page

    monkeypatch.setattr(browser, "open_page", open_page)
    only = employers.listing()
    only = [e for e in only if e["id"] == "td"]
    monkeypatch.setattr(employers, "listing", lambda: only)          # (the purpose-built sites are not asked here)
    monkeypatch.setattr(employers, "migrate_legacy", lambda: None)
    monkeypatch.setattr(browser, "needs_window", lambda key: not opened or len(opened) < 2)
    return {"opened": opened, "pages": pages}


def test_a_scan_reads_a_refused_board_in_the_browser_in_the_same_scan(boards, monkeypatch):
    """The program's requests are refused (a rest kept from before): not one is sent, and the board is read through its
    page in this scan - not "at the next scan"."""
    from datetime import datetime, timedelta, timezone

    from autoapply import discover
    from autoapply.models import Job
    from autoapply.sources import public

    db.set_setting(public.RESTING, {"myworkdayjobs.com": {"until": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), "strikes": 2}})
    import httpx

    monkeypatch.setattr(httpx.Client, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked while it rests")))
    db.set_setting("intake.enabled", False)
    out = discover.run(notify_user=False)
    assert "TD" not in out["errors"] and out["sources"]["TD"]["new"] == 21
    assert [k for k, _ in boards["opened"]] == ["sources:workday"]
    with db.session() as s:
        assert s.query(Job).filter(Job.source == "workday").count() == 21


def test_a_board_page_that_checks_the_hidden_browser_is_opened_once_more_in_a_window(boards):
    from autoapply import employers
    from autoapply.sources import public

    boards["pages"]["next"] = [Board(check_for=10**6), Board()]
    got = employers.read_in_browser(employers.listing(), ["intern"], lambda *a: True)
    assert len(boards["opened"]) == 2 and got[0][2] is None and len(got[0][0]) == 21
    boards["opened"].clear()
    boards["pages"]["next"] = [Board(check_for=10**6), Board(check_for=10**6)]
    got = employers.read_in_browser(employers.listing(), ["intern"], lambda *a: True)
    assert isinstance(got[0][2], public.Challenged) and got[0][0] is None
