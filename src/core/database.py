"""Database engine and session management.

Uses SQLAlchemy 2.0 async-compatible patterns with psycopg3.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.core.config import get_db_url, load_config


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""


def get_engine(config: dict | None = None):
    """Create a SQLAlchemy engine from config."""
    if config is None:
        config = load_config()
    url = get_db_url(config)
    return create_engine(url, echo=False, pool_pre_ping=True)


def get_session_factory(config: dict | None = None) -> sessionmaker[Session]:
    """Create a session factory."""
    engine = get_engine(config)
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(config: dict | None = None) -> None:
    """Create all tables and enable pgvector extension."""
    engine = get_engine(config)
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(engine)
