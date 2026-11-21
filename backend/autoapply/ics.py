"""The calendar as a file other calendars read (iCalendar, RFC 5545): downloaded once from the calendar page, or
subscribed to at an address that a calendar program reads again by itself.

What leaves the program here is little: the title, the time, the link and one line of what it is about - never the
answers of a record or the text of a mail. The subscription address carries a token that can read this and nothing
else; it can be replaced (the old address stops working).

Times are written as the applicant's local wall clock without a zone ("floating"): an interview at 10:00 is at 10:00
in the calendar program of the same place. A whole-day item is a day. Each item's reminders go with it (VALARM), so
the calendar program reminds too.
"""
from __future__ import annotations

import hmac
import secrets as _random
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import agenda, alarms, db, i18n, secrets

TOKEN = "calendar_feed_token"
KIND_LABEL = {"deadline": "截止", "interview": "面试", "assessment": "测评", "offer": "Offer 答复", "info_request": "对方要补充信息", "contact": "联系", "own": "日程"}


def _esc(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Lines longer than 75 octets are folded (a line break and a space), without cutting a character in two."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > 75:
            out.append(cur)
            cur, size = " ", 1
        cur += ch
        size += n
    out.append(cur)
    return "\r\n".join(out)


def _trigger(before: int, all_day: bool) -> str:
    """How long before the start of the item (for a whole day: its midnight) the reminder goes off."""
    if all_day:
        h, m = alarms._morning()
        days = before // 1440 + (1 if before % 1440 else 0)
        minutes = days * 1440 - (h * 60 + m)
    else:
        minutes = before
    return f"-PT{minutes}M" if minutes >= 0 else f"PT{-minutes}M"


def build(items: list[dict[str, Any]], *, name: str = "AutoApply") -> str:
    base = str(db.get_setting("app.base_url")).rstrip("/")
    reminded = alarms.by_item([x["id"] for x in items])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AutoApply//Calendar//EN", "CALSCALE:GREGORIAN", f"X-WR-CALNAME:{_esc(name)}"]
    for x in items:
        if x.get("done"):
            continue
        start = datetime.fromisoformat(x["start"])
        what = i18n.tr(KIND_LABEL.get(x["kind"], "日程"))
        title = f"{what}：{x['subject'] or x['title']}" if x["kind"] == "deadline" else f"{what}：{x['title']}"
        lines += ["BEGIN:VEVENT", f"UID:{x['id']}@autoapply", f"DTSTAMP:{stamp}", f"SUMMARY:{_esc(title)}"]
        if x["all_day"]:
            lines += [f"DTSTART;VALUE=DATE:{start:%Y%m%d}", f"DTEND;VALUE=DATE:{start.date() + timedelta(days=1):%Y%m%d}"]
        else:
            lines += [f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{start + timedelta(minutes=30):%Y%m%dT%H%M%S}"]
        page = f"{base}/calendar?view=day&date={start:%Y-%m-%d}"
        lines.append(f"DESCRIPTION:{_esc(((x['subject'] + chr(10)) if x['subject'] and x['kind'] != 'deadline' else '') + page)}")
        lines.append(f"URL:{x['link'] or page}")
        for before in reminded.get(x["id"], []):
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(title)}", f"TRIGGER:{_trigger(before, x['all_day'])}", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


# --- the address to subscribe to ----------------------------------------------------------------------------------------
def token(*, new: bool = False) -> str:
    t = "" if new else secrets.get(TOKEN)
    if not t:
        t = _random.token_urlsafe(24)
        secrets.put(TOKEN, t)
    return t


def token_ok(given: str) -> bool:
    t = secrets.get(TOKEN)
    return bool(t) and hmac.compare_digest(given.encode(), t.encode())


def feed() -> str:
    """What a calendar program that subscribed reads: a month back and four months ahead, the kinds shown by default."""
    today = date.today()
    return build(agenda.items(today - timedelta(days=30), today + timedelta(days=120)))


def address() -> dict[str, Any]:
    """The address, and from where it works: a calendar program can read it only where the program can be reached."""
    base = str(db.get_setting("app.base_url")).rstrip("/")
    host = base.split("://")[-1].split("/")[0].split(":")[0].lower()
    local = host in ("127.0.0.1", "localhost", "::1", "[::1]") or not host
    return {"url": f"{base}/api/calendar/feed/{token()}.ics", "local_only": local}
