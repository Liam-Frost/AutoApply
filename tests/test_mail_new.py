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
        self.queries: list[str] = []
        self.expired = False

    def arrive(self, mid: str, subject: str, body: str = "", sender: str = "jobs@example.com", labels: tuple[str, ...] = ("INBOX",)) -> None:
        self.history_id += 1
        self.added.append((self.history_id, mid))
        self.store[mid] = {"id": mid, "labelIds": list(labels), "payload": {"headers": [{"name": "Subject", "value": subject}, {"name": "From", "value": sender},
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
        return Call({"historyId": str(self.history_id), "emailAddress": "me@example.com"})

    def list(self, userId, **kw):  # noqa: N803
        if "startHistoryId" in kw:
            self.calls.append("history")
            if self.expired:
                from googleapiclient.errors import HttpError

                return Call(HttpError(type("R", (), {"status": 404, "reason": "Not Found"})(), b"{}"))
            new = [m for n, m in self.added if n > int(kw["startHistoryId"])]
            return Call({"history": [{"id": str(n), "messagesAdded": [{"message": {"id": m}}]} for n, m in self.added if n > int(kw["startHistoryId"])], "historyId": str(self.history_id)})
        self.calls.append("search")
        self.queries.append(kw.get("q", ""))
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
    assert card.heading == "面试已取消" and "重新安排" in card.hint and messages.mail_update("interview", "t", "s").heading == "面试邀请"
    assert messages.mail_label("interview", "changed")[1] == "面试安排有变化" and messages.mail_label("rejection", "cancelled")[1] == "申请未通过"
    # what the reading of the mail found is kept with it and used when it is linked to an application later
    with db.session() as s:
        s.add(MailEvent(message_id="m9", sender="x", subject="Interview cancelled", category="interview", event="cancelled", summary="cancelled", company_guess="4AG"))
    assert mail.link("m9", [app_id]) == 1 and sent[-1].heading == "面试已取消"


# --- which application a mail is about ---


def test_a_mail_is_not_about_an_application_that_did_not_exist_when_it_was_written(app_env):
    """A mail of forty days ago was put on an application made yesterday for a posting of the same name: the newest
    application at the employer with the best title won, and when the mail was written was not looked at."""
    from datetime import timedelta

    from autoapply.models import Application, Job, now

    t = now()
    with db.session() as s:
        jobs = [Job(source="workday", source_id=sid, company="Acme", title=title, apply_url=f"https://acme.test/{sid}", channel="employer site", jd_text="x" * 300)
                for sid, title in (("R03394", "Engineer"), ("R04410", "Engineer"), ("R05555", "Engineer"), ("7", "Analyst"))]
        s.add_all(jobs)
        s.flush()
        old = Application(job_id=jobs[0].id, status="submitted", created_at=t - timedelta(days=50), submitted_at=t - timedelta(days=49))
        new = Application(job_id=jobs[1].id, status="submitted", created_at=t - timedelta(days=1), submitted_at=t)
        # sent by hand long ago, met by the program only yesterday: it existed when it was sent
        by_hand = Application(job_id=jobs[2].id, status="submitted", created_at=t - timedelta(days=1), submitted_at=t - timedelta(days=45))
        other = Application(job_id=jobs[3].id, status="submitted", created_at=t - timedelta(days=60), submitted_at=t - timedelta(days=60))
        s.add_all([old, new, by_hand, other])
        s.flush()
        old, new, by_hand, other = old.id, new.id, by_hand.id, other.id
    forty_days_ago = t - timedelta(days=40)
    assert mail.match_application("Acme", "Engineer", forty_days_ago) == by_hand            # the last one sent before the mail - not the one made yesterday
    assert mail.match_application("Acme", "Engineer", t - timedelta(days=47)) == old         # only one of that name existed then
    assert mail.match_application("Acme", "Engineer", t + timedelta(minutes=5)) == new       # a mail of now: the newest, as before
    assert mail.match_application("Acme", "Engineer", t - timedelta(days=70)) is None        # none existed: the applicant is asked
    assert mail.match_application("Acme", "Engineer", None) == new                           # a mail that carries no date is not held to one
    # the posting's own number in the mail settles it, whatever the titles and dates say
    assert mail.match_application("Acme", "Engineer", t, "Regarding your application for requisition R03394 (Engineer)") == old
    assert mail.match_application("Acme", "", t, "Your application R05555-2 was received") == by_hand      # with a suffix after it
    assert mail.match_application("Acme", "", t, "Your application XR055551 was received") is None       # inside another number: not this one
    assert mail.match_application("Acme", "Engineer", t, "ref r04410.") == new
    assert mail.match_application("Acme", "Engineer", t, "posting 7 of 12") == new           # a short number is in every mail: it names nothing


def test_what_the_applicant_said_a_mail_is_about_is_not_changed_by_what_the_program_finds_later(app_env, monkeypatch):
    from autoapply import notify
    from autoapply.models import Application, Job, MailEvent

    monkeypatch.setattr(notify, "send", lambda *a, **k: None)
    with db.session() as s:
        ids = []
        for i in (1, 2):
            j = Job(source="manual", source_id=f"k{i}", company="Acme", title=f"Role {i}", apply_url=f"https://acme.test/{i}", channel="employer site", jd_text="x" * 300)
            s.add(j)
            s.flush()
            a = Application(job_id=j.id, status="submitted")
            s.add(a)
            s.flush()
            ids.append(a.id)
        s.add(MailEvent(message_id="m1", sender="hr@acme.test", subject="Interview", category="interview", event="new", summary="invited", company_guess="Acme"))
    assert mail.link("m1", [ids[0]], by="site") == 1                 # the employer's list says: the first
    assert mail.link("m1", [ids[1]], by="user") == 1                 # the applicant corrects it: the second
    assert mail.link("m1", [ids[0]], by="site") == 0                 # the program looks at the list again: it stays as the applicant said
    with db.session() as s:
        me = s.query(MailEvent).filter_by(message_id="m1").one()
        assert (me.application_id, me.linked_by) == (ids[1], "user")

def test_rejected_refresh_grant_requires_new_consent(app_env, monkeypatch):
    from types import SimpleNamespace
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials
    from autoapply import mail, secrets

    def rejected(request):
        raise RefreshError("invalid_grant", {"error": "invalid_grant"})
    secrets.put(secrets.GMAIL_TOKEN, "{}")
    fake = SimpleNamespace(expired=True, refresh_token="test", refresh=rejected)
    monkeypatch.setattr(Credentials, "from_authorized_user_info", lambda *args: fake)
    with pytest.raises(mail.GmailReconnect):
        mail._service()
    assert mail.status()["reconnect"] and not mail.status()["authorized"]


def test_gmail_is_read_through_the_proxy_the_setting_says_and_no_answer_says_so(app_env, monkeypatch):
    """httplib2 - what the Gmail API is read with - takes a proxy only from HTTPS_PROXY. With the setting on the system's
    proxy and no such variable (the program started from the Start menu), Gmail was read straight from Google while
    everything else went through the system's proxy; where Google is reached only through one, no mail was read for a
    day, and each check said "the site may be under maintenance" (2026-11-25). The token's refresh and the reading go
    the way the setting says; a check that cannot reach Gmail says that."""
    import google.auth.transport.requests as transport
    import httplib2
    from google.oauth2.credentials import Credentials
    from types import SimpleNamespace

    from autoapply import handlers, humanize, i18n, net, secrets
    from autoapply.models import Task

    for k in net._VARS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(net, "_ORIGINAL", {})
    monkeypatch.setattr(net, "_system_url", lambda: "http://127.0.0.1:7890")      # (what Windows is set to)
    db.set_setting("proxy.mode", "system")
    assert httplib2.proxy_info_from_environment("https") is None                  # what httplib2 alone went by
    pi = net.httplib2_proxy("https")
    assert (pi.proxy_host, pi.proxy_port) == ("127.0.0.1", 7890) and pi.applies_to("gmail.googleapis.com") and not pi.applies_to("localhost")
    # (and httplib2 can use it: without PySocks it drops any proxy without a word and connects directly - it always had)
    assert pi.isgood()
    s = net.requests_session()
    assert s.proxies == {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"} and not s.trust_env

    # the token is refreshed through a session that goes that way, and the mail is read with an Http that asks the setting
    seen: dict = {}
    real = transport.Request
    monkeypatch.setattr(transport, "Request", lambda session=None: seen.setdefault("session", session) and real(session=session))
    secrets.put(secrets.GMAIL_TOKEN, "{}")
    fake = SimpleNamespace(expired=True, refresh_token="t", refresh=lambda request: None, to_json=lambda: "{}")
    monkeypatch.setattr(Credentials, "from_authorized_user_info", lambda *a: fake)
    svc = mail._service()
    assert seen["session"].proxies["https"] == "http://127.0.0.1:7890"
    assert svc._http.http.proxy_info is net.httplib2_proxy
    db.set_setting("proxy.mode", "none")
    assert net.httplib2_proxy("https") is None and net.requests_session().proxies == {}

    # no answer from Gmail: said as that, with the way it went - not as a site under maintenance
    db.set_setting("proxy.mode", "system")
    monkeypatch.setattr(mail, "track", lambda **kw: (_ for _ in ()).throw(TimeoutError("timed out")))
    with pytest.raises(mail.GmailUnreachable) as got:
        handlers._mail(Task(kind="mail", ref="schedule", payload={}))
    assert "through http://127.0.0.1:7890" in str(got.value)
    said = humanize.explain(f"GmailUnreachable: {got.value}")["message"]
    assert "Gmail" in i18n.tr(said, "en") and "maintenance" not in i18n.tr(said, "en")
    monkeypatch.setattr(mail, "track", lambda **kw: (_ for _ in ()).throw(ValueError("something else")))
    with pytest.raises(ValueError):      # (anything else stays what it is)
        handlers._mail(Task(kind="mail", ref="schedule", payload={}))
    # an IMAP mailbox is reached directly: its timeout is its own server's, not said as Gmail's
    db.set_setting("mail.kind", "imap")
    monkeypatch.setattr(mail, "track", lambda **kw: (_ for _ in ()).throw(TimeoutError("timed out")))
    with pytest.raises(TimeoutError):
        handlers._mail(Task(kind="mail", ref="schedule", payload={}))
    db.set_setting("mail.kind", "")

    # the program's own proxy, with a name and a password that are percent-encoded in its address: httplib2 gets them
    # as they are; an address the setting says to reach directly is reached directly by the refresh too
    db.set_setting("proxy.mode", "custom")
    db.set_setting("proxy.url", "10.0.0.2:8080")
    db.set_setting("proxy.username", "me@home")
    secrets.put(net.PROXY_PASSWORD, "p@ss:%1")
    pi = net.httplib2_proxy("https")
    assert (pi.proxy_host, pi.proxy_port, pi.proxy_user, pi.proxy_pass) == ("10.0.0.2", 8080, "me@home", "p@ss:%1")
    assert net.requests_session("https://oauth2.googleapis.com/token").proxies["https"].startswith("http://me%40home:")
    db.set_setting("proxy.bypass", ".googleapis.com, intranet.example")
    assert net.requests_session("https://oauth2.googleapis.com/token").proxies == {}
    assert net.requests_session("https://accounts.google.com/").proxies["https"].startswith("http://me%40home:")
    assert not net.httplib2_proxy("https").applies_to("gmail.googleapis.com")
    assert net.bypassed("intranet.example") and net.bypassed("a.intranet.example") and not net.bypassed("notintranet.example")
    assert net.bypassed("localhost") and not net.bypassed("gmail.com")


def test_mail_the_applicant_sent_is_not_read_as_mail_from_an_employer(gmail, monkeypatch):
    """The program sent the applicant's reply to an employer ("Re: ... Job Application - ..."); the next look searched
    the whole mailbox, found that reply, took it for the employer asking for more, opened a card for it and drafted an
    answer to it (2026-11-23). What the applicant sent - from the mailbox, from an address of theirs, or a mail the
    program sent - is not read; only the employer's mail is."""
    from datetime import datetime, timedelta, timezone

    from autoapply.models import Outgoing

    db.set_setting("account.email", "applicant@example.org")
    with db.session() as s:
        s.add(Outgoing(kind="reply", to="hr@acme.example", subject="Re: Job Application", status="sent", message_id="m-sent-by-program", sent_from="applicant@gmail.example"))
    gmail.arrive("m-employer", "Re: Job Application - more documents, please", sender="HR <hr@acme.example>")
    gmail.arrive("m-sent", "Re: Job Application", sender="Me <me@example.com>", labels=("SENT",))
    gmail.arrive("m-sent-by-program", "Re: Job Application", sender="applicant@gmail.example", labels=("INBOX",))
    gmail.arrive("m-other-address", "Re: Job Application", sender="Applicant <APPLICANT@example.org>")
    gmail.arrive("m-from-the-mailbox", "Re: Job Application", sender="me@example.com")
    got = mailbox.fetch(datetime.now(timezone.utc) - timedelta(days=3), 10, job_related=True, skip=lambda i: False)
    assert [m.id for m in got] == ["m-employer"]
    assert "-in:sent" in gmail.queries[-1] and "-in:drafts" in gmail.queries[-1]       # (left out by the search already)
    assert db.get_setting("mail.address") == "me@example.com"                         # the mailbox's own address, asked once
    # what arrived since the last look: the same
    mail.mark_history()
    gmail.arrive("m-new-sent", "Re: Interview", sender="me@example.com")
    gmail.arrive("m-new", "Interview invitation", sender="hr@acme.example")
    assert [m.id for m in mailbox.fetch_new()] == ["m-new"]


def test_what_the_applicants_own_mail_did_before_is_taken_back_once(app_env):
    from autoapply import lifecycle
    from autoapply.models import Application, Job, MailEvent, Outgoing, Todo, now

    db.set_setting("mail.address", "me@example.com")
    with db.session() as s:
        job = Job(source="manual", source_id="o1", company="Acme", title="Firmware Co-op", apply_url="https://acme.example/jobs/1", jd_text="x" * 300)
        s.add(job)
        s.flush()
        a = Application(job_id=job.id, status="confirmed")
        s.add(a)
        s.flush()
        app_id = a.id
        s.add(Outgoing(application_id=app_id, kind="reply", to="hr@acme.example", subject="Re: Job Application", status="sent", message_id="mine-1", sent_from="me@example.com"))
        at = now()
        s.add(MailEvent(message_id="mine-1", sender="me@example.com", subject="Re: Job Application", category="interview", application_id=app_id, created_at=at, summary="the reply"))
        lifecycle.move(s.get(Application, app_id), "interview", source="mail", at=at)
        s.add(MailEvent(message_id="theirs-1", sender="HR <hr@acme.example>", subject="Re: Job Application", category="info_request", application_id=app_id, summary="more documents"))
        card = Todo(kind="followup", ref=f"followup:{app_id}:interview", title="Acme: interview", payload={"message_id": "mine-1", "application_id": app_id})
        theirs = Todo(kind="followup", ref=f"followup:{app_id}:info_request", title="Acme: more documents", payload={"message_id": "theirs-1", "application_id": app_id})
        s.add_all([card, theirs])
        s.flush()
        s.add(Outgoing(application_id=app_id, kind="reply", to="me@example.com", subject="Re: Re: Job Application", status="draft", todo_id=card.id, in_reply_to="mine-1"))
        card_id, theirs_id = card.id, theirs.id
    assert mail.forget_own_mail() == 1
    with db.session() as s:
        assert s.query(MailEvent).filter_by(message_id="mine-1").one().category == "other"
        assert s.query(MailEvent).filter_by(message_id="theirs-1").one().category == "info_request"       # the employer's mail is untouched
        assert s.get(Todo, card_id).status == "dismissed" and s.get(Todo, theirs_id).status == "open"
        assert s.query(Outgoing).filter_by(status="draft").count() == 0
        assert s.get(Application, app_id).status == "confirmed"                                         # the move it made, taken back
    assert mail.forget_own_mail() == 0
