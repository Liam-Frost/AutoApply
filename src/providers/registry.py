"""Provider registry.

The registry is the single place that knows the full set of supported
providers. CLI, Web UI, and the agent loop all consult it rather than
hard-coding provider ids. New providers register themselves here so
adding one is a single import.

A process-wide instance is exposed via :func:`get_registry` to keep
imports cheap; tests construct their own :class:`ProviderRegistry`
with a stub :class:`CredentialStore` to avoid touching real disk.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.providers.base import LLMProvider, ProviderError
from src.providers.store import CredentialStore


class ProviderRegistry:
    """Holds provider classes plus a shared credential store."""

    def __init__(self, store: CredentialStore | None = None) -> None:
        self._store = store or CredentialStore()
        self._classes: dict[str, type[LLMProvider]] = {}
        self._instances: dict[str, LLMProvider] = {}

    # ----- registration -----

    def register(self, cls: type[LLMProvider]) -> None:
        if not getattr(cls, "id", ""):
            raise ProviderError(
                f"Provider class {cls!r} must define a non-empty `id`."
            )
        if cls.id in self._classes:
            raise ProviderError(f"Provider id {cls.id!r} already registered.")
        self._classes[cls.id] = cls

    def register_all(self, classes: Iterable[type[LLMProvider]]) -> None:
        for cls in classes:
            self.register(cls)

    # ----- lookup -----

    def ids(self) -> list[str]:
        return sorted(self._classes)

    def get(self, provider_id: str) -> LLMProvider:
        if provider_id not in self._classes:
            raise ProviderError(f"Unknown provider {provider_id!r}.")
        if provider_id not in self._instances:
            self._instances[provider_id] = self._classes[provider_id](store=self._store)
        return self._instances[provider_id]

    def maybe_get(self, provider_id: str) -> LLMProvider | None:
        try:
            return self.get(provider_id)
        except ProviderError:
            return None

    def all(self) -> list[LLMProvider]:
        return [self.get(pid) for pid in self.ids()]

    def configured(self) -> list[LLMProvider]:
        return [p for p in self.all() if p.is_configured()]

    @property
    def store(self) -> CredentialStore:
        return self._store

    def public_view(self) -> list[dict[str, Any]]:
        return [p.public_view() for p in self.all()]


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_default_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    """Lazy singleton populated by :func:`_register_builtins` on first call.

    The lazy import in ``_register_builtins`` keeps the base modules free
    of provider-specific deps (httpx clients are imported only when a
    provider is actually instantiated).
    """
    global _default_registry
    if _default_registry is None:
        registry = ProviderRegistry()
        _register_builtins(registry)
        _default_registry = registry
    return _default_registry


def _register_builtins(registry: ProviderRegistry) -> None:
    """Register the providers shipped with AutoApply.

    Lazy imports keep the dependency surface small until callers
    actually need a provider.
    """
    from src.providers.anthropic import AnthropicProvider  # noqa: PLC0415
    from src.providers.claude_cli import ClaudeCliProvider  # noqa: PLC0415
    from src.providers.codex import CodexCliProvider  # noqa: PLC0415
    from src.providers.gemini import GeminiProvider  # noqa: PLC0415
    from src.providers.openai import OpenAIProvider  # noqa: PLC0415

    registry.register(OpenAIProvider)
    registry.register(AnthropicProvider)
    registry.register(GeminiProvider)
    # Codex and Claude are both subprocess wrappers around an
    # already-installed agent CLI; neither owns its OAuth flow. A
    # future native CodexOAuthProvider would live alongside these,
    # not replace them.
    registry.register(CodexCliProvider)
    registry.register(ClaudeCliProvider)


def reset_default_registry() -> None:
    """Drop the cached singleton. Used by tests that mutate registration."""
    global _default_registry
    _default_registry = None
