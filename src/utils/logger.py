"""Logging setup for AutoApply.

Configures file + console logging with rotation.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any


def setup_logging(config: dict[str, Any]) -> logging.Logger:
    """Configure and return the root application logger."""
    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    fmt = log_cfg.get("format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root_logger = logging.getLogger("autoapply")
    root_logger.setLevel(level)

    # Avoid duplicate handlers on re-init
    if root_logger.handlers:
        return root_logger

    formatter = logging.Formatter(fmt)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root_logger.addHandler(console)

    # File handler
    log_file = log_cfg.get("file")
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    return root_logger
