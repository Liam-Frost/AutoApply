"""Phase 12 -- ``get_cache_settings`` resolution order.

Locks in the env > settings > default priority so future refactors
can't silently re-order it.
"""

from __future__ import annotations

import pytest

from src.core.config import get_cache_settings


class TestCacheSettingsResolution:
    def test_env_var_wins_over_settings(self, monkeypatch) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://env-host:6380/3")
        out = get_cache_settings(
            {"cache": {"redis_url": "redis://yaml-host:6379/0"}}
        )
        assert out["redis_url"] == "redis://env-host:6380/3"

    def test_settings_used_when_env_unset(self, monkeypatch) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        out = get_cache_settings({"cache": {"redis_url": "redis://yaml-host:6379/0"}})
        assert out["redis_url"] == "redis://yaml-host:6379/0"

    def test_default_used_when_unset(self, monkeypatch) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        out = get_cache_settings({})
        assert out["redis_url"] == "redis://localhost:6379/0"

    def test_l1_max_entries_defaults_to_1024(self, monkeypatch) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        out = get_cache_settings({})
        assert out["l1_max_entries"] == 1024

    def test_l1_max_entries_honoured(self, monkeypatch) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        out = get_cache_settings({"cache": {"l1_max_entries": 2048}})
        assert out["l1_max_entries"] == 2048

    def test_l1_max_entries_negative_falls_back_to_default(
        self, monkeypatch
    ) -> None:
        """A misconfigured negative value must not blow up the cache
        boot; fall back to the safe default instead."""
        monkeypatch.delenv("REDIS_URL", raising=False)
        out = get_cache_settings({"cache": {"l1_max_entries": -50}})
        assert out["l1_max_entries"] == 1024

    def test_l1_max_entries_non_int_falls_back(self, monkeypatch) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        out = get_cache_settings({"cache": {"l1_max_entries": "lots"}})
        assert out["l1_max_entries"] == 1024

    @pytest.mark.parametrize("bad_cache", [None, "scalar", 42, []])
    def test_malformed_cache_section_uses_defaults(
        self, monkeypatch, bad_cache
    ) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        out = get_cache_settings({"cache": bad_cache})
        assert out["redis_url"] == "redis://localhost:6379/0"
        assert out["l1_max_entries"] == 1024

    @pytest.mark.parametrize("bad_url", [123, None, [], {}, ""])
    def test_non_string_redis_url_falls_back_to_default(
        self, monkeypatch, bad_url
    ) -> None:
        """Codex review P2 regression: a YAML typo like
        ``redis_url: 123`` must not reach ``Redis.from_url`` -- the
        connection layer can't catch every error type that produces,
        so we normalise to a string at the settings boundary."""
        monkeypatch.delenv("REDIS_URL", raising=False)
        out = get_cache_settings({"cache": {"redis_url": bad_url}})
        assert out["redis_url"] == "redis://localhost:6379/0"

    def test_whitespace_redis_url_falls_back_to_default(
        self, monkeypatch
    ) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        out = get_cache_settings({"cache": {"redis_url": "   "}})
        assert out["redis_url"] == "redis://localhost:6379/0"

    def test_redis_url_is_trimmed(self, monkeypatch) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        out = get_cache_settings({"cache": {"redis_url": "  redis://h:6379/0  "}})
        assert out["redis_url"] == "redis://h:6379/0"
