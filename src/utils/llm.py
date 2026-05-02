"""LLM CLI wrapper.

Invokes Claude Code CLI and Codex CLI via subprocess.
The high-level helpers honor configured provider priority and can fall back
between CLIs when one fails or is unavailable.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.core.config import load_config

logger = logging.getLogger("autoapply.llm")

SUPPORTED_PROVIDERS = ("claude-cli", "codex-cli")


class LLMError(Exception):
    """Raised when an LLM CLI call fails."""


def detect_available_providers() -> dict[str, bool]:
    """Detect which supported LLM CLIs are available in PATH."""
    return {
        "claude-cli": _resolve_executable("claude") is not None,
        "codex-cli": _resolve_executable("codex") is not None,
    }


def get_llm_settings(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return normalized LLM settings with backward-compatible defaults."""
    if config is None:
        config = load_config()

    llm = config.get("llm", {})
    primary = llm.get("primary_provider") or llm.get("provider") or "claude-cli"
    fallback = llm.get("fallback_provider")
    allow_fallback = bool(llm.get("allow_fallback", fallback is not None))
    timeout = int(llm.get("timeout", 120))

    primary = _normalize_provider(primary, role="primary")
    if fallback in ("", "none"):
        fallback = None
    if fallback is not None:
        fallback = _normalize_provider(fallback, role="fallback")
    if fallback == primary:
        fallback = None

    return {
        "primary_provider": primary,
        "fallback_provider": fallback,
        "allow_fallback": allow_fallback,
        "timeout": timeout,
    }


def generate_text(
    prompt: str,
    *,
    system: str = "",
    timeout: int | None = None,
    output_format: str = "text",
    config: dict[str, Any] | None = None,
) -> str:
    """Generate text using the configured provider order with optional fallback."""
    settings = get_llm_settings(config)
    timeout = timeout or settings["timeout"]
    providers = [settings["primary_provider"]]
    if settings["allow_fallback"] and settings["fallback_provider"]:
        providers.append(settings["fallback_provider"])

    errors: list[str] = []
    for provider in providers:
        try:
            return _call_provider(
                provider,
                prompt,
                system=system,
                timeout=timeout,
                output_format=output_format,
            )
        except LLMError as exc:
            logger.warning("LLM provider %s failed: %s", provider, exc)
            errors.append(f"{provider}: {exc}")

    raise LLMError("All configured LLM providers failed. " + " | ".join(errors))


def generate_json(
    prompt: str,
    *,
    system: str = "",
    timeout: int | None = None,
    config: dict[str, Any] | None = None,
) -> Any:
    """Generate JSON-like output using the configured provider order."""
    raw = generate_text(
        prompt,
        system=system,
        timeout=timeout,
        output_format="json",
        config=config,
    )
    return _parse_json_response(raw)


def claude_generate(
    prompt: str,
    *,
    system: str = "",
    timeout: int = 120,
    output_format: str = "text",
) -> str:
    """Call Claude Code CLI directly for text generation."""
    executable = _resolve_executable("claude")
    if executable is None:
        raise LLMError(
            "Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
        )

    cmd = [executable, "-p", prompt, "--output-format", output_format]
    if system:
        cmd.extend(["--system-prompt", system])

    logger.debug("Claude CLI call: prompt=%d chars, system=%d chars", len(prompt), len(system))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        raise LLMError(f"Claude CLI timed out after {timeout}s")
    except FileNotFoundError as exc:
        raise LLMError(
            "Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
        ) from exc

    if result.returncode != 0:
        raise LLMError(f"Claude CLI error (code {result.returncode}): {result.stderr.strip()}")

    response = result.stdout.strip()
    logger.debug("Claude CLI response: %d chars", len(response))
    return response


def claude_generate_json(prompt: str, *, system: str = "", timeout: int = 120) -> Any:
    """Call Claude CLI directly and parse the response as JSON."""
    raw = claude_generate(prompt, system=system, timeout=timeout, output_format="json")
    return _parse_json_response(raw)


def codex_generate(
    prompt: str,
    *,
    system: str = "",
    timeout: int = 120,
    output_format: str = "text",
) -> str:
    """Call Codex CLI directly for text generation."""
    executable = _resolve_executable("codex")
    if executable is None:
        raise LLMError("Codex CLI not found. Install with: npm install -g @openai/codex")

    full_prompt = prompt
    if system:
        full_prompt = f"System instructions:\n{system}\n\nUser request:\n{prompt}"
    if output_format == "json":
        full_prompt = f"{full_prompt}\n\nReturn only valid JSON with no markdown fences."

    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as output_file:
        output_path = Path(output_file.name)
    output_path.unlink(missing_ok=True)

    cmd = [
        executable,
        "exec",
        "--full-auto",
        "--color",
        "never",
        "--output-last-message",
        str(output_path),
        full_prompt,
    ]

    logger.debug("Codex CLI call: prompt=%d chars, system=%d chars", len(prompt), len(system))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        output_path.unlink(missing_ok=True)
        raise LLMError(f"Codex CLI timed out after {timeout}s")
    except FileNotFoundError as exc:
        output_path.unlink(missing_ok=True)
        raise LLMError("Codex CLI not found. Install with: npm install -g @openai/codex") from exc

    try:
        final_message = (
            output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
        )
    finally:
        output_path.unlink(missing_ok=True)

    if result.returncode != 0:
        raise LLMError(f"Codex CLI error (code {result.returncode}): {result.stderr.strip()}")

    response = final_message or result.stdout.strip()
    logger.debug("Codex CLI response: %d chars", len(response))
    return response


def _call_provider(
    provider: str,
    prompt: str,
    *,
    system: str,
    timeout: int,
    output_format: str,
) -> str:
    """Dispatch to the selected provider."""
    if provider == "claude-cli":
        return claude_generate(prompt, system=system, timeout=timeout, output_format=output_format)
    if provider == "codex-cli":
        return codex_generate(prompt, system=system, timeout=timeout, output_format=output_format)
    raise LLMError(f"Unsupported LLM provider: {provider}")


def _normalize_provider(provider: str, *, role: str) -> str:
    """Validate a provider string."""
    if provider not in SUPPORTED_PROVIDERS:
        supported = ", ".join(SUPPORTED_PROVIDERS)
        raise ValueError(f"Invalid {role} LLM provider '{provider}'. Expected one of: {supported}")
    return provider


def _resolve_executable(command: str) -> str | None:
    """Resolve a CLI executable path for direct subprocess use.

    On Windows, passing bare commands like ``codex`` to ``subprocess.run`` may fail
    even when ``shutil.which`` can see a ``.cmd`` shim. Using the resolved path avoids
    that CreateProcess lookup issue.
    """
    return shutil.which(command) or shutil.which(f"{command}.cmd") or shutil.which(f"{command}.exe")


def _parse_json_response(raw: str) -> Any:
    """Parse JSON output and tolerate fenced responses."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = [line for line in cleaned.split("\n") if not line.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return raw

    if isinstance(parsed, dict) and "result" in parsed:
        inner = parsed["result"]
        if isinstance(inner, str):
            try:
                return json.loads(inner)
            except (json.JSONDecodeError, TypeError):
                return inner
    return parsed
