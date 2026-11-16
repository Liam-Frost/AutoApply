"""Where a run's time goes, what stands out in it, and what the program learns from it and keeps."""

from __future__ import annotations

import json
import time

import pytest

from autoapply import db, improve, learned, timing
from autoapply.models import Run

RECIPE = json.dumps({"controls": [{"when": {"label": "^Code$"}, "do": "leave_if_shown"}]})
PLUGIN = '''import re

def set_value(page, q, value, w):
    if q.label != "Nickname":
        return False
    page.locator("#nick").fill(str(value).upper())
    return True
'''


@pytest.fixture
def store(app_env, monkeypatch):
    from autoapply import fixtures

    db.init_db()
    monkeypatch.setattr(fixtures, "run_all", lambda ats=None: {"fixtures": 2, "failed": 0, "results": [{"fixture": "a", "ok": True}, {"fixture": "b", "ok": True}]})
    return monkeypatch


# --- timing ---


def test_a_run_records_what_its_time_was_spent_on_and_never_counts_the_applicant():
    assert timing.end() == [] and not timing.active()
    timing.mark("driver", "nothing", 5.0)                # no run in progress: nothing happens
    timing.begin()
    with timing.span("driver", "field", label="First name"):
        time.sleep(0.02)
    timing.mark("ai", "repair", 1500.0, ok=True)
    timing.mark("human", "window", 60000.0)
    with pytest.raises(ValueError):
        with timing.span("tool", "select"):
            raise ValueError("no")
    spans = timing.end()
    assert [(s["k"], s["n"]) for s in spans if s["k"] != "human"] and all(s["t"] >= 0 for s in spans)
    by = timing.by_name(spans)
    assert by[("tool", "select")]["failed"] == 1 and by[("driver", "field")]["n"] == 1
    assert timing.totals(spans)["human"] == 60000 and 1500 <= timing.working_ms(spans) < 3000
    assert next(s for s in spans if s["n"] == "field")["label"] == "First name"


def test_a_run_that_loops_cannot_fill_the_record():
    timing.begin()
    for _ in range(timing.LIMIT + 50):
        timing.mark("tool", "click", 1.0)
    spans = timing.end()
    assert len(spans) == timing.LIMIT + 1 and spans[-1]["count"] == 50


# --- what stands out ---


def run(spans, *, site="site-jobs.example.com", ats="generic", ok=1, steps=None, learned_ids=None):
    with db.session() as s:
        r = Run(kind="execute", ref="application:1", ats=ats, ok=ok, steps=steps or [], spans=spans, site=site, learned=learned_ids or [])
        s.add(r)
        s.flush()
        return r.id


def usual_run():
    return [{"k": "site", "n": "load", "t": 0, "ms": 2000}, {"k": "driver", "n": "field", "t": 2000, "ms": 3000}, {"k": "ai", "n": "repair", "t": 5000, "ms": 20000}]


def test_only_what_is_far_from_usual_or_done_over_and_over_is_a_finding(store):
    for _ in range(4):
        run(usual_run())
    assert improve.review(run([{"k": "site", "n": "load", "t": 0, "ms": 5000}, {"k": "driver", "n": "field", "t": 0, "ms": 4000}, {"k": "ai", "n": "repair", "t": 0, "ms": 90000}]))["findings"] == []
    slow = improve.review(run([{"k": "site", "n": "load", "t": 0, "ms": 2000}, {"k": "driver", "n": "field", "t": 0, "ms": 40000},
                               {"k": "driver", "n": "field", "t": 0, "ms": 100, "ok": False, "label": "Code"},
                               *[{"k": "tool", "n": "select", "t": 0, "ms": 900, "ok": False} for _ in range(3)], {"k": "human", "n": "window", "t": 0, "ms": 900000}],
                              steps=[{"op": "repair", "cause": "the Code list shows only +1"}, {"op": "repair", "cause": "again"}]))
    kinds = {f["what"] for f in slow["findings"]}
    assert kinds == {"slow", "tool_failed_repeatedly", "fields_not_filled_by_the_driver", "taken_over_repeatedly"}
    assert slow["totals"]["human"] == 900000 and slow["working_ms"] < 60000          # waiting for the applicant is not the run's time
    assert slow["usual"] == {"runs": 5, "median_ms": 25000}
    first = improve.review(run(usual_run(), site="site-new.example.org", ats="other"))        # nothing to compare with: nothing is called slow
    assert first["findings"] == [] and first["usual"]["runs"] == 0


