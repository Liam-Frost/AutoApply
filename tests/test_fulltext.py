"""A posting whose source gave only a summary: marked, completed from its own page, and said to be one where it is not
(autoapply/fulltext.py).

The plan asked for the full description of every posting; a job board's feed carries a teaser, and that teaser was
scored as if it were the posting - what it did not mention was taken not to be required."""

import pytest

from autoapply import db

POSTING = "<h1>Data Analyst, Store Operations</h1><p>Northwind Analytics is hiring a Data Analyst.</p>" + "".join(
    f"<p>Responsibility {i}: build and maintain the weekly store-performance report for the operations team.</p>" for i in range(12)) + \
    "<h2>Requirements</h2><ul><li>Must be legally authorized to work in Canada without sponsorship.</li><li>SQL and one of Python or R.</li></ul>"
PAGE = f"""<!doctype html><html><head><title>Data Analyst</title><script>var tracking = "do not read this";</script><style>p {{ color: red }}</style></head>
<body><header><nav><a href="/">Home</a><a href="/jobs">All jobs</a></nav></header>
<main>{POSTING}</main>
<footer>Copyright Northwind Analytics. Cookie settings.</footer></body></html>"""
SUMMARY = "Northwind Analytics is hiring a Data Analyst to build the weekly store-performance report for the operations team. Read more"


def _job(text=SUMMARY, partial="summary", **kw):
    from autoapply.models import Job

    with db.session() as s:
        j = Job(source="feed", source_id=kw.pop("sid", "board:1"), title="Data Analyst, Store Operations", company="Northwind Analytics", tenant="board", status="new",
                apply_url="https://careers.northwind.example/jobs/101", jd_text=text, jd_partial=partial, **kw)
        s.add(j)
        s.flush()
        return j.id


def _get(job_id):
    from autoapply.models import Job

    with db.session() as s:
        j = s.get(Job, job_id)
        s.expunge(j)
        return j


def test_a_feed_item_is_the_posting_or_what_a_board_shows_of_it():
    from autoapply.sources import public

    long = "Build services. " * 100
    assert public.teaser("A short teaser of the job.", from_content=False) == "summary"
    assert public.teaser(long + " Read more", from_content=True) == "summary" and public.teaser(long + " [...]", from_content=False) == "summary"
    assert public.teaser(long + "…", from_content=True) == "summary" and public.teaser(long + " View the full job description.", from_content=False) == "summary"
    assert public.teaser(long, from_content=False) == "" and public.teaser("The whole of a short posting.", from_content=True) == ""
    assert public.teaser("x" * (public.FEED_TEXT + 1), from_content=True) == "cut"
    feed = f"""<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
      <item><title>Acme: Data Analyst</title><link>https://jobs.example/1</link><guid>1</guid><description>Teaser only. [...]</description></item>
      <item><title>Acme: Engineer</title><link>https://jobs.example/2</link><guid>2</guid><description>Teaser.</description>
            <content:encoded><![CDATA[<p>{long}</p>]]></content:encoded></item></channel></rss>"""
    items = public.parse_feed(feed)
    assert [(i["title"], i["partial"]) for i in items] == [("Acme: Data Analyst", "summary"), ("Acme: Engineer", "")]
    assert items[1]["summary"].startswith("Build services.") and len(items[1]["summary"]) > 1200      # the item's own content, not its teaser


def test_the_text_of_a_page_is_what_a_reader_sees():
    from autoapply import fulltext

    text = fulltext.read_html(PAGE)
    assert text.startswith("Data Analyst, Store Operations") and "without sponsorship" in text
    assert "tracking" not in text and "color: red" not in text and "All jobs" not in text and "Cookie settings" not in text
    # a page that marks no main part: everything a reader sees, still without scripts and navigation
    plain = fulltext.read_html(PAGE.replace("<main>", "<div>").replace("</main>", "</div>"))
    assert "without sponsorship" in plain and "tracking" not in plain and "All jobs" not in plain
    assert fulltext.read_html("") == "" and fulltext.read_html("<p>only this</p>") == "only this"
    assert fulltext.about(text, "Data Analyst, Store Operations", "Northwind Analytics")
    assert not fulltext.about("Sign in to continue. Enter your e-mail address and password. " * 20, "Data Analyst, Store Operations", "Northwind Analytics")
    assert fulltext.about("We at Northwind Analytics are looking for people.", "Something Else Entirely", "Northwind Analytics")


