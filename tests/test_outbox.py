"""E-mail the program writes for the applicant: an application sent by e-mail, a reply to an employer (outbox.py).

What is held here: nothing goes out that is not on record first; a mail is sent once; a mail with something still to be
filled in by the applicant is not sent; an application sent by e-mail is "sent" from the moment the mailbox took it,
with the mailbox's id as its evidence; and the mailbox keeps reading with the authorization it has until the applicant
grants more.
"""
from __future__ import annotations

import json

import pytest

from autoapply import db


@pytest.fixture()
def mailbox(app_env, monkeypatch):
    """A mailbox that may send, and takes what it is given."""
    from autoapply import mail

    sent: list[dict] = []

    def send_message(**kw):
        sent.append(kw)
        return {"id": f"m{len(sent)}", "thread_id": f"t{len(sent)}", "from": "alex@example.com"}

    monkeypatch.setattr(mail, "can_send", lambda: True)
    monkeypatch.setattr(mail, "send_message", send_message)
    return sent


def _application(status="recon"):
    import uuid

    from autoapply.models import Application, Job

    with db.session() as s:
        j = Job(source="manual", source_id=uuid.uuid4().hex, company="Acme", title="Backend Intern", apply_url="https://acme.example/jobs/1", channel="email", jd_text="Send your résumé to jobs@acme.example", status="queued", online=1)
        s.add(j)
        s.flush()
        a = Application(job_id=j.id, status=status, channel="email")
        s.add(a)
        s.flush()
        return a.id, j.id


def test_an_application_by_email_is_on_record_looked_at_and_sent_once_with_its_evidence(mailbox, tmp_path):
    from autoapply import outbox
    from autoapply.models import Application, Todo

    app_id, _ = _application()
    cv = tmp_path / "resume.pdf"
    cv.write_bytes(b"%PDF-1.4 x")
    oid = outbox.compose(app_id, kind="application", to="jobs@acme.example", subject="Backend Intern - Alex Chen", body="Dear team,\n\nPlease find my résumé attached.\n\nAlex Chen",
                         attachments=[{"name": "resume.pdf", "path": str(cv)}], title="Acme · Backend Intern")
    with db.session() as s:
        card = s.query(Todo).filter_by(kind="mail_out", status="open").one()
        assert card.payload["outgoing_id"] == oid and card.ref == f"mail:{oid}"
    assert mailbox == []                                                   # written is not sent
    got = outbox.edit(oid, {"subject": "Application: Backend Intern - Alex Chen", "cc": "alex@example.com"})
    assert got["subject"].startswith("Application:") and got["can_edit"]
    outbox.send(oid)
    outbox.send(oid)                                                       # pressed twice
    assert len(mailbox) == 1 and mailbox[0]["to"] == "jobs@acme.example" and mailbox[0]["attachments"][0]["name"] == "resume.pdf"
    with db.session() as s:
        a = s.get(Application, app_id)
        assert a.status == "submitted" and a.evidence["mail"] == {"outgoing_id": oid, "message_id": "m1", "thread_id": "t1"}
        assert "jobs@acme.example" in a.evidence["text"] and "resume.pdf" in a.evidence["text"]
        assert s.query(Todo).filter_by(kind="mail_out", status="open").count() == 0
    with pytest.raises(outbox.NotNow):
        outbox.edit(oid, {"body": "changed after it went"})
    # a second mail written for the same application replaces the one that was not sent; a file that is gone is said
    a2, _ = _application()
    first = outbox.compose(a2, kind="application", to="jobs@acme.example", subject="s", body="b", attachments=[{"name": "resume.pdf", "path": str(cv)}])
    second = outbox.compose(a2, kind="application", to="jobs@acme.example", subject="s2", body="b2", attachments=[{"name": "resume.pdf", "path": str(cv)}])
    assert outbox.get(first)["status"] == "discarded" and outbox.get(second)["status"] == "draft"
    cv.unlink()
    with pytest.raises(outbox.NotNow, match="附件"):
        outbox.send(second)
    with pytest.raises(ValueError):
        outbox.compose(a2, kind="application", to="nobody", subject="s", body="b")


