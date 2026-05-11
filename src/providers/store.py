"""File-backed credential store.

We keep secrets in a single JSON document at
``data/providers/credentials.json``. The path is created with mode
0700 on the directory and 0600 on the file (best-effort -- Windows
ignores POSIX bits but the path is still gitignored from day one).

Concurrent access is naive (full read-modify-write) because credential
edits happen at human cadence; we aren't worried about lost-update
races between the Web UI and the CLI.

The store NEVER logs secret values. Internal exceptions reference
provider ids only.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from src.core.config import PROJECT_ROOT
from src.providers.base import ProviderCredentials, ProviderError

logger = logging.getLogger("autoapply.providers.store")

_DEFAULT_PATH = PROJECT_ROOT / "data" / "providers" / "credentials.json"


class CredentialStore:
    """JSON-on-disk dict of ``provider_id -> ProviderCredentials``."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = (path or _DEFAULT_PATH).resolve()

    # ----- public API -----

    def get(self, provider_id: str) -> ProviderCredentials | None:
        data = self._read()
        raw = data.get(provider_id)
        if raw is None:
            return None
        try:
            return ProviderCredentials.from_dict(raw)
        except (KeyError, TypeError, ValueError) as exc:
            # Corrupt rows are surfaced as missing rather than crashing
            # other providers. The CLI surfaces this on `provider list`.
            logger.warning(
                "Discarding corrupt credential row for %s: %s",
                provider_id,
                exc,
            )
            return None

    def set(self, credentials: ProviderCredentials) -> None:
        if not credentials.provider_id:
            raise ProviderError("Cannot save credentials without a provider_id.")
        data = self._read()
        data[credentials.provider_id] = credentials.to_dict()
        self._write(data)

    def delete(self, provider_id: str) -> bool:
        data = self._read()
        if provider_id not in data:
            return False
        data.pop(provider_id, None)
        self._write(data)
        return True

    def list_ids(self) -> list[str]:
        return sorted(self._read().keys())

    def list_all(self) -> list[ProviderCredentials]:
        data = self._read()
        out: list[ProviderCredentials] = []
        for pid in sorted(data):
            row = data[pid]
            try:
                out.append(ProviderCredentials.from_dict(row))
            except Exception:  # noqa: BLE001 -- defensive; corrupt rows skipped
                logger.warning("Skipping corrupt credential row %r.", pid)
        return out

    def clear(self) -> None:
        """Drop every credential. Useful in tests."""
        if self.path.exists():
            self.path.unlink()

    # ----- internals -----

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            # We do NOT silently overwrite the file -- a corrupt file
            # might be evidence of disk damage or a partially-written
            # update. Surface to the caller; they can decide.
            raise ProviderError(
                f"Credentials file at {self.path} is not valid JSON: {exc}"
            ) from exc

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Best-effort restrictive directory mode. Ignored on Windows.
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        # Atomic-ish write: tmp + rename so a partial write doesn't
        # corrupt the existing file.
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)
