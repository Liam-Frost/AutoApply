"""The settings of time: the calendar's time zone, the reminders each kind of item gets by itself, the quiet hours.

The page chooses a zone from the server's list (GET /api/time/zones: every zone with its offset now, from the program's
own rules), shows the reminders as words but keeps them as minutes, and sets the quiet hours with two times - so what
the server accepts, and what it does with what it accepted, is checked here; how the page shows it is in
frontend/tests/{timezones,reminder-rules,combobox}.test.js.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from autoapply import db


@pytest.fixture()
def client(app_env):
    from autoapply.api.main import app

    return TestClient(app)


def _put(client, settings):
    return client.put("/api/settings", json={"settings": settings, "secrets": {}})


# --- the list of zones ----------------------------------------------------------------------------------------------------

def test_the_list_of_zones_has_every_zone_with_its_offset_now_its_country_and_what_an_old_spelling_stands_for(client):
    d = client.get("/api/time/zones").json()
    assert set(d) >= {"system", "chosen", "chosen_valid", "zones"}
    assert isinstance(d["system"], str) and d["chosen"] == "" and d["chosen_valid"] is True       # nothing chosen: the computer's
    zones = {z["id"]: z for z in d["zones"]}
    assert len(zones) > 400 and all(isinstance(z["offset"], int) for z in d["zones"])
    assert "Factory" not in zones and "localtime" not in zones
    assert zones["America/Vancouver"]["country"] == "CA" and "alias_of" not in zones["America/Vancouver"]
    assert zones["US/Pacific"]["alias_of"] == "America/Los_Angeles" and zones["PRC"]["alias_of"] == "Asia/Shanghai"
    assert zones["Asia/Calcutta"]["alias_of"] == "Asia/Kolkata" and zones["UTC"]["alias_of"] == "Etc/UTC"
    assert "alias_of" not in zones["Africa/Accra"] and zones["Africa/Accra"]["country"] == "GH"      # a place of its own, though linked
    assert zones["Asia/Kolkata"]["offset"] == 330 and zones["Asia/Kathmandu"]["offset"] == 345      # half and quarter hours
    assert zones["Etc/GMT+5"]["offset"] == -300 and "country" not in zones["Etc/GMT+5"]              # (the sign of Etc/ is the other way round)


def test_the_offsets_are_the_programs_own_rules_british_columbia_keeps_utc_minus_seven(app_env):
    from autoapply import clock

    winter = {z["id"]: z["offset"] for z in clock.zones(datetime(2027, 1, 15, 12, tzinfo=timezone.utc))}
    summer = {z["id"]: z["offset"] for z in clock.zones(datetime(2027, 7, 15, 12, tzinfo=timezone.utc))}
    assert winter["America/Vancouver"] == summer["America/Vancouver"] == -420      # no change of clocks since 2026
    assert (winter["America/Los_Angeles"], summer["America/Los_Angeles"]) == (-480, -420)
    assert (winter["America/Toronto"], summer["America/Toronto"]) == (-300, -240)
    assert (winter["Australia/Sydney"], summer["Australia/Sydney"]) == (660, 600)      # (the other half of the world)
    assert winter["US/Pacific"] == winter["America/Los_Angeles"]


# --- the zone setting -----------------------------------------------------------------------------------------------------

def test_the_zone_setting_refuses_what_is_not_a_zone_and_keeps_an_old_spelling_as_it_is(client):
    from autoapply import clock

    r = _put(client, {"time.zone": "Vancouver time"})
    assert r.status_code == 400 and "Vancouver time" in r.json()["detail"]
    assert db.get_setting("time.zone") == ""
    assert _put(client, {"time.zone": "US/Pacific"}).status_code == 200
    assert db.get_setting("time.zone") == "US/Pacific" and clock.zone_name() == "US/Pacific"       # saved as written, never replaced
    d = client.get("/api/time/zones").json()
    assert d["chosen"] == "US/Pacific" and d["chosen_valid"] is True
    assert _put(client, {"time.zone": ""}).status_code == 200 and db.get_setting("time.zone") == ""


def test_a_saved_value_that_is_not_a_zone_is_said_to_be_one_and_the_computers_zone_is_used(client, monkeypatch):
    from autoapply import clock

    monkeypatch.setattr(clock, "system_zone", lambda: "America/Vancouver")
    db.set_setting("time.zone", "Mars/Olympus")           # (from an older version, or a hand-edited file)
    d = client.get("/api/time/zones").json()
    assert d["chosen"] == "Mars/Olympus" and d["chosen_valid"] is False and d["system"] == "America/Vancouver"
    assert clock.zone_name() == "America/Vancouver"
    assert db.get_setting("time.zone") == "Mars/Olympus"     # shown as it is until another is chosen


# --- the reminders of each kind -------------------------------------------------------------------------------------------

def test_the_reminders_of_each_kind_are_whole_minutes_from_zero_to_sixty_days_kept_once_largest_first(client):
    from autoapply import alarms

    ok = {"interview": [30, 1440, 30], "assessment": [120.0, 1440], "offer": [], "deadline": [0, 86400]}
    assert _put(client, {"calendar.reminders": ok}).status_code == 200
    kept = db.get_setting("calendar.reminders")
    assert kept == {"interview": [1440, 30], "assessment": [1440, 120], "offer": [], "deadline": [86400, 0]}
    assert alarms.defaults("interview") == [1440, 30] and alarms.defaults("offer") == [] and alarms.defaults("contact") == []


@pytest.mark.parametrize("bad", [
    {"interview": [-5]}, {"interview": [86401]}, {"interview": [1.5]}, {"interview": ["30"]}, {"interview": [True]},
    {"interview": [None]}, {"interview": 30}, {"party": [30]}, [30], "1440, 30",
])
def test_reminders_the_backend_would_not_keep_are_refused_and_nothing_of_that_save_is_written(client, bad):
    before = db.get_setting("calendar.reminders")
    r = _put(client, {"notify.todo": False, "calendar.reminders": bad})
    assert r.status_code == 400
    assert db.get_setting("calendar.reminders") == before and db.get_setting("notify.todo") is True


def test_the_reminders_mean_what_they_meant(app_env):
    from autoapply import alarms

    db.set_setting("calendar.allday_at", "09:00")
    at = datetime(2026, 12, 10, 14, 0)
    assert alarms.fire_at(at, False, 30) == datetime(2026, 12, 10, 13, 30)
    assert alarms.fire_at(at, False, 0) == at
    assert alarms.fire_at(at, True, 0) == datetime(2026, 12, 10, 9, 0)            # a whole day: in the morning
    assert alarms.fire_at(at, True, 120) == datetime(2026, 12, 9, 9, 0)           # less than a day before: the morning before
    assert alarms.fire_at(at, True, 2 * 1440) == datetime(2026, 12, 8, 9, 0)


# --- the quiet hours ------------------------------------------------------------------------------------------------------

def test_quiet_hours_saved_by_the_page_cross_midnight_as_before(client):
    from autoapply import notify

    assert _put(client, {"notify.quiet": {"on": True, "from": "22:00", "to": "08:00"}}).status_code == 200
    at = lambda h, m=0: datetime(2026, 11, 20, h, m)      # noqa: E731
    assert [notify.quiet_now(at(h, m)) for h, m in ((21, 59), (22, 0), (23, 30), (0, 0), (2, 0), (7, 59), (8, 0), (13, 0))] == [False, True, True, True, True, True, False, False]
    _put(client, {"notify.quiet": {"on": True, "from": "13:00", "to": "15:00"}})
    assert [notify.quiet_now(at(h)) for h in (12, 13, 14, 15)] == [False, True, True, False]
    _put(client, {"notify.quiet": {"on": True, "from": "09:00", "to": "09:00"}})
    assert not any(notify.quiet_now(at(h)) for h in range(24))                   # the same hour twice: no quiet hours
    _put(client, {"notify.quiet": {"on": False, "from": "22:00", "to": "08:00"}})
    assert notify.quiet_now(at(23)) is False



def test_the_quiet_hours_are_on_the_applicants_clock(client, monkeypatch):
    """Without a moment given, "now" is the applicant's (their time zone), not the computer's: the hours are their night."""
    from autoapply import clock, notify

    _put(client, {"notify.quiet": {"on": True, "from": "22:00", "to": "08:00"}})
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 11, 20, 23, 30))
    assert notify.quiet_now() is True
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 11, 20, 12, 0))
    assert notify.quiet_now() is False

def test_a_reminder_goes_through_the_quiet_hours_unless_it_is_told_to_wait(client, monkeypatch):
    from autoapply import alarms, notify

    sent = []
    monkeypatch.setattr(notify, "send", lambda *a, **k: sent.append(k.get("through_quiet")) or True)
    monkeypatch.setattr("autoapply.agenda.items", lambda *a, **k: [{"id": "todo:1", "start": "2026-11-20T23:30", "all_day": False, "done": False, "title": "Interview",
                                                                  "subject": "Northfield", "kind": "interview", "link": "", "about": {"todo_id": 1}}])
    alarms.add("todo:1", 30)
    assert _put(client, {"calendar.reminders_quiet": False}).status_code == 200
    assert alarms.tick(datetime(2026, 11, 20, 23, 5)) == 1 and sent == [True]       # its time, through the quiet hours
    alarms.remove(alarms.of("todo:1")[0]["id"])
    alarms.add("todo:1", 30)
    _put(client, {"calendar.reminders_quiet": True})
    assert alarms.tick(datetime(2026, 11, 20, 23, 5)) == 1 and sent == [True, False]   # held with the rest
