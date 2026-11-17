"""Gmail: asking only for what arrived since the last look."""

from __future__ import annotations

import base64

import pytest

from autoapply import db, mail, mailbox


class Call:
    def __init__(self, result):
        self.result = result

    def execute(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeGmail:
    """As much of the Gmail client as the program uses: users().getProfile / history().list / messages().list|get."""

    def __init__(self):
        self.history_id = 100
        self.added: list[tuple[int, str]] = []          # (history number, message id)
        self.store: dict[str, dict] = {}
        self.calls: list[str] = []
        self.expired = False

    def arrive(self, mid: str, subject: str, body: str = "") -> None:
        self.history_id += 1
        self.added.append((self.history_id, mid))
        self.store[mid] = {"id": mid, "payload": {"headers": [{"name": "Subject", "value": subject}, {"name": "From", "value": "jobs@example.com"},
                                                                {"name": "Date", "value": "Mon, 16 Nov 2026 10:00:00 +0000"}],
                                                    "mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()}}}

    def users(self):
        return self

    def history(self):
        return self

    def messages_api(self):
        return self

    def getProfile(self, userId):  # noqa: N802, N803
        self.calls.append("profile")
        return Call({"historyId": str(self.history_id)})

    def list(self, userId, **kw):  # noqa: N803
        if "startHistoryId" in kw:
            self.calls.append("history")
            if self.expired:
                from googleapiclient.errors import HttpError

                return Call(HttpError(type("R", (), {"status": 404, "reason": "Not Found"})(), b"{}"))
            new = [m for n, m in self.added if n > int(kw["startHistoryId"])]
            return Call({"history": [{"id": str(n), "messagesAdded": [{"message": {"id": m}}]} for n, m in self.added if n > int(kw["startHistoryId"])], "historyId": str(self.history_id)})
        self.calls.append("search")
        return Call({"messages": [{"id": m} for m in self.store]})

    def get(self, userId, id, format):  # noqa: A002, N803
        self.calls.append("get:" + id)
        return Call(self.store[id])




@pytest.fixture
def gmail(app_env, monkeypatch):
    from autoapply import secrets

    db.init_db()
    g = FakeGmail()

    class Users:
        def getProfile(self, **kw):  # noqa: N802
            return g.getProfile(**kw)

        def history(self):
            return g

        def messages(self):
            return g

    monkeypatch.setattr(mail, "_service", lambda: type("S", (), {"users": lambda self: Users()})())
    secrets.put(secrets.GMAIL_TOKEN, "{}")
    return g


def test_before_a_first_look_nothing_can_be_told(gmail):
    assert mail.anything_new() is None and mail.added_since_last() is None and mailbox.fetch_new() is None
    assert mail.track(quick=True) == {"skipped": "no starting point yet: the next full pass sets one"}


def test_the_pass_over_the_last_days_sets_the_starting_point_and_does_not_fetch_what_is_known(gmail):
    from datetime import datetime, timedelta, timezone

    gmail.arrive("m1", "Thank you for applying")
    got = mailbox.fetch(datetime.now(timezone.utc) - timedelta(days=3), 10, job_related=True, skip=lambda i: False)
    assert [m.id for m in got] == ["m1"] and db.get_setting(mail.HISTORY) == str(gmail.history_id)
    gmail.calls.clear()
    assert mailbox.fetch(datetime.now(timezone.utc) - timedelta(days=3), 10, job_related=True, skip=lambda i: i == "m1") == []
    assert gmail.calls == ["search"]                       # the list of ids, and no message fetched again


def test_only_what_arrived_is_read_and_reading_your_own_mail_changes_nothing(gmail):
    mail.mark_history()
    gmail.calls.clear()
    assert mail.anything_new() is False and gmail.calls == ["history"]          # one small request, nothing fetched
    gmail.arrive("m2", "Your application to Example", "We received your application.")
    gmail.arrive("m3", "Weekly newsletter", "Ten recipes for autumn.")
    assert mail.anything_new() is True
    before = db.get_setting(mail.HISTORY)
    assert mail.anything_new() is True and db.get_setting(mail.HISTORY) == before   # left for the one who reads it
    got = mailbox.fetch_new()
    assert [m.id for m in got] == ["m2"]                    # the newsletter is not about an application
    assert db.get_setting(mail.HISTORY) == before           # not behind us until the caller has dealt with it
    mail.commit_history()
    assert db.get_setting(mail.HISTORY) == str(gmail.history_id)
    assert mail.anything_new() is False and mailbox.fetch_new() == []
    # history only says what was added: a message that was read, archived or labelled meanwhile is not in it again
    assert "search" not in gmail.calls


def test_a_message_already_recorded_is_not_fetched_again(gmail):
    mail.mark_history()
    gmail.arrive("m4", "Interview invitation")
    gmail.calls.clear()
    assert mailbox.fetch_new(skip=lambda i: i == "m4") == [] and "get:m4" not in gmail.calls


def test_a_starting_point_gmail_no_longer_keeps_falls_back_to_the_last_days(gmail):
    mail.mark_history()
    gmail.expired = True
    assert mail.anything_new() is None and db.get_setting(mail.HISTORY) == ""
    db.set_setting(mail.HISTORY, "5")
    assert mail.added_since_last() is None and db.get_setting(mail.HISTORY) == ""


def test_the_scheduler_queues_a_task_only_when_something_arrived(gmail):
    from autoapply import tasks
    from autoapply.models import Task

    def queued():
        with db.session() as s:
            return [(t.kind, t.ref, t.payload) for t in s.query(Task).filter_by(status="queued")]

    mail.mark_history()
    tasks._mail_new()
    assert queued() == []
    gmail.arrive("m5", "Your application")
    tasks._mail_new()
    tasks._mail_new()                                       # asked again before the task ran: still one
    assert queued() == [("mail", "new", {"quick": True})]
    db.set_setting("mail.kind", "imap")
    with db.session() as s:
        s.query(Task).delete()
    tasks._mail_new()
    assert queued() == []                                   # another kind of mailbox is read by the pass over the last days


def test_more_arrivals_than_one_look_takes_are_read_over_several_looks_oldest_first(gmail):
    """With more arrivals than the limit, the earliest were dropped and the place in the history moved past them."""
    mail.mark_history()
    for i in range(7):
        gmail.arrive(f"b{i}", "Your application", "received")
    got = []
    for _ in range(4):
        batch = mailbox.fetch_new(3)
        got.append([m.id for m in batch])
        mail.commit_history()
    assert got == [["b0", "b1", "b2"], ["b3", "b4", "b5"], ["b6"], []]


def test_a_batch_that_was_not_recorded_is_read_again(gmail, monkeypatch):
    """The place in the history moved on when the messages were fetched; a model that was unavailable then left them
    without a record and out of every later look."""
    mail.mark_history()
    gmail.arrive("c1", "Your application to Example", "We received your application.")
    monkeypatch.setattr(mail, "triage", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("the model is not answering")))
    with pytest.raises(RuntimeError):
        mail.track(quick=True)
    assert mail.anything_new() is True                      # still to be read
    monkeypatch.setattr(mail, "triage", lambda *a, **k: {"category": "other", "company": "", "job_title": "", "summary": "x"})
    assert mail.track(quick=True)["new_mail"] == 1
    assert mail.anything_new() is False and mail.track(quick=True)["new_mail"] == 0


def test_an_e_mail_that_cancels_an_interview_is_not_an_invitation_to_one(app_env, monkeypatch):
    """"Ashley has cancelled your interview" was announced as "Interview invitation" and would have moved the application
    to the interview stage: the category said what the e-mail was about, and that was read as what it said."""
    from autoapply import messages, notify
    from autoapply.models import Application, ApplicationEvent, Job, MailEvent

    assert "event" in mail.TRIAGE_SCHEMA["properties"] and "cancelled" in mail.TRIAGE_RULES
    db.init_db()
    with db.session() as s:
        job = Job(source="manual", source_id="r1", company="4AG Robotics", title="AI Co-op Student", apply_url="https://x.example/1", channel="employer site", jd_text="x" * 300)
        s.add(job)
        s.flush()
        a = Application(job_id=job.id, status="submitted")
        s.add(a)
        s.flush()
        app_id = a.id
    sent = []
    monkeypatch.setattr(notify, "send", lambda kind, card, **k: sent.append(card))
    # invited, then the same interview is cancelled: back to where it was, and said as what it is
    assert mail._record(app_id, "interview", "invited for Thursday", None, "m1", "new")[0] == 1
    with db.session() as s:
        assert s.get(Application, app_id).status == "interview"
    assert mail._record(app_id, "interview", "the interview was cancelled", None, "m2", "cancelled") == (1, False, "4AG Robotics · AI Co-op Student")
    with db.session() as s:
        a = s.get(Application, app_id)
        assert a.status == "submitted" and "cancelled" in a.last_event
        assert [(e.old, e.new) for e in s.query(ApplicationEvent).filter_by(application_id=app_id)][-2:] == [("submitted", "interview"), ("interview", "submitted")]
    # a cancellation for an application that never got that far changes nothing; a moved interview still is an interview
    assert mail._record(app_id, "interview", "cancelled", None, "m3", "cancelled")[0] == 0
    assert mail._record(app_id, "interview", "moved to Friday", None, "m4", "changed")[0] == 1
    card = messages.mail_update("interview", "4AG Robotics · AI Co-op Student", "the interview was cancelled", event="cancelled")
    assert card.heading == "面试被取消" and "重新安排" in card.hint and messages.mail_update("interview", "t", "s").heading == "面试邀请"
    assert messages.mail_label("interview", "changed")[1] == "面试安排有变化" and messages.mail_label("rejection", "cancelled")[1] == "申请未通过"
    # what the reading of the mail found is kept with it and used when it is linked to an application later
    with db.session() as s:
        s.add(MailEvent(message_id="m9", sender="x", subject="Interview cancelled", category="interview", event="cancelled", summary="cancelled", company_guess="4AG"))
    assert mail.link("m9", [app_id]) == 1 and sent[-1].heading == "面试被取消"
