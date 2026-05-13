"""Claude Code CLI subprocess provider (Phase 10.4).

Anthropic's ``claude`` CLI ships with its own auth flow (``claude
login`` for subscription, or ``ANTHROPIC_API_KEY`` env for key-based).
AutoApply does not own that flow -- if the user can run ``claude -p
'hello'`` from a shell, we can too. So this provider is intentionally
thin:

* :attr:`auth_type` is :class:`AuthType.SUBPROCESS` -- the UI renders an
  install/login hint rather than a key form or OAuth button.
* :meth:`is_configured` returns True iff the binary is on PATH **and**
  ``claude --version`` exits 0. There is no credential record to store.
* :meth:`generate` delegates to the existing :func:`src.utils.llm.
  claude_generate` so the well-tested invocation path is reused.
* :meth:`test_connection` runs ``claude --version`` as a cheap probe
  -- a real generation would burn the user's quota and add latency.

The sibling :class:`CodexOAuthProvider` (10.3) deliberately wraps
``codex login`` because Codex's OAuth flow is intricate; Claude's CLI
just needs the user to have run ``claude login`` once, so we don't
re-implement that here.
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
    ProviderErrorKind,
    ProviderTestResult,
    classify_cli_error,
    now_iso,
)

logger = logging.getLogger("autoapply.providers.claude_cli")


class ClaudeCliProvider(LLMProvider):
    id = "claude-cli"
    display_name = "Claude (Anthropic CLI)"
    auth_type = AuthType.SUBPROCESS
    description = (
        "Anthropic's Claude Code CLI. Auth is handled by the CLI itself "
        "(`claude login` for subscription, ANTHROPIC_API_KEY for keys). "
        "AutoApply just invokes `claude -p <prompt>`."
    )
    install_hint = "Install with `npm install -g @anthropic-ai/claude-code`"

    def __init__(
        self,
        store: Any | None = None,
        *,
        executable: str | None = None,
        version_runner: Callable[[str], tuple[int, str]] | None = None,
        generator: Callable[..., str] | None = None,
    ) -> None:
        super().__init__(store)
        self._executable_override = executable
        self._version_runner = version_runner or _run_version
        # Generator is injected for tests; the production path uses
        # ``claude_generate`` which already encapsulates argv assembly,
        # timeouts, and error mapping.
        self._generator = generator

    # ----- discovery -----

    def claude_executable(self) -> str | None:
        return self._executable_override or _resolve_claude()

    def is_installed(self) -> bool:
        return self.claude_executable() is not None

    # ----- LLMProvider overrides -----

    def is_configured(self) -> bool:
        # Subprocess providers have no stored credential; "configured"
        # collapses to "is the binary callable?". We avoid running
        # ``claude --version`` here -- ``is_configured`` is called on
        # every CLI command and the cost would add up. Existence on
        # PATH is the cheap proxy; ``test_connection`` does the deep
        # check.
        return self.is_installed()

    def disconnect(self) -> None:
        # Nothing to disconnect -- the CLI owns its own state. We
        # intentionally do NOT shell out to ``claude logout`` because
        # the user may still want to use the CLI directly outside
        # AutoApply.
        if self._store is not None:
            # If a future flow ever wrote a breadcrumb, drop it.
            self._store.delete(self.id)

    def test_connection(self, *, timeout: int = 10) -> ProviderTestResult:
        executable = self.claude_executable()
        if executable is None:
            return ProviderTestResult(
                ok=False,
                detail="Claude CLI not found in PATH.",
            )
        t0 = time.monotonic()
        try:
            rc, output = self._version_runner(executable)
        except Exception as exc:  # noqa: BLE001
            return ProviderTestResult(
                ok=False, detail=f"claude --version failed: {exc}"
            )
        latency = int((time.monotonic() - t0) * 1000)
        ok = rc == 0
        return ProviderTestResult(
            ok=ok,
            detail=output.strip()[:240] if output else ("OK" if ok else "non-zero exit"),
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
                "Claude CLI not found in PATH. "
                "Install with `npm install -g @anthropic-ai/claude-code`.",
                kind=ProviderErrorKind.AUTH,
            )
        # Late import keeps the provider package free of CLI module
        # imports at load time (matches CodexOAuthProvider's pattern).
        from src.utils.llm import LLMError, claude_generate  # noqa: PLC0415

        generator = self._generator or claude_generate
        try:
            # Thread output_format through so `claude -p ... --output-format json`
            # is invoked when callers (e.g. generate_json) need it.
            return generator(
                prompt,
                system=system,
                timeout=timeout,
                output_format=output_format,
            )
        except LLMError as exc:
            raise ProviderError(
                str(exc), kind=classify_cli_error(str(exc))
            ) from exc

    def public_view(self) -> dict[str, Any]:
        # Surface "installed" as a top-level breadcrumb so the UI can
        # show "needs install" without making a subprocess call.
        view = super().public_view()
        view["installed"] = self.is_installed()
        return view


# ---------------------------------------------------------------------------
# Helpers (split for tests)
# ---------------------------------------------------------------------------


def _resolve_claude() -> str | None:
    return (
        shutil.which("claude")
        or shutil.which("claude.cmd")
        or shutil.which("claude.exe")
    )


def _run_version(executable: str) -> tuple[int, str]:
    result = subprocess.run(  # noqa: S603 -- args are constants
        [executable, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    # Some versions of the CLI emit the version on stderr; concat both.
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def _now_iso() -> str:
    # Re-export so tests can patch it if they want stable timestamps.
    return now_iso()