def test_a_summary_is_completed_from_the_postings_own_page_and_stays_completed(app_env, monkeypatch):
    from autoapply import discover, fulltext

    fulltext.forget_attempts()
    asked = []
    monkeypatch.setattr(fulltext, "_get", lambda url: asked.append(url) or PAGE)
    monkeypatch.setattr(fulltext, "_in_browser", lambda url: pytest.fail("a page that a plain request reads is not opened in a browser"))
    jid = _job()
    assert fulltext.complete(jid) is True and asked == ["https://careers.northwind.example/jobs/101"]
    j = _get(jid)
    assert j.jd_partial == "" and "without sponsorship" in j.jd_text and "All jobs" not in j.jd_text and "full text read from the posting's page" in j.note
    assert fulltext.complete(jid) is True and len(asked) == 1                 # it is the whole text now: nothing to read
    # the feed lists the posting again at the next scan - with its teaser. The teaser does not replace the posting.
    row = {"source_id": "board:1", "title": "Data Analyst, Store Operations", "company": "Northwind Analytics", "tenant": "board", "jd_text": SUMMARY, "jd_partial": "summary",
           "apply_url": "https://careers.northwind.example/jobs/101"}
    discover.upsert([row], source="feed", scope="board", complete=False)
    j = _get(jid)
    assert j.jd_partial == "" and "without sponsorship" in j.jd_text
    # a posting that is new comes in as what the source gave: a summary, marked as one; a source that gives the whole text is not marked
    discover.upsert([{**row, "source_id": "board:2"}, {**row, "source_id": "board:3", "jd_text": "the whole text " * 200, "jd_partial": ""}], source="feed", scope="board", complete=False)
    from autoapply.models import Job

    with db.session() as s:
        assert {x.source_id: x.jd_partial for x in s.query(Job)} == {"board:1": "", "board:2": "summary", "board:3": ""}
    # ...and when a source that gave a summary gives the whole text one day, that is taken
    discover.upsert([{**row, "source_id": "board:2", "jd_text": "now the whole text " * 100, "jd_partial": ""}], source="feed", scope="board", complete=False)
    with db.session() as s:
        two = s.query(Job).filter_by(source_id="board:2").one()
        assert two.jd_partial == "" and two.jd_text.startswith("now the whole text")


@pytest.mark.parametrize("page, why", [
    ("<main>" + "<p>Sign in to continue. Enter your e-mail address and your password to see this page.</p>" * 20 + "</main>", "a sign-in wall is not the posting"),
    ("<main><p>Northwind Analytics is hiring a Data Analyst.</p></main>", "less than the summary already says"),
    ("", "the page did not answer"),
])
def test_a_page_that_is_not_the_posting_leaves_the_summary_as_it_is(app_env, monkeypatch, page, why):
    from autoapply import fulltext

    fulltext.forget_attempts()
    calls = {"get": 0, "browser": 0}
    monkeypatch.setattr(fulltext, "_get", lambda url: calls.__setitem__("get", calls["get"] + 1) or page)
    monkeypatch.setattr(fulltext, "_in_browser", lambda url: calls.__setitem__("browser", calls["browser"] + 1) or "")
    jid = _job()
    assert fulltext.complete(jid) is False, why
    j = _get(jid)
    assert j.jd_partial == "summary" and j.jd_text == SUMMARY
    assert calls["get"] == 1
    assert fulltext.complete(jid) is False and calls["get"] == 1              # not asked again right away
    fulltext.forget_attempts()
    assert fulltext.complete(jid, browser_too=False) is False and calls["get"] == 2


def test_a_page_drawn_by_script_is_read_in_a_browser(app_env, monkeypatch):
    from autoapply import fulltext

    fulltext.forget_attempts()
    monkeypatch.setattr(fulltext, "_get", lambda url: "<html><body><div id='root'></div><script>render()</script></body></html>")
    monkeypatch.setattr(fulltext, "_in_browser", lambda url: fulltext.read_html(PAGE))
    jid = _job()
    assert fulltext.complete(jid) is True and "without sponsorship" in _get(jid).jd_text


