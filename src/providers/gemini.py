"""Google Gemini provider (generative-language API).

Uses the v1beta REST surface so we don't take the
``google-generativeai`` SDK. Auth is a query parameter -- ``?key=KEY``
-- rather than a header, matching the official curl examples.

We carefully strip the key from the URL when surfacing errors to the
user, since httpx by default puts the full URL into exception
messages.
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

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiProvider(ApiKeyProvider):
    id = "gemini"
    display_name = "Google Gemini"
    description = "Google Gemini generative-language API"
    install_hint = "Get an API key from https://aistudio.google.com/apikey"
    api_key_env_var = "GEMINI_API_KEY"
    default_model = DEFAULT_MODEL

    def _base_url(self) -> str:
        creds = self.credentials()
        if creds:
            override = creds.metadata.get("base_url")
            if isinstance(override, str) and override.strip():
                return override.strip().rstrip("/")
        return DEFAULT_BASE_URL

    def _probe_connection(
        self, api_key: str, *, timeout: int
    ) -> ProviderTestResult:
        url = f"{self._base_url()}/models"
        t0 = time.monotonic()
        with self._client(timeout) as client:
            response = client.get(
                url,
                params={"key": api_key},
                headers={"User-Agent": "autoapply/0.7"},
            )
        latency = self._measure(t0)

        if response.status_code in (401, 403):
            return ProviderTestResult(
                ok=False,
                detail=(
                    f"Gemini rejected the key (HTTP {response.status_code}). "
                    "Check the value at aistudio.google.com/apikey."
                ),
                latency_ms=latency,
            )
        if response.status_code >= 400:
            return ProviderTestResult(
                ok=False,
                detail=(
                    f"Gemini returned HTTP {response.status_code}: "
                    f"{_safe_text(response, key=api_key)}"
                ),
                latency_ms=latency,
            )

        body: dict[str, Any]
        try:
            body = response.json()
        except ValueError:
            body = {}
        models = body.get("models") if isinstance(body, dict) else None
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
        url = f"{self._base_url()}/models/{model}:generateContent"

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        try:
            with self._client(timeout) as client:
                response = client.post(
                    url,
                    params={"key": api_key},
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "autoapply/0.7",
                    },
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"Gemini generation timed out after {timeout}s",
                kind=ProviderErrorKind.TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Gemini network error: {exc}",
                kind=ProviderErrorKind.NETWORK,
            ) from exc

        if response.status_code >= 400:
            raise ProviderError(
                f"Gemini generation failed (HTTP {response.status_code}): "
                f"{_safe_text(response, key=api_key)}",
                kind=classify_http_status(response.status_code),
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderError(
                f"Gemini response was not JSON: {exc}",
                kind=ProviderErrorKind.PARSE,
            ) from exc

        candidates = body.get("candidates") if isinstance(body, dict) else None
        if not isinstance(candidates, list) or not candidates:
            raise ProviderError(
                f"Gemini response missing 'candidates': {body!r}",
                kind=ProviderErrorKind.PARSE,
            )
        content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list) or not parts:
            raise ProviderError(
                f"Gemini response missing parts: {body!r}",
                kind=ProviderErrorKind.PARSE,
            )
        text_parts = [p.get("text", "") for p in parts if isinstance(p, dict)]
        joined = "".join(t for t in text_parts if isinstance(t, str))
        if not joined:
            raise ProviderError(
                f"Gemini response had no text parts: {body!r}",
                kind=ProviderErrorKind.PARSE,
            )
        return joined


def _safe_text(response: httpx.Response, *, key: str = "", limit: int = 240) -> str:
    text = (response.text or "").strip()
    if key:
        text = text.replace(key, "***")
    return text[:limit] + ("…" if len(text) > limit else "")
