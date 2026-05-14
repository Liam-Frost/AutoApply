"""Phase 13: Job Index & Freshness Engine.

Submodules:
  normalize -- search key normalization + content hashing
  state     -- freshness state machine (Phase 13.3)
  search    -- cache-first search flow (Phase 13.4)
  enrich    -- snapshot-versioned detail enrichment (Phase 13.5)
  freshness -- context-aware should_refresh (Phase 13.6)
  migration -- legacy file-cache import (Phase 13.8)
"""

from src.jobs.normalize import (
    UNSTABLE_CONTENT_FIELDS,
    content_hash,
    normalize_job_content,
    normalize_search_key,
    search_query_fingerprint,
)

__all__ = [
    "UNSTABLE_CONTENT_FIELDS",
    "content_hash",
    "normalize_job_content",
    "normalize_search_key",
    "search_query_fingerprint",
]