# --- the gate ---


def test_what_may_not_be_learned(store):
    for bad in ({"controls": [{"when": {"label": "Code"}, "do": "format_disk"}]}, {"controls": [{"when": {}, "do": "native"}]}, {"controls": [{"when": {"label": "("}, "do": "native"}]}, {}):
        with pytest.raises(learned.Refused):
            learned.check_recipe(bad)
    for bad in ("import os\ndef set_value(page, q, value, w): return False", "from subprocess import run\ndef set_value(p, q, v, w): pass", "def set_value(page, q, value, w):\n    open('x')",
                "def set_value(page, q, value, w):\n    return page.__class__", "def helper(): pass", "def set_value(:"):
        with pytest.raises(learned.Refused):
            learned.check_code(bad)
    learned.check_code(PLUGIN)
    rev = learned.add("plugin", "generic", "bad", "why", "import socket\ndef set_value(page, q, value, w): return False")
    assert rev["status"] == "parked" and "socket" in rev["why_status"] and learned.in_force() == []


def test_a_revision_that_breaks_the_reading_of_saved_pages_is_not_let_in(store):
    from autoapply import fixtures

    def replay(ats=None):
        broken = bool(learned.in_force())
        return {"fixtures": 1, "failed": int(broken), "results": [{"fixture": "meta_p1", "ok": not broken}]}

    store.setattr(fixtures, "run_all", replay)
    rev = learned.add("recipe", "site-jobs.example.com", "t", "w", RECIPE)
    assert rev["status"] == "parked" and "meta_p1" in rev["why_status"]


# --- in force, on trial ---


def test_what_was_learned_is_kept_in_the_data_folder_and_holds_up_or_is_taken_out(store):
    from autoapply import config

    rev = learned.add("recipe", "site-jobs.example.com", "Code 已显示就不再选", "区号列表只显示 +1", RECIPE, from_run=7, baseline={"runs": 5, "median_ms": 20000})
    assert rev["status"] == "trial" and (config.DATA / "learned" / rev["id"] / "recipe.json").exists()       # not in the program's folder: an upgrade leaves it
    learned.begin(["site-other.example.org", "workday"])
    assert learned.in_force() == []                                                    # another site: not in force
    learned.drop()
    for n in (1, 2):
        learned.begin(["site-jobs.example.com", "generic"])
        assert learned.in_force() == [rev["id"]]
        learned._tls.force["used"].add(rev["id"])
        changed = learned.end(ok=True, working_ms=15000, interventions=0, run_id=n)
    assert [c["status"] for c in changed] == ["active"] and learned.get(rev["id"])["status"] == "active"
    # a strike - its own rule failed in a run - takes it out at once, even when the run got through without it
    learned.begin(["site-jobs.example.com"])
    learned._strike(learned.get(rev["id"]), "leave_if_shown on 'Code': TimeoutError")
    changed = learned.end(ok=True, working_ms=15000, interventions=0, run_id=3)
    assert changed[0]["status"] == "reverted" and "TimeoutError" in changed[0]["why_status"]
    learned.begin(["site-jobs.example.com"])
    assert learned.in_force() == []
    assert [h["status"] for h in learned.get(rev["id"])["history"]] == ["trial", "active", "reverted"]


def test_runs_that_got_slower_or_kept_failing_with_it_take_it_out(store):
    slow = learned.add("recipe", "generic", "slow", "w", RECIPE, baseline={"runs": 5, "median_ms": 10000})
    fails = learned.add("recipe", "workday", "fails", "w", RECIPE)
    idle = learned.add("recipe", "greenhouse", "never used", "w", RECIPE)
    for n in (1, 2):
        for target, rev, ok, ms in (("generic", slow, True, 30000), ("workday", fails, False, 9000), ("greenhouse", idle, False, 9000)):
            learned.begin([target])
            if rev is not idle:
                learned._tls.force["used"].add(rev["id"])
            learned.end(ok=ok, working_ms=ms, interventions=0, run_id=n)
    assert learned.get(slow["id"])["status"] == "reverted" and "每次约 30 秒，之前约 10 秒" in learned.get(slow["id"])["why_status"]
    assert learned.get(fails["id"])["status"] == "reverted"
    assert learned.get(idle["id"])["status"] == "trial"            # runs it took no part in say nothing about it


