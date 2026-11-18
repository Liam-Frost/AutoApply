"""What the settings come to, in words.

The settings are many, in several places, and what they add up to had to be worked out by the applicant: which postings
get in at all, which of the remaining ones get a draft, and how far the program then goes by itself. This reads the
rules where the program reads them - the intake filter, the thresholds of the scoring, how applications are sent
(``agent/work.py: policy``), what an application may spend - and says them, each
with the place where it is changed. Nothing is decided here: a statement that differs from what the program does is a
mistake in this file (tests/test_rules.py holds the two against each other).

``what_i_apply_to``: every line is a fact the applicant gave, a hard filter (what fails it is not taken in), a
preference (it moves the score), or a threshold. ``what_the_program_may_do``: every step, with who does it now.
"""
from __future__ import annotations

from typing import Any

from . import db

KINDS = {"fact": "你告诉程序的", "filter": "硬条件", "preference": "评分偏好", "threshold": "分数线", "source": "来源"}

SUBMIT, PREPARE, LOGINS, FILTERS = "/settings/automation/submit", "/settings/automation/prepare", "/settings/accounts/logins", "/settings/goals/filters"


def _line(kind: str, text: str, where: str, note: str = "") -> dict[str, str]:
    return {"kind": kind, "label": KINDS[kind], "text": text, "where": where, "note": note}


def _words(xs: Any) -> str:
    return "、".join(str(x) for x in (xs or []) if str(x).strip())


def what_i_apply_to() -> list[dict[str, str]]:
    from . import employers, intake, knowledge, persona

    st = db.all_settings()
    out: list[dict[str, str]] = []
    said = persona.describe(persona.get())
    out.append(_line("fact", said or "还没有填求职档案：程序按最初的默认方式工作", "/settings/goals/profile"))

    r = intake.rules()
    if not r["enabled"]:
        out.append(_line("filter", "入库前的硬条件没有启用：读到的岗位都会入库并评分", FILTERS))
    else:
        if r["title_any"]:
            out.append(_line("filter", f"标题里要有这些词之一：{_words(r['title_any'])}", FILTERS))
        if r["title_role_any"]:
            out.append(_line("filter", f"并且要有这些词之一：{_words(r['title_role_any'])}", FILTERS))
        if r["title_none"]:
            out.append(_line("filter", f"标题里不能有：{_words(r['title_none'])}", FILTERS))
        if r["countries"]:
            out.append(_line("filter", f"工作地点在：{_words(r['countries'])}", FILTERS, "岗位没写地点时不会因此被丢掉"))
        if int(r["max_age_days"] or 0) > 0:
            out.append(_line("filter", f"只要最近 {int(r['max_age_days'])} 天内发布的", FILTERS, "网站没写发布日期时不会因此被丢掉"))
        if not any((r["title_any"], r["title_role_any"], r["title_none"], r["countries"], int(r["max_age_days"] or 0) > 0)):
            out.append(_line("filter", "入库前的硬条件已启用，但一条也没有填：读到的岗位都会入库", FILTERS))
        if r.get("exempt_sources"):
            out.append(_line("filter", "学校门户和你手动添加的岗位不受上面这些条件限制", FILTERS))
    fields = sorted(intake.my_fields())
    given = bool([x for x in (st["intake.programs"] or []) if str(x).strip()])
    if fields:
        out.append(_line("filter", f"写明面向哪些专业的岗位，专业名里要有：{_words(fields)}", FILTERS,
                         "来自你填的专业" if given else "来自个人资料 Education 一节的第一条；没写面向专业的岗位不受影响"))

    lines = [ln.strip().lstrip("-*# ").strip() for ln in (knowledge.read("scoring") or "").splitlines()]
    lines = [ln for ln in lines if ln and not ln.lower().startswith(("scoring", "评分规则"))]
    if lines:
        for ln in lines[:8]:
            out.append(_line("preference", ln[:160], "/profile?tab=scoring"))
        if len(lines) > 8:
            out.append(_line("preference", f"……评分规则里还有 {len(lines) - 8} 行", "/profile?tab=scoring"))
    else:
        out.append(_line("preference", "还没有写评分规则：程序只按岗位说明和你的资料有多匹配来评分", "/profile?tab=scoring"))

    prio = [e for e in employers.listing() if e.get("priority") and e.get("enabled", True)]
    out.append(_line("threshold", f"评分达到 {float(st['queue.min_score_for_draft']):g} 分的岗位准备草案", PREPARE))
    if prio:
        out.append(_line("threshold", f"重点雇主（{len(prio)} 家）的岗位达到 {float(st['employers.priority_min_score'] or 7.0):g} 分就准备草案", PREPARE))
    watched = [e for e in employers.listing() if e.get("enabled", True)]
    # (whole sentences, not pieces put together: each of them is a text of the interface, and is translated as one)
    out.append(_line("source", f"关注 {len(watched)} 家雇主，其中重点 {len(prio)} 家" if prio else f"关注 {len(watched)} 家雇主", "/jobs/sources"))
    if st["sources.pdportal"]:
        out.append(_line("source", "扫描新岗位时读学校门户", "/jobs/sources"))
    if st["sources.search_terms"]:
        out.append(_line("source", f"在大型官网上搜：{_words(st['sources.search_terms'])}", "/settings/goals/search"))
    return out


