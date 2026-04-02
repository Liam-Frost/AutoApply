"""Global configuration loader.

Loads settings from config/settings.yaml and .env, with environment variable overrides.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Project root is two levels up from this file (src/core/config.py -> AutoApply/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load configuration from YAML file with .env overrides.

    Priority (highest to lowest):
    1. Environment variables (AUTOAPPLY_DB_PASSWORD, etc.)
    2. .env file
    3. config/settings.yaml defaults
    """
    # Load .env if it exists
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    # Load YAML config
    if config_path is None:
        config_path = PROJECT_ROOT / "config" / "settings.yaml"

    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Apply environment variable overrides
    _apply_env_overrides(config)

    # Resolve relative paths against project root
    _resolve_paths(config)

    return config


def _apply_env_overrides(config: dict[str, Any]) -> None:
    """Override config values from environment variables."""
    env_map = {
        "AUTOAPPLY_DB_HOST": ("database", "host"),
        "AUTOAPPLY_DB_PORT": ("database", "port"),
        "AUTOAPPLY_DB_NAME": ("database", "name"),
        "AUTOAPPLY_DB_USER": ("database", "user"),
        "AUTOAPPLY_DB_PASSWORD": ("database", "password"),
        "AUTOAPPLY_LOG_LEVEL": ("logging", "level"),
    }
    for env_var, path in env_map.items():
        value = os.environ.get(env_var)
        if value is not None:
            section = config
            for key in path[:-1]:
                section = section.setdefault(key, {})
            # Convert port to int
            if path[-1] == "port":
                value = int(value)
            section[path[-1]] = value


def _resolve_paths(config: dict[str, Any]) -> None:
    """Resolve relative paths in config against PROJECT_ROOT."""
    docs = config.get("documents", {})
    for key in ("output_dir", "template_dir"):
        if key in docs and not Path(docs[key]).is_absolute():
            docs[key] = str(PROJECT_ROOT / docs[key])

    log_cfg = config.get("logging", {})
    if "file" in log_cfg and not Path(log_cfg["file"]).is_absolute():
        log_cfg["file"] = str(PROJECT_ROOT / log_cfg["file"])


def get_db_url(config: dict[str, Any]) -> str:
    """Build PostgreSQL connection URL from config."""
    db = config["database"]
    password = db.get("password", "")
    auth = f"{db['user']}:{password}" if password else db["user"]
    return f"postgresql+psycopg://{auth}@{db['host']}:{db['port']}/{db['name']}"
