"""``autoapply web`` -- launch the web GUI."""

from __future__ import annotations

import logging
import webbrowser

import click

logger = logging.getLogger("autoapply.cli.web")


@click.command("web")
@click.option("--host", default="127.0.0.1", help="Bind host.")
@click.option("--port", default=8000, help="Bind port.")
@click.option("--no-open", is_flag=True, help="Don't auto-open browser.")
@click.option("--reload", "use_reload", is_flag=True, help="Enable auto-reload for development.")
@click.option("--show-logs", is_flag=True, help="Show Uvicorn server and access logs.")
def web_cmd(host: str, port: int, no_open: bool, use_reload: bool, show_logs: bool) -> None:
    """Launch the AutoApply web dashboard."""
    import uvicorn

    url = f"http://{host}:{port}"
    click.secho(f"AutoApply web GUI available at {url}", fg="green")

    if not no_open:
        webbrowser.open(url)

    try:
        uvicorn.run(
            "src.web.app:create_app",
            host=host,
            port=port,
            reload=use_reload,
            factory=True,
            log_level="info" if show_logs else "critical",
            access_log=show_logs,
        )
    except Exception as exc:
        logger.exception("Failed to start web GUI")
        raise click.ClickException(f"Failed to start web GUI: {exc}") from exc
