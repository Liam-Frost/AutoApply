"""Simple file-backed persistence for generated material versions."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from src.core.config import PROJECT_ROOT

VERSIONS_DIR = PROJECT_ROOT / "data" / "output" / "versions"


def save_generation_version(
    *,
    job: dict,
    material_type: str,
    artifact: dict | None,
    artifacts: dict,
    document: dict | None,
    validation: dict | None,
    requirements: dict | None,
) -> dict:
    """Persist a generated material version and return version metadata."""
    now = datetime.now(UTC)
    version_id = uuid4().hex
    payload = {
        "id": version_id,
        "created_at": now.isoformat(),
        "material_type": material_type,
        "job": job,
        "artifact": artifact,
        "artifacts": artifacts,
        "document": document,
        "validation": validation,
        "requirements": requirements,
    }

    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{now.strftime('%Y%m%d_%H%M%S')}_{_slug(job)}_{material_type}_{version_id}.json"
    path = VERSIONS_DIR / filename
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "id": version_id,
        "path": str(path),
        "created_at": payload["created_at"],
    }


def _slug(job: dict) -> str:
    company = str(job.get("company") or "company")
    title = str(job.get("title") or "role")
    value = f"{company}_{title}".lower()
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value[:60] or "material"
