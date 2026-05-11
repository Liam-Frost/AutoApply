"""Tests for the Codex CLI subprocess provider (Phase 10.3 rev. 2).

Mirrors the Claude CLI subprocess provider tests — same shape because
both providers play the same architectural role (orchestrate an
agent CLI that owns its own auth). We never spawn the real ``codex``
binary; the provider exposes seams (``executable``, ``version_runner``,
``generator``) precisely for this purpose.

If/when a separate native ``CodexOAuthProvider`` lands (AutoApply
owns OAuth tokens + talks to OpenAI's API directly), its tests live
in their own file -- they're a fundamentally different surface.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from src.providers.base import AuthType, ProviderError
from src.providers.codex import CodexCliProvider, CodexOAuthProvider
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
    executable: str | None = "codex",
    version_runner: Callable[[str], tuple[int, str]] | None = None,
    status_runner: Callable[[str], tuple[int, str]] | None = None,
    generator: Callable[..., str] | None = None,
) -> tuple[CodexCliProvider, CredentialStore]:
    store = CredentialStore(path=tmp_path / "creds.json")
    # Default status runner: pretend the user is logged in. Tests that
    # care about logged-out state override this explicitly.
    def _default_status(_exe: str) -> tuple[int, str]:
        return 0, "Logged in as user@example.com"

    if status_runner is None:
        status_runner = _default_status
    return (
        CodexCliProvider(
            store=store,
            executable=executable,
            version_runner=version_runner,
            status_runner=status_runner,
            generator=generator,
        ),
        store,
    )


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_class_attributes(self) -> None:
        assert CodexCliProvider.id == "codex-cli"
        # Phase 10 rev 2: Codex CLI is a SUBPROCESS provider, NOT an
        # OAuth provider. The CLI manages its own auth via
        # `codex login`; AutoApply just calls `codex exec`.
        assert CodexCliProvider.auth_type is AuthType.SUBPROCESS
        assert "Codex" in CodexCliProvider.display_name
        assert "@openai/codex" in CodexCliProvider.install_hint

    def test_oauth_alias_points_at_cli_class(self) -> None:
        # Back-compat shim: keep the old import path resolving so
        # external code that referenced CodexOAuthProvider continues to
        # work while it migrates to the new name.
        assert CodexOAuthProvider is CodexCliProvider


# ---------------------------------------------------------------------------
# is_configured / is_installed
# ---------------------------------------------------------------------------


class TestInstallation:
    def test_is_configured_true_when_executable_present(
        self, tmp_path: Path
    ) -> None:
        provider, _ = _provider(tmp_path, executable="codex")
        assert provider.is_installed()
        assert provider.is_configured()

    def test_is_configured_false_when_executable_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.providers.codex._resolve_codex", lambda: None
        )
        provider, _ = _provider(tmp_path, executable=None)
        assert not provider.is_installed()
        assert not provider.is_configured()

    def test_public_view_exposes_installed_flag(self, tmp_path: Path) -> None:
        provider, _ = _provider(tmp_path, executable="codex")
        view = provider.public_view()
        assert view["installed"] is True
        assert view["auth_type"] == "subprocess"


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


class TestDisconnect:
    def test_disconnect_does_not_logout_cli(self, tmp_path: Path) -> None:
        """The user might be using codex outside AutoApply -- we
        intentionally do NOT shell out to ``codex logout``."""
        provider, _ = _provider(tmp_path, executable="codex")
        provider.disconnect()  # no-op; must not raise

    def test_disconnect_removes_stale_breadcrumb(self, tmp_path: Path) -> None:
        from src.providers.base import ProviderCredentials

        provider, store = _provider(tmp_path, executable="codex")
        # Old rev wrote a "managed_by: codex-cli" breadcrumb. Make sure
        # disconnect cleans up such stale records so they don't linger
        # after upgrade.
        store.set(
            ProviderCredentials(
                provider_id="codex-cli",
                auth_type=AuthType.SUBPROCESS,
                secret={"managed_by": "codex-cli"},
            )
        )
        provider.disconnect()
        assert store.get("codex-cli") is None


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------


class TestTestConnection:
    def test_missing_executable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.providers.codex._resolve_codex", lambda: None
        )
        provider, _ = _provider(tmp_path, executable=None)
        result = provider.test_connection()
        assert result.ok is False
        assert "not found" in result.detail.lower()

    def test_version_ok(self, tmp_path: Path) -> None:
        def fake_version(executable: str) -> tuple[int, str]:
            assert executable == "codex"
            return 0, "codex-cli 0.118.0\n"

        def fake_status(executable: str) -> tuple[int, str]:
            return 0, "Logged in as ada@example.com"

        provider, _ = _provider(
            tmp_path,
            version_runner=fake_version,
            status_runner=fake_status,
        )
        result = provider.test_connection()
        assert result.ok is True
        # Detail comes from `codex login status` (the deeper probe),
        # not `codex --version`, when the user is authenticated.
        assert "Logged in" in result.detail
        assert result.latency_ms >= 0

    def test_version_non_zero(self, tmp_path: Path) -> None:
        def fake_version(executable: str) -> tuple[int, str]:
            return 1, "boom"

        provider, _ = _provider(tmp_path, version_runner=fake_version)
        result = provider.test_connection()
        assert result.ok is False
        assert "boom" in result.detail

    def test_version_raises(self, tmp_path: Path) -> None:
        def fake_version(executable: str) -> tuple[int, str]:
            raise RuntimeError("denied")

        provider, _ = _provider(tmp_path, version_runner=fake_version)
        result = provider.test_connection()
        assert result.ok is False
        assert "denied" in result.detail

    def test_installed_but_not_logged_in_returns_not_ok(
        self, tmp_path: Path
    ) -> None:
        """Regression guard: a machine with codex on PATH but no
        `codex login` must NOT be reported as a working connection,
        otherwise the registry would dispatch generations that crash
        at runtime."""
        def fake_version(executable: str) -> tuple[int, str]:
            return 0, "codex-cli 0.118.0"

        def fake_status(executable: str) -> tuple[int, str]:
            return 0, "Not logged in. Please run `codex login`."

        provider, _ = _provider(
            tmp_path,
            version_runner=fake_version,
            status_runner=fake_status,
        )
        result = provider.test_connection()
        assert result.ok is False
        assert "logged in" in result.detail.lower() or "login" in result.detail.lower()

    def test_status_raises_falls_back_to_version_result(
        self, tmp_path: Path
    ) -> None:
        """If `codex login status` itself crashes, we don't lock the
        user out -- better to let the next real call surface a real
        error than refuse pre-emptively on a probe failure."""
        def fake_version(executable: str) -> tuple[int, str]:
            return 0, "codex-cli 0.118.0"

        def fake_status(executable: str) -> tuple[int, str]:
            raise RuntimeError("status probe blew up")

        provider, _ = _provider(
            tmp_path,
            version_runner=fake_version,
            status_runner=fake_status,
        )
        result = provider.test_connection()
        assert result.ok is True
        assert "auth probe failed" in result.detail


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
        """Regression guard: codex_generate appends a JSON-only prompt
        suffix when output_format=='json' -- the provider must
        forward that, not drop it."""
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
            "src.providers.codex._resolve_codex", lambda: None
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

    def test_singleton_registers_codex_cli(self) -> None:
        registry = get_registry()
        assert "codex-cli" in registry.ids()
        provider = registry.get("codex-cli")
        assert isinstance(provider, CodexCliProvider)
        # The registered instance must have auth_type=SUBPROCESS so the
        # web/CLI UI does not offer it a Connect/OAuth affordance.
        assert provider.auth_type is AuthType.SUBPROCESS

    def test_register_explicitly(self, tmp_path: Path) -> None:
        registry = ProviderRegistry(
            store=CredentialStore(path=tmp_path / "c.json")
        )
        registry.register(CodexCliProvider)
        assert "codex-cli" in registry.ids()
