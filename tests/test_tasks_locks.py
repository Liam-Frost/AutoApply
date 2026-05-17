"""Phase 14.10: tests for the advisory-lock backstop.

Runs against the live dev Postgres -- advisory locks are a
Postgres-specific feature so an in-memory fake is not useful here.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import get_db_url, load_config
from src.tasks.locks import advisory_lock, hash_for_key


@pytest.fixture(scope="module")
def engine():
    return create_engine(get_db_url(load_config()))


@pytest.fixture
def session_a(engine) -> Session:
    s = sessionmaker(bind=engine)()
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def session_b(engine) -> Session:
    s = sessionmaker(bind=engine)()
    yield s
    s.rollback()
    s.close()


def test_hash_is_stable_per_key() -> None:
    assert hash_for_key("plan_run:default") == hash_for_key("plan_run:default")
    assert hash_for_key("a") != hash_for_key("b")
    # Fits in a signed 64-bit slot (the column type for advisory locks).
    assert 0 <= hash_for_key("anything") < (1 << 63)


def test_advisory_lock_is_exclusive_across_two_sessions(
    session_a: Session, session_b: Session
) -> None:
    """The whole point: process A holding the lock means process B
    can not also hold it."""
    key = "test:phase-14-10:exclusive"
    with session_a.begin():
        with advisory_lock(session_a, key) as acquired_a:
            assert acquired_a is True
            # While A still holds the lock, B's attempt must observe it.
            with session_b.begin():
                with advisory_lock(session_b, key) as acquired_b:
                    assert acquired_b is False
    # After A's transaction commits, B can claim it on a fresh tx.
    with session_b.begin():
        with advisory_lock(session_b, key) as acquired_after:
            assert acquired_after is True


def test_advisory_lock_releases_on_rollback(
    session_a: Session, session_b: Session
) -> None:
    key = "test:phase-14-10:rollback"
    try:
        with session_a.begin():
            with advisory_lock(session_a, key) as acquired_a:
                assert acquired_a is True
                raise RuntimeError("simulate failure mid-critical-section")
    except RuntimeError:
        pass
    # Rollback released the lock; B should now get it.
    with session_b.begin():
        with advisory_lock(session_b, key) as acquired_b:
            assert acquired_b is True


def test_advisory_lock_distinct_keys_do_not_collide(
    session_a: Session, session_b: Session
) -> None:
    key_a = "test:phase-14-10:keyA"
    key_b = "test:phase-14-10:keyB"
    with session_a.begin():
        with advisory_lock(session_a, key_a) as acquired_a:
            assert acquired_a is True
            with session_b.begin():
                with advisory_lock(session_b, key_b) as acquired_b:
                    # Different keys -> no contention.
                    assert acquired_b is True
