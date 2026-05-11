"""Tests for the ``autoapply provider`` CLI (Phase 10.6).

Each test installs an isolated registry singleton + a temporary
``config/settings.yaml`` so subcommands run hermetically. We never
touch real network, real ``codex``, or the user's keychain.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from src.cli.main import cli
from src.providers.base import (
    AuthType,
    LLMProvider,
    ProviderCredentials,
    ProviderTestResult,
)
from src.providers.codex import CodexLoginEvent
from src.providers.registry import ProviderRegistry, reset_default_registry
from src.providers.store import CredentialStore

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _StubApiKeyProvider(LLMProvider):
    """API-key provider with controllable test_connection."""

    id = "stub-api"
    display_name = "Stub API"
    auth_type = AuthType.API_KEY
    description = "test stub"

    test_result: ProviderTestResult = ProviderTestResult(ok=True, detail="OK")

    def test_connection(self, *, timeout: int = 10) -> ProviderTestResult:
        return self.test_result

    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        timeout: int = 120,
        output_format: str = "text",
    ) -> str:
        return "stub"


# We need a real ApiKeyProvider for set-key (isinstance check). Build a
# thin subclass that bypasses the network probe.
from src.providers.api_base import ApiKeyProvider  # noqa: E402


class _StubApiKeyConcrete(ApiKeyProvider):
    id = "stub-api"
    display_name = "Stub API"
    description = "test stub"
    api_key_env_var = "STUB_API_KEY"
    default_model = "stub-model"

    test_result: ProviderTestResult = ProviderTestResult(ok=True, detail="OK")

    def _probe_connection(self, api_key: str, *, timeout: int) -> ProviderTestResult:
        return self.test_result

    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        timeout: int = 120,
        output_format: str = "text",
    ) -> str:
        return "stub"


class _StubSubprocessProvider(LLMProvider):
    id = "stub-sub"
    display_name = "Stub Subprocess"
    auth_type = AuthType.SUBPROCESS
    description = "subprocess stub"

    def test_connection(self, *, timeout: int = 10) -> ProviderTestResult:
        return ProviderTestResult(ok=True, detail="OK")

    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        timeout: int = 120,
        output_format: str = "text",
    ) -> str:
        return "stub-sub"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ProviderRegistry:
    """Replace the singleton registry with one that has our stubs +
    point settings.yaml at a tmp file so `provider use` is sandboxed."""
    reset_default_registry()
    store = CredentialStore(path=tmp_path / "creds.json")
    registry = ProviderRegistry(store=store)
    registry.register(_StubApiKeyConcrete)
    registry.register(_StubSubprocessProvider)

    import src.providers.registry as registry_module

    registry_module._default_registry = registry

    # Sandboxed settings.yaml.
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        "llm:\n  primary_provider: stub-api\n  allow_fallback: false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.cli.cmd_provider._SETTINGS_PATH", settings_path)

    yield registry
    reset_default_registry()


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestProviderList:
    def test_human_output(
        self, runner: CliRunner, isolated_registry: ProviderRegistry
    ) -> None:
        result = runner.invoke(cli, ["provider", "list"])
        assert result.exit_code == 0, result.output
        assert "stub-api" in result.output
        assert "stub-sub" in result.output

    def test_json_output(
        self, runner: CliRunner, isolated_registry: ProviderRegistry
    ) -> None:
        result = runner.invoke(cli, ["provider", "list", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
        ids = {p["id"] for p in payload["data"]["providers"]}
        assert {"stub-api", "stub-sub"} <= ids


# ---------------------------------------------------------------------------
# test
# ---------------------------------------------------------------------------


class TestProviderTest:
    def test_ok(
        self, runner: CliRunner, isolated_registry: ProviderRegistry
    ) -> None:
        result = runner.invoke(cli, ["provider", "test", "stub-sub", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["data"]["provider_id"] == "stub-sub"

    def test_unknown_provider_exits_nonzero(
        self, runner: CliRunner, isolated_registry: ProviderRegistry
    ) -> None:
        result = runner.invoke(cli, ["provider", "test", "bogus", "--json"])
        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert "Unknown provider" in payload["error"]["message"]

    def test_failure_exits_nonzero(
        self, runner: CliRunner, isolated_registry: ProviderRegistry
    ) -> None:
        # No API key is stored yet, so the ApiKeyProvider's
        # ``test_connection`` short-circuits with ok=False before
        # touching the network probe -- this is what we want to assert.
        result = runner.invoke(cli, ["provider", "test", "stub-api", "--json"])
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# set-key
# ---------------------------------------------------------------------------


class TestProviderSetKey:
    def test_set_key_saves_credential(
        self,
        runner: CliRunner,
        isolated_registry: ProviderRegistry,
    ) -> None:
        # Force the probe to succeed.
        instance = isolated_registry.get("stub-api")
        instance.test_result = ProviderTestResult(ok=True, detail="OK", latency_ms=5)

        result = runner.invoke(
            cli,
            [
                "provider",
                "set-key",
                "stub-api",
                "--api-key",
                "sk-test-123",
                "--model",
                "stub-model-2",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        creds = isolated_registry.store.get("stub-api")
        assert creds is not None
        assert creds.secret["api_key"] == "sk-test-123"
        assert creds.metadata["model"] == "stub-model-2"
        assert creds.verified_at is not None

    def test_no_test_skips_probe(
        self, runner: CliRunner, isolated_registry: ProviderRegistry
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "provider",
                "set-key",
                "stub-api",
                "--api-key",
                "sk-test",
                "--no-test",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        creds = isolated_registry.store.get("stub-api")
        assert creds is not None
        # verified_at stays None because we skipped the probe.
        assert creds.verified_at is None

    def test_rejects_non_api_key_provider(
        self, runner: CliRunner, isolated_registry: ProviderRegistry
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "provider",
                "set-key",
                "stub-sub",
                "--api-key",
                "sk-test",
                "--json",
            ],
        )
        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert "auth_type" in payload["error"]["message"]

    def test_failed_probe_keeps_key_and_records_error(
        self, runner: CliRunner, isolated_registry: ProviderRegistry
    ) -> None:
        instance = isolated_registry.get("stub-api")
        instance.test_result = ProviderTestResult(ok=False, detail="bad key")

        result = runner.invoke(
            cli,
            [
                "provider",
                "set-key",
                "stub-api",
                "--api-key",
                "sk-bad",
                "--json",
            ],
        )
        assert result.exit_code == 1
        creds = isolated_registry.store.get("stub-api")
        assert creds is not None
        assert creds.secret["api_key"] == "sk-bad"
        assert creds.last_test_error == "bad key"


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


class TestProviderDisconnect:
    def test_disconnect_removes_credential(
        self, runner: CliRunner, isolated_registry: ProviderRegistry
    ) -> None:
        isolated_registry.store.set(
            ProviderCredentials(
                provider_id="stub-api",
                auth_type=AuthType.API_KEY,
                secret={"api_key": "sk"},
            )
        )
        result = runner.invoke(
            cli, ["provider", "disconnect", "stub-api", "--json"]
        )
        assert result.exit_code == 0, result.output
        assert isolated_registry.store.get("stub-api") is None


# ---------------------------------------------------------------------------
# use
# ---------------------------------------------------------------------------


class TestProviderUse:
    def test_use_updates_settings(
        self,
        runner: CliRunner,
        isolated_registry: ProviderRegistry,
        tmp_path: Path,
    ) -> None:
        result = runner.invoke(
            cli, ["provider", "use", "stub-sub", "--json"]
        )
        assert result.exit_code == 0, result.output

        # Read back the sandboxed settings.yaml via the module reference.
        import src.cli.cmd_provider as cmd_provider

        text = cmd_provider._SETTINGS_PATH.read_text(encoding="utf-8")
        assert "primary_provider: stub-sub" in text

    def test_use_with_fallback(
        self, runner: CliRunner, isolated_registry: ProviderRegistry
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "provider",
                "use",
                "stub-api",
                "--fallback",
                "stub-sub",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["data"]["fallback_provider"] == "stub-sub"

    def test_use_rejects_unknown(
        self, runner: CliRunner, isolated_registry: ProviderRegistry
    ) -> None:
        result = runner.invoke(
            cli, ["provider", "use", "bogus", "--json"]
        )
        assert result.exit_code == 2
        assert json.loads(result.output)["ok"] is False


# ---------------------------------------------------------------------------
# login (Codex OAuth)
# ---------------------------------------------------------------------------


class TestProviderLogin:
    def test_login_drives_codex_session(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from src.providers.codex import CodexOAuthProvider

        reset_default_registry()
        store = CredentialStore(path=tmp_path / "creds.json")

        # Fake login session: pretend the user finished OAuth quickly.
        class _FakeSession:
            return_code = 0
            url = "https://auth.openai.com/oauth"
            code = None
            events: list[CodexLoginEvent] = []

            def wait(self, timeout: float | None = None) -> int:  # noqa: ARG002
                return 0

            def cancel(self) -> None:  # pragma: no cover
                pass

        provider = CodexOAuthProvider(store=store, codex_executable="codex")

        # Monkeypatch start_login to skip subprocess entirely.
        def fake_start_login(**kwargs):
            on_event = kwargs.get("on_event")
            if on_event:
                on_event(
                    CodexLoginEvent(
                        type="url", message="https://auth.openai.com/oauth"
                    )
                )
                on_event(CodexLoginEvent(type="complete", message="done"))
            return _FakeSession()

        monkeypatch.setattr(provider, "start_login", fake_start_login)

        registry = ProviderRegistry(store=store)
        registry._classes["codex-cli"] = CodexOAuthProvider
        registry._instances["codex-cli"] = provider

        import src.providers.registry as registry_module

        registry_module._default_registry = registry

        result = runner.invoke(
            cli,
            ["provider", "login", "codex-cli", "--no-browser", "--json"],
        )
        try:
            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert payload["ok"] is True
            assert any(
                ev["type"] == "url" for ev in payload["data"]["events"]
            )
            assert store.get("codex-cli") is not None
        finally:
            reset_default_registry()

    def test_login_rejects_non_oauth_provider(
        self, runner: CliRunner, isolated_registry: ProviderRegistry
    ) -> None:
        result = runner.invoke(
            cli, ["provider", "login", "stub-api", "--json"]
        )
        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert "does not support OAuth" in payload["error"]["message"]
