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


SERVE = """
import os, sys
sys.path.insert(0, r'{backend}')
import uvicorn
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


def shots(out: Path, lang: str, port: int = 8021) -> None:
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
            b.close()
    finally:
        p.kill()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", metavar="LANG")
    ap.add_argument("--serve", type=int, metavar="PORT")
    ap.add_argument("--shots", metavar="DIR")
    ap.add_argument("--lang", default="zh", choices=["zh", "en"])
    a = ap.parse_args()
    if a.seed:
        seed(a.seed)
    elif a.shots:
        shots(Path(a.shots), a.lang)
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
