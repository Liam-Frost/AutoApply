"""Phase 13.8: import legacy ``data/cache/linkedin_search/*.json`` into the
Job Index and tear down the file-backed cache.

The legacy ``src.intake.search_cache`` module stored each LinkedIn
search result set as a JSON blob keyed by a SHA-1 of the request
parameters. We import those files into ``search_queries`` +
``search_results`` so the historical cache isn't lost, then delete the
files (caller-controlled via ``delete_after_import``).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from src.core.config import PROJECT_ROOT
from src.jobs.store import JobIndexStore

logger = logging.getLogger("autoapply.jobs.legacy")

DEFAULT_LEGACY_DIR = PROJECT_ROOT / "data" / "cache" / "linkedin_search"


@dataclass
class ImportReport:
    files_seen: int
    files_imported: int
    files_skipped: int
    queries_inserted: int
    results_linked: int
    errors: list[str]


def import_legacy_file_cache(
    *,
    store: JobIndexStore,
    legacy_dir: Path | None = None,
    delete_after_import: bool = False,
) -> ImportReport:
    """Walk the legacy cache dir and replay each file into the Job Index.

    Each legacy file has the shape
        {"created_at": str, "max_pages": int, "jobs": [<RawJob dict>...]}
    so we mint a SearchQuery row keyed by the file's parameters
    (recovered from the embedded payload where possible -- the legacy
    cache didn't persist the original request body) and link every
    contained job as a SearchResult row pointing at a fresh JobPosting.

    Caller controls the session boundary; this function only flushes.
    """
    legacy_dir = legacy_dir or DEFAULT_LEGACY_DIR
    report = ImportReport(
        files_seen=0,
        files_imported=0,
        files_skipped=0,
        queries_inserted=0,
        results_linked=0,
        errors=[],
    )

    if not legacy_dir.exists():
        return report

    for path in sorted(legacy_dir.glob("*.json")):
        report.files_seen += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"{path.name}: parse failed ({exc})")
            report.files_skipped += 1
            continue

        jobs = payload.get("jobs") or []
        if not jobs:
            report.files_skipped += 1
            continue

        # Reconstruct a synthetic raw_params from the embedded jobs --
        # the legacy file didn't store the original request, so the
        # best we can do is hash the (file digest, max_pages) tuple.
        # Crucially, the imported query's ``status`` is 'stale' so the
        # next real search forces a re-scrape rather than trusting the
        # historical cache.
        synthetic_key = path.stem  # sha1 digest from the legacy module
        raw_params = {
            "_legacy_import": True,
            "_legacy_filename": path.name,
            "max_pages": payload.get("max_pages"),
        }
        query = store.upsert_query(
            source="linkedin",
            fingerprint=synthetic_key[:64],
            raw_params=raw_params,
            max_pages=payload.get("max_pages"),
        )
        if query.last_run_at is None:
            report.queries_inserted += 1
        # Mark stale so the next read triggers a fresh scrape.
        store.mark_query_run(
            query, status="stale", error="imported from legacy file cache",
            result_count=len(jobs),
        )

        for rank, job in enumerate(jobs):
            source_id = job.get("source_id") or job.get("id") or f"legacy-{rank}"
            company = job.get("company") or "Unknown"
            posting = store.upsert_posting(
                source="linkedin",
                source_id=str(source_id),
                company=company,
                canonical_url=job.get("application_url"),
            )
            store.link_result(query_id=query.id, posting_id=posting.id, rank=rank)
            report.results_linked += 1

        report.files_imported += 1
        if delete_after_import:
            try:
                path.unlink()
            except OSError as exc:
                report.errors.append(f"{path.name}: delete failed ({exc})")

    return report


def clear_indexed_searches(*, store: JobIndexStore, source: str = "linkedin") -> int:
    """Replace the legacy ``clear_linkedin_search_cache()`` behaviour for
    the Job Index. Deletes every ``search_queries`` row for ``source``
    (cascades to ``search_results`` via the FK). Returns the number of
    queries removed."""
    from sqlalchemy import delete  # noqa: PLC0415

    from src.core.models import SearchQuery  # noqa: PLC0415

    stmt = delete(SearchQuery).where(
        SearchQuery.tenant_id == store.tenant_id,
        SearchQuery.source == source,
    )
    result = store.session.execute(stmt)
    return result.rowcount or 0


def discover_legacy_files(legacy_dir: Path | None = None) -> Iterable[Path]:
    legacy_dir = legacy_dir or DEFAULT_LEGACY_DIR
    if not legacy_dir.exists():
        return ()
    return sorted(legacy_dir.glob("*.json"))
