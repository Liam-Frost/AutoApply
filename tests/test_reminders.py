"""Things with a date, cards put off until later, and hours in which the phone stays quiet.

A mail that invites to an interview ended in a notice and a status; what to do and by when stayed in the mail. A card
could be closed or left - not put off. And everything the program had to say, it said at once, at any hour.
"""
from datetime import datetime, timedelta

import pytest

from autoapply import db


def _app(status="submitted", company="Acme"):
    from autoapply.models import Application, Job

    with db.session() as s:
        j = Job(source="manual", source_id=f"r-{company}", company=company, title="Software Intern", apply_url=f"https://x.test/{company}", channel="employer site", jd_text="x" * 300)
        s.add(j)
        s.flush()
        a = Application(job_id=j.id, status=status, submitted_at=datetime(2026, 11, 1), created_at=datetime(2026, 10, 30))
        s.add(a)
        s.flush()
        return a.id


def _cards(kind="followup", status="open"):
    from autoapply.models import Todo

    with db.session() as s:
        return [(t.title, t.due_at, t.body, dict(t.payload or {})) for t in s.query(Todo).filter_by(kind=kind, status=status).order_by(Todo.id)]


def test_what_a_mail_asks_becomes_a_card_with_its_date_and_follows_what_the_employer_says_next(app_env, monkeypatch):
    from autoapply import mail, mailbox, notify

    app_id = _app()
    sent = []
    monkeypatch.setattr(notify, "send", lambda category, card, **k: sent.append(getattr(card, "heading", card)) or True)
    now = datetime.now().astimezone()
    box: list = []
    monkeypatch.setattr(mailbox, "fetch", lambda *a, **k: list(box))
    says = {
        "Online assessment": {"category": "assessment", "event": "new", "action": "完成在线测评", "due": "2026-11-24", "due_text": "by November 24", "summary": "测评需在 11 月 24 日前完成"},
        "Interview invitation": {"category": "interview", "event": "new", "action": "参加视频面试", "due": "2026-11-26T10:00", "due_text": "Thursday, Nov 26 at 10:00 AM PST", "summary": "面试邀请"},
        "Interview moved": {"category": "interview", "event": "changed", "action": "参加视频面试", "due": "2026-11-27T14:30", "due_text": "Friday, Nov 27 at 2:30 PM PST", "summary": "面试改期"},
        "Interview reminder": {"category": "interview", "event": "reminder", "action": "", "due": "", "due_text": "", "summary": "提醒"},
        "Interview cancelled": {"category": "interview", "event": "cancelled", "action": "", "due": "", "due_text": "", "summary": "面试取消"},
        "Next steps": {"category": "info_request", "event": "new", "action": "回复可面试的时间", "due": "", "due_text": "", "summary": "请回复你方便的时间"},
    }
    monkeypatch.setattr(mail, "triage", lambda subj, frm, body: {"company": "Acme", "job_title": "Software Intern", "received": False, **says[subj]})

    def arrives(subject, n):
        box[:] = [mailbox.Message(id=f"m{n}", sender="Acme <hr@acme.test>", subject=subject, body="…", date=now + timedelta(minutes=n))]
        mail.track()

    arrives("Online assessment", 1)
    arrives("Interview invitation", 2)
    cards = _cards()
    assert [(t, d) for t, d, _, _ in cards] == [("Acme · Software Intern：在线测评", datetime(2026, 11, 24)), ("Acme · Software Intern：面试邀请", datetime(2026, 11, 26, 10, 0))]
    assert "完成在线测评" in cards[0][2] and "by November 24" in cards[0][2] and cards[0][3]["date_only"] is True and cards[0][3]["application_id"] == app_id
    assert cards[1][3]["date_only"] is False and cards[1][3]["due_text"].endswith("PST")          # the mail's own wording is kept, time zone and all
    arrives("Interview moved", 3)                # the employer moves it: the same card, the new date
    arrives("Interview reminder", 4)             # a reminder changes nothing
    cards = _cards()
    assert len(cards) == 2 and cards[1][1] == datetime(2026, 11, 27, 14, 30) and "Nov 27 at 2:30 PM" in cards[1][2]
    arrives("Next steps", 5)                     # asks for something and names no date: a card without one - none is made up
    assert _cards()[-1][0].startswith("Acme · Software Intern：") and _cards()[-1][1] is None and "回复可面试的时间" in _cards()[-1][2]
    arrives("Interview cancelled", 6)            # called off: its card is closed (the assessment's stays)
    assert [t for t, _, _, _ in _cards()] == ["Acme · Software Intern：在线测评", _cards()[-1][0]]
    assert len(_cards(status="done")) == 1
    # a mail the applicant put on its application afterwards asks the same thing of them
    from autoapply.models import MailEvent

    other = _app(company="Globex")
    with db.session() as s:
        s.add(MailEvent(message_id="late", sender="x", subject="Assessment", category="assessment", event="new", summary="测评", company_guess="?",
                        asks={"action": "完成测评", "due": "2026-12-01", "due_text": "Dec 1"}))
    mail.link("late", [other])
    assert ("Globex · Software Intern：在线测评", datetime(2026, 12, 1)) in [(t, d) for t, d, _, _ in _cards()]


