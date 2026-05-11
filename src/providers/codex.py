"""Codex CLI provider with OAuth login.

We do not reimplement Codex's OAuth dance. Codex CLI ships its own
``codex login`` flow that handles client_id + endpoints + token
storage in ``~/.codex/``. Phase 10's Codex provider is a wrapper:

  * ``start_login()`` spawns ``codex login`` (or ``codex login
    --device-auth`` for headless flows) as a subprocess, streams its
    stdout/stderr line-by-line, parses out the user-facing URL and
    device code (if any), and emits structured events for the CLI /
    Web UI to render.
  * Once the subprocess exits with success, we drop a no-secret
    "breadcrumb" credential into our store so ``is_configured()`` can
    answer cheaply without re-shelling.
  * ``disconnect()`` runs ``codex logout`` and removes the breadcrumb.
  * ``generate()`` shells out via the existing ``codex_generate``
    helper in ``src.utils.llm``, so the agent loop sees the same
    surface as today.

The subprocess plumbing is split off into :class:`CodexLoginSession`
so unit tests can fake the process and exercise the stdout parser
without spawning a real ``codex``.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.providers.base import (
    AuthType,
    LLMProvider,
    ProviderCredentials,
    ProviderError,
    ProviderTestResult,
    now_iso,
)

logger = logging.getLogger("autoapply.providers.codex")

# Captures any http(s) URL surfaced by codex's login output.
_URL_RE = re.compile(r"https?://[^\s'\"<>]+")
# Best-effort device-code line scanner. Codex's exact phrasing is not
# pinned -- we capture any short alphanumeric token following common
# "code" markers and surface it; users will see the raw line too.
_CODE_RE = re.compile(
    r"(?:code|enter\s+code|verification[\s_-]*code)\s*[:=]?\s*([A-Z0-9-]{4,})",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Event stream
# ---------------------------------------------------------------------------


@dataclass
class CodexLoginEvent:
    """One step in the login flow, surfaced to the CLI / Web UI."""

    type: str  # 'output' | 'url' | 'code' | 'complete' | 'error' | 'browser_opened'
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "message": self.message, "detail": dict(self.detail)}


EventCallback = Callable[[CodexLoginEvent], None]


# ---------------------------------------------------------------------------
# Subprocess factory (split out for tests)
# ---------------------------------------------------------------------------


@dataclass
class _ProcessHandle:
    """Minimal duck type the session needs from a subprocess."""

    stdout: Any  # iterable of str
    wait: Callable[..., int]
    terminate: Callable[[], None]
    kill: Callable[[], None]
    pid: int = 0


def _default_process_factory(cmd: list[str]) -> _ProcessHandle:
    process = subprocess.Popen(  # noqa: S603 -- cmd is built from validated args
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    if process.stdout is None:
        raise ProviderError("Failed to capture codex login stdout.")
    return _ProcessHandle(
        stdout=process.stdout,
        wait=process.wait,
        terminate=process.terminate,
        kill=process.kill,
        pid=process.pid or 0,
    )


# ---------------------------------------------------------------------------
# Login session
# ---------------------------------------------------------------------------


class CodexLoginSession:
    """One in-progress ``codex login`` invocation.

    Lifecycle:
        session = CodexLoginSession(...)
        session.start()
        # Events flow through the on_event callback (or session.events).
        rc = session.wait(timeout=600)   # 0 == success
        session.cancel()                  # safe even after completion

    Attributes (read after :meth:`wait` returns):
        url:         the URL the user should open in a browser
        code:        the device code, if device-auth flow was used
        return_code: subprocess exit code, or None if still running
        events:      complete ordered list of CodexLoginEvent emitted
    """

    def __init__(
        self,
        *,
        executable: str | None = None,
        device_auth: bool = False,
        auto_open_browser: bool = True,
        on_event: EventCallback | None = None,
        process_factory: Callable[[list[str]], _ProcessHandle] | None = None,
        browser_opener: Callable[[str], bool] | None = None,
    ) -> None:
        self._executable = executable or _resolve_codex()
        self._device_auth = device_auth
        self._auto_open_browser = auto_open_browser
        self._on_event = on_event
        self._process_factory = process_factory or _default_process_factory
        self._browser_opener = browser_opener or _open_browser_default

        self._process: _ProcessHandle | None = None
        self._reader_thread: threading.Thread | None = None
        self._lock = threading.Lock()

        self.url: str | None = None
        self.code: str | None = None
        self.return_code: int | None = None
        self.events: list[CodexLoginEvent] = []
        self._browser_attempted = False

    # ----- public lifecycle -----

    def start(self) -> None:
        if self._executable is None:
            raise ProviderError(
                "Codex CLI not found in PATH. Install with `npm install -g @openai/codex`."
            )
        if self._process is not None:
            raise ProviderError("Login session already started.")
        cmd = [self._executable, "login"]
        if self._device_auth:
            cmd.append("--device-auth")
        try:
            self._process = self._process_factory(cmd)
        except FileNotFoundError as exc:
            raise ProviderError(
                "Codex CLI not found. Install with `npm install -g @openai/codex`."
            ) from exc
        self._reader_thread = threading.Thread(
            target=self._read_loop, name="codex-login-reader", daemon=True
        )
        self._reader_thread.start()

    def wait(self, timeout: float | None = None) -> int:
        if self._process is None:
            raise ProviderError("Login session has not been started.")
        rc = self._process.wait(timeout=timeout)
        # Drain reader thread so all pending events land before we return.
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=2.0)
        self.return_code = rc
        return rc

    def cancel(self) -> None:
        if self._process is None:
            return
        try:
            self._process.terminate()
        except Exception:  # noqa: BLE001 -- best-effort
            try:
                self._process.kill()
            except Exception:  # noqa: BLE001
                pass

    # ----- reader loop -----

    def _read_loop(self) -> None:
        assert self._process is not None
        try:
            for raw_line in self._process.stdout:
                line = raw_line.rstrip("\r\n") if isinstance(raw_line, str) else ""
                if not line:
                    continue
                self._emit("output", line)
                self._maybe_extract_url(line)
                self._maybe_extract_code(line)
        except Exception as exc:  # noqa: BLE001 -- reader thread boundary
            self._emit("error", f"reader-thread crashed: {exc}")
        finally:
            try:
                rc = self._process.wait(timeout=0)
            except Exception:  # noqa: BLE001
                rc = None
            if rc is None:
                # Process still running -- exit message will be emitted by .wait()
                return
            if rc == 0:
                self._emit("complete", "Codex login completed.", {"return_code": rc})
            else:
                self._emit(
                    "error", f"codex login exited with code {rc}.", {"return_code": rc}
                )

    def _maybe_extract_url(self, line: str) -> None:
        match = _URL_RE.search(line)
        if not match:
            return
        url = match.group(0).rstrip(".,)")
        # Filter out any URLs that don't look like an OAuth login (e.g.
        # documentation links codex prints around the actual URL).
        if not _looks_like_login_url(url):
            return
        with self._lock:
            if self.url is not None:
                return
            self.url = url
        self._emit("url", url, {"url": url})
        if self._auto_open_browser and not self._browser_attempted:
            self._browser_attempted = True
            opened = False
            try:
                opened = bool(self._browser_opener(url))
            except Exception as exc:  # noqa: BLE001
                self._emit(
                    "output",
                    f"(browser auto-open raised: {exc}; please open the URL manually)",
                )
            self._emit(
                "browser_opened" if opened else "output",
                (
                    "Opened browser at the login URL."
                    if opened
                    else "Browser auto-open failed; open the URL manually."
                ),
                {"opened": opened, "url": url},
            )

    def _maybe_extract_code(self, line: str) -> None:
        match = _CODE_RE.search(line)
        if not match:
            return
        code = match.group(1)
        with self._lock:
            if self.code is not None:
                return
            self.code = code
        self._emit("code", code, {"code": code})

    def _emit(self, type_: str, message: str = "", detail: dict[str, Any] | None = None) -> None:
        event = CodexLoginEvent(type=type_, message=message, detail=detail or {})
        self.events.append(event)
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception as exc:  # noqa: BLE001 -- protect reader thread
                logger.debug("codex login event callback failed: %s", exc)


# ---------------------------------------------------------------------------
# Codex provider
# ---------------------------------------------------------------------------


class CodexOAuthProvider(LLMProvider):
    id = "codex-cli"
    display_name = "Codex (OpenAI CLI)"
    auth_type = AuthType.OAUTH
    description = (
        "OpenAI's Codex CLI logged in via the official OAuth flow. "
        "AutoApply wraps `codex login` and `codex exec`; tokens stay "
        "in ~/.codex/ -- AutoApply only stores a non-secret breadcrumb."
    )
    install_hint = "Install with `npm install -g @openai/codex`"

    def __init__(
        self,
        store: Any | None = None,
        *,
        codex_executable: str | None = None,
        login_session_factory: Callable[..., CodexLoginSession] | None = None,
        status_runner: Callable[[str], tuple[int, str]] | None = None,
        logout_runner: Callable[[str], tuple[int, str]] | None = None,
    ) -> None:
        super().__init__(store)
        self._codex_executable_override = codex_executable
        self._login_session_factory = login_session_factory or _default_session_factory
        self._status_runner = status_runner or _run_codex_command
        self._logout_runner = logout_runner or _run_codex_command

    # ----- helpers -----

    def codex_executable(self) -> str | None:
        return self._codex_executable_override or _resolve_codex()

    # ----- connection lifecycle -----

    def start_login(
        self,
        *,
        device_auth: bool = False,
        auto_open_browser: bool = True,
        on_event: EventCallback | None = None,
    ) -> CodexLoginSession:
        executable = self.codex_executable()
        if executable is None:
            raise ProviderError(
                "Codex CLI not found in PATH. Install with `npm install -g @openai/codex`."
            )
        session = self._login_session_factory(
            executable=executable,
            device_auth=device_auth,
            auto_open_browser=auto_open_browser,
            on_event=on_event,
        )
        session.start()
        return session

    def finalize_login(
        self,
        session: CodexLoginSession,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderCredentials:
        """Persist a no-secret breadcrumb after a successful login session."""
        if session.return_code is None:
            raise ProviderError(
                "Cannot finalize login -- session has not completed."
            )
        if session.return_code != 0:
            raise ProviderError(
                f"codex login failed (exit code {session.return_code})."
            )
        if self._store is None:
            raise ProviderError(
                "Cannot persist credentials -- provider was constructed without a store."
            )
        creds = ProviderCredentials(
            provider_id=self.id,
            auth_type=self.auth_type,
            secret={"managed_by": "codex-cli"},
            connected_at=now_iso(),
            verified_at=now_iso(),
            metadata=dict(metadata or {}),
        )
        self._store.set(creds)
        return creds

    def disconnect(self) -> None:
        executable = self.codex_executable()
        if executable is not None:
            try:
                self._logout_runner(executable)
            except Exception as exc:  # noqa: BLE001 -- best-effort logout
                logger.warning("codex logout raised: %s", exc)
        super().disconnect()

    def test_connection(self, *, timeout: int = 10) -> ProviderTestResult:
        executable = self.codex_executable()
        if executable is None:
            return ProviderTestResult(
                ok=False,
                detail="Codex CLI not found in PATH.",
            )
        t0 = time.monotonic()
        try:
            rc, output = self._status_runner(executable, "login", "status")
        except Exception as exc:  # noqa: BLE001
            return ProviderTestResult(ok=False, detail=f"codex login status failed: {exc}")
        latency = int((time.monotonic() - t0) * 1000)

        ok = rc == 0 and not _looks_logged_out(output)
        result = ProviderTestResult(
            ok=ok,
            detail=output.strip()[:240] if output else ("OK" if ok else "Not logged in."),
            latency_ms=latency,
        )
        creds = self.credentials()
        if creds is not None and self._store is not None:
            creds.verified_at = now_iso() if ok else creds.verified_at
            creds.last_test_error = None if ok else result.detail
            self._store.set(creds)
        return result

    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        timeout: int = 120,
        output_format: str = "text",
    ) -> str:
        # Reuse the existing CLI helper to keep one well-tested codex
        # invocation path. Late import avoids a circular dep through
        # src.utils.llm -> src.core.config -> ... that bites at module
        # load time in CLI startup.
        from src.utils.llm import LLMError, codex_generate  # noqa: PLC0415

        try:
            # Pass output_format so codex_generate appends its JSON-only
            # prompt suffix when callers (e.g. generate_json) need it.
            return codex_generate(
                prompt,
                system=system,
                timeout=timeout,
                output_format=output_format,
            )
        except LLMError as exc:
            raise ProviderError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _default_session_factory(**kwargs: Any) -> CodexLoginSession:
    return CodexLoginSession(**kwargs)


def _open_browser_default(url: str) -> bool:
    try:
        return bool(webbrowser.open(url))
    except Exception:  # noqa: BLE001 -- webbrowser may raise on headless boxes
        return False


def _resolve_codex() -> str | None:
    return (
        shutil.which("codex")
        or shutil.which("codex.cmd")
        or shutil.which("codex.exe")
    )


def _run_codex_command(executable: str, *args: str) -> tuple[int, str]:
    cmd = [executable, *args]
    result = subprocess.run(  # noqa: S603 -- args are constants
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def _looks_like_login_url(url: str) -> bool:
    """Filter out doc / help URLs we don't want the user to open."""
    lowered = url.lower()
    if any(
        marker in lowered
        for marker in ("/docs", "/help", "github.com", "openai.com/docs")
    ):
        return False
    # Anything that smells like an OAuth or auth flow is fair game.
    return any(
        marker in lowered
        for marker in ("auth", "login", "oauth", "device", "sign-in", "signin")
    )


def _looks_logged_out(output: str) -> bool:
    if not output:
        return True
    lowered = output.lower()
    return any(
        marker in lowered
        for marker in ("not logged in", "no credentials", "logged out", "please log in")
    )


def register(registry: Any) -> None:
    """Helper used by the registry's _register_builtins."""
    registry.register(CodexOAuthProvider)
