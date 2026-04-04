"""Shared CLI output helpers."""

from __future__ import annotations

import json

import click


def emit_json(payload: dict) -> None:
    """Render a stable JSON payload to stdout."""
    click.echo(json.dumps(payload, indent=2, sort_keys=True))
