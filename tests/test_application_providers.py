"""Tests for ``src.application.providers`` (Phase 10 web surface).

The use cases are thin wrappers around the provider registry, so we
isolate them by installing a stub registry singleton and pointing the
settings YAML helper at a tmp file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.providers.api_base import ApiKeyProvider
from src.providers.base import (
    AuthType,
    LLMProvider,
    ProviderCredentials,
    ProviderTestResult,
)
from src.providers.registry import ProviderRegistry, reset_default_registry
from src.providers.store import CredentialStore

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _StubApiKey(ApiKeyProvider):
    id = "stub-api"
    display_name = "Stub API"
    description = "test stub"
    api_key_env_var = "STUB_API_KEY"
    default_model = "stub-model"

    probe_ok: bool = True
    probe_detail: str = "OK"
    probe_raises: BaseException | None = None

    def _probe_connection(self, api_key: str, *, timeout: int) -> ProviderTestResult:
        if self.probe_raises:
            raise self.probe_raises
        return ProviderTestResult(ok=self.probe_ok, detail=self.probe_detail)

    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        timeout: int = 120,
        output_format: str = "text",
    ) -> str:
        return "stub"


class _StubSubprocess(LLMProvider):
    id = "stub-sub"
    display_name = "Stub Subprocess"
    auth_type = AuthType.SUBPROCESS
    description = "subprocess stub"

    def test_connection(self, *, timeout: int = 10) -> ProviderTestResult:
        return ProviderTestResult(ok=True)

    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        timeout: int = 120,
        output_format: str = "text",
    ) -> str:
        return "sub"


@pytest.fixture
def isolated_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reset_default_registry()
    store = CredentialStore(path=tmp_path / "creds.json")
    registry = ProviderRegistry(store=store)
    registry.register(_StubApiKey)
    registry.register(_StubSubprocess)

    import src.providers.registry as registry_module

    registry_module._default_registry = registry

    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        "llm:\n  primary_provider: stub-sub\n  allow_fallback: false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "src.application.providers._SETTINGS_PATH", settings_path
    )
    yield registry, settings_path
    reset_default_registry()


# ---------------------------------------------------------------------------
# list_providers
# ---------------------------------------------------------------------------


class TestListProviders:
    def test_returns_public_view_with_primary_selection(self, isolated_setup) -> None:
        from src.application.providers import list_providers

        result = list_providers()
        assert result["ok"] is True
        ids = [p["id"] for p in result["providers"]]
        assert {"stub-api", "stub-sub"} <= set(ids)
        assert result["primary_provider"] == "stub-sub"
        # No credentials yet -- stub-api should not report having a secret.
        api_row = next(p for p in result["providers"] if p["id"] == "stub-api")
        creds_view = api_row.get("credentials")
        assert creds_view is None or not creds_view.get("has_secret", False)


# ---------------------------------------------------------------------------
# test_provider_connection
# ---------------------------------------------------------------------------


class TestTestProviderConnection:
    def test_unknown_provider(self, isolated_setup) -> None:
        from src.application.providers import test_provider_connection

        result = test_provider_connection("bogus")
        assert result["ok"] is False
        assert result["error_code"] == "unknown_provider"

    def test_returns_probe_result(self, isolated_setup) -> None:
        from src.application.providers import test_provider_connection

        result = test_provider_connection("stub-sub")
        assert result["ok"] is True
        assert result["provider_id"] == "stub-sub"

    def test_probe_failure_returns_not_ok(self, isolated_setup) -> None:
        from src.application.providers import test_provider_connection

        registry, _ = isolated_setup
        instance = registry.get("stub-api")
        instance.probe_ok = False
        instance.probe_detail = "rejected"
        # Need to save a credential first so the probe actually fires.
        registry.store.set(
            ProviderCredentials(
                provider_id="stub-api",
                auth_type=AuthType.API_KEY,
                secret={"api_key": "sk"},
            )
        )
        result = test_provider_connection("stub-api")
        assert result["ok"] is False
        assert "rejected" in result["error"]


# ---------------------------------------------------------------------------
# connect_api_key_provider
# ---------------------------------------------------------------------------


class TestConnectApiKeyProvider:
    def test_saves_credential_and_verifies(self, isolated_setup) -> None:
        from src.application.providers import connect_api_key_provider

        registry, _ = isolated_setup
        result = connect_api_key_provider(
            "stub-api", api_key="sk-test", model="custom-model"
        )
        assert result["ok"] is True
        assert result["verified"] is True
        creds = registry.store.get("stub-api")
        assert creds is not None
        assert creds.secret["api_key"] == "sk-test"
        assert creds.metadata["model"] == "custom-model"
        assert creds.verified_at is not None

    def test_unknown_provider_rejected(self, isolated_setup) -> None:
        from src.application.providers import connect_api_key_provider

        result = connect_api_key_provider("nope", api_key="sk")
        assert result["ok"] is False
        assert result["error_code"] == "unknown_provider"

    def test_non_api_key_provider_rejected(self, isolated_setup) -> None:
        from src.application.providers import connect_api_key_provider

        result = connect_api_key_provider("stub-sub", api_key="sk")
        assert result["ok"] is False
        assert result["error_code"] == "wrong_auth_type"

    def test_empty_key_rejected(self, isolated_setup) -> None:
        from src.application.providers import connect_api_key_provider

        result = connect_api_key_provider("stub-api", api_key="   ")
        assert result["ok"] is False
        assert result["error_code"] == "empty_api_key"

    def test_failed_probe_keeps_key_records_error(self, isolated_setup) -> None:
        from src.application.providers import connect_api_key_provider

        registry, _ = isolated_setup
        instance = registry.get("stub-api")
        instance.probe_ok = False
        instance.probe_detail = "bad key"
        result = connect_api_key_provider("stub-api", api_key="sk-bad")
        assert result["ok"] is False
        creds = registry.store.get("stub-api")
        assert creds is not None
        assert creds.secret["api_key"] == "sk-bad"
        assert creds.last_test_error == "bad key"
        assert creds.verified_at is None


# ---------------------------------------------------------------------------
# disconnect_provider
# ---------------------------------------------------------------------------


class TestDisconnectProvider:
    def test_removes_credential(self, isolated_setup) -> None:
        from src.application.providers import disconnect_provider

        registry, _ = isolated_setup
        registry.store.set(
            ProviderCredentials(
                provider_id="stub-api",
                auth_type=AuthType.API_KEY,
                secret={"api_key": "sk"},
            )
        )
        result = disconnect_provider("stub-api")
        assert result["ok"] is True
        assert registry.store.get("stub-api") is None

    def test_unknown_provider(self, isolated_setup) -> None:
        from src.application.providers import disconnect_provider

        result = disconnect_provider("nope")
        assert result["ok"] is False
        assert result["error_code"] == "unknown_provider"


# ---------------------------------------------------------------------------
# use_provider_as_primary
# ---------------------------------------------------------------------------


class TestUseProviderAsPrimary:
    def test_preserves_fallback_when_unspecified(self, isolated_setup) -> None:
        """Regression guard for the codex review P1 finding: a UI
        "Use as primary" click must NOT silently drop the user's
        configured fallback."""
        from src.application.providers import use_provider_as_primary

        _, settings_path = isolated_setup
        # Seed the file with an explicit fallback.
        settings_path.write_text(
            "llm:\n"
            "  primary_provider: stub-sub\n"
            "  fallback_provider: stub-api\n"
            "  allow_fallback: true\n",
            encoding="utf-8",
        )
        # Now flip primary to stub-api without specifying fallback.
        result = use_provider_as_primary("stub-api")
        assert result["ok"] is True
        data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        assert data["llm"]["primary_provider"] == "stub-api"
        # If the previous fallback equaled the new primary, the
        # self-heal clears it (we can't fall back to ourselves).
        assert data["llm"]["fallback_provider"] is None
        assert data["llm"]["allow_fallback"] is False

    def test_preserves_unrelated_fallback(self, isolated_setup) -> None:
        from src.application.providers import use_provider_as_primary

        _, settings_path = isolated_setup
        # Register a third provider so we can pick a fallback that
        # isn't equal to the new primary.
        registry, _ = isolated_setup

        class _ThirdProvider(LLMProvider):
            id = "stub-third"
            display_name = "Third"
            auth_type = AuthType.API_KEY

            def test_connection(self, *, timeout: int = 10) -> ProviderTestResult:
                return ProviderTestResult(ok=True)

            def generate(
                self,
                prompt: str,
                *,
                system: str = "",
                timeout: int = 120,
                output_format: str = "text",
            ) -> str:
                return "third"

        registry.register(_ThirdProvider)
        settings_path.write_text(
            "llm:\n"
            "  primary_provider: stub-sub\n"
            "  fallback_provider: stub-third\n"
            "  allow_fallback: true\n",
            encoding="utf-8",
        )
        result = use_provider_as_primary("stub-api")
        assert result["ok"] is True
        data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        assert data["llm"]["primary_provider"] == "stub-api"
        # stub-third was NOT touched -- this is the new preserve semantic.
        assert data["llm"]["fallback_provider"] == "stub-third"
        assert data["llm"]["allow_fallback"] is True

    def test_explicit_clear_via_empty_string(self, isolated_setup) -> None:
        from src.application.providers import use_provider_as_primary

        _, settings_path = isolated_setup
        settings_path.write_text(
            "llm:\n"
            "  primary_provider: stub-sub\n"
            "  fallback_provider: stub-api\n"
            "  allow_fallback: true\n",
            encoding="utf-8",
        )
        result = use_provider_as_primary("stub-sub", fallback_provider="")
        assert result["ok"] is True
        data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        assert data["llm"]["primary_provider"] == "stub-sub"
        assert data["llm"]["fallback_provider"] is None
        assert data["llm"]["allow_fallback"] is False

    def test_with_explicit_fallback(self, isolated_setup) -> None:
        from src.application.providers import use_provider_as_primary

        _, settings_path = isolated_setup
        result = use_provider_as_primary("stub-api", fallback_provider="stub-sub")
        assert result["ok"] is True
        data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        assert data["llm"]["primary_provider"] == "stub-api"
        assert data["llm"]["fallback_provider"] == "stub-sub"
        assert data["llm"]["allow_fallback"] is True

    def test_unknown_primary(self, isolated_setup) -> None:
        from src.application.providers import use_provider_as_primary

        result = use_provider_as_primary("nope")
        assert result["ok"] is False
        assert result["error_code"] == "unknown_provider"

    def test_unknown_fallback(self, isolated_setup) -> None:
        from src.application.providers import use_provider_as_primary

        result = use_provider_as_primary("stub-api", fallback_provider="nope")
        assert result["ok"] is False
        assert result["error_code"] == "unknown_provider"


class TestDisconnectRoutingCleanup:
    """Regression guard for the codex review P1 finding: disconnecting
    a provider that is the configured primary or fallback must clean
    settings.yaml so the next LLM call doesn't fail."""

    def test_disconnect_non_routed_provider_leaves_settings_alone(
        self, isolated_setup
    ) -> None:
        from src.application.providers import disconnect_provider

        registry, settings_path = isolated_setup
        registry.store.set(
            ProviderCredentials(
                provider_id="stub-api",
                auth_type=AuthType.API_KEY,
                secret={"api_key": "sk"},
            )
        )
        # stub-api is connected but NOT primary (stub-sub is). Routing
        # stays untouched.
        original = settings_path.read_text(encoding="utf-8")
        result = disconnect_provider("stub-api")
        assert result["ok"] is True
        assert result["reset_routing"] is False
        assert settings_path.read_text(encoding="utf-8") == original

    def test_disconnect_primary_clears_routing(self, isolated_setup) -> None:
        from src.application.providers import disconnect_provider

        registry, settings_path = isolated_setup
        registry.store.set(
            ProviderCredentials(
                provider_id="stub-api",
                auth_type=AuthType.API_KEY,
                secret={"api_key": "sk"},
            )
        )
        settings_path.write_text(
            "llm:\n  primary_provider: stub-api\n  allow_fallback: false\n",
            encoding="utf-8",
        )
        result = disconnect_provider("stub-api")
        assert result["ok"] is True
        assert result["reset_routing"] is True
        data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        # Primary cleared; no configured fallback to promote.
        assert data["llm"]["primary_provider"] == ""

    def test_disconnect_primary_promotes_configured_fallback(
        self, isolated_setup
    ) -> None:
        from src.application.providers import disconnect_provider

        registry, settings_path = isolated_setup
        # Both providers must be configured so the fallback is promotable.
        registry.store.set(
            ProviderCredentials(
                provider_id="stub-api",
                auth_type=AuthType.API_KEY,
                secret={"api_key": "sk"},
            )
        )
        settings_path.write_text(
            "llm:\n"
            "  primary_provider: stub-api\n"
            "  fallback_provider: stub-sub\n"
            "  allow_fallback: true\n",
            encoding="utf-8",
        )
        result = disconnect_provider("stub-api")
        assert result["ok"] is True
        data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        # stub-sub is a subprocess provider; is_configured() returns
        # True for it because the test machine has codex CLI on PATH,
        # so it gets promoted to primary.
        if data["llm"]["primary_provider"]:
            assert data["llm"]["primary_provider"] == "stub-sub"
        else:
            # Fallback was not configured -> primary blanked out.
            assert data["llm"]["primary_provider"] == ""

    def test_disconnect_fallback_only_clears_fallback(
        self, isolated_setup
    ) -> None:
        from src.application.providers import disconnect_provider

        registry, settings_path = isolated_setup
        registry.store.set(
            ProviderCredentials(
                provider_id="stub-api",
                auth_type=AuthType.API_KEY,
                secret={"api_key": "sk"},
            )
        )
        settings_path.write_text(
            "llm:\n"
            "  primary_provider: stub-sub\n"
            "  fallback_provider: stub-api\n"
            "  allow_fallback: true\n",
            encoding="utf-8",
        )
        result = disconnect_provider("stub-api")
        assert result["ok"] is True
        data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        # Primary untouched; fallback cleared.
        assert data["llm"]["primary_provider"] == "stub-sub"
        assert data["llm"]["fallback_provider"] is None
        assert data["llm"]["allow_fallback"] is False
