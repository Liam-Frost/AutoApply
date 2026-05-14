"""Phase 12.5 -- ``embed_text`` cache integration tests.

Covers the new cache-wrapped embedding API: hit short-circuits the
HTTP call, only successful results are cached, transient failures
degrade to ``None``, graceful degrade when OpenAI isn't configured.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.cache.cache import Cache, reset_cache
from src.cache.lru import LRUBackend
from src.matching.semantic import DEFAULT_EMBEDDING_MODEL, embed_text


@pytest.fixture(autouse=True)
def _cleanup_cache():
    reset_cache()
    yield
    reset_cache()


def _l1_cache() -> Cache:
    return Cache(l1=LRUBackend(), l2=None)


def _ok_embedding_response(vector: list[float]) -> Any:
    class _Resp:
        status_code = 200

        def json(self) -> dict:
            return {"data": [{"embedding": vector}]}

        @property
        def text(self) -> str:
            return ""

    return _Resp()


class _FakeProvider:
    """Minimal stand-in for the OpenAI provider used by embed_text."""

    def __init__(
        self,
        configured: bool = True,
        api_key: str | None = "sk-test",
    ) -> None:
        self._configured = configured
        self._api_key = api_key

    def is_configured(self) -> bool:
        return self._configured

    def credentials(self):
        if not self._configured:
            return None

        class _Creds:
            secret = {"api_key": self._api_key}

        return _Creds()

    def get_api_key(self) -> str:
        """Mirrors ``ApiKeyProvider.get_api_key`` -- credentials first,
        then env var, then raise ``ProviderError``."""
        from src.providers.base import ProviderError  # noqa: PLC0415

        if self._configured and self._api_key:
            return self._api_key
        import os  # noqa: PLC0415

        env = os.environ.get("OPENAI_API_KEY")
        if env:
            return env
        raise ProviderError("OpenAI not connected")

    def _base_url(self) -> str:
        return "https://api.openai.com/v1"


class _FakeRegistry:
    def __init__(self, provider: _FakeProvider | None) -> None:
        self._provider = provider

    def maybe_get(self, name: str):
        return self._provider if name == "openai" else None


@pytest.fixture
def cache():
    return _l1_cache()


@pytest.fixture
def provider_configured():
    return _FakeProvider(configured=True)


def _patch_provider(provider, cache_obj):
    return (
        patch("src.cache.get_cache", return_value=cache_obj),
        patch("src.providers.get_registry", return_value=_FakeRegistry(provider)),
    )


class TestEmbedHappyPath:
    def test_first_call_hits_api_caches_result(
        self, cache, provider_configured
    ) -> None:
        captured: list[dict] = []

        def fake_post(url, **kw):
            captured.append({"url": url, "json": kw.get("json")})
            return _ok_embedding_response([0.1, 0.2, 0.3])

        with (
            patch("src.cache.get_cache", return_value=cache),
            patch(
                "src.providers.get_registry",
                return_value=_FakeRegistry(provider_configured),
            ),
            patch("httpx.post", side_effect=fake_post),
        ):
            result = embed_text("hello world")
        assert result == [0.1, 0.2, 0.3]
        assert len(captured) == 1
        assert captured[0]["json"]["input"] == "hello world"
        assert captured[0]["json"]["model"] == DEFAULT_EMBEDDING_MODEL
        # Cache has one write.
        assert cache.stats()["writes"] == 1

    def test_second_call_serves_from_cache(
        self, cache, provider_configured
    ) -> None:
        calls = {"n": 0}

        def fake_post(url, **kw):
            calls["n"] += 1
            return _ok_embedding_response([0.4, 0.5, 0.6])

        with (
            patch("src.cache.get_cache", return_value=cache),
            patch(
                "src.providers.get_registry",
                return_value=_FakeRegistry(provider_configured),
            ),
            patch("httpx.post", side_effect=fake_post),
        ):
            first = embed_text("the same text")
            second = embed_text("the same text")
        assert first == second == [0.4, 0.5, 0.6]
        # Only ONE API call -- the second was served by L1.
        assert calls["n"] == 1
        assert cache.stats()["hits_l1"] == 1


class TestKeySemantics:
    def test_model_in_cache_key(self, cache, provider_configured) -> None:
        """Two requests for the same text with different models must
        round-trip the API both times (different cache key)."""

        calls = {"n": 0}

        def fake_post(url, **kw):
            calls["n"] += 1
            return _ok_embedding_response([float(calls["n"])])

        with (
            patch("src.cache.get_cache", return_value=cache),
            patch(
                "src.providers.get_registry",
                return_value=_FakeRegistry(provider_configured),
            ),
            patch("httpx.post", side_effect=fake_post),
        ):
            a = embed_text("same text", model="text-embedding-3-small")
            b = embed_text("same text", model="text-embedding-3-large")
        assert a != b
        assert calls["n"] == 2

    def test_different_text_different_key(
        self, cache, provider_configured
    ) -> None:
        calls = {"n": 0}

        def fake_post(url, **kw):
            calls["n"] += 1
            return _ok_embedding_response([float(calls["n"])])

        with (
            patch("src.cache.get_cache", return_value=cache),
            patch(
                "src.providers.get_registry",
                return_value=_FakeRegistry(provider_configured),
            ),
            patch("httpx.post", side_effect=fake_post),
        ):
            embed_text("text one")
            embed_text("text two")
        assert calls["n"] == 2

    def test_base_url_in_cache_key(self, cache) -> None:
        """Codex review P2 regression: the same model name on a
        different ``base_url`` (e.g. a compatible proxy that routes
        ``text-embedding-3-small`` to a different backend) can mean
        a different embedding space. The cache key must distinguish
        endpoints so vectors from different spaces don't collide."""

        class _ProviderWithUrl(_FakeProvider):
            def __init__(self, url: str) -> None:
                super().__init__(configured=True, api_key="sk-test")
                self._url = url

            def _base_url(self) -> str:
                return self._url

        calls = {"n": 0}

        def fake_post(url, **kw):
            calls["n"] += 1
            return _ok_embedding_response([float(calls["n"])])

        # First call: public OpenAI endpoint.
        with (
            patch("src.cache.get_cache", return_value=cache),
            patch(
                "src.providers.get_registry",
                return_value=_FakeRegistry(
                    _ProviderWithUrl("https://api.openai.com/v1")
                ),
            ),
            patch("httpx.post", side_effect=fake_post),
        ):
            a = embed_text("same text")
        # Second call: same text, different proxy URL.
        with (
            patch("src.cache.get_cache", return_value=cache),
            patch(
                "src.providers.get_registry",
                return_value=_FakeRegistry(
                    _ProviderWithUrl("https://proxy.example.com/v1")
                ),
            ),
            patch("httpx.post", side_effect=fake_post),
        ):
            b = embed_text("same text")
        # Two API calls fired -> two distinct cache entries.
        assert calls["n"] == 2
        assert a != b


