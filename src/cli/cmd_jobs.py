"""Phase 13.8: ``autoapply jobs`` subcommand group.

For now only the legacy-cache import is wired up. The Phase 14 PR will
extend the group with ``autoapply jobs refresh <fingerprint>`` and
``autoapply jobs state <id>``.
"""

from __future__ import annotations

from pathlib import Path

import click


@click.group(name="jobs")
def jobs_cmd() -> None:
    """Job Index utilities (Phase 13)."""


@jobs_cmd.command("import-legacy-cache")
@click.option(
    "--legacy-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Override the default data/cache/linkedin_search directory.",
)
@click.option(
    "--delete",
    is_flag=True,
    default=False,
    help="Delete each JSON file after a successful import.",
)
def import_legacy_cache(legacy_dir: Path | None, delete: bool) -> None:
    """Import the legacy file cache into the Phase 13 Job Index.

    Each ``data/cache/linkedin_search/*.json`` file becomes a
    ``search_queries`` row (status='stale' so the next read re-scrapes)
    plus one ``search_results`` link per contained posting. Idempotent:
    re-running the import skips files whose synthetic fingerprint
    already exists.
    """
    from src.core.config import load_config  # noqa: PLC0415
    from src.core.database import get_session_factory  # noqa: PLC0415
    from src.jobs.legacy import import_legacy_file_cache  # noqa: PLC0415
    from src.jobs.store import JobIndexStore  # noqa: PLC0415

    session_factory = get_session_factory(load_config())
    with session_factory() as session, session.begin():
        store = JobIndexStore(session)
        report = import_legacy_file_cache(
            store=store, legacy_dir=legacy_dir, delete_after_import=delete
        )

    click.echo(f"Files seen:      {report.files_seen}")
    click.echo(f"Files imported:  {report.files_imported}")
    click.echo(f"Files skipped:   {report.files_skipped}")
    click.echo(f"Queries created: {report.queries_inserted}")
    click.echo(f"Results linked:  {report.results_linked}")
    if report.errors:
        click.echo("Errors:")
        for err in report.errors:
            click.echo(f"  - {err}")
