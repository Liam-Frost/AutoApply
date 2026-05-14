"""``autoapply redis`` -- inspect and clear the Phase 12 L2 cache.

Subcommands:

* ``redis ping``   -- round-trip ``PING`` to verify Redis is reachable.
* ``redis info``   -- entry counts per cache namespace + memory usage.
* ``redis flush``  -- clear a namespace, the entire cache version, or
                      (with ``--all``) every key in the configured DB.

Every subcommand supports ``--json`` so automation can parse the
result without scraping human-readable output. The CLI is intentionally
operator-grade -- it does not expose raw Redis primitives; for that,
``redis-cli`` is one ``REDIS_URL`` away.

Why a dedicated CLI surface (instead of, say, only exposing this via
the future inspector UI in 12.6)? Because the cache is the first
piece of infrastructure where "is my Redis even up?" is a real
operator question, and you want to answer it before the UI is on the
line.
"""

from __future__ import annotations

import logging
from typing import Any

import click
from redis.exceptions import RedisError

from src.cache.base import CACHE_VERSION, NAMESPACE_TTLS, namespace_prefix
from src.cache.connection import (
    _resolve_redis_url,
    get_redis_client,
    redis_health,
    reset_redis_client,
)
from src.cli.output import build_json_payload, emit_json

logger = logging.getLogger("autoapply.cli.redis")


@click.group("redis")
def redis_cmd() -> None:
    """Inspect and manage the Phase 12 L2 cache (Redis)."""


# ---------------------------------------------------------------------------
# ping
# ---------------------------------------------------------------------------


@redis_cmd.command("ping")
@click.option("--json", "as_json", is_flag=True, help="Emit a JSON envelope.")
def ping_cmd(as_json: bool) -> None:
    """Round-trip ``PING`` against ``REDIS_URL`` / ``cache.redis_url``."""
    health = redis_health()
    if as_json:
        emit_json(
            build_json_payload(
                command="redis.ping",
                data={
                    "ok": health.ok,
                    "url": health.url,
                    "detail": health.detail,
                    "latency_ms": health.latency_ms,
                },
            )
        )
        # ``--json`` is an output format, not a result indicator: a
        # failed health check must still exit non-zero so CI / shell
        # automation can act on it. Mirrors the human-readable path.
        if not health.ok:
            raise SystemExit(1)
        return
    if health.ok:
        click.echo(
            f"PONG  url={health.url}  latency={health.latency_ms} ms"
        )
    else:
        click.echo(
            f"FAIL  url={health.url}\n      {health.detail}",
            err=True,
        )
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------


def _scan_count(client: Any, pattern: str, *, batch: int = 500) -> int:
    """Return the number of keys matching ``pattern`` using ``SCAN``.

    We could use ``DBSIZE`` for the global count, but per-namespace
    counts require a scan anyway and SCAN does not block Redis.
    """
    count = 0
    cursor = 0
    iterations = 0
    while True:
        cursor, batch_keys = client.scan(cursor=cursor, match=pattern, count=batch)
        count += len(batch_keys)
        iterations += 1
        # Bound the loop -- a pathological pattern shouldn't lock up
        # the CLI thread. 1000 iterations * 500 = 500k keys; well
        # past anything Phase 12 should accumulate.
        if cursor == 0 or iterations >= 1000:
            break
    return count


@redis_cmd.command("info")
@click.option("--json", "as_json", is_flag=True, help="Emit a JSON envelope.")
def info_cmd(as_json: bool) -> None:
    """Show per-namespace entry counts and Redis memory usage."""
    # Force a reload so an operator who just rotated ``REDIS_URL``
    # gets the new target without restarting their shell.
    reset_redis_client()
    client = get_redis_client()
    url = _resolve_redis_url()
    if client is None:
        if as_json:
            emit_json(
                build_json_payload(
                    command="redis.info",
                    data={"ok": False, "url": url, "error": "redis_unreachable"},
                )
            )
            # See ping_cmd: JSON payload describes the failure, but
            # the exit code must still be non-zero so callers can
            # detect it without parsing the body.
            raise SystemExit(1)
        click.echo(f"Redis unreachable at {url}", err=True)
        raise SystemExit(1)

    namespaces: dict[str, dict[str, Any]] = {}
    for ns, ttl in NAMESPACE_TTLS.items():
        prefix = namespace_prefix(ns)
        try:
            count = _scan_count(client, f"{prefix}*")
        except RedisError as exc:
            count = -1
            logger.warning("SCAN for namespace %s failed: %s", ns, exc)
        namespaces[ns] = {
            "prefix": prefix,
            "ttl_seconds": ttl,
            "entries": count,
        }

    info_data: dict[str, Any] = {}
    try:
        raw_info = client.info(section="memory")
        info_data = {
            "used_memory_bytes": raw_info.get("used_memory"),
            "used_memory_human": raw_info.get("used_memory_human"),
            "maxmemory_bytes": raw_info.get("maxmemory") or None,
        }
    except RedisError as exc:
        logger.warning("INFO memory failed: %s", exc)
        info_data = {"error": str(exc)}

    payload = {
        "ok": True,
        "url": url,
        "cache_version": CACHE_VERSION,
        "namespaces": namespaces,
        "memory": info_data,
    }

    if as_json:
        emit_json(build_json_payload(command="redis.info", data=payload))
        return

    click.echo(f"Redis: {url}")
    click.echo(f"Cache version prefix: {CACHE_VERSION}:")
    click.echo("\nNamespaces:")
    for ns, info in namespaces.items():
        entries = "?" if info["entries"] < 0 else str(info["entries"])
        click.echo(
            f"  {ns:<10}  entries={entries:>6}   ttl={info['ttl_seconds']:>8}s   "
            f"prefix={info['prefix']}"
        )
    if "used_memory_human" in info_data:
        click.echo(f"\nMemory: {info_data['used_memory_human']}")


