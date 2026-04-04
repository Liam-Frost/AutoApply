"""Tests for LLM provider selection and fallback behavior."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.utils.llm import LLMError, generate_text, get_llm_settings


class TestLLMSettings:
    def test_legacy_provider_maps_to_primary(self):
        settings = get_llm_settings({"llm": {"provider": "claude-cli", "timeout": 30}})
        assert settings["primary_provider"] == "claude-cli"
        assert settings["fallback_provider"] is None
        assert settings["timeout"] == 30


class TestDirectCLIInvocation:
    def test_claude_uses_system_prompt_flag(self):
        from src.utils.llm import claude_generate

        completed = type("Completed", (), {"returncode": 0, "stdout": "OK", "stderr": ""})()

        with (
            patch("src.utils.llm._resolve_executable", return_value=r"C:\tools\claude.exe"),
            patch("src.utils.llm.subprocess.run", return_value=completed) as mock_run,
        ):
            result = claude_generate("hello", system="be terse")

        assert result == "OK"
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == r"C:\tools\claude.exe"
        assert "--system-prompt" in cmd
        assert "--system" not in cmd

    def test_codex_uses_resolved_executable_path(self):
        from src.utils.llm import codex_generate

        completed = type("Completed", (), {"returncode": 0, "stdout": "OK", "stderr": ""})()

        with (
            patch(
                "src.utils.llm._resolve_executable",
                return_value=r"C:\Users\me\AppData\Roaming\npm\codex.cmd",
            ),
            patch("src.utils.llm.subprocess.run", return_value=completed) as mock_run,
        ):
            result = codex_generate("hello")

        assert result == "OK"
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == r"C:\Users\me\AppData\Roaming\npm\codex.cmd"


class TestLLMFallback:
    def test_falls_back_from_codex_to_claude(self):
        with (
            patch(
                "src.utils.llm.load_config",
                return_value={
                    "llm": {
                        "primary_provider": "codex-cli",
                        "fallback_provider": "claude-cli",
                        "allow_fallback": True,
                    }
                },
            ),
            patch("src.utils.llm.codex_generate", side_effect=LLMError("codex boom")),
            patch("src.utils.llm.claude_generate", return_value="claude ok"),
        ):
            assert generate_text("hello") == "claude ok"

    def test_falls_back_from_claude_to_codex(self):
        with (
            patch(
                "src.utils.llm.load_config",
                return_value={
                    "llm": {
                        "primary_provider": "claude-cli",
                        "fallback_provider": "codex-cli",
                        "allow_fallback": True,
                    }
                },
            ),
            patch("src.utils.llm.claude_generate", side_effect=LLMError("claude boom")),
            patch("src.utils.llm.codex_generate", return_value="codex ok"),
        ):
            assert generate_text("hello") == "codex ok"

    def test_raises_when_fallback_disabled(self):
        with (
            patch(
                "src.utils.llm.load_config",
                return_value={
                    "llm": {
                        "primary_provider": "claude-cli",
                        "fallback_provider": "codex-cli",
                        "allow_fallback": False,
                    }
                },
            ),
            patch("src.utils.llm.claude_generate", side_effect=LLMError("claude boom")),
        ):
            with pytest.raises(LLMError, match="All configured LLM providers failed"):
                generate_text("hello")
