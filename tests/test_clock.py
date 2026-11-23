"""The applicant's clock, and the times employers' mails give on theirs.

A mail said an interview was "Tuesday, November 24, 10:00 AM (Surrey local time)"; the card kept 10:00 as if it were the
applicant's own time, eight time zones away. And an assessment "to be completed within 14 days" had no date at all.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from autoapply import db


@pytest.fixture()
def shanghai(app_env):
    db.set_setting("time.zone", "Asia/Shanghai")
    return app_env


def _application(company="Northfield Power Labs", location="Surrey, BC, Canada"):
    from autoapply.models import Application, Job

    with db.session() as s:
        j = Job(source="manual", source_id=company, company=company, title="Software Developer Co-op", location=location, apply_url="https://jobs.example/x",
                jd_text="x" * 300, status="applied", online=1)
        s.add(j)
        s.flush()
        a = Application(job_id=j.id, status="interview")
        s.add(a)
        s.flush()
        return a.id


def test_a_time_said_in_the_employers_zone_is_shown_on_the_applicants_clock(shanghai):
    from autoapply import clock, reminders

    # British Columbia stopped changing its clocks in 2026: in late November Vancouver is 7 hours behind UTC, Los Angeles 8
    due, facts = reminders.due_of({"due": "2026-11-24T10:00", "due_zone": "America/Vancouver"})
    assert due == datetime(2026, 11, 25, 1, 0) and facts["due_zone"] == "America/Vancouver" and facts["due_said"] == "2026-11-24T10:00" and not facts["zone_assumed"]
    assert reminders.due_of({"due": "2026-11-24T10:00", "due_zone": "America/Los_Angeles"})[0] == datetime(2026, 11, 25, 2, 0)
    assert reminders.due_of({"due": "2026-07-14T10:00", "due_zone": "America/Toronto"})[0] == datetime(2026, 7, 14, 22, 0)      # (and summer time where it is kept)
    # the applicant's own time is left as it is; so is a time nobody said the zone of - and that is said
    assert reminders.due_of({"due": "2026-11-24T10:00", "due_zone": "applicant"}) == (datetime(2026, 11, 24, 10, 0), {"date_only": False, "due_zone": "", "due_said": "", "zone_assumed": False})
    assert reminders.due_of({"due": "2026-11-24T10:00"})[1]["zone_assumed"] is True
    assert reminders.due_of({"due": "2026-11-24T10:00", "due_zone": "Mars/Olympus"})[0] == datetime(2026, 11, 24, 10, 0)       # (not a zone: as written)
    # a day has no zone; a moment with its offset is a moment
    assert reminders.due_of({"due": "2026-12-05", "due_zone": "America/Vancouver"}) == (datetime(2026, 12, 5), {"date_only": True, "due_zone": "", "due_said": "", "zone_assumed": False})
    assert reminders.due_of({"due": "2026-11-24T10:00-07:00"})[0] == datetime(2026, 11, 25, 1, 0)
    assert clock.zone_name() == "Asia/Shanghai" and clock.offset_minutes() == 480
    assert clock.valid("America/Vancouver") and not clock.valid("Vancouver time") and not clock.valid("")


def test_the_card_of_an_interview_carries_the_zone_and_a_later_mail_without_a_date_leaves_it(shanghai, monkeypatch):
    from autoapply import agenda, mail, reminders
    from autoapply.models import Todo

    app_id = _application()
    monkeypatch.setattr(mail, "when", lambda *a, **k: pytest.fail("the mail told the zone: nothing more is asked"))
    asks = mail._zoned(app_id, "interview", {"due": "2026-11-24T10:00", "due_zone": "America/Vancouver", "due_text": "Tuesday, November 24, 10:00 to 10:45 AM (Surrey local time)"})
    tid = reminders.from_mail(app_id, "Northfield", "interview", "changed", "the interview is confirmed", asks, "m1")
    reminders.from_mail(app_id, "Northfield", "interview", "new", "the Teams invitation", {"action": "attend"}, "m2")      # (names no time)
    with db.session() as s:
        t = s.get(Todo, tid)
        assert t.due_at == datetime(2026, 11, 25, 1, 0)
        assert t.payload["due_text"].startswith("Tuesday, November 24") and t.payload["due_zone"] == "America/Vancouver" and t.payload["message_id"] == "m2"
    item = next(x for x in agenda.items(datetime(2026, 11, 23).date(), datetime(2026, 11, 30).date()) if x["kind"] == "interview")
    assert item["start"] == "2026-11-25T01:00" and item["due_zone"] == "America/Vancouver" and item["due_said"] == "2026-11-24T10:00" and item["zone_assumed"] is False


def test_a_time_without_a_zone_is_asked_about_with_the_postings_place_beside_it(shanghai, monkeypatch):
    from autoapply import llm, mail, reminders
    from autoapply.models import MailEvent, Todo

    app_id = _application()
    with db.session() as s:
        s.add(MailEvent(message_id="m1", sender="hr@northfield.example", subject="Interview", received_at=datetime(2026, 11, 18, 16, 37), category="interview", event="new",
                        application_id=app_id, summary="Interview on Tuesday at 10", asks={"due": "2026-11-24T10:00", "due_text": "Tuesday at 10"}))
    seen = {}

    def answer(prompt, schema, **kw):
        seen["prompt"] = prompt
        return {"due": "2026-11-24T10:00", "due_zone": "America/Vancouver", "due_text": "Tuesday at 10"}

    monkeypatch.setattr(llm, "json", answer)
    asks = mail._zoned(app_id, "interview", {"due": "2026-11-24T10:00", "due_text": "Tuesday at 10"})
    assert asks["due_zone"] == "America/Vancouver"
    assert "Surrey, BC, Canada" in seen["prompt"] and "Asia/Shanghai" in seen["prompt"] and "Tuesday at 10" in seen["prompt"]
    tid = reminders.from_mail(app_id, "Northfield", "interview", "new", "Interview on Tuesday at 10", asks, "m1")
    with db.session() as s:
        assert s.get(Todo, tid).due_at == datetime(2026, 11, 25, 1, 0)
    # the AI not there: the card is made with the time as written, and says no zone was told
    monkeypatch.setattr(llm, "json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no model")))
    assert "due_zone" not in mail._zoned(app_id, "interview", {"due": "2026-12-01T09:00"})


def test_the_mail_reader_is_told_when_the_mail_was_sent_and_whose_zone_is_the_applicants(shanghai, monkeypatch):
    from autoapply import llm, mail

    seen = {}
    monkeypatch.setattr(llm, "json", lambda prompt, schema, **kw: seen.update(prompt=prompt, schema=schema) or {"category": "other", "company": "", "job_title": "", "summary": ""})
    mail.triage("Online assessment", "Amazon <no-reply@amazon.example>", "You have 14 days to complete it.", datetime(2026, 11, 9, 1, 30))      # (recorded in UTC)
    assert "Date: 2026-11-09 09:30 (Monday)" in seen["prompt"] and "Asia/Shanghai" in seen["prompt"]
    props = seen["schema"]["properties"]
    assert "due_zone" in props and "period" in props["due"]["description"] and "do NOT convert" in props["due"]["description"]


def test_cards_read_before_zones_were_asked_for_are_read_once_more(shanghai, monkeypatch):
    from autoapply import mail
    from autoapply.models import MailEvent, Todo

    iv, oa, mine = _application(), _application("Amazon", "Seattle, WA"), _application("Globex", "Toronto, ON")
    with db.session() as s:
        for app_id, cat, summary, asks in ((iv, "interview", "Tue Nov 24, 10:00 (Surrey local time)", {"due": "2026-11-24T10:00"}), (oa, "assessment", "you have 14 days", None)):
            s.add(MailEvent(message_id=f"m-{app_id}", sender="x", subject="x", received_at=datetime(2026, 11, 9, 1, 30), category=cat, event="new", application_id=app_id, summary=summary, asks=asks))
        s.add(Todo(kind="followup", ref=f"followup:{iv}:interview", title="interview", due_at=datetime(2026, 11, 24, 10, 0), payload={"application_id": iv, "category": "interview", "message_id": f"m-{iv}"}))
        s.add(Todo(kind="followup", ref=f"followup:{oa}:assessment", title="assessment", payload={"application_id": oa, "category": "assessment", "message_id": f"m-{oa}"}))
        s.add(Todo(kind="followup", ref=f"followup:{mine}:interview", title="mine", due_at=datetime(2026, 12, 1, 9, 0),
                   payload={"application_id": mine, "category": "interview", "message_id": "m-x", "date_by": "user"}))
    asked = []

    def when(app_id, category):
        asked.append(app_id)
        return {"due": "2026-11-24T10:00", "due_zone": "America/Vancouver", "due_text": "Tue Nov 24, 10:00 (Surrey local time)"} if app_id == iv else {"due": "2026-11-23", "due_text": "14 days from the invitation"}

    monkeypatch.setattr(mail, "when", when)
    assert mail.redate_cards() == 2 and sorted(asked) == [iv, oa]
    with db.session() as s:
        cards = {t.title: t for t in s.query(Todo)}
        assert cards["interview"].due_at == datetime(2026, 11, 25, 1, 0) and cards["interview"].payload["due_zone"] == "America/Vancouver"
        assert cards["assessment"].due_at == datetime(2026, 11, 23) and cards["assessment"].payload["date_only"] is True and cards["assessment"].payload["due_text"].startswith("14 days")
        assert cards["mine"].due_at == datetime(2026, 12, 1, 9, 0)        # (the applicant's own date is theirs)
    assert mail.redate_cards() == 0 and len(asked) == 2      # once


def test_now_and_recorded_moments_follow_the_zone_that_was_set(app_env):
    from autoapply import agenda, clock

    db.set_setting("time.zone", "Pacific/Auckland")
    assert abs((clock.now() - clock.to_local(datetime.utcnow())).total_seconds()) < 5
    assert agenda._local(datetime(2026, 11, 24, 0, 0)) == datetime(2026, 11, 24, 13, 0)
    db.set_setting("time.zone", "")
    assert abs((clock.now() - datetime.now()).total_seconds()) < 5      # (nothing set: the computer's clock)


def test_the_zone_setting_takes_only_a_zone(app_env):
    from fastapi import HTTPException

    from autoapply.api.main import calendar_items, get_settings, put_settings

    put_settings({"settings": {"time.zone": " America/Vancouver "}})
    assert db.get_setting("time.zone") == "America/Vancouver" and calendar_items("2026-11-23", "2026-11-30")["zone"] == "America/Vancouver"
    with pytest.raises(HTTPException) as e:
        put_settings({"settings": {"time.zone": "Vancouver time"}})
    assert e.value.status_code == 400
    put_settings({"settings": {"time.zone": ""}})
    assert "system_zone" in get_settings()


def test_an_update_already_running_is_not_offered_again(app_env, monkeypatch):
    """The about page said "Ready: 2.0.2 is prepared - switch to 2.0.2" on a program that was 2.0.2."""
    from autoapply import config, updates

    cur = updates.version()
    (config.DATA / "releases" / cur / "frontend" / "dist").mkdir(parents=True)
    db.set_setting(updates.STATE, {"latest": cur, "staged": cur, "status": "ready"})
    st = updates.status()
    assert st["staged"] == "" and st["status"] == "idle" and st["newer"] is False
    updates.after_start()
    assert updates.state().get("staged") == "" and updates.state().get("status") == "idle"
    # a newer one that is prepared is still offered
    newer = ".".join(str(int(p) + (1 if i == 0 else 0)) for i, p in enumerate(cur.split(".")[:3]))
    (config.DATA / "releases" / newer / "frontend" / "dist").mkdir(parents=True)
    db.set_setting(updates.STATE, {"latest": newer, "staged": newer, "status": "ready"})
    assert updates.status()["staged"] == newer and updates.status()["status"] == "ready"


def test_the_backlog_names_every_kind_and_gives_one_row_to_one_name(app_env):
    from autoapply import analytics
    from autoapply.models import Todo, now

    t = now()
    with db.session() as s:
        for kind in ("login", "takeover", "driver", "driver_patch", "answer", "something_new"):
            s.add(Todo(kind=kind, title=kind, status="done", created_at=t - timedelta(hours=2), done_at=t - timedelta(hours=1)))
        s.flush()
        got = analytics._backlog(s, analytics.Window(None, None, None, None, "", ""))      # (the whole record)
    labels = [str(r["label"]) for r in got["by_kind"]]
    assert len(labels) == len(set(labels)) and not any(x in labels for x in ("driver", "driver_patch", "login", "takeover", "something_new"))
    assert sorted(r["n"] for r in got["by_kind"]) == [1, 1, 2, 2] and got["handled"] == 6


def test_files_of_an_application_that_ended_unsent_are_not_in_preparation(app_env, tmp_path):
    from autoapply.api.main import list_documents
    from autoapply.models import Application, Document, Job

    with db.session() as s:
        for name, status, sent in (("Withdrawn Co", "withdrawn", None), ("Sent Co", "submitted", datetime(2026, 11, 20)), ("Working Co", "draft_ready", None)):
            j = Job(source="manual", source_id=name, company=name, title="Analyst", apply_url="https://jobs.example/" + name, jd_text="x" * 300, status="queued", online=1)
            s.add(j)
            s.flush()
            s.add(Application(job_id=j.id, status=status, submitted_at=sent))
            f = tmp_path / f"{name}.pdf"
            f.write_bytes(b"%PDF-1.4")
            s.add(Document(kind="cover_letter", name=f.name, path=str(f), job_id=j.id))
    rows = {r["job_company"]: r for r in list_documents()}
    assert (rows["Withdrawn Co"]["job_over"], rows["Withdrawn Co"]["job_sent"]) == (True, False)
    assert (rows["Sent Co"]["job_over"], rows["Sent Co"]["job_sent"]) == (False, True)
    assert (rows["Working Co"]["job_over"], rows["Working Co"]["job_sent"]) == (False, False)
