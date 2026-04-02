"""Resume template management.

Templates are .docx files with placeholder variables in {{variable}} syntax.
Each template has named content blocks that can be swapped out per job.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("autoapply.documents.templates")

TEMPLATE_REGISTRY: dict[str, Path] = {}


def register_template(name: str, path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    TEMPLATE_REGISTRY[name] = path
    logger.debug("Registered template '%s' at %s", name, path)


def get_template_path(name: str) -> Path:
    if name not in TEMPLATE_REGISTRY:
        raise KeyError(f"Template '{name}' not registered. Available: {list(TEMPLATE_REGISTRY)}")
    return TEMPLATE_REGISTRY[name]


def discover_templates(template_dir: Path) -> None:
    """Auto-register all .docx files found in template_dir."""
    if not template_dir.exists():
        logger.warning("Template directory not found: %s", template_dir)
        return
    for path in template_dir.glob("*.docx"):
        register_template(path.stem, path)
    logger.info("Discovered %d templates in %s", len(TEMPLATE_REGISTRY), template_dir)
