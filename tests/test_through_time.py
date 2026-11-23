"""How many applications were sent, along the stretch of time the page is set to; what a model costs; how hard it thinks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from autoapply import db


def test_a_single_day_is_seen_by_the_hour_and_nothing_else_is(app_env):
    from autoapply import analytics as an

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = datetime.now().strftime("%Y-%m-%d")
    # two sent today - never before midnight: "five and ten minutes ago" was yesterday in the first minutes of a day
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
    sent = [(max(midnight, now - timedelta(minutes=5)), True), (max(midnight, now - timedelta(minutes=10)), False)]
    day = an._through_time(an.window(0, today, today), sent, [now], "")
    assert day["bucket"] == "hour" and sum(r["n"] for r in day["rows"]) == 2 and sum(r["replies"] for r in day["rows"]) == 1
    assert len(day["rows"]) == datetime.now().hour + 1 and day["rows"][0]["label"] == "00:00"      # every hour so far, the empty ones too
    assert an._through_time(an.window(0, today, today), sent, [], "week")["bucket"] == "hour"      # one day is by the hour whatever is asked
    for days, bucket, want in ((7, "", "day"), (30, "", "day"), (90, "", "week"), (400, "", "month"), (30, "week", "week"), (30, "month", "month")):
        got = an._through_time(an.window(days, "", ""), sent, [], bucket)
        assert got["bucket"] == want and sum(r["n"] for r in got["rows"]) == 2
    week = an._through_time(an.window(7, "", ""), sent, [], "")
    assert len(week["rows"]) == 8 and [r["n"] for r in week["rows"]][:-1] == [0] * 7             # the days nothing was sent are there


def test_the_models_of_the_day_have_a_price_and_a_service_is_told_how_hard_to_think(app_env):
    import httpx

    from autoapply import llm_openai, metering

    sol = metering.price_for("chatgpt", "gpt-6.2-sol")
    assert (float(sol["input"]), float(sol["output"]), float(sol["cache_read"])) == (2.0, 10.0, 0.1) and float(sol["over"]["input"]) == 4.0
    assert float(metering.price_for("openai", "gpt-6.2-astra")["output"]) == 40.0 and metering.price_for("openai", "gpt-6.2") is None

    seen = []

    def answer(request):
        import json

        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "x", "model": "gpt-6.2-sol", "choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    c = llm_openai.Client("https://api.example/v1", "k", transport=httpx.MockTransport(answer))
    c.text("hi", model="gpt-6.2-sol")
    c.effort = "high"
    c.text("hi", model="gpt-6.2-sol")
    assert "reasoning_effort" not in seen[0] and seen[1]["reasoning_effort"] == "high"
    assert "max_completion_tokens" in seen[0] and "max_tokens" not in seen[0]      # (the name the newer models take the limit under)


def test_what_the_notice_after_authorizing_says_is_what_was_granted(app_env):
    import json

    from autoapply import mail, messages, secrets

    card = messages.gmail_authorized
    secrets.put(secrets.GMAIL_TOKEN, json.dumps({"refresh_token": "r", "client_id": "c", "client_secret": "x", "scopes": [mail.READ]}))
    assert "只能读信" in card().heading
    secrets.put(secrets.GMAIL_TOKEN, json.dumps({"refresh_token": "r", "client_id": "c", "client_secret": "x", "scopes": mail.SCOPES}))
    assert "发信" in card().heading and "只读" not in card().heading
    assert db.get_setting("mail.send") == "review"


def test_how_applications_get_done_is_read_from_their_journals(app_env):
    """Runs per application, how runs ended, the share of steps spent going over an application again, and steps and
    time to done by recruiting system - from what the runs wrote down."""
    import json

    from autoapply import analytics as an
    from autoapply.agent import work
    from autoapply.models import Application, Job

    with db.session() as s:
        j = Job(source="manual", source_id="w1", company="Acme", title="Intern", apply_url="https://acme.wd5.myworkdayjobs.com/x/job/1", status="queued", online=1)
        s.add(j)
        s.flush()
        a = Application(job_id=j.id, status="submitted")
        s.add(a)
        s.flush()
        app_id = a.id
    now = datetime.now().replace(microsecond=0)
    t = lambda m: (now - timedelta(minutes=60 - m)).isoformat()  # noqa: E731
    lines = [{"at": t(0), "kind": "run", "mode": "auto"}, {"at": t(1), "kind": "ended", "why": "LLMUnavailable: used up", "steps": 0},       # a run that never began
             {"at": t(5), "kind": "run", "mode": "auto"}, *({"at": t(6), "kind": "tool", "tool": "click"} for _ in range(30)),
             {"at": t(15), "kind": "report", "outcome": "needs_you"},
             {"at": t(20), "kind": "run", "mode": "auto"}, *({"at": t(21), "kind": "tool", "tool": "click"} for _ in range(20)),
             {"at": t(30), "kind": "report", "outcome": "ready"},
             {"at": t(40), "kind": "run", "mode": "send"}, *({"at": t(41), "kind": "tool", "tool": "click"} for _ in range(10))]      # cut off after sending, no report
    folder = work.folder_of(app_id)
    folder.mkdir(parents=True)
    (folder / "journal.jsonl").write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    got = an.agent_runs(an.window(7, "", ""))
    assert got["applications"] == 1 and got["runs"] == 3 and got["idle_runs"] == 1
    assert got["again"] == {"steps": 30, "of": 60, "rate": 0.5}                         # the second and third runs: 20 + 10 of 60
    assert {e["key"]: e["n"] for e in got["ends"]} == {"ready": 1, "needs_you": 1, "cut_off": 1, "model": 1}
    assert got["by_system"] == [{"key": "workday", "label": "Workday", "apps": 1, "done": 1, "median_steps": 50, "median_seconds": 1200.0}]
    assert an.agent_runs(an.window(0, "2020-01-01", "2020-01-02"))["applications"] == 0   # nothing began then
