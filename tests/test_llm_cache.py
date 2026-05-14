"""Phase 12.4 -- LLM response caching tests.

Covers the opt-in cache wiring on :func:`src.utils.llm.generate_text`:
fingerprint stability, cache hit short-circuits the provider, only
successful responses are cached, transient failures don't poison the
cache, and the cache hit registers in ``last_attempt_chain`` for the
trace / dashboard.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.cache.cache import Cache, reset_cache
from src.cache.lru import LRUBackend
from src.utils.llm import (
    LLMError,
    _cache_fingerprint,
    generate_text,
    last_attempt_chain,
)


@pytest.fixture(autouse=True)
def _cleanup_cache():
    reset_cache()
    yield
    reset_cache()


def _llm_config(primary: str = "claude-cli") -> dict:
    return {
        "llm": {
            "primary_provider": primary,
            "fallback_providers": [],
            "allow_fallback": False,
        }
    }


def _wire_l1_only_cache():
    """Install a fresh L1-only cache for the test and return the
    Cache instance. ``reset_cache`` restores process state at the
    end of each test via the autouse fixture."""
    cache = Cache(l1=LRUBackend(), l2=None)
    # ``src.utils.llm`` looks up ``get_cache`` lazily, so we just
    # need to make that singleton accessor return our instance.
    return cache


class TestFingerprint:
    def _fp(
        self,
        *,
        primary_provider="claude-cli",
        system="",
        prompt="hi",
        output_format="text",
        model=None,
        base_url=None,
    ) -> str:
        return _cache_fingerprint(
            primary_provider=primary_provider,
            system=system,
            prompt=prompt,
            output_format=output_format,
            model=model,
            base_url=base_url,
        )

    def test_same_inputs_same_fingerprint(self) -> None:
        assert self._fp(system="sys") == self._fp(system="sys")

    def test_different_prompts_different_fingerprint(self) -> None:
        assert self._fp(prompt="hi") != self._fp(prompt="hello")

    def test_different_providers_different_fingerprint(self) -> None:
        assert self._fp(primary_provider="claude-cli") != self._fp(
            primary_provider="codex-cli"
        )

    def test_output_format_in_fingerprint(self) -> None:
        """``text`` vs ``json`` produce different responses for the
        same prompt; the fingerprint must distinguish them."""
        assert self._fp(output_format="text") != self._fp(output_format="json")

    def test_model_in_fingerprint(self) -> None:
        """Codex review P2 regression: changing the configured model
        on an API-key provider is a semantic input change. Two
        otherwise-identical calls with different models must yield
        different cache keys; otherwise a model swap would replay
        the previous model's response until TTL."""
        assert self._fp(model="gpt-4") != self._fp(model="gpt-5")
        # Subprocess providers fall back to ``model=None``.
        assert self._fp(model=None) != self._fp(model="gpt-4")

    def test_base_url_in_fingerprint(self) -> None:
        """Codex review P2 regression: the same provider id can be
        pointed at different compatible endpoints via the
        ``base_url`` credential metadata. The fingerprint must
        distinguish endpoints or a swap replays stale responses."""
        assert self._fp(base_url="https://api.openai.com/v1") != self._fp(
            base_url="https://my-proxy.example.com/v1"
        )


