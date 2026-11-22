"""Made-up, adversarial records for the page tests (test_ui_pages.py): what makes a page break - the shortest and the
longest names, Chinese ones, a posting without a title, a calendar item with an absurd title, site accounts in every
state with a long technical error, sessions saved, run out and missing.

`build()` runs inside the throw-away copy that tests/ui_server.py starts (after the demo's own seed, in the same
process, with AUTOAPPLY_DATA pointing at its temp folder) and writes through the program's own models and functions.
Nothing here is real: every name, address and password is invented, and the passwords go to the copy's own secret
store (a file in its temp folder - ui_server sets AUTOAPPLY_SECRETS=file), never to the computer's keyring.

The constants are what the tests look for; this module imports nothing of the program until `build()` is called.
"""

from __future__ import annotations

# ── what the tests look for ──────────────────────────────────────────────────────────────────────────────────────────
TAG = "Zq"      # every company made here starts with it: the tests find their own rows by it
SHORT = "Zq"
LONG_COMPANY = ("Zq Very Long Enterprise Solutions and Consolidated Holdings of North America Incorporated, University Recruiting "
                "Division for Co-operative Education, Internships and New Graduate Programs (Western Region)")[:200]
LONG_TITLE = ("Zq Senior Associate Data and Business Intelligence Analyst, Commercial Operations, Pricing Strategy, Revenue "
              "Management and Customer Insights - Twelve to Sixteen Month Co-op Term Starting January (Hybrid)")[:200]
CJK_COMPANY = "Zq深圳市腾飞数据科技股份有限公司华南区校园招聘中心"
CJK_TITLE = "数据分析师（应届毕业生，商业智能与运营方向）"
NAMES = [(SHORT, "BA"), (LONG_COMPANY, LONG_TITLE), (CJK_COMPANY, CJK_TITLE), ("Zq Untitled Ltd", "")]

ABSURD_EVENT = ("Zq-event " + "Second-round panel interview with the hiring manager, two senior analysts and a director from the regional "
                "operations team, followed by a case study presentation, a tour of the office and an informal coffee chat ") [:200]
PASSWORD = "Made-up-Pw-7731!q"      # the password of every account here that has one (made up)
LONG_ERROR = (
    "TimeoutError: Locator.click: Timeout 30000ms exceeded.\nCall log:\n  - waiting for get_by_role(\"button\", name=\"Create Account\")\n"
    "    - locator resolved to <button type=\"submit\" disabled data-automation-id=\"createAccountSubmitButton\">Create Account</button>\n"
    "    58 x waiting for element to be visible, enabled and stable\n       - element is not enabled\n"
    "at https://zq-umbrella.wd5.myworkdayjobs.example/en-US/External_Careers/login?redirect=%2Fen-US%2FExternal_Careers%2Fjob%2FR-0018472%2Fapply\n"
    "step 14 of 400; the page said: \"Verify that you are not a robot before creating an account.\"")
ERROR_MARK = "createAccountSubmitButton"      # a piece of LONG_ERROR that must never stand in a row
LONG_HOST = "careers.zq-very-long-enterprise-solutions-north-america-university-recruiting.example-talent-acquisition-platform.example"
LONG_EMAIL = "alexander.zq.university-recruiting.co-op-applications-2027@students.northfield-university.example"

# key -> (host, e-mail, password?, status, created_by, error, session): one of every state the accounts page tells apart
# (auth.readiness: ready, manual, verify, register_failed, signin_failed, locked, never)
ACCOUNTS = {
    "workday:zq-ready.wd3": ("zq-ready.wd3.myworkdayjobs.example", "alex@example.com", True, "ok", "takeover", None, "good"),
    "workday:zq-nopw.wd1": ("zq-nopw.wd1.myworkdayjobs.example", "alex@example.com", False, "ok", "takeover", None, "expired"),
    "icims:zq-verify": ("zq-verify.icims.example", "alex@example.com", True, "pending", "agent", None, None),
    "workday:zq-umbrella.wd5": ("zq-umbrella.wd5.myworkdayjobs.example", "alex@example.com", True, "pending", "agent", LONG_ERROR, None),
    "oracle:zq-manual": ("zq-manual.fa.oraclecloud.example", "alex@example.com", True, "needs_human", "takeover", "The site asks for a code sent to your phone at every sign-in.", "session-only"),
    "workday:zq-signin.wd2": ("zq-signin.wd2.myworkdayjobs.example", "alex@example.com", False, "unknown", "manual", "HTTP 403 at /login: the e-mail address or the password is wrong.", None),
    "workday:zq-locked.wd12": ("zq-locked.wd12.myworkdayjobs.example", "alex@example.com", True, "locked", "manual", "Account locked after too many sign-in attempts.", "good"),
    "eightfold:zq-long": (LONG_HOST, LONG_EMAIL, True, "unknown", "chrome_csv", None, None),
    "workday:zq-never.wd1": ("", "", False, "unknown", "manual", None, None),
}
REVEAL = "workday:zq-ready.wd3"      # the row the reveal test opens

