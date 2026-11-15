"""User-facing wording for things the engine tracks with internal names.

The engine keeps tenant keys ("workday:tmx.wd3"), task kinds ("recon"), refs ("job:669") and raw
exception text. None of that belongs on screen. The API passes those through here so every page
shows a site by its employer's name, a task by what it does, and an error as one plain sentence -
with the raw text kept as collapsible "technical details" for debugging.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from . import db
from .models import Application, Draft, Job

ATS = {
    "workday": "Workday", "greenhouse": "Greenhouse", "ashby": "Ashby", "lever": "Lever", "pdportal": "UBC PD Portal",
    "generic": "公司官网", "oracle": "Oracle", "eightfold": "Eightfold", "workable": "Workable", "smartrecruiters": "SmartRecruiters",
    "icims": "iCIMS", "successfactors": "SAP SuccessFactors", "jazzhr": "JazzHR", "": "",
}
TASK = {
    "discover": "扫描新岗位", "score": "给岗位评分", "recon": "读取申请表、生成草案", "scout": "带着草案的答案读完后面的步骤", "tailor": "按岗位调整简历", "revise": "按你的意见修改草案", "reanswer": "重新回答草案里没答上的问题",
    "execute": "填写并提交申请", "mail": "检查邮箱", "canary": "自检",
}
TASK_STATUS = {"queued": ("排队中", ""), "running": ("进行中", "info"), "done": ("完成", "ok"), "failed": ("没完成", "bad"), "waiting_human": ("等你处理", "warn")}


def ats_name(ats: str) -> str:
    return ATS.get(ats or "", (ats or "").capitalize())


def site(tenant_key: str) -> dict[str, str]:
    """{"name": employer (or host), "system": ATS label} for a tenant key such as "workday:tmx.wd3"."""
    ats, _, tenant = (tenant_key or "").partition(":")
    name = ""
    with db.session() as s:
        if ats == "generic":
            rows = s.query(Job.company).filter(Job.apply_url.like(f"%{tenant}%")).all()
        elif ats == "pdportal":
            rows = []
            name = "UBC PD Portal"
        else:
            rows = s.query(Job.company).filter(Job.ats == ats, Job.tenant == tenant).all()
            if not rows:  # tenant "tmx.wd3" vs stored "tmx"
                rows = s.query(Job.company).filter(Job.ats == ats, Job.tenant == tenant.split(".")[0]).all()
        if rows:
            name = Counter(r[0] for r in rows if r[0]).most_common(1)[0][0]
    if not name:
        name = tenant.split(".")[0].upper() if ats == "workday" else tenant
    return {"name": name, "system": "" if ats == "pdportal" else ats_name(ats)}


_CJK = re.compile(r"[一-鿿]")
_RULES: list[tuple[str, str]] = [
    (r"ChatGPT.*(usage limit|额度已用完)|hit your usage limit", "ChatGPT 订阅的额度用完了，要等它重置。"),
    (r"Claude subscription usage limit", "Claude 订阅的额度用完了，要等它重置。"),
    (r"usage limit", "这家 AI 服务的额度用完了，要等它重置。"),
    (r"还没有安装 ChatGPT 接入组件", "ChatGPT 的接入组件还没有安装。"),
    (r"AI 服务的额度用完了或账户欠费", "这家 AI 服务的余额用完了或账户欠费。"),
    (r"拒绝了这个 API key|API key is missing or invalid", "API key 没填、填错了，或者没有权限。"),
    (r"连不上 AI 服务|cannot reach the Claude API", "连不上这家 AI 服务。检查网络和“设置 → 网络”。"),
    (r"还没有选模型", "这家服务还没有选模型。"),
    (r"subscription login is not usable|not logged in", "登录失效了，需要重新登录这家服务。"),
    (r"网站暂时打不开|SiteDown|HTTP 5\d\d|Server error '5\d\d|error page|empty page|could not open the posting|net::ERR|Page\.goto: Timeout|Site Maintenance",
     "网站暂时打不开，可能正在维护。稍后会自动重试，不需要你操作。"),
    (r"窗口已关闭或超时", "窗口关闭前没有看到“提交成功”的页面，所以不确定有没有提交。如果你已经点了提交，点“我已经提交了”。"),
    (r"岗位.{0,12}已关闭|找不到这个岗位|posting not found|no longer (open|accepting|available)|job_unavailable|not found on Ashby", "这个岗位在雇主官网上已经关闭或下线了。"),
    (r"captcha|human verification|人机验证", "网站要求做人机验证，这一步需要你本人完成。"),
    (r"already exists|already registered|已经注册过", "这个邮箱在该网站上已经注册过。请登录一次，之后程序会记住。"),
    (r"应该已经有账号", "你之前投过这家公司，应该已经有账号。请登录一次，登录状态和密码会保存下来。"),
    (r"Registration did not complete|registration failed|Registered, but signing in failed", "自动注册没有完成。你可以让它再试一次，或者自己登录。"),
    (r"verification e-?mail did not arrive|没有等到这封邮件|no verification e-mail", "没有收到网站发来的验证邮件。"),
    (r"没有接受邮件验证码", "网站没有接受邮件里的验证码。"),
    (r"Automatic login failed|Login did not succeed|Login failed twice|sign-in rejected", "用保存的密码自动登录没有成功，需要你登录一次。"),
    (r"session has expired|session expired", "登录已过期，需要你重新登录一次。"),
    (r"login required|No stored login|needs you to sign in|sign in yourself|This account needs", "这个网站需要先登录才能继续。"),
    (r"differ from the draft|mismatch", "填完后逐项核对，发现页面上有内容和草案不一致，所以没有提交。"),
    (r"form changed|drift", "申请表和生成草案时不一样了，已重新读取。"),
    (r"no confirmation after submit", "点了提交，但没有看到“提交成功”的页面。请到邮箱确认是否收到确认信。"),
    (r"could not determine the form structure", "没能读懂这个网站的申请表。"),
    (r"no résumé|No résumé", "还没有上传简历。"),
    (r"cover-letter|cover letter", "求职信没有生成成功。"),
    (r"interrupted|superseded", "这次运行被中断了（通常是因为重启）。"),
    (r"Locator\.|waiting for locator|TimeoutError|Timeout \d+ms|strict mode violation|is not an? <", "页面上没有出现程序预期的内容。可能是网站还没加载完，也可能是页面改版了。"),
    (r"KeyError|TypeError|AttributeError|ValueError|AssertionError|Traceback", "程序内部出错了，这次没有完成。"),
]


def explain(text: str | None) -> dict[str, str]:
    """One plain sentence for an error or status text, plus the raw text as detail when it adds anything."""
    raw = (text or "").strip()
    if not raw:
        return {"message": "", "detail": ""}
    m = re.match(r"^(confirmation|rejection|interview|assessment|offer|info_request): (.*)$", raw, re.S)
    if m:  # the latest e-mail about this application
        from .messages import MAIL

        return {"message": f"{MAIL[m.group(1)][1]}：{m.group(2)}", "detail": ""}
    for pat, msg in _RULES:
        if re.search(pat, raw, re.I):
            return {"message": msg, "detail": "" if raw == msg else raw}
    cjk = len(_CJK.findall(raw))
    if cjk >= 6 and not re.search(r"Error:|Exception|Locator|Call log", raw):
        return {"message": raw, "detail": ""}
    if not re.search(r"Error|Exception|Traceback|Timeout|failed|Locator|refused|invalid", raw, re.I):
        return {"message": raw, "detail": ""}  # a plain status note, not a failure
    return {"message": "这一步没有完成。", "detail": raw}


_NOTES: list[tuple[str, str]] = [
    (r"^Proposed rule \(confirm to save to profile\): (.*)$", r"建议记住这条规则（你确认后会存进个人资料）：\1"),
    (r"^Form changed since the approved draft v(\d+): (\d+) new or changed question\(s\) need review; the other answers are carried over\.$",
     r"申请表和你批准第 \1 版草案时不一样了：有 \2 个新增或变化的问题需要你看，其余答案沿用。"),
    (r"^(?:Required file|File) '(.+?)' has no matching document\.( No résumé has been uploaded yet.*)?$", r"「\1」这一栏没有可以上传的文件。"),
    (r"^The form has no transcript field; the transcript goes in the Cover Letter slot\.$", "表单上没有成绩单栏，成绩单会放在求职信那一栏上传。"),
    (r"^Cover letter still has open issues: (.*)$", r"求职信还有没解决的问题：\1"),
    (r"^The later steps of this form were read by filling in this draft's answers step by step, up to the review page; nothing was submitted\. (\d+) answer\(s\) were added from your profile; "
     r"(\d+) answer\(s\) the employer's site already holds were read into the draft; (\d+) question\(s\) need your answer\.$",
     r"后面的步骤已经读完：程序带着这份草案的答案一步步填到了确认页，没有提交。按你的资料补了 \1 个答案，读回了雇主网站上已经存着的 \2 个答案，有 \3 个问题需要你回答。"),
    (r"^The later steps of this form were read by filling in this draft's answers step by step, up to the review page; nothing was submitted\. (\d+) answer\(s\) were added from your profile; (\d+) question\(s\) need your answer\.$",
     r"后面的步骤已经读完：程序带着这份草案的答案一步步填到了确认页，没有提交。按你的资料补了 \1 个答案，有 \2 个问题需要你回答。"),
    (r"^Reading the later steps stopped at \"(.*)\": (\d+) question\(s\) there need your answer\. Answer them and the reading goes on from there; nothing was submitted\.$",
     r"读后面的步骤时停在了「\1」：那里有 \2 个问题需要你回答。回答之后会从那里接着读；没有提交。"),
    (r"^Reading the later steps did not work this time; .*$", r"这次没能读到后面的步骤；填表时会读到，问到的新问题会加进这份草案。"),
    (r"^Steps of this form that could not be read yet: (.*?)\. The form shows them only after the earlier steps are filled; .*$",
     r"这张表有几步在生成草案时还读不到：\1。要先填完前面的步骤，表单才显示它们；第一次填表时会读到，问到的新问题会加进这份草案，需要你回答的会退回给你。"),
]
_BASIS: list[tuple[str, str]] = [
    (r"^carried over from approved draft v(\d+)$", r"沿用你批准过的第 \1 版草案"),
    (r"^revised per comment: (.*)$", r"按你的修改意见：\1"),
    (r"^materials list$", "从你上传的材料里选的"),
    (r"^no document for this slot$", "没有对应的文件"),
    (r"^edited by the user$|^user edit$", "你手动填写的"),
    (r"^answer cache.*$|^cache.*$", "以前回答过同样的问题"),
]


def _map(text: str, table: list[tuple[str, str]]) -> str:
    for pat, rep in table:
        if re.search(pat, text or "", re.S):
            out = re.sub(pat, rep, text, flags=re.S)
            if "No résumé has been uploaded" in (text or ""):
                out += "还没有上传简历，请到“个人资料 → 材料清单”上传。"
            return out
    return text or ""


def note(text: str) -> str:
    """A draft note in the user's language (the stored text stays as the engine wrote it)."""
    return _map(text, _NOTES)


