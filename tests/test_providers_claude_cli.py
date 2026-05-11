"""Tests for the Claude CLI subprocess provider (Phase 10.4).

We never spawn ``claude`` for real -- the provider exposes seams
(``executable``, ``version_runner``, ``generator``) precisely so we
can drive it deterministically.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from src.providers.base import AuthType, ProviderError
from src.providers.claude_cli import ClaudeCliProvider
from src.providers.registry import (
    ProviderRegistry,
    get_registry,
    reset_default_registry,
)
from src.providers.store import CredentialStore
from src.utils.llm import LLMError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _provider(
    tmp_path: Path,
    *,
    executable: str | None = "claude",
    version_runner: Callable[[str], tuple[int, str]] | None = None,
    generator: Callable[..., str] | None = None,
) -> tuple[ClaudeCliProvider, CredentialStore]:
    store = CredentialStore(path=tmp_path / "creds.json")
    return (
        ClaudeCliProvider(
            store=store,
            executable=executable,
            version_runner=version_runner,
            generator=generator,
        ),
        store,
    )


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_class_attributes(self) -> None:
        assert ClaudeCliProvider.id == "claude-cli"
        assert ClaudeCliProvider.auth_type is AuthType.SUBPROCESS
        assert "Claude" in ClaudeCliProvider.display_name
        assert "claude-code" in ClaudeCliProvider.install_hint


# ---------------------------------------------------------------------------
# is_configured / is_installed
# ---------------------------------------------------------------------------


class TestInstallation:
    def test_is_configured_true_when_executable_present(
        self, tmp_path: Path
    ) -> None:
        provider, _ = _provider(tmp_path, executable="claude")
        assert provider.is_installed()
        assert provider.is_configured()

    def test_is_configured_false_when_executable_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.providers.claude_cli._resolve_claude", lambda: None
        )
        provider, _ = _provider(tmp_path, executable=None)
        assert not provider.is_installed()
        assert not provider.is_configured()

    def test_public_view_exposes_installed_flag(self, tmp_path: Path) -> None:
        provider, _ = _provider(tmp_path, executable="claude")
        view = provider.public_view()
        assert view["installed"] is True
        assert view["auth_type"] == "subprocess"


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


class TestDisconnect:
    def test_disconnect_does_not_logout_cli(self, tmp_path: Path) -> None:
        """The user might be using claude outside AutoApply -- we
        intentionally don't shell out to ``claude logout``."""
        provider, _ = _provider(tmp_path, executable="claude")
        # No-op: nothing to assert other than "doesn't raise".
        provider.disconnect()

    def test_disconnect_removes_stale_breadcrumb(self, tmp_path: Path) -> None:
        from src.providers.base import ProviderCredentials

        provider, store = _provider(tmp_path, executable="claude")
        store.set(
            ProviderCredentials(
                provider_id="claude-cli",
                auth_type=AuthType.SUBPROCESS,
                secret={"breadcrumb": True},
            )
        )
        provider.disconnect()
        assert store.get("claude-cli") is None


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------


class TestTestConnection:
    def test_missing_executable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.providers.claude_cli._resolve_claude", lambda: None
        )
        provider, _ = _provider(tmp_path, executable=None)
        result = provider.test_connection()
        assert result.ok is False
        assert "not found" in result.detail.lower()

    def test_version_ok(self, tmp_path: Path) -> None:
        def fake_version(executable: str) -> tuple[int, str]:
            assert executable == "claude"
            return 0, "claude 1.42.0\n"

        provider, _ = _provider(tmp_path, version_runner=fake_version)
        result = provider.test_connection()
        assert result.ok is True
        assert "1.42.0" in result.detail
        assert result.latency_ms >= 0

    def test_version_non_zero(self, tmp_path: Path) -> None:
        def fake_version(executable: str) -> tuple[int, str]:
            return 1, "could not initialize"

        provider, _ = _provider(tmp_path, version_runner=fake_version)
        result = provider.test_connection()
        assert result.ok is False
        assert "could not initialize" in result.detail

    def test_version_raises(self, tmp_path: Path) -> None:
        def fake_version(executable: str) -> tuple[int, str]:
            raise RuntimeError("permission denied")

        provider, _ = _provider(tmp_path, version_runner=fake_version)
        result = provider.test_connection()
        assert result.ok is False
        assert "permission denied" in result.detail


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


class TestGenerate:
    def test_generate_delegates_to_injected_callable(self, tmp_path: Path) -> None:
        captured: dict[str, object] = {}

        def fake(
            prompt: str,
            *,
            system: str = "",
            timeout: int = 120,
            output_format: str = "text",
        ) -> str:
            captured["prompt"] = prompt
            captured["system"] = system
            captured["timeout"] = timeout
            captured["output_format"] = output_format
            return "PONG"

        provider, _ = _provider(tmp_path, generator=fake)
        out = provider.generate("ping", system="be terse", timeout=42)
        assert out == "PONG"
        assert captured == {
            "prompt": "ping",
            "system": "be terse",
            "timeout": 42,
            "output_format": "text",
        }

    def test_generate_threads_output_format_json(self, tmp_path: Path) -> None:
        """Regression guard for the P1 review finding -- the registry
        bridge must forward output_format so claude_generate switches
        to --output-format json."""
        captured: dict[str, object] = {}

        def fake(
            prompt: str,
            *,
            system: str = "",
            timeout: int = 120,
            output_format: str = "text",
        ) -> str:
            captured["output_format"] = output_format
            return '{"ok": true}'

        provider, _ = _provider(tmp_path, generator=fake)
        provider.generate("ping", output_format="json")
        assert captured["output_format"] == "json"

    def test_generate_raises_when_not_installed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.providers.claude_cli._resolve_claude", lambda: None
        )
        provider, _ = _provider(tmp_path, executable=None)
        with pytest.raises(ProviderError, match="not found"):
            provider.generate("hi")

    def test_generate_wraps_llm_error(self, tmp_path: Path) -> None:
        def fake(
            prompt: str,
            *,
            system: str = "",
            timeout: int = 120,
            output_format: str = "text",
        ) -> str:
            raise LLMError("upstream timeout")

        provider, _ = _provider(tmp_path, generator=fake)
        with pytest.raises(ProviderError, match="upstream timeout"):
            provider.generate("hi")


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


class TestRegistryWiring:
    def teardown_method(self) -> None:
        reset_default_registry()

    def test_singleton_registers_claude_cli(self) -> None:
        registry = get_registry()
        assert "claude-cli" in registry.ids()
        provider = registry.get("claude-cli")
        assert isinstance(provider, ClaudeCliProvider)

    def test_register_explicitly(self, tmp_path: Path) -> None:
        registry = ProviderRegistry(store=CredentialStore(path=tmp_path / "c.json"))
        registry.register(ClaudeCliProvider)
        assert "claude-cli" in registry.ids()
