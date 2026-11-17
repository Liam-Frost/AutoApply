"""What the program knows about a site is kept in one place, under one key (sites.py)."""

from __future__ import annotations

import json

from autoapply import config, db, knowledge, learned, sites

RECIPE = json.dumps({"controls": [{"when": {"label": "^Code$"}, "do": "leave_if_shown"}]})


def _all_of_it(key):
    sites.link("generic:apply.acme.example", key)
    sites.set_fact(key, "sso_offered", ["google"])
    sites.set_fact(key, "driver_written", True)
    sites.note(key, "The phone code list shows only +1 once chosen.")
    sites.note(key, "Upload the résumé first.")
    sites.save_plan(key, {"steps": {"Contact": {"questions": [{"label": "City", "type": "text", "selector": "#a"}]}}, "pages": ["Contact"]})
    return learned.add("recipe", key, "Code 已显示就不再选", "区号列表只显示 +1", RECIPE)


def test_one_key_reaches_everything_known_about_a_site_whatever_spelling_it_was_kept_under(app_env, monkeypatch):
    from autoapply import fixtures
    from autoapply.ats.base import FormSchema

    monkeypatch.setattr(fixtures, "run_all", lambda ats=None: {"fixtures": 0, "failed": 0, "results": []})
    key = "generic:careers.acme.example"
    rev = _all_of_it("site-careers.acme.example")                       # the spelling notes, steps and revisions used to have
    got = sites.about(key)
    assert got["name"] == "careers.acme.example" and got["explored"] and got["facts"]["sso_offered"] == ["google"] and got["facts"]["driver_written"] is True
    assert [n["text"] for n in got["notes"]] == ["Upload the résumé first.", "The phone code list shows only +1 once chosen."]      # newest first
    assert got["steps"] == [{"title": "Contact", "questions": ["City"]}] and [r["id"] for r in got["revisions"]] == [rev["id"]]
    assert sites.account("generic:apply.acme.example") == key and sites.account(key) == key
    assert sites.notes(key).splitlines()[0].endswith("Upload the résumé first.")
    # a form the agent explored is the site's; one a coded driver reads is the system's - whose notes are the applicant's playbook
    assert sites.of_form(FormSchema(ats="generic", tenant="careers.acme.example", url="x", source="agent")) == key
    assert sites.of_form(FormSchema(ats="workday", tenant="acme.wd1", url="x", source="walk")) == "workday"
    assert sites.of_form(FormSchema(ats="workday", tenant="acme.wd1", url="x", source="agent")) == "workday:acme.wd1"      # explored on a system with a driver: the site, as its account is keyed
    sites.note("workday", "The date picker wants the month first.")
    assert "month first" in knowledge.playbook("workday") and "month first" in sites.notes("workday")
    assert [row["key"] for row in sites.listing()] == ["generic:apply.acme.example", key]
    assert next(r for r in sites.listing() if r["key"] == key)["revisions"] == 1


def test_forgetting_a_site_takes_what_was_learned_about_working_it_and_leaves_its_sign_in(app_env, monkeypatch):
    from autoapply import fixtures

    monkeypatch.setattr(fixtures, "run_all", lambda ats=None: {"fixtures": 0, "failed": 0, "results": []})
    key = "generic:careers.acme.example"
    rev = _all_of_it(key)
    sites.set_fact(key, "session_browser", "nodriver")
    assert sites.forget(key) == {"notes": 2, "steps": 1, "revisions": 1}
    got = sites.about(key)
    assert got["notes"] == [] and got["steps"] == [] and learned.get(rev["id"])["status"] == "reverted" and got["facts"]["driver_written"] is False
    assert got["facts"]["session_browser"] == "nodriver" and got["facts"]["sso_offered"] == ["google"]       # about the account: still true
    assert sites.account("generic:apply.acme.example") == key


def test_a_site_that_moved_takes_everything_with_it(app_env, monkeypatch):
    from autoapply import fixtures

    monkeypatch.setattr(fixtures, "run_all", lambda ats=None: {"fixtures": 0, "failed": 0, "results": []})
    old, new = "generic:careers.acme.example", "generic:jobs.acme.example"
    rev = _all_of_it(old)
    assert sites.move(old, new) and not sites.move("generic:nowhere.example", new)
    got = sites.about(new)
    assert len(got["notes"]) == 2 and got["steps"] and [r["id"] for r in got["revisions"]] == [rev["id"]] and got["facts"]["sso_offered"] == ["google"]
    assert sites.about(old)["notes"] == [] and sites.account("generic:apply.acme.example") == new      # what signed in there follows


