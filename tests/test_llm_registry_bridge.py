"""Tests for the Phase 10.5 registry bridge in ``src.utils.llm``.

The bridge lets ``generate_text`` dispatch to Phase 10 registered
providers when they're configured, falling back to the legacy CLI
helpers when they're not. We exercise both paths plus the normalize
relaxation that accepts new provider ids.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.providers.base import (
    AuthType,
    LLMProvider,
    ProviderCredentials,
    ProviderError,
    ProviderTestResult,
)
from src.providers.registry import ProviderRegistry, reset_default_registry
from src.providers.store import CredentialStore
from src.utils.llm import (
    LLMError,
    _dispatch_via_registry,
    _normalize_provider,
    generate_text,
)

# ---------------------------------------------------------------------------
# Tiny in-memory provider for the bridge tests
# ---------------------------------------------------------------------------


class _ScriptedProvider(LLMProvider):
    id = "scripted"
    display_name = "Scripted"
    auth_type = AuthType.API_KEY

    response: str = "scripted-output"
    raise_on_generate: BaseException | None = None

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
        if self.raise_on_generate is not None:
            raise self.raise_on_generate
        return self.response


def _install_singleton(
    tmp_path: Path,
    *,
    configured: bool = True,
    response: str = "scripted-output",
    raise_on_generate: BaseException | None = None,
) -> ProviderRegistry:
    """Replace the process-wide registry with one carrying _ScriptedProvider."""
    reset_default_registry()
    store = CredentialStore(path=tmp_path / "creds.json")
    if configured:
        store.set(
            ProviderCredentials(
                provider_id="scripted",
                auth_type=AuthType.API_KEY,
                secret={"api_key": "sk-test"},
            )
        )
    registry = ProviderRegistry(store=store)
    registry.register(_ScriptedProvider)

    # Mutate behavior on the singleton instance.
    instance = registry.get("scripted")
    assert isinstance(instance, _ScriptedProvider)
    instance.response = response
    instance.raise_on_generate = raise_on_generate

    # Stash the registry as the default so `get_registry()` returns it.
    import src.providers.registry as registry_module

    registry_module._default_registry = registry
    return registry


# ---------------------------------------------------------------------------
# _dispatch_via_registry
# ---------------------------------------------------------------------------


class TestDispatchViaRegistry:
    def teardown_method(self) -> None:
        reset_default_registry()

    def test_returns_none_when_provider_unknown(self, tmp_path: Path) -> None:
        _install_singleton(tmp_path)
        result = _dispatch_via_registry(
            "no-such-provider", "hi", system="", timeout=10, output_format="text"
        )
        assert result is None

    def test_returns_none_when_provider_not_configured(self, tmp_path: Path) -> None:
        _install_singleton(tmp_path, configured=False)
        result = _dispatch_via_registry(
            "scripted", "hi", system="", timeout=10, output_format="text"
        )
        assert result is None

    def test_returns_provider_output(self, tmp_path: Path) -> None:
        _install_singleton(tmp_path, response="hello back")
        result = _dispatch_via_registry(
            "scripted", "hi", system="", timeout=10, output_format="text"
        )
        assert result == "hello back"

    def test_provider_error_becomes_llm_error(self, tmp_path: Path) -> None:
        _install_singleton(
            tmp_path, raise_on_generate=ProviderError("rate limited")
        )
        with pytest.raises(LLMError, match="rate limited"):
            _dispatch_via_registry(
                "scripted", "hi", system="", timeout=10, output_format="text"
            )

    def test_output_format_is_forwarded_to_provider(self, tmp_path: Path) -> None:
        """Regression guard for the P1 review finding: the bridge must
        thread output_format so CLI-backed providers can switch to
        --output-format json instead of returning prose."""

        captured: dict[str, str] = {}

        class _RecordingProvider(LLMProvider):
            id = "recording"
            display_name = "Recording"
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
                captured["output_format"] = output_format
                return "ok"

        reset_default_registry()
        store = CredentialStore(path=tmp_path / "creds.json")
        store.set(
            ProviderCredentials(
                provider_id="recording",
                auth_type=AuthType.API_KEY,
                secret={"api_key": "sk"},
            )
        )
        registry = ProviderRegistry(store=store)
        registry.register(_RecordingProvider)
        import src.providers.registry as registry_module

        registry_module._default_registry = registry

        _dispatch_via_registry(
            "recording", "hi", system="", timeout=10, output_format="json"
        )
        assert captured == {"output_format": "json"}


# ---------------------------------------------------------------------------
# generate_text end-to-end
# ---------------------------------------------------------------------------


class TestGenerateTextUsesRegistry:
    def teardown_method(self) -> None:
        reset_default_registry()

    def test_uses_registry_provider_when_configured(self, tmp_path: Path) -> None:
        _install_singleton(tmp_path, response="from-registry")
        out = generate_text(
            "hello",
            config={"llm": {"primary_provider": "scripted", "allow_fallback": False}},
        )
        assert out == "from-registry"

    def test_falls_back_to_legacy_cli_when_registry_silent(
        self, tmp_path: Path
    ) -> None:
        # No registry provider matches "claude-cli" because we replaced
        # the singleton with one that only knows "scripted".
        _install_singleton(tmp_path)

        completed = type(
            "Completed", (), {"returncode": 0, "stdout": "from-cli", "stderr": ""}
        )()
        with (
            patch(
                "src.utils.llm._resolve_executable",
                return_value=r"C:\tools\claude.exe",
            ),
            patch("src.utils.llm.subprocess.run", return_value=completed),
        ):
            out = generate_text(
                "hi",
                config={
                    "llm": {
                        "primary_provider": "claude-cli",
                        "allow_fallback": False,
                    }
                },
            )
        assert out == "from-cli"

    def test_registry_failure_triggers_fallback_provider(
        self, tmp_path: Path
    ) -> None:
        """When the configured primary errors, the LLM helper should
        try the fallback. We verify the fallback path runs by raising
        in the registry and letting the legacy claude path answer."""
        _install_singleton(
            tmp_path, raise_on_generate=ProviderError("registry boom")
        )

        completed = type(
            "Completed",
            (),
            {"returncode": 0, "stdout": "from-fallback", "stderr": ""},
        )()
        with (
            patch(
                "src.utils.llm._resolve_executable",
                return_value=r"C:\tools\claude.exe",
            ),
            patch("src.utils.llm.subprocess.run", return_value=completed),
        ):
            out = generate_text(
                "hi",
                config={
                    "llm": {
                        "primary_provider": "scripted",
                        "fallback_provider": "claude-cli",
                        "allow_fallback": True,
                    }
                },
            )
        assert out == "from-fallback"


# ---------------------------------------------------------------------------
# _normalize_provider
# ---------------------------------------------------------------------------


class TestNormalizeProvider:
    def teardown_method(self) -> None:
        reset_default_registry()

    def test_accepts_legacy_cli_provider(self, tmp_path: Path) -> None:
        _install_singleton(tmp_path)
        assert _normalize_provider("claude-cli", role="primary") == "claude-cli"

    def test_accepts_registry_provider_id(self, tmp_path: Path) -> None:
        _install_singleton(tmp_path)
        assert _normalize_provider("scripted", role="primary") == "scripted"

    def test_rejects_unknown_id(self, tmp_path: Path) -> None:
        _install_singleton(tmp_path)
        with pytest.raises(ValueError, match="Invalid"):
            _normalize_provider("nope-cli", role="primary")
