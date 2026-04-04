"""Alembic migration environment.

Uses AutoApply's config system to get the database URL and model metadata.
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Add project root to sys.path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import get_db_url, load_config
from src.core.database import Base

# Import all models so Base.metadata is populated
from src.core.models import ApplicantProfile, Application, BulletPool, Job, QABank  # noqa: F401

config = context.config

# Set sqlalchemy.url from our config system
app_config = load_config()
config.set_main_option("sqlalchemy.url", get_db_url(app_config))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