def test_a_date_is_only_what_the_mail_states(app_env):
    from autoapply import reminders

    assert reminders.parse_due("2026-11-24") == datetime(2026, 11, 24) and reminders.parse_due("2026-11-24T10:00") == datetime(2026, 11, 24, 10, 0)
    for nothing in ("", "next week", "within 7 days", "24/11", None):
        assert reminders.parse_due(nothing) is None
    from autoapply import mail

    said = mail.TRIAGE_SCHEMA["properties"]["due"]["description"]
    assert "ONLY if the e-mail states one" in said and "never work one out" in said


def test_a_contacts_day_makes_a_card_once(app_env, monkeypatch):
    """(What is coming up is said by its reminders: test_alarms.py.)"""
    from autoapply import notify, reminders
    from autoapply.models import Contact, Todo

    told = []
    monkeypatch.setattr(notify, "send", lambda category, card, **k: told.append((card.heading, card.subject)) or True)
    monkeypatch.setattr(notify, "flush_held", lambda at=None: 0)
    with db.session() as s:
        s.add(Contact(name="Dana", company="Acme", follow_up="2026-11-26", note="ask about the team"))
    assert reminders.check(datetime(2026, 11, 25, 9, 0)) == {"shown_again": 0, "contacts": 0}
    assert reminders.check(datetime(2026, 11, 26, 8, 30))["contacts"] == 1
    assert reminders.check(datetime(2026, 11, 26, 12, 0))["contacts"] == 0
    assert told == [("今天截止", "跟进 Dana（Acme）")]
    with db.session() as s:      # the contact's day made a card, once - also after it is dealt with
        card = s.query(Todo).filter_by(ref="contact:1:2026-11-26").one()
        assert card.payload["contact_id"] == 1 and "ask about the team" in card.body
        card.status = "done"
    assert reminders.check(datetime(2026, 11, 27, 9, 0))["contacts"] == 0


def test_a_card_can_be_put_off_and_comes_back(app_env, monkeypatch):
    from fastapi.testclient import TestClient

    from autoapply import notify, reminders
    from autoapply.api.main import app
    from autoapply.models import Todo

    told = []
    monkeypatch.setattr(notify, "send", lambda category, card, **k: told.append(card.heading) or True)
    monkeypatch.setattr(notify, "flush_held", lambda at=None: 0)
    with db.session() as s:
        s.add(Todo(kind="takeover", ref="account:x", title="Acme", body="please sign in", payload={}))
        s.add(Todo(kind="followup", ref="followup:9:offer", title="Acme：Offer", payload={}, due_at=datetime.now() + timedelta(days=2)))
    c = TestClient(app)
    until = (datetime.now() + timedelta(days=3)).replace(microsecond=0)
    assert c.post("/api/todos/1/snooze", json={"until": until.isoformat()}).status_code == 200
    rows = {r["id"]: r for r in c.get("/api/todos").json()}
    assert rows[1]["snoozed_until"] == until.isoformat() and rows[2]["snoozed_until"] is None
    assert rows[2]["category"] == "dated" and rows[2]["days_left"] == 2 and rows[2]["urgency"] == 1        # a card counts by its own date
    assert c.get("/api/overview").json()["open_todos"] == 1                       # what was put off is not counted until then
    assert reminders.check(until - timedelta(hours=1))["shown_again"] == 0
    assert reminders.check(until + timedelta(minutes=1))["shown_again"] == 1 and told[-1] == "到了你设定的提醒时间"
    assert c.get("/api/overview").json()["open_todos"] == 2
    # brought back by hand; a date set, changed and removed by hand
    c.post("/api/todos/1/snooze", json={"until": until.isoformat()})
    assert c.post("/api/todos/1/snooze", json={"until": None}).status_code == 200 and c.get("/api/todos").json()[1]["snoozed_until"] is None
    assert c.post("/api/todos/1/due", json={"due": "2026-12-05T09:30"}).status_code == 200
    assert {r["id"]: r for r in c.get("/api/todos").json()}[1]["due_at"] == "2026-12-05T09:30:00"
    assert c.post("/api/todos/1/due", json={"due": None}).status_code == 200 and c.post("/api/todos/1/due", json={"due": "soon"}).status_code == 400
    assert c.post("/api/todos/999/snooze", json={"until": None}).status_code == 404


