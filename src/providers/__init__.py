"""LLM provider layer.

Phase 10 generalises the harness from a hardcoded ``claude-cli`` /
``codex-cli`` choice to a registry of pluggable providers (API-key
based for OpenAI / Anthropic / Gemini, OAuth-based for the Codex CLI,
subprocess-based for Claude / Codex CLIs that ship their own auth).

Public surface:

* :class:`LLMProvider` -- the ABC every provider implements.
* :class:`ProviderTestResult` / :class:`ProviderCredentials` -- shared
  data shapes used by the registry, CLI, and Web UI.
* :class:`CredentialStore` -- file-backed secret storage with strict
  permissions; gitignored from day one.
* :func:`get_registry` -- process-wide :class:`ProviderRegistry`
  populated lazily on first access.

The agent loop and the existing :mod:`src.utils.llm` helper still work
unchanged in this sub-phase; integration lands in 10.6.
"""

from src.providers.base import (
    AuthType,
    LLMProvider,
    ProviderCredentials,
    ProviderError,
    ProviderTestResult,
)
from src.providers.registry import ProviderRegistry, get_registry
from src.providers.store import CredentialStore

__all__ = [
    "AuthType",
    "CredentialStore",
    "LLMProvider",
    "ProviderCredentials",
    "ProviderError",
    "ProviderRegistry",
    "ProviderTestResult",
    "get_registry",
]
