"""Giving a driver the program wrote back to the project, so that other people's copies can fill that site too.

When a site's driver (improve.py: written after the first application that went through there) has held up in its
trial and is in effect, the applicant is asked - once per driver - whether to report it to the project as an issue.

The program sends nothing by itself. Saying yes opens GitHub's own "new issue" page in the applicant's browser with
the text filled in: they read it there, and it is theirs to submit, under their own GitHub account. That needs no
access to their account, and what leaves the computer is exactly what they see.

What the text holds: the site's address, the application system, the program's version, what the revision does and
why, and the revision itself (a recipe, or a plugin's code). A revision never holds an answer or anything from the
profile (improve.py's rules; learned.py's gate) - only how the form is worked.

Setting ``learned.share``:
    ask     a card asks each time (the default)           "this time" / "always" / "not this time" / "never"
    always  the card comes with the issue ready to open; nothing is asked
    never   nothing is offered
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from . import db, learned, sites

CHOICES = ("once", "always", "skip", "never")
URL_LIMIT = 7000            # GitHub refuses a longer address; what does not fit is pasted by hand (the card says so)


def preference() -> str:
    p = str(db.get_setting("learned.share") or "ask")
    return p if p in ("ask", "always", "never") else "ask"


def repo() -> str:
    r = str(db.get_setting("update.repo") or "")
    return r if re.fullmatch(r"[\w.-]+/[\w.-]+", r) else ""


def issue(rev: dict[str, Any]) -> dict[str, Any]:
    """The issue for a revision: {"title", "body", "url", "whole"}; "whole" is False when the text had to be cut to fit
    an address (the full text is then in the body, to be pasted)."""
    host = sites.name(str(rev.get("target") or ""))
    text = learned.content(rev)
    lang = "python" if rev.get("kind") == "plugin" else "json"
    title = f"Learned driver: {host}"
    head = (f"A copy of AutoApply wrote this for a site it had no driver for, and it held up in its trial runs.\n\n"
            f"- Site: `{host}`\n- Kind: {rev.get('kind')}\n- Program version: {rev.get('version') or '?'}\n"
            f"- Runs it held up in: {sum(1 for t in rev.get('trials') or [] if t.get('used') and t.get('ok'))}\n\n"
            f"**What it does**: {rev.get('title') or ''}\n\n**Why**: {rev.get('why') or ''}\n\n")
    body = f"{head}```{lang}\n{text}\n```\n"
    base = f"https://github.com/{repo()}/issues/new?labels=learned-driver&title={quote(title)}&body="
    whole = len(base) + len(quote(body)) <= URL_LIMIT
    sent = body
    if not whole:
        room = text
        while room and len(base) + len(quote(f"{head}```{lang}\n{room}\n```\n\n_(cut to fit the address: the whole text is to be pasted here)_\n")) > URL_LIMIT:
            room = room[:int(len(room) * 0.8)]
        sent = f"{head}```{lang}\n{room}\n```\n\n_(cut to fit the address: the whole text is to be pasted here)_\n"
    return {"title": title, "body": body, "url": base + quote(sent) if repo() else "", "whole": whole}


def offer(rev: dict[str, Any]) -> bool:
    """A site's driver has held up and is in effect: ask whether to report it (unless the applicant said never, it
    was offered before, or there is no project to report to). True when a card was made."""
    if rev.get("origin") != "driver" or rev.get("status") != "active" or rev.get("shared") or preference() == "never" or not repo():
        return False
    from . import notify

    ready = preference() == "always"
    host = sites.name(str(rev.get("target") or ""))
    learned._update(rev["id"], shared="offered")
    notify.add_todo("share", f"把 {host} 的驱动分享给其他用户？" if not ready else f"{host} 的驱动可以分享了",
                    body="程序为这个网站写的驱动已经在试用里表现正常。把它作为 issue 提交到项目仓库，其他人的程序以后也能直接填这个网站。"
                         "提交的内容只有：网站地址、驱动本身（表单怎么操作）和程序版本，不含你的任何答案或个人资料。"
                         "点“提交”会在你的浏览器里打开 GitHub 的新建 issue 页面，内容已填好，由你确认后用自己的账号提交。",
                    ref=f"learned:{rev['id']}:share", payload={"id": rev["id"], "host": host, "ready": ready})
    return True


def decide(rev_id: str, choice: str) -> dict[str, Any]:
    """The applicant's answer to the card. once | always: the issue to open. skip | never: nothing. always and never
    are also kept as the preference for the drivers that follow."""
    if choice not in CHOICES:
        raise ValueError(choice)
    rev = learned.get(rev_id)
    if rev is None:
        raise KeyError(rev_id)
    from . import notify

    if choice in ("always", "never"):
        db.set_setting("learned.share", choice)
    out: dict[str, Any] = {"choice": choice, "preference": preference()}
    if choice in ("once", "always"):
        out.update(issue(rev))
        learned._update(rev_id, shared="opened")
    else:
        learned._update(rev_id, shared="declined")
    notify.close_todos("share", f"learned:{rev_id}:share")
    if choice == "never":       # nothing is offered from here on: the cards that were waiting go too
        for other in learned.revisions():
            if other.get("shared") == "offered":
                learned._update(other["id"], shared="declined")
                notify.close_todos("share", f"learned:{other['id']}:share")
    return out