def test_what_earlier_versions_kept_in_five_places_is_brought_into_the_one(app_env, monkeypatch):
    from autoapply import fixtures
    from autoapply.models import Run

    monkeypatch.setattr(fixtures, "run_all", lambda ats=None: {"fixtures": 0, "failed": 0, "results": []})
    db.set_setting("accounts.alias", {"generic:www.google.com": "idp:google"})
    db.set_setting("sso.offered", {"generic:jobs.acme.example": ["google", "linkedin"]})
    db.set_setting("browser.visible_sites", ["generic:www.amazon.jobs"])
    db.set_setting("browser.session_made_in", {"idp:google": "nodriver"})
    db.set_setting("learned.drivers_written", ["site-jobs.acme.example"])
    config.PLAYBOOKS.mkdir(parents=True, exist_ok=True)
    (config.PLAYBOOKS / "site-jobs.acme.example.md").write_text(
        knowledge.NOTES_HEAD + "\n- (2026-11-16) The phone code list shows only +1.\n- (2026-11-12) Upload first.\n\nWritten by hand: ask HR for the code.\n", encoding="utf-8")
    (config.PLAYBOOKS / "workday.md").write_text("# Workday\n\nThe applicant's own notes.\n", encoding="utf-8")
    (config.DATA / "sites").mkdir(parents=True, exist_ok=True)
    (config.DATA / "sites" / "site-jobs.acme.example.json").write_text(json.dumps({"steps": {"Contact": {"questions": [{"label": "City"}]}}}), encoding="utf-8")
    rev = learned.add("recipe", "site-jobs.acme.example", "Code", "w", RECIPE)
    with db.session() as s:
        s.add(Run(kind="execute", ref="application:1", ats="generic", ok=1, site="site-jobs.acme.example", steps=[], spans=[]))
        s.add(Run(kind="execute", ref="application:2", ats="workday", ok=1, site="workday", steps=[], spans=[]))
    # ... and a site on a system with a driver, whose notes were filed by the last part of its name only
    from autoapply import auth

    auth.upsert_account("workday:ciena.wd5", ats="workday", host="ciena.wd5.myworkdayjobs.com", status="ok")
    (config.PLAYBOOKS / "site-ciena.wd5.md").write_text(knowledge.NOTES_HEAD + "\n- (2026-11-10) The date picker wants the month first.\n", encoding="utf-8")
    with db.session() as s:
        s.add(Run(kind="execute", ref="application:3", ats="workday", ok=1, site="site-ciena.wd5", steps=[], spans=[]))
    done = sites.migrate()
    assert done == {"links": 1, "facts": 4, "notes": 4, "plans": 1, "revisions": 1, "runs": 2}
    assert "month first" in sites.notes("workday:ciena.wd5") and sites.about("generic:ciena.wd5")["notes"] == []
    key = "generic:jobs.acme.example"
    got = sites.about(key)
    assert [n["at"] for n in got["notes"]][:2] == ["2026-11-16", "2026-11-12"] and "ask HR for the code" in got["notes"][2]["text"]
    assert got["steps"] == [{"title": "Contact", "questions": ["City"]}] and got["facts"]["driver_written"] is True and got["facts"]["sso_offered"] == ["google", "linkedin"]
    assert sites.account("generic:www.google.com") == "idp:google" and sites.fact("idp:google", "session_browser") == "nodriver"
    assert sites.fact("generic:www.amazon.jobs", "needs_window") is True
    assert learned.get(rev["id"])["target"] == key
    with db.session() as s:
        assert sorted(r.site for r in s.query(Run)) == [key, "workday", "workday:ciena.wd5"]
    # what was read is kept beside where it was, and the applicant's own playbooks are not touched
    assert (config.PLAYBOOKS / "migrated" / "site-jobs.acme.example.md").exists() and not (config.PLAYBOOKS / "site-jobs.acme.example.md").exists()
    assert (config.PLAYBOOKS / "workday.md").exists() and (config.DATA / "sites" / "migrated" / "site-jobs.acme.example.json").exists()
    assert sites.migrate() == {"links": 1, "facts": 4, "notes": 0, "plans": 0, "revisions": 0, "runs": 0}       # run again: nothing is doubled
    assert len(sites.about(key)["notes"]) == 3


def test_the_analysis_page_gets_each_site_and_can_clear_one(app_env, monkeypatch):
    from fastapi.testclient import TestClient

    from autoapply import fixtures
    from autoapply.api.main import app

    monkeypatch.setattr(fixtures, "run_all", lambda ats=None: {"fixtures": 0, "failed": 0, "results": []})
    key = "generic:careers.acme.example"
    _all_of_it(key)
    sites.set_fact("idp:google", "session_browser", "nodriver")         # a record about a sign-in only: not something "learned about working a site"
    c = TestClient(app)
    listed = c.get("/api/sites").json()
    assert {r["key"] for r in listed} >= {key, "idp:google"}
    shown = c.get("/api/analytics/timing").json()["sites"]
    assert [(r["name"], r["notes"], r["steps"], r["questions"], r["revisions"]) for r in shown] == [("careers.acme.example", 2, 1, 1, 1)]
    one = c.get(f"/api/sites/{key}").json()
    assert one["steps"][0]["title"] == "Contact" and len(one["notes"]) == 2
    assert c.post(f"/api/sites/{key}/forget").json() == {"notes": 2, "steps": 1, "revisions": 1}
    assert c.get("/api/analytics/timing").json()["sites"] == []