def test_the_applicant_can_be_asked_first_and_has_the_last_word(store):
    from autoapply.models import Todo

    db.set_setting("learned.mode", "ask")
    rev = learned.add("plugin", "generic", "Nickname 大写", "why", PLUGIN)
    assert rev["status"] == "proposed"
    with db.session() as s:
        assert [(t.kind, t.ref) for t in s.query(Todo).filter_by(status="open")] == [("learned", f"learned:{rev['id']}")]
    learned.begin(["generic"])
    assert learned.in_force() == []                               # not in force until approved
    assert learned.decide(rev["id"], "approve")["status"] == "trial"
    with db.session() as s:
        assert s.query(Todo).filter_by(status="open").count() == 0
    assert learned.decide(rev["id"], "revert")["status"] == "reverted"
    assert learned.decide(rev["id"], "retry")["status"] == "trial"
    with pytest.raises(learned.Refused):
        learned.decide(rev["id"], "approve")


def test_after_an_upgrade_what_was_learned_goes_through_the_gate_again(store, monkeypatch):
    ok = learned.add("recipe", "generic", "still fine", "w", RECIPE)
    broken = learned.add("plugin", "workday", "now broken", "w", PLUGIN)
    monkeypatch.setattr(learned, "version", lambda: "9.9.9")
    monkeypatch.setattr(learned, "gate", lambda rev: (_ for _ in ()).throw(learned.Refused("no")) if rev["id"] == broken["id"] else {"fixtures": 1})
    assert learned.recheck_after_upgrade() == 1
    assert learned.get(ok["id"])["status"] == "trial" and learned.get(ok["id"])["version"] == "9.9.9"
    assert learned.get(broken["id"])["status"] == "parked" and "9.9.9" in learned.get(broken["id"])["why_status"]      # parked, not deleted
    assert learned.recheck_after_upgrade() == 0


# --- on a real page ---


FORM = """<label for="code">Code</label><button id="code" type="button">+1</button>
<label for="nick">Nickname</label><input id="nick"><label for="city">City</label><input id="city">"""


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_default_timeout(4000)
        pg.set_content(FORM)
        yield pg
        b.close()


def test_the_generic_driver_follows_what_was_learned_and_falls_back_when_it_fails(store, page):
    from autoapply.ats.base import Question
    from autoapply.ats.generic_driver import get_value, set_value

    code = Question(id="#code", label="Code", type="select", options=["+1 United States", "+1 Canada"], page=0)
    nick = Question(id="#nick", label="Nickname", type="text", page=0)
    city = Question(id="#city", label="City", type="text", page=0)
    with pytest.raises(Exception):                       # as it was: a button that opens no list cannot be "selected"
        set_value(page, code, "+1 Canada")
    recipe = learned.add("recipe", "site-jobs.example.com", "Code", "w", RECIPE)
    plugin = learned.add("plugin", "site-jobs.example.com", "Nickname", "w", PLUGIN)
    learned.begin(["site-jobs.example.com"])
    set_value(page, code, "+1 Canada")                   # learned: it already shows part of the entry - left alone
    set_value(page, nick, "liam")                        # learned: the plugin fills it its own way
    set_value(page, city, "Vancouver")                   # nothing learned for it: as always
    assert page.locator("#nick").input_value() == "LIAM" and get_value(page, city) == "Vancouver"
    assert learned._tls.force["used"] == {recipe["id"], plugin["id"]} and learned._tls.force["strikes"] == {}
    # the plugin's way stops working (the site changed): the ordinary way fills the field in the same run, and it has a strike
    page.evaluate("document.getElementById('nick').id = 'nickname'")
    nick2 = Question(id="#nickname", label="Nickname", type="text", page=0)
    set_value(page, nick2, "liam")
    assert page.locator("#nickname").input_value() == "liam"
    changed = learned.end(ok=True, working_ms=5000, interventions=0, run_id=1)
    assert [(c["title"], c["status"]) for c in changed] == [("Nickname", "reverted")]


# --- the agent writes it down ---


