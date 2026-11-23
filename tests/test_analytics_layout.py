"""The data the analysis page lays out in its "pace and to-dos" part (views/analytics/Pace.vue): how long a posting and
an application wait for their first record, the to-dos handled by kind (the page shows the first few and the rest behind
a control - so every kind must be there, once, with its own count), and the open to-dos that waited longest, with what
tells them apart (kind, posting, a date of their own, put off until when). Empty and one-row cases included: the page
draws an intentional line, not an empty table, from them."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from autoapply import db

NOW = datetime.now(timezone.utc).replace(tzinfo=None)


def _all():
    """A window over the whole record."""
    from autoapply import analytics

    return analytics.Window(None, None, None, None, "", "")


def _job(company: str, *, deadline: str = "", found: datetime | None = None) -> int:
    from autoapply.models import Job

    with db.session() as s:
        j = Job(source="manual", source_id=company, company=company, title="Analyst", apply_url="https://jobs.example/" + company, jd_text="x" * 300,
                status="queued", online=1, score=8.0, deadline=deadline, first_seen=found or NOW - timedelta(days=2))
        s.add(j)
        s.flush()
        return j.id


def _app(job_id: int, *, begun: datetime | None = None, status: str = "draft_ready") -> int:
    from autoapply.models import Application

    with db.session() as s:
        a = Application(job_id=job_id, status=status, created_at=begun or NOW - timedelta(days=1))
        s.add(a)
        s.flush()
        return a.id


def _record(app_id: int, at: datetime) -> int:
    from autoapply.models import Draft

    with db.session() as s:
        d = Draft(application_id=app_id, version=1, review_status="pending", schema={}, answers=[], unresolved=[], created_at=at)
        s.add(d)
        s.flush()
        return d.id


def _handled(kind: str, waited_h: float, *, done_ago_h: float = 1, status: str = "done") -> None:
    from autoapply.models import Todo

    done = NOW - timedelta(hours=done_ago_h)
    with db.session() as s:
        s.add(Todo(kind=kind, title=kind, status=status, created_at=done - timedelta(hours=waited_h), done_at=done))


def _open(kind: str, age_h: float, **kw) -> int:
    from autoapply.models import Todo

    with db.session() as s:
        t = Todo(kind=kind, title=kw.pop("title", kind), status="open", created_at=NOW - timedelta(hours=age_h), **kw)
        s.add(t)
        s.flush()
        return t.id


def _backlog():
    from autoapply import analytics

    with db.session() as s:
        return analytics._backlog(s, _all())


def _first():
    from autoapply import analytics

    with db.session() as s:
        return analytics._first_records(s, _all())


# ── the to-dos handled, by kind ───────────────────────────────────────────────────────────────────────────────────────

def test_many_kinds_are_each_one_row_with_their_own_count_largest_first(app_env):
    kinds = {"answer": 5, "review": 4, "submit": 3, "failed": 3, "mail_unmatched": 2, "followup": 2, "gone": 1, "captcha": 1, "config": 1}
    for k, n in kinds.items():
        for i in range(n):
            _handled(k, waited_h=2 + i)
    b = _backlog()
    rows = b["by_kind"]
    assert len(rows) == len(kinds) > 6                      # more than the page shows at first: all of them are here
    assert {r["kind"]: r["n"] for r in rows} == kinds       # nothing merged that means something else, no count changed
    assert [r["n"] for r in rows] == sorted((r["n"] for r in rows), reverse=True)
    assert b["handled"] == sum(kinds.values())
    labels = [str(r["label"]) for r in rows]
    assert len(set(labels)) == len(labels) and not set(labels) & set(kinds)       # a name a person reads, never the kind's id
    assert all(r["kinds"] == [r["kind"]] for r in rows)
    assert all(r["median_hours"] is not None for r in rows)


def test_two_kinds_of_one_meaning_are_one_row_that_says_which(app_env):
    for k in ("login", "login", "takeover"):
        _handled(k, waited_h=1)
    rows = _backlog()["by_kind"]
    assert len(rows) == 1 and rows[0]["n"] == 3
    assert rows[0]["kind"] == "login" and rows[0]["kinds"] == ["login", "takeover"]


def test_one_kind(app_env):
    _handled("answer", waited_h=3)
    b = _backlog()
    assert b["handled"] == 1 and len(b["by_kind"]) == 1
    assert round(b["by_kind"][0]["median_hours"]) == 3 and round(b["median_hours"]) == 3


def test_nothing_handled_and_nothing_open(app_env):
    b = _backlog()
    assert b == {"handled": 0, "median_hours": None, "by_kind": [], "open": 0, "snoozed": 0, "oldest": []}


def test_only_what_was_handled_in_the_period_is_counted(app_env):
    from autoapply import analytics

    _handled("answer", waited_h=2, done_ago_h=1)
    _handled("answer", waited_h=2, done_ago_h=24 * 40)      # long before the period
    _open("answer", 5)                                      # still open: not handled
    w = analytics.window(days=7)
    with db.session() as s:
        b = analytics._backlog(s, w)
    assert b["handled"] == 1 and b["by_kind"][0]["n"] == 1 and b["open"] == 1


def test_every_kind_of_to_do_has_a_name_in_each_language(app_env):
    from autoapply import analytics

    for kind, label in analytics.TODO_KINDS.items():
        for lang in ("en", "zh", "fr"):
            text = label.in_lang(lang)
            assert text and text != kind and "server.analytics" not in text, (kind, lang, text)


# ── the open to-dos that waited longest ───────────────────────────────────────────────────────────────────────────────

def test_the_oldest_open_to_dos_first_at_most_five_with_what_tells_them_apart(app_env):
    from autoapply.models import Todo

    j = _job("Acme", deadline="2099-01-31 23:59")
    a = _app(j)
    d = _record(a, NOW - timedelta(hours=2))
    later = datetime.now() + timedelta(days=2)              # (local time, as the to-do page keeps it)
    passed = datetime.now() - timedelta(days=2)
    ids = [
        _open("followup", 90, title="Acme - interview", payload={"job_id": j}, due_at=later),
        _open("answer", 80, ref=f"draft:{d}"),
        _open("failed", 70, ref=f"application:{a}"),
        _open("submit", 60, payload={"draft_id": d}, snoozed_until=later),
        _open("config", 50, ref="config:gmail", snoozed_until=passed),       # put off until a time that is past: not snoozed now
        _open("login", 40),
        _open("gone", 30),
    ]
    with db.session() as s:
        s.add(Todo(kind="answer", title="done", status="done", created_at=NOW - timedelta(hours=200), done_at=NOW - timedelta(hours=1)))
    b = _backlog()
    assert b["open"] == 7 and b["snoozed"] == 1
    old = b["oldest"]
    assert [o["id"] for o in old] == ids[:5]                                   # the five that waited longest, oldest first
    assert [round(o["hours"]) for o in old] == [90, 80, 70, 60, 50]
    keys = {"id", "title", "kind", "hours", "kind_key", "created_at", "due_at", "date_only", "snoozed_until", "job_id", "company", "job_title", "deadline"}
    assert all(set(o) == keys for o in old)
    first, by_draft, by_app, snoozed, unsnoozed = old
    assert first["kind_key"] == "followup" and str(first["kind"]) != "followup"
    assert first["due_at"] == later.isoformat() and first["snoozed_until"] is None
    assert (first["job_id"], first["company"], first["job_title"], first["deadline"]) == (j, "Acme", "Analyst", "2099-01-31 23:59")
    assert by_draft["company"] == "Acme" and by_app["company"] == "Acme"        # the posting found through a record, an application
    assert snoozed["snoozed_until"] == later.isoformat() and snoozed["company"] == "Acme"
    assert unsnoozed["snoozed_until"] is None
    assert (unsnoozed["job_id"], unsnoozed["company"], unsnoozed["deadline"]) == (None, "", "")      # about no posting
    assert datetime.fromisoformat(first["created_at"]) < datetime.fromisoformat(by_draft["created_at"])


def test_a_card_whose_reference_is_not_a_number_is_about_no_posting(app_env):
    _open("failed", 3, ref="application:not-a-number", payload={"job_id": "x"})
    o = _backlog()["oldest"][0]
    assert o["job_id"] is None and o["company"] == ""


# ── the first record ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_first_record_with_no_data(app_env):
    assert _first() == {"n": 0, "from_found_hours": None, "from_begun_hours": None, "slow": 0}
    _app(_job("Acme"))                                        # an application without a record yet: still nothing to tell
    assert _first()["n"] == 0


def test_first_record_counts_the_first_record_only_and_the_slow_ones(app_env):
    a = _app(_job("Acme", found=NOW - timedelta(hours=100)), begun=NOW - timedelta(hours=10))
    _record(a, NOW - timedelta(hours=4))
    _record(a, NOW - timedelta(hours=1))                       # a second version: not the first record
    b = _app(_job("Globex", found=NOW - timedelta(hours=8)), begun=NOW - timedelta(hours=6))
    _record(b, NOW - timedelta(hours=2))
    f = _first()
    assert f["n"] == 2 and f["slow"] == 1                      # Acme waited 96 hours from being found
    assert round(f["from_found_hours"]) == round((96 + 6) / 2) and round(f["from_begun_hours"]) == round((6 + 4) / 2)


def test_the_outcomes_view_carries_both_parts(app_env):
    from autoapply import analytics

    got = analytics.applications(analytics.window())
    assert got["first_record"]["n"] == 0 and got["backlog"]["oldest"] == [] and got["backlog"]["snoozed"] == 0