def basis(text: str) -> str:
    return _map(text, _BASIS)


APP_STATUS = {
    "recon": "正在读取申请表", "revising": "正在按你的意见修改", "needs_input": "有问题等你回答", "draft_ready": "等你审批",
    "approved": "已批准，排队填写", "executing": "正在填写", "drifted": "申请表有变化，重新读取中", "ready_to_submit": "填好了，还没确认提交",
    "needs_human": "需要你处理", "failed": "没有提交成功", "submitted": "已提交", "confirmed": "已收到确认信", "assessment": "笔试 / OA / VA",
    "interview": "面试", "offer": "收到 Offer", "rejected": "已被拒", "withdrawn": "不投了",
}
REVIEW = {"pending": "等你审批", "approved": "已批准", "superseded": "已被新版本替代", "rejected": "已退回"}


def subject(ref: str) -> str:
    """What a task or run is about, in words: "job:669" -> "Bombardier · Intern, Software Developer"."""
    kind, _, rest = (ref or "").partition(":")
    ident = rest.split(":")[0]
    if kind in ("schedule", "manual", "unscored", ""):
        return {"schedule": "定时运行", "manual": "手动触发", "unscored": "新入库的岗位"}.get(kind, "")
    if kind == "account":
        st = site(rest)
        return f"{st['name']} 的账号"
    if kind == "config":
        return "设置"
    if not ident.isdigit():
        return ""
    with db.session() as s:
        job = None
        if kind == "job":
            job = s.get(Job, int(ident))
        elif kind in ("application", "confirm"):
            a = s.get(Application, int(ident))
            job = a.job if a else None
        elif kind == "draft":
            d = s.get(Draft, int(ident))
            job = d.application.job if d else None
        return f"{job.company} · {job.title}" if job else ""


