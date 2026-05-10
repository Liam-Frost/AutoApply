"""Shared base for API-key REST providers.

OpenAI, Anthropic, and Gemini all follow the same shape:

    1. user pastes an API key
    2. we hit a cheap endpoint to verify it
    3. on success we persist the key + a verified_at timestamp
    4. generation calls a chat-completion endpoint

The differences are URLs, headers, and JSON shapes -- captured by the
concrete subclasses. Connection management, persistence, and
:meth:`disconnect` live here so each subclass stays narrow.

The HTTP client is injected via ``http_client_factory`` so tests can
substitute a fake without monkeypatching httpx globals.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

import httpx

from src.providers.base import (
    AuthType,
    LLMProvider,
    ProviderCredentials,
    ProviderError,
    ProviderTestResult,
    now_iso,
)

logger = logging.getLogger("autoapply.providers.api")

# A factory returning a context-managed HTTP client. We accept any
# callable returning something ``with`` -friendly so tests can hand in
# a stub that doesn't speak the real httpx protocol.
HttpClientFactory = Callable[[], AbstractContextManager[httpx.Client]]


def _default_http_client_factory(timeout: float) -> HttpClientFactory:
    def _factory() -> AbstractContextManager[httpx.Client]:
        return httpx.Client(timeout=timeout)

    return _factory


class ApiKeyProvider(LLMProvider):
    """Base class for ``api_key`` auth-type providers."""

    auth_type = AuthType.API_KEY

    # Subclasses set these.
    api_key_env_var: str = ""
    default_model: str = ""

    def __init__(
        self,
        store: Any | None = None,
        *,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        super().__init__(store)
        # Defer creating the default factory until first call so ctor
        # cost stays trivial; this matters for the registry which
        # instantiates every provider on first lookup.
        self._http_client_factory = http_client_factory

    # ----- credential plumbing -----

    def get_api_key(self) -> str:
        """Return the configured API key, falling back to env vars.

        Raises :class:`ProviderError` if neither is set; callers (the
        agent loop, the CLI test command) catch this and surface a
        targeted error message rather than crashing.
        """
        creds = self.credentials()
        if creds and creds.secret.get("api_key"):
            return str(creds.secret["api_key"])
        if self.api_key_env_var:
            env_value = os.environ.get(self.api_key_env_var)
            if env_value:
                return env_value
        raise ProviderError(
            f"{self.display_name or self.id} is not connected. "
            f"Run `autoapply provider connect {self.id}` or set "
            f"{self.api_key_env_var or '<env var>'}."
        )

    def get_model(self) -> str:
        """Return the configured chat model, falling back to ``default_model``."""
        creds = self.credentials()
        if creds:
            override = creds.metadata.get("model")
            if isinstance(override, str) and override.strip():
                return override.strip()
        return self.default_model

    def connect(
        self,
        api_key: str,
        *,
        model: str | None = None,
        timeout: int = 10,
    ) -> ProviderTestResult:
        """Verify the candidate key with a probe; persist only on success.

        Mirrors the OAuth pattern -- never store an unverified
        credential. The probe uses :meth:`_probe_connection` directly
        so we don't have to first ``set`` then ``delete`` on failure.
        """
        if not isinstance(api_key, str) or not api_key.strip():
            raise ProviderError("API key must be a non-empty string.")
        api_key = api_key.strip()
        try:
            result = self._probe_connection(api_key, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 -- network/HTTP boundary
            return ProviderTestResult(ok=False, detail=_redact(str(exc), api_key))

        if not result.ok:
            return result

        creds = ProviderCredentials(
            provider_id=self.id,
            auth_type=self.auth_type,
            secret={"api_key": api_key},
            connected_at=now_iso(),
            verified_at=now_iso(),
            metadata={"model": model} if model else {},
        )
        if self._store is None:
            raise ProviderError(
                "Cannot persist credentials -- provider was constructed without a store."
            )
        self._store.set(creds)
        return result

    def test_connection(self, *, timeout: int = 10) -> ProviderTestResult:
        try:
            api_key = self.get_api_key()
        except ProviderError as exc:
            return ProviderTestResult(ok=False, detail=str(exc))
        try:
            result = self._probe_connection(api_key, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            result = ProviderTestResult(ok=False, detail=_redact(str(exc), api_key))

        creds = self.credentials()
        if creds is not None and self._store is not None:
            creds.verified_at = now_iso() if result.ok else creds.verified_at
            creds.last_test_error = None if result.ok else result.detail
            self._store.set(creds)
        return result

    # ----- subclass hooks -----

    def _probe_connection(self, api_key: str, *, timeout: int) -> ProviderTestResult:
        """Hit a cheap endpoint and report success/failure.

        Subclasses override. Implementations MUST NOT log the raw key
        and MUST translate provider-specific HTTP errors into a
        user-readable :class:`ProviderTestResult.detail`.
        """
        raise NotImplementedError

    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        timeout: int = 120,
    ) -> str:
        """Default impl: subclasses override.

        Kept abstract here rather than raising NotImplementedError so
        type checkers flag the missing override at subclass-time.
        """
        raise NotImplementedError

    # ----- helpers -----

    def _client(self, timeout: float) -> AbstractContextManager[httpx.Client]:
        factory = self._http_client_factory or _default_http_client_factory(timeout)
        return factory()

    @staticmethod
    def _measure(start: float) -> int:
        return int((time.monotonic() - start) * 1000)


def _redact(message: str, secret: str) -> str:
    """Strip a known secret out of a message before it reaches the user."""
    if not secret:
        return message
    return message.replace(secret, "***")
