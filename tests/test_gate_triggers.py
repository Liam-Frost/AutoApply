"""Phase 15.10: tests for the materials gate-trigger policy + helpers.

Round-trip the gate flow against the real dev Postgres so we catch
schema regressions in :class:`GateRequest`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import get_db_url, load_config
from src.core.models import GateRequest
from src.generation import gate_triggers


@pytest.fixture(scope="module")
def engine():
    return create_engine(get_db_url(load_config()))


@pytest.fixture
def db_session(engine) -> Session:
    s = sessionmaker(bind=engine)()
    yield s
    s.execute(
        sa_delete(GateRequest).where(GateRequest.tenant_id.like("test-gt-%"))
    )
    s.commit()
    s.close()


# ---- Policy ----------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "materials.bullet_pool_mutation",
        "materials.story_bank_mutation",
        "materials.template_manifest_persist",
    ],
)
def test_is_gateworthy_true_for_persistent_mutations(kind: str) -> None:
    assert gate_triggers.is_gateworthy(kind) is True


@pytest.mark.parametrize(
    "kind",
    [
        "materials.docx_patch_one_shot",
        "materials.cover_letter_one_shot",
        "materials.latex_render_one_shot",
        "",
        "unknown",
    ],
)
def test_is_gateworthy_false_for_one_shot_generation(kind: str) -> None:
    assert gate_triggers.is_gateworthy(kind) is False


# ---- propose_bullet_pool_mutation -----------------------------------


def test_propose_bullet_pool_creates_gate(db_session: Session) -> None:
    proposal = gate_triggers.propose_bullet_pool_mutation(
        db_session,
        bullets=[
            {"action": "add", "text": "Built a thing", "tags": ["python"]},
            {"action": "edit", "bullet_id": "b1", "text": "Edited"},
        ],
        rationale="agent learned new evidence from latest application",
        tenant_id="test-gt-bullets",
    )
    db_session.commit()

    row = db_session.get(GateRequest, proposal.gate_id)
    assert row is not None
    assert row.kind == "materials.bullet_pool_mutation"
    assert row.status == "pending"
    assert row.tenant_id == "test-gt-bullets"
    assert "1 add" in row.summary
    assert "1 edit" in row.summary
    assert row.payload["rationale"].startswith("agent learned")


def test_propose_bullet_pool_no_actions_summarized_as_noop(
    db_session: Session,
) -> None:
    proposal = gate_triggers.propose_bullet_pool_mutation(
        db_session,
        bullets=[],
        rationale="empty payload check",
        tenant_id="test-gt-noop",
    )
    db_session.commit()

    row = db_session.get(GateRequest, proposal.gate_id)
    assert row is not None
    assert "no-op" in row.summary


# ---- propose_story_bank_mutation ------------------------------------


def test_propose_story_bank_creates_gate(db_session: Session) -> None:
    proposal = gate_triggers.propose_story_bank_mutation(
        db_session,
        stories=[
            {"action": "add", "title": "Leadership", "body": "...", "themes": ["lead"]},
        ],
        rationale="adding STAR story for behavioral interviews",
        tenant_id="test-gt-stories",
    )
    db_session.commit()

    row = db_session.get(GateRequest, proposal.gate_id)
    assert row is not None
    assert row.kind == "materials.story_bank_mutation"
    assert "1 add" in row.summary


# ---- propose_template_manifest_persist ------------------------------


def test_propose_template_manifest_persist_flags_unvalidated(
    db_session: Session,
) -> None:
    proposal = gate_triggers.propose_template_manifest_persist(
        db_session,
        template_id="user-latex-v1",
        package_dir="data/templates/resume/user-latex-v1",
        sample_render_ok=False,
        notes=["sample render failed: missing placeholder"],
        tenant_id="test-gt-manifest-bad",
    )
    db_session.commit()
    row = db_session.get(GateRequest, proposal.gate_id)
    assert row is not None
    assert "WARNING" in row.summary
    assert row.payload["sample_render_ok"] is False


def test_propose_template_manifest_persist_ok(db_session: Session) -> None:
    proposal = gate_triggers.propose_template_manifest_persist(
        db_session,
        template_id="user-latex-v2",
        package_dir="data/templates/resume/user-latex-v2",
        sample_render_ok=True,
        notes=[],
        tenant_id="test-gt-manifest-ok",
    )
    db_session.commit()
    row = db_session.get(GateRequest, proposal.gate_id)
    assert row is not None
    assert "WARNING" not in row.summary
    assert "sample render OK" in row.summary


# ---- find_pending_for_task ------------------------------------------


def test_find_pending_for_task_filters_by_task_and_status(
    db_session: Session,
) -> None:

    from src.core.models import TaskRecord

    task = TaskRecord(
        tenant_id="test-gt-find",
        kind="materials.generate",
        queue="materials",
        status="running",
    )
    db_session.add(task)
    db_session.flush()

    a = gate_triggers.propose_bullet_pool_mutation(
        db_session,
        bullets=[{"action": "add", "text": "x"}],
        rationale="r",
        task_id=task.id,
        tenant_id="test-gt-find",
    )
    b = gate_triggers.propose_story_bank_mutation(
        db_session,
        stories=[{"action": "add", "title": "x"}],
        rationale="r",
        task_id=task.id,
        tenant_id="test-gt-find",
    )
    # Different task -- must NOT come back from find_pending_for_task.
    other_task = TaskRecord(
        tenant_id="test-gt-find",
        kind="materials.generate",
        queue="materials",
        status="running",
    )
    db_session.add(other_task)
    db_session.flush()
    gate_triggers.propose_bullet_pool_mutation(
        db_session,
        bullets=[{"action": "add", "text": "y"}],
        rationale="r",
        task_id=other_task.id,
        tenant_id="test-gt-find",
    )
    # Untracked task_id -- gate with no task_id at all.
    gate_triggers.propose_story_bank_mutation(
        db_session,
        stories=[{"action": "add", "title": "y"}],
        rationale="r",
        task_id=None,
        tenant_id="test-gt-find",
    )
    db_session.commit()

    pending = gate_triggers.find_pending_for_task(db_session, task.id)
    pending_ids = {p.id for p in pending}
    assert pending_ids == {a.gate_id, b.gate_id}

    # Approve one -- find_pending should drop it.
    from src.tasks import gate as gate_module

    gate_module.approve(db_session, a.gate_id, decided_by="op")
    db_session.commit()
    pending_after = gate_triggers.find_pending_for_task(db_session, task.id)
    assert {p.id for p in pending_after} == {b.gate_id}

    # Cleanup the extra TaskRecord rows (gate fixture deletes its own).
    db_session.execute(
        sa_delete(TaskRecord).where(TaskRecord.tenant_id == "test-gt-find")
    )
    db_session.commit()
