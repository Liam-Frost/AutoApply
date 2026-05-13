"""OpenAI Chat Completions provider.

Uses the documented v1 REST surface so we don't take a hard dependency
on the ``openai`` SDK (which has its own breaking-change cadence). One
class for both ``api.openai.com`` and Azure-style overrides via
``base_url`` metadata, but the AutoApply UI only exposes the public
endpoint in Phase 10.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from src.providers.api_base import ApiKeyProvider
from src.providers.base import (
    ProviderError,
    ProviderErrorKind,
    ProviderTestResult,
    classify_http_status,
)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIProvider(ApiKeyProvider):
    id = "openai"
    display_name = "OpenAI"
    description = "OpenAI Chat Completions (gpt-4o, gpt-4o-mini, ...)"
    install_hint = "Get an API key from https://platform.openai.com/api-keys"
    api_key_env_var = "OPENAI_API_KEY"
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
            "Authorization": f"Bearer {api_key}",
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
                detail="OpenAI rejected the key (401). Check the value at platform.openai.com.",
                latency_ms=latency,
            )
        if response.status_code >= 400:
            return ProviderTestResult(
                ok=False,
                detail=f"OpenAI returned HTTP {response.status_code}: {_safe_text(response)}",
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
        output_format: str = "text",  # noqa: ARG002 -- JSON is prompt-driven for REST providers
    ) -> str:
        api_key = self.get_api_key()
        model = self.get_model()
        url = f"{self._base_url()}/chat/completions"
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": model, "messages": messages}

        try:
            with self._client(timeout) as client:
                response = client.post(
                    url, headers=self._headers(api_key), json=payload
                )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"OpenAI generation timed out after {timeout}s",
                kind=ProviderErrorKind.TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"OpenAI network error: {exc}",
                kind=ProviderErrorKind.NETWORK,
            ) from exc

        if response.status_code >= 400:
            raise ProviderError(
                f"OpenAI generation failed (HTTP {response.status_code}): "
                f"{_safe_text(response)}",
                kind=classify_http_status(response.status_code),
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderError(
                f"OpenAI response was not JSON: {exc}",
                kind=ProviderErrorKind.PARSE,
            ) from exc

        choices = body.get("choices") if isinstance(body, dict) else None
        if not isinstance(choices, list) or not choices:
            raise ProviderError(
                f"OpenAI response missing 'choices': {body!r}",
                kind=ProviderErrorKind.PARSE,
            )
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ProviderError(
                f"OpenAI response missing 'choices[0].message.content': {body!r}",
                kind=ProviderErrorKind.PARSE,
            )
        return content


def _safe_text(response: httpx.Response, limit: int = 240) -> str:
    text = (response.text or "").strip()
    return text[:limit] + ("…" if len(text) > limit else "")
