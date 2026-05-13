"""Phase 11.1 -- ordered fallback chain + error classification.

These tests cover the new behaviour layered on top of the existing
:class:`tests.test_llm.TestLLMFallback` cases:

* multi-element ``fallback_providers`` chains
* error classification (HTTP status + CLI text) and the transient gate
* attempt-chain bookkeeping on success, transient-only failure, and
  fatal abort
* :data:`src.utils.llm.last_attempt_chain` ContextVar plumbing
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.providers.base import (
    ProviderError,
    ProviderErrorKind,
    classify_cli_error,
    classify_http_status,
)
from src.utils.llm import LLMError, generate_text, get_llm_settings, last_attempt_chain


class TestSettingsChain:
    def test_list_shape_is_honoured(self):
        settings = get_llm_settings(
            {
                "llm": {
                    "primary_provider": "claude-cli",
                    "fallback_providers": ["codex-cli", "openai"],
                    "allow_fallback": True,
                }
            }
        )
        assert settings["fallback_providers"] == ["codex-cli", "openai"]
        # fallback_provider mirrors the first entry for back-compat
        assert settings["fallback_provider"] == "codex-cli"

    def test_legacy_scalar_is_promoted_to_chain(self):
        settings = get_llm_settings(
            {
                "llm": {
                    "primary_provider": "claude-cli",
                    "fallback_provider": "codex-cli",
                    "allow_fallback": True,
                }
            }
        )
        assert settings["fallback_providers"] == ["codex-cli"]

    def test_primary_is_removed_from_chain(self):
        settings = get_llm_settings(
            {
                "llm": {
                    "primary_provider": "claude-cli",
                    "fallback_providers": ["claude-cli", "codex-cli"],
                    "allow_fallback": True,
                }
            }
        )
        # 'claude-cli' appears as primary so the chain skips the dup
        assert settings["fallback_providers"] == ["codex-cli"]

    def test_duplicates_in_chain_collapse(self):
        settings = get_llm_settings(
            {
                "llm": {
                    "primary_provider": "claude-cli",
                    "fallback_providers": ["codex-cli", "codex-cli", "openai"],
                    "allow_fallback": True,
                }
            }
        )
        assert settings["fallback_providers"] == ["codex-cli", "openai"]

    def test_comma_string_is_accepted(self):
        settings = get_llm_settings(
            {
                "llm": {
                    "primary_provider": "claude-cli",
                    "fallback_providers": "codex-cli, openai",
                    "allow_fallback": True,
                }
            }
        )
        assert settings["fallback_providers"] == ["codex-cli", "openai"]


class TestClassifiers:
    @pytest.mark.parametrize(
        ("status", "kind"),
        [
            (401, ProviderErrorKind.AUTH),
            (403, ProviderErrorKind.AUTH),
            (429, ProviderErrorKind.QUOTA),
            (400, ProviderErrorKind.BAD_REQUEST),
            (404, ProviderErrorKind.BAD_REQUEST),
            (500, ProviderErrorKind.SERVER),
            (503, ProviderErrorKind.SERVER),
            (200, ProviderErrorKind.UNKNOWN),
        ],
    )
    def test_classify_http_status(self, status, kind):
        assert classify_http_status(status) == kind

    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("Claude CLI timed out after 60s", ProviderErrorKind.TIMEOUT),
            ("Please login first via `codex login`", ProviderErrorKind.AUTH),
            ("Rate limit exceeded for this minute", ProviderErrorKind.QUOTA),
            ("HTTP 429 from upstream", ProviderErrorKind.QUOTA),
            ("Codex CLI not found. Install with: npm install ...", ProviderErrorKind.AUTH),
            ("some weird thing happened", ProviderErrorKind.UNKNOWN),
        ],
    )
    def test_classify_cli_error(self, text, kind):
        assert classify_cli_error(text) == kind

    def test_transient_gate(self):
        assert ProviderErrorKind.NETWORK.is_transient is True
        assert ProviderErrorKind.QUOTA.is_transient is True
        assert ProviderErrorKind.AUTH.is_transient is True
        assert ProviderErrorKind.TIMEOUT.is_transient is True
        assert ProviderErrorKind.SERVER.is_transient is True
        assert ProviderErrorKind.UNKNOWN.is_transient is True
        # Non-transient: don't waste a fallback hop on a malformed prompt
        assert ProviderErrorKind.BAD_REQUEST.is_transient is False
        assert ProviderErrorKind.PARSE.is_transient is False


def _chain_config(*providers: str) -> dict:
    return {
        "llm": {
            "primary_provider": providers[0],
            "fallback_providers": list(providers[1:]),
            "allow_fallback": True,
        }
    }


class TestThreeProviderChain:
    """Three providers; both legacy CLI ids are exercised + the registry."""

    def test_succeeds_on_first(self):
        with (
            patch(
                "src.utils.llm.load_config",
                return_value=_chain_config("claude-cli", "codex-cli"),
            ),
            patch("src.utils.llm._dispatch_via_registry_enabled", return_value=False),
            patch("src.utils.llm.claude_generate", return_value="primary win"),
            patch("src.utils.llm.codex_generate", side_effect=AssertionError("not reached")),
        ):
            assert generate_text("p") == "primary win"
            chain = last_attempt_chain.get()
            assert [a["provider"] for a in chain] == ["claude-cli"]
            assert chain[0]["ok"] is True

    def test_advances_past_transient_failures(self):
        # Two transient failures then a third success.
        primary_err = LLMError("claude rate limit hit")  # classify -> QUOTA
        secondary_err = LLMError("codex CLI timed out after 60s")  # classify -> TIMEOUT
        with (
            patch(
                "src.utils.llm.load_config",
                return_value=_chain_config("claude-cli", "codex-cli"),
            ),
            patch("src.utils.llm._dispatch_via_registry_enabled", return_value=False),
            patch("src.utils.llm.claude_generate", side_effect=primary_err),
            patch("src.utils.llm.codex_generate", side_effect=secondary_err),
        ):
            with pytest.raises(LLMError) as excinfo:
                generate_text("p")

        attempts = excinfo.value.attempts
        assert [a["provider"] for a in attempts] == ["claude-cli", "codex-cli"]
        assert attempts[0]["kind"] == ProviderErrorKind.QUOTA.value
        assert attempts[1]["kind"] == ProviderErrorKind.TIMEOUT.value
        assert all(a["ok"] is False for a in attempts)

    def test_stops_on_non_transient(self):
        # First provider raises a ProviderError(BAD_REQUEST). The second
        # provider must NOT be called because retrying a malformed prompt
        # elsewhere just burns money on the same failure.
        bad = ProviderError("400 invalid prompt", kind=ProviderErrorKind.BAD_REQUEST)
        wrapped = LLMError("Provider 'claude-cli' failed: 400 invalid prompt")
        wrapped.__cause__ = bad

        codex_calls = {"n": 0}

        def codex_stub(*_args, **_kwargs):
            codex_calls["n"] += 1
            return "should not be reached"

        with (
            patch(
                "src.utils.llm.load_config",
                return_value=_chain_config("claude-cli", "codex-cli"),
            ),
            patch("src.utils.llm._dispatch_via_registry_enabled", return_value=False),
            patch("src.utils.llm.claude_generate", side_effect=wrapped),
            patch("src.utils.llm.codex_generate", side_effect=codex_stub),
        ):
            with pytest.raises(LLMError, match="non-transient"):
                generate_text("p")

        assert codex_calls["n"] == 0


class TestAttemptChainSideChannel:
    def test_contextvar_is_reset_on_each_call(self):
        with (
            patch(
                "src.utils.llm.load_config",
                return_value=_chain_config("claude-cli", "codex-cli"),
            ),
            patch("src.utils.llm._dispatch_via_registry_enabled", return_value=False),
            patch("src.utils.llm.claude_generate", side_effect=LLMError("first quota")),
            patch("src.utils.llm.codex_generate", return_value="ok"),
        ):
            assert generate_text("a") == "ok"
            first = list(last_attempt_chain.get())

        with (
            patch(
                "src.utils.llm.load_config",
                return_value=_chain_config("claude-cli"),
            ),
            patch("src.utils.llm._dispatch_via_registry_enabled", return_value=False),
            patch("src.utils.llm.claude_generate", return_value="ok2"),
        ):
            assert generate_text("b") == "ok2"
            second = list(last_attempt_chain.get())

        assert len(first) == 2
        assert len(second) == 1  # ContextVar reset between calls
