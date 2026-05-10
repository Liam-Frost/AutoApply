"""Tests for the Phase 10.1 provider abstraction layer.

Covers:

* ``ProviderCredentials`` round-trip + redaction
* ``CredentialStore`` read/write/delete + atomicity
* ``ProviderRegistry`` register / lookup / view filtering
* The base :class:`LLMProvider` defaults

Concrete providers (OpenAI / Anthropic / Gemini / Codex) are
exercised in their own tests as they land.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.providers.base import (
    AuthType,
    LLMProvider,
    ProviderCredentials,
    ProviderError,
    ProviderTestResult,
)
from src.providers.registry import ProviderRegistry
from src.providers.store import CredentialStore

# ---------------------------------------------------------------------------
# Stub provider used throughout
# ---------------------------------------------------------------------------


class _StubProvider(LLMProvider):
    id = "stub"
    display_name = "Stub"
    auth_type = AuthType.API_KEY
    description = "Test stub."
    install_hint = "pip install nothing"

    def test_connection(self, *, timeout: int = 10) -> ProviderTestResult:
        return ProviderTestResult(ok=True, detail="stub", latency_ms=1)

    def generate(self, prompt: str, *, system: str = "", timeout: int = 120) -> str:
        return f"echo: {prompt}"


class _OtherStub(LLMProvider):
    id = "other"
    display_name = "Other"
    auth_type = AuthType.OAUTH

    def test_connection(self, *, timeout: int = 10) -> ProviderTestResult:
        return ProviderTestResult(ok=False, detail="not connected")

    def generate(self, prompt: str, *, system: str = "", timeout: int = 120) -> str:
        raise ProviderError("not connected")


# ---------------------------------------------------------------------------
# ProviderCredentials
# ---------------------------------------------------------------------------


class TestProviderCredentials:
    def test_round_trip(self) -> None:
        creds = ProviderCredentials(
            provider_id="openai",
            auth_type=AuthType.API_KEY,
            secret={"api_key": "sk-test"},
            connected_at="2026-01-01T00:00:00+00:00",
        )
        as_dict = creds.to_dict()
        restored = ProviderCredentials.from_dict(as_dict)
        assert restored == creds

    def test_unknown_auth_type_falls_back_to_api_key(self) -> None:
        restored = ProviderCredentials.from_dict(
            {"provider_id": "x", "auth_type": "weird"}
        )
        assert restored.auth_type == AuthType.API_KEY

    def test_public_view_redacts_secret(self) -> None:
        creds = ProviderCredentials(
            provider_id="openai",
            auth_type=AuthType.API_KEY,
            secret={"api_key": "sk-test"},
        )
        view = creds.public_view()
        assert view["has_secret"] is True
        assert "secret" not in view
        assert "sk-test" not in json.dumps(view)


# ---------------------------------------------------------------------------
# CredentialStore
# ---------------------------------------------------------------------------


class TestCredentialStore:
    def test_set_get_delete(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "creds.json")
        creds = ProviderCredentials(
            provider_id="openai",
            auth_type=AuthType.API_KEY,
            secret={"api_key": "sk"},
        )
        store.set(creds)
        loaded = store.get("openai")
        assert loaded == creds
        assert store.delete("openai") is True
        assert store.get("openai") is None
        assert store.delete("openai") is False

    def test_get_missing_returns_none(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "creds.json")
        assert store.get("missing") is None

    def test_corrupt_file_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "creds.json"
        path.write_text("not json")
        store = CredentialStore(path=path)
        with pytest.raises(ProviderError):
            store.list_ids()

    def test_corrupt_row_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "creds.json"
        path.write_text(
            json.dumps({"good": {"provider_id": "good", "auth_type": "api_key"}})
        )
        # Inject a corrupt row.
        data = json.loads(path.read_text())
        data["bad"] = {"missing_provider_id": True}
        path.write_text(json.dumps(data))
        store = CredentialStore(path=path)
        ids = store.list_ids()
        assert "good" in ids and "bad" in ids
        # `get` on the corrupt row returns None rather than crashing.
        assert store.get("bad") is None
        assert store.get("good") is not None

    def test_set_requires_provider_id(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "creds.json")
        with pytest.raises(ProviderError):
            store.set(
                ProviderCredentials(provider_id="", auth_type=AuthType.API_KEY)
            )

    def test_atomic_write_uses_tmp_file(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "creds.json")
        store.set(
            ProviderCredentials(
                provider_id="openai",
                auth_type=AuthType.API_KEY,
                secret={"api_key": "sk"},
            )
        )
        # The .tmp companion should not survive past the rename.
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_clear_removes_file(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "creds.json")
        store.set(
            ProviderCredentials(provider_id="x", auth_type=AuthType.API_KEY)
        )
        store.clear()
        assert not (tmp_path / "creds.json").exists()


# ---------------------------------------------------------------------------
# ProviderRegistry
# ---------------------------------------------------------------------------


class TestProviderRegistry:
    def test_register_and_lookup(self, tmp_path: Path) -> None:
        registry = ProviderRegistry(store=CredentialStore(path=tmp_path / "c.json"))
        registry.register(_StubProvider)
        provider = registry.get("stub")
        assert provider.id == "stub"
        assert isinstance(provider, _StubProvider)

    def test_double_register_raises(self, tmp_path: Path) -> None:
        registry = ProviderRegistry(store=CredentialStore(path=tmp_path / "c.json"))
        registry.register(_StubProvider)
        with pytest.raises(ProviderError):
            registry.register(_StubProvider)

    def test_unknown_provider_raises(self, tmp_path: Path) -> None:
        registry = ProviderRegistry(store=CredentialStore(path=tmp_path / "c.json"))
        with pytest.raises(ProviderError):
            registry.get("nope")

    def test_maybe_get_returns_none_for_missing(self, tmp_path: Path) -> None:
        registry = ProviderRegistry(store=CredentialStore(path=tmp_path / "c.json"))
        assert registry.maybe_get("nope") is None

    def test_classes_without_id_rejected(self, tmp_path: Path) -> None:
        class NoId(LLMProvider):
            def test_connection(self, *, timeout: int = 10) -> ProviderTestResult:
                return ProviderTestResult(ok=False)

            def generate(self, prompt: str, *, system: str = "", timeout: int = 120) -> str:
                return ""

        registry = ProviderRegistry(store=CredentialStore(path=tmp_path / "c.json"))
        with pytest.raises(ProviderError):
            registry.register(NoId)

    def test_configured_filters_unset(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "c.json")
        registry = ProviderRegistry(store=store)
        registry.register(_StubProvider)
        registry.register(_OtherStub)
        # Nothing connected yet.
        assert registry.configured() == []
        # Connect one.
        store.set(
            ProviderCredentials(
                provider_id="stub",
                auth_type=AuthType.API_KEY,
                secret={"api_key": "x"},
            )
        )
        configured = registry.configured()
        assert [p.id for p in configured] == ["stub"]

    def test_public_view_exposes_class_metadata(self, tmp_path: Path) -> None:
        registry = ProviderRegistry(store=CredentialStore(path=tmp_path / "c.json"))
        registry.register(_StubProvider)
        view = registry.public_view()
        assert view[0]["id"] == "stub"
        assert view[0]["auth_type"] == "api_key"
        assert view[0]["configured"] is False


# ---------------------------------------------------------------------------
# LLMProvider defaults
# ---------------------------------------------------------------------------


class TestLLMProviderDefaults:
    def test_disconnect_drops_credentials(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "c.json")
        store.set(
            ProviderCredentials(
                provider_id="stub",
                auth_type=AuthType.API_KEY,
                secret={"api_key": "x"},
            )
        )
        provider = _StubProvider(store=store)
        assert provider.is_configured()
        provider.disconnect()
        assert not provider.is_configured()
        assert store.get("stub") is None

    def test_is_configured_false_without_secret(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "c.json")
        store.set(
            ProviderCredentials(provider_id="stub", auth_type=AuthType.API_KEY)
        )
        provider = _StubProvider(store=store)
        assert not provider.is_configured()

    def test_public_view_shows_credential_breadcrumbs(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "c.json")
        store.set(
            ProviderCredentials(
                provider_id="stub",
                auth_type=AuthType.API_KEY,
                secret={"api_key": "x"},
                connected_at="2026-01-01T00:00:00+00:00",
                verified_at="2026-01-01T00:01:00+00:00",
            )
        )
        provider = _StubProvider(store=store)
        view = provider.public_view()
        assert view["configured"] is True
        assert view["credentials"]["connected_at"] == "2026-01-01T00:00:00+00:00"
        assert "secret" not in view["credentials"]
