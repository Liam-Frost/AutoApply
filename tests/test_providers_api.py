"""Tests for the OpenAI / Anthropic / Gemini REST adapters.

Each provider is exercised through a fake HTTP client factory so the
tests are deterministic and offline. We assert:

  * connection probe interprets HTTP statuses correctly,
  * connect() persists only on a successful probe, with a
    verified_at timestamp,
  * test_connection() updates verified_at / last_test_error in-place,
  * generate() unwraps each provider's response shape,
  * environment-variable fallback works when no credential is stored,
  * API key is NEVER echoed back in error messages.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.providers.anthropic import AnthropicProvider
from src.providers.api_base import ApiKeyProvider
from src.providers.base import ProviderCredentials, ProviderError
from src.providers.gemini import GeminiProvider
from src.providers.openai import OpenAIProvider
from src.providers.store import CredentialStore

# ---------------------------------------------------------------------------
# Fake HTTP client
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, body: Any | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._body = body
        self.text = text or ""

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("no body")
        return self._body


class _FakeClient(AbstractContextManager["_FakeClient"]):
    """Recorder + scripted-response client used in place of httpx.Client."""

    def __init__(
        self,
        *,
        get_response: _FakeResponse | None = None,
        post_response: _FakeResponse | None = None,
    ) -> None:
        self.get_response = get_response
        self.post_response = post_response
        self.calls: list[dict[str, Any]] = []

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc_info: Any) -> None:  # noqa: D401
        return None

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> _FakeResponse:
        self.calls.append(
            {"method": "GET", "url": url, "params": params, "headers": headers}
        )
        if self.get_response is None:
            raise AssertionError(f"unexpected GET to {url}")
        return self.get_response

    def post(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json: Any = None,
    ) -> _FakeResponse:
        self.calls.append(
            {
                "method": "POST",
                "url": url,
                "params": params,
                "headers": headers,
                "json": json,
            }
        )
        if self.post_response is None:
            raise AssertionError(f"unexpected POST to {url}")
        return self.post_response


def _factory_for(client: _FakeClient):
    def _factory():
        return client

    return _factory


# ---------------------------------------------------------------------------
# Shared base class behaviour
# ---------------------------------------------------------------------------


class TestApiKeyProviderBase:
    def test_get_api_key_uses_env_when_no_creds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = CredentialStore(path=tmp_path / "c.json")
        provider = OpenAIProvider(store=store)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        assert provider.get_api_key() == "sk-from-env"

    def test_get_api_key_prefers_stored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = CredentialStore(path=tmp_path / "c.json")
        store.set(
            ProviderCredentials(
                provider_id="openai",
                auth_type=ApiKeyProvider.auth_type,
                secret={"api_key": "sk-stored"},
            )
        )
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        assert OpenAIProvider(store=store).get_api_key() == "sk-stored"

    def test_get_api_key_raises_when_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        store = CredentialStore(path=tmp_path / "c.json")
        with pytest.raises(ProviderError):
            OpenAIProvider(store=store).get_api_key()

    def test_get_model_falls_back_to_default(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "c.json")
        provider = OpenAIProvider(store=store)
        assert provider.get_model() == provider.default_model

    def test_get_model_uses_stored_override(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "c.json")
        store.set(
            ProviderCredentials(
                provider_id="openai",
                auth_type=ApiKeyProvider.auth_type,
                secret={"api_key": "sk"},
                metadata={"model": "gpt-4o"},
            )
        )
        assert OpenAIProvider(store=store).get_model() == "gpt-4o"


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class TestOpenAIProvider:
    def test_probe_success_records_model_count(self, tmp_path: Path) -> None:
        client = _FakeClient(
            get_response=_FakeResponse(
                200, body={"data": [{"id": "gpt-4"}, {"id": "gpt-4o"}]}
            )
        )
        store = CredentialStore(path=tmp_path / "c.json")
        provider = OpenAIProvider(store=store, http_client_factory=_factory_for(client))
        result = provider.connect("sk-test")
        assert result.ok
        assert result.model_count == 2
        # Persisted with verified_at populated.
        creds = store.get("openai")
        assert creds is not None
        assert creds.secret["api_key"] == "sk-test"
        assert creds.verified_at

    def test_connect_does_not_persist_on_401(self, tmp_path: Path) -> None:
        client = _FakeClient(
            get_response=_FakeResponse(401, body={"error": {"message": "bad key"}})
        )
        store = CredentialStore(path=tmp_path / "c.json")
        provider = OpenAIProvider(store=store, http_client_factory=_factory_for(client))
        result = provider.connect("sk-bad")
        assert not result.ok
        assert "401" in result.detail
        # Nothing was saved.
        assert store.get("openai") is None

    def test_connect_does_not_leak_key_on_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _BadClient(_FakeClient):
            def get(self, *a: Any, **kw: Any) -> _FakeResponse:  # type: ignore[override]
                raise httpx.ConnectError("can't reach https://x.com?key=sk-secret")

        client = _BadClient()
        provider = OpenAIProvider(
            store=CredentialStore(path=tmp_path / "c.json"),
            http_client_factory=_factory_for(client),
        )
        result = provider.connect("sk-secret")
        assert not result.ok
        assert "sk-secret" not in result.detail
        assert "***" in result.detail

    def test_test_connection_updates_verified_at(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "c.json")
        store.set(
            ProviderCredentials(
                provider_id="openai",
                auth_type=ApiKeyProvider.auth_type,
                secret={"api_key": "sk-test"},
            )
        )
        client = _FakeClient(get_response=_FakeResponse(200, body={"data": []}))
        provider = OpenAIProvider(
            store=store, http_client_factory=_factory_for(client)
        )
        result = provider.test_connection()
        assert result.ok
        creds = store.get("openai")
        assert creds is not None and creds.verified_at

    def test_test_connection_records_last_error_on_failure(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "c.json")
        store.set(
            ProviderCredentials(
                provider_id="openai",
                auth_type=ApiKeyProvider.auth_type,
                secret={"api_key": "sk-test"},
                verified_at="2026-01-01T00:00:00+00:00",
            )
        )
        client = _FakeClient(
            get_response=_FakeResponse(500, body={"error": {"message": "oops"}})
        )
        provider = OpenAIProvider(
            store=store, http_client_factory=_factory_for(client)
        )
        result = provider.test_connection()
        assert not result.ok
        creds = store.get("openai")
        assert creds is not None
        # Old verified_at preserved; last_test_error populated.
        assert creds.verified_at == "2026-01-01T00:00:00+00:00"
        assert creds.last_test_error and "500" in creds.last_test_error

    def test_generate_unwraps_choices_message_content(
        self, tmp_path: Path
    ) -> None:
        store = CredentialStore(path=tmp_path / "c.json")
        store.set(
            ProviderCredentials(
                provider_id="openai",
                auth_type=ApiKeyProvider.auth_type,
                secret={"api_key": "sk"},
                metadata={"model": "gpt-4o"},
            )
        )
        client = _FakeClient(
            post_response=_FakeResponse(
                200,
                body={
                    "choices": [
                        {"message": {"content": "hello world"}}
                    ]
                },
            )
        )
        provider = OpenAIProvider(
            store=store, http_client_factory=_factory_for(client)
        )
        out = provider.generate("hi", system="be terse")
        assert out == "hello world"
        # The system prompt was forwarded; the model came from metadata.
        sent = client.calls[0]["json"]
        assert sent["model"] == "gpt-4o"
        assert sent["messages"][0]["role"] == "system"
        assert sent["messages"][0]["content"] == "be terse"

    def test_generate_raises_provider_error_on_http_failure(
        self, tmp_path: Path
    ) -> None:
        store = CredentialStore(path=tmp_path / "c.json")
        store.set(
            ProviderCredentials(
                provider_id="openai",
                auth_type=ApiKeyProvider.auth_type,
                secret={"api_key": "sk"},
            )
        )
        client = _FakeClient(post_response=_FakeResponse(429, text="rate limited"))
        provider = OpenAIProvider(
            store=store, http_client_factory=_factory_for(client)
        )
        with pytest.raises(ProviderError, match="429"):
            provider.generate("hi")


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


class TestAnthropicProvider:
    def test_probe_success(self, tmp_path: Path) -> None:
        client = _FakeClient(
            get_response=_FakeResponse(
                200, body={"data": [{"id": "claude-sonnet-4-5"}]}
            )
        )
        store = CredentialStore(path=tmp_path / "c.json")
        provider = AnthropicProvider(
            store=store, http_client_factory=_factory_for(client)
        )
        result = provider.connect("sk-ant-test")
        assert result.ok
        assert client.calls[0]["headers"]["x-api-key"] == "sk-ant-test"
        assert client.calls[0]["headers"]["anthropic-version"]

    def test_generate_concatenates_text_blocks(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "c.json")
        store.set(
            ProviderCredentials(
                provider_id="anthropic",
                auth_type=ApiKeyProvider.auth_type,
                secret={"api_key": "sk-ant"},
            )
        )
        client = _FakeClient(
            post_response=_FakeResponse(
                200,
                body={
                    "content": [
                        {"type": "text", "text": "hello "},
                        {"type": "text", "text": "world"},
                        {"type": "tool_use", "input": {}},  # ignored
                    ]
                },
            )
        )
        provider = AnthropicProvider(
            store=store, http_client_factory=_factory_for(client)
        )
        out = provider.generate("hi", system="be terse")
        assert out == "hello world"
        sent = client.calls[0]["json"]
        assert sent["system"] == "be terse"
        assert sent["max_tokens"] >= 1

    def test_generate_raises_on_no_text_blocks(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "c.json")
        store.set(
            ProviderCredentials(
                provider_id="anthropic",
                auth_type=ApiKeyProvider.auth_type,
                secret={"api_key": "sk-ant"},
            )
        )
        client = _FakeClient(
            post_response=_FakeResponse(
                200, body={"content": [{"type": "tool_use"}]}
            )
        )
        provider = AnthropicProvider(
            store=store, http_client_factory=_factory_for(client)
        )
        with pytest.raises(ProviderError, match="text blocks"):
            provider.generate("hi")


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


class TestGeminiProvider:
    def test_probe_success(self, tmp_path: Path) -> None:
        client = _FakeClient(
            get_response=_FakeResponse(
                200, body={"models": [{"name": "models/gemini-2.5-flash"}]}
            )
        )
        store = CredentialStore(path=tmp_path / "c.json")
        provider = GeminiProvider(
            store=store, http_client_factory=_factory_for(client)
        )
        result = provider.connect("AIza-test")
        assert result.ok
        # Key is sent as ?key=, not as a header.
        assert client.calls[0]["params"]["key"] == "AIza-test"

    def test_generate_extracts_text_from_candidates(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "c.json")
        store.set(
            ProviderCredentials(
                provider_id="gemini",
                auth_type=ApiKeyProvider.auth_type,
                secret={"api_key": "AIza"},
            )
        )
        client = _FakeClient(
            post_response=_FakeResponse(
                200,
                body={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"text": "hello"},
                                    {"text": " world"},
                                ]
                            }
                        }
                    ]
                },
            )
        )
        provider = GeminiProvider(
            store=store, http_client_factory=_factory_for(client)
        )
        out = provider.generate("hi", system="be terse")
        assert out == "hello world"
        sent = client.calls[0]["json"]
        assert sent["systemInstruction"]["parts"][0]["text"] == "be terse"

    def test_error_message_redacts_key(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "c.json")
        store.set(
            ProviderCredentials(
                provider_id="gemini",
                auth_type=ApiKeyProvider.auth_type,
                secret={"api_key": "AIza-secret"},
            )
        )
        client = _FakeClient(
            post_response=_FakeResponse(
                500, text="internal error involving key=AIza-secret"
            )
        )
        provider = GeminiProvider(
            store=store, http_client_factory=_factory_for(client)
        )
        with pytest.raises(ProviderError) as excinfo:
            provider.generate("hi")
        assert "AIza-secret" not in str(excinfo.value)
        assert "***" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Registry now exposes all three.
# ---------------------------------------------------------------------------


class TestRegistryRegistersBuiltins:
    def test_three_providers_present(self) -> None:
        from src.providers.registry import ProviderRegistry, _register_builtins

        registry = ProviderRegistry()
        _register_builtins(registry)
        assert set(registry.ids()) == {"openai", "anthropic", "gemini"}
