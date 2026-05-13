"""Provider ABC, shared types, and error class.

Every provider -- API-key, OAuth, or subprocess -- conforms to the
:class:`LLMProvider` interface. The interface is intentionally narrow:
the only generation entry point is ``generate(prompt, system, timeout)
-> str`` so that existing :func:`src.utils.llm.generate_text` callers
keep working with no changes when 10.6 wires the registry into them.

Connection management is a separate dimension. Providers expose:

* :attr:`auth_type` -- describes how a credential was obtained, used
  by the UI to render the right "Connect" affordance.
* :meth:`is_configured` -- did the user complete a connect flow?
* :meth:`test_connection` -- cheap round-trip to verify the credential
  is actually accepted by the upstream service.
* :meth:`disconnect` -- forget the credential.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ProviderErrorKind(str, Enum):  # noqa: UP042
    """Why a provider call failed.

    The fallback chain in ``src.utils.llm.generate_text`` keeps trying
    the next provider when the kind is :attr:`is_transient`. Non-transient
    kinds (bad request, parse) abort immediately -- retrying a malformed
    prompt on a second provider just burns money on the same failure.
    """

    AUTH = "auth"                # 401/403, expired key, "not authenticated"
    QUOTA = "quota"              # 429, rate limit, daily cap
    NETWORK = "network"          # DNS, connection refused, TLS error
    TIMEOUT = "timeout"          # request timeout or upstream slowloris
    SERVER = "server"            # 5xx
    BAD_REQUEST = "bad_request"  # 400, prompt rejected, content filter -- NOT retryable
    PARSE = "parse"              # response decoded but missing required fields -- NOT retryable
    UNKNOWN = "unknown"          # default; treated as transient

    @property
    def is_transient(self) -> bool:
        return self not in (
            ProviderErrorKind.BAD_REQUEST,
            ProviderErrorKind.PARSE,
        )


class ProviderError(Exception):
    """Raised when a provider operation fails in a way the caller
    should surface to the user (e.g. invalid key, network error).

    The ``kind`` field lets the fallback chain decide whether to try
    the next provider; older call sites that constructed a bare
    :class:`ProviderError` without a kind get :attr:`ProviderErrorKind.UNKNOWN`
    which is treated as transient (i.e. fallback applies), matching the
    pre-Phase-11.1 behaviour.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: ProviderErrorKind = ProviderErrorKind.UNKNOWN,
    ) -> None:
        super().__init__(message)
        self.kind = kind


def classify_http_status(status_code: int) -> ProviderErrorKind:
    """Map an HTTP status code to a :class:`ProviderErrorKind`."""
    if status_code in (401, 403):
        return ProviderErrorKind.AUTH
    if status_code == 429:
        return ProviderErrorKind.QUOTA
    if 400 <= status_code < 500:
        return ProviderErrorKind.BAD_REQUEST
    if 500 <= status_code < 600:
        return ProviderErrorKind.SERVER
    return ProviderErrorKind.UNKNOWN


def classify_cli_error(message: str) -> ProviderErrorKind:
    """Best-effort classification of a CLI provider failure message.

    Subprocess providers (`claude`, `codex`) don't surface structured
    error codes; we match on the surface text of common failure modes.
    Anything we can't recognise stays ``UNKNOWN`` -- which the fallback
    chain treats as transient, matching pre-Phase-11.1 behaviour.
    """
    msg = message.lower()
    if "timed out" in msg or "timeout" in msg:
        return ProviderErrorKind.TIMEOUT
    if (
        "not authenticated" in msg
        or "please login" in msg
        or "claude login" in msg
        or "codex login" in msg
    ):
        return ProviderErrorKind.AUTH
    if "rate limit" in msg or "quota" in msg or "429" in msg:
        return ProviderErrorKind.QUOTA
    if "not found" in msg and "install" in msg:
        return ProviderErrorKind.AUTH
    return ProviderErrorKind.UNKNOWN


class AuthType(str, Enum):  # noqa: UP042 -- match ApprovalStatus's str+Enum pattern
    """How the user's credential was obtained.

    The web UI uses this to choose the connect affordance:
    API_KEY shows a paste-key form, OAUTH starts the device-auth
    flow, SUBPROCESS shows the install command for the underlying CLI.
    """

    API_KEY = "api_key"
    OAUTH = "oauth"
    SUBPROCESS = "subprocess"