def test_a_mail_that_could_not_be_sent_is_still_there_and_one_without_the_permission_says_so(app_env, monkeypatch):
    from autoapply import mail, outbox, secrets

    app_id, _ = _application()
    oid = outbox.compose(app_id, kind="application", to="jobs@acme.example", subject="s", body="b")
    # the mailbox was authorized for reading only: what it has keeps working, and sending says what is missing
    secrets.put(secrets.GMAIL_TOKEN, json.dumps({"refresh_token": "r", "client_id": "c", "client_secret": "x", "scopes": [mail.READ]}))
    assert mail.granted() == {mail.READ} and mail.can_send() is False and mail.status()["can_send"] is False
    with pytest.raises(outbox.NotNow, match="重新授权"):
        outbox.send(oid)
    assert outbox.get(oid)["status"] == "failed" and outbox.get(oid)["can_edit"]
    secrets.put(secrets.GMAIL_TOKEN, json.dumps({"refresh_token": "r", "client_id": "c", "client_secret": "x", "scopes": mail.SCOPES}))
    assert mail.can_send() is True
    monkeypatch.setattr(mail, "send_message", lambda **kw: {"id": "m9", "thread_id": "t9", "from": "alex@example.com"})
    assert outbox.send(oid)["status"] == "sent"


def test_a_reply_says_what_only_the_applicant_knows_and_is_not_sent_while_that_is_open(mailbox, monkeypatch):
    from autoapply import llm, mail, outbox, reminders, tasks
    from autoapply import handlers  # noqa: F401  (registers the task)
    from autoapply.models import Todo

    app_id, _ = _application("submitted")
    monkeypatch.setattr(mail, "original", lambda mid: {"from": "Dana <dana@acme.example>", "reply_to": "", "subject": "Three quick questions", "message_id_header": "<x@acme>",
                                                       "references": "<x@acme>", "thread_id": "t7", "body": "Are you eligible for SWPP? Can you work on site? Where do you live?"})
    asked = {}

    def fake_json(prompt, schema, **kw):
        asked["prompt"], asked["system"] = prompt, kw.get("system")
        return {"subject": "ignored", "body": "Hi Dana,\n\nI can work on site in North Vancouver, and I live in Richmond.\n\nAlex", "missing": ["你是否符合 SWPP 资格？"]}

    monkeypatch.setattr(llm, "json", fake_json)
    tid = reminders.from_mail(app_id, "Acme · Backend Intern", "info_request", "new", "three questions", {"action": "answer three questions", "due": "2026-11-24T17:00"}, "gm-1")
    assert tasks.drain() == 1                                   # the answer is written without anybody asking for it
    with db.session() as s:
        oid = s.get(Todo, tid).payload["outgoing_id"]
    out = outbox.get(oid)
    assert out["to"] == "Dana <dana@acme.example>" and out["subject"] == "Re: Three quick questions" and out["missing"] == ["你是否符合 SWPP 资格？"]
    assert "SWPP" in asked["prompt"] and "do not guess" in asked["system"]
    with pytest.raises(outbox.NotNow, match="需要你填写"):
        outbox.send(oid)
    outbox.edit(oid, {"body": out["body"].replace("[[你是否符合 SWPP 资格？]]", "Yes, I am eligible for SWPP.")})
    outbox.send(oid)
    assert mailbox[0]["in_reply_to"] == "gm-1" and "eligible for SWPP" in mailbox[0]["body"]
    with db.session() as s:
        assert s.get(Todo, tid).status == "done"                # what the employer asked has been answered
    # set to go by themselves: a reply with nothing missing goes; one with something missing never does
    db.set_setting("mail.send", "auto")
    app2, _ = _application("submitted")
    t2 = reminders.from_mail(app2, "Acme · Backend Intern", "info_request", "new", "one more", {"action": "confirm"}, "gm-2")
    assert tasks.drain() == 1 and len(mailbox) == 1             # (the model's answer still has the open question in it)
    monkeypatch.setattr(llm, "json", lambda *a, **k: {"subject": "s", "body": "Hi Dana,\n\nConfirmed.\n\nAlex", "missing": []})
    outbox.draft_reply(t2)
    assert len(mailbox) == 2 and mailbox[1]["in_reply_to"] == "gm-2"


