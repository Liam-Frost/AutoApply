"""Phase 13.2: tests for search key + content hash normalization."""

from __future__ import annotations

from src.jobs.normalize import (
    UNSTABLE_CONTENT_FIELDS,
    content_hash,
    normalize_job_content,
    normalize_search_key,
    search_query_fingerprint,
)


class TestSearchKeyNormalization:
    def test_tracking_params_are_stripped(self) -> None:
        with_tracking = {
            "keywords": "swe intern",
            "currentJobId": "1234567",
            "origin": "JYMBII_IN_APP_NOTIFICATION",
            "trk": "public_jobs_apply-button",
            "utm_source": "linkedin",
        }
        without = {"keywords": "swe intern"}
        assert normalize_search_key(with_tracking) == normalize_search_key(without)

    def test_keywords_order_does_not_matter(self) -> None:
        a = normalize_search_key({"keywords": ["python", "go"]})
        b = normalize_search_key({"keywords": ["go", "python"]})
        assert a == b
        assert search_query_fingerprint(a) == search_query_fingerprint(b)

    def test_whitespace_and_case_are_canonicalized(self) -> None:
        a = normalize_search_key({"location": "  United  States  "})
        b = normalize_search_key({"location": "united states"})
        assert a == b

    def test_empty_values_are_dropped(self) -> None:
        out = normalize_search_key(
            {
                "keywords": "swe",
                "location": "",
                "experience_levels": [],
                "max_pages": None,
            }
        )
        assert out == {"keywords": "swe"}

    def test_source_partitions_the_keyspace(self) -> None:
        linkedin = search_query_fingerprint({"keywords": "swe"}, source="linkedin")
        greenhouse = search_query_fingerprint({"keywords": "swe"}, source="greenhouse")
        assert linkedin != greenhouse

    def test_fingerprint_is_sha256_hex(self) -> None:
        fp = search_query_fingerprint({"keywords": "swe"}, source="linkedin")
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_list_of_dicts_dedupes_by_value(self) -> None:
        a = normalize_search_key({"filters": [{"k": "v"}, {"k": "v"}]})
        b = normalize_search_key({"filters": [{"k": "v"}]})
        assert a == b

    def test_unknown_params_are_kept(self) -> None:
        # The blacklist -- not the whitelist -- is authoritative so new
        # ATS-specific filters work without a code change.
        # Keys are preserved verbatim (LinkedIn's geoId / sortBy are camelCase
        # and shouldn't be folded); only the values are normalized.
        out = normalize_search_key({"f_BRAND_NEW_FILTER": "X"})
        assert out == {"f_BRAND_NEW_FILTER": "x"}


class TestContentHash:
    def _job(self, **overrides: object) -> dict:
        base = {
            "title": "Software Engineer Intern",
            "company": "Acme",
            "location": "Toronto, ON",
            "description": "Build cool stuff.",
            "employment_type": "internship",
        }
        base.update(overrides)
        return base

    def test_identical_content_collapses(self) -> None:
        assert content_hash(self._job()) == content_hash(self._job())

    def test_unstable_fields_do_not_affect_hash(self) -> None:
        h1 = content_hash(self._job())
        h2 = content_hash(
            self._job(
                applicant_count=42,
                promoted=True,
                discovered_at="2026-05-14T00:00:00Z",
                current_job_id="abc",
                view_count=10_000,
            )
        )
        assert h1 == h2

    def test_unstable_field_set_is_documented(self) -> None:
        assert "applicant_count" in UNSTABLE_CONTENT_FIELDS
        assert "current_job_id" in UNSTABLE_CONTENT_FIELDS
        assert "promoted" in UNSTABLE_CONTENT_FIELDS

    def test_description_edit_changes_hash(self) -> None:
        h1 = content_hash(self._job())
        h2 = content_hash(self._job(description="Build cool stuff. Updated."))
        assert h1 != h2

    def test_whitespace_normalization(self) -> None:
        h1 = content_hash(self._job(description="Build  cool   stuff."))
        h2 = content_hash(self._job(description=" build cool stuff."))
        assert h1 == h2

    def test_normalized_content_excludes_unstable(self) -> None:
        normalized = normalize_job_content(self._job(applicant_count=99, promoted=True))
        for field in UNSTABLE_CONTENT_FIELDS:
            assert field not in normalized

    def test_empty_string_collapse(self) -> None:
        # An empty location ought not perturb the hash relative to a
        # missing location.
        h1 = content_hash(self._job(location=""))
        h2 = content_hash({k: v for k, v in self._job().items() if k != "location"})
        assert h1 == h2