def _scoring(monkeypatch, reason="岗位做数据分析，和你的方向一致。"):
    from autoapply import knowledge, llm

    knowledge.write("profile", "# Profile\n- Business Analytics\n")
    knowledge.write("scoring", "# Rules\n- Exclude postings that require sponsorship the applicant does not have.\n")
    seen = []

    def answer(prompt, schema, **kw):
        seen.append(prompt)
        if "brief" in schema["properties"] and len(schema["properties"]) == 1:
            return {"brief": "#### 这个岗位做什么\n- 报表"}
        return {"excluded": False, "exclusion_rule": "", "score": 7.0, "direction": "data", "reason": reason, "term": "", "months": "", "summary": "数据分析", "brief": ""}

    monkeypatch.setattr(llm, "json", answer)
    return seen


def test_a_posting_scored_on_a_summary_says_so(app_env, monkeypatch):
    """Its page could not be read: the model is told that it reads a summary, and the reason says it whatever the model wrote."""
    from autoapply import fulltext, scoring

    fulltext.forget_attempts()
    monkeypatch.setattr(fulltext, "_get", lambda url: "")
    monkeypatch.setattr(fulltext, "_in_browser", lambda url: "")
    seen = _scoring(monkeypatch)
    long_summary = SUMMARY + " " + "The team works with store managers every week. " * 6
    jid = _job(long_summary)
    out = scoring.score_job(jid)
    assert "only a SUMMARY of this posting" in seen[0] and "do not take silence for absence" in seen[0]
    assert out["reason"].startswith("只有摘要：") and out["reason"].endswith("和你的方向一致。")
    j = _get(jid)
    assert j.score == 7.0 and j.status == "scored" and j.score_reason == out["reason"] and j.jd_partial == "summary"
    # the model said it itself: once is enough
    seen = _scoring(monkeypatch, reason="只有摘要可读：看起来是数据分析岗位。")
    fulltext.forget_attempts()
    assert scoring.score_job(jid)["reason"] == "只有摘要可读：看起来是数据分析岗位。"
    # the overview is written from the same text, with the same warning
    assert scoring.brief_job(jid) and "only a SUMMARY of this posting" in seen[-1]
    # a text that was cut is said to be one too
    cut = _job("The posting goes on. " * 40, partial="cut", sid="board:9")
    assert scoring.score_job(cut)["reason"].startswith("岗位说明很长") and "its beginning only" in seen[-1]


def test_a_summary_too_short_to_score_is_completed_first_and_then_scored(app_env, monkeypatch):
    from autoapply import fulltext, scoring
    from autoapply.models import Job

    fulltext.forget_attempts()
    pages = {"https://careers.northwind.example/jobs/101": PAGE}
    monkeypatch.setattr(fulltext, "_get", lambda url: pages.get(url, ""))
    monkeypatch.setattr(fulltext, "_in_browser", lambda url: "")
    seen = _scoring(monkeypatch)
    db.set_setting("scoring.parallel", 1)
    short = "Data Analyst wanted. Read more"
    reads = _job(short)                                                             # its page can be read
    with db.session() as s:
        s.add(Job(source="feed", source_id="board:7", title="Operations Analyst", company="Orchard Retail", tenant="board", status="new",
                  apply_url="https://careers.orchard.example/jobs/7", jd_text=short, jd_partial="summary"))          # its page cannot
        s.add(Job(source="import", source_id="old:1", title="Imported", company="Old", status="new", jd_text="one line"))  # never had a description, and is no summary of one
    out = scoring.score_pending()
    assert out["scored"] == 1 and out["no_description"] == 1
    j = _get(reads)
    assert j.status == "scored" and j.jd_partial == "" and "without sponsorship" in j.jd_text
    assert len(seen) == 1 and "without sponsorship" in seen[0] and "only a SUMMARY" not in seen[0]      # scored on the posting, not on its teaser
    assert not j.score_reason.startswith("只有摘要")
    with db.session() as s:
        assert {x.source_id: x.status for x in s.query(Job)} == {"board:1": "scored", "board:7": "new", "old:1": "new"}


def test_the_posting_says_on_its_page_that_its_text_is_a_summary(app_env):
    from fastapi.testclient import TestClient

    from autoapply.api.main import app

    c = TestClient(app)
    jid = _job()
    assert c.get(f"/api/jobs/{jid}").json()["jd_partial"] == "summary"
    whole = _job("the whole text " * 100, partial="", sid="board:5")
    assert c.get(f"/api/jobs/{whole}").json()["jd_partial"] == ""
    # "score this one" is not refused for a summary that is short: its page is read first
    assert c.post("/api/jobs/bulk", json={"action": "score", "ids": [jid]}).json() == {"done": 1, "skipped": 0}