def test_in_the_quiet_hours_nothing_is_pushed_and_nothing_is_lost(app_env, monkeypatch):
    from autoapply import messages, notify
    from autoapply.models import Notification

    pushed = []
    monkeypatch.setattr(notify, "_channels", lambda: [type("C", (), {"send": lambda self, text: pushed.append(text), "send_card": lambda self, card, base: pushed.append(card.heading)})()])
    night, morning = datetime(2026, 11, 20, 2, 0), datetime(2026, 11, 20, 8, 5)
    assert notify.quiet_now(night) is False                                         # not unless the applicant says so
    db.set_setting("notify.quiet", {"on": True, "from": "22:00", "to": "08:00"})
    assert [notify.quiet_now(datetime(2026, 11, 20, h, m)) for h, m in ((21, 59), (22, 0), (2, 0), (7, 59), (8, 0), (13, 0))] == [False, True, True, True, False, False]
    db.set_setting("notify.quiet", {"on": True, "from": "13:00", "to": "15:00"})    # hours within one day work the same
    assert [notify.quiet_now(datetime(2026, 11, 20, h, 0)) for h in (12, 13, 14, 15)] == [False, True, True, False]
    db.set_setting("notify.quiet", {"on": True, "from": "22:00", "to": "08:00"})
    monkeypatch.setattr(notify, "quiet_now", lambda at=None: (at or night).hour < 8 or (at or night).hour >= 22)
    assert notify.send("task_result", messages.submitted("Acme · Intern", evidence="Thank you"), ref="application:1") is False
    assert notify.send("status_update", messages.mail_update("interview", "Globex · Intern", "invited"), ref="application:2", tag="interview") is False
    assert pushed == []
    # the approval of a sign-in the applicant started themselves is the one thing that goes through
    assert notify.send("todo", messages.second_factor("UBC PD Portal", "Duo"), ref="account:pdportal:ubc", through_quiet=True) is True
    assert pushed == ["请在手机上批准 Duo"]
    with db.session() as s:
        assert [(n.held, n.sent) for n in s.query(Notification).order_by(Notification.id)] == [(1, 0), (1, 0), (0, 1)]      # all on record, two held back
    assert notify.flush_held(night) == 0 and len(pushed) == 1
    assert notify.flush_held(morning) == 2                                           # the hours are over: one message, not a burst
    assert len(pushed) == 2 and "静默时段里有 2 条通知" in pushed[1] and "Acme · Intern" in pushed[1] and "Globex · Intern" in pushed[1]
    with db.session() as s:
        assert [(n.held, n.sent) for n in s.query(Notification).order_by(Notification.id)] == [(0, 1), (0, 1), (0, 1)]
    assert notify.flush_held(morning) == 0


def test_one_thing_many_tasks_wait_for_is_one_card_and_one_notice(app_env, monkeypatch):
    from autoapply import notify
    from autoapply.models import Todo

    pushed = []
    monkeypatch.setattr(notify, "_channels", lambda: [type("C", (), {"send_card": lambda self, card, base: pushed.append(card.subject)})()])
    ids = {notify.add_todo("takeover", "Acme", body="please sign in", ref="account:workday:acme", payload={"n": i}) for i in range(5)}
    with db.session() as s:
        assert len(ids) == 1 and s.query(Todo).count() == 1 and pushed == ["Acme"]


def test_a_reminder_that_repeats_the_date_leaves_the_card_where_the_applicant_put_it(app_env, monkeypatch):
    """Every mail with a date brought a card back that had been put off - also a reminder that said the same date again."""
    from datetime import timedelta

    from autoapply import notify, reminders
    from autoapply.models import Todo, now

    monkeypatch.setattr(notify, "send", lambda *a, **k: True)
    app_id = _app("interview")
    asks = {"action": "Interview with the team", "due": "2026-12-03T10:00", "due_text": "Dec 3, 10:00 PT"}
    tid = reminders.from_mail(app_id, "Acme · Intern", "interview", "new", "invited", asks, "m1")
    until = now() + timedelta(days=2)
    reminders.snooze(tid, until)
    assert reminders.from_mail(app_id, "Acme · Intern", "interview", "reminder", "see you then", asks, "m2") == tid       # the same date, said again
    with db.session() as s:
        t = s.get(Todo, tid)
        assert t.snoozed_until is not None and t.due_at.strftime("%Y-%m-%d %H:%M") == "2026-12-03 10:00"
    moved = {**asks, "due": "2026-12-05T14:00", "due_text": "Dec 5, 2 pm PT"}
    reminders.from_mail(app_id, "Acme · Intern", "interview", "rescheduled", "moved", moved, "m3")                       # the employer moves it: it is shown again
    with db.session() as s:
        t = s.get(Todo, tid)
        assert t.snoozed_until is None and t.due_at.strftime("%Y-%m-%d %H:%M") == "2026-12-05 14:00"
