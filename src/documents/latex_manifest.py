"""Phase 15.3: helpers for the LaTeX manifest contract.

Lives in ``src/documents/`` (next to ``latex_engine.py``) so the
template manifest, the engine, and the adapter assistant (Phase 15.8)
all share one source of truth for the LaTeX side of the manifest.

What we own here:

* :func:`resolve_field` -- read a dotted IR path against a Pydantic
  IR object. Used by the field-mapping renderer in Phase 15.4.
* :func:`render_command` -- build a single ``\\cmd{arg}{arg2}``
  string from a :class:`LatexFieldMapping`, escaping correctly per
  the package's ``escape_allowlist``.
* :func:`escape_latex` -- the shared escape policy with per-character
  opt-out support so a template that prints raw URLs via ``\\url{}``
  does not see ``%`` mangled.
* :func:`validate_assets` -- assets in the manifest must stay inside
  the package dir (mirrors D013 -- never let a manifest cross-mount
  arbitrary host files).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.documents.templates import LatexConfig, LatexFieldMapping, TemplateManifest

_LATEX_SPECIAL_CHARS = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
}


def escape_latex(value: Any, *, allowlist: list[str] | None = None) -> str:
    """Replace LaTeX special characters in ``value`` with their
    escaped form. Characters listed in ``allowlist`` are passed
    through verbatim (the template promises to handle them).

    ``None``, ``int``, ``float``, ``bool`` are coerced via ``str()``.
    Lists / dicts are joined with newlines / blank strings to keep
    the call sites simple -- a misconfigured mapping returning a list
    of bullets gets a readable rendering rather than ``[1, 2, 3]``.
    """
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(escape_latex(v, allowlist=allowlist) for v in value)
    if isinstance(value, dict):
        # Render dicts as ``key: value`` lines (e.g. for header).
        return "\n".join(
            f"{escape_latex(k, allowlist=allowlist)}: {escape_latex(v, allowlist=allowlist)}"
            for k, v in value.items()
        )
    text = str(value)
    allow = set(allowlist or ())
    out: list[str] = []
    for ch in text:
        if ch in allow:
            out.append(ch)
        elif ch in _LATEX_SPECIAL_CHARS:
            out.append(_LATEX_SPECIAL_CHARS[ch])
        else:
            out.append(ch)
    return "".join(out)


def resolve_field(ir: Any, path: str) -> Any:
    """Walk a dotted path like ``header.name`` or ``experiences.0.name``
    against a Pydantic model or dict. Returns ``None`` when any
    segment is absent; raises only on a truly malformed path
    (non-string token where an attribute is required)."""
    if not path:
        return None
    cursor: Any = ir
    for raw_token in path.split("."):
        if cursor is None:
            return None
        token = raw_token.strip()
        if not token:
            continue
        if token.isdigit():
            try:
                cursor = cursor[int(token)]
            except (KeyError, IndexError, TypeError):
                return None
            continue
        # Try attribute first (Pydantic models), then key (dicts).
        next_value = getattr(cursor, token, _MISSING)
        if next_value is _MISSING:
            if isinstance(cursor, dict):
                next_value = cursor.get(token)
            else:
                return None
        cursor = next_value
    return cursor


def render_command(
    ir: Any,
    mapping: LatexFieldMapping,
    *,
    config: LatexConfig | None = None,
) -> str:
    """Build the LaTeX command string for ``mapping``.

    Returns an empty string when the resolved IR value is empty *and*
    the mapping's ``arity`` is non-zero -- letting the template
    quietly skip optional sections rather than emitting
    ``\\experienceitem{}{}``.
    """
    primary = resolve_field(ir, mapping.ir_field)
    secondary = (
        resolve_field(ir, mapping.second_ir_field) if mapping.second_ir_field else None
    )
    allowlist = list(config.escape_allowlist) if config is not None else None

    primary_escaped = escape_latex(primary, allowlist=allowlist) if primary is not None else ""
    secondary_escaped = (
        escape_latex(secondary, allowlist=allowlist) if secondary is not None else ""
    )

    if mapping.arity == 0:
        return f"\\{mapping.command}"
    if mapping.arity == 1:
        if not primary_escaped:
            return ""
        return f"\\{mapping.command}{{{primary_escaped}}}"
    # arity == 2
    if not primary_escaped and not secondary_escaped:
        return ""
    return f"\\{mapping.command}{{{primary_escaped}}}{{{secondary_escaped}}}"


def validate_assets(manifest: TemplateManifest, package_dir: Path) -> list[str]:
    """Return a list of error strings for every manifest asset that
    cannot be located, or that resolves outside ``package_dir``.

    Empty list means "all assets accounted for"; the 15.8 adapter
    assistant fails to persist a template whose validation list is
    non-empty.
    """
    errors: list[str] = []
    if manifest.latex is None:
        return errors
    package_root = package_dir.resolve()
    for raw_asset in manifest.latex.assets:
        cleaned = (raw_asset or "").strip().replace("\\", "/").lstrip("/")
        if not cleaned:
            errors.append("empty asset path in manifest")
            continue
        candidate = (package_dir / cleaned).resolve()
        if package_root not in candidate.parents and candidate != package_root:
            errors.append(f"asset {raw_asset!r} resolves outside package dir")
            continue
        if not candidate.exists():
            errors.append(f"asset {raw_asset!r} not found at {candidate}")
    return errors


def validate_field_coverage(
    manifest: TemplateManifest,
    ir_fields: set[str],
) -> list[str]:
    """When ``strict_field_coverage`` is on, every IR field present in
    the runtime payload must have a mapping. Returns the names of
    uncovered fields."""
    if manifest.latex is None or not manifest.latex.strict_field_coverage:
        return []
    declared = {mapping.ir_field for mapping in manifest.latex.field_mappings}
    return sorted(ir_fields - declared)


_MISSING = object()


__all__ = [
    "escape_latex",
    "render_command",
    "resolve_field",
    "validate_assets",
    "validate_field_coverage",
]