class TestGracefulDegrade:
    def test_provider_not_configured_returns_none(
        self, monkeypatch, cache
    ) -> None:
        """Without credentials AND without ``OPENAI_API_KEY``, the
        embedding path must degrade silently."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with (
            patch("src.cache.get_cache", return_value=cache),
            patch(
                "src.providers.get_registry",
                return_value=_FakeRegistry(_FakeProvider(configured=False)),
            ),
        ):
            assert embed_text("hi") is None
        assert cache.stats()["writes"] == 0

    def test_env_var_only_api_key_still_works(
        self, monkeypatch, cache
    ) -> None:
        """Codex review P2 regression: a deployment that supplies
        ``OPENAI_API_KEY`` via env -- without running
        ``autoapply provider connect`` -- must still get embeddings.
        Earlier versions short-circuited on ``is_configured()`` which
        only checks the credential store."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-only")
        provider = _FakeProvider(configured=False, api_key=None)

        def fake_post(url, **kw):
            assert kw["headers"]["Authorization"] == "Bearer sk-env-only"
            return _ok_embedding_response([0.7, 0.8, 0.9])

        with (
            patch("src.cache.get_cache", return_value=cache),
            patch(
                "src.providers.get_registry",
                return_value=_FakeRegistry(provider),
            ),
            patch("httpx.post", side_effect=fake_post),
        ):
            result = embed_text("hi")
        assert result == [0.7, 0.8, 0.9]

    def test_provider_missing_returns_none(self, cache) -> None:
        with (
            patch("src.cache.get_cache", return_value=cache),
            patch(
                "src.providers.get_registry",
                return_value=_FakeRegistry(None),
            ),
        ):
            assert embed_text("hi") is None

    def test_empty_input_returns_none_without_api_call(
        self, cache, provider_configured
    ) -> None:
        with (
            patch("src.cache.get_cache", return_value=cache),
            patch(
                "src.providers.get_registry",
                return_value=_FakeRegistry(provider_configured),
            ),
            patch("httpx.post", side_effect=AssertionError("must not be called")),
        ):
            assert embed_text("") is None
            assert embed_text("   ") is None

    def test_http_failure_returns_none_no_cache_write(
        self, cache, provider_configured
    ) -> None:
        class _ErrResp:
            status_code = 500
            text = "server down"

        with (
            patch("src.cache.get_cache", return_value=cache),
            patch(
                "src.providers.get_registry",
                return_value=_FakeRegistry(provider_configured),
            ),
            patch("httpx.post", return_value=_ErrResp()),
        ):
            assert embed_text("hi") is None
        assert cache.stats()["writes"] == 0

    def test_http_exception_returns_none(
        self, cache, provider_configured
    ) -> None:
        with (
            patch("src.cache.get_cache", return_value=cache),
            patch(
                "src.providers.get_registry",
                return_value=_FakeRegistry(provider_configured),
            ),
            patch("httpx.post", side_effect=RuntimeError("network blew up")),
        ):
            assert embed_text("hi") is None

    def test_malformed_payload_returns_none(
        self, cache, provider_configured
    ) -> None:
        class _MalformedResp:
            status_code = 200

            def json(self) -> dict:
                return {"wrong_shape": True}

        with (
            patch("src.cache.get_cache", return_value=cache),
            patch(
                "src.providers.get_registry",
                return_value=_FakeRegistry(provider_configured),
            ),
            patch("httpx.post", return_value=_MalformedResp()),
        ):
            assert embed_text("hi") is None
        # Malformed != cache poison -- nothing written.
        assert cache.stats()["writes"] == 0

    @pytest.mark.parametrize(
        "shape",
        [
            # Top-level array instead of object.
            [{"embedding": [0.1]}],
            # data is not a list.
            {"data": "not-a-list"},
            # data[0] is not a dict.
            {"data": ["not-an-object"]},
            # data[0].embedding is not a list.
            {"data": [{"embedding": "nope"}]},
            # data[0].embedding has non-numeric entries.
            {"data": [{"embedding": ["x", "y"]}]},
            # data is empty.
            {"data": []},
            # Bare string instead of an object.
            "totally-wrong",
        ],
    )
    def test_pathological_payloads_return_none_not_raise(
        self, cache, provider_configured, shape
    ) -> None:
        """Codex review P2 regression: any shape that's syntactically
        valid JSON but not the documented embeddings response must
        degrade to ``None`` rather than ``AttributeError`` out of the
        function."""

        class _Resp:
            status_code = 200

            def json(self):
                return shape

        with (
            patch("src.cache.get_cache", return_value=cache),
            patch(
                "src.providers.get_registry",
                return_value=_FakeRegistry(provider_configured),
            ),
            patch("httpx.post", return_value=_Resp()),
        ):
            # Must not raise.
            assert embed_text("hi") is None


class TestCacheOptOut:
    def test_cache_false_skips_lookup_and_write(
        self, cache, provider_configured
    ) -> None:
        calls = {"n": 0}

        def fake_post(url, **kw):
            calls["n"] += 1
            return _ok_embedding_response([0.1, 0.2])

        with (
            patch("src.cache.get_cache", return_value=cache),
            patch(
                "src.providers.get_registry",
                return_value=_FakeRegistry(provider_configured),
            ),
            patch("httpx.post", side_effect=fake_post),
        ):
            embed_text("same", cache=False)
            embed_text("same", cache=False)
        # No caching -> both calls hit the API.
        assert calls["n"] == 2
        assert cache.stats()["writes"] == 0