def test_a_run_that_stood_out_is_looked_at_and_what_the_agent_writes_goes_through_the_gate(store, tmp_path):
    from autoapply import llm, tasks
    from autoapply.models import Task

    for _ in range(4):
        run(usual_run())
    (tmp_path / "repair_page_1.json").write_text(json.dumps({"problem": {"message": "values differ", "mismatches": [{"label": "Code"}]},
                                                             "report": {"cause": "shows only +1", "suggestion": "leave it when it shows +1"}, "steps": []}), encoding="utf-8")
    with db.session() as s:
        r = Run(kind="execute", ref="application:1", ats="generic", ok=1, site="site-jobs.example.com", dir=str(tmp_path),
                steps=[{"op": "repair", "cause": "a"}, {"op": "repair", "cause": "b"}], spans=usual_run())
        s.add(r)
        s.flush()
        rid = r.id
    db.set_setting("learned.drivers_written", ["site-jobs.example.com"])      # (its driver has been asked for: see the next test)
    quiet = run(usual_run())
    improve.after_run(quiet, [])
    improve.after_run(rid, [])
    with db.session() as s:
        assert [(t.kind, t.payload) for t in s.query(Task).filter_by(status="queued")] == [("improve", {"run_id": rid})]      # only the run that stood out
    seen = {}

    def answer(prompt, schema, **kw):
        seen["prompt"] = prompt
        return {"revisions": [{"kind": "recipe", "scope": "site", "title": "Code 已显示就不再选", "why": "反复接手都是因为区号只显示 +1", "expected": "不再为 Code 接手", "recipe": RECIPE, "code": ""},
                              {"kind": "plugin", "scope": "system", "title": "坏的", "why": "x", "expected": "", "recipe": "", "code": "import os"}], "nothing_because": ""}

    store.setattr(llm, "json", answer)
    out = improve.propose(rid)
    assert "taken_over_repeatedly" in seen["prompt"] and "leave it when it shows +1" in seen["prompt"]
    assert [(r["status"], r["title"]) for r in out["revisions"]] == [("trial", "Code 已显示就不再选"), ("parked", "坏的")]
    kept = learned.revisions()
    assert kept[0]["target"] == "site-jobs.example.com" and kept[0]["from_run"] == rid and kept[0]["baseline"] == {"runs": 6, "median_ms": 25000}
    assert kept[1]["target"] == "generic"
    assert improve.propose(quiet) == {"skipped": "nothing stands out in this run"}
    db.set_setting("learned.enabled", False)
    with db.session() as s:
        s.query(Task).delete()
    improve.after_run(rid, [])
    with db.session() as s:
        assert s.query(Task).count() == 0                # switched off: nothing is looked at
    assert tasks is not None


def test_the_third_run_on_a_site_without_a_driver_has_one_written_from_all_three(store, tmp_path):
    """The design: the agent does a site it has no driver for by hand, and the third time it writes the driver."""
    from autoapply import knowledge, llm
    from autoapply.models import Task

    site = "site-careers.example.org"
    knowledge.add_site_note(site, "The phone code list shows only +1 once chosen.")
    ids = []
    for n in range(3):
        d = tmp_path / f"r{n}"
        d.mkdir()
        (d / "repair_page_1.json").write_text(json.dumps({"problem": {"message": "values differ", "mismatches": [{"label": "Code"}]},
                                                         "report": {"cause": f"take-over {n}: the list shows only +1", "suggestion": "leave it"}, "steps": []}), encoding="utf-8")
        with db.session() as s:
            r = Run(kind="execute", ref=f"application:{n}", ats="generic", ok=1, site=site, dir=str(d), steps=[{"op": "repair", "cause": "x"}],
                    spans=[*usual_run(), {"k": "driver", "n": "field", "t": 0, "ms": 100, "ok": False, "label": "Code"}])
            s.add(r)
            s.flush()
            ids.append(r.id)
        assert improve.driver_due(ids[-1]) is (n == 2)
    assert not improve.driver_due(run(usual_run(), site="workday", ats="workday"))       # a system with a driver of its own
    with db.session() as s:
        s.query(Task).delete()
    improve.after_run(ids[-1], [])
    with db.session() as s:
        assert [(t.kind, t.payload) for t in s.query(Task).filter_by(status="queued")] == [("improve", {"run_id": ids[-1], "driver": True})]
    seen = {}

    def answer(prompt, schema, *, system, **kw):
        seen.update(prompt=prompt, system=system)
        return {"revisions": [{"kind": "recipe", "scope": "system", "title": "区号已显示就不再选", "why": "三次运行都因为区号接手", "expected": "不再接手", "recipe": RECIPE, "code": ""}], "nothing_because": ""}

    store.setattr(llm, "json", answer)
    out = improve.propose(ids[-1], driver=True)
    assert "Write the site's driver" in seen["system"] and "shows only +1 once chosen" in seen["prompt"] and all(f"take-over {n}" in seen["prompt"] for n in range(3))
    assert out["driver_for"] == site and [r["status"] for r in out["revisions"]] == ["trial"]
    kept = learned.revisions()[-1]
    assert (kept["target"], kept["origin"]) == (site, "driver")           # a site's driver is the site's, whatever scope was said
    assert db.get_setting("learned.drivers_written") == [site]
    assert not improve.driver_due(run(usual_run(), site=site))            # once per site
    store.setattr(llm, "json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked a second time")))
    assert improve.propose(run(usual_run(), site=site), driver=True) == {"skipped": "nothing stands out in this run"}


