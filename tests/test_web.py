"""Tests for the Vue-based web GUI and JSON API."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.web.app import create_app

    return TestClient(create_app())


class TestAppFactory:
    def test_create_app(self):
        from src.web.app import create_app

        app = create_app()
        assert app.title == "AutoApply"
        assert app.version == "0.7.0"

    def test_routes_registered(self):
        from src.web.app import create_app

        app = create_app()
        paths = [route.path for route in app.routes]

        assert "/" in paths
        assert "/assets" in paths
        assert "/api/dashboard" in paths
        assert "/api/jobs/search" in paths
        assert "/api/applications" in paths
        assert "/api/profile" in paths
        assert "/api/settings/llm" in paths


class TestSpaShell:
    def test_root_serves_spa_index(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert '<div id="app"></div>' in response.text
        assert "/assets/" in response.text

    def test_nested_route_serves_spa_index(self, client):
        response = client.get("/jobs/")
        assert response.status_code == 200
        assert '<div id="app"></div>' in response.text


class TestDashboardApi:
    def test_dashboard_returns_json(self, client):
        payload = {
            "pipeline": {"SUBMITTED": 3},
            "summary": {
                "total_discovered": 5,
                "total_applied": 3,
                "total_failed": 0,
                "total_review": 1,
                "avg_match_score": 0.8,
                "avg_fields_filled_pct": 0.7,
            },
            "outcomes": {
                "total": 3,
                "pending": 1,
                "rates": {"response_rate": 0.5, "positive_rate": 0.25},
            },
            "companies": [
                {
                    "company": "TestCo",
                    "applications": 2,
                    "submitted": 1,
                    "outcomes": {},
                    "avg_match_score": 0.9,
                }
            ],
            "db_connected": True,
        }

        with patch("src.web.routes.api._load_dashboard_data", return_value=payload):
            response = client.get("/api/dashboard")

        assert response.status_code == 200
        assert response.json()["summary"]["total_discovered"] == 5
        assert response.json()["companies"][0]["company"] == "TestCo"


class TestJobsApi:
    @patch("src.intake.search.search_jobs")
    def test_jobs_search_post_ats(self, mock_search, client):
        from src.intake.schema import RawJob

        mock_search.return_value = [
            RawJob(
                source="greenhouse",
                source_id="123",
                company="TestCo",
                title="SWE Intern",
                ats_type="greenhouse",
            )
        ]

        response = client.post(
            "/api/jobs/search",
            json={
                "source": "ats",
                "keyword": "",
                "location": "",
                "profile": "default",
                "time_filter": "week",
                "ats": "",
                "company": "",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["error"] is None
        assert payload["jobs"][0]["company"] == "TestCo"
        assert payload["jobs"][0]["title"] == "SWE Intern"

    @patch("src.intake.search.search_jobs")
    @patch("src.intake.search.search_linkedin")
    def test_jobs_search_all_keeps_ats_results_when_linkedin_fails(
        self,
        mock_linkedin,
        mock_search,
        client,
    ):
        from src.intake.schema import RawJob

        mock_linkedin.side_effect = RuntimeError("linkedin unavailable")
        mock_search.return_value = [
            RawJob(
                source="greenhouse",
                source_id="123",
                company="TestCo",
                title="Backend Engineer",
                ats_type="greenhouse",
            )
        ]

        response = client.post(
            "/api/jobs/search",
            json={
                "source": "all",
                "keyword": "backend",
                "location": "",
                "profile": "default",
                "time_filter": "week",
                "ats": "",
                "company": "",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["jobs"][0]["title"] == "Backend Engineer"
        assert "LinkedIn:" in payload["error"]

    @patch("src.cli.cmd_apply._run_application_for_job")
    @patch("src.cli.cmd_apply._load_job_for_application")
    @patch("src.cli.cmd_apply._load_profile")
    @patch("src.cli.cmd_apply._detect_ats_from_url")
    def test_jobs_apply_post(
        self,
        mock_detect_ats,
        mock_load_profile,
        mock_load_job,
        mock_run_apply,
        client,
    ):
        from src.core.state_machine import AppStatus
        from src.intake.schema import RawJob

        mock_detect_ats.return_value = "greenhouse"
        mock_load_profile.return_value = {"identity": {"full_name": "Test User"}}
        mock_load_job.return_value = RawJob(
            source="greenhouse",
            source_id="123",
            company="TestCo",
            title="SWE Intern",
            ats_type="greenhouse",
            application_url="https://boards.greenhouse.io/testco/jobs/123",
        )
        mock_run_apply.return_value = MagicMock(status=AppStatus.REVIEW_REQUIRED, error="")

        response = client.post(
            "/api/jobs/apply",
            json={"url": "https://boards.greenhouse.io/testco/jobs/123"},
        )

        assert response.status_code == 200
        assert response.json()["message"] == "Filled to review stage"


class TestApplicationsApi:
    def test_applications_list(self, client):
        app = MagicMock(
            id="00000000-0000-0000-0000-000000000001",
            job_id="00000000-0000-0000-0000-000000000002",
            status="SUBMITTED",
            match_score=0.8,
            outcome="pending",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            submitted_at=datetime.now(UTC),
        )
        job = MagicMock(
            id="00000000-0000-0000-0000-000000000002",
            company="TestCo",
            title="SWE Intern",
            location="Remote",
            application_url="https://example.com/apply",
            ats_type="greenhouse",
        )
        session = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__.return_value = session
        session_cm.__exit__.return_value = None

        with (
            patch("src.web.routes.api.load_config", return_value={}),
            patch(
                "src.core.database.get_session_factory",
                return_value=MagicMock(return_value=session_cm),
            ),
            patch("src.tracker.database.get_applications_with_jobs", return_value=[(app, job)]),
            patch("src.tracker.database.get_application_counts", return_value={"SUBMITTED": 1}),
            patch(
                "src.tracker.analytics.compute_outcome_stats",
                return_value=MagicMock(
                    total_submitted=1,
                    pending=1,
                    rejected=0,
                    oa=0,
                    interview=0,
                    offer=0,
                    response_rate=0.0,
                    positive_rate=0.0,
                ),
            ),
        ):
            response = client.get("/api/applications?status=SUBMITTED")

        assert response.status_code == 200
        payload = response.json()
        assert payload["applications"][0]["job"]["company"] == "TestCo"
        assert payload["pipeline"]["SUBMITTED"] == 1

    def test_update_outcome_route(self, client):
        updated = MagicMock(
            id="00000000-0000-0000-0000-000000000001",
            outcome="offer",
            outcome_updated_at=datetime.now(UTC),
        )
        session = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__.return_value = session
        session_cm.__exit__.return_value = None

        with (
            patch("src.web.routes.api.load_config", return_value={}),
            patch(
                "src.core.database.get_session_factory",
                return_value=MagicMock(return_value=session_cm),
            ),
            patch("src.tracker.database.update_outcome", return_value=updated),
        ):
            response = client.patch(
                "/api/applications/00000000-0000-0000-0000-000000000001/outcome",
                json={"outcome": "offer"},
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Updated to offer"


class TestProfileApi:
    def test_profile_endpoint_returns_empty_state(self, client):
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        mock_path.__str__.return_value = "data/profile/profile.yaml"

        with patch("src.web.routes.api.PROFILE_FILE", mock_path):
            response = client.get("/api/profile")

        assert response.status_code == 200
        assert response.json()["has_profile"] is False

    def test_profile_upload_rejects_invalid_extension(self, client):
        response = client.post(
            "/api/profile/upload-resume",
            files={"resume": ("resume.txt", b"invalid", "text/plain")},
        )

        assert response.status_code == 400
        assert "Only .pdf and .docx files are supported." in response.json()["detail"]


class TestSettingsApi:
    def test_settings_page_loads(self, client):
        with (
            patch("src.web.routes.api.load_config", return_value={}),
            patch(
                "src.web.routes.api.get_llm_settings",
                return_value={
                    "primary_provider": "claude-cli",
                    "fallback_provider": "codex-cli",
                    "allow_fallback": True,
                },
            ),
            patch(
                "src.web.routes.api.detect_available_providers",
                return_value={"claude-cli": True, "codex-cli": True},
            ),
        ):
            response = client.get("/api/settings/llm")

        assert response.status_code == 200
        assert response.json()["llm"]["primary_provider"] == "claude-cli"

    def test_settings_update_llm(self, client):
        with (
            patch("src.web.routes.api.update_llm_settings"),
            patch("src.web.routes.api.load_config", return_value={}),
            patch(
                "src.web.routes.api.get_llm_settings",
                return_value={
                    "primary_provider": "codex-cli",
                    "fallback_provider": "claude-cli",
                    "allow_fallback": True,
                },
            ),
            patch(
                "src.web.routes.api.detect_available_providers",
                return_value={"claude-cli": True, "codex-cli": True},
            ),
        ):
            response = client.put(
                "/api/settings/llm",
                json={
                    "primary_provider": "codex-cli",
                    "fallback_provider": "claude-cli",
                    "allow_fallback": True,
                },
            )

        assert response.status_code == 200
        assert response.json()["message"] == "LLM settings updated successfully."


class TestWebCLI:
    def test_web_help(self):
        from click.testing import CliRunner

        from src.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["web", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output
        assert "--port" in result.output
        assert "--no-open" in result.output
        assert "--reload" in result.output
        assert "--show-logs" in result.output

    def test_main_help_includes_web(self):
        from click.testing import CliRunner

        from src.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "web" in result.output
