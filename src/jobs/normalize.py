"""Phase 13.2: normalization + content hashing for the Job Index.

Two responsibilities live here, both pure functions so they can be reused
by the search flow, the enrichment pipeline, and the legacy-cache migration:

1. ``normalize_search_key`` -- strip tracking / session params from a search
   condition and return a dict whose JSON form is stable across browsers,
   query orderings, and LinkedIn's session-scoped junk. Wrapped by
   ``search_query_fingerprint`` for a SHA256 fingerprint suitable for the
   ``search_queries.normalized_key`` column.

2. ``normalize_job_content`` + ``content_hash`` -- collapse a scraped JD
   into the stable subset of fields we actually care about for "did this
   posting change?", then hash it. Volatile fields (applicant count,
   promoted flag, scrape timestamps, the LinkedIn ``currentJobId``
   redirect) are excluded so identical content never produces a new
   snapshot row just because LinkedIn rotated a counter.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

# LinkedIn / generic tracking params that must NOT participate in the
# normalized key. These come from clicks, share links, A/B test cohorts,
# and the LinkedIn "currentJobId" redirect that changes per-tab.
_SEARCH_TRACKING_PARAMS = frozenset(
    {
        "currentJobId",
        "origin",
        "refId",
        "trackingId",
        "trk",
        "trkInfo",
        "originalSubdomain",
        "lipi",
        "lici",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
    }
)

# Fields the search-key normalizer keeps verbatim (after stable ordering).
# Anything not listed and not in the tracking blacklist is *also* kept so
# new ATS-specific filters work without code changes -- the blacklist is
# the authoritative deny list.
_KNOWN_SEARCH_PARAMS = frozenset(
    {
        "keywords",
        "location",
        "geoId",
        "distance",
        "sortBy",
        "f_TPR",
        "f_E",
        "f_JT",
        "f_WT",
        "f_C",
        "f_I",
        "f_F",
        "time_filter",
        "experience_levels",
        "employment_types",
        "job_types",
        "location_types",
        "max_pages",
        "enrich_details",
        "max_detail_fetches",
        "allow_public_fallback",
    }
)

# Fields excluded from the content hash. These are real fields on the
# JD but their values flap independently of the posting content (LinkedIn
# applicant counters, promoted badges, the scrape timestamp itself).
UNSTABLE_CONTENT_FIELDS: frozenset[str] = frozenset(
    {
        "applicant_count",
        "applicants",
        "promoted",
        "is_promoted",
        "easy_apply",
        "easy_apply_url",
        "discovered_at",
        "scraped_at",
        "expires_at",
        "last_seen_at",
        "current_job_id",
        "view_count",
        "viewer_count",
        "posted_time_ago",
    }
)

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_search_key(
    params: dict[str, Any],
    *,
    source: str | None = None,
) -> dict[str, Any]:
    """Return a stable representation of a search condition.

    - Tracking / session params (``currentJobId``, ``origin``, ``utm_*`` ...)
      are dropped.
    - Strings are stripped of leading/trailing whitespace and collapsed
      to single internal spaces; comparisons are case-insensitive for
      typical "United States" vs "united states" drift on LinkedIn.
    - List values are sorted and de-duplicated so ``["python", "go"]``
      and ``["go", "python"]`` collapse to the same key.
    - ``None``, empty strings, and empty lists are dropped so they
      don't perturb the hash when a caller passes an unset filter.
    - The optional ``source`` argument is recorded under ``__source__``
      so the same filter set against LinkedIn vs Greenhouse stays
      distinct in the index.
    """
    cleaned: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if key in _SEARCH_TRACKING_PARAMS:
            continue
        normalized = _normalize_value(value)
        if normalized is None:
            continue
        cleaned[key] = normalized

    out: dict[str, Any] = {}
    if source:
        out["__source__"] = source.strip().lower()
    for key in sorted(cleaned):
        out[key] = cleaned[key]
    return out


def search_query_fingerprint(
    params: dict[str, Any],
    *,
    source: str | None = None,
) -> str:
    """SHA256 fingerprint of the normalized search key.

    The fingerprint fits ``search_queries.normalized_key`` (VARCHAR(64))
    and is what callers should store; the raw normalized dict is what
    they should persist alongside it in ``raw_params`` for debugging.
    """
    key = normalize_search_key(params, source=source)
    blob = json.dumps(key, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def normalize_job_content(content: dict[str, Any]) -> dict[str, Any]:
    """Project a scraped JD onto the stable subset used for the content hash.

    Drops the fields in :data:`UNSTABLE_CONTENT_FIELDS` and normalizes
    strings the same way the search-key normalizer does. The result
    is what ``content_hash`` digests; storing the *full* raw payload
    remains the caller's responsibility (``job_snapshots.raw_data``).
    """
    cleaned: dict[str, Any] = {}
    for key, value in (content or {}).items():
        if key in UNSTABLE_CONTENT_FIELDS:
            continue
        normalized = _normalize_value(value)
        if normalized is None:
            continue
        cleaned[key] = normalized
    return {k: cleaned[k] for k in sorted(cleaned)}


def content_hash(content: dict[str, Any]) -> str:
    """SHA256 over the normalized JD. Identical content -> identical hash."""
    normalized = normalize_job_content(content)
    blob = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        s = _WHITESPACE_RE.sub(" ", value).strip().lower()
        return s or None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (list, tuple, set)):
        items = []
        seen: set[Any] = set()
        for item in value:
            norm = _normalize_value(item)
            if norm is None:
                continue
            try:
                if norm in seen:
                    continue
                seen.add(norm)
            except TypeError:
                # unhashable (dict) -- de-dup by JSON form
                marker = json.dumps(norm, sort_keys=True, ensure_ascii=False)
                if marker in seen:
                    continue
                seen.add(marker)
            items.append(norm)
        if not items:
            return None
        try:
            return sorted(items)
        except TypeError:
            return sorted(items, key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))
    if isinstance(value, dict):
        nested = {}
        for k, v in value.items():
            norm = _normalize_value(v)
            if norm is None:
                continue
            nested[str(k)] = norm
        if not nested:
            return None
        return {k: nested[k] for k in sorted(nested)}
    return value
