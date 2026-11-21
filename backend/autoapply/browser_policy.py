"""Choose a browser once, before a workflow starts navigating.

The rule everything here follows: A SIGN-IN LIVES IN THE BROWSER IT WAS MADE IN. Sites tie a session to the browser
that signed in (Google and the university portal visibly; others silently), so cookies carried into another browser
are a signed-out session at best and get the real one revoked at worst. Therefore the browser is chosen per site -
by where that site's sign-in is - and never per kind of work: reading a form, filling it, scanning a list and signing
in all happen in the same browser for one site.

In order:
  1. what the task was told to use (the applicant's choice for one run);
  2. where the site's saved sign-in was made (recorded when it is saved: sites.fact(key, "session_browser"));
  3. a rule for the site (settings: browser.rules, "tenant") - the browser its sign-in is to be made in.
     A rule's "operations" no longer narrow this: a rule that said "login only" sent the rest of the work to the other
     browser, which is exactly what must not happen;
  4. a site that signs in through a provider (or whose sign-in is a provider's own) follows the provider's browser;
  5. a rule for an address ("domain"), where "operations" still mean something - a page visited on the way;
  6. the automated browser.
A site is looked up under the key its sign-in is kept under (sites.account), so that "Google's careers site" and
"Google" are one."""

from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlparse

BACKENDS = {"playwright", "nodriver"}
OPERATIONS = {"login", "scan", "read", "apply"}
_override = ContextVar("browser_backend", default=None)


@contextmanager
def task_backend(backend):
    token = _override.set(backend)
    try:
        yield
    finally:
        _override.reset(token)



@dataclass(frozen=True)
class Selection:
    backend: str
    reason: str


def validate(settings: dict) -> None:
    if "browser.nodriver_enabled" in settings and not isinstance(settings["browser.nodriver_enabled"], bool):
        raise ValueError("browser.nodriver_enabled must be a boolean")
    if "browser.executable" in settings and not isinstance(settings["browser.executable"], str):
        raise ValueError("browser.executable must be a path string")
    rules = settings.get("browser.rules", [])
    if not isinstance(rules, list):
        raise ValueError("browser.rules must be a list")
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("backend") not in BACKENDS:
            raise ValueError("Each browser rule needs a supported backend")
        if bool(rule.get("tenant")) == bool(rule.get("domain")):
            raise ValueError("Each browser rule needs exactly one tenant or domain")
        if rule.get("tenant") and not isinstance(rule["tenant"], str):
            raise ValueError("Browser tenant must be a string")
        if domain := rule.get("domain"):
            if not isinstance(domain, str) or any(c in domain for c in "/:@?#* ") or domain.startswith("."):
                raise ValueError("Browser domains must be hostnames, such as accounts.google.com")
        operations = rule.get("operations", [])
        if not isinstance(operations, list) or any(op not in OPERATIONS for op in operations):
            raise ValueError("Unsupported browser operation")


def select(tenant: str | None, url: str = "", operation: str = "apply", override: str | None = None) -> Selection:
    from . import db

    if operation not in OPERATIONS:
        raise ValueError(f"Unsupported browser operation: {operation}")
    enabled = bool(db.get_setting("browser.nodriver_enabled"))
    override = override or _override.get()
    if override:
        if override not in BACKENDS:
            raise ValueError("Unsupported browser backend")
        if override == "nodriver" and not enabled:
            raise ValueError("Enable nodriver in browser settings first")
        return Selection(override, "task override")
    if not enabled:
        return Selection("playwright", "default")
    rules = db.get_setting("browser.rules") or []
    validate({"browser.rules": rules})
    if tenant:
        found = of_session(tenant, rules)
        if found is not None:
            return found
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    for rule in rules:
        target = rule.get("domain")
        if not target or (rule.get("operations") and operation not in rule["operations"]):
            continue
        if host == target.lower() or host.endswith("." + target.lower()):
            return Selection(rule["backend"], f"domain: {target}")
    return Selection("playwright", "default")


def store_rules_whole() -> None:
    """A rule for a site says which browser its sign-in lives in - for all of its work. Rules saved when they could be
    limited to "login" have been ignored in that part since; here they are stored as what they now mean (once, at start)."""
    from . import db

    rules = db.get_setting("browser.rules") or []
    if any(r.get("tenant") and r.get("operations") for r in rules):
        db.set_setting("browser.rules", [{**r, "operations": []} if r.get("tenant") else r for r in rules])


def canonical(tenant: str | None) -> str:
    """The key a site's sign-in is kept under: its own, or that of the site it signs in on."""
    from . import sites

    return sites.account(tenant)


def of_session(tenant: str, rules: list | None = None, _seen: tuple = ()) -> Selection | None:
    """The browser this site's sign-in lives in, when that is known or laid down; None when nothing says (steps 2-4)."""
    from . import db

    from . import sites

    key = canonical(tenant)
    made = sites.fact(key, "session_browser")
    if made in BACKENDS:
        return Selection(made, f"where the sign-in for {key} was made")
    rules = rules if rules is not None else (db.get_setting("browser.rules") or [])
    for rule in rules:
        if rule.get("tenant") and rule["tenant"] in (tenant, key):
            return Selection(rule["backend"], f"tenant: {rule['tenant']}")
    return None


def session_browser(tenant: str) -> str:
    """"nodriver" or "playwright": the browser the work for this site is done in when nothing overrides it."""
    from . import db

    if not db.get_setting("browser.nodriver_enabled"):
        return "playwright"
    found = of_session(tenant)
    return found.backend if found else "playwright"


def remember(tenant: str, backend: str) -> bool:
    """A site that an application got further on in ``backend``: the next task there starts in it. Only where the
    applicant has no rule of their own for the site. Returns whether a rule was written."""
    from . import db

    if backend not in BACKENDS or not tenant:
        return False
    rules = list(db.get_setting("browser.rules") or [])
    if any(r.get("tenant") == tenant for r in rules):
        return False
    db.set_setting("browser.rules", [*rules, {"tenant": tenant, "backend": backend, "operations": []}])
    return True