def test_the_analysis_page_gets_the_time_by_system_and_what_was_learned(store):
    from fastapi.testclient import TestClient

    from autoapply.api.main import app

    for ms in (20000, 30000):
        run([{"k": "driver", "n": "field", "t": 0, "ms": ms}, {"k": "human", "n": "window", "t": 0, "ms": 500000}], ats="workday", site="workday")
    rid = run(usual_run(), learned_ids=[])
    rev = learned.add("recipe", "generic", "学到的", "为什么", RECIPE)
    c = TestClient(app)
    got = c.get("/api/analytics/timing").json()
    wd = next(s for s in got["systems"] if s["ats"] == "workday")
    assert wd["runs"] == 2 and wd["median_ms"] == 25000 and wd["trend"][0]["runs"] == 2 and wd["trend"][0]["driver"] == 25000
    assert got["count"] == 3 and got["mode"] == "auto" and got["learned"][0]["title"] == "学到的" and got["learned"][0]["status"] == "trial"
    one = c.get(f"/api/analytics/timing/runs/{rid}").json()
    assert [s["n"] for s in one["spans"]] == ["load", "field", "repair"] and one["review"]["working_ms"] == 25000
    assert c.get("/api/analytics/timing/runs/999999").status_code == 404
    assert c.get(f"/api/learned/{rev['id']}").json()["content"] == RECIPE
    assert c.post(f"/api/learned/{rev['id']}/revert").json()["status"] == "reverted"
    assert c.post(f"/api/learned/{rev['id']}/approve").status_code == 409
    assert c.post("/api/learned/nope/revert").status_code == 404


@pytest.mark.parametrize("module, cls", [("greenhouse", "GreenhouseDriver"), ("ashby", "AshbyDriver"), ("workday", "WorkdayDriver")])
def test_the_coded_drivers_record_each_field_they_fill_too(module, cls, monkeypatch):
    """Per-field time was recorded by the generic driver only: a run on Greenhouse, Ashby or Workday showed its steps
    and nothing about which field took the time."""
    import importlib
    from types import SimpleNamespace

    from autoapply.ats.base import DriverError, FormSchema, Question

    driver = getattr(importlib.import_module(f"autoapply.ats.{module}"), cls)()
    qs = [Question(id="a", label="First name", type="text", page=0), Question(id="b", label="Phone code", type="select", page=0)]

    def fill_one(page, q, val):
        if q.id == "b":
            raise DriverError("no such entry")

    monkeypatch.setattr(driver, "_fill_one", fill_one)
    monkeypatch.setattr(driver, "_rows_as_they_are", lambda *a, **k: {}, raising=False)
    page = SimpleNamespace(locator=lambda *a, **k: SimpleNamespace(count=lambda: 0), keyboard=SimpleNamespace(press=lambda *a, **k: None), wait_for_timeout=lambda *a, **k: None)
    timing.begin()
    try:
        driver.fill_page(page, FormSchema(ats=module, tenant="t", url="https://x.example", questions=qs, pages=["One"]), 0, {"a": "Alex", "b": "+1"})
    except Exception:  # noqa: BLE001 - how each driver reports the field that failed is its own business
        pass
    fields = [(s["label"], s.get("ok", True)) for s in timing.end() if (s["k"], s["n"]) == ("driver", "field")]
    assert fields == [("First name", True), ("Phone code", False)]


# --- what the review of this change found ---


def test_a_steps_time_is_what_is_left_once_what_happened_inside_it_is_taken_out():
    """A step was recorded as the whole stretch since the step before, on top of the fields, requests and loads
    recorded inside it: a 1.5 s step with a 1 s field in it counted as 2.5 s of the driver's time."""
    timing.begin()
    began = time.monotonic()
    timing.mark("driver", "field", 1000.0, started=began + 0.1, label="First name")
    timing.mark("ai", "repair", 2000.0, started=began + 1.2)
    whole = 4000.0
    timing.mark("driver", "step:fill_page", max(0.0, whole - timing.inside(began)), started=began)
    spans = timing.end()
    assert next(s for s in spans if s["n"] == "step:fill_page")["ms"] == 1000
    assert timing.totals(spans) == {"site": 0, "driver": 2000, "ai": 2000, "tool": 0, "human": 0} and timing.working_ms(spans) == 4000