@dataclass
class ProviderCredentials:
    """File-backed credential record.

    Always stored as a flat dict so :class:`CredentialStore` can
    serialise it without provider-specific deserialisers. Providers
    consult/produce this through their own helpers.

    ``connected_at`` and ``verified_at`` are user-facing breadcrumbs
    for the Web UI; ``last_test_error`` records the last connection-
    test failure so the user can see why a key stopped working.
    """

    provider_id: str
    auth_type: AuthType
    secret: dict[str, Any] = field(default_factory=dict)
    connected_at: str = ""
    verified_at: str | None = None
    last_test_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["auth_type"] = self.auth_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProviderCredentials:
        try:
            auth = AuthType(data.get("auth_type", AuthType.API_KEY.value))
        except ValueError:
            auth = AuthType.API_KEY
        return cls(
            provider_id=str(data["provider_id"]),
            auth_type=auth,
            secret=dict(data.get("secret") or {}),
            connected_at=str(data.get("connected_at") or ""),
            verified_at=data.get("verified_at"),
            last_test_error=data.get("last_test_error"),
            metadata=dict(data.get("metadata") or {}),
        )

    def public_view(self) -> dict[str, Any]:
        """Redacted form safe to ship to the front-end and to logs."""
        return {
            "provider_id": self.provider_id,
            "auth_type": self.auth_type.value,
            "connected_at": self.connected_at,
            "verified_at": self.verified_at,
            "last_test_error": self.last_test_error,
            "metadata": dict(self.metadata or {}),
            "has_secret": bool(self.secret),
        }


@dataclass
class ProviderTestResult:
    """Outcome of a non-mutating connection probe."""

    ok: bool
    detail: str = ""
    latency_ms: int = 0
    model_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LLMProvider(ABC):
    """Subclass to add a new LLM provider.

    Class attributes describe the provider to UIs without instantiating;
    instances do real work and may cache state.
    """

    id: str = ""
    display_name: str = ""
    auth_type: AuthType = AuthType.API_KEY
    description: str = ""
    install_hint: str = ""

    def __init__(self, store: Any | None = None) -> None:
        # ``store`` is duck-typed so this module doesn't have a hard
        # dependency on the concrete CredentialStore (avoids circular
        # imports and lets tests inject a fake).
        self._store = store

    # ----- credential helpers -----

    def credentials(self) -> ProviderCredentials | None:
        if self._store is None:
            return None
        return self._store.get(self.id)

    def is_configured(self) -> bool:
        creds = self.credentials()
        return bool(creds and creds.secret)

    def disconnect(self) -> None:
        """Default: forget the credential record. OAuth/subprocess
        providers may override to do more (e.g. invoke ``codex logout``
        so the underlying CLI also drops its own state)."""
        if self._store is not None:
            self._store.delete(self.id)

    # ----- connection / generation -----

    @abstractmethod
    def test_connection(self, *, timeout: int = 10) -> ProviderTestResult:
        ...

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        timeout: int = 120,
        output_format: str = "text",
    ) -> str:
        """Run a single text generation.

        ``output_format`` is either ``"text"`` (default) or ``"json"``.
        CLI-backed providers (Claude Code, Codex) thread this through
        to the underlying ``--output-format`` flag / prompt suffix so
        the resulting string is valid JSON. API providers always
        return text and may ignore the hint -- the caller's
        ``_parse_json_response`` strips fences if necessary.
        """

    # ----- public metadata -----

    def public_view(self) -> dict[str, Any]:
        creds = self.credentials()
        return {
            "id": self.id,
            "display_name": self.display_name,
            "auth_type": self.auth_type.value,
            "description": self.description,
            "install_hint": self.install_hint,
            "configured": self.is_configured(),
            "credentials": creds.public_view() if creds else None,
        }


# ---------------------------------------------------------------------------
# Helpers shared by the concrete providers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    """ISO timestamp with timezone for credential breadcrumbs."""
    return datetime.now(UTC).isoformat()
