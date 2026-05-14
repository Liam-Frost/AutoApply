"""Phase 12.2 -- ``autoapply redis`` CLI subcommand tests.

Patches the singleton client factories to return a fakeredis instance
so the CLI exercises the same code paths it would against a real
Redis, without binding tests to a running daemon.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import fakeredis
import pytest
from click.testing import CliRunner

from src.cache.base import CACHE_VERSION
from src.cache.connection import RedisHealth
from src.cli.cmd_redis import redis_cmd


@pytest.fixture
def fake_client() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


class TestPing:
    def test_ping_ok(self, fake_client: fakeredis.FakeRedis) -> None:
        with patch(
            "src.cli.cmd_redis.redis_health",
            return_value=RedisHealth(
                ok=True,
                url="redis://localhost:6379/0",
                detail="PONG",
                latency_ms=3,
            ),
        ):
            result = CliRunner().invoke(redis_cmd, ["ping"])
        assert result.exit_code == 0
        assert "PONG" in result.output

    def test_ping_failure_exits_nonzero(self) -> None:
        with patch(
            "src.cli.cmd_redis.redis_health",
            return_value=RedisHealth(
                ok=False,
                url="redis://localhost:6379/0",
                detail="ConnectionError: refused",
            ),
        ):
            result = CliRunner().invoke(redis_cmd, ["ping"])
        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "refused" in result.output

    def test_ping_json_envelope(self) -> None:
        with patch(
            "src.cli.cmd_redis.redis_health",
            return_value=RedisHealth(
                ok=True,
                url="redis://localhost:6379/0",
                detail="PONG",
                latency_ms=2,
            ),
        ):
            result = CliRunner().invoke(redis_cmd, ["ping", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["data"]["ok"] is True
        assert payload["data"]["detail"] == "PONG"

    def test_ping_json_failure_exits_nonzero(self) -> None:
        """Codex review P2 regression: ``--json`` must still surface
        a failed health check as exit-1 so CI / shell automation can
        act on it without parsing the body."""
        with patch(
            "src.cli.cmd_redis.redis_health",
            return_value=RedisHealth(
                ok=False,
                url="redis://localhost:6379/0",
                detail="ConnectionError",
            ),
        ):
            result = CliRunner().invoke(redis_cmd, ["ping", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["data"]["ok"] is False


class TestInfo:
    def test_info_with_no_keys(self, fake_client: fakeredis.FakeRedis) -> None:
        with (
            patch("src.cli.cmd_redis.reset_redis_client"),
            patch("src.cli.cmd_redis.get_redis_client", return_value=fake_client),
        ):
            result = CliRunner().invoke(redis_cmd, ["info", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["data"]["ok"] is True
        # Every namespace shows up with entries=0.
        for ns_info in payload["data"]["namespaces"].values():
            assert ns_info["entries"] == 0

    def test_info_counts_per_namespace(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        fake_client.setex(f"{CACHE_VERSION}:llm:a", 60, "x")
        fake_client.setex(f"{CACHE_VERSION}:llm:b", 60, "y")
        fake_client.setex(f"{CACHE_VERSION}:embedding:c", 60, "z")
        with (
            patch("src.cli.cmd_redis.reset_redis_client"),
            patch("src.cli.cmd_redis.get_redis_client", return_value=fake_client),
        ):
            result = CliRunner().invoke(redis_cmd, ["info", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        ns = payload["data"]["namespaces"]
        assert ns["llm"]["entries"] == 2
        assert ns["embedding"]["entries"] == 1
        assert ns["response"]["entries"] == 0

    def test_info_unreachable_exits_nonzero(self) -> None:
        with (
            patch("src.cli.cmd_redis.reset_redis_client"),
            patch("src.cli.cmd_redis.get_redis_client", return_value=None),
        ):
            result = CliRunner().invoke(redis_cmd, ["info"])
        assert result.exit_code == 1
        assert "unreachable" in result.output.lower()

    def test_info_unreachable_json_also_exits_nonzero(self) -> None:
        """Codex review P2 regression: JSON is just an output format;
        the failure must still set a non-zero exit code so CI can
        notice it without parsing the body."""
        with (
            patch("src.cli.cmd_redis.reset_redis_client"),
            patch("src.cli.cmd_redis.get_redis_client", return_value=None),
        ):
            result = CliRunner().invoke(redis_cmd, ["info", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["data"]["ok"] is False


class TestFlush:
    def test_flush_namespace(self, fake_client: fakeredis.FakeRedis) -> None:
        fake_client.setex(f"{CACHE_VERSION}:llm:a", 60, "x")
        fake_client.setex(f"{CACHE_VERSION}:llm:b", 60, "y")
        fake_client.setex(f"{CACHE_VERSION}:embedding:c", 60, "z")
        with patch(
            "src.cli.cmd_redis.get_redis_client", return_value=fake_client
        ):
            result = CliRunner().invoke(
                redis_cmd, ["flush", "--namespace", "llm", "--yes"]
            )
        assert result.exit_code == 0
        assert not fake_client.exists(f"{CACHE_VERSION}:llm:a")
        assert not fake_client.exists(f"{CACHE_VERSION}:llm:b")
        # Other namespace survives.
        assert fake_client.exists(f"{CACHE_VERSION}:embedding:c")

    def test_flush_default_clears_cache_version(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        fake_client.setex(f"{CACHE_VERSION}:llm:a", 60, "x")
        fake_client.setex(f"{CACHE_VERSION}:embedding:b", 60, "y")
        # A key outside the cache version prefix survives (e.g. some
        # future Phase 13 job snapshot lives in the same DB).
        fake_client.setex("job:snapshot:z", 60, "snap")
        with patch(
            "src.cli.cmd_redis.get_redis_client", return_value=fake_client
        ):
            result = CliRunner().invoke(redis_cmd, ["flush", "--yes"])
        assert result.exit_code == 0
        assert not fake_client.exists(f"{CACHE_VERSION}:llm:a")
        assert not fake_client.exists(f"{CACHE_VERSION}:embedding:b")
        assert fake_client.exists("job:snapshot:z")

    def test_flush_all_runs_flushdb(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        fake_client.setex(f"{CACHE_VERSION}:llm:a", 60, "x")
        fake_client.setex("job:snapshot:z", 60, "snap")
        with patch(
            "src.cli.cmd_redis.get_redis_client", return_value=fake_client
        ):
            result = CliRunner().invoke(redis_cmd, ["flush", "--all", "--yes"])
        assert result.exit_code == 0
        # Both gone -- FLUSHDB doesn't care about the version prefix.
        assert not fake_client.exists(f"{CACHE_VERSION}:llm:a")
        assert not fake_client.exists("job:snapshot:z")

    def test_flush_namespace_rejects_glob(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        """Codex review P2 regression: ``--namespace '*'`` must NOT
        be interpolated into a SCAN glob -- it would wipe every key
        in the cache version."""
        fake_client.setex(f"{CACHE_VERSION}:llm:a", 60, "x")
        fake_client.setex(f"{CACHE_VERSION}:embedding:b", 60, "y")
        with patch(
            "src.cli.cmd_redis.get_redis_client", return_value=fake_client
        ):
            result = CliRunner().invoke(
                redis_cmd, ["flush", "--namespace", "*", "--yes"]
            )
        # Non-zero exit; the keys must still be present.
        assert result.exit_code == 2
        assert fake_client.exists(f"{CACHE_VERSION}:llm:a")
        assert fake_client.exists(f"{CACHE_VERSION}:embedding:b")

    def test_flush_namespace_rejects_glob_json(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        fake_client.setex(f"{CACHE_VERSION}:llm:a", 60, "x")
        with patch(
            "src.cli.cmd_redis.get_redis_client", return_value=fake_client
        ):
            result = CliRunner().invoke(
                redis_cmd,
                ["flush", "--namespace", "ll*", "--yes", "--json"],
            )
        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert payload["data"]["ok"] is False
        assert payload["data"]["error"] == "invalid_namespace"
        # And the key survived.
        assert fake_client.exists(f"{CACHE_VERSION}:llm:a")

    def test_flush_namespace_and_all_are_mutually_exclusive(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        with patch(
            "src.cli.cmd_redis.get_redis_client", return_value=fake_client
        ):
            result = CliRunner().invoke(
                redis_cmd,
                ["flush", "--namespace", "llm", "--all", "--yes"],
            )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output.lower()

    def test_flush_unreachable_exits_nonzero(self) -> None:
        with patch("src.cli.cmd_redis.get_redis_client", return_value=None):
            result = CliRunner().invoke(redis_cmd, ["flush", "--yes"])
        assert result.exit_code == 1
        assert "unreachable" in result.output.lower()

    def test_flush_unreachable_json_also_exits_nonzero(self) -> None:
        """Codex review P2 regression: same as info, but for the
        destructive path -- this is the one where a silent exit-0 on
        failure would let a CI cache-refresh job fire-and-forget
        thinking it succeeded."""
        with patch("src.cli.cmd_redis.get_redis_client", return_value=None):
            result = CliRunner().invoke(
                redis_cmd, ["flush", "--yes", "--json"]
            )
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["data"]["ok"] is False

    def test_flush_json_envelope_reports_count(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        fake_client.setex(f"{CACHE_VERSION}:llm:a", 60, "x")
        fake_client.setex(f"{CACHE_VERSION}:llm:b", 60, "y")
        with patch(
            "src.cli.cmd_redis.get_redis_client", return_value=fake_client
        ):
            result = CliRunner().invoke(
                redis_cmd,
                ["flush", "--namespace", "llm", "--yes", "--json"],
            )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["data"]["ok"] is True
        assert payload["data"]["deleted"] == 2

    def test_flush_json_without_yes_refuses(
        self, fake_client: fakeredis.FakeRedis
    ) -> None:
        """Codex review P2 regression: ``--json`` must NOT bypass
        ``--yes``. JSON is just an output format, not a confirmation
        for a destructive operation."""
        fake_client.setex(f"{CACHE_VERSION}:llm:a", 60, "x")
        with patch(
            "src.cli.cmd_redis.get_redis_client", return_value=fake_client
        ):
            result = CliRunner().invoke(
                redis_cmd, ["flush", "--namespace", "llm", "--json"]
            )
        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert payload["data"]["ok"] is False
        assert payload["data"]["error"] == "confirmation_required"
        # And the key must still be there -- no destructive op ran.
        assert fake_client.exists(f"{CACHE_VERSION}:llm:a")
