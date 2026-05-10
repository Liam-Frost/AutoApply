"""Anthropic Messages API provider.

Uses the documented v1 REST surface. Header layout differs from OpenAI:
``x-api-key`` instead of ``Authorization``, plus a required
``anthropic-version`` header. Generation goes through ``/v1/messages``
which returns a content block list rather than a chat-completions
``choices[0].message.content`` shape.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from src.providers.api_base import ApiKeyProvider
from src.providers.base import ProviderError, ProviderTestResult

DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_MODEL = "claude-sonnet-4-5"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096


class AnthropicProvider(ApiKeyProvider):
    id = "anthropic"
    display_name = "Anthropic"
    description = "Anthropic Messages API (Claude family)"
    install_hint = "Get an API key from https://console.anthropic.com/settings/keys"
    api_key_env_var = "ANTHROPIC_API_KEY"
    default_model = DEFAULT_MODEL

    def _base_url(self) -> str:
        creds = self.credentials()
        if creds:
            override = creds.metadata.get("base_url")
            if isinstance(override, str) and override.strip():
                return override.strip().rstrip("/")
        return DEFAULT_BASE_URL

    def _headers(self, api_key: str) -> dict[str, str]:
        return {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
            "User-Agent": "autoapply/0.7",
        }

    def _probe_connection(
        self, api_key: str, *, timeout: int
    ) -> ProviderTestResult:
        url = f"{self._base_url()}/models"
        t0 = time.monotonic()
        with self._client(timeout) as client:
            response = client.get(url, headers=self._headers(api_key))
        latency = self._measure(t0)

        if response.status_code == 401:
            return ProviderTestResult(
                ok=False,
                detail=(
                    "Anthropic rejected the key (401). "
                    "Check the value at console.anthropic.com."
                ),
                latency_ms=latency,
            )
        if response.status_code >= 400:
            return ProviderTestResult(
                ok=False,
                detail=(
                    f"Anthropic returned HTTP {response.status_code}: "
                    f"{_safe_text(response)}"
                ),
                latency_ms=latency,
            )

        body: dict[str, Any]
        try:
            body = response.json()
        except ValueError:
            body = {}
        models = body.get("data") if isinstance(body, dict) else None
        return ProviderTestResult(
            ok=True,
            detail="OK",
            latency_ms=latency,
            model_count=len(models) if isinstance(models, list) else None,
        )

    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        timeout: int = 120,
    ) -> str:
        api_key = self.get_api_key()
        model = self.get_model()
        url = f"{self._base_url()}/messages"
        max_tokens = DEFAULT_MAX_TOKENS
        creds = self.credentials()
        if creds:
            override = creds.metadata.get("max_tokens")
            if isinstance(override, int) and override > 0:
                max_tokens = override

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system

        with self._client(timeout) as client:
            response = client.post(
                url, headers=self._headers(api_key), json=payload
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"Anthropic generation failed (HTTP {response.status_code}): "
                f"{_safe_text(response)}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderError(f"Anthropic response was not JSON: {exc}") from exc

        content = body.get("content") if isinstance(body, dict) else None
        if not isinstance(content, list) or not content:
            raise ProviderError(f"Anthropic response missing 'content': {body!r}")
        # Concatenate all text-type blocks; ignore tool/use blocks here.
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                value = block.get("text", "")
                if isinstance(value, str):
                    parts.append(value)
        if not parts:
            raise ProviderError(
                f"Anthropic response had no text blocks: {body!r}"
            )
        return "".join(parts)


def _safe_text(response: httpx.Response, limit: int = 240) -> str:
    text = (response.text or "").strip()
    return text[:limit] + ("…" if len(text) > limit else "")
