"""File-backed approval queue for irreversible agent actions.

The orchestrator calls ``gate.propose(kind, summary, payload, ttl)`` to
park an action that needs human review. The web GUI surfaces pending
requests; the user approves or rejects. The orchestrator polls
``gate.get(request_id)`` to see the decision and only then performs the
real side effect.

Storage is JSON-on-disk, mirroring the trace store -- inspectable with
``cat`` and trivial to back up. A SQL table is overkill for the volumes
we expect.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from src.core.config import PROJECT_ROOT

_DEFAULT_DIR = PROJECT_ROOT / "data" / "agent_gate"


class GateError(Exception):
    """Raised on invalid gate operations (bad ids, illegal transitions)."""


class ApprovalStatus(str, Enum):  # noqa: UP042 -- StrEnum behavior differs in JSON dumps
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


_TERMINAL = {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED}


@dataclass
class ApprovalRequest:
    id: str
    kind: str
    summary: str
    payload: dict[str, Any]
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: str = ""
    decided_at: str | None = None
    decided_by: str | None = None
    reason: str | None = None
    ttl_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    def is_expired(self, now: datetime) -> bool:
        if self.status != ApprovalStatus.PENDING or self.ttl_seconds is None:
            return False
        created = _parse_iso(self.created_at)
        if created is None:
            return False
        return (now - created).total_seconds() > self.ttl_seconds


@dataclass
class _GateState:
    requests: dict[str, ApprovalRequest] = field(default_factory=dict)


class ApprovalGate:
    """Persistent queue. Safe to instantiate per-request; all state lives on disk."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = (base_dir or _DEFAULT_DIR).resolve()

    # ----- public API -----

    def propose(
        self,
        *,
        kind: str,
        summary: str,
        payload: dict[str, Any] | None = None,
        ttl_seconds: int | None = None,
    ) -> ApprovalRequest:
        if not kind or not isinstance(kind, str):
            raise GateError("'kind' is required.")
        if not summary or not isinstance(summary, str):
            raise GateError("'summary' is required.")
        if ttl_seconds is not None and ttl_seconds <= 0:
            raise GateError("'ttl_seconds' must be positive when provided.")
        request = ApprovalRequest(
            id=_make_request_id(),
            kind=kind,
            summary=summary,
            payload=dict(payload or {}),
            status=ApprovalStatus.PENDING,
            created_at=_now_iso(),
            ttl_seconds=ttl_seconds,
        )
        self._save(request)
        return request

    def get(self, request_id: str) -> ApprovalRequest:
        request = self._load(request_id)
        # Lazy expiry: evaluate on read so callers don't need a sweeper.
        if request.is_expired(datetime.now(UTC)):
            request.status = ApprovalStatus.EXPIRED
            request.decided_at = _now_iso()
            request.decided_by = "system:expired"
            self._save(request)
        return request

    def list(
        self,
        *,
        status: ApprovalStatus | None = None,
        limit: int = 100,
    ) -> list[ApprovalRequest]:
        if not self.base_dir.exists():
            return []
        out: list[ApprovalRequest] = []
        files = sorted(
            (p for p in self.base_dir.iterdir() if p.is_file() and p.suffix == ".json"),
            reverse=True,
        )
        now = datetime.now(UTC)
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            req = _request_from_dict(data)
            if req.is_expired(now):
                req.status = ApprovalStatus.EXPIRED
                req.decided_at = _now_iso()
                req.decided_by = "system:expired"
                self._save(req)
            if status is not None and req.status != status:
                continue
            out.append(req)
            if len(out) >= limit:
                break
        return out

    def approve(
        self, request_id: str, *, decided_by: str = "user", reason: str | None = None
    ) -> ApprovalRequest:
        return self._decide(request_id, ApprovalStatus.APPROVED, decided_by, reason)

    def reject(
        self, request_id: str, *, decided_by: str = "user", reason: str | None = None
    ) -> ApprovalRequest:
        return self._decide(request_id, ApprovalStatus.REJECTED, decided_by, reason)

    # ----- internal helpers -----

    def _decide(
        self,
        request_id: str,
        status: ApprovalStatus,
        decided_by: str,
        reason: str | None,
    ) -> ApprovalRequest:
        request = self.get(request_id)
        if request.status in _TERMINAL:
            raise GateError(
                f"Request '{request_id}' is already {request.status.value}; "
                "decisions are immutable."
            )
        request.status = status
        request.decided_at = _now_iso()
        request.decided_by = decided_by
        request.reason = reason
        self._save(request)
        return request

    def _save(self, request: ApprovalRequest) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        path = self._safe_path(request.id)
        path.write_text(
            json.dumps(request.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load(self, request_id: str) -> ApprovalRequest:
        path = self._safe_path(request_id)
        if not path.exists():
            raise GateError(f"Request '{request_id}' not found.")
        return _request_from_dict(json.loads(path.read_text(encoding="utf-8")))

    def _safe_path(self, request_id: str) -> Path:
        if "/" in request_id or "\\" in request_id or ".." in request_id:
            raise GateError(f"Invalid request id: {request_id!r}")
        return self.base_dir / f"{request_id}.json"


def _make_request_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(4)}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _request_from_dict(data: dict[str, Any]) -> ApprovalRequest:
    raw_status = data.get("status", ApprovalStatus.PENDING.value)
    try:
        status = ApprovalStatus(raw_status)
    except ValueError:
        status = ApprovalStatus.PENDING
    return ApprovalRequest(
        id=str(data["id"]),
        kind=str(data.get("kind", "")),
        summary=str(data.get("summary", "")),
        payload=dict(data.get("payload", {})),
        status=status,
        created_at=str(data.get("created_at", "")),
        decided_at=data.get("decided_at"),
        decided_by=data.get("decided_by"),
        reason=data.get("reason"),
        ttl_seconds=data.get("ttl_seconds"),
    )