def test_the_agent_hands_an_applications_mail_over_and_the_applicants_setting_decides_when_it_goes(mailbox, tmp_path, monkeypatch):
    import contextlib

    from autoapply import browser, outbox, tasks
    from autoapply import handlers  # noqa: F401
    from autoapply.agent import run
    from autoapply.agent.run import Desk
    from autoapply.models import Application

    # the tool: not around open questions, only files that are there
    desk = Desk(tmp_path / "app", None, site="generic:acme.example", mode="auto")
    handed = []
    desk.mail_out = lambda to, cc, subject, body, files: handed.append((to, subject, files)) or {"id": 5, "sent": False, "why": "they look first"}
    desk.hands = type("H", (), {"files": {"resume.pdf": str(tmp_path / "resume.pdf")}})()
    desk.asked = [{"question": "When can you start?"}]
    assert "not answered" in desk.email_application("jobs@acme.example", "s", "b") and not handed
    desk.asked = []
    with pytest.raises(ValueError, match="not among the files"):
        desk.email_application("jobs@acme.example", "s", "b", files=["transcript.pdf"])
    assert "with the applicant" in desk.email_application("jobs@acme.example", "s", "b", files=["resume.pdf"]) and desk.mailed["id"] == 5

    # the whole way: the run hands the mail over; looked at first unless the applicant set otherwise
    monkeypatch.setattr(browser, "open_page", lambda *a, **k: contextlib.nullcontext(object()))

    def apply(page, posting, applicant, folder, *, mail_out=None, mode="prepare", **kw):
        folder.mkdir(parents=True, exist_ok=True)
        got = mail_out("jobs@acme.example", "", "Backend Intern - Alex Chen", "Dear team,\n\nAlex", {})
        return run.Result(outcome="mailed", record={"outcome": "mailed", "mail": got, "asked": []}, stopped="end_turn", steps=6, seconds=30.0)

    monkeypatch.setattr(run, "apply", apply)
    app_id, job_id = _application()
    tasks.enqueue("apply", ref=f"job:{job_id}", payload={"job_id": job_id})
    assert tasks.drain() == 1 and mailbox == []
    with db.session() as s:
        assert s.get(Application, app_id).status == "needs_human"
    oid = outbox.of_application(app_id)[0]["id"]
    outbox.send(oid)                                             # the applicant presses send
    with db.session() as s:
        assert s.get(Application, app_id).status == "submitted" and len(mailbox) == 1
    db.set_setting("mail.send", "auto")
    app2, job2 = _application()
    tasks.enqueue("apply", ref=f"job:{job2}", payload={"job_id": job2})
    assert tasks.drain() == 1 and len(mailbox) == 2              # sent by itself, as set
    with db.session() as s:
        a = s.get(Application, app2)
        assert a.status == "submitted" and a.auto_approved == 1


def test_a_confirmation_is_looked_for_only_where_and_while_it_is_needed(app_env, monkeypatch):
    """Looks for one application's confirmation stood in the queue for applications confirmed long before, on a
    mailbox that is asked every two minutes what is new anyway."""
    from autoapply import chain, handlers, lifecycle, mail, mailbox, tasks  # noqa: F401
    from autoapply.models import Application, Task

    app_id, _ = _application("submitted")
    monkeypatch.setattr(mailbox, "incremental", lambda: True)
    assert mail.watches_new_mail() and mail.watch_for_confirmation(app_id) == 0        # the check every few minutes finds it
    db.set_setting("schedule.mail_new_minutes", 0)
    assert not mail.watches_new_mail() and mail.watch_for_confirmation(app_id) == 2    # switched off: this application is looked for
    with db.session() as s:
        lifecycle.move(s.get(Application, app_id), "confirmed", source="mail")
    chain.mend()
    with db.session() as s:
        assert [t.status for t in s.query(Task).filter(Task.ref == f"confirm:{app_id}")] == ["cancelled", "cancelled"]
    # one that comes due for an application confirmed meanwhile reads nothing
    read = []
    monkeypatch.setattr(mail, "track", lambda **kw: read.append(kw) or {"status_updates": 0})
    tasks.enqueue("mail", ref=f"confirm:{app_id}", dedupe=False)
    assert tasks.drain() == 1 and read == []


class _Mailbox:
    """Gmail's service, as far as sending uses it: it can drop the connection before, or after, it took the mail."""

    def __init__(self, drops):
        self.drops, self.sent, self.calls = list(drops), [], []

    def users(self):
        return self

    def messages(self):
        return self

    def getProfile(self, **kw):  # noqa: N802
        return self._call("profile", lambda: {"emailAddress": "alex@example.com"})

    def list(self, **kw):
        want = kw["q"].partition(":")[2]
        return self._call("list", lambda: {"messages": [{"id": f"g{i}", "threadId": f"t{i}"} for i, mid in enumerate(self.sent) if mid == want]})

    def send(self, **kw):
        import base64
        import email

        mid = email.message_from_bytes(base64.urlsafe_b64decode(kw["body"]["raw"]))["Message-ID"].strip("<>")

        def go():
            how = self.drops.pop(0) if self.drops else ""
            if how != "before":
                self.sent.append(mid)
            if how:
                import ssl

                raise ssl.SSLEOFError("EOF occurred in violation of protocol")
            return {"id": f"g{len(self.sent) - 1}", "threadId": "t"}

        return self._call("send", go)

    def _call(self, name, fn):
        self.calls.append(name)
        return type("R", (), {"execute": staticmethod(fn)})()


