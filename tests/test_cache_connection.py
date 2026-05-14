"""Phase 12 -- ``src.cache.connection`` resilience tests.

The cache contract promises that any failure to reach Redis degrades
to L1-only rather than propagating an exception. The connection
layer is where that contract is enforced, so we exercise it
exhaustively: transport failures, malformed URLs, DNS-style socket
errors.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from src.cache.connection import (
    get_redis_client,
    redis_health,
    reset_redis_client,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_redis_client()
    yield
    reset_redis_client()


class TestMalformedUrl:
    def test_get_redis_client_returns_none_on_value_error(
        self, monkeypatch
    ) -> None:
        """Codex review P2 regression: ``Redis.from_url('garbage')``
        raises ``ValueError``, not a Redis exception. The connection
        layer must catch it and return ``None`` so the cache degrades
        rather than crashing."""
        monkeypatch.setenv("REDIS_URL", "not-a-real-url")
        # The malformed URL path can raise during construction or
        # during ping; either way the helper must swallow it.
        assert get_redis_client() is None

    def test_redis_health_reports_failure_for_malformed_url(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("REDIS_URL", "totally-broken-scheme")
        health = redis_health()
        assert health.ok is False
        # The detail field should carry the underlying error message
        # so operators can see why their URL was rejected.
        assert health.detail


class TestTransportErrors:
    def test_get_redis_client_returns_none_on_connection_refused(
        self, monkeypatch
    ) -> None:
        """A reachable Redis URL pointing at a dead daemon must
        degrade the same way as a malformed URL."""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:1/0")
        with patch(
            "src.cache.connection.redis.Redis.from_url"
        ) as from_url:
            client = from_url.return_value
            client.ping.side_effect = RedisConnectionError("refused")
            assert get_redis_client() is None

    def test_get_redis_client_returns_none_on_oserror(
        self, monkeypatch
    ) -> None:
        """DNS failures surface as OSError, not RedisError."""
        monkeypatch.setenv("REDIS_URL", "redis://nope.invalid:6379/0")
        with patch(
            "src.cache.connection.redis.Redis.from_url"
        ) as from_url:
            from_url.side_effect = OSError("Name or service not known")
            assert get_redis_client() is None

    def test_redis_health_reports_failure_on_oserror(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://nope.invalid:6379/0")
        with patch(
            "src.cache.connection.redis.Redis.from_url"
        ) as from_url:
            from_url.side_effect = OSError("Name or service not known")
            health = redis_health()
        assert health.ok is False


class TestSingletonReuse:
    def test_same_url_returns_same_instance(self, monkeypatch) -> None:
        """Healthy client must be cached so callers don't re-handshake
        every call. ``force_reload`` is the only way to rebuild."""
        monkeypatch.setenv("REDIS_URL", "redis://example:6379/0")
        with patch(
            "src.cache.connection.redis.Redis.from_url"
        ) as from_url:
            client = from_url.return_value
            client.ping.return_value = True
            first = get_redis_client()
            second = get_redis_client()
        assert first is second is client

    def test_url_change_rebuilds_client(self, monkeypatch) -> None:
        with patch(
            "src.cache.connection.redis.Redis.from_url"
        ) as from_url:
            client = from_url.return_value
            client.ping.return_value = True

            monkeypatch.setenv("REDIS_URL", "redis://host-a:6379/0")
            get_redis_client()
            monkeypatch.setenv("REDIS_URL", "redis://host-b:6379/0")
            get_redis_client()

            # Two distinct URLs -> two ``from_url`` calls.
            assert from_url.call_count == 2
