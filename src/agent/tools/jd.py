"""Phase 15.6: ``jd_lookup`` agent tool.

Reads a Job Description snapshot by section, bound to a specific
``job_snapshot_id``. Read-only; the agent cannot mutate JD content
through this tool. Designed to share the dotted-path / paging shape
of :class:`src.agent.tools.profile.ProfileLookupTool` so the cover
letter agent (Phase 15.7) and the future resume / filter agents all
follow the same retrieval idiom.

Why bound to ``job_snapshot_id`` rather than a live JD scrape:

* Audit binding (D019) -- every artifact generated for an application
  must trace back to the exact content the LLM saw. A live scrape can
  drift between the cover-letter agent reading and the user
  submitting.
* Cache-friendliness -- the snapshot is content-hashed and immutable,
  so caching JD lookups is safe across an agent run.
* Phase 17 plan_run pre-fetches the snapshot once; every downstream
  agent reuses the same row.

The tool exposes a small surface:

* ``path="title"`` / ``"location"`` / ``"description"`` / ...
  for scalar fields.
* ``path="requirements.must_have"`` for the structured requirements
  JSONB.
* ``path="`` (empty / unspecified) returns a section index so the
  agent can discover what is available before drilling.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from src.agent.tools.base import Tool, ToolError, ToolResult

logger = logging.getLogger(__name__)


_MAX_RETURN_CHARS = 4_000

# Top-level columns on JobSnapshot we surface as scalar paths.
_SNAPSHOT_SCALARS: tuple[str, ...] = (
    "title",
    "location",
    "employment_type",
    "seniority",
    "description",
    "application_url",
    "content_hash",
)
# JSONB columns the agent can drill into via dotted paths.
_SNAPSHOT_NESTED: tuple[str, ...] = ("requirements", "raw_data")


class JdLookupTool(Tool):
    """Look up a value on the bound ``JobSnapshot`` by dotted path.

    Examples::

        path=""                          -> section index
        path="title"                     -> the role title string
        path="requirements"              -> {"_count": N, "keys": [...]}
        path="requirements.must_have"    -> ["python", "fastapi"]
        path="description"               -> first 4000 chars

    The tool never returns ``None`` -- a missing path produces an
    explanation string with ``is_error=False`` so the agent can adjust
    instead of crashing the loop.
    """

    name = "jd_lookup"
    description = (
        "Read a section of the bound JD snapshot by dotted path. "
        "Use empty path to discover sections. The snapshot is "
        "immutable and content-hashed; values do not change mid-run."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Dotted path, e.g. 'title' or 'requirements.must_have'. "
                    "Empty/omitted returns the section index."
                ),
            },
        },
        "required": [],
    }

    def __init__(self, snapshot: Any, *, snapshot_id: uuid.UUID | str | None = None) -> None:
        """``snapshot`` is the JobSnapshot ORM row (or any object with
        the same attribute surface -- the tool stays decoupled from
        SQLAlchemy so tests can pass a dataclass). ``snapshot_id`` is
        recorded for audit purposes only; the binding is to the
        object passed in here."""
        if snapshot is None:
            raise ToolError("jd_lookup must be bound to a JobSnapshot; got None")
        self._snapshot = snapshot
        self._snapshot_id = str(snapshot_id) if snapshot_id else str(
            getattr(snapshot, "id", "") or ""
        )

    # ----- public ----------------------------------------------------

    def run(self, args: dict[str, Any]) -> ToolResult:
        raw_path = args.get("path") if isinstance(args, dict) else None
        path = (raw_path or "").strip() if isinstance(raw_path, str) else ""
        if not path:
            return self._section_index()

        return self._resolve(path)

    # ----- internals -------------------------------------------------

    def _section_index(self) -> ToolResult:
        scalars: dict[str, str] = {}
        for name in _SNAPSHOT_SCALARS:
            value = getattr(self._snapshot, name, None)
            if value is None:
                continue
            scalars[name] = _summarize_scalar(value)
        nested: dict[str, dict[str, Any]] = {}
        for name in _SNAPSHOT_NESTED:
            value = getattr(self._snapshot, name, None)
            if not value:
                continue
            if isinstance(value, dict):
                nested[name] = {
                    "_count": len(value),
                    "keys": sorted(value.keys())[:32],
                }
        payload = {
            "snapshot_id": self._snapshot_id,
            "scalar_paths": list(scalars.keys()),
            "nested_paths": list(nested.keys()),
            "scalar_previews": scalars,
            "nested_previews": nested,
        }
        return ToolResult(output=_to_json(payload))

    def _resolve(self, path: str) -> ToolResult:
        head, _, tail = path.partition(".")
        if head in _SNAPSHOT_SCALARS:
            value = getattr(self._snapshot, head, None)
            if value is None:
                return ToolResult(
                    output=f"{head!r} is not set on this snapshot."
                )
            return ToolResult(output=_truncate(str(value)))

        if head in _SNAPSHOT_NESTED:
            blob = getattr(self._snapshot, head, None) or {}
            if not isinstance(blob, dict):
                return ToolResult(
                    output=f"{head!r} is not structured (type={type(blob).__name__}).",
                    is_error=True,
                )
            if not tail:
                # Summary view -- count + top-level keys.
                payload = {
                    "_count": len(blob),
                    "keys": sorted(blob.keys()),
                }
                return ToolResult(output=_to_json(payload))
            value = _walk(blob, tail.split("."))
            if value is _MISSING:
                return ToolResult(
                    output=(
                        f"path {path!r} not found; available keys at "
                        f"{head!r}: {sorted(blob.keys())[:32]}"
                    )
                )
            return ToolResult(output=_render(value))

        return ToolResult(
            output=(
                f"unknown top-level path {head!r}; known scalars: "
                f"{list(_SNAPSHOT_SCALARS)}; known nested: "
                f"{list(_SNAPSHOT_NESTED)}"
            )
        )


# ---- Helpers ---------------------------------------------------------


_MISSING = object()


def _walk(blob: Any, tokens: list[str]) -> Any:
    cursor: Any = blob
    for token in tokens:
        if cursor is None:
            return _MISSING
        if token.isdigit() and isinstance(cursor, list):
            idx = int(token)
            if 0 <= idx < len(cursor):
                cursor = cursor[idx]
                continue
            return _MISSING
        if isinstance(cursor, dict):
            if token not in cursor:
                return _MISSING
            cursor = cursor[token]
            continue
        return _MISSING
    return cursor


def _render(value: Any) -> str:
    if isinstance(value, str):
        return _truncate(value)
    if isinstance(value, list | dict):
        payload: dict[str, Any] = {"_count": len(value)}
        if isinstance(value, list):
            payload["items_preview"] = [
                _summarize_scalar(v) for v in value[:20]
            ]
        else:
            payload["keys"] = sorted(value.keys())[:32]
        return _to_json(payload)
    return _truncate(str(value))


def _summarize_scalar(value: Any) -> str:
    text = str(value)
    if len(text) > 160:
        return text[:157] + "..."
    return text


def _truncate(text: str) -> str:
    if len(text) <= _MAX_RETURN_CHARS:
        return text
    return text[: _MAX_RETURN_CHARS - 24] + "...[truncated]"


def _to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str)


__all__ = ["JdLookupTool"]
