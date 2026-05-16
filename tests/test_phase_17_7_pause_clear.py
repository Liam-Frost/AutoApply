"""Phase 17.7 -- pause-nightly --clear-pending behaviour.

The pause sentinel + resume CLI round-trip is already covered in
``tests/test_phase_17_1_nightly_run.py::TestCliCommands``; this file
adds the 'clear pending queue (for vacation)' affordance the plan
calls for.

The DB round-trip uses the dev Postgres, same pattern as 17.2.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session, sessionmaker

from src.application.review import CreateEntryArgs, approve, create_entry
from src.core.config import get_db_url, load_config
from src.core.models import ReviewQueueEntry


@pytest.fixture(scope="module")
def engine():
    return create_engine(get_db_url(load_config()))


@pytest.fixture
def db_session(engine) -> Session:
    s = sessionmaker(bind=engine)()
    yield s
    s.execute(
        sa_delete(ReviewQueueEntry).where(
            ReviewQueueEntry.tenant_id.like("test-pn-%")
        )
    )
    s.commit()
    s.close()


def _seed(session: Session, tenant: str) -> ReviewQueueEntry:
    args = CreateEntryArgs(
        tenant_id=tenant,
        job_id=uuid.uuid4(),
        job_snapshot_id=uuid.uuid4(),
        materials_path=None,
        score_breakdown=None,
        company="X",
        title="Y",
    )
    entry = create_entry(session, args)
    session.commit()
    return entry


class TestPauseClearPending:
    def test_clear_pending_rejects_pending_rows_only(
        self,
        db_session: Session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        tenant = f"test-pn-{uuid.uuid4().hex[:6]}"
        pending = _seed(db_session, tenant=tenant)
        approved_entry = _seed(db_session, tenant=tenant)
        approve(db_session, approved_entry.id)
        db_session.commit()

        # Route the sentinel under tmp_path so we don't touch real
        # data/ between test runs.
        import src.cli.cmd_nightly as cli_mod

        monkeypatch.setattr(
            cli_mod,
            "nightly_pause_sentinel_path",
            lambda: tmp_path / "data" / "nightly_paused",
        )

        runner = CliRunner()
        result = runner.invoke(
            cli_mod.pause_nightly_cmd,
            ["--clear-pending", "--tenant", tenant],
        )
        assert result.exit_code == 0
        body = json.loads(result.output)
        assert body["paused"] is True
        assert body["cleared_pending"] == 1

        # Re-read the rows to confirm:
        db_session.expire_all()
        rejected = db_session.get(ReviewQueueEntry, pending.id)
        survivor = db_session.get(ReviewQueueEntry, approved_entry.id)
        assert rejected.status == "rejected"
        assert rejected.reason == "paused for vacation"
        # Already-approved row stays approved.
        assert survivor.status == "approved"

    def test_default_pause_does_not_clear(
        self,
        db_session: Session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Without ``--clear-pending``, the kill switch is purely the
        sentinel touch -- pending rows survive."""
        tenant = f"test-pn-{uuid.uuid4().hex[:6]}"
        pending = _seed(db_session, tenant=tenant)

        import src.cli.cmd_nightly as cli_mod

        monkeypatch.setattr(
            cli_mod,
            "nightly_pause_sentinel_path",
            lambda: tmp_path / "data" / "nightly_paused",
        )

        runner = CliRunner()
        result = runner.invoke(cli_mod.pause_nightly_cmd, [])
        assert result.exit_code == 0
        body = json.loads(result.output)
        assert body["paused"] is True
        assert body["cleared_pending"] == 0

        db_session.expire_all()
        survivor = db_session.get(ReviewQueueEntry, pending.id)
        assert survivor.status == "pending"
