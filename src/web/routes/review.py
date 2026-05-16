"""Phase 17.3 ``/api/review`` routes.

Thin wrappers over :mod:`src.application.review`. The frontend
``/review`` kanban (Phase 17.3 + 17.4) consumes:

* ``GET /api/review`` -- list entries; optional ``?status=`` filter.
* ``GET /api/review/{entry_id}`` -- single entry detail (popover).
* ``POST /api/review/{entry_id}/approve`` -- ``pending → approved``.
* ``POST /api/review/{entry_id}/reject`` -- ``pending|approved → rejected``.
* ``POST /api/review/{entry_id}/refresh`` -- ``stale → pending`` (Phase
  17.5 staleness recovery; the UI button is "Refresh materials").
* ``POST /api/review/bulk/approve`` (Phase 17.4) -- multi-id approve.
* ``POST /api/review/bulk/reject`` (Phase 17.4) -- multi-id or
  by-filter reject.

Submission (``approved → submitted``) is NOT exposed here; the
Phase 17.5 pre-submit gate owns that transition and the gate route
ships in a later sub-phase. Trying to PATCH straight to ``submitted``
returns a 409 with the gate-required reason.

Auth: routes resolve ``tenant_id`` from the request (Phase 18 wires
this to the session; today the helper falls back to ``"default"``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from src.application.review import (
    approve as approve_entry,
)
from src.application.review import (
    bulk_approve,
    bulk_reject,
    bulk_reject_by_filter,
    list_entries,
    refresh_stale,
    serialize_entry,
)
from src.application.review import (
    get_entry as get_entry_db,
)
from src.application.review import (
    reject as reject_entry,
)
from src.core.database import get_session_factory
from src.review.state_machine import InvalidTransitionError

router = APIRouter(prefix="/api/review", tags=["review"])


def _tenant() -> str:
    """Resolve the active tenant id.

    Phase 14 set up a ContextVar; Phase 18 will wire it to the session.
    Today this falls back to ``"default"`` so single-tenant deployments
    keep working without auth.
    """
    try:
        from src.tasks.context import current_tenant_id  # noqa: PLC0415

        tid = current_tenant_id()
    except Exception:  # noqa: BLE001
        tid = None
    return tid or "default"


# --------------------------------------------------------------------------- #
# Payload models                                                              #
# --------------------------------------------------------------------------- #


class ReviewActionPayload(BaseModel):
    """Body for single-item approve/reject/refresh routes."""

    reason: str | None = None
    reviewer: str | None = None


class BulkActionPayload(BaseModel):
    """Body for ``POST /api/review/bulk/approve|reject`` with explicit ids."""

    entry_ids: list[str] = Field(default_factory=list)
    reason: str | None = None
    reviewer: str | None = None


class BulkRejectByFilterPayload(BaseModel):
    """Body for ``POST /api/review/bulk/reject-by-filter``.

    Either ``company`` or ``keyword_in_title`` must be set (the route
    returns 400 if neither is). Both can be combined; matches are
    ``AND``-ed.
    """

    company: str | None = None
    keyword_in_title: str | None = None
    reason: str | None = None
    reviewer: str | None = None


# --------------------------------------------------------------------------- #
# Read routes                                                                 #
# --------------------------------------------------------------------------- #


@router.get("")
async def list_review_entries(
    status: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    """Read path for the kanban board.

    ``status=None`` returns every status for the current tenant; the
    UI groups them client-side. The implicit ordering is ``created_at
    DESC`` so the most recent nightly run is on top.
    """
    factory = get_session_factory()
    with factory() as session:
        entries = list_entries(
            session, tenant_id=_tenant(), status=status, limit=limit  # type: ignore[arg-type]
        )
        return {
            "ok": True,
            "entries": [serialize_entry(e) for e in entries],
        }


@router.get("/{entry_id}")
async def get_review_entry(entry_id: str) -> dict[str, Any]:
    factory = get_session_factory()
    with factory() as session:
        entry = get_entry_db(session, entry_id)
        if entry is None or entry.tenant_id != _tenant():
            # Treat cross-tenant access as not-found so we don't leak
            # whether an id exists in another tenant's scope.
            raise HTTPException(404, "review entry not found")
        return {"ok": True, "entry": serialize_entry(entry)}


# --------------------------------------------------------------------------- #
# Single-item write routes                                                    #
# --------------------------------------------------------------------------- #


def _wrap_transition(callable_, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Common write-path error handling.

    Maps:
      * InvalidTransitionError -> 409
      * LookupError -> 404
      * SQLAlchemyError -> 500 with a non-leaky message

    A successful call returns ``{ok: True, entry: serialize_entry(...)}``.
    """
    try:
        entry = callable_(*args, **kwargs)
    except InvalidTransitionError as exc:
        raise HTTPException(409, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(500, "database error") from exc
    return {"ok": True, "entry": serialize_entry(entry)}


# --------------------------------------------------------------------------- #
# Bulk routes (Phase 17.4)                                                    #
# --------------------------------------------------------------------------- #
#
# Declared BEFORE the single-item /{entry_id}/* routes so FastAPI's
# path matcher doesn't fall through ``/bulk/approve`` -> ``entry_id="bulk"``.


@router.post("/bulk/approve")
async def bulk_approve_route(payload: BulkActionPayload) -> dict[str, Any]:
    """Phase 17.4 -- multi-id approve.

    Returns aggregate ``{succeeded: [...], failed: [{id, error}]}`` so
    the UI can render ``"8 of 12 approved -- 4 failed: ..."`` in one
    pass. The route does NOT short-circuit on first failure -- this is
    a deliberate kanban affordance.
    """
    if not payload.entry_ids:
        raise HTTPException(400, "entry_ids is required")
    tenant = _tenant()
    factory = get_session_factory()
    with factory() as session, session.begin():
        # Tenant guard: filter to ids that belong to this tenant.
        owned = []
        for eid in payload.entry_ids:
            entry = get_entry_db(session, eid)
            if entry is not None and entry.tenant_id == tenant:
                owned.append(eid)
        result = bulk_approve(
            session,
            owned,
            reviewer=payload.reviewer,
            reason=payload.reason,
        )
    return {"ok": True, **result.to_dict()}


@router.post("/bulk/reject")
async def bulk_reject_route(payload: BulkActionPayload) -> dict[str, Any]:
    if not payload.entry_ids:
        raise HTTPException(400, "entry_ids is required")
    tenant = _tenant()
    factory = get_session_factory()
    with factory() as session, session.begin():
        owned = []
        for eid in payload.entry_ids:
            entry = get_entry_db(session, eid)
            if entry is not None and entry.tenant_id == tenant:
                owned.append(eid)
        result = bulk_reject(
            session,
            owned,
            reviewer=payload.reviewer,
            reason=payload.reason,
        )
    return {"ok": True, **result.to_dict()}


@router.post("/bulk/reject-by-filter")
async def bulk_reject_by_filter_route(
    payload: BulkRejectByFilterPayload,
) -> dict[str, Any]:
    if not payload.company and not payload.keyword_in_title:
        raise HTTPException(
            400, "either company or keyword_in_title is required"
        )
    factory = get_session_factory()
    with factory() as session, session.begin():
        result = bulk_reject_by_filter(
            session,
            tenant_id=_tenant(),
            company=payload.company,
            keyword_in_title=payload.keyword_in_title,
            reviewer=payload.reviewer,
            reason=payload.reason,
        )
    return {"ok": True, **result.to_dict()}


# --------------------------------------------------------------------------- #
# Single-item write routes (declared after /bulk/* so path matcher resolves   #
# /bulk/approve to the bulk route, not entry_id="bulk").                      #
# --------------------------------------------------------------------------- #


@router.post("/{entry_id}/approve")
async def approve_route(
    entry_id: str, payload: ReviewActionPayload
) -> dict[str, Any]:
    factory = get_session_factory()
    with factory() as session, session.begin():
        # Tenant isolation: load + check before transitioning.
        entry = get_entry_db(session, entry_id)
        if entry is None or entry.tenant_id != _tenant():
            raise HTTPException(404, "review entry not found")
        return _wrap_transition(
            approve_entry,
            session,
            entry_id,
            reviewer=payload.reviewer,
            reason=payload.reason,
        )


@router.post("/{entry_id}/reject")
async def reject_route(
    entry_id: str, payload: ReviewActionPayload
) -> dict[str, Any]:
    factory = get_session_factory()
    with factory() as session, session.begin():
        entry = get_entry_db(session, entry_id)
        if entry is None or entry.tenant_id != _tenant():
            raise HTTPException(404, "review entry not found")
        return _wrap_transition(
            reject_entry,
            session,
            entry_id,
            reviewer=payload.reviewer,
            reason=payload.reason,
        )


@router.post("/{entry_id}/refresh")
async def refresh_route(
    entry_id: str, payload: ReviewActionPayload
) -> dict[str, Any]:
    """``stale → pending``. The UI surfaces this as 'Refresh materials'
    so the operator can re-run materials generation after the Phase
    17.5 pre-submit gate flagged staleness."""
    factory = get_session_factory()
    with factory() as session, session.begin():
        entry = get_entry_db(session, entry_id)
        if entry is None or entry.tenant_id != _tenant():
            raise HTTPException(404, "review entry not found")
        return _wrap_transition(
            refresh_stale,
            session,
            entry_id,
            reviewer=payload.reviewer,
        )
