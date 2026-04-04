"""Tests for Phase 7: Web GUI.

Tests FastAPI app creation, route registration, template rendering,
and basic endpoint functionality using FastAPI's TestClient.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ──────────────────────────────────────────────
# App Factory Tests
# ──────────────────────────────────────────────


class TestAppFactory:
    """Test FastAPI application creation and configuration."""

    def test_create_app(self):
        from src.web.app import create_app

        app = create_app()
        assert app.title == "AutoApply"
        assert app.version == "0.7.0"

    def test_app_has_templates(self):
        from src.web.app import create_app

        app = create_app()
        assert hasattr(app.state, "templates")

    def test_routes_registered(self):
        from src.web.app import create_app

        app = create_app()
        paths = [r.path for r in app.routes]

        assert "/" in paths
        assert "/jobs/" in paths
        assert "/jobs/search" in paths
        assert "/applications/" in paths
        assert "/profile/" in paths

    def test_static_mount(self):
        from src.web.app import create_app

        app = create_app()
        paths = [r.path for r in app.routes]
        assert "/static" in paths


# ──────────────────────────────────────────────
# Dashboard Tests
# ──────────────────────────────────────────────


class TestDashboard:
    """Test dashboard page rendering."""

    @pytest.fixture
    def client(self):
        from src.web.app import create_app

        app = create_app()
        return TestClient(app)

    def test_dashboard_loads(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "AutoApply" in response.text
        assert "Dashboard" in response.text

    def test_dashboard_has_stats_cards(self, client):
        response = client.get("/")
        assert "Total Applications" in response.text
        assert "Pending" in response.text
        assert "Submitted" in response.text

    def test_dashboard_has_quick_actions(self, client):
        response = client.get("/")
        assert "Search Jobs" in response.text
        assert "View Applications" in response.text
        assert "Manage Profile" in response.text

    def test_dashboard_shows_db_warning_when_disconnected(self, client):
        response = client.get("/")
        assert "Database not connected" in response.text or "autoapply init" in response.text


# ──────────────────────────────────────────────
# Jobs Page Tests
# ──────────────────────────────────────────────


class TestJobsPage:
    """Test job search page."""

    @pytest.fixture
    def client(self):
        from src.web.app import create_app

        app = create_app()
        return TestClient(app)

    def test_jobs_page_loads(self, client):
        response = client.get("/jobs/")
        assert response.status_code == 200
        assert "Search Jobs" in response.text

    def test_jobs_page_has_search_form(self, client):
        response = client.get("/jobs/")
        assert "source" in response.text
        assert "keyword" in response.text
        assert "location" in response.text
        assert "LinkedIn" in response.text

    def test_jobs_search_empty_returns_no_results(self, client):
        response = client.get("/jobs/")
        assert "No jobs found" in response.text or "Search" in response.text

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
            ),
        ]

        response = client.post(
            "/jobs/search",
            data={
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
        assert "1 jobs found" in response.text
        assert "TestCo" in response.text
        assert "SWE Intern" in response.text

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
            "/jobs/apply",
            data={"url": "https://boards.greenhouse.io/testco/jobs/123"},
        )

        assert response.status_code == 200
        assert "Filled to review stage" in response.text


# ──────────────────────────────────────────────
# Applications Page Tests
# ──────────────────────────────────────────────


class TestApplicationsPage:
    """Test applications tracking page."""

    @pytest.fixture
    def client(self):
        from src.web.app import create_app

        app = create_app()
        return TestClient(app)

    def test_applications_page_loads(self, client):
        response = client.get("/applications/")
        assert response.status_code == 200
        assert "Applications" in response.text

    def test_applications_shows_empty_state(self, client):
        response = client.get("/applications/")
        # Either shows DB warning or empty state
        assert (
            "No applications" in response.text
            or "Database" in response.text
            or "autoapply init" in response.text
        )

    def test_applications_filter_params(self, client):
        response = client.get("/applications/?status=SUBMITTED&outcome=pending")
        assert response.status_code == 200

    def test_update_outcome_route(self, client):
        session = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__.return_value = session
        session_cm.__exit__.return_value = None

        with (
            patch("src.core.config.load_config", return_value={}),
            patch(
                "src.core.database.get_session_factory",
                return_value=MagicMock(return_value=session_cm),
            ),
            patch("src.tracker.database.update_outcome", return_value=MagicMock()),
        ):
            response = client.post(
                "/applications/update-outcome",
                data={"application_id": "00000000-0000-0000-0000-000000000001", "outcome": "offer"},
            )

        assert response.status_code == 200
        assert "Updated to offer" in response.text


# ──────────────────────────────────────────────
# Profile Page Tests
# ──────────────────────────────────────────────


class TestProfilePage:
    """Test profile management page."""

    @pytest.fixture
    def client(self):
        from src.web.app import create_app

        app = create_app()
        return TestClient(app)

    def test_profile_page_loads(self, client):
        response = client.get("/profile/")
        assert response.status_code == 200
        assert "Profile" in response.text

    def test_profile_shows_upload_when_no_profile(self, client):
        with patch("src.web.routes.profile.PROFILE_FILE") as mock_path:
            mock_path.exists.return_value = False
            response = client.get("/profile/")
            assert response.status_code == 200
            assert "Upload Resume" in response.text or "No profile" in response.text


# ──────────────────────────────────────────────
# Navigation Tests
# ──────────────────────────────────────────────


class TestNavigation:
    """Test navigation links across pages."""

    @pytest.fixture
    def client(self):
        from src.web.app import create_app

        app = create_app()
        return TestClient(app)

    def test_nav_links_on_dashboard(self, client):
        response = client.get("/")
        assert 'href="/"' in response.text
        assert 'href="/jobs"' in response.text
        assert 'href="/applications"' in response.text
        assert 'href="/profile"' in response.text

    def test_nav_links_on_jobs(self, client):
        response = client.get("/jobs/")
        assert 'href="/"' in response.text
        assert 'href="/jobs"' in response.text


# ──────────────────────────────────────────────
# CLI Web Command Tests
# ──────────────────────────────────────────────


class TestWebCLI:
    """Test the web CLI command."""

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

    def test_main_help_includes_web(self):
        from click.testing import CliRunner

        from src.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "web" in result.output