def result_summary(kind: str, status: str, result: dict[str, Any] | None) -> str:
    r = result or {}
    if status != "done":
        return ""
    if kind == "discover":
        t = r.get("total") or {}
        errs = r.get("errors") or {}
        base = (f"读到 {t['read']} 个，" if t.get("read") else "") + f"符合条件 {t.get('seen', 0)} 个，新增 {t.get('new', 0)} 个" + (f"，下线 {t['offline']} 个" if t.get("offline") else "")
        return base + (f"；{len(errs)} 个来源没读到" if errs else "")
    if kind == "mail":
        if r.get("skipped"):
            return "Gmail 还没有授权，已跳过"
        return f"新邮件 {r.get('new_mail', 0)} 封，更新了 {r.get('status_updates', 0)} 个申请的状态" + (f"，{r['unmatched']} 封没对上岗位" if r.get("unmatched") else "")
    if kind == "score":
        return (f"评了 {r.get('scored', 0)} 个岗位" + (f"，{r['queued_for_draft']} 个高分岗位排队生成草案" if r.get("queued_for_draft") else "")
                + (f"；还有 {r['remaining']} 个没评，几分钟后接着评" if r.get("remaining") else "")) if "scored" in r else "已评分"
    if kind == "recon":
        return "草案已生成，等你审批" if r.get("draft_id") else ""
    if kind == "revise":
        return "已按你的意见生成新版本"
    if kind == "execute":
        return {"submitted": "已提交", "ready_to_submit": "已填好，但没有确认提交成功", "drifted": "申请表有变化，已重新读取", "failed": "没有提交",
                "needs_human": "需要你处理", "approved": "改为在可见窗口里重跑"}.get(str(r.get("status")), "")
    if kind == "canary":
        return "自检完成"
    return ""
