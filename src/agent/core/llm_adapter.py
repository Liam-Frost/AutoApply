"""Adapt the project's CLI-based LLM to the LLMCallable signature.

The agent loop expects ``(prompt, system, timeout) -> str``. The existing
``generate_text`` helper in ``src.utils.llm`` already takes those, so the
adapter is thin -- it exists so tests and alt providers can swap in
without touching the loop.
"""

from __future__ import annotations

from src.utils.llm import generate_text


def cli_llm(prompt: str, system: str, timeout: int) -> str:
    """Default LLMCallable backed by the configured CLI provider chain."""
    return generate_text(prompt, system=system, timeout=timeout)
