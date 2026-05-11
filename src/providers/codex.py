"""Codex CLI subprocess provider (Phase 10.3, rev. 2).

This is a thin subprocess wrapper around OpenAI's ``codex`` CLI --
intentionally the same shape as :class:`ClaudeCliProvider`. Both let
AutoApply orchestrate an already-installed agent CLI; AutoApply does
NOT own the OAuth dance, does NOT store tokens, and does NOT impose
its own client on top of the CLI. The user runs ``codex login`` once
themselves; we just call ``codex exec``.

This is deliberately separate from the (currently-unimplemented)
notion of a native Codex OAuth provider where AutoApply would speak
to OpenAI's API directly using OAuth tokens. Those two paths are
architecturally different:

  * **Subprocess tool** (this file) -- AutoApply is the orchestrator,
    Codex CLI is the agent. Auth lives in the CLI.
  * **OAuth provider** (future work) -- AutoApply implements a Codex
    HTTP client and owns the OAuth flow + tokens.

Confusing the two leaks the CLI's lifecycle into the provider layer
(start_login / finalize_login / event streaming, etc.) and pretends
we have a native client when we don't.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from collections.abc import Callable
from typing import Any

from src.providers.base import (
    AuthType,
    LLMProvider,
    ProviderError,
    ProviderTestResult,
)

logger = logging.getLogger("autoapply.providers.codex")


class CodexCliProvider(LLMProvider):
    id = "codex-cli"
    display_name = "Codex (OpenAI CLI)"
    auth_type = AuthType.SUBPROCESS
    description = (
        "OpenAI's Codex CLI. Auth is handled by the CLI itself "
        "(`codex login` for ChatGPT subscription or OPENAI_API_KEY). "
        "AutoApply just invokes `codex exec` -- same lifecycle as the "
        "Claude Code CLI provider."
    )
    install_hint = "Install with `npm install -g @openai/codex`"

    def __init__(
        self,
        store: Any | None = None,
        *,
        executable: str | None = None,
        version_runner: Callable[[str], tuple[int, str]] | None = None,
        status_runner: Callable[[str], tuple[int, str]] | None = None,
        generator: Callable[..., str] | None = None,
    ) -> None:
        super().__init__(store)
        self._executable_override = executable
        self._version_runner = version_runner or _run_version
        # ``codex login status`` is what distinguishes "installed" from
        # "actually authenticated". We probe it in test_connection so
        # the Settings UI can surface "needs login" before a real
        # generation hits the failure path.
        self._status_runner = status_runner or _run_login_status
        # Generator injected for tests; production path uses
        # ``codex_generate`` from src.utils.llm which already handles
        # argv assembly, output-file plumbing, and timeouts.
        self._generator = generator

    # ----- discovery -----

    def codex_executable(self) -> str | None:
        return self._executable_override or _resolve_codex()

    def is_installed(self) -> bool:
        return self.codex_executable() is not None

    # ----- LLMProvider overrides -----

    def is_configured(self) -> bool:
        # Same semantic as ClaudeCliProvider: existence on PATH is the
        # cheap proxy. `test_connection` runs the deep probe.
        return self.is_installed()

    def disconnect(self) -> None:
        # The Codex CLI manages its own auth in ~/.codex/. We
        # deliberately do NOT shell out to ``codex logout`` because
        # the user might be using codex outside AutoApply. Only drop
        # any stale credential breadcrumb in our store.
        if self._store is not None:
            self._store.delete(self.id)

    def test_connection(self, *, timeout: int = 10) -> ProviderTestResult:
        """Deep probe: must distinguish 'binary on PATH' from 'logged in'.

        Order:
          1. Is the binary callable? (`codex --version`)
          2. Is the user actually authenticated? (`codex login status`)

        Without step 2 a user with codex installed but never run
        `codex login` would see "OK" here, only to have the first
        real generation fail later. We treat that "installed but
        unauthenticated" state as ok=False so the Settings UI can
        surface a 'needs login' hint.
        """
        executable = self.codex_executable()
        if executable is None:
            return ProviderTestResult(
                ok=False,
                detail="Codex CLI not found in PATH.",
            )

        t0 = time.monotonic()
        try:
            rc, output = self._version_runner(executable)
        except Exception as exc:  # noqa: BLE001
            return ProviderTestResult(
                ok=False,
                detail=f"codex --version failed: {exc}",
            )
        if rc != 0:
            return ProviderTestResult(
                ok=False,
                detail=output.strip()[:240] if output else "non-zero exit",
                latency_ms=int((time.monotonic() - t0) * 1000),
            )

        # Step 2: auth check.
        try:
            status_rc, status_output = self._status_runner(executable)
        except Exception as exc:  # noqa: BLE001
            # If `codex login status` itself crashes, fall back to the
            # version-only result rather than locking the user out --
            # better to let them try than refuse pre-emptively.
            return ProviderTestResult(
                ok=True,
                detail=(
                    f"{output.strip()[:200]} (auth probe failed: {exc})"
                ),
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        latency = int((time.monotonic() - t0) * 1000)

        if status_rc != 0 or _looks_logged_out(status_output):
            return ProviderTestResult(
                ok=False,
                detail=(
                    status_output.strip()[:240]
                    if status_output
                    else "codex is installed but not logged in. Run `codex login`."
                ),
                latency_ms=latency,
            )

        return ProviderTestResult(
            ok=True,
            detail=(status_output.strip()[:240] if status_output else "OK"),
            latency_ms=latency,
        )

    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        timeout: int = 120,
        output_format: str = "text",
    ) -> str:
        if not self.is_installed():
            raise ProviderError(
                "Codex CLI not found in PATH. "
                "Install with `npm install -g @openai/codex`."
            )
        # Late import: keeps the provider package free of CLI module
        # imports at load time and avoids a circular dep through
        # src.utils.llm -> src.core.config -> ...
        from src.utils.llm import LLMError, codex_generate  # noqa: PLC0415

        generator = self._generator or codex_generate
        try:
            return generator(
                prompt,
                system=system,
                timeout=timeout,
                output_format=output_format,
            )
        except LLMError as exc:
            raise ProviderError(str(exc)) from exc

    def public_view(self) -> dict[str, Any]:
        # Surface "installed" so the Web UI can render
        # "Available" / "Missing" badges without a subprocess call.
        view = super().public_view()
        view["installed"] = self.is_installed()
        return view


# ---------------------------------------------------------------------------
# Helpers (split for tests)
# ---------------------------------------------------------------------------


def _resolve_codex() -> str | None:
    return (
        shutil.which("codex")
        or shutil.which("codex.cmd")
        or shutil.which("codex.exe")
    )


def _run_version(executable: str) -> tuple[int, str]:
    result = subprocess.run(  # noqa: S603 -- args are constants
        [executable, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def _run_login_status(executable: str) -> tuple[int, str]:
    """Run ``codex login status`` and return (rc, combined-output)."""
    result = subprocess.run(  # noqa: S603 -- args are constants
        [executable, "login", "status"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def _looks_logged_out(output: str) -> bool:
    """Heuristic: does ``codex login status`` text suggest no auth?"""
    if not output:
        return True
    lowered = output.lower()
    return any(
        marker in lowered
        for marker in (
            "not logged in",
            "no credentials",
            "logged out",
            "please log in",
            "please run `codex login`",
        )
    )


# ---------------------------------------------------------------------------
# Backwards compatibility shim
# ---------------------------------------------------------------------------
#
# Earlier revisions of Phase 10 shipped a ``CodexOAuthProvider`` that
# wrapped ``codex login`` and persisted a "managed_by: codex-cli"
# breadcrumb. That conflated the CLI orchestrator role with a native
# OAuth client role. The CLI side now lives in CodexCliProvider above.
# Keep the old name as an alias so external imports (web UI, tests)
# that were written against the wrapper keep loading -- the alias
# raises a deprecation warning the first time it is touched and is
# scheduled for removal once the future OAuth provider lands.

CodexOAuthProvider = CodexCliProvider
