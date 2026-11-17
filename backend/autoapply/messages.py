"""Notification templates: one function per event, each returning a ``Card``.

A card renders two ways: Telegram HTML (bold heading, quoted detail, tappable
link) and plain text (stored in the notification log and shown in the UI).

Layout, top to bottom:
    icon + heading        what happened, in a few words
    subject               which job / account it is about
    fields                short "label: value" facts
    items                 a bulleted list
    detail                longer text, quoted (collapsed in Telegram when long)
    hint                  what, if anything, the user should do
    link                  where to look in the app

Cards never carry passwords, verification codes, or profile data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from html import escape
from typing import Any


@dataclass
class Card:
    icon: str
    heading: str
    subject: str = ""  # "Company · Title" (the company part is emphasised) or any one-line subject
    fields: list[tuple[str, str]] = field(default_factory=list)
    items: list[str] = field(default_factory=list)
    items_title: str = ""
    inline: bool = False  # fields on one line, "a 1 · b 2"
    detail: str = ""
    hint: str = ""
    path: str = ""  # app path, e.g. /drafts/12
    link: str = "打开查看"

    def _blocks(self, html: bool, base_url: str) -> str:
        e = escape if html else (lambda x: x)
        b = (lambda x: f"<b>{x}</b>") if html else (lambda x: x)
        out = [f"{self.icon} {b(e(self.heading))}"]
        if self.subject:
            head, sep, rest = self.subject.partition(" · ")
            out.append(b(e(head)) + (e(sep + rest) if sep else ""))
        body: list[str] = []
        fs = [(k, v) for k, v in self.fields if v not in ("", None)]
        colon = "：" if re.search(r"[\u4e00-\u9fff]", self.heading + "".join(k for k, _ in fs)) else ": "
        if self.inline and fs:
            body.append(" · ".join(f"{e(k)} {b(e(str(v)))}" for k, v in fs))
        else:
            body += [f"{e(k)}{colon}{e(str(v))}" for k, v in fs]
        if self.items and self.items_title:
            body.append(e(self.items_title))
        body += [f"• {e(i)}" for i in self.items]
        if self.detail:
            d = self.detail.strip()
            if html:
                body.append(f"<blockquote{' expandable' if len(d) > 240 or d.count(chr(10)) > 3 else ''}>{e(d)}</blockquote>")
            else:
                body.append("\n".join("> " + ln for ln in d.splitlines()))
        if self.hint:
            body.append(f"<i>{e(self.hint)}</i>" if html else self.hint)
        if body:
            out.append("")
            out += body
        if self.path:
            url = base_url.rstrip("/") + self.path
            out.append("")
            out.append(f'👉 <a href="{escape(url, quote=True)}">{e(self.link)}</a>' if html else f"{self.link}{colon}{url}")
        return "\n".join(out)

    def localized(self) -> "Card":
        """This card in the interface language (the card itself when that is Chinese). Names of companies and postings, and
        anything a website or the AI wrote, stay as they are: only the program's own wording is translated."""
        from . import i18n

        to = i18n.lang()
        if to == "zh":
            return self
        t = lambda x: i18n.tr(x, to)  # noqa: E731
        return replace(self, heading=t(self.heading), fields=[(t(k), t(v) if isinstance(v, str) else v) for k, v in self.fields], items=[t(i) for i in self.items],
                       items_title=t(self.items_title), detail=i18n.tr_lines(self.detail, to), hint=t(self.hint), link=t(self.link))

    def html(self, base_url: str) -> str:
        return self._blocks(True, base_url)

    def plain(self, base_url: str) -> str:
        return self._blocks(False, base_url)


