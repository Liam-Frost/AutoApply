"""What the program knows about a site is kept in one place, under one name (sites.py)."""
from __future__ import annotations

from autoapply import config, db, knowledge, sites


def _known(key):
    sites.note(key, "The phone code list shows only +1.")
    sites.note(key, "Upload the résumé first: the form fills itself from it.")
    sites.set_fact(key, "sso_offered", ["google"])
    sites.link("generic:apply.acme.example", key)


def test_a_site_is_named_the_way_its_account_and_session_have_always_been_kept(app_env):
    """The name is what a stored password, a saved session and the notes are found under: a site that had one before
    there was an agent keeps it."""
    for url, key in (("https://cnh.wd1.myworkdayjobs.com/en-US/CNH/job/X_123", "workday:cnh.wd1"), ("https://boards.greenhouse.io/acme/jobs/123", "greenhouse:acme"),
                     ("https://job-boards.greenhouse.io/embed/job_app?for=acme&token=5", "greenhouse:acme"), ("https://jobs.ashbyhq.com/openai/1b2c", "ashby:openai"),
                     ("https://pdportal.apsc.ubc.ca/myAccount/co-op/postings.htm#posting=1", "pdportal:ubc"), ("https://www.amazon.jobs/en/jobs/1/apply", "generic:www.amazon.jobs"),
                     ("https://acme.example/careers?gh_jid=5", "generic:acme.example"), ("https://jobs.lever.co/Acme/abc", "lever:acme")):
        assert sites.key_of(url) == key
    # told by the host, never by a name somewhere in the address
    assert sites.key_of("https://myworkdayjobs.com.evil.example/x") == "generic:myworkdayjobs.com.evil.example"
    assert sites.key_of("https://evil.example/?next=acme.wd1.myworkdayjobs.com") == "generic:evil.example"


def test_forgetting_a_site_takes_what_was_written_down_about_working_it_and_leaves_its_sign_in(app_env):
    key = "generic:careers.acme.example"
    _known(key)
    sites.set_fact(key, "session_browser", "nodriver")
    assert "Upload the résumé first" in sites.notes(key) and sites.forget(key) == {"notes": 2}
    got = sites.about(key)
    assert got["notes"] == [] and got["facts"]["session_browser"] == "nodriver" and got["facts"]["sso_offered"] == ["google"]       # about the account: still true
    assert sites.account("generic:apply.acme.example") == key


def test_a_site_that_moved_takes_everything_with_it(app_env):
    old, new = "generic:careers.acme.example", "generic:jobs.acme.example"
    _known(old)
    assert sites.move(old, new) and not sites.move("generic:nowhere.example", new)
    got = sites.about(new)
    assert len(got["notes"]) == 2 and got["facts"]["sso_offered"] == ["google"]
    assert sites.about(old)["notes"] == [] and sites.account("generic:apply.acme.example") == new      # what signed in there follows


def test_what_earlier_versions_kept_elsewhere_is_brought_into_the_one_place(app_env):
    db.set_setting("accounts.alias", {"generic:www.google.com": "idp:google"})
    db.set_setting("sso.offered", {"generic:jobs.acme.example": ["google", "linkedin"]})
    db.set_setting("browser.visible_sites", ["generic:www.amazon.jobs"])
    db.set_setting("browser.session_made_in", {"idp:google": "nodriver"})
    config.PLAYBOOKS.mkdir(parents=True, exist_ok=True)
    (config.PLAYBOOKS / "site-jobs.acme.example.md").write_text(
        knowledge.NOTES_HEAD + "\n- (2026-11-16) The phone code list shows only +1.\n- (2026-11-12) Upload first.\n\nWritten by hand: ask HR for the code.\n", encoding="utf-8")
    (config.PLAYBOOKS / "workday.md").write_text("# Workday\n\nThe applicant's own notes.\n", encoding="utf-8")
    done = sites.migrate()
    assert done == {"links": 1, "facts": 3, "notes": 3, "runs": 0}
    got = sites.about("generic:jobs.acme.example")
    assert [n["at"] for n in got["notes"]][:2] == ["2026-11-16", "2026-11-12"] and "ask HR for the code" in got["notes"][2]["text"] and got["facts"]["sso_offered"] == ["google", "linkedin"]
    assert sites.account("generic:www.google.com") == "idp:google" and sites.fact("idp:google", "session_browser") == "nodriver" and sites.fact("generic:www.amazon.jobs", "needs_window") is True
    # what was read is kept beside where it was, and the applicant's own playbooks are not touched
    assert (config.PLAYBOOKS / "migrated" / "site-jobs.acme.example.md").exists() and (config.PLAYBOOKS / "workday.md").exists()
    assert sites.migrate()["notes"] == 0 and len(sites.about("generic:jobs.acme.example")["notes"]) == 3       # run again: nothing is doubled


def test_the_page_about_sites_gets_each_site_and_can_clear_one(app_env):
    from fastapi.testclient import TestClient

    from autoapply.api.main import app

    key = "generic:careers.acme.example"
    _known(key)
    sites.note("system:workday", "The date boxes take typing.")
    c = TestClient(app)
    listed = {r["key"]: r for r in c.get("/api/sites").json()}
    assert listed[key]["notes"] == 2 and listed[key]["explored"] and not listed["system:workday"]["explored"]
    assert len(c.get(f"/api/sites/{key}").json()["notes"]) == 2
    assert c.post(f"/api/sites/{key}/forget").json() == {"notes": 2} and c.get(f"/api/sites/{key}").json()["notes"] == []
