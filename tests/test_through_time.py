"""How many applications were sent, along the stretch of time the page is set to; what a model costs; how hard it thinks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from autoapply import db


def test_a_single_day_is_seen_by_the_hour_and_nothing_else_is(app_env):
    from autoapply import analytics as an

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = datetime.now().strftime("%Y-%m-%d")
    sent = [(now - timedelta(minutes=5), True), (now - timedelta(minutes=10), False)]
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
