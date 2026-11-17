"""SQLite engine, session helper, and key/value settings access."""

from __future__ import annotations

import logging
import json
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from . import config

_engine = None
_Session: sessionmaker[Session] | None = None


def get_engine():
    global _engine, _Session
    if _engine is None:
        _engine = create_engine(
            f"sqlite:///{config.DB_PATH}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )

        @event.listens_for(_engine, "connect")
        def _pragmas(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")  # wait for a short writer instead of failing
            cur.close()

        _Session = sessionmaker(_engine, expire_on_commit=False)

        @event.listens_for(_Session, "before_flush")
        def _status_history(session, _ctx, _instances):  # noqa: ANN001
            """Whoever changes an application's status - the executor, the mail tracker, the user - the change is kept."""
            from sqlalchemy import inspect as sa_inspect

            from .models import Application, ApplicationEvent, SENT

            for obj in list(session.dirty):
                if isinstance(obj, Application) and obj.id is not None:
                    h = sa_inspect(obj).attrs.status.history
                    if h.has_changes() and h.added and (not h.deleted or h.deleted[0] != h.added[0]):
                        session.add(ApplicationEvent(application_id=obj.id, old=str(h.deleted[0]) if h.deleted else "", new=str(h.added[0]),
                                                     source=str(obj.__dict__.pop("_moved_by", "") or "")))
                        if str(h.added[0]) in SENT:      # whichever way it was sent: what waited on it is closed (lifecycle.settle)
                            session.info.setdefault("sent", set()).add(obj.id)

        @event.listens_for(_Session, "after_commit")
        def _settle_sent(session):  # noqa: ANN001
            ids = session.info.pop("sent", None)
            if not ids:
                return
            from . import lifecycle

            for i in ids:
                try:
                    lifecycle.settle(i)
                except Exception:  # noqa: BLE001 - the status change itself is committed; closing the cards must not undo it
                    logging.getLogger("autoapply.db").exception("could not settle application %s", i)

        @event.listens_for(_Session, "after_rollback")
        def _forget_sent(session):  # noqa: ANN001
            session.info.pop("sent", None)
    return _engine


def reset_engine() -> None:
    """Drop the cached engine (tests point config.DB_PATH elsewhere)."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    models.Base.metadata.create_all(get_engine())
    _add_missing_columns()


# Columns added after the first release. SQLite has no "ADD COLUMN IF NOT EXISTS", so check first.
_NEW_COLUMNS = {"jobs": {"brief": "TEXT DEFAULT ''", "duplicate_of": "INTEGER", "posted": "VARCHAR DEFAULT ''", "archived_at": "DATETIME"},
                "mail_events": {"event": "VARCHAR DEFAULT 'new'", "linked_by": "VARCHAR DEFAULT ''"}, "application_events": {"source": "VARCHAR DEFAULT ''"},
                "tasks": {"stages": "JSON", "due_at": "DATETIME"}, "runs": {"spans": "JSON", "site": "VARCHAR", "learned": "JSON"}}


def _add_missing_columns() -> None:
    from sqlalchemy import text

    with get_engine().begin() as c:
        for table, cols in _NEW_COLUMNS.items():
            have = {r[1] for r in c.execute(text(f"PRAGMA table_info({table})"))}
            for name, ddl in cols.items():
                if name not in have:
                    c.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


@contextmanager
def session() -> Iterator[Session]:
    get_engine()
    assert _Session is not None
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_setting(key: str, default: Any = None) -> Any:
    from .models import Setting

    with session() as s:
        row = s.get(Setting, key)
        if row is not None:
            return json.loads(row.value)
    if default is not None:
        return default
    return config.DEFAULT_SETTINGS.get(key)


def set_setting(key: str, value: Any) -> None:
    from .models import Setting

    with session() as s:
        row = s.get(Setting, key)
        if row is None:
            s.add(Setting(key=key, value=json.dumps(value, ensure_ascii=False)))
        else:
            row.value = json.dumps(value, ensure_ascii=False)


def all_settings() -> dict[str, Any]:
    from .models import Setting

    out = dict(config.DEFAULT_SETTINGS)
    with session() as s:
        for row in s.query(Setting).all():
            out[row.key] = json.loads(row.value)
    return out
