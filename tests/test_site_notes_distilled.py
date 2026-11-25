"""A site's notes, once they are many, are written into one account of how the site is worked; what holds for its
whole recruiting system goes to the system's notes; the lines that went in are kept (2026-11-25, the owner: the notes
should get better with every application, not lose their oldest line at twelve)."""
from __future__ import annotations


def test_twelve_notes_are_distilled_the_lines_kept_and_what_holds_for_the_system_goes_up(app_env, monkeypatch):
    from fastapi.testclient import TestClient

    from autoapply import db, llm, sites, tasks
    from autoapply.api.main import app
    from autoapply.models import Task

    key = "workday:acme.wd5"
    for i in range(11):
        sites.note(key, f"line {i}: the Next button is at the bottom of step {i}")
    with db.session() as s:
        assert s.query(Task).filter_by(kind="notes").count() == 0                     # (eleven: not yet)
    sites.note(key, "line 11: the résumé parser swaps the dates; the applicant is a.b@example.com")
    with db.session() as s:
        t = s.query(Task).filter_by(kind="notes", ref=key).one()                   # twelve: distilled in the background
    # until it is done, nothing is dropped (up to twice as many)
    sites.note(key, "line 12: noted while it waited")
    assert len(sites.about(key)["notes"]) == 13

    seen = {}

    def model(prompt, schema, *, system=None, **kw):
        seen["prompt"], seen["system"] = prompt, system
        return {"how": "## Signing in\nSign in with the applicant's address (a.b@example.com).\n## The form\nNext is at the bottom of each step.",
                "system": ["Workday: the résumé parser swaps start and end dates - check them on My Experience."]}

    monkeypatch.setattr(llm, "json", model)
    out = tasks._handlers["notes"](t)
    assert out == {"distilled": 13, "system": 1}
    assert "<recruiting_system>workday</recruiting_system>" in seen["prompt"] and "line 0" in seen["prompt"] and "nothing about the applicant" in seen["system"]
    got = sites.about(key)
    assert got["notes"] == [] and got["digest"]["text"].startswith("## Signing in")
    assert "a.b@example.com" not in got["digest"]["text"] and "(the applicant's address)" in got["digest"]["text"]   # (an address never kept)
    assert len(got["digest"]["from"]) == 13 and got["digest"]["from"][0]["text"].startswith("line 12")             # the lines that went in
    # what holds for every Workday site: in the system's notes, which every Workday site's agent reads
    assert "swaps start and end dates" in sites.notes("system:workday")
    # the agent reads the account first, then what was noted since
    sites.note(key, "line 13: after the account")
    said = sites.notes(key)
    assert said.startswith("How this site is worked (distilled on ") and said.index("## The form") < said.index("Noted since:") < said.index("line 13")
    # a later round: the account written before goes in with the new lines; the lines from before stay kept
    for i in range(14, 25):
        sites.note(key, f"line {i}")
    monkeypatch.setattr(llm, "json", lambda prompt, schema, **kw: seen.update(again=prompt) or {"how": "## Better\nall of it", "system": []})
    sites.distill(key)
    assert "Next is at the bottom of each step" in seen["again"]
    got = sites.about(key)
    assert got["digest"]["text"] == "## Better\nall of it" and len(got["digest"]["from"]) == 25 and got["notes"] == []

    # the applicant's own wording takes the account's place; the agent reads it
    c = TestClient(app)
    r = c.put(f"/api/sites/{key}/digest", json={"text": "## Mine\nMy way of doing it."}).json()
    assert r["digest"]["text"] == "## Mine\nMy way of doing it." and r["digest"]["by"] == "applicant" and len(r["digest"]["from"]) == 25
    assert "My way of doing it." in sites.notes(key)
    # the site reached under another address: one account goes with it, the lines with it
    sites.note("workday:acme.wd1", "a line on the old address")
    assert sites.move(key, "workday:acme.wd1")
    moved = sites.about("workday:acme.wd1")
    assert moved["digest"]["text"] == "## Mine\nMy way of doing it." and [n["text"] for n in moved["notes"]] == ["a line on the old address"]
    # an employer's own site has no recruiting system to send anything up to
    assert sites.system_of("generic:careers.acme.example") == "" and sites.system_of(key) == "workday"


def test_sites_with_many_notes_from_before_are_distilled_after_the_update(app_env, monkeypatch):
    from autoapply import db, sites
    from autoapply.models import Site, Task

    with db.session() as s:      # (written by a version that kept twelve and dropped the rest)
        s.add(Site(key="generic:careers.acme.example", notes=[{"at": "2026-11-20", "text": f"old {i}"} for i in range(12)]))
        s.add(Site(key="generic:jobs.other.example", notes=[{"at": "2026-11-20", "text": "one"}]))
    assert sites.queue_due() == ["generic:careers.acme.example"]      # (what the start does)
    with db.session() as s:
        assert [t.ref for t in s.query(Task).filter_by(kind="notes")] == ["generic:careers.acme.example"]
    assert sites.distill_due("generic:careers.acme.example") and not sites.distill_due("generic:jobs.other.example")
