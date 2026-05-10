"""Profile-lookup tool.

We deliberately do not paste the entire applicant profile into the agent
prompt -- that bloats every step's context, and any future profile field
(SSN-equivalent ID, citizenship status, references) would leak by
default. Instead the agent is forced to ask for a specific dotted path,
and every lookup is recorded as an observable step in the trace.

Lookups are read-only. The tool never mutates the profile.
"""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools.base import Tool, ToolError, ToolResult

# Hard cap on the size of any single returned scalar / blob. PII values
# are short by nature; anything beyond this is almost certainly a list
# the agent should be paging through differently.
_MAX_RETURN_CHARS = 4_000


class ProfileLookupTool(Tool):
    """Look up a value in the applicant profile by dotted path.

    Examples:
        path="identity.full_name"          -> "Liam Liu"
        path="identity.email"              -> "frostnova986@gmail.com"
        path="education[0].institution"    -> "University of British Columbia"
        path="education"                   -> {"_count": 2, "items": [...]}

    The tool returns a structured JSON observation so the agent can keep
    drilling without re-fetching the whole subtree.
    """

    name = "profile_lookup"
    description = (
        "Read a value from the applicant profile by dotted path. "
        "Use indexes for list elements, e.g. 'education[0].institution'. "
        "When the path resolves to a list or dict the tool returns a "
        "summary including a `_count` so you can decide whether to drill in."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Dotted path, e.g. 'identity.email' or "
                    "'work_experiences[0].title'."
                ),
            },
        },
        "required": ["path"],
    }

    def __init__(
        self,
        profile_data: dict[str, Any],
        *,
        denylist: set[str] | None = None,
    ) -> None:
        self._profile = profile_data or {}
        # Top-level keys we never expose. Empty by default; callers can
        # blacklist sections like raw resume bytes if they ever appear.
        self._denylist = denylist or set()

    def run(self, args: dict[str, Any]) -> ToolResult:
        path = args.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ToolError("'path' must be a non-empty string.")
        path = path.strip()

        try:
            tokens = _parse_path(path)
        except ValueError as exc:
            return ToolResult(output=f"Invalid path: {exc}", is_error=True)

        if tokens and tokens[0] in self._denylist:
            return ToolResult(
                output=(
                    f"Section {tokens[0]!r} is blocked from agent lookup. "
                    "Ask the user to mediate."
                ),
                is_error=True,
            )

        try:
            value = _walk(self._profile, tokens)
        except KeyError as exc:
            return ToolResult(
                output=f"Profile path {path!r} not found: {exc}.",
                is_error=True,
            )
        except IndexError as exc:
            return ToolResult(
                output=f"Profile path {path!r} index error: {exc}.",
                is_error=True,
            )

        rendered = _render_value(value)
        if len(rendered) > _MAX_RETURN_CHARS:
            rendered = rendered[: _MAX_RETURN_CHARS - 14] + "…[truncated]"
        return ToolResult(output=rendered, data={"path": path, "value": _coerce(value)})


# ---------------------------------------------------------------------------
# Path parsing / walking
# ---------------------------------------------------------------------------


def _parse_path(path: str) -> list[str | int]:
    """Split a dotted path with optional ``[index]`` segments.

    Indexes must be plain non-negative integers; anything else is an
    error. We do not support quoted keys with dots in them -- the
    profile schema is stable and uses safe identifiers throughout.
    """
    tokens: list[str | int] = []
    buf = ""
    i = 0
    while i < len(path):
        ch = path[i]
        if ch == ".":
            if buf:
                tokens.append(buf)
                buf = ""
            i += 1
            continue
        if ch == "[":
            if buf:
                tokens.append(buf)
                buf = ""
            close = path.find("]", i + 1)
            if close == -1:
                raise ValueError("unterminated '[' in path")
            inside = path[i + 1 : close]
            if not inside.isdigit():
                raise ValueError(f"non-integer index {inside!r}")
            tokens.append(int(inside))
            i = close + 1
            continue
        buf += ch
        i += 1
    if buf:
        tokens.append(buf)
    if not tokens:
        raise ValueError("empty path")
    if not isinstance(tokens[0], str):
        raise ValueError("path must start with a key, not an index")
    return tokens


def _walk(data: Any, tokens: list[str | int]) -> Any:
    cursor: Any = data
    for tok in tokens:
        if isinstance(tok, int):
            if not isinstance(cursor, list):
                raise KeyError(
                    f"expected list at index [{tok}], got {type(cursor).__name__}"
                )
            if tok < 0 or tok >= len(cursor):
                raise IndexError(f"index {tok} out of range (len={len(cursor)})")
            cursor = cursor[tok]
        else:
            if not isinstance(cursor, dict):
                raise KeyError(
                    f"expected dict at key {tok!r}, got {type(cursor).__name__}"
                )
            if tok not in cursor:
                raise KeyError(f"key {tok!r} not present")
            cursor = cursor[tok]
    return cursor


def _render_value(value: Any) -> str:
    """Stringify a value for the agent observation channel.

    Scalars come back as plain strings. Containers come back as a small
    JSON envelope with a count + a preview, so the agent learns the
    shape without us pasting the whole thing.
    """
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, list):
        preview = value[:5]
        return json.dumps(
            {"_count": len(value), "preview": [_coerce(x) for x in preview]},
            ensure_ascii=False,
        )
    if isinstance(value, dict):
        return json.dumps(
            {"_keys": sorted(value.keys()), "value": _coerce(value)},
            ensure_ascii=False,
        )
    return str(value)


def _coerce(value: Any) -> Any:
    """JSON-friendly coercion (defensive; profile data is YAML-clean today)."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_coerce(x) for x in value]
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    return str(value)