def _step(key: str, name: str, who: str, text: str, where: str, more: list[str] | None = None) -> dict[str, Any]:
    """``who``: "auto" the program does it by itself, "you" it waits for the applicant, "mixed" it depends (see more), "off"."""
    return {"key": key, "name": name, "who": who, "text": text, "where": where, "more": more or []}


def what_the_program_may_do() -> list[dict[str, Any]]:
    from .agent import work

    st = db.all_settings()
    out: list[dict[str, Any]] = []
    paused = bool(st["schedule.paused"])

    every = int(st["schedule.discover_minutes"] or 0)
    out.append(_step("discover", "找岗位", "off" if (paused or not every) else "auto",
                     "自动运行已暂停：不会自己扫描，你点“扫描新岗位”才扫" if paused else f"每 {every} 分钟自己扫描一次新岗位" if every else "定时扫描已关闭：你点“扫描新岗位”才扫",
                     "/settings/automation/schedule", [f"新岗位自动评分，每次最多 {int(st['scoring.max_per_run'])} 个，其余留到下一次"]))

    cap = int(st["drafts.max_pending"] or 0)
    out.append(_step("prepare", "开始一份申请", "off" if paused else "auto",
                     "自动运行已暂停：不会自己开始申请" if paused else "评分够线的岗位，Agent 自己去做申请", PREPARE,
                     [f"同时最多 {cap} 份申请等你，到了就不再自己开始新的" if cap else "等你处理的申请没有数量上限", "你亲手点“申请”的不受暂停和上限限制"]))

    policy = work.policy()
    more = []
    if st["policy.manual_companies"]:
        more.append(f"这些公司始终停在最后一步，由你点提交：{_words(st['policy.manual_companies'])}")
    if policy == "auto" and st["tailor.review"] and str(st["tailor.mode"]) != "off":
        more.append("用了刚为这个岗位改写的简历时，先等你看过再提交")
    more.append("表单需要、而你的资料里没有的信息，Agent 不会编：它会问你，问题没答完不会提交")
    text = {"auto": "没有需要问你的问题时，Agent 填完就自己提交", "approve": "Agent 填好后把申请记录给你看，你批准之后它才提交",
            "hand_over": "Agent 填到最后一步停下，把窗口交给你，由你检查后点提交"}[policy]
    out.append(_step("submit", "提交申请", {"auto": "auto", "approve": "mixed", "hand_over": "you"}[policy], text, SUBMIT, more))

    out.append(_step("accounts", "账号和登录", "auto", "网站需要账号时，Agent 用已保存的账号登录；没有账号就用你的邮箱注册一个，密码由程序生成并保存，Agent 看不到", LOGINS,
                     ["验证码、手机上的二次验证、没有保存密码的账号：交给你", "已保存的密码只会输入到这个网站自己的登录页"]))
    b = (st["agent.budgets"] or {}).get("apply") or {}
    out.append(_step("budget", "每份申请的预算", "auto", f"一份申请最多用 {int(b.get('steps') or 400)} 步、{int(b.get('minutes') or 45)} 分钟；用完会停下来问你要不要继续",
                     "/settings/automation/permissions"))
    for s in out:
        s["more"] = [m for m in s["more"] if m]
    return out


def summary() -> dict[str, Any]:
    return {"apply": what_i_apply_to(), "allowed": what_the_program_may_do(), "paused": bool(db.get_setting("schedule.paused"))}
