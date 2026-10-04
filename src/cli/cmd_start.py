"""Unified local runtime launcher for AutoApply."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import click

from src.tasks.app import QUEUES


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _default_worker_pool() -> str:
    return "solo" if os.name == "nt" else "prefork"


def _validate_queues(ctx: click.Context, param: click.Parameter, value: str) -> list[str]:
    if not value:
        return list(QUEUES)
    raw = [q.strip() for q in value.split(",") if q.strip()]
    unknown = sorted(set(raw) - set(QUEUES))
    if unknown:
        raise click.BadParameter(f"unknown queue(s): {unknown}; known: {list(QUEUES)}")
    return raw


def _run(
    args: list[str], *, check: bool = True, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        text=True,
        check=check,
        env=env,
    )


def _run_quiet(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _run_capture(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _docker_available() -> bool:
    try:
        return _run_quiet(["docker", "info"]).returncode == 0
    except FileNotFoundError:
        raise click.ClickException(
            "Docker CLI was not found. Install Docker Desktop or run with --skip-docker."
        ) from None


def _compose_service_running(service: str) -> bool:
    try:
        result = _run_capture(["docker", "compose", "ps", "--services", "--status", "running"])
    except FileNotFoundError:
        return False
    if result.returncode != 0:
        return False
    return service in {line.strip() for line in result.stdout.splitlines()}


def _compose_published_port(service: str, container_port: int) -> int | None:
    try:
        result = _run_capture(["docker", "compose", "port", service, str(container_port)])
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    text = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    if not text or ":" not in text:
        return None
    try:
        return int(text.rsplit(":", 1)[1])
    except ValueError:
        return None


def _port_is_bindable(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
        return True
    except OSError:
        return False


def _find_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _runtime_env(postgres_port: int, redis_port: int) -> dict[str, str]:
    env = os.environ.copy()
    env["AUTOAPPLY_DB_HOST"] = env.get("AUTOAPPLY_DB_HOST") or "127.0.0.1"
    env["AUTOAPPLY_DB_PORT"] = str(postgres_port)
    env["AUTOAPPLY_DB_HOST_PORT"] = str(postgres_port)
    env["AUTOAPPLY_REDIS_HOST_PORT"] = str(redis_port)
    env["REDIS_URL"] = env.get("REDIS_URL") or f"redis://127.0.0.1:{redis_port}/0"
    env["CELERY_BROKER_URL"] = env.get("CELERY_BROKER_URL") or env["REDIS_URL"]
    env["CELERY_RESULT_BACKEND"] = env.get("CELERY_RESULT_BACKEND") or env["REDIS_URL"]
    return env


def _resolve_service_ports(
    *, postgres_port: int, redis_port: int, auto_ports: bool, skip_docker: bool
) -> tuple[int, int]:
    resolved_postgres = postgres_port
    resolved_redis = redis_port
    postgres_running = False
    redis_running = False
    if not skip_docker and _compose_service_running("postgres"):
        published = _compose_published_port("postgres", 5432)
        if published:
            resolved_postgres = published
            postgres_running = True
    if not skip_docker and _compose_service_running("redis"):
        published = _compose_published_port("redis", 6379)
        if published:
            resolved_redis = published
            redis_running = True

    if (
        auto_ports
        and not postgres_running
        and not skip_docker 
        and not _port_is_bindable("127.0.0.1", resolved_postgres)
    ):
        fallback = _find_free_port("127.0.0.1")
        click.secho(
            f"Port {resolved_postgres} is not bindable; using Postgres host port {fallback}.",
            fg="yellow",
        )
        resolved_postgres = fallback
    if (
        auto_ports
        and not redis_running
        and not skip_docker
        and not _port_is_bindable("127.0.0.1", resolved_redis)
    ):
        fallback = _find_free_port("127.0.0.1")
        click.secho(
            f"Port {resolved_redis} is not bindable; using Redis host port {fallback}.",
            fg="yellow",
        )
        resolved_redis = fallback
    if not auto_ports and not skip_docker:
        blocked = []
        if not postgres_running and not _port_is_bindable("127.0.0.1", resolved_postgres):
            blocked.append(str(resolved_postgres))
        if not redis_running and not _port_is_bindable("127.0.0.1", resolved_redis):
            blocked.append(str(resolved_redis))
        if blocked:
            raise click.ClickException(
                "Required host port(s) are not bindable: "
                + ", ".join(blocked)
                + ". Free the port(s), choose --postgres-port/--redis-port, "
                + "or omit --no-auto-ports."
            )
    return resolved_postgres, resolved_redis


def _resolve_web_port(*, host: str, port: int, auto_ports: bool) -> int:
    if _port_is_bindable(host, port):
        return port
    if not auto_ports:
        raise click.ClickException(
            f"Web port {host}:{port} is not bindable. Free it, pass --port, "
            "or omit --no-auto-ports."
        )
    fallback = _find_free_port(host)
    click.secho(
        f"Web port {host}:{port} is not bindable; using {host}:{fallback}.",
        fg="yellow",
    )
    return fallback


def _start_docker_runtime() -> bool:
    candidates = []
    if os.name == "nt":
        for key in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(key)
            if base:
                candidates.append(Path(base) / "Docker" / "Docker" / "Docker Desktop.exe")
        for candidate in candidates:
            if candidate.exists():
                subprocess.Popen([str(candidate)], cwd=str(PROJECT_ROOT))
                return True
    elif sys.platform == "darwin":
        if Path("/Applications/Docker.app").exists():
            subprocess.Popen(["open", "-a", "Docker"], cwd=str(PROJECT_ROOT))
            return True
    return False


def _wait_for_docker(timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _docker_available():
            return True
        time.sleep(2)
    return False


def _ensure_docker_services(*, timeout_seconds: int, env: dict[str, str]) -> None:
    if not _docker_available():
        click.secho("Docker is not responding; trying to start Docker Desktop...", fg="yellow")
        if not _start_docker_runtime():
            raise click.ClickException(
                "Docker is not running, and AutoApply could not locate Docker Desktop. "
                "Start Docker/Desktop daemon once, or run with --skip-docker if Postgres/Redis already run elsewhere."
            )
        if not _wait_for_docker(timeout_seconds):
            raise click.ClickException(
                f"Docker Desktop did not become ready within {timeout_seconds}s."
            )
    click.secho("Starting Postgres + Redis via docker compose...", fg="cyan")
    try:
        _run(["docker", "compose", "up", "-d"], env=env)
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(
            "docker compose failed to start Postgres/Redis. If the error mentions "
            "port binding, rerun `uv run autoapply start` so AutoApply can pick "
            "alternate ports, or pass explicit values such as "
            "`--postgres-port 15432 --redis-port 16379`."
        ) from exc


def _start_child(
    label: str, args: list[str], *, env: dict[str, str]
) -> subprocess.Popen[str]:
    click.secho(f"Starting {label}: {' '.join(args)}", fg="cyan")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    return subprocess.Popen(
        args,
        cwd=PROJECT_ROOT,
        text=True,
        creationflags=creationflags,
        env=env,
    )


def _stop_children(children: list[subprocess.Popen[str]]) -> None:
    for child in reversed(children):
        if child.poll() is not None:
            continue
        try:
            if os.name == "nt":
                child.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                child.terminate()
        except Exception:
            child.terminate()
    for child in reversed(children):
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()


@click.command("start")
@click.option("--host", default="127.0.0.1", help="Web bind host.")
@click.option("--port", default=8000, type=int, help="Web bind port.")
@click.option("--no-open", is_flag=True, help="Do not open the browser.")
@click.option("--reload", "use_reload", is_flag=True, help="Enable Uvicorn reload.")
@click.option("--show-logs", is_flag=True, help="Show Uvicorn access/server logs.")
@click.option("--skip-docker", is_flag=True, help="Do not run docker compose up -d.")
@click.option("--skip-migrate", is_flag=True, help="Do not run alembic upgrade head.")
@click.option("--no-worker", is_flag=True, help="Do not start a Celery worker.")
@click.option("--no-beat", is_flag=True, help="Do not start Celery Beat.")
@click.option("--docker-wait", default=90, type=int, help="Seconds to wait for Docker Desktop.")
@click.option("--postgres-port", default=5432, type=int, help="Preferred host port for Postgres.")
@click.option("--redis-port", default=6379, type=int, help="Preferred host port for Redis.")
@click.option(
    "--auto-ports/--no-auto-ports",
    default=True,
    help="Automatically choose alternate host ports when defaults are unavailable.",
)
@click.option(
    "--worker-queues",
    default=",".join(QUEUES),
    callback=_validate_queues,
    help="Comma-separated Celery queues for the local worker.",
)
@click.option("--worker-concurrency", default=2, type=click.IntRange(min=1, max=64))
@click.option(
    "--worker-pool",
    default=_default_worker_pool(),
    type=click.Choice(["solo", "prefork", "threads"]),
    help="Celery worker pool. Windows defaults to solo.",
)
@click.option(
    "--loglevel",
    default="info",
    type=click.Choice(["debug", "info", "warning", "error"]),
)
@click.option("--check", is_flag=True, help="Print planned startup steps and exit.")
def start_cmd(
    host: str,
    port: int,
    no_open: bool,
    use_reload: bool,
    show_logs: bool,
    skip_docker: bool,
    skip_migrate: bool,
    no_worker: bool,
    no_beat: bool,
    docker_wait: int,
    postgres_port: int,
    redis_port: int,
    auto_ports: bool,
    worker_queues: list[str],
    worker_concurrency: int,
    worker_pool: str,
    loglevel: str,
    check: bool,
) -> None:
    """Start the local AutoApply stack: services, worker, beat, and web."""
    postgres_port, redis_port = _resolve_service_ports(
        postgres_port=postgres_port,
        redis_port=redis_port,
        auto_ports=auto_ports,
        skip_docker=skip_docker,
    )
    port = _resolve_web_port(host=host, port=port, auto_ports=auto_ports)
    env = _runtime_env(postgres_port, redis_port)
    worker_args = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "src.tasks",
        "worker",
        "-Q",
        ",".join(worker_queues),
        "-c",
        str(worker_concurrency),
        "--pool",
        worker_pool,
        "-l",
        loglevel,
    ]
    beat_args = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "src.tasks",
        "beat",
        "-S",
        "redbeat.RedBeatScheduler",
        "--max-interval",
        "30",
        "-l",
        loglevel,
    ]
    migrate_args = [sys.executable, "-m", "alembic", "upgrade", "head"]

    if check:
        if not skip_docker:
            click.echo(
                "AUTOAPPLY_DB_HOST_PORT="
                f"{postgres_port} AUTOAPPLY_REDIS_HOST_PORT={redis_port} docker compose up -d"
            )
        if not skip_migrate:
            click.echo(f"AUTOAPPLY_DB_PORT={postgres_port} " + " ".join(migrate_args))
        if not no_worker:
            click.echo(f"REDIS_URL={env['REDIS_URL']} " + " ".join(worker_args))
        if not no_beat:
            click.echo(f"REDIS_URL={env['REDIS_URL']} " + " ".join(beat_args))
        click.echo(
            f"AUTOAPPLY_DB_PORT={postgres_port} REDIS_URL={env['REDIS_URL']} "
            f"uvicorn src.web.app:create_app --factory --host {host} --port {port}"
        )
        return

    if not skip_docker:
        _ensure_docker_services(timeout_seconds=docker_wait, env=env)
    if not skip_migrate:
        click.secho("Applying database migrations...", fg="cyan")
        _run(migrate_args, env=env)

    children: list[subprocess.Popen[str]] = []
    try:
        if not no_worker:
            children.append(_start_child("Celery worker", worker_args, env=env))
        if not no_beat:
            children.append(_start_child("Celery Beat", beat_args, env=env))

        import uvicorn

        url = f"http://{host}:{port}"
        click.secho(f"AutoApply web GUI available at {url}", fg="green")
        if not no_open:
            webbrowser.open(url)
        os.environ.update(env)
        uvicorn.run(
            "src.web.app:create_app",
            host=host,
            port=port,
            reload=use_reload,
            factory=True,
            log_level="info" if show_logs else "warning",
            access_log=show_logs,
        )
    finally:
        _stop_children(children)


__all__ = ["start_cmd"]