CUSTOM_PROVIDER = "Zq Northfield University Single Sign-On (CWL) for Students, Staff and Alumni"


def build() -> None:
    """Fill the current data folder (already seeded by scripts/demo.py) with the records above."""
    import os
    import time
    from datetime import datetime, timedelta

    from autoapply import agenda, auth, browser, config, db, secrets
    from autoapply.models import Account, Application, Contact, Job, Outgoing, Todo

    data = str(config.DATA).replace("\\", "/")
    assert "autoapply-ui-" in data, ("ui_data.build() writes made-up records into the test copy's temp folder only", data)
    assert secrets.backend() == "file", "the made-up passwords go into the copy's own file store, not into the computer's keyring"
    now = datetime.utcnow()
    local = datetime.now()

    # ── postings and applications ────────────────────────────────────────────────────────────────────────────────────
    stages = ["needs_input", "draft_ready", "needs_human", "ready_to_submit", "submit_unknown", "drifted", "failed", "recon", "revising", "approved", "executing",
              "submitted", "confirmed", "assessment", "interview", "offer", "rejected", "withdrawn", "returned"]
    sent = {"submitted", "confirmed", "assessment", "interview", "offer", "rejected"}
    apps: dict[str, int] = {}
    with db.session() as s:
        n = 0
        # postings without an application, in every group of the postings page: to do, skipped, taken down
        for status, online in (("scored", 1), ("scored", 1), ("skipped", 1), ("scored", 0)):
            for company, title in NAMES:
                n += 1
                s.add(Job(source="manual", source_id=f"zq-post-{n}", company=company, title=title, location="Vancouver, BC, Canada" if n % 2 else "深圳 · 南山区",
                          score=9.5 - n * 0.3, status=status, online=online, apply_url=f"https://careers.zq{n}.example/jobs/{n}", channel="employer site",
                          deadline=(now + timedelta(days=n - 3)).strftime("%Y-%m-%d 23:59"), posted=(now - timedelta(days=n)).strftime("%Y-%m-%d"), jd_text="x" * 300,
                          first_seen=now - timedelta(days=n), salary="CAD 62,000-70,000" if n % 3 == 0 else ""))
        # an application in every stage, each with another of the hard names
        for k, st in enumerate(stages):
            company, title = NAMES[k % len(NAMES)]
            j = Job(source="manual", source_id=f"zq-app-{k}", company=company, title=title, location="Toronto, ON, Canada", score=8.0, status="scored",
                    apply_url=f"https://careers.zqa{k}.example/jobs/{k}", channel="employer site", ats="workday" if k % 2 else "greenhouse",
                    deadline=(now + timedelta(days=k + 1)).strftime("%Y-%m-%d 23:59"), jd_text="x" * 300, first_seen=now - timedelta(days=k + 2))
            s.add(j)
            s.flush()
            a = Application(job_id=j.id, status=st, channel="employer site", created_at=now - timedelta(days=k + 1),
                            last_event=("Zq latest: " + LONG_TITLE) if k % 3 == 0 else "")
            if st in sent:
                a.submitted_at = now - timedelta(days=k)
            s.add(a)
            s.flush()
            apps[st] = a.id

    # the next event of an application in progress: one with an absurd title, one ordinary
    agenda.add_own(ABSURD_EVENT, (local + timedelta(days=2)).replace(hour=14, minute=30, second=0, microsecond=0), all_day=False, application_id=apps["interview"])
    agenda.add_own("Zq offer call", (local + timedelta(days=3)).replace(hour=0, minute=0, second=0, microsecond=0), all_day=True, application_id=apps["offer"])
    agenda.add_own("Zq assessment", (local + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0), all_day=False, application_id=apps["assessment"])

    # ── to-dos: open and done, with and without a date ───────────────────────────────────────────────────────────────
    for title, days, done in (("Zq call back the recruiter", 1, False), ("Zq " + LONG_TITLE, 4, False), ("Zq 准备群面材料", -1, False), ("Zq sent the transcript", -2, True)):
        tid = agenda.add_own(title, (local + timedelta(days=days)).replace(hour=9, minute=0, second=0, microsecond=0), all_day=False)
        if done:
            with db.session() as s:
                t = s.get(Todo, tid)
                t.status, t.done_at = "done", now
    with db.session() as s:
        s.add(Todo(kind="submit", ref=f"application:{apps['submit_unknown']}", title=f"{LONG_COMPANY} · {LONG_TITLE}", body="Zq " + LONG_TITLE,
                   payload={"application_id": apps["submit_unknown"]}, due_at=local + timedelta(days=1)))
        s.add(Todo(kind="followup", ref="zq:followup", title="Zq follow up", body="", payload={}, status="done", done_at=now - timedelta(days=1)))

    # ── contacts ─────────────────────────────────────────────────────────────────────────────────────────────────────
        for name, company, role, follow in (("Zq Li", SHORT, "HR", (local + timedelta(days=3)).strftime("%Y-%m-%d")),
                                            ("Zq Maximiliana Alexandra Fitzgerald-Montgomery", LONG_COMPANY, LONG_TITLE, (local - timedelta(days=2)).strftime("%Y-%m-%d")),
                                            ("张伟", CJK_COMPANY, "高级招聘经理", ""), ("Zq", "", "", "")):
            s.add(Contact(name=name, company=company, role=role, relation="alumni" if company else "", how=LONG_EMAIL if company == LONG_COMPANY else "", follow_up=follow,
                          note="Zq " + LONG_TITLE if company == LONG_COMPANY else ""))

    # ── outgoing mail (written by hand here: no AI) ──────────────────────────────────────────────────────────────────
        for status, subject, error in (("draft", "Zq Application: " + LONG_TITLE, ""), ("sent", "Zq Re: 面试时间确认", ""), ("failed", "Zq Thank you", "SMTPAuthenticationError: (535, b'5.7.8 Username and Password not accepted.')")):
            s.add(Outgoing(application_id=apps["interview"], kind="reply" if status != "draft" else "application", to=LONG_EMAIL, subject=subject, body="Zq Dear hiring team,\n\n" + LONG_TITLE,
                           status=status, error=error, sent_at=now - timedelta(hours=3) if status == "sent" else None, sent_by="user"))

    # ── site accounts in every state, and their sessions ─────────────────────────────────────────────────────────────
    stamp = time.time()

    def cookie(domain: str, expires: float, name: str = "sid") -> dict:
        return {"name": name, "value": "made-up-" + name, "domain": domain, "path": "/", "expires": expires, "httpOnly": True, "secure": True, "sameSite": "Lax"}

    def session(key: str, cookies: list[dict], saved_ago: float) -> None:
        browser.write_state(key, {"cookies": cookies, "origins": []}, made_in="")
        p = browser._state_path(key)  # noqa: SLF001 (the age of the file is when it was saved)
        os.utime(p, (stamp - saved_ago, stamp - saved_ago))

    for key, (host, email, has_pw, status, by, error, sess) in ACCOUNTS.items():
        auth.upsert_account(key, host=host, email=email, password=PASSWORD if has_pw else None, status=status, created_by=by, error=error)
        domain = "." + (host.split(".", 1)[1] if "." in host else "zq.example")
        if sess == "good":
            session(key, [cookie(domain, stamp + 400 * 86400), cookie(domain, -1, "PLAY_SESSION")], 86400 + 3 * 3600)
        elif sess == "expired":
            session(key, [cookie(domain, stamp - 3 * 86400)], 40 * 86400)
        elif sess == "session-only":
            session(key, [cookie(domain, -1, "ORA_SESSION")], 2 * 3600)
    with db.session() as s:
        s.get(Account, "workday:zq-ready.wd3").last_login_ok = now - timedelta(days=1, hours=3)
        s.get(Account, "workday:zq-signin.wd2").last_login_ok = now - timedelta(days=30)

    # identity providers: one saved, one run out, one never, and a custom one with a long name and a session-only cookie
    session("idp:google", [cookie(".google.com", stamp + 380 * 86400, "SID")], 5 * 86400)
    session("idp:linkedin", [cookie(".linkedin.com", stamp - 10 * 86400, "li_at")], 120 * 86400)
    db.set_setting("identity.custom", [{"name": CUSTOM_PROVIDER, "url": "https://sso.zq-northfield.example/login", "domains": ["zq-northfield.example"]}])
    custom = next(k for k, v in browser.identities().items() if v.get("custom"))
    session("idp:" + custom, [cookie(".zq-northfield.example", -1, "shib")], 3600)
    db.set_setting("identity.emails", {"google": "alex.zq.personal.account-for-applications@example.com"})