class TestCacheRoundtrip:
    def test_cache_false_skips_lookup_and_write(self) -> None:
        """Default ``cache=False`` (agent path) must not hit the cache
        at all -- otherwise an agent reasoning step would receive a
        stale answer."""
        cache = _wire_l1_only_cache()
        calls = {"n": 0}

        def stub(_prompt, **_kw):
            calls["n"] += 1
            return "fresh-answer"

        with (
            patch("src.utils.llm.load_config", return_value=_llm_config()),
            patch("src.utils.llm._dispatch_via_registry_enabled", return_value=False),
            patch("src.utils.llm.claude_generate", side_effect=stub),
            patch("src.cache.get_cache", return_value=cache),
        ):
            generate_text("p", cache=False)
            generate_text("p", cache=False)
        assert calls["n"] == 2
        assert cache.stats()["writes"] == 0

    def test_cache_true_caches_and_replays(self) -> None:
        cache = _wire_l1_only_cache()
        calls = {"n": 0}

        def stub(_prompt, **_kw):
            calls["n"] += 1
            return "cached-answer"

        with (
            patch("src.utils.llm.load_config", return_value=_llm_config()),
            patch("src.utils.llm._dispatch_via_registry_enabled", return_value=False),
            patch("src.utils.llm.claude_generate", side_effect=stub),
            patch("src.cache.get_cache", return_value=cache),
        ):
            first = generate_text("p", cache=True)
            second = generate_text("p", cache=True)
        assert first == second == "cached-answer"
        # First call hit the provider, second was served from cache.
        assert calls["n"] == 1
        assert cache.stats()["hits_l1"] == 1
        assert cache.stats()["writes"] == 1

    def test_cache_hit_records_synthetic_attempt(self) -> None:
        """The trace + cost dashboard read ``last_attempt_chain``;
        a cache hit must register as ``cached=True`` with
        ``kind='cache_hit'`` so they can attribute the call."""
        cache = _wire_l1_only_cache()

        with (
            patch("src.utils.llm.load_config", return_value=_llm_config()),
            patch("src.utils.llm._dispatch_via_registry_enabled", return_value=False),
            patch("src.utils.llm.claude_generate", return_value="answer"),
            patch("src.cache.get_cache", return_value=cache),
        ):
            generate_text("p", cache=True)  # populate
            generate_text("p", cache=True)  # hit
            attempts = last_attempt_chain.get()
        assert len(attempts) == 1
        assert attempts[0]["cached"] is True
        assert attempts[0]["kind"] == "cache_hit"
        assert attempts[0]["ok"] is True

    def test_failure_does_not_pollute_cache(self) -> None:
        """A transient failure must NOT be cached -- otherwise every
        subsequent caller for that prompt would replay the failure
        for the full TTL window."""
        cache = _wire_l1_only_cache()

        with (
            patch("src.utils.llm.load_config", return_value=_llm_config()),
            patch("src.utils.llm._dispatch_via_registry_enabled", return_value=False),
            patch(
                "src.utils.llm.claude_generate",
                side_effect=LLMError("transient timeout"),
            ),
            patch("src.cache.get_cache", return_value=cache),
        ):
            try:
                generate_text("p", cache=True)
            except LLMError:
                pass
        # No write happened.
        assert cache.stats()["writes"] == 0

    def test_cache_failure_does_not_break_call(self) -> None:
        """If the cache itself raises (e.g. Redis explodes mid-call),
        the LLM call must still go through to the provider rather
        than failing the user request."""

        class BoomCache:
            def get(self, *_a, **_kw):
                raise RuntimeError("cache went boom")

            def set(self, *_a, **_kw):
                raise RuntimeError("cache went boom")

        with (
            patch("src.utils.llm.load_config", return_value=_llm_config()),
            patch("src.utils.llm._dispatch_via_registry_enabled", return_value=False),
            patch("src.utils.llm.claude_generate", return_value="ok"),
            patch("src.cache.get_cache", return_value=BoomCache()),
        ):
            result = generate_text("p", cache=True)
        assert result == "ok"

    def test_fallback_response_is_not_cached(self) -> None:
        """Codex review P2 regression: if the primary failed and a
        fallback answered, the answer must NOT be cached under the
        primary's key. Caching it would keep returning the fallback
        response on every subsequent call for the TTL window, even
        after the primary recovers."""
        cache = _wire_l1_only_cache()

        with (
            patch(
                "src.utils.llm.load_config",
                return_value={
                    "llm": {
                        "primary_provider": "claude-cli",
                        "fallback_providers": ["codex-cli"],
                        "allow_fallback": True,
                    }
                },
            ),
            patch("src.utils.llm._dispatch_via_registry_enabled", return_value=False),
            patch(
                "src.utils.llm.claude_generate",
                side_effect=LLMError("primary down, transient"),
            ),
            patch("src.utils.llm.codex_generate", return_value="fallback-answer"),
            patch("src.cache.get_cache", return_value=cache),
        ):
            result = generate_text("p", cache=True)
        assert result == "fallback-answer"
        # Fallback answered -> nothing written to cache.
        assert cache.stats()["writes"] == 0

    def test_different_prompts_do_not_collide(self) -> None:
        cache = _wire_l1_only_cache()
        calls: list[str] = []

        def stub(prompt, **_kw):
            calls.append(prompt)
            return f"reply-to:{prompt}"

        with (
            patch("src.utils.llm.load_config", return_value=_llm_config()),
            patch("src.utils.llm._dispatch_via_registry_enabled", return_value=False),
            patch("src.utils.llm.claude_generate", side_effect=stub),
            patch("src.cache.get_cache", return_value=cache),
        ):
            a = generate_text("first", cache=True)
            b = generate_text("second", cache=True)
            # Second call to each prompt -- both should be cache hits.
            a2 = generate_text("first", cache=True)
            b2 = generate_text("second", cache=True)
        assert calls == ["first", "second"]  # only first hit per prompt
        assert a == a2 == "reply-to:first"
        assert b == b2 == "reply-to:second"


