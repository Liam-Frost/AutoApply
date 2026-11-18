"""Notification cards: markup is escaped, both renderings carry the same facts, no template crashes."""


def test_card_renders_html_and_plain():
    from autoapply import messages as m

    c = m.failed("A&B <Labs> · Engineer", error="value <script> differs")
    h, p = c.html("http://127.0.0.1:8000"), c.plain("http://127.0.0.1:8000/")
    assert "<b>A&amp;B &lt;Labs&gt;</b> · Engineer" in h and "&lt;script&gt;" in h and "<script>" not in h
    assert '<a href="http://127.0.0.1:8000/todos">' in h
    assert "A&B <Labs> · Engineer" in p and "http://127.0.0.1:8000/todos" in p and "<b>" not in p


def test_every_template_renders():
    from autoapply import messages as m

    t = "Acme · Engineer"
    cards = [
        m.discover_started(3),
        m.discover_done({"seen": 5, "new": 0, "back": 0, "offline": 0}, {}, {}),
        m.discover_done({"seen": 5, "new": 2, "back": 1, "offline": 1}, {"a": 2}, {"b": "boom"}),
        m.submitted(t, evidence="Thanks", auto=True), m.submitted(t, evidence="", note="already applied"),
        m.failed(t, error="x" * 900), m.session_saved("k", credentials=True), m.gmail_authorized(),
        m.high_scores([{"score": 8.5, "company": "A", "title": "T", "deadline": ""}] * 14),
        *[m.mail_update(k, t, "s") for k in [*m.MAIL, "other"]],
        *[m.todo(k, t, "body", payload={"draft_id": 3}) for k in [*m.TODO, "unknown"]],
        m.draft_ready(t, 3, answers=4, files=["R.pdf"]), m.test(),
    ]
    for c in cards:
        assert c.html("http://x") and c.plain("http://x") and len(c.html("http://x")) < 4000
    d = m.draft_ready(t, 3, answers=4, files=["R.pdf"]).plain("http://x")
    assert "/drafts/3" in d and "4 项" in d and "R.pdf" in d


def test_send_records_plain_text_and_todo_push(app_env, monkeypatch):
    from autoapply import db, messages, notify
    from autoapply.models import Notification

    got = []
    ch = type("C", (), {"send_card": lambda self, card, base: got.append(card.html(base))})()
    monkeypatch.setattr(notify, "_channels", lambda: [ch])
    notify.add_todo("takeover", "workday:acme", body="no session", ref="account:x")
    notify.add_todo("failed", "Acme · Eng", ref="application:1", push=False)
    notify.send("task_result", messages.failed("Acme · Eng", error="boom"), ref="application:1")
    assert len(got) == 2 and "需要你登录" in got[0] and "<b>Acme</b>" in got[1]
    with db.session() as s:
        rows = [n.text for n in s.query(Notification).order_by(Notification.id)]
    assert len(rows) == 2 and "<b>" not in rows[1] and "/todos" in rows[1]
