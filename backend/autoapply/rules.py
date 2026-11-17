"""What the settings come to, in words.

The settings are many, in several places, and what they add up to had to be worked out by the applicant: which postings
get in at all, which of the remaining ones get a draft, and how far the program then goes by itself. This reads the
rules where the program reads them - the intake filter, the thresholds of the scoring, the submission policy
(``executor.submit_mode``), the conditions of automatic approval, the rule for creating accounts - and says them, each
with the place where it is changed. Nothing is decided here: a statement that differs from what the program does is a
mistake in this file (tests/test_rules.py holds the two against each other).

``what_i_apply_to``: every line is a fact the applicant gave, a hard filter (what fails it is not taken in), a
preference (it moves the score), or a threshold. ``what_the_program_may_do``: every step, with who does it now.
"""
from __future__ import annotations

from typing import Any

from . import db

# the systems a policy can be set for, with the names the applicant knows them by (the settings page shows the same)
SYSTEMS = [("greenhouse", "Greenhouse"), ("ashby", "Ashby"), ("workday", "Workday"), ("pdportal", "UBC PD Portal"), ("generic", "其他网站")]
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


def submit_by_system() -> dict[str, str]:
    """Who presses Submit on each system for a draft whose answers raise no doubt, as the executor decides it."""
    from . import executor

    return {k: executor.submit_mode(k, "", [])["mode"] for k, _ in SYSTEMS}


def what_the_program_may_do() -> list[dict[str, Any]]:
    from . import executor

    st = db.all_settings()
    name = dict(SYSTEMS)
    out: list[dict[str, Any]] = []
    paused = bool(st["schedule.paused"])

    every = int(st["schedule.discover_minutes"] or 0)
    out.append(_step("discover", "找岗位", "off" if (paused or not every) else "auto",
                     "自动运行已暂停：不会自己扫描，你点“扫描新岗位”才扫" if paused else f"每 {every} 分钟自己扫描一次新岗位" if every else "定时扫描已关闭：你点“扫描新岗位”才扫",
                     "/settings/automation/schedule", [f"新岗位自动评分，每次最多 {int(st['scoring.max_per_run'])} 个，其余留到下一次"]))

    cap = int(st["drafts.max_pending"] or 0)
    out.append(_step("prepare", "准备草案", "off" if paused else "auto",
                     "自动运行已暂停：不会自己准备草案" if paused else "评分够线的岗位，程序自己读申请表、准备草案", PREPARE,
                     [f"同时最多 {cap} 份草案等你，到了就不再自己开始新的" if cap else "等你处理的草案没有数量上限", "你亲手点“生成草案”的不受暂停和上限限制"]))

    systems = [n for k, n in SYSTEMS if (st["auto_approve.per_ats"] or {}).get(k)]
    if st["auto_approve.enabled"] and systems:
        conds = [f"岗位评分至少 {float(st['auto_approve.min_score']):g}", f"这个招聘系统已连续成功提交 {int(st['auto_approve.min_driver_successes'])} 次以上",
                 "没有答不上的问题", "所有答案都来自你确认过的资料，把握高", "没有第一次遇到的敏感问题", "网站已登录", "草案里没有需要留意的备注",
                 "求职信是新写的也可以" if st["auto_approve.allow_new_cover_letter"] else "求职信不是新写的",
                 "用了新调整的简历的不行" if st["tailor.review"] else "用了新调整的简历也可以"]
        out.append(_step("approve", "批准草案", "mixed", f"同时满足下面所有条件的草案不用你批准（只限：{'、'.join(systems)}）；其余的都要你批准", SUBMIT + "-auto", conds))
    else:
        out.append(_step("approve", "批准草案", "you", "每份草案都要你批准（自动批准已打开，但没有一个招聘系统被允许）" if st["auto_approve.enabled"] else "每份草案都要你批准", SUBMIT))

    modes = submit_by_system()
    default = "manual" if str(st["policy.default"]) == "manual" else "auto"
    more = [f"{name[k]}：由你点提交" if m == "manual" else f"{name[k]}：程序自己提交" for k, m in modes.items() if m != default]
    if st["policy.manual_companies"]:
        more.append(f"这些公司始终由你点提交：{_words(st['policy.manual_companies'])}")
    level = str(st["policy.manual_confidence"] or "low")
    if level in ("low", "medium"):
        more.append("草案里有“把握低”的答案时，由你点提交" if level == "low" else "草案里有“把握中等”或“把握低”的答案时，由你点提交")
    more += [f"不管怎么设，这种情况也由你点提交：{x}" for x in executor.STOPS_ANYWAY]
    everywhere_manual = all(m == "manual" for m in modes.values())
    out.append(_step("submit", "点提交", "you" if everywhere_manual else "mixed" if (more and len(more) > len(executor.STOPS_ANYWAY)) or default == "manual" else "auto",
                     "你批准之后，程序填好就停下，由你检查后点提交" if default == "manual" else "你批准之后，程序填好、核对无误就自己提交", SUBMIT, more))

    can = bool(st["register.auto"])
    off = [n for k, n in SYSTEMS if (st["register.per_ats"] or {}).get(k) is False]
    sso = {"ask": "网站支持用第三方账号登录时，每个网站第一次先问你", "auto": "网站支持用第三方账号登录时，直接用你已登录的第三方账号", "never": "不用第三方账号登录，用邮箱注册"}
    out.append(_step("register", "注册账号", "off" if not can else "mixed" if off else "auto",
                     "没投过的网站由程序自己注册账号" if can else "程序不自己注册账号：遇到要登录的网站就请你登录", LOGINS,
                     ([f"这些招聘系统上不自己注册：{'、'.join(off)}"] if can and off else []) + [sso.get(str(st["sso.mode"]), ""), "你以前投过的网站，始终请你登录原来的账号"]))

    out.append(_step("notices", "点掉挡住表单的隐私声明", "auto" if st["consent.acknowledge_notices"] else "you",
                     "遇到只是告知的数据隐私声明，自己点“接受”后继续" if st["consent.acknowledge_notices"] else "遇到数据隐私声明就停下来等你", "/settings/automation/permissions",
                     ["申请表里面要勾选的同意项不在此列：照草案里你批准的答案填"]))
    out.append(_step("repair", "填写出错时让 AI 接手", "auto" if st["repair.enabled"] else "off",
                     "AI 可以接手把你批准过的内容填进去；不能编新答案，不能点提交" if st["repair.enabled"] else "填写出错就停下，不让 AI 接手", "/settings/automation/adaptive"))
    learn = bool(st["learned.enabled"])
    out.append(_step("learn", "从运行里学习", "off" if not learn else "you" if str(st["learned.mode"]) == "ask" else "auto",
                     "不从运行里学习" if not learn else "学到的做法先问你再用" if str(st["learned.mode"]) == "ask" else "学到的做法通过检查就自动试用，出错自动撤回", "/settings/automation/adaptive"))
    for s in out:
        s["more"] = [m for m in s["more"] if m]
    return out


def summary() -> dict[str, Any]:
    return {"apply": what_i_apply_to(), "allowed": what_the_program_may_do(), "paused": bool(db.get_setting("schedule.paused"))}