# ---------------------------------------------------------------------------
# flush
# ---------------------------------------------------------------------------


@redis_cmd.command("flush")
@click.option(
    "--namespace",
    "namespace",
    type=str,
    default=None,
    help="Clear only this namespace (e.g. `llm`, `embedding`).",
)
@click.option(
    "--all",
    "flush_all",
    is_flag=True,
    help="Clear every key in the configured Redis DB (destructive).",
)
@click.option(
    "--yes",
    "confirmed",
    is_flag=True,
    help="Skip the interactive confirmation prompt.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a JSON envelope.")
def flush_cmd(
    namespace: str | None, flush_all: bool, confirmed: bool, as_json: bool
) -> None:
    """Clear cache entries.

    Without flags: clears the current cache version's entire keyspace
    (i.e. every key starting with ``{CACHE_VERSION}:``). With
    ``--namespace``: clears just that namespace. With ``--all``:
    runs ``FLUSHDB`` on the configured Redis DB. Mutually exclusive.
    """
    if flush_all and namespace:
        raise click.UsageError("--namespace and --all are mutually exclusive.")

    client = get_redis_client()
    url = _resolve_redis_url()
    if client is None:
        if as_json:
            emit_json(
                build_json_payload(
                    command="redis.flush",
                    data={"ok": False, "url": url, "error": "redis_unreachable"},
                )
            )
            raise SystemExit(1)
        click.echo(f"Redis unreachable at {url}", err=True)
        raise SystemExit(1)

    if namespace:
        try:
            scope = f"namespace {namespace!r}"
            pattern = f"{namespace_prefix(namespace)}*"
        except ValueError as exc:
            # ``namespace_prefix`` rejects anything that could be a
            # Redis glob (e.g. ``--namespace '*'``). Surface the
            # rejection rather than letting the wildcard wipe keys
            # outside the intended namespace.
            if as_json:
                emit_json(
                    build_json_payload(
                        command="redis.flush",
                        data={
                            "ok": False,
                            "url": url,
                            "error": "invalid_namespace",
                            "detail": str(exc),
                        },
                    )
                )
                raise SystemExit(2) from exc
            click.echo(f"Invalid namespace: {exc}", err=True)
            raise SystemExit(2) from exc
    elif flush_all:
        scope = "ENTIRE Redis DB (every key, not just the cache version)"
        pattern = None
    else:
        scope = f"cache version {CACHE_VERSION!r}"
        pattern = f"{CACHE_VERSION}:*"

    if not confirmed:
        # ``--json`` is an output format, not a confirmation. Forcing
        # JSON automation to opt in via ``--yes`` matches every other
        # destructive ``autoapply`` subcommand and prevents a
        # one-flag-typo from wiping the cache.
        if as_json:
            emit_json(
                build_json_payload(
                    command="redis.flush",
                    data={
                        "ok": False,
                        "url": url,
                        "scope": scope,
                        "error": "confirmation_required",
                        "detail": "Pass --yes to confirm destructive flush.",
                    },
                )
            )
            raise SystemExit(2)
        click.confirm(
            f"This will clear {scope} at {url}. Continue?",
            default=False,
            abort=True,
        )

    deleted = 0
    try:
        if pattern is None:
            client.flushdb()
            deleted = -1  # FLUSHDB doesn't report a count
        else:
            cursor = 0
            iterations = 0
            while True:
                cursor, batch = client.scan(cursor=cursor, match=pattern, count=500)
                if batch:
                    deleted += client.delete(*batch)
                iterations += 1
                if cursor == 0 or iterations >= 1000:
                    break
    except RedisError as exc:
        if as_json:
            emit_json(
                build_json_payload(
                    command="redis.flush",
                    data={"ok": False, "url": url, "error": str(exc)},
                )
            )
            raise SystemExit(1) from exc
        click.echo(f"Flush failed: {exc}", err=True)
        raise SystemExit(1) from exc

    if as_json:
        emit_json(
            build_json_payload(
                command="redis.flush",
                data={
                    "ok": True,
                    "url": url,
                    "scope": scope,
                    "deleted": deleted,
                },
            )
        )
        return
    if deleted < 0:
        click.echo(f"Flushed {scope} at {url}.")
    else:
        click.echo(f"Flushed {scope} at {url}. Deleted {deleted} key(s).")
