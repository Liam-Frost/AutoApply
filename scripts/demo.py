"""A demo installation with made-up data: for trying the program without touching your own data, for screenshots, for demos.

Everything in it is fictional - the applicant, the employers (all on .example addresses), the postings, the mail.

    uv run python scripts/demo.py --serve 8020 [--lang zh|en]         start a demo copy (no background work, no AI calls)
    uv run python scripts/demo.py --shots docs/images [--lang zh|en]  take the screenshots used in the README

The demo lives in a temporary folder with its own keyring namespace, so it cannot read or change a real installation.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

L = {  # text the program (or its AI) would have written, in the two interface languages
    "zh": {
        "reasons": ["目标方向完全吻合，要求的 SQL 和 Tableau 都在简历里；应届可投，地点在温哥华。", "岗位和目标方向一致，但要求 2 年经验，略高于现有经历。", "数据分析岗，行业是医疗，简历里的实习经历对口。",
                    "运营分析，偏流程改进；技能匹配，薪资在期望范围内。", "要求有金融建模经验，简历里只有课程项目。", "岗位偏销售支持，和目标方向只有部分重合。"],
        "basis": {"name": "个人资料：姓名", "email": "个人资料：邮箱", "phone": "个人资料：电话", "resume": "材料库里的简历", "cover": "为这个岗位写的求职信",
                  "auth": "个人资料：加拿大公民，可以合法工作", "sponsor": "个人资料：不需要签证担保", "linkedin": "个人资料：LinkedIn", "heard": "岗位来自公司招聘页",
                  "why": "根据简历里的 Lumen Health 实习和岗位说明写的，没有添加简历以外的经历", "start": "个人资料：2027 年 5 月毕业，6 月可以到岗"},
        "why": "Northwind 把运营数据直接用来改善门店体验，这正是我在 Lumen Health 实习时最喜欢做的事：我搭的周报看板把预约爽约率的分析时间从两天缩短到两小时。我想在一个数据会被真正用起来的团队里继续做这件事。",
        "mail": ["Harbor Bank 确认已收到你对 Junior Data Analyst 的申请，会在两周内回复。", "Kestrel Systems 邀请你参加 11 月 20 日上午 10 点的线上面试（45 分钟）。", "Pinecrest Labs 表示这次不再推进你的申请。"],
        "todo_login": "这个网站要先登录才能申请。你在这里有账号的话，登录一次，程序会记住登录状态。",
        "unresolved": "资料里没有写期望薪资。",
        "open": [{"label": "Expected salary (CAD)", "expected": "", "kind": "fix", "why": "资料里没有这一项，需要你来填"}],
        "mapped": [{"label": "Veteran Status", "approved": "No", "chosen": "I am not a protected veteran"}],
        "added": [{"label": "Legal First Name", "value": "Alexander", "basis": "个人资料：证件上的名字是 Alexander Chen"}],
        "submit_body": "还有 1 处没填好，需要你在窗口里处理；1 项是 AI 按你的资料补填的",
        "answer_body": "1 个问题没有答案：\n· What are your salary expectations?",
        "profile": "# 个人资料\n\n## 身份与联系方式\n\n- 姓名：Alex Chen（证件上的名字是 Alexander Chen）\n- 邮箱：alex.chen@example.com\n- 电话：+1 604-555-0142\n- 所在地：加拿大温哥华\n- LinkedIn：https://www.linkedin.com/in/alex-chen-example\n\n## 教育\n\n- Example University，商学学士（商业分析方向），2023 年 9 月 – 2027 年 5 月\n\n## 工作许可\n\n- 加拿大公民，可以合法工作；不需要签证担保。\n\n## 到岗\n\n- 2027 年 5 月毕业，6 月可以到岗。\n",
    },
    "en": {
        "reasons": ["Matches the target role exactly; the SQL and Tableau it asks for are on the résumé; open to new graduates; Vancouver.", "On target, but asks for two years of experience, slightly more than the résumé shows.",
                    "Data analysis in healthcare; the internship on the résumé is directly relevant.", "Operations analysis with a process-improvement angle; skills match and the salary is in range.",
                    "Asks for financial modelling experience; the résumé only has course projects.", "Leans towards sales support; only partly the target direction."],
        "basis": {"name": "Profile: name", "email": "Profile: e-mail", "phone": "Profile: phone", "resume": "Résumé from the materials library", "cover": "Cover letter written for this posting",
                  "auth": "Profile: Canadian citizen, legally able to work", "sponsor": "Profile: no sponsorship needed", "linkedin": "Profile: LinkedIn", "heard": "The posting came from the company's careers page",
                  "why": "Written from the Lumen Health internship on the résumé and the posting; nothing added that is not on the résumé", "start": "Profile: graduates May 2027, can start in June"},
        "why": "Northwind uses its operations data to improve what happens in stores, which is the part of my Lumen Health internship I enjoyed most: the weekly dashboard I built cut the no-show analysis from two days to two hours. I want to keep doing that on a team where the numbers actually get used.",
        "mail": ["Harbor Bank confirmed it received your application for Junior Data Analyst and will reply within two weeks.", "Kestrel Systems invites you to a 45-minute online interview on 20 November at 10:00.", "Pinecrest Labs is not moving forward with your application this time."],
        "todo_login": "This site needs you to sign in before applying. If you have an account here, sign in once and the program remembers it.",
        "unresolved": "The profile does not state a salary expectation.",
        "open": [{"label": "Expected salary (CAD)", "expected": "", "kind": "fix", "why": "The profile does not state this; it needs you"}],
        "mapped": [{"label": "Veteran Status", "approved": "No", "chosen": "I am not a protected veteran"}],
        "added": [{"label": "Legal First Name", "value": "Alexander", "basis": "Profile: the name on documents is Alexander Chen"}],
        "submit_body": "1 item still needs you in the window; 1 item was filled in by the AI from your profile",
        "answer_body": "1 question has no answer:\n· What are your salary expectations?",
        "profile": "# Profile\n\n## Identity and contact\n\n- Name: Alex Chen (name on documents: Alexander Chen)\n- E-mail: alex.chen@example.com\n- Phone: +1 604-555-0142\n- Location: Vancouver, Canada\n- LinkedIn: https://www.linkedin.com/in/alex-chen-example\n\n## Education\n\n- Example University, Bachelor of Commerce (Business Analytics), Sept 2023 – May 2027\n\n## Work authorisation\n\n- Canadian citizen, legally able to work; no sponsorship needed.\n\n## Availability\n\n- Graduates May 2027; can start in June.\n",
    },
}

JOBS = [  # company, title, location, score, source, application status
    ("Northwind Analytics", "Data Analyst, Store Operations (New Grad)", "Vancouver, BC, Canada", 9.2, "greenhouse", "draft_ready"),
    ("Harbor Bank", "Junior Data Analyst", "Toronto, ON, Canada", 8.8, "workday", "confirmed"),
    ("Kestrel Systems", "Business Intelligence Analyst I", "Vancouver, BC, Canada", 8.6, "ashby", "interview"),
    ("Lumen Health", "Analyst, Clinical Operations", "Burnaby, BC, Canada", 8.4, "greenhouse", "ready_to_submit"),
    ("Aurora Robotics", "Operations Analyst", "Seattle, WA, USA", 8.1, "page", "needs_human"),
    ("Pinecrest Labs", "Associate Analyst, Finance", "Calgary, AB, Canada", 7.9, "lever", "rejected"),
    ("Meridian Foods", "Supply Chain Analyst (Entry Level)", "Richmond, BC, Canada", 7.7, "workday", "needs_input"),
    ("Cobalt Insurance", "Reporting Analyst", "Remote, Canada", 7.4, "feed", "submitted"),
    ("Tidewater Energy", "Business Analyst, Commercial", "Calgary, AB, Canada", 7.1, "workday", ""),
    ("Orchard Retail", "Pricing Analyst", "Toronto, ON, Canada", 6.8, "greenhouse", ""),
    ("Summit Logistics", "Data Coordinator", "Delta, BC, Canada", 6.2, "feed", ""),
    ("Vantage Media", "Sales Operations Associate", "Vancouver, BC, Canada", 5.6, "lever", ""),
]


def seed(lang: str) -> None:
    """Fill the current (empty) data folder. Call with AUTOAPPLY_DATA / AUTOAPPLY_KNOWLEDGE pointing at it."""
    sys.path.insert(0, str(ROOT / "backend"))
    from autoapply import db, knowledge, persona
    from autoapply.models import Application, Draft, Job, MailEvent, Todo

    t = L[lang]
    db.init_db()
    db.set_setting("ui.lang", lang)
    who = {"stage": "new_grad", "field": "business", "targets": ["data analyst", "business analyst", "operations analyst"], "countries": ["CA", "US"], "sponsorship": False,
           "portal": "", "strategy": "focused"}
    persona.apply(who, persona.template(who), persona.default_scoring(who))
    knowledge.write("profile", t["profile"], source="user", note="demo")
    now = datetime.utcnow()
    soon = int(time.time()) + 3 * 3600
    week = int(time.time()) + 4 * 86400
    db.set_setting("llm.provider", "claude_subscription")
    db.set_setting("llm.providers", {"deepseek": {"base_url": "", "model": "deepseek-chat", "small_model": "deepseek-chat"}})
    db.set_setting("llm.failover", [{"provider": "chatgpt", "model": "", "small_model": ""}])
    db.set_setting("llm.quota", {
        "claude_subscription": {"provider": "claude_subscription", "supported": True, "checked_at": int(time.time()) + 86400, "kind": "windows", "blocked": False, "windows": [
            {"key": "five_hour", "label": "5 小时额度", "used": 62, "resets_at": soon, "blocked": False}, {"key": "seven_day", "label": "每周额度", "used": 41, "resets_at": week, "blocked": False}]},
        "chatgpt": {"provider": "chatgpt", "supported": True, "checked_at": int(time.time()) + 86400, "kind": "windows", "blocked": False, "plan": "plus", "windows": [
            {"key": "primary", "label": "5 小时额度", "used": 88, "resets_at": soon + 1800, "blocked": False}, {"key": "secondary", "label": "每周额度", "used": 47, "resets_at": week, "blocked": False}]},
        "deepseek": {"provider": "deepseek", "supported": True, "checked_at": int(time.time()) + 86400, "kind": "balance", "blocked": False, "balances": [{"currency": "USD", "amount": 12.4}]},
    })
    questions = [("first_name", "First Name", "text", "Alex", "name"), ("last_name", "Last Name", "text", "Chen", "name"), ("email", "Email", "text", "alex.chen@example.com", "email"),
                 ("phone", "Phone", "text", "+1 604-555-0142", "phone"), ("resume", "Resume/CV", "file", "Alex_Chen_Resume.pdf", "resume"), ("cover", "Cover Letter", "file", "Northwind_Analytics_Cover_Letter.pdf", "cover"),
                 ("linkedin", "LinkedIn Profile", "text", "https://www.linkedin.com/in/alex-chen-example", "linkedin"),
                 ("auth", "Are you legally authorized to work in Canada?", "select", "Yes", "auth"), ("sponsor", "Will you now or in the future require sponsorship?", "select", "No", "sponsor"),
                 ("start", "Earliest start date", "text", "June 2027", "start"), ("heard", "How did you hear about this role?", "select", "Company website", "heard"),
                 ("why", "Why are you interested in this role at Northwind?", "textarea", t["why"], "why")]

    def schema(ats: str, host: str) -> dict:
        return {"ats": ats, "tenant": host.split(".")[0], "job_ref": "1", "url": f"https://{host}/jobs/1", "source": "api", "pages": ["Application"], "extra": {},
                "questions": [{"id": i, "label": lab, "type": typ, "required": i not in ("linkedin", "heard"), "options": ["Yes", "No"] if typ == "select" and i != "heard" else
                               (["Company website", "Job board", "Referral", "Other"] if i == "heard" else []), "page": 0, "section": "", "help": "", "locator": {}, "depends_on": "", "accept_text": False}
                              for i, lab, typ, _, _ in questions],
                "_ref": {"ats": ats, "tenant": host.split(".")[0], "job_id": "1", "url": f"https://{host}/jobs/1", "host": host, "extra": {}}}

    def answers(unresolved: bool = False) -> list[dict]:
        rows = [{"id": i, "label": lab, "type": typ, "options": [], "required": i not in ("linkedin", "heard"), "page": 0, "value": val, "basis": t["basis"][b],
                 "confidence": "medium" if i == "why" else "high", "source": "materials" if typ == "file" else "profile", "sensitive": "work_auth" if i == "auth" else "sponsorship" if i == "sponsor" else "",
                 "sensitive_confirmed": True} for i, lab, typ, val, b in questions]
        if unresolved:
            rows.append({"id": "salary", "label": "What are your salary expectations?", "type": "text", "options": [], "required": True, "page": 0, "value": "", "basis": t["unresolved"],
                         "confidence": "low", "source": "unresolved", "sensitive": "salary", "sensitive_confirmed": False})
        return rows

    with db.session() as s:
        ids = {}
        for n, (company, title, loc, score, source, st) in enumerate(JOBS):
            host = f"careers.{company.split()[0].lower()}.example"
            j = Job(source=source if source != "page" else "manual", source_id=f"demo{n}", company=company, title=title, location=loc, score=score, score_reason=t["reasons"][min(n // 2, 5)],
                    apply_url=f"https://{host}/jobs/{100 + n}", channel="employer site", ats="greenhouse" if source in ("greenhouse", "feed", "page", "lever") else source, tenant=host.split(".")[1],
                    deadline=(now + timedelta(days=4 + n * 2)).strftime("%Y-%m-%d 23:59"), posted=(now - timedelta(days=n + 1)).strftime("%Y-%m-%d"), status="scored", jd_text="x" * 400,
                    salary="CAD 62,000–70,000" if n % 3 == 0 else "", first_seen=now - timedelta(days=n + 1))
            s.add(j)
            s.flush()
            ids[company] = j.id
            if not st:
                continue
            a = Application(job_id=j.id, status=st, channel="employer site", created_at=now - timedelta(days=n, hours=3))
            if st in ("confirmed", "interview", "rejected", "submitted"):
                a.submitted_at = now - timedelta(days=n + 2)
                a.evidence = {"text": "Thank you for applying", "url": f"https://{host}/jobs/{100 + n}/confirmation"}
            s.add(a)
            s.flush()
            if st in ("draft_ready", "needs_input", "ready_to_submit"):
                rows = answers(unresolved=st == "needs_input")
                d = Draft(application_id=a.id, version=1, schema=schema("greenhouse", host), answers=rows, unresolved=[r for r in rows if r["source"] == "unresolved"],
                          materials=[{"kind": "resume", "name": "Alex_Chen_Resume.pdf", "path": ""}, {"kind": "cover_letter", "name": f"{company.replace(' ', '_')}_Cover_Letter.pdf", "path": ""}],
                          review_status="approved" if st == "ready_to_submit" else "pending", notes=[], plan=[], auto_approve_check={"passed": False, "failed": ["cover_letter_ok"], "checks": {}})
                s.add(d)
                s.flush()
                title_ = f"{company} · {title}"
                if st == "needs_input":
                    s.add(Todo(kind="answer", ref=f"draft:{d.id}", title=title_, body=t["answer_body"], payload={"draft_id": d.id}))
                elif st == "ready_to_submit":
                    s.add(Todo(kind="submit", ref=f"application:{a.id}", title=title_, body=t["submit_body"],
                               payload={"draft_id": d.id, "incomplete": True, "open_items": t["open"], "mapped": t["mapped"], "added": t["added"]}))
            if st == "needs_human":
                s.add(Todo(kind="takeover", ref=f"account:generic:{host}", title=f"{company} · {title}", body=t["todo_login"],
                           payload={"tenant_key": f"generic:{host}", "ats": "generic", "url": f"https://{host}/login", "job_url": f"https://{host}/jobs/{100 + n}", "can_register": True}))
        apps = {a.job.company: a for a in s.query(Application)}
        for k, (company, cat, subj) in enumerate([("Harbor Bank", "confirmation", "Thank you for applying to Harbor Bank"), ("Kestrel Systems", "interview", "Interview invitation - Business Intelligence Analyst I"),
                                                   ("Pinecrest Labs", "rejection", "Update on your application")]):
            apps[company].last_event = f"{cat}: {t['mail'][k]}"
            s.add(MailEvent(message_id=f"demo-mail-{k}", sender=f"careers@{company.split()[0].lower()}.example", subject=subj, received_at=now - timedelta(hours=5 + 20 * k), category=cat,
                            application_id=apps[company].id, company_guess=company, summary=t["mail"][k]))
        seed_history(s, now, lang)
        seed_timing(s, now)


SERVE = """
import os, sys
sys.path.insert(0, r'{backend}')
import uvicorn
from autoapply import access
access.enforced = lambda: False      # the demo copy holds made-up data and is opened by the screenshot script
from autoapply import db, net, persona
db.init_db(); net.apply()
uvicorn.run('autoapply.api.main:app', host='127.0.0.1', port={port}, log_level='warning', lifespan='off')
"""


def start(lang: str, port: int) -> tuple[subprocess.Popen, Path]:
    home = Path(tempfile.mkdtemp(prefix="autoapply-demo-"))
    (home / "data").mkdir()
    (home / "knowledge").mkdir()
    env = {**os.environ, "AUTOAPPLY_DATA": str(home / "data"), "AUTOAPPLY_KNOWLEDGE": str(home / "knowledge"), "AUTOAPPLY_KEYRING_SERVICE": "autoapply-demo", "PYTHONIOENCODING": "utf-8"}
    subprocess.run([sys.executable, __file__, "--seed", lang], env=env, check=True)
    p = subprocess.Popen([sys.executable, "-c", SERVE.format(backend=str(ROOT / "backend"), port=port)], env=env)
    import urllib.request

    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/overview", timeout=2)  # noqa: S310
            return p, home
        except OSError:
            time.sleep(0.5)
    p.kill()
    raise RuntimeError("the demo server did not start")


def seed_history(s, now: datetime, lang: str = "zh") -> None:  # noqa: ANN001
    """What the analysis page shows: four months of earlier applications, five weeks of the program's tasks, and the
    model requests those tasks made. Made up like everything else here, and drawn from a fixed seed so that two demo
    copies look the same. Costs are computed from the built-in price list, exactly as for real requests."""
    import random

    from autoapply import metering
    from autoapply.models import Application, ApplicationEvent, Job, LLMRequest, MailEvent, Task

    rnd = random.Random(7)
    firms = ["Alder", "Birchwood", "Cedar Point", "Dunmore", "Eastgate", "Fairhaven", "Glenrock", "Highfield", "Ironbridge", "Juniper", "Kingsley", "Larkspur"]
    kinds = ["Analytics", "Logistics", "Health", "Energy", "Retail", "Software"]
    roles = [("Data Analyst", "数据分析"), ("Business Analyst", "商业分析"), ("Operations Analyst", "运营分析"), ("Reporting Analyst", "数据分析"), ("BI Developer", "商业智能")]
    if lang == "en":
        names = {"数据分析": "Data analysis", "商业分析": "Business analysis", "运营分析": "Operations analysis", "商业智能": "Business intelligence"}
        roles = [(t_, names[d_]) for t_, d_ in roles]
    n = 0
    for month_back, count in ((4, 6), (3, 11), (2, 16), (1, 13)):
        for _ in range(count):
            n += 1
            firm, (title, direction) = f"{firms[n % len(firms)]} {kinds[(n * 5) % len(kinds)]}", roles[n % len(roles)]
            score = rnd.choice([6.0, 6.5, 7.0, 7.5, 7.5, 8.0, 8.0, 8.5, 9.0, 9.5])
            sent = now - timedelta(days=month_back * 30 - rnd.randint(0, 27), hours=rnd.randint(0, 9))
            roll = rnd.random() + (score - 7.5) * 0.06          # better-scored postings answer a little more often
            status = "interview" if roll > 0.97 else "assessment" if roll > 0.93 else "rejected" if roll > 0.62 else "confirmed" if roll > 0.36 else "submitted"
            j = Job(source="greenhouse" if n % 3 else "lever", source_id=f"demo-old{n}", company=firm, title=title, direction=direction, location="Vancouver, BC", score=score,
                    apply_url=f"https://careers.{firm.split()[0].lower()}.example/jobs/{n}", channel="employer site", ats="greenhouse" if n % 3 else "lever", status="applied", online=0,
                    jd_text="x" * 300, first_seen=sent - timedelta(days=rnd.randint(1, 9)), archived_at=now - timedelta(days=5))
            s.add(j)
            s.flush()
            a = Application(job_id=j.id, status=status, channel="employer site", submitted_at=sent, created_at=sent - timedelta(hours=2))
            s.add(a)
            s.flush()
            if status != "submitted":
                s.add(MailEvent(message_id=f"demo-old-c{n}", sender="careers@employer.example", subject="Application received", received_at=sent + timedelta(minutes=3), category="confirmation", application_id=a.id))
            if status in ("rejected", "interview", "assessment"):
                went_far = status != "rejected" or rnd.random() < 0.15       # some rejections came after an interview
                if went_far:
                    s.add(MailEvent(message_id=f"demo-old-i{n}", sender="careers@employer.example", subject="Next step", received_at=sent + timedelta(days=rnd.randint(4, 12)),
                                    category="interview" if status != "assessment" else "assessment", application_id=a.id))
                    s.add(ApplicationEvent(application_id=a.id, at=sent + timedelta(days=6), old="confirmed", new="interview" if status != "assessment" else "assessment"))
                if status == "rejected":
                    s.add(MailEvent(message_id=f"demo-old-r{n}", sender="careers@employer.example", subject="Update on your application", received_at=sent + timedelta(days=rnd.randint(9, 30)),
                                    category="rejection", application_id=a.id))

    for k, (firm, title, score, days_ago, gone) in enumerate([("Marlow Analytics", "Junior Data Analyst", 9.0, 12, "deadline"), ("Northgate Health", "Reporting Analyst", 8.5, 20, "offline"),
                                                              ("Orchard Logistics", "Operations Analyst", 8.0, 31, "deadline"), ("Peregrine Software", "BI Analyst", 7.5, 44, "offline")]):
        s.add(Job(source="greenhouse", source_id=f"demo-missed{k}", company=firm, title=title, direction=roles[0][1], location="Vancouver, BC", score=score, status="scored",
                  apply_url=f"https://careers.{firm.split()[0].lower()}.example/jobs/{k}", channel="employer site", ats="greenhouse", online=0 if gone == "offline" else 1,
                  deadline=(now - timedelta(days=days_ago - 9)).strftime("%Y-%m-%d 23:59"), jd_text="x" * 300, first_seen=now - timedelta(days=days_ago)))

    # --- the program's tasks of the last five weeks, and their model requests --------------------------------------------
    OPUS, HAIKU, SONNET = "claude-opus-5-5", "claude-haiku-5-5", "claude-sonnet-5-5"
    job_ids = [j.id for j in s.query(Job).order_by(Job.id)]
    app_ids = [a.id for a in s.query(Application).order_by(Application.id)]

    def request(task: Task, at: datetime, feature: str, model: str, kind: str, tokens: tuple[int, int, int, int], *, turns: int = 1, ok: bool = True, backup: bool = False, call: str = "") -> None:
        provider = "anthropic" if backup else "claude_subscription"
        tk = metering.Tokens(*tokens) if ok else metering.Tokens(detail="none")
        price = metering.price_for(provider, model)
        cost = metering.cost_micros(tk, price, turns=turns)
        s.add(LLMRequest(request_id=f"demo-{task.id}-{feature}-{rnd.random()}", call_id=call or f"demo-{task.id}-{feature}-{rnd.random()}", attempt=1 if backup else 0, started_at=at,
                         latency_ms=int(900 * turns * rnd.uniform(0.7, 1.6)), provider=provider, model=model, billing="metered" if backup else "subscription", kind=kind, feature=feature,
                         task_id=task.id, workflow=task.kind, ref=task.ref, status="ok" if ok else "rate_limited", error="" if ok else "usage limit reached", turns=turns,
                         input_tokens=tk.input, cache_read_tokens=tk.cache_read, cache_write_tokens=tk.cache_write, output_tokens=tk.output, detail=tk.detail,
                         cost_micros=cost, cost_source="list_price" if cost is not None else "", pricing_version=price["version"] if price and cost is not None else "", source="live"))

    def task(kind: str, ref: str, at: datetime, status: str, minutes: float, *, result: dict | None = None, error: str = "", stages: list[str] | None = None) -> Task:
        t_ = Task(kind=kind, ref=ref, status=status, result=result or {}, error=error, attempts=1, created_at=at, started_at=at, finished_at=at + timedelta(minutes=minutes),
                  stages=[{"stage": x, "at": at.isoformat()} for x in (stages or [])])
        s.add(t_)
        s.flush()
        return t_

    for day in range(34, -1, -1):
        base = now - timedelta(days=day, hours=rnd.randint(1, 6))
        busy = 0.55 + 0.45 * (1 - day / 34)                                   # the program is used a little more as the weeks go by
        if day % 2 == 0:                                                        # scan and score
            task("discover", "schedule", base, "done", rnd.uniform(1, 3), result={"total": {"seen": 40, "new": rnd.randint(2, 9)}})
            n_scored = rnd.randint(3, 12)
            t_ = task("score", "unscored", base + timedelta(minutes=4), "done", n_scored * 0.3, result={"scored": n_scored})
            for i in range(n_scored):
                request(t_, base + timedelta(minutes=4, seconds=18 * i), "scoring", OPUS, "json", (rnd.randint(300, 700), rnd.randint(5200, 6400), rnd.randint(0, 400), rnd.randint(350, 620)))
        new_mail = rnd.randint(0, 4)
        t_ = task("mail", "schedule", base + timedelta(hours=2), "done", 0.6, result={"new_mail": new_mail})
        for i in range(new_mail):
            request(t_, t_.started_at + timedelta(seconds=9 * i), "mail_triage", HAIKU, "json", (rnd.randint(900, 2200), 0, 0, rnd.randint(120, 260)))
        for _ in range(rnd.choice([0, 1, 1, 2]) if rnd.random() < busy else 0):           # drafts
            jid = rnd.choice(job_ids)
            at = base + timedelta(hours=rnd.uniform(2.5, 5))
            roll = rnd.random()
            if roll < 0.18:
                err = rnd.choice(["网站暂时打不开：ERR_CONNECTION_TIMED_OUT；30 分钟后自动重试", "岗位在雇主官网上已关闭或链接失效，没有生成草案", "Claude subscription usage limit reached: resets 3pm"])
                t_ = task("recon", f"job:{jid}", at, "failed", rnd.uniform(0.5, 2), error=err, stages=["read_form"] if "usage" not in err else ["read_form", "explore_form"])
                if "usage" in err:
                    request(t_, at, "explore_form", OPUS, "agent", (0, 0, 0, 0), ok=False)
                continue
            explored = rnd.random() < 0.45                                     # a site without a driver: the AI explores the form
            t_ = task("recon", f"job:{jid}", at, "done", rnd.uniform(1.5, 6), result={"draft_id": 1}, stages=["read_form"] + (["explore_form"] if explored else []) + ["cover_letter", "tailor_resume", "answers"])
            if explored:
                turns = rnd.randint(14, 34)
                if rnd.random() < 0.08:
                    turns *= 3                                                  # the odd form that takes far longer than the others
                request(t_, at, "explore_form", OPUS, "agent", (turns * 900, turns * 21000, turns * 2600, turns * 380), turns=turns)
            request(t_, at + timedelta(minutes=1), "cover_letter", OPUS, "json", (rnd.randint(2500, 4000), rnd.randint(3000, 5000), 0, rnd.randint(900, 1400)))
            request(t_, at + timedelta(minutes=1, seconds=40), "tailor_resume", OPUS, "json", (rnd.randint(2800, 4200), rnd.randint(3000, 5000), 0, rnd.randint(1200, 2100)))
            call = f"demo-answers-{t_.id}"
            if rnd.random() < 0.07:                                             # the subscription ran out: the same call is made again on the backup
                request(t_, at + timedelta(minutes=2), "answers", OPUS, "json", (0, 0, 0, 0), ok=False, call=call)
                request(t_, at + timedelta(minutes=2, seconds=20), "answers", SONNET, "json", (rnd.randint(7000, 11000), 0, 0, rnd.randint(1500, 2600)), backup=True, call=call)
            else:
                request(t_, at + timedelta(minutes=2), "answers", OPUS, "json", (rnd.randint(1500, 2600), rnd.randint(6000, 9000), 0, rnd.randint(1500, 2600)), call=call)
        if rnd.random() < 0.5 * busy:                                           # filling a form
            aid = rnd.choice(app_ids)
            at = base + timedelta(hours=rnd.uniform(5, 8))
            roll = rnd.random()
            outcome_ = "submitted" if roll < 0.52 else "ready_to_submit" if roll < 0.82 else "failed"
            helped = rnd.random() < 0.5 or outcome_ == "failed"
            stages = ["ensure_session", "open", "fill_page"] + (["form_reports", "repair"] if helped else []) + ["read_back"] + (["submit"] if outcome_ == "submitted" else ["handed_over"] if outcome_ == "ready_to_submit" else [])
            res = {"status": outcome_, **({"error": rnd.choice(["could not advance to the next page", "values on the form differ from the approved draft"])} if outcome_ == "failed" else {})}
            t_ = task("execute", f"application:{aid}", at, "done", rnd.uniform(1.2, 4) if outcome_ != "ready_to_submit" else rnd.uniform(6, 18), result=res, stages=stages)
            if helped:
                turns = rnd.randint(5, 16)
                request(t_, at + timedelta(seconds=50), "take_over", OPUS, "agent", (turns * 700, turns * 15000, turns * 1800, turns * 260), turns=turns)
        if day % 9 == 4:
            t_ = task("revise", f"draft:{rnd.randint(1, 3)}", base + timedelta(hours=9), "done", 0.8, result={"draft_id": 1})
            request(t_, t_.started_at, "revise_draft", OPUS, "json", (rnd.randint(2000, 3200), rnd.randint(7000, 9000), 0, rnd.randint(700, 1300)))


def seed_timing(s, now: datetime) -> None:  # noqa: ANN001
    """What "Time & learning" on the analysis page shows: six weeks of form-filling runs with where their time went,
    and two things the program learned from them - one that holds up, one that was taken out again. Made up."""
    import json
    import random

    from autoapply import learned
    from autoapply.models import Run

    rnd = random.Random(11)
    recipe = json.dumps({"controls": [{"when": {"label": "^Code$"}, "do": "leave_if_shown"}]}, indent=1)
    code = "def set_value(page, q, value, w):\n    if q.label != \"Start date\":\n        return False\n    w.set_text(page.locator(\"#start-date\"), str(value))\n    return True\n"
    made = (now - timedelta(days=16)).isoformat(timespec="seconds")
    revs = [
        {"id": "demo000001", "kind": "recipe", "target": "generic:careers.alder.example", "title": "区号列表已经显示所选条目时不再重选", "status": "active",
         "why": "这个网站的电话区号列表选中后只显示“+1”，驱动每次都判定为没选上，AI 因此反复接手同一页。", "expected": "不再为 Code 字段接手，每次运行少等两到三次 AI。",
         "why_status": "在 4 次运行里表现正常", "created": made, "from_run": 12, "version": "1.0.3", "strikes": 0, "baseline": {"runs": 6, "median_ms": 212000},
         "trials": [{"run": 20 + i, "ok": True, "ms": 96000 + i * 3000, "human": 0, "used": True} for i in range(4)],
         "history": [{"at": made, "status": "trial", "why": "passed the gate"}, {"at": (now - timedelta(days=11)).isoformat(timespec="seconds"), "status": "active", "why": "held up in 2 runs"}]},
        {"id": "demo000002", "kind": "plugin", "target": "workday", "title": "开始日期用键盘直接输入", "status": "reverted",
         "why": "日期控件逐格点击很慢，直接输入可以省十几秒。", "expected": "“填一个字段”里的日期不再超过 10 秒。",
         "why_status": "在一次运行里出错，已退回原来的做法：set_value: TimeoutError", "created": (now - timedelta(days=9)).isoformat(timespec="seconds"), "from_run": 26, "version": "1.0.3", "strikes": 1,
         "baseline": {"runs": 9, "median_ms": 148000}, "trials": [{"run": 31, "ok": False, "ms": 151000, "human": 0, "used": True, "strike": "set_value: TimeoutError"}],
         "history": [{"at": (now - timedelta(days=9)).isoformat(timespec="seconds"), "status": "trial", "why": "passed the gate"},
                     {"at": (now - timedelta(days=7)).isoformat(timespec="seconds"), "status": "reverted", "why": "it failed in a run: set_value: TimeoutError"}]},
    ]
    learned.root().mkdir(parents=True, exist_ok=True)
    for rev, body, name in ((revs[0], recipe, "recipe.json"), (revs[1], code, "plugin.py")):
        (learned.root() / rev["id"]).mkdir(exist_ok=True)
        (learned.root() / rev["id"] / name).write_text(body, encoding="utf-8")
    learned._save(revs)
    # ... and what the program knows about one site, all in one place (sites.py)
    from autoapply.models import Site

    notes = ["The forward button on the questions step is labelled 'Save and continue'.", "The phone code list shows only the code once an entry is chosen.",
             "The résumé is uploaded on the first step; the form fills name and e-mail from it."]
    s.add(Site(key="generic:careers.alder.example", facts={"driver_written": True}, notes=[{"at": (now - timedelta(days=3 * n)).date().isoformat(), "text": t} for n, t in enumerate(notes)],
               steps={"pages": ["Contact", "Questions", "Review"], "steps": {
                   "Contact": {"questions": [{"label": x, "type": "text", "selector": f"#c{i}"} for i, x in enumerate(("First name", "Last name", "E-mail", "Phone code", "Phone number"))]},
                   "Questions": {"questions": [{"label": x, "type": "radio", "selector": f"#q{i}"} for i, x in enumerate(("Are you legally authorised to work here?", "Will you require sponsorship?", "Earliest start date"))]}}}))

    def spans(takeovers: int, slow_field: bool) -> list[dict]:
        out, t = [], 0

        def add(kind: str, name: str, ms: int, **extra) -> None:
            nonlocal t
            out.append({"k": kind, "n": name, "t": t, "ms": ms, **extra})
            t += ms

        add("site", "load", rnd.randint(1800, 5200), host="careers.alder.example")
        for label in ("First name", "Last name", "Email", "Phone", "Code", "Current location", "Resume"):
            failed = label == "Code" and takeovers > 0
            add("driver", "field", rnd.randint(14000, 19000) if (slow_field and label == "Current location") else rnd.randint(300, 2600), label=label, **({"ok": False} if failed else {}))
        for _ in range(takeovers):
            add("ai", "take_over", rnd.randint(18000, 34000))
            for tool in ("list_controls", "select", "check_form"):
                add("tool", tool, rnd.randint(400, 3800), **({"ok": False} if tool == "select" else {}))
        add("driver", "step:read_back", rnd.randint(900, 2400))
        add("driver", "step:submit", rnd.randint(2500, 6000))
        return out

    for day in range(40, -1, -3):
        at = now - timedelta(days=day, hours=rnd.randint(0, 6))
        for ats, site, subject_id in (("generic", "site-careers.alder.example", 1), ("workday", "workday", 2)):
            after = ats == "generic" and day <= 15
            takeovers = 0 if after else rnd.choice([1, 2, 2, 3]) if ats == "generic" else rnd.choice([0, 1, 1])
            steps = [{"op": "open"}, {"op": "fill_page"}] + [{"op": "repair", "cause": "the Code list shows only +1"}] * takeovers + [{"op": "read_back"}, {"op": "submit"}]
            s.add(Run(kind="execute", ref=f"application:{subject_id}", ats=ats, ok=1, steps=steps, spans=spans(takeovers, slow_field=(ats == "workday" and day % 9 == 0)),
                      site=site, learned=["demo000001"] if after else [], created_at=at))


def shots(out: Path, lang: str, port: int = 8021, only: str = "") -> None:
    from PIL import Image
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    p, _home = start(lang, port)
    base = f"http://127.0.0.1:{port}"
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(viewport={"width": 1360, "height": 860}, device_scale_factor=2, color_scheme="light", locale="zh-CN" if lang == "zh" else "en-US")
            ctx.add_init_script(f"try {{ localStorage.setItem('lang', '{lang}'); localStorage.setItem('theme', 'light') }} catch (e) {{}}")
            page = ctx.new_page()

            def snap(name: str, path: str, *, element: str = "", before=None, full: bool = False) -> None:  # noqa: ANN001
                if only and name != only:
                    return
                page.goto(base + path, wait_until="networkidle")
                page.wait_for_timeout(1500)       # the English dictionary is applied after the page has drawn
                if before:
                    before()
                    page.wait_for_timeout(900)
                png = out / f"_{name}.png"
                if element:
                    page.locator(element).first.screenshot(path=str(png))
                else:
                    page.screenshot(path=str(png), full_page=full)
                Image.open(png).convert("RGB").save(out / f"{name}-{lang}.webp", "WEBP", quality=88, method=6)
                png.unlink()
                print(out / f"{name}-{lang}.webp")

            did = page.request.get(base + "/api/drafts").json()[0]["id"]
            snap("overview", "/home")
            snap("jobs", "/jobs", before=lambda: page.locator(".seg button").filter(has_text=re.compile(r"^(全部|All)\s*\d+")).first.click())
            page.set_viewport_size({"width": 1360, "height": 1180})
            snap("draft", f"/drafts/{did}")
            snap("todos", "/todos")
            page.set_viewport_size({"width": 1360, "height": 860})

            def to_ai() -> None:
                page.get_by_role("button", name="AI 模型" if lang == "zh" else "AI model").first.click()
                page.wait_for_timeout(1200)
                page.add_style_tag(content=".pr-nav { visibility: hidden }")    # the side list is sticky and would cover the corner of the card

            snap("failover", "/settings", element=".pr > .card:last-child", before=to_ai)
            page.set_viewport_size({"width": 1360, "height": 1040})
            snap("analytics", "/analytics?view=ai")
            b.close()
    finally:
        p.kill()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", metavar="LANG")
    ap.add_argument("--serve", type=int, metavar="PORT")
    ap.add_argument("--shots", metavar="DIR")
    ap.add_argument("--lang", default="zh", choices=["zh", "en"])
    ap.add_argument("--only", default="", metavar="NAME", help="with --shots: take only this screenshot (overview, jobs, draft, todos, failover, analytics)")
    a = ap.parse_args()
    if a.seed:
        seed(a.seed)
    elif a.shots:
        shots(Path(a.shots), a.lang, only=a.only)
    elif a.serve:
        p, home = start(a.lang, a.serve)
        print(f"demo at http://127.0.0.1:{a.serve}  (data in {home}; Ctrl+C stops it)")
        try:
            p.wait()
        except KeyboardInterrupt:
            p.kill()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
