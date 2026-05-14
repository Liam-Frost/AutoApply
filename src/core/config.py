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


def load_raw_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load config YAML without env overrides or path resolution."""
    if config_path is None:
        config_path = PROJECT_ROOT / "config" / "settings.yaml"

    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_config(config: dict[str, Any], config_path: Path | None = None) -> None:
    """Persist config YAML to disk."""
    if config_path is None:
        config_path = PROJECT_ROOT / "config" / "settings.yaml"

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False, allow_unicode=False)


def update_llm_settings(
    primary_provider: str,
    fallback_provider: str | None,
    allow_fallback: bool,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Update the persisted LLM provider settings in config/settings.yaml.

    Phase 11.1 added the list-form ``fallback_providers``. Writers must
    keep both the scalar and the list in sync; otherwise a user who has
    already migrated to the list form will not see fallback changes
    take effect (``get_llm_settings`` prefers the list when both
    exist).
    """
    config = load_raw_config(config_path)
    llm = config.setdefault("llm", {})
    llm["provider"] = primary_provider
    llm["primary_provider"] = primary_provider
    llm["fallback_provider"] = fallback_provider
    llm["fallback_providers"] = [fallback_provider] if fallback_provider else []
    llm["allow_fallback"] = allow_fallback
    save_config(config, config_path)
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
    """Build PostgreSQL connection URL from config.

    Credentials are percent-encoded so special characters (@, :, /, #, etc.)
    in usernames or passwords do not break URL parsing.
    """
    from urllib.parse import quote_plus

    db = config["database"]
    user = quote_plus(str(db["user"]))
    password = db.get("password", "")
    auth = f"{user}:{quote_plus(str(password))}" if password else user
    return f"postgresql+psycopg://{auth}@{db['host']}:{db['port']}/{db['name']}"


def get_cache_settings(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the normalised Phase 12 cache configuration.

    Resolution order matches :mod:`src.cache.connection`:
      1. ``REDIS_URL`` env var
      2. ``cache.redis_url`` in ``settings.yaml``
      3. ``redis://localhost:6379/0`` default

    The ``l1_max_entries`` setting clamps the in-process LRU. Returning
    a normalised dict here keeps the cache layer from each having its
    own copy of the resolution rules.
    """
    import os

    if config is None:
        config = load_config()
    raw = config.get("cache", {}) if isinstance(config, dict) else {}
    if not isinstance(raw, dict):
        raw = {}

    env_url = os.environ.get("REDIS_URL")
    yaml_url = raw.get("redis_url")
    # Normalise to a string at the settings boundary so a YAML typo
    # like ``redis_url: 123`` can't reach ``Redis.from_url()`` and
    # raise a ``TypeError`` past the connection layer's defences.
    if env_url and isinstance(env_url, str) and env_url.strip():
        redis_url = env_url.strip()
    elif isinstance(yaml_url, str) and yaml_url.strip():
        redis_url = yaml_url.strip()
    else:
        redis_url = "redis://localhost:6379/0"

    l1_raw = raw.get("l1_max_entries", 1024)
    try:
        l1_max_entries = int(l1_raw)
    except (TypeError, ValueError):
        l1_max_entries = 1024
    if l1_max_entries <= 0:
        l1_max_entries = 1024

    return {
        "redis_url": redis_url,
        "l1_max_entries": l1_max_entries,
    }
