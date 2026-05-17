"""Phase 17.8: per-document-type material generation defaults.

The user sets one default per document type ('resume', 'cover_letter')
in Settings → Default material strategy. Each default says:

* ``strategy``: ``"regenerate"`` to render from a template, or
  ``"patch_existing"`` to edit a UserDocument from the library in
  place.
* ``default_template_id``: TemplatePackage id (used when strategy is
  ``regenerate`` and the caller didn't override).
* ``default_document_id``: UserDocument id (used when strategy is
  ``patch_existing`` and the caller didn't override).

The Jobs page "Generate" button and plan-run automation both ask
:func:`resolve_material_choice` for the effective triple before
calling the materials router. Per-call overrides win over defaults;
defaults win over a fallback ``regenerate`` with the system-default
template.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import yaml

from src.core.config import PROJECT_ROOT

logger = logging.getLogger("autoapply.application.material_defaults")

MATERIAL_DEFAULTS_PATH = PROJECT_ROOT / "config" / "material_defaults.yaml"

SUPPORTED_DOCUMENT_TYPES = ("resume", "cover_letter")
SUPPORTED_STRATEGIES = ("regenerate", "patch_existing")


def _empty_default() -> dict[str, Any]:
    return {
        "strategy": "regenerate",
        "default_template_id": "",
        "default_document_id": "",
    }


def load_material_defaults() -> dict[str, dict[str, Any]]:
    """Return ``{document_type: {strategy, default_template_id, default_document_id}}``.

    Missing file = empty defaults for both types (regenerate, no
    template pinned — caller falls back to the system default
    template).
    """
    if not MATERIAL_DEFAULTS_PATH.exists():
        return {t: _empty_default() for t in SUPPORTED_DOCUMENT_TYPES}
    try:
        with open(MATERIAL_DEFAULTS_PATH, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except Exception:  # noqa: BLE001
        logger.exception("material_defaults.yaml is unreadable; using empties")
        return {t: _empty_default() for t in SUPPORTED_DOCUMENT_TYPES}

    if not isinstance(raw, dict):
        raw = {}
    out: dict[str, dict[str, Any]] = {}
    for doc_type in SUPPORTED_DOCUMENT_TYPES:
        entry = raw.get(doc_type)
        if not isinstance(entry, dict):
            entry = {}
        out[doc_type] = _normalize_default(entry)
    return out


def save_material_defaults(payload: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Validate + persist. Returns the normalized payload that ended up on disk."""
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "error": "Material defaults payload must be an object.",
            "error_code": "invalid_payload",
        }

    normalized: dict[str, dict[str, Any]] = {}
    for doc_type in SUPPORTED_DOCUMENT_TYPES:
        entry = payload.get(doc_type) or {}
        if not isinstance(entry, dict):
            return {
                "ok": False,
                "error": f"Default for {doc_type!r} must be an object.",
                "error_code": "invalid_payload",
            }
        normalized[doc_type] = _normalize_default(entry)

    MATERIAL_DEFAULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MATERIAL_DEFAULTS_PATH, "w", encoding="utf-8") as fh:
        yaml.safe_dump(normalized, fh, sort_keys=True, allow_unicode=False)

    return {
        "ok": True,
        "status": "saved",
        "defaults": normalized,
    }


def load_material_defaults_data() -> dict[str, Any]:
    return {
        "ok": True,
        "defaults": load_material_defaults(),
        "config_path": str(MATERIAL_DEFAULTS_PATH),
    }


def resolve_material_choice(
    *,
    document_type: str,
    override_strategy: str | None = None,
    override_template_id: str | None = None,
    override_document_id: str | None = None,
) -> dict[str, Any]:
    """Compute the effective generation choice for one document.

    Resolution order, per field:
      strategy    : override → saved default → 'regenerate'
      template_id : override → saved default → '' (caller falls back)
      document_id : override → saved default → '' (only used if
                    strategy == 'patch_existing')

    The returned dict has keys ``strategy``, ``template_id``,
    ``document_id``, ``source`` (an audit string explaining which
    layer won).
    """
    if document_type not in SUPPORTED_DOCUMENT_TYPES:
        raise ValueError(f"unsupported document_type {document_type!r}")
    saved = load_material_defaults().get(document_type, _empty_default())

    strategy = (override_strategy or saved.get("strategy") or "regenerate").strip()
    if strategy not in SUPPORTED_STRATEGIES:
        strategy = "regenerate"

    template_id = (override_template_id or saved.get("default_template_id") or "").strip()
    document_id = (override_document_id or saved.get("default_document_id") or "").strip()

    # If user said patch_existing but no document, downgrade to
    # regenerate so we always produce *something*. Audit the downgrade
    # so callers can surface it.
    downgraded = False
    if strategy == "patch_existing" and not document_id:
        strategy = "regenerate"
        downgraded = True

    source_parts = []
    if override_strategy:
        source_parts.append("override")
    elif saved.get("strategy"):
        source_parts.append("saved-default")
    else:
        source_parts.append("system-default")
    if downgraded:
        source_parts.append("downgraded-no-source-document")

    return {
        "strategy": strategy,
        "template_id": template_id or None,
        "document_id": document_id or None,
        "source": ",".join(source_parts),
    }


def _normalize_default(entry: dict[str, Any]) -> dict[str, Any]:
    strategy = str(entry.get("strategy") or "regenerate").strip()
    if strategy not in SUPPORTED_STRATEGIES:
        strategy = "regenerate"
    template_id = str(entry.get("default_template_id") or "").strip()
    document_id = str(entry.get("default_document_id") or "").strip()
    # Light validation: if document_id is set, ensure it's a UUID-ish
    # string so we don't persist garbage. Permissive: accept any 32+
    # char hex-ish blob to leave room for future id formats.
    if document_id:
        try:
            UUID(document_id)
        except (TypeError, ValueError):
            document_id = ""
    return {
        "strategy": strategy,
        "default_template_id": template_id,
        "default_document_id": document_id,
    }


__all__ = [
    "MATERIAL_DEFAULTS_PATH",
    "SUPPORTED_DOCUMENT_TYPES",
    "SUPPORTED_STRATEGIES",
    "load_material_defaults",
    "load_material_defaults_data",
    "resolve_material_choice",
    "save_material_defaults",
]
