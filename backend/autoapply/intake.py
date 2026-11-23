"""Intake rules: which postings from a source are stored at all.

Career sites list thousands of roles. Storing and scoring all of them would bury the relevant ones and
spend model quota on roles that were never candidates. These rules are cheap text checks applied to
every posting *before* it is stored; what passes is then read and scored by the model as before.

A posting is kept when all of these hold (each rule is skipped when its list is empty):
  1. the title contains one of ``intake.title_any``           (the kind of role: intern, co-op, ...)
  2. the title contains one of ``intake.title_role_any``      (the field: software, engineer, ...)
  3. the title contains none of ``intake.title_none``         (senior, manager, PhD, ...)
  4. the location is in one of ``intake.countries`` - or the location is unknown
  5. it was posted within ``intake.max_age_days`` - or the date is unknown

Sources in ``intake.exempt_sources`` (PD Portal, links you add by hand) are never filtered: someone
already chose those postings for you.
"""

from __future__ import annotations

from .say import say as T

import re
from datetime import date, datetime
from typing import Any, Iterable, Iterator

from . import db

REASONS = {"kind": T("server.intake.notTheKindOf"), "role": T("server.intake.wrongDirection"), "excluded": T("server.intake.titleContainsAnExcluded"), "country": T("server.intake.notInYourChosen"), "old": T("server.intake.postedTooLongAgo")}

_CA_PROV = r"(?:BC|ON|QC|AB|MB|SK|NS|NB|NL|PE|YT|NT|NU)"
_CA_CITY = r"vancouver|toronto|waterloo|montr[eé]al|ottawa|calgary|edmonton|burnaby|richmond|kitchener|markham|mississauga|victoria|winnipeg|halifax|qu[eé]bec"
_US_STATE = r"(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)"
COUNTRY_PATTERNS = {
    "CA": rf"\bcanada\b|\bCAN\b|,\s*{_CA_PROV}\b(?!\s*,\s*US)|\b(?:{_CA_CITY})\b|\b(?:ontario|british columbia|alberta|manitoba|saskatchewan|nova scotia)\b",
    "US": rf"\bunited states\b|\bU\.?S\.?A?\b|,\s*{_US_STATE}\b(?!\s*,\s*CAN)|\bUS,\s*{_US_STATE}\b",
}
# other countries: by name or a well-known city; matched case-insensitively (see countries_of)
COUNTRY_PATTERNS.update({
    "GB": r"\bunited kingdom\b|\bengland\b|\bscotland\b|\bwales\b|\b(?:london|manchester|edinburgh|birmingham|bristol|oxford|leeds|glasgow)\b|,\s*UK\b|\bGBR\b",
    "AU": r"\baustralia\b|\b(?:sydney|melbourne|brisbane|perth|canberra|adelaide)\b|\bAUS\b",
    "DE": r"\bgermany\b|\bdeutschland\b|\b(?:berlin|munich|münchen|hamburg|frankfurt|stuttgart|cologne|köln)\b|\bDEU\b",
    "SG": r"\bsingapore\b|\bSGP\b",
    "CN": r"\bchina\b|\b(?:beijing|shanghai|shenzhen|guangzhou|hangzhou|chengdu|nanjing|suzhou)\b|中国|北京|上海|深圳|广州|杭州",
    "HK": r"\bhong kong\b|\bHKG\b|香港",
    "FR": r"\bfrance\b|\b(?:paris|lyon|toulouse|marseille|lille|nantes)\b|\bFRA\b",
    "NL": r"\bnetherlands\b|\bnederland\b|\b(?:amsterdam|rotterdam|eindhoven|utrecht|the hague|den haag)\b|\bNLD\b",
    "IE": r"\bireland\b(?!,?\s*northern)|\b(?:dublin|cork|galway|limerick)\b|\bIRL\b",
    "ES": r"\bspain\b|\bespaña\b|\b(?:madrid|barcelona|valencia|seville|sevilla)\b|\bESP\b",
    "IT": r"\bitaly\b|\bitalia\b|\b(?:milan|milano|rome|roma|turin|torino|bologna)\b|\bITA\b",
    "SE": r"\bsweden\b|\b(?:stockholm|gothenburg|göteborg|malmö)\b|\bSWE\b",
})