def test_a_mail_goes_out_once_through_a_connection_that_drops(app_env, monkeypatch):
    """A reply was not sent: the connection to the mailbox was cut once, and nothing tried again. Trying again blindly
    would send a mail twice when only the answer was lost."""
    import ssl

    from autoapply import mail, outbox

    monkeypatch.setattr(mail, "can_send", lambda: True)
    monkeypatch.setattr(mail.time, "sleep", lambda s: None)
    for drops, tries in ((["before"], 2), (["after"], 1), ([], 1)):
        box = _Mailbox(drops)
        monkeypatch.setattr(mail, "_service", lambda box=box: box)
        got = mail.send_message(to="jobs@acme.example", subject="s", body="b")
        assert len(box.sent) == 1 and box.calls.count("send") == tries and got["id"] == "g0", drops      # one mail, whatever was lost on the way
    # a connection that stays down: said in the program's words, and the mail is still there to send
    box = _Mailbox(["before"] * 5)
    monkeypatch.setattr(mail, "_service", lambda: box)
    app_id, _ = _application()
    oid = outbox.compose(app_id, kind="application", to="jobs@acme.example", subject="s", body="b")
    with pytest.raises(ssl.SSLError):
        outbox.send(oid)
    left = outbox.get(oid)
    assert left["status"] == "failed" and left["can_edit"] and "网络中断" in left["error"] and "SSL" not in left["error"] and box.sent == []


def test_a_mail_in_the_conversation_of_an_applications_mail_is_about_that_application(app_env, monkeypatch):
    """The employer's answer to a reply the program sent named nothing the matcher could use ("Re: three quick
    questions", from a person, not from Acme's careers address): it asked which application it was about."""
    from datetime import datetime, timedelta, timezone

    from autoapply import mail, mailbox, notify
    from autoapply.models import MailEvent, Outgoing

    monkeypatch.setattr(notify, "send", lambda *a, **k: True)
    app_id, _ = _application("submitted")
    other, _ = _application("submitted")
    with db.session() as s:
        s.add(Outgoing(application_id=app_id, kind="reply", to="dana@acme.example", subject="Re: questions", body="b", status="sent", thread_id="t-ours"))
    box: list = []
    monkeypatch.setattr(mailbox, "fetch", lambda *a, **k: list(box))
    monkeypatch.setattr(mail, "triage", lambda subj, frm, body, *when: {"company": "", "job_title": "", "category": "interview", "event": "new", "summary": "an interview", "received": False})
    now = datetime.now(timezone.utc)

    def arrives(mid, thread, n):
        box[:] = [mailbox.Message(id=mid, sender="Dana <dana@acme.example>", subject="Re: questions", body="Can you talk on Friday?", date=now + timedelta(minutes=n), thread=thread)]
        mail.track()
        with db.session() as s:
            e = s.query(MailEvent).filter_by(message_id=mid).one()
            return e.application_id, e.linked_by

    assert arrives("m1", "t-ours", 1) == (app_id, "thread")        # the thread of the program's own reply
    assert arrives("m2", "t-ours", 2) == (app_id, "thread")
    assert arrives("m3", "t-new", 3) == (None, "")                  # a conversation of its own: asked, as before
    assert arrives("m4", "t-new", 4) == (None, "")
    mail.link("m3", [other])                                         # the applicant says which: the rest of that conversation follows
    with db.session() as s:
        assert {e.message_id: (e.application_id, e.linked_by) for e in s.query(MailEvent).filter_by(thread_id="t-new")} == {"m3": (other, "user"), "m4": (other, "thread")}
    # a conversation that has been put on two applications says nothing
    with db.session() as s:
        s.query(MailEvent).filter_by(message_id="m4").update({"application_id": app_id})
    assert mail.of_thread("t-new") is None and mail.of_thread("t-ours") == app_id and mail.of_thread("") is None