def test_a_field_a_revision_filled_that_reads_back_differently_is_its_failure(store, page):
    """A plugin that says it filled the field and did not was taken at its word; the take-over repaired the field, the
    run counted as a good trial, and two such runs made the broken plugin permanent."""
    from autoapply.ats.base import Question
    from autoapply.ats.generic_driver import set_value

    liar = learned.add("plugin", "site-jobs.example.com", "Says it did", "w", "def set_value(page, q, value, w):\n    return q.label == 'City'\n")
    learned.begin(["site-jobs.example.com"])
    set_value(page, Question(id="#city", label="City", type="text", page=0), "Vancouver")
    assert page.locator("#city").input_value() == "" and learned._tls.force["filled"] == {"#city": liar["id"]}
    learned.read_back_differs(["#other"])                 # a field it did not fill is not held against it
    assert learned._tls.force["strikes"] == {}
    learned.read_back_differs(["#city"])
    changed = learned.end(ok=True, working_ms=5000, interventions=1, run_id=1)
    assert [(c["title"], c["status"]) for c in changed] == [("Says it did", "reverted")] and "read back differently" in changed[0]["why_status"]


def test_the_waits_that_were_learned_are_kept_after_a_load_a_step_and_every_field(store, page):
    """A recipe of waits alone went on trial and did nothing: the only wait that was ever kept was the one after a field
    that a learned rule had filled."""
    from autoapply.ats.base import Question
    from autoapply.ats.generic_driver import set_value

    rev = learned.add("recipe", "site-jobs.example.com", "Waits", "w", json.dumps({"waits": [{"after": "load", "ms": 11}, {"after": "field", "ms": 12}, {"after": "step", "ms": 13}]}))
    learned.begin(["site-jobs.example.com"])
    waited = []
    real = page.wait_for_timeout
    page.wait_for_timeout = lambda ms: waited.append(ms)
    try:
        learned.waits_on(page)
        page.goto("about:blank")
        assert waited == [11]
        page.set_content("<input id=city>")
        set_value(page, Question(id="#city", label="City", type="text", page=0), "Vancouver")       # filled the ordinary way
        assert 12 in waited and page.locator("#city").input_value() == "Vancouver"
        learned.wait_after(page, "step")
        assert waited[-1] == 13 and learned._tls.force["used"] == {rev["id"]}
    finally:
        page.wait_for_timeout = real
        learned.drop()


def test_what_was_learned_is_in_a_backup(store):
    import zipfile

    from autoapply import backup, siteplan

    rev = learned.add("recipe", "site-jobs.example.com", "Code", "w", RECIPE)
    siteplan._save("site-jobs.example.com", {"steps": {"One": []}})
    out = backup.export()
    with zipfile.ZipFile(out["path"]) as z:
        names = set(z.namelist())
    assert {"data/learned/index.json", f"data/learned/{rev['id']}/recipe.json", "data/sites/site-jobs.example.com.json"} <= names


def test_something_proposed_before_an_upgrade_goes_through_the_gate_again_when_it_is_approved(store, monkeypatch):
    db.set_setting("learned.mode", "ask")
    old = learned.add("recipe", "site-jobs.example.com", "Old", "w", RECIPE)
    gone = learned.add("recipe", "site-jobs.example.com", "Gone", "w", RECIPE)
    assert old["status"] == gone["status"] == "proposed"
    monkeypatch.setattr(learned, "version", lambda: "9.9.9")
    calls = []

    def gate(rev):
        calls.append(rev["title"])
        if rev["title"] == "Gone":
            raise learned.Refused("the saved pages are read differently")
        return {"fixtures": 2}

    monkeypatch.setattr(learned, "gate", gate)
    assert learned.decide(old["id"], "approve")["status"] == "trial" and learned.get(old["id"])["version"] == "9.9.9"
    parked = learned.decide(gone["id"], "approve")
    assert parked["status"] == "parked" and "9.9.9" in parked["why_status"] and calls == ["Old", "Gone"]


def test_every_run_of_the_window_can_be_opened(store):
    from autoapply import analytics as an

    for _ in range(45):
        run(usual_run())
    got = an.timing_overview(an.window(0, "", ""))
    assert got["count"] == 45 and len(got["runs"]) == 45