def _has(text: str, kw: str) -> bool:
    """Whole-word match that also accepts a plural ("intern" matches "Interns" but not "internal")."""
    kw = kw.strip()
    if not kw:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(kw.lower())}(?:s|ship|ships)?(?![a-z0-9])", text.lower()) is not None


def countries_of(location: str) -> set[str]:
    """Country codes found in a location string (several places may be listed, separated by ';' or '·')."""
    out = set()
    for part in re.split(r"[;·|]", location or ""):
        part = part.strip()
        if not part:
            continue
        bits = [b.strip() for b in part.split(",")]   # "City, Region, CC": the last token is the country
        m = re.fullmatch(r"([A-Z]{2,3})", bits[2]) if len(bits) == 3 and bits[0] and bits[1] else None
        if m:
            cc = {"USA": "US", "CAN": "CA", "UK": "GB", "GBR": "GB", "AUS": "AU", "DEU": "DE", "SGP": "SG", "CHN": "CN", "HKG": "HK"}.get(m.group(1), m.group(1))
            if cc in COUNTRY_PATTERNS:
                out.add(cc)
            continue
        for code, pat in COUNTRY_PATTERNS.items():
            if re.search(pat, part, 0 if code == "US" else re.I) or (code == "US" and re.search(r"\bunited states\b", part, re.I)):
                out.add(code)
    return out


def rules() -> dict[str, Any]:
    st = db.all_settings()
    return {k: st[f"intake.{k}"] for k in ("enabled", "title_any", "title_role_any", "title_none", "countries", "max_age_days", "exempt_sources")}


def title_ok(title: str, r: dict[str, Any]) -> str:
    """'' when the title passes, else the reason key."""
    if r["title_any"] and not any(_has(title, k) for k in r["title_any"]):
        return "kind"
    if r["title_role_any"] and not any(_has(title, k) for k in r["title_role_any"]):
        return "role"
    if any(_has(title, k) for k in r["title_none"] or []):
        return "excluded"
    return ""


def check(row: dict[str, Any], r: dict[str, Any] | None = None) -> str:
    """'' when the posting should be stored, else the reason key."""
    r = r or rules()
    if not r["enabled"] or row.get("source") in (r["exempt_sources"] or []):
        return ""
    why = title_ok(row.get("title", ""), r)
    if why:
        return why
    loc = row.get("location") or ""
    if r["countries"] and loc.strip():
        found = countries_of(loc)
        remote_only = loc.strip().lower() == "remote"
        if not remote_only and not (found & set(r["countries"])):
            return "country"
    if r["max_age_days"] and row.get("posted"):
        try:
            if (date.today() - datetime.strptime(row["posted"][:10], "%Y-%m-%d").date()).days > int(r["max_age_days"]):
                return "old"
        except ValueError:
            pass
    return ""


# --- who a posting is for ----------------------------------------------------------------------------------------
# A co-op portal lists every faculty's postings, and each says which programmes it is for ("Targeted Co-op Programs:
# Civil, Integrated ..."; "Open To All Majors: No"). That is the posting's own statement - not a matter of how its title
# is worded - so it holds for every source, the exempt ones included, and needs no model: a posting for other
# programmes is set aside before it is scored.

_NOT_A_FIELD = {"master", "masters", "bachelor", "of", "in", "and", "the", "for", "engineering", "science", "applied", "program", "programs", "programme",
                "ubc", "okanagan", "vancouver", "meng", "basc", "eece", "design", "co", "op", "coop", "student", "students", "year", "university"}


def _field_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) > 2 and w not in _NOT_A_FIELD}


