"""Phase 16.3 -- ``/api/matching/explain`` route + ``explain_job`` use case.

Use-case logic (profile loading + RawJob coercion + scorer dispatch)
gets unit coverage; the route then gets a single wire-up smoke test to
confirm it returns the structured envelope.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.application.matching import explain_job
from src.matching.rules import RuleResult, RuleVerdict
from src.matching.scorer import ScoreBreakdown

_PROFILE = {
    "identity": {
        "location": "Vancouver, BC, Canada",
        "citizenship": "Chinese",
        "work_authorization": "Study Permit",
        "visa_sponsorship_needed": True,
    },
    "education": [{"degree": "Bachelor of Science"}],
    "work_experiences": [
        {
            "company": "Acme",
            "title": "Intern",
            "start_date": "2025-05",
            "end_date": "2025-08",
            "bullets": [{"text": "Built APIs", "tags": ["python"]}],
        }
    ],
    "skills": {"languages": ["Python"]},
}


def _job_payload(**overrides: object) -> dict:
    defaults = {
        "id": "00000000-0000-0000-0000-000000000001",
        "source": "greenhouse",
        "source_id": "j1",
        "company": "Acme",
        "title": "Software Engineering Intern",
        "location": "Vancouver, BC",
        "employment_type": "internship",
        "seniority": "internship",
        "description": (
            "Strong Python intern role. This role does not offer visa "
            "sponsorship at this time."
        ),
        "ats_type": "greenhouse",
        "application_url": "https://example.com/apply",
        "raw_data": {
            "requirements": {"visa_sponsorship": False},
        },
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------- #
# Use case: explain_job                                                       #
# --------------------------------------------------------------------------- #


class TestExplainJobUseCase:
    @patch("src.application.matching._get_active_profile_dict", return_value=_PROFILE)
    def test_returns_structured_breakdown_for_disqualified_job(self, _profile):
        result = explain_job(_job_payload())
        assert result["ok"] is True
        bd = result["score_breakdown"]
        assert bd is not None
        assert bd["disqualified"] is True
        assert any(
            r["rule_id"] == "work_authorization" for r in bd["disqualify_results"]
        )

    @patch("src.application.matching._get_active_profile_dict", return_value=_PROFILE)
    def test_evidence_excerpt_present_for_disqualifying_rule(self, _profile):
        result = explain_job(_job_payload())
        bd = result["score_breakdown"]
        wa = next(r for r in bd["disqualify_results"] if r["rule_id"] == "work_authorization")
        assert wa["evidence_excerpt"] is not None
        assert "sponsorship" in wa["evidence_excerpt"].lower()

    @patch("src.application.matching._get_active_profile_dict", return_value=_PROFILE)
    def test_qualified_job_returns_empty_disqualify_results(self, _profile):
        result = explain_job(
            _job_payload(
                description="Strong Python intern; visa sponsorship available.",
                raw_data={"requirements": {"visa_sponsorship": True}},
            )
        )
        bd = result["score_breakdown"]
        assert bd["disqualified"] is False
        assert bd["disqualify_results"] == []

    @patch("src.application.matching._get_active_profile_dict", return_value=None)
    def test_no_active_profile_returns_ok_false(self, _profile):
        result = explain_job(_job_payload())
        assert result["ok"] is False
        assert result["score_breakdown"] is None
        assert any("profile" in w.lower() for w in result["warnings"])

    @patch("src.application.matching._get_active_profile_dict", return_value=_PROFILE)
    def test_malformed_payload_returns_ok_false(self, _profile):
        # Missing the required ``source_id`` field -> RawJob construction fails.
        result = explain_job({"id": "abc", "company": "X"})
        assert result["ok"] is False
        assert result["score_breakdown"] is None
        assert any("payload" in w.lower() for w in result["warnings"])

    @patch("src.application.matching._get_active_profile_dict", return_value=_PROFILE)
    def test_snapshot_id_threaded_from_raw_data(self, _profile):
        payload = _job_payload()
        payload["raw_data"]["job_snapshot_id"] = "snap-xyz"
        result = explain_job(payload)
        assert result["score_breakdown"]["job_snapshot_id"] == "snap-xyz"

    @patch("src.application.matching._get_active_profile_dict", return_value=_PROFILE)
    def test_strips_serialize_job_only_fields(self, _profile):
        """serialize_job() adds flat fields like ``match_score`` that
        RawJob doesn't accept -- the use case must strip them so the
        Pydantic constructor doesn't reject the payload."""
        payload = _job_payload(
            match_score=0.42,
            disqualified=True,
            experience_level="entry",
            employment_category="internship",
            location_type="onsite",
            education_level="Bachelor's",
            experience_years_min=0,
            experience_years_max=2,
            pay_min=20,
            pay_max=30,
            discovered_at="2026-05-15T12:00:00Z",
        )
        result = explain_job(payload)
        assert result["ok"] is True


# --------------------------------------------------------------------------- #
# Route wire-up                                                               #
# --------------------------------------------------------------------------- #


@pytest.fixture
def client() -> TestClient:
    from src.web.app import create_app

    return TestClient(create_app())


class TestExplainRoute:
    @patch("src.application.matching._get_active_profile_dict", return_value=_PROFILE)
    def test_route_returns_breakdown(self, _profile, client: TestClient):
        response = client.post(
            "/api/matching/explain",
            json={"job": _job_payload()},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["score_breakdown"]["disqualified"] is True

    def test_route_validates_payload_shape(self, client: TestClient):
        # Missing the required ``job`` field -> FastAPI 422.
        response = client.post("/api/matching/explain", json={})
        assert response.status_code == 422


# --------------------------------------------------------------------------- #
# ScoreBreakdown.to_dict consumer contract                                    #
# --------------------------------------------------------------------------- #


class TestUiContract:
    """Pin the shape the popover renders so the backend can't drift."""

    def test_to_dict_has_all_keys_the_popover_reads(self):
        bd = ScoreBreakdown(
            job_id="x",
            company="X",
            title="Y",
            final_score=0.42,
            disqualified=True,
            disqualify_reasons=["no visa"],
            disqualify_results=[
                RuleResult(
                    rule_id="work_authorization",
                    rule_name="work_authorization",
                    passed=False,
                    verdict="fail",
                    reason="no visa",
                    evidence_excerpt="...no sponsorship...",
                )
            ],
            rule_verdict=RuleVerdict(job_id="x", passed=False),
            job_snapshot_id="snap-9",
        )
        d = bd.to_dict()
        # Keys the Vue template references explicitly.
        for key in (
            "final_score",
            "job_snapshot_id",
            "disqualified",
            "disqualify_results",
            "disqualify_reasons",
        ):
            assert key in d, key
        rule = d["disqualify_results"][0]
        for key in ("rule_id", "rule_name", "verdict", "reason", "evidence_excerpt"):
            assert key in rule, key
