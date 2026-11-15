"""Choose a browser once, before a workflow starts navigating."""

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
PRESETS = [
    {"tenant": "pdportal:ubc", "backend": "nodriver", "operations": []},
    {"tenant": "idp:google", "backend": "nodriver", "operations": ["login"]},
    {"domain": "accounts.google.com", "backend": "nodriver", "operations": ["login"]},
]


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
    alias = (db.get_setting("accounts.alias") or {}).get(tenant, tenant)
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    rules = db.get_setting("browser.rules") or []
    validate({"browser.rules": rules})
    for key in ("tenant", "domain"):
        for rule in rules:
            target = rule.get(key)
            if not target or (rule.get("operations") and operation not in rule["operations"]):
                continue
            matches = target in (tenant, alias) if key == "tenant" else host == target.lower() or host.endswith("." + target.lower())
            if matches:
                return Selection(rule["backend"], f"{key}: {target}")
    provider = (db.get_setting("sso.sites") or {}).get(tenant)
    if provider == "google":
        return Selection("nodriver", "approved Google SSO")
    return Selection("playwright", "default")
