"""Tests for the Codex OAuth provider (Phase 10.3).

The Codex provider wraps the official ``codex`` CLI rather than
re-implementing OAuth. These tests exercise:

* the stdout parser (URL + device-code extraction, browser auto-open
  hook, completion / error event ordering),
* :class:`CodexOAuthProvider` lifecycle (start_login, finalize_login,
  disconnect, test_connection),
* registry wiring (the singleton should now ship the provider).

We never spawn the real ``codex`` binary -- a ``FakeProcess`` simulates
stdout streams and exit codes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest

from src.providers.base import AuthType, ProviderError
from src.providers.codex import (
    CodexLoginEvent,
    CodexLoginSession,
    CodexOAuthProvider,
    _looks_like_login_url,
    _looks_logged_out,
)
from src.providers.registry import ProviderRegistry, get_registry, reset_default_registry
from src.providers.store import CredentialStore

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeProcess:
    """Stand-in for the subprocess.Popen handle our session expects."""

    def __init__(
        self,
        lines: Iterable[str],
        *,
        return_code: int = 0,
        wait_raises: BaseException | None = None,
    ) -> None:
        self.stdout = list(lines)
        self._rc = return_code
        self._wait_raises = wait_raises
        self.terminated = False
        self.killed = False
        self.pid = 4242

    def wait(self, timeout: float | None = None) -> int:  # noqa: ARG002
        if self._wait_raises is not None:
            raise self._wait_raises
        return self._rc

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def make_factory(process: FakeProcess) -> Callable[[list[str]], FakeProcess]:
    captured: dict[str, list[str]] = {"cmd": []}

    def _factory(cmd: list[str]) -> FakeProcess:
        captured["cmd"] = list(cmd)
        return process

    _factory.captured = captured  # type: ignore[attr-defined]
    return _factory


# ---------------------------------------------------------------------------
# URL / logout heuristics
# ---------------------------------------------------------------------------


class TestLoginUrlHeuristics:
    def test_oauth_url_recognised(self) -> None:
        assert _looks_like_login_url(
            "https://auth.openai.com/oauth/authorize?client_id=abc"
        )

    def test_device_url_recognised(self) -> None:
        assert _looks_like_login_url("https://example.com/device?code=ABCD")

    def test_docs_url_filtered(self) -> None:
        assert not _looks_like_login_url("https://platform.openai.com/docs/codex")

    def test_github_url_filtered(self) -> None:
        assert not _looks_like_login_url("https://github.com/openai/codex")


class TestLoggedOutHeuristics:
    @pytest.mark.parametrize(
        "out",
        ["", "Not logged in.", "no credentials found", "Please log in to continue."],
    )
    def test_recognises_logged_out_phrasing(self, out: str) -> None:
        assert _looks_logged_out(out)

    def test_logged_in_phrasing(self) -> None:
        assert not _looks_logged_out("Logged in as user@example.com")


# ---------------------------------------------------------------------------
# CodexLoginSession
# ---------------------------------------------------------------------------


class TestCodexLoginSession:
    def test_extracts_url_and_emits_complete_event(self) -> None:
        process = FakeProcess(
            [
                "Starting Codex login flow...",
                "Open this URL to continue: https://auth.openai.com/device?code=ABCD",
                "Waiting for browser...",
                "Login successful.",
            ],
            return_code=0,
        )
        events: list[CodexLoginEvent] = []
        opened: list[str] = []
        session = CodexLoginSession(
            executable="codex",
            process_factory=make_factory(process),
            on_event=events.append,
            browser_opener=lambda url: opened.append(url) or True,
        )
        session.start()
        assert session.wait(timeout=2) == 0
        assert session.url == "https://auth.openai.com/device?code=ABCD"
        assert opened == [session.url]

        types = [e.type for e in events]
        assert "url" in types
        assert "browser_opened" in types
        assert types[-1] == "complete"

    def test_extracts_device_code(self) -> None:
        process = FakeProcess(
            [
                "Open https://auth.openai.com/device",
                "Enter code: ABC-1234",
                "Login succeeded.",
            ],
            return_code=0,
        )
        events: list[CodexLoginEvent] = []
        session = CodexLoginSession(
            executable="codex",
            device_auth=True,
            auto_open_browser=False,
            process_factory=make_factory(process),
            on_event=events.append,
        )
        session.start()
        assert session.wait(timeout=2) == 0
        assert session.code == "ABC-1234"
        assert any(e.type == "code" for e in events)

    def test_device_auth_flag_passed_to_subprocess(self) -> None:
        process = FakeProcess(["done"], return_code=0)
        factory = make_factory(process)
        session = CodexLoginSession(
            executable="codex",
            device_auth=True,
            auto_open_browser=False,
            process_factory=factory,
        )
        session.start()
        session.wait(timeout=2)
        assert factory.captured["cmd"] == ["codex", "login", "--device-auth"]

    def test_no_device_auth_flag_by_default(self) -> None:
        process = FakeProcess(["done"], return_code=0)
        factory = make_factory(process)
        session = CodexLoginSession(
            executable="codex",
            auto_open_browser=False,
            process_factory=factory,
        )
        session.start()
        session.wait(timeout=2)
        assert factory.captured["cmd"] == ["codex", "login"]

    def test_browser_opener_failure_does_not_crash(self) -> None:
        process = FakeProcess(
            ["Open this URL: https://auth.openai.com/oauth"], return_code=0
        )
        events: list[CodexLoginEvent] = []
        session = CodexLoginSession(
            executable="codex",
            process_factory=make_factory(process),
            on_event=events.append,
            browser_opener=lambda url: (_ for _ in ()).throw(RuntimeError("nope")),
        )
        session.start()
        session.wait(timeout=2)
        # We should still surface the URL plus an output line about the
        # failure -- but not crash.
        assert session.url is not None
        assert any("browser auto-open raised" in e.message for e in events)

    def test_non_zero_exit_emits_error_event(self) -> None:
        process = FakeProcess(
            ["Open https://auth.openai.com/oauth", "Login canceled."], return_code=2
        )
        events: list[CodexLoginEvent] = []
        session = CodexLoginSession(
            executable="codex",
            auto_open_browser=False,
            process_factory=make_factory(process),
            on_event=events.append,
        )
        session.start()
        rc = session.wait(timeout=2)
        assert rc == 2
        assert events[-1].type == "error"
        assert events[-1].detail["return_code"] == 2

    def test_cannot_start_twice(self) -> None:
        process = FakeProcess([], return_code=0)
        session = CodexLoginSession(
            executable="codex",
            process_factory=make_factory(process),
            auto_open_browser=False,
        )
        session.start()
        with pytest.raises(ProviderError):
            session.start()

    def test_cancel_before_start_is_noop(self) -> None:
        session = CodexLoginSession(
            executable="codex",
            process_factory=make_factory(FakeProcess([], return_code=0)),
        )
        # No exception even though .start() was never called.
        session.cancel()

    def test_cancel_terminates_process(self) -> None:
        process = FakeProcess(["streaming..."], return_code=0)
        session = CodexLoginSession(
            executable="codex",
            auto_open_browser=False,
            process_factory=make_factory(process),
        )
        session.start()
        session.cancel()
        assert process.terminated is True

    def test_docs_urls_are_filtered_out(self) -> None:
        process = FakeProcess(
            [
                "See https://platform.openai.com/docs/codex for help.",
                "Open this URL: https://auth.openai.com/device?code=X",
                "Done.",
            ],
            return_code=0,
        )
        session = CodexLoginSession(
            executable="codex",
            auto_open_browser=False,
            process_factory=make_factory(process),
        )
        session.start()
        session.wait(timeout=2)
        # The docs URL must be skipped in favor of the real OAuth URL.
        assert session.url == "https://auth.openai.com/device?code=X"


# ---------------------------------------------------------------------------
# CodexOAuthProvider lifecycle
# ---------------------------------------------------------------------------


def _make_provider(
    tmp_path: Path,
    *,
    executable: str | None = "codex",
    status_runner: Callable[..., tuple[int, str]] | None = None,
    logout_runner: Callable[..., tuple[int, str]] | None = None,
    login_session_factory: Callable[..., CodexLoginSession] | None = None,
) -> tuple[CodexOAuthProvider, CredentialStore]:
    store = CredentialStore(path=tmp_path / "creds.json")
    provider = CodexOAuthProvider(
        store=store,
        codex_executable=executable,
        status_runner=status_runner,
        logout_runner=logout_runner,
        login_session_factory=login_session_factory,
    )
    return provider, store


class TestCodexProviderMetadata:
    def test_class_attributes(self) -> None:
        assert CodexOAuthProvider.id == "codex-cli"
        assert CodexOAuthProvider.auth_type is AuthType.OAUTH
        assert "Codex" in CodexOAuthProvider.display_name


class TestStartLogin:
    def test_raises_when_codex_not_installed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pretend the system PATH has no codex binary.
        monkeypatch.setattr("src.providers.codex._resolve_codex", lambda: None)
        provider, _ = _make_provider(tmp_path, executable=None)
        with pytest.raises(ProviderError, match="not found"):
            provider.start_login()

    def test_returns_started_session(self, tmp_path: Path) -> None:
        process = FakeProcess(["Login successful."], return_code=0)
        captured: dict[str, Any] = {}

        def factory(**kwargs: Any) -> CodexLoginSession:
            captured.update(kwargs)
            return CodexLoginSession(
                executable=kwargs["executable"],
                device_auth=kwargs.get("device_auth", False),
                auto_open_browser=kwargs.get("auto_open_browser", True),
                on_event=kwargs.get("on_event"),
                process_factory=make_factory(process),
                browser_opener=lambda url: True,
            )

        provider, _ = _make_provider(tmp_path, login_session_factory=factory)
        session = provider.start_login(device_auth=True, auto_open_browser=False)
        assert captured["executable"] == "codex"
        assert captured["device_auth"] is True
        assert captured["auto_open_browser"] is False
        # Session was started -- wait succeeds quickly with the fake.
        assert session.wait(timeout=2) == 0


class TestFinalizeLogin:
    def _completed_session(
        self, *, return_code: int = 0
    ) -> CodexLoginSession:
        process = FakeProcess(["ok"], return_code=return_code)
        session = CodexLoginSession(
            executable="codex",
            auto_open_browser=False,
            process_factory=make_factory(process),
        )
        session.start()
        session.wait(timeout=2)
        return session

    def test_persists_breadcrumb(self, tmp_path: Path) -> None:
        provider, store = _make_provider(tmp_path)
        session = self._completed_session()
        creds = provider.finalize_login(session, metadata={"account": "user@x"})
        assert creds.auth_type is AuthType.OAUTH
        assert creds.metadata == {"account": "user@x"}
        # Breadcrumb is not empty (so is_configured() returns True).
        assert creds.secret
        # But contains no actual secret values.
        assert "token" not in creds.secret
        assert "refresh_token" not in creds.secret
        # Round-trip through the store.
        assert store.get("codex-cli") == creds
        assert provider.is_configured()

    def test_refuses_unfinished_session(self, tmp_path: Path) -> None:
        provider, _ = _make_provider(tmp_path)
        process = FakeProcess(["..."], return_code=0)
        session = CodexLoginSession(
            executable="codex",
            auto_open_browser=False,
            process_factory=make_factory(process),
        )
        # Note: never called .wait(), so return_code is None.
        with pytest.raises(ProviderError, match="has not completed"):
            provider.finalize_login(session)

    def test_refuses_failed_session(self, tmp_path: Path) -> None:
        provider, _ = _make_provider(tmp_path)
        session = self._completed_session(return_code=2)
        with pytest.raises(ProviderError, match="exit code 2"):
            provider.finalize_login(session)

    def test_finalize_without_store_raises(self) -> None:
        provider = CodexOAuthProvider(store=None, codex_executable="codex")
        process = FakeProcess(["ok"], return_code=0)
        session = CodexLoginSession(
            executable="codex",
            auto_open_browser=False,
            process_factory=make_factory(process),
        )
        session.start()
        session.wait(timeout=2)
        with pytest.raises(ProviderError, match="without a store"):
            provider.finalize_login(session)


class TestDisconnect:
    def test_runs_codex_logout_and_drops_breadcrumb(self, tmp_path: Path) -> None:
        calls: list[tuple[str, ...]] = []

        def logout(executable: str, *args: str) -> tuple[int, str]:
            calls.append((executable, *args))
            return 0, "logged out"

        provider, store = _make_provider(tmp_path, logout_runner=logout)
        session = TestFinalizeLogin()._completed_session()
        provider.finalize_login(session)
        assert provider.is_configured()
        provider.disconnect()
        assert calls and calls[0][0] == "codex"
        assert store.get("codex-cli") is None

    def test_logout_failure_does_not_block_disconnect(
        self, tmp_path: Path
    ) -> None:
        def logout(executable: str, *args: str) -> tuple[int, str]:
            raise RuntimeError("network down")

        provider, store = _make_provider(tmp_path, logout_runner=logout)
        session = TestFinalizeLogin()._completed_session()
        provider.finalize_login(session)
        # Even though codex logout raised, the local breadcrumb must be gone.
        provider.disconnect()
        assert store.get("codex-cli") is None


class TestTestConnection:
    def test_missing_codex_returns_not_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.providers.codex._resolve_codex", lambda: None)
        provider, _ = _make_provider(tmp_path, executable=None)
        result = provider.test_connection()
        assert result.ok is False
        assert "not found" in result.detail.lower()

    def test_status_ok(self, tmp_path: Path) -> None:
        def status(executable: str, *args: str) -> tuple[int, str]:
            assert args == ("login", "status")
            return 0, "Logged in as user@example.com"

        provider, store = _make_provider(tmp_path, status_runner=status)
        session = TestFinalizeLogin()._completed_session()
        provider.finalize_login(session)
        result = provider.test_connection()
        assert result.ok is True
        # verified_at gets bumped on success.
        creds = store.get("codex-cli")
        assert creds is not None and creds.verified_at is not None

    def test_status_logged_out(self, tmp_path: Path) -> None:
        def status(executable: str, *args: str) -> tuple[int, str]:
            return 0, "Not logged in."

        provider, store = _make_provider(tmp_path, status_runner=status)
        session = TestFinalizeLogin()._completed_session()
        provider.finalize_login(session)
        result = provider.test_connection()
        assert result.ok is False
        creds = store.get("codex-cli")
        assert creds is not None and creds.last_test_error

    def test_status_exception_returns_not_ok(self, tmp_path: Path) -> None:
        def status(executable: str, *args: str) -> tuple[int, str]:
            raise RuntimeError("subprocess crash")

        provider, _ = _make_provider(tmp_path, status_runner=status)
        result = provider.test_connection()
        assert result.ok is False
        assert "subprocess crash" in result.detail


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


class TestRegistryWiring:
    def teardown_method(self) -> None:
        reset_default_registry()

    def test_singleton_registers_codex(self) -> None:
        registry = get_registry()
        assert "codex-cli" in registry.ids()
        provider = registry.get("codex-cli")
        assert isinstance(provider, CodexOAuthProvider)

    def test_explicit_registry_can_register_codex(self, tmp_path: Path) -> None:
        registry = ProviderRegistry(store=CredentialStore(path=tmp_path / "c.json"))
        registry.register(CodexOAuthProvider)
        assert "codex-cli" in registry.ids()
