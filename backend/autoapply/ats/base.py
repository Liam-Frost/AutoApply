"""Shared types for ATS drivers: the form schema, the driver interface, errors.

A driver knows how to *operate* one ATS. It never decides *what* to answer;
answers come from ``answers.resolve`` and are passed in as plain values.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

SENSITIVE_PATTERNS = [
    (r"sponsor", "sponsorship"),
    (r"salary|compensation|pay expectation|desired (annual )?pay", "salary"),
    (r"intellectual property|patent|trademark|copyright", "ip"),
    (r"non-?compet|non-?disclosure|non-?solicit|restrictive covenant", "noncompete"),
    (r"gender|ethnic|race\b|racial|disab|veteran|indigenous|lgbt|pronoun|sexual orientation", "demographic"),
    (r"authorized to work|legally (entitled|eligible|permitted|authorized)|work permit|citizen|permanent resident", "work_auth"),
    (r"criminal|convict|background check", "background"),
    (r"\breferees?\b|\breferences?\b(?! (number|code|id|#))|recommender", "referee"),
    (r"notice period|current (salary|compensation|pay)", "salary"),
]


def sensitivity(label: str) -> str:
    low = label.lower()
    for pat, tag in SENSITIVE_PATTERNS:
        if re.search(pat, low):
            return tag
    return ""


def norm_question(label: str) -> str:
    """Normalise a question label for the answer cache."""
    t = re.sub(r"\s+", " ", label).strip().lower()
    t = re.sub(r"[*:]+$", "", t).strip()
    return t


def options_hash(options: list[str]) -> str:
    if not options:
        return ""
    return hashlib.sha1("|".join(sorted(o.strip().lower() for o in options)).encode()).hexdigest()[:12]


@dataclass
class Question:
    id: str  # stable key within the form (usually the field name)
    label: str
    type: str = "text"
    required: bool = False
    options: list[str] = field(default_factory=list)
    page: int = 0
    section: str = ""
    help: str = ""
    locator: dict[str, Any] = field(default_factory=dict)  # driver-specific hints
    depends_on: str = ""  # id of the question whose answer reveals this one
    accept_text: bool = False  # file question that also accepts pasted text
    searchable: bool = False  # a list that is searched or loads as one types: ``options`` are only its first entries, not all of its choices
    max_length: int = 0  # the most characters the form accepts for this answer (0 = no limit known); learned when the form refuses a longer one

    def key(self) -> tuple[str, str]:
        return norm_question(self.label), options_hash(self.options)


@dataclass
class FormSchema:
    ats: str
    tenant: str = ""
    job_ref: str = ""
    url: str = ""
    title: str = ""
    company: str = ""
    requires_login: bool = False
    source: str = "api"  # api | walk | agent
    pages: list[str] = field(default_factory=list)  # page titles, in order
    questions: list[Question] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FormSchema":
        d = dict(d)
        d["questions"] = [Question(**q) for q in d.get("questions", [])]
        return cls(**d)

    def fingerprint(self, page: int | None = None) -> str:
        """Hash of the structure that matters for drift detection."""
        items = [
            (q.page, norm_question(q.label), q.type, q.required, options_hash(q.options))
            for q in self.questions
            if page is None or q.page == page
        ]
        return hashlib.sha1(json.dumps(sorted(items)).encode()).hexdigest()[:16]

    def by_id(self) -> dict[str, Question]:
        return {q.id: q for q in self.questions}


def diff_schemas(draft: FormSchema, live: FormSchema, page: int | None = None) -> dict[str, list[dict[str, Any]]]:
    """Compare the reviewed schema against what the live form shows.

    Returns {"added": [...], "changed": [...], "removed": [...]} where only
    *required* additions and option/type changes count as blocking drift.
    """

    def keyed(s: FormSchema) -> dict[str, Question]:
        return {norm_question(q.label): q for q in s.questions if page is None or q.page == page}

    a, b = keyed(draft), keyed(live)
    added = [asdict(q) for k, q in b.items() if k not in a]
    removed = [asdict(q) for k, q in a.items() if k not in b]
    changed = []
    for k in a.keys() & b.keys():
        qa, qb = a[k], b[k]
        # Live inspection cannot always see options (custom dropdowns) or tell
        # text from textarea, so only compare what both sides actually know.
        fam = lambda t: "text" if t in ("text", "textarea", "date") else "choice" if t in ("select", "multiselect", "radio") else t  # noqa: E731
        type_changed = fam(qa.type) != fam(qb.type)
        opts_changed = bool(qa.options) and bool(qb.options) and options_hash(qa.options) != options_hash(qb.options)
        if type_changed or opts_changed:
            changed.append({"before": asdict(qa), "after": asdict(qb)})
    return {"added": added, "changed": changed, "removed": removed}


def blocking_drift(d: dict[str, list[dict[str, Any]]]) -> bool:
    return any(q.get("required") for q in d["added"]) or bool(d["changed"])


# --- errors --------------------------------------------------------------------


BUGS = (AttributeError, NameError, ImportError)


def tolerated(e: BaseException) -> None:
    """Called first in a handler that lets a failure pass ("the page is busy", "the control is not there yet"): what a
    page does may be let pass, a mistake in the program may not. A method the browser adapter does not have, a name
    that does not exist - these were swallowed by the same handlers, and showed up later as something else."""
    if isinstance(e, BUGS):
        raise e


class DriverError(Exception):
    """Structured failure the repair agent can act on."""

    def __init__(self, message: str, *, page: int | None = None, question: str = "", expected: str = "", seen: str = "") -> None:
        super().__init__(message)
        self.page, self.question, self.expected, self.seen = page, question, expected, seen

    def to_dict(self) -> dict[str, Any]:
        return {"message": str(self), "page": self.page, "question": self.question, "expected": self.expected, "seen": self.seen}


class SiteDown(DriverError):
    """The site itself is not answering (5xx, gateway error page, blank app shell). Not a login problem
    and not a driver bug: nothing is counted against the account and no one is asked to sign in."""


class NeedsHuman(Exception):
    """Login, CAPTCHA, MFA, or an existing account without stored credentials."""

    def __init__(self, reason: str, *, kind: str = "login", url: str = "", waits_for: str = "") -> None:
        super().__init__(reason)
        self.reason, self.kind, self.url = reason, kind, url
        self.waits_for = waits_for      # the card that was made for it ("account:idp:google"): what the task waits for


# the site says the account exists and its e-mail address has not been confirmed yet - after sign-up ("An email has been
# sent to you. Please verify your account.") or at a later sign-in ("Verify your account before you sign in")
UNCONFIRMED_RE = re.compile(r"verify your|verification (e-?mail|link)|not (yet |been )*(verified|activated|confirmed)|activate your (account|profile)|"
                            r"confirm your (e-?mail|account|address)|e-?mail (has been|was) sent to you", re.I)


class Unconfirmed(NeedsHuman):
    """The site will not sign this account in until its e-mail address is confirmed. Not the applicant's to do: the
    confirmation mail is in the mailbox the program reads (auth.confirm_address). A driver raises this from login()
    when the site says so; whoever signs in goes through the confirmation and signs in again."""


# the site says an application for this posting exists already: there is no form to fill, and nothing to send again
ALREADY_RE = re.compile(r"you(.ve| have) already (applied|submitted)|already (applied|submitted an application) (for|to) this|"
                        r"you(.ve| have) previously applied (for|to) this|application (has )?already (been )?(received|submitted)|你已(经)?申请过", re.I)


class AlreadyApplied(Exception):
    """The employer's site shows this posting as applied for. Whoever meets it - reading the form, walking it, filling
    it - raises this with what the site showed ({"url", "text"}); the application is then a sent one (lifecycle.applied_before)."""


# --- driver interface ----------------------------------------------------------


@dataclass
class JobRef:
    ats: str
    tenant: str  # board token / workday tenant / company slug
    job_id: str
    url: str
    host: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def tenant_key(self) -> str:
        return f"{self.ats}:{self.tenant}"


@dataclass
class PasswordPolicy:
    length: int = 20
    symbols: str = "!@#$%^&*"


class Driver(Protocol):
    ats: str
    requires_login: bool
    password_policy: PasswordPolicy

    def detect(self, url: str) -> JobRef | None: ...

    # --- schema
    def get_schema(self, ref: JobRef, page: Any | None, answers: dict[str, Any] | None = None) -> FormSchema: ...

    # --- execution (page is a Playwright sync Page)
    def open_application(self, page: Any, ref: JobRef) -> None: ...
    def live_questions(self, page: Any, page_index: int) -> list[Question]: ...
    def fill_page(self, page: Any, schema: FormSchema, page_index: int, answers: dict[str, Any]) -> None: ...
    def next_page(self, page: Any) -> bool: ...
    def read_back(self, page: Any, schema: FormSchema, page_index: int | None = None) -> dict[str, Any]: ...
    def submit(self, page: Any) -> None: ...
    def confirmation(self, page: Any) -> dict[str, Any] | None: ...
    def already_applied(self, page: Any, ref: JobRef) -> bool: ...

    # --- auth (only when requires_login)
    def is_logged_in(self, page: Any, ref: JobRef) -> bool: ...
    def login(self, page: Any, ref: JobRef, email: str, password: str) -> None: ...
    def register(self, page: Any, ref: JobRef, email: str, password: str) -> str: ...  # "ok" | "verify_email" | "exists"
    def login_url(self, ref: JobRef) -> str: ...


def host_is(host: str, domain: str) -> bool:
    """Is ``host`` that site or one of its subdomains? "jobs.ashbyhq.com" is ashbyhq.com; "notashbyhq.com" and
    "ashbyhq.com.evil.example" are not. Sites are told apart by this, never by looking for a name inside an address."""
    host, domain = (host or "").lower().split(":")[0].rstrip("."), domain.lower()
    return host == domain or host.endswith("." + domain)


def url_host(url: str) -> str:
    """The host of an address, lower case, without the port ('' when there is none)."""
    from urllib.parse import urlparse

    try:
        return (urlparse(url if "//" in (url or "") else f"https://{url}").hostname or "").lower()
    except ValueError:
        return ""


def values_equal(expected: Any, actual: Any) -> bool:
    """Loose comparison for read-back verification."""

    def n(v: Any) -> Any:
        if isinstance(v, bool):
            return v
        if isinstance(v, (list, tuple, set)):
            return sorted(n(x) for x in v)
        if v is None:
            return ""
        s = re.sub("[🀀-🫿☀-➿️]", "", str(v))  # flags and icons shown in front of an option
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s

    e, a = n(expected), n(actual)
    if e == a:
        return True
    if isinstance(e, str) and isinstance(a, str):
        # phone formatting, trailing slashes, masked file names
        de, da = re.sub(r"\D", "", e), re.sub(r"\D", "", a)
        if len(de) >= 7 and de and (de.endswith(da) or da.endswith(de)) and min(len(de), len(da)) >= 7:
            return True
        if e.rstrip("/") == a.rstrip("/"):
            return True
    return False