def targeted(text: str) -> tuple[bool | None, list[str]]:
    """What a posting says about who it is for: (open to all majors - None when it does not say, the programmes it names)."""
    text = text or ""
    m = re.search(r"Open To All Majors:\s*(Yes|No)\b", text, re.I)
    open_to_all = None if m is None else m.group(1).lower() == "yes"
    programs: list[str] = []
    m = re.search(r"Targeted Co-op Programs:(.*)", text, re.S | re.I)
    if m:
        for line in m.group(1).splitlines():
            line = line.strip()
            if not line or line.lower() == "view targeted programs":
                continue
            if ":" in line or len(line) > 80 or re.match(r"^[A-Z][A-Z &/-]{8,}$", line):      # the next field ("Start Date: ..."), or the next section's heading
                break
            if line not in programs:
                programs.append(line)
    return open_to_all, programs[:40]


def my_fields() -> set[str]:
    """The applicant's field(s) of study as words: what they set (intake.programs), else the field of the programme
    they are in - the first entry of the profile's Education section, written "institution, degree, field, dates": the
    part just before the dates. Nothing is guessed from the rest of the section (an earlier degree, notes)."""
    given = [str(x) for x in (db.get_setting("intake.programs") or []) if str(x).strip()]
    if given:
        return {w for x in given for w in (_field_words(x) or {x.strip().lower()})}
    from . import knowledge

    return _field_words(field_of_study(knowledge.read("profile") or ""))


def programmes() -> list[str]:
    """The applicant's programme(s) of study by name, for a site that lists postings by programme: what they set
    (intake.programs), else the field of the programme they are in (the profile's Education section)."""
    given = [str(x).strip() for x in (db.get_setting("intake.programs") or []) if str(x).strip()]
    if given:
        return given
    from . import knowledge

    mine = field_of_study(knowledge.read("profile") or "")
    return [mine] if mine else []


def field_of_study(profile: str) -> str:
    """"Computer Engineering" from "- University of X (City), Bachelor of Applied Science, Computer Engineering, Sept 2024 - ..."."""
    section = re.search(r"^## Education\b(.*?)(?=^## |\Z)", profile, re.S | re.M)
    first = re.search(r"^- (.+?)(?=^- |\Z)", section.group(1), re.S | re.M) if section else None
    if not first:
        return ""
    head = re.split(r"\b(?:19|20)\d\d\b", " ".join(first.group(1).split()))[0]          # up to the first year
    head = re.sub(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*$", "", head.strip().rstrip(",(- "), flags=re.I)
    parts = [p.strip() for p in head.split(",") if p.strip()]
    return parts[-1] if len(parts) >= 2 else ""


def not_for_me(text: str, mine: set[str] | None = None) -> str:
    """'' when the posting is (or may be) for the applicant; else, in words, whom it is for instead."""
    open_to_all, programs = targeted(text)
    if open_to_all or not programs:
        return ""
    mine = my_fields() if mine is None else mine
    if not mine or any(_field_words(p) & mine for p in programs):
        return ""
    names = "、".join(programs[:6]) + (" …" if len(programs) > 6 else "")
    return T("server.intake.forOtherProgrammes", p0=names)


def keeper(r: dict[str, Any] | None = None):  # noqa: ANN201
    """A cheap pre-check sources can call before fetching a posting's details."""
    r = r or rules()

    def keep(title: str, location: str = "") -> bool:
        return not check({"title": title, "location": location}, r)

    return keep


def apply(rows: Iterable[dict[str, Any]], stats: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield the rows to store; count the rest by reason in ``stats`` ({"read", "kept", "dropped": {reason: n}})."""
    r = rules()
    stats.update(read=0, kept=0, dropped={})
    for row in rows:
        stats["read"] += 1
        why = check(row, r)
        if why:
            stats["dropped"][why] = stats["dropped"].get(why, 0) + 1
            continue
        stats["kept"] += 1
        yield row
