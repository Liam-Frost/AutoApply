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

        with patch("src.web.routes.api.load_dashboard_data", return_value=payload):
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

    @patch("src.web.routes.api.apply_to_url")
    def test_jobs_apply_post(self, mock_apply_to_url, client):
        mock_apply_to_url.return_value = {
            "ok": True,
            "status": "REVIEW_REQUIRED",
            "job": {"company": "TestCo", "title": "SWE Intern"},
        }

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
        with patch(
            "src.web.routes.api.load_applications_data",
            return_value={
                "applications": [
                    {
                        "id": str(app.id),
                        "job_id": str(app.job_id),
                        "status": app.status,
                        "match_score": app.match_score,
                        "outcome": app.outcome,
                        "created_at": app.created_at.isoformat(),
                        "updated_at": app.updated_at.isoformat(),
                        "submitted_at": app.submitted_at.isoformat(),
                        "job": {
                            "id": str(job.id),
                            "company": job.company,
                            "title": job.title,
                            "location": job.location,
                            "application_url": job.application_url,
                            "ats_type": job.ats_type,
                        },
                    }
                ],
                "pipeline": {"SUBMITTED": 1},
                "outcomes": {
                    "total": 1,
                    "pending": 1,
                    "rates": {"response_rate": 0.0, "positive_rate": 0.0},
                },
                "error": None,
                "filters": {"status": "SUBMITTED", "outcome": "", "company": "", "limit": 50},
            },
        ):
            response = client.get("/api/applications?status=SUBMITTED")

        assert response.status_code == 200
        payload = response.json()
        assert payload["applications"][0]["job"]["company"] == "TestCo"
        assert payload["pipeline"]["SUBMITTED"] == 1

    def test_update_outcome_route(self, client):
        with patch(
            "src.web.routes.api.update_application_outcome",
            return_value={
                "ok": True,
                "status": "updated",
                "message": "Updated to offer",
                "application_id": "00000000-0000-0000-0000-000000000001",
                "outcome": "offer",
                "updated_at": datetime.now(UTC).isoformat(),
            },
        ):
            response = client.patch(
                "/api/applications/00000000-0000-0000-0000-000000000001/outcome",
                json={"outcome": "offer"},
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Updated to offer"


class TestProfileApi:
    def test_profile_endpoint_returns_empty_state(self, client):
        with patch(
            "src.web.routes.api.load_profile_data",
            return_value={
                "profile": None,
                "profile_path": "data/profile/profiles/default.yaml",
                "has_profile": False,
                "profiles": [],
                "active_profile_id": None,
                "selected_profile_id": None,
            },
        ):
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

    def test_create_profile(self, client):
        with patch(
            "src.web.routes.api.create_empty_profile",
            return_value={
                "ok": True,
                "status": "created",
                "message": "Profile 'new-profile' created.",
                "profile": {
                    "identity": {},
                    "education": [],
                    "work_experiences": [],
                    "projects": [],
                    "skills": {},
                },
                "profile_path": "data/profile/profiles/new-profile.yaml",
                "has_profile": True,
                "profiles": [{"id": "new-profile", "is_active": True}],
                "active_profile_id": "new-profile",
                "selected_profile_id": "new-profile",
            },
        ):
            response = client.post(
                "/api/profile", json={"profile_id": "new-profile", "set_active": True}
            )

        assert response.status_code == 200
        assert response.json()["active_profile_id"] == "new-profile"

    def test_save_profile(self, client):
        with patch(
            "src.web.routes.api.save_profile_data",
            return_value={
                "ok": True,
                "status": "saved",
                "message": "Profile 'default' saved.",
                "profile": {
                    "identity": {"full_name": "Test User"},
                    "education": [],
                    "work_experiences": [],
                    "projects": [],
                    "skills": {},
                },
                "profile_path": "data/profile/profiles/default.yaml",
                "has_profile": True,
                "profiles": [{"id": "default", "is_active": True}],
                "active_profile_id": "default",
                "selected_profile_id": "default",
            },
        ):
            response = client.put(
                "/api/profile/default",
                json={
                    "profile_id": "default",
                    "profile": {"identity": {"full_name": "Test User"}},
                    "set_active": True,
                },
            )

        assert response.status_code == 200
        assert response.json()["profile"]["identity"]["full_name"] == "Test User"

    def test_activate_profile(self, client):
        with patch(
            "src.web.routes.api.activate_profile_data",
            return_value={
                "ok": True,
                "status": "activated",
                "message": "Profile 'default' activated.",
                "profile": {"identity": {}},
                "profile_path": "data/profile/profiles/default.yaml",
                "has_profile": True,
                "profiles": [{"id": "default", "is_active": True}],
                "active_profile_id": "default",
                "selected_profile_id": "default",
            },
        ):
            response = client.post("/api/profile/default/activate")

        assert response.status_code == 200
        assert response.json()["status"] == "activated"

    def test_delete_profile(self, client):
        with patch(
            "src.web.routes.api.delete_profile_data",
            return_value={
                "ok": True,
                "status": "deleted",
                "message": "Profile 'default' deleted.",
                "profile": None,
                "profile_path": "",
                "has_profile": False,
                "profiles": [],
                "active_profile_id": None,
                "selected_profile_id": None,
            },
        ):
            response = client.delete("/api/profile/default")

        assert response.status_code == 200
        assert response.json()["status"] == "deleted"

    def test_rename_profile(self, client):
        with patch(
            "src.web.routes.api.rename_profile_data",
            return_value={
                "ok": True,
                "status": "renamed",
                "message": "Profile 'default' renamed to 'new-default'.",
                "profile": {"identity": {}},
                "profile_path": "data/profile/profiles/new-default.yaml",
                "has_profile": True,
                "profiles": [{"id": "new-default", "is_active": True}],
                "active_profile_id": "new-default",
                "selected_profile_id": "new-default",
            },
        ):
            response = client.patch(
                "/api/profile/default/rename",
                json={"new_profile_id": "new-default"},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "renamed"
        assert response.json()["selected_profile_id"] == "new-default"


class TestSettingsApi:
    def test_settings_page_loads(self, client):
        with patch(
            "src.web.routes.api.load_llm_settings_data",
            return_value={
                "llm": {
                    "primary_provider": "claude-cli",
                    "fallback_provider": "codex-cli",
                    "allow_fallback": True,
                },
                "available_providers": {"claude-cli": True, "codex-cli": True},
                "config_path": "config/settings.yaml",
            },
        ):
            response = client.get("/api/settings/llm")

        assert response.status_code == 200
        assert response.json()["llm"]["primary_provider"] == "claude-cli"

    def test_settings_update_llm(self, client):
        with patch(
            "src.web.routes.api.update_llm_settings_data",
            return_value={
                "ok": True,
                "status": "updated",
                "message": "LLM settings updated successfully.",
                "llm": {
                    "primary_provider": "codex-cli",
                    "fallback_provider": "claude-cli",
                    "allow_fallback": True,
                },
                "available_providers": {"claude-cli": True, "codex-cli": True},
                "config_path": "config/settings.yaml",
            },
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
