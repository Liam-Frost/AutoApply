"""Shared CLI output helpers."""

from __future__ import annotations

import json
from typing import Any

import click

PROTOCOL_VERSION = "1.0"
MESSAGE_TYPE = "autoapply.cli.result"


def build_json_payload(*, command: str, data: dict[str, Any]) -> dict[str, Any]:
    """Wrap command-specific data in a stable CLI protocol envelope."""
    ok = bool(data.get("ok", False))
    error_message = data.get("error")
    error_code = data.get("error_code")

    return {
        "protocol_version": PROTOCOL_VERSION,
        "type": MESSAGE_TYPE,
        "command": command,
        "ok": ok,
        "error": (
            {
                "code": error_code,
                "message": error_message,
            }
            if error_message or error_code
            else None
        ),
        "data": data,
    }


def emit_json(payload: dict) -> None:
    """Render a stable JSON payload to stdout."""
    click.echo(json.dumps(payload, indent=2, sort_keys=True))