def _cut(s: str, n: int) -> str:
    s = str(s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# --- task started ------------------------------------------------------------------------

def discover_started(sources: int) -> Card:
    return Card("🔎", "开始扫描岗位", fields=[("来源", f"{sources} 个")])


def execute_started(title: str, *, ats: str, policy: str, pages: int = 0, reasons: list[str] | None = None) -> Card:
    how = "填好后由你点击提交" if policy == "manual" else "核对无误后自动提交"
    if policy == "manual" and reasons:
        how += "（" + "；".join(reasons[:2]) + "）"
    return Card("▶️", "开始填写申请", title, fields=[("系统", ats), ("页数", str(pages) if pages else ""), ("提交方式", how)])


# --- task result -------------------------------------------------------------------------

def discover_done(total: dict[str, int], new_by_source: dict[str, int], errors: dict[str, str]) -> Card:
    c = Card("🔎", "岗位扫描完成", path="/jobs", link="查看岗位列表", inline=True)
    c.fields = [("读到", str(total["read"]) if total.get("read") else ""), ("符合条件", str(total["seen"])), ("新增", str(total["new"])), ("重新上架", str(total["back"]) if total["back"] else ""), ("已下线", str(total["offline"]) if total["offline"] else "")]
    c.items = [f"{name}　+{n}" for name, n in sorted(new_by_source.items(), key=lambda x: -x[1])[:8] if n]
    if errors:
        # sources that failed for the same reason are named together: eight boards of one service turned away by its
        # security check are one thing to know, not eight
        said: dict[str, list[str]] = {}
        for k, v in errors.items():
            why = "需要你登录（见待办）" if v.startswith("needs login") else "网站拒绝自动访问（见待办）" if "blocked by the site" in v else _cut(v, 80)
            said.setdefault(why, []).append(k)
        c.detail = "未能读取的来源：\n" + "\n".join(f"{'、'.join(names)}：{why}" for why, names in said.items())
        if any("安全检查拒绝" in why for why in said):
            c.hint = "被安全检查拒绝的来源和登录无关：对方的防护不接受这台电脑当前的网络出口（常见于代理或 VPN）。几小时内不会再去请求它们。"
    if not total["new"] and not errors:
        c.hint = "没有新岗位。"
    return c


def submitted(title: str, *, evidence: str, auto: bool = False, note: str = "") -> Card:
    c = Card("✅", "申请已提交", title, path="/jobs", link="查看岗位")
    c.fields = [("方式", "自动通过并提交" if auto else ""), ("备注", "网站显示此前已申请过" if note == "already applied" else "")]
    if evidence:
        c.detail = "确认页：" + _cut(evidence, 220)
    return c


def submit_unknown(title: str, *, said: str = "") -> Card:
    return Card("❓", "提交结果待确认", title, detail=_cut(said, 300), hint="点过提交，但没有看到提交成功的页面。不要重新填写：先等确认邮件，或在待办里现在就查。",
                path="/todos", link="打开待办")


def failed(title: str, *, error: str) -> Card:
    return Card("❌", "申请没有提交", title, detail=_cut(error, 400), hint="没有提交任何内容。原因和下一步见待办。", path="/todos", link="打开待办")


def task_failed(kind: str, error: str) -> Card:
    what = {"revise": "按批注修改草案", "recon": "读取表单并生成草案"}.get(kind, kind)
    return Card("⚠️", f"{what}没有完成", detail=_cut(error, 400), hint="草案没有被改动。", path="/runs", link="查看任务记录")


def second_factor(site: str, method: str) -> Card:
    return Card("📱", f"请在手机上批准 {method}", site, hint=f"程序正在登录 {site}，账号密码已经输入；现在等你在手机上批准，最多等 3 分钟。不是你发起的登录也会出现在这里：那就不要批准。")


def registered(key: str) -> Card:
    return Card("🆕", "已注册账号", key, hint="密码保存在本机凭据管理器里。", path="/accounts", link="查看账号")


def session_saved(key: str, *, credentials: bool) -> Card:
    return Card("🔑", "登录状态已保存", key, fields=[("密码", "已一并保存" if credentials else "")], path="/accounts", link="查看账号")


def tailored(title: str, *, focus: str, problems: list[str]) -> Card:
    if problems:
        return Card("📄", "定制简历没有通过检查", title, hint="；".join(problems)[:300] + "。申请会用你上传的原版简历。", path="/files", link="打开材料库")
    return Card("📄", "定制简历写好了", title, hint=focus[:300], path="/files", link="打开材料库")


def gmail_authorized() -> Card:
    return Card("📧", "Gmail 只读授权完成", hint="之后会定时读取与申请有关的邮件，不会发送或修改任何邮件。")


# --- status update -----------------------------------------------------------------------

def high_scores(rows: list[dict[str, Any]]) -> Card:
    """rows: {score, company, title, deadline}"""
    c = Card("⭐", f"{len(rows)} 个新的高分岗位", path="/jobs", link="查看岗位列表", hint="已排队生成申请草案。")
    for r in rows[:12]:
        dl = f"　截止 {r['deadline']}" if r.get("deadline") else ""
        c.items.append(f"{r['score']:g}　{r['company']} · {_cut(r['title'], 60)}{dl}")
    if len(rows) > 12:
        c.items.append(f"……另有 {len(rows) - 12} 个")
    return c


def auto_approved(title: str, draft_id: int) -> Card:
    return Card("⚡", "草案自动通过", title, hint="符合全部自动通过条件，已进入执行。", path=f"/drafts/{draft_id}", link="查看草案")


def drifted(title: str, changes: list[str]) -> Card:
    return Card("🔁", "申请表有变化", title, items=[_cut(x, 90) for x in changes[:8]],
                hint="正在重新读取表单。已审批的答案会沿用，稍后只需补审变化的部分。", path="/drafts", link="查看草案")


MAIL = {
    "confirmation": ("📬", "收到申请确认"),
    "rejection": ("📭", "申请未通过"),
    "interview": ("🎉", "面试邀请"),
    "assessment": ("🧪", "在线测评"),
    "offer": ("🏆", "录用通知"),
    "info_request": ("❓", "对方需要补充信息"),
}


# What an e-mail says ABOUT an interview, an assessment or an offer when it does not announce one (mail.EVENTS).
MAIL_EVENT = {
    ("interview", "cancelled"): ("⚠️", "面试被取消"), ("interview", "changed"): ("🗓️", "面试安排有变化"), ("interview", "reminder"): ("⏰", "面试提醒"),
    ("assessment", "cancelled"): ("⚠️", "在线测评被取消"), ("assessment", "changed"): ("🗓️", "在线测评有变化"), ("assessment", "reminder"): ("⏰", "在线测评提醒"),
    ("offer", "cancelled"): ("⚠️", "录用被撤回"), ("offer", "changed"): ("📝", "录用条件有更新"), ("offer", "reminder"): ("⏰", "录用通知待回复"),
}


def mail_label(category: str, event: str = "new") -> tuple[str, str]:
    """(icon, heading) for an e-mail: by what it is about and what it says about it."""
    return MAIL_EVENT.get((category, event)) or MAIL.get(category, ("✉️", category or "收到新邮件"))


def mail_update(category: str, title: str, summary: str, *, new_status: str = "", event: str = "new") -> Card:
    icon, heading = MAIL_EVENT.get((category, event)) or MAIL.get(category, ("✉️", "收到新邮件"))
    hint = ("请查看原邮件，确认是否需要重新安排或回复。" if event == "cancelled" and (category, event) in MAIL_EVENT
            else "请尽快查看原邮件并回复。" if category in ("interview", "assessment", "offer", "info_request") else "")
    return Card(icon, heading, title, fields=[("状态更新为", new_status)], detail=_cut(summary, 300), hint=hint, path="/jobs", link="查看岗位")


def quota_low(name: str, lines: list[tuple[str, str]], *, out: bool, backup: str, primary: bool) -> Card:
    if backup:
        hint = (f"接下来会自动改用备用服务：{backup}。" if out else f"用完后会自动改用备用服务：{backup}。") if primary else "这是一个备用服务；轮到它时如果还没恢复，会跳到下一个。"
    else:
        hint = "没有设置备用服务：用完后需要 AI 的任务会停下来，等额度恢复再继续。可以在“设置 → AI 模型”里加一个备用。"
    return Card("⛔" if out else "⚠️", "AI 额度用完了" if out else "AI 额度快用完了", fields=[("服务", name), *lines], hint=hint, path="/settings", link="打开设置")


def llm_switched(frm: str, to: str, why: str, until: str) -> Card:
    reason = ("用量额度用完了" if re.search(r"usage limit|limit reached|额度|quota|欠费|billing", why, re.I) else "请求太频繁，被限流了" if re.search(r"rate.?limit|429", why, re.I)
              else "登录或 key 失效了" if re.search(r"login|key|authenticat|拒绝", why, re.I) else "暂时连不上或出错了")
    return Card("🔁", "AI 服务已切换到备用", fields=[("原来用的", frm), ("现在用的", to), ("原因", reason)],
                hint=(f"{until} 之后会再试原来的服务，" if until else "") + "恢复后自动切回；不需要你操作。", path="/settings", link="打开设置")


# --- to-do -------------------------------------------------------------------------------

# kind -> (icon, heading, hint)
TODO = {
    "answer": ("✍️", "有问题需要你回答", "回答后草案才能进入审批。"),
    "review": ("📝", "草案等你审批", "逐项看一遍要填的内容，通过后才会开始填写。"),
    "takeover": ("🔐", "需要你登录", "在待办里点“去登录”，在弹出的窗口里完成登录，登录状态会自动保存。"),
    "blocked": ("🚧", "这个网站程序操作不了", "申请页在程序的浏览器里打不开或点不动。可以自己打开岗位页面投递，然后在待办里点“我已经提交了”。"),
    "login": ("🔐", "需要你登录", "在待办里点“去登录”，在弹出的窗口里完成登录。"),
    "captcha": ("🤖", "需要人工验证", "网站要求人机验证，这一步只能由你完成。"),
    "submit": ("👆", "已填好，等你提交", "请在弹出的浏览器窗口里检查一遍，然后点击提交。窗口会保留约 20 分钟。"),
    "submit_incomplete": ("⚠️", "还没填完，需要你接手", "有几处驱动和 AI 都没能填好，已经在待办里逐项列出。请在弹出的浏览器窗口里处理后再提交。窗口会保留约 20 分钟。"),
    "failed": ("❌", "申请没有提交", "没有提交任何内容。"),
    "driver_patch": ("🛠", "驱动补丁建议", "agent 已替驱动填完这一页；这是给之后修改驱动用的建议，不影响本次申请。"),
    "driver": ("🧪", "驱动巡检发现问题", "在修好之前，这个系统的申请可能会失败。"),
    "config": ("⚙️", "配置需要处理", ""),
    "mail_unmatched": ("📨", "邮件没能关联到岗位", "程序会先到雇主网站上查是哪个申请；查不到的话，请在待办里指定。"),
}


def todo(kind: str, title: str, body: str = "", *, payload: dict[str, Any] | None = None) -> Card:
    icon, heading, hint = TODO.get("submit_incomplete" if kind == "submit" and (payload or {}).get("incomplete") else kind, ("🔔", "需要你处理", ""))
    did = (payload or {}).get("draft_id")
    path, link = (f"/drafts/{did}", "打开草案") if kind in ("answer", "review") and did else ("/todos", "打开待办")
    return Card(icon, heading, title, detail=_cut(body, 500) if body else "", hint=hint, path=path, link=link)


def draft_ready(title: str, draft_id: int, *, answers: int, files: list[str], why_not_auto: list[str]) -> Card:
    c = todo("review", title, payload={"draft_id": draft_id})
    c.fields = [("要填写", f"{answers} 项"), ("要上传", "、".join(files))]
    c.items = [WHY_NOT_AUTO.get(x, x) for x in why_not_auto if x != "enabled"][:4]
    c.items_title = "没有自动通过的原因："
    return c


WHY_NOT_AUTO = {
    "no_unresolved": "有问题还没有答案",
    "all_high_from_rules": "有答案是模型推断的，不是来自已确认的规则或资料",
    "no_new_sensitive": "有敏感问题的答案还没被你确认过",
    "cover_letter_ok": "这次新写了求职信",
    "score_ok": "岗位评分低于自动通过的门槛",
    "driver_proven": "这个系统连续成功提交的次数还不够",
    "session_ready": "这个网站还没有可用的登录状态",
    "no_unusual_notes": "草案里有需要你留意的备注",
    "revised_by_user": "草案被你修改过",
}


def test() -> Card:
    return Card("✅", "AutoApply 通知已接通", hint="之后的任务进度、待办和申请状态会发到这里。")
