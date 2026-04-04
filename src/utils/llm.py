"""LLM CLI wrapper.

Invokes Claude Code CLI and Codex CLI via subprocess for text generation.
No API SDK dependency — CLI handles its own authentication.
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

logger = logging.getLogger("autoapply.llm")


class LLMError(Exception):
    """Raised when an LLM CLI call fails."""


def claude_generate(
    prompt: str,
    *,
    system: str = "",
    timeout: int = 120,
    output_format: str = "text",
) -> str:
    """Call Claude Code CLI for text generation.

    Args:
        prompt: The user prompt to send.
        system: Optional system prompt.
        timeout: Max seconds to wait for response.
        output_format: "text" or "json".

    Returns:
        The generated text response.
    """
    cmd = ["claude", "-p", prompt, "--output-format", output_format]
    if system:
        cmd.extend(["--system", system])

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
    except FileNotFoundError:
        raise LLMError(
            "Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
        )

    if result.returncode != 0:
        raise LLMError(f"Claude CLI error (code {result.returncode}): {result.stderr.strip()}")

    response = result.stdout.strip()
    logger.debug("Claude CLI response: %d chars", len(response))
    return response


def claude_generate_json(prompt: str, *, system: str = "", timeout: int = 120) -> Any:
    """Call Claude CLI and parse the response as JSON."""
    raw = claude_generate(prompt, system=system, timeout=timeout, output_format="json")
    try:
        parsed = json.loads(raw)
        # claude --output-format json wraps in {"result": "..."}
        if isinstance(parsed, dict) and "result" in parsed:
            inner = parsed["result"]
            # Try to parse inner as JSON too (for structured output)
            try:
                return json.loads(inner)
            except (json.JSONDecodeError, TypeError):
                return inner
        return parsed
    except json.JSONDecodeError:
        # Fall back to raw text if not valid JSON
        return raw


def codex_generate(
    prompt: str,
    *,
    timeout: int = 120,
) -> str:
    """Call Codex CLI for text generation.

    Args:
        prompt: The prompt to send.
        timeout: Max seconds to wait.

    Returns:
        The generated text response.
    """
    cmd = ["codex", "exec", "--full-auto", prompt]

    logger.debug("Codex CLI call: prompt=%d chars", len(prompt))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        raise LLMError(f"Codex CLI timed out after {timeout}s")
    except FileNotFoundError:
        raise LLMError("Codex CLI not found. Install with: npm install -g @openai/codex")

    if result.returncode != 0:
        raise LLMError(f"Codex CLI error (code {result.returncode}): {result.stderr.strip()}")

    response = result.stdout.strip()
    logger.debug("Codex CLI response: %d chars", len(response))
    return response
