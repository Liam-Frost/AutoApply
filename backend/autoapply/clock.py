"""The applicant's clock.

Everything the program shows with a time - a deadline, an interview, a reminder - is on the applicant's own wall clock.
That is the computer's clock unless the applicant names a time zone (Settings: ``time.zone``, an IANA name), which they
do when the program runs somewhere else than they are (a server, a container) or when they travel.

An employer's mail says a time in ITS zone ("10:00 AM, Surrey local time"), or in the zone a scheduling tool converted it
to. `from_zone` turns such a time into the applicant's; the time zone database knows when each place changes its clocks,
so nothing here adds or subtracts hours by hand.
"""
from __future__ import annotations

import zoneinfo
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from . import db

# Places change their clocks' rules (British Columbia stopped changing its clocks in 2026): the rules that come with the
# program (the tzdata package, pinned and updated with each release) are used, not whatever the computer has.
try:
    import tzdata  # noqa: F401

    zoneinfo.reset_tzpath(to=())
except Exception:  # noqa: BLE001 - without the package the computer's own rules are what there is
    pass

APPLICANT = "applicant"      # what the mail reader says when a time is already the applicant's own


def system_zone() -> str:
    """The computer's time zone by name ("Asia/Shanghai"), or "" when it cannot be told."""
    try:
        import tzlocal

        return str(tzlocal.get_localzone_name() or "")
    except Exception:  # noqa: BLE001 - not installed, or a system that does not say: the offset is still known
        return ""


def valid(name: str) -> bool:
    try:
        ZoneInfo(str(name))
        return bool(name)
    except Exception:  # noqa: BLE001 - not a zone
        return False


def zone_name() -> str:
    """The applicant's zone by name: the one they set, else the computer's ("" when that has no name)."""
    chosen = str(db.get_setting("time.zone") or "").strip()
    return chosen if chosen and valid(chosen) else system_zone()


def _zone() -> ZoneInfo | None:
    chosen = str(db.get_setting("time.zone") or "").strip()
    return ZoneInfo(chosen) if chosen and valid(chosen) else None


def to_local(moment: datetime) -> datetime:
    """A moment (with its zone; without one it is UTC, as the program records moments) on the applicant's wall clock."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    z = _zone()
    return (moment.astimezone(z) if z is not None else moment.astimezone()).replace(tzinfo=None)


def now() -> datetime:
    """Now, on the applicant's wall clock."""
    z = _zone()
    return datetime.now(z).replace(tzinfo=None) if z is not None else datetime.now()


def today() -> date:
    return now().date()


def offset_minutes() -> int:
    """How far the applicant's clock is from UTC right now, in minutes."""
    z = _zone()
    off = (datetime.now(z) if z is not None else datetime.now().astimezone()).utcoffset()
    return int(off.total_seconds() // 60) if off is not None else 0


def from_zone(wall: datetime, zone: str) -> datetime | None:
    """A wall-clock time said in ``zone`` (an IANA name), on the applicant's wall clock. None when the zone is not one."""
    if not valid(zone):
        return None
    return to_local(wall.replace(tzinfo=ZoneInfo(zone)))
