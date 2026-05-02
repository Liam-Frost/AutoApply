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
        assert "/api/jobs/linkedin/session" in paths
        assert "/api/jobs/linkedin/session/connect" in paths
        assert "/api/jobs/manual-apply-target" in paths
        assert "/api/jobs/generate-material" in paths
        assert "/api/templates" in paths
        assert "/api/templates/upload" in paths
        assert "/api/templates/latex" in paths
        assert "/api/templates/{document_type}/{template_id}" in paths
        assert "/api/templates/{document_type}/{template_id}/validate" in paths
        assert "/api/artifacts/download" in paths
        assert "/api/jobs/filter-profiles" in paths
        assert "/api/applications" in paths
        assert "/api/profile" in paths
        assert "/api/settings/llm" in paths
        assert "/api/settings/search-cache" in paths


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

    def test_materials_route_serves_spa_index(self, client):
        response = client.get("/materials")
        assert response.status_code == 200
        assert '<div id="app"></div>' in response.text

    def test_materials_subroute_serves_spa_index(self, client):
        response = client.get("/materials/templates")
        assert response.status_code == 200
        assert '<div id="app"></div>' in response.text

    def test_unknown_top_level_path_serves_spa_index(self, client):
        # Any non-/api/, non-/assets/ path falls back to the SPA so
        # vue-router can render its own "not found" view rather than
        # FastAPI returning a 404 on a hard refresh.
        response = client.get("/some-deep/client-only/route")
        assert response.status_code == 200
        assert '<div id="app"></div>' in response.text

    def test_unknown_api_path_returns_404(self, client):
        response = client.get("/api/does-not-exist")
        assert response.status_code == 404


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
    @patch("src.web.routes.api.search_jobs_usecase")
    def test_jobs_search_uses_no_filter_profile_by_default(self, mock_usecase, client):
        mock_usecase.return_value = {
            "search_params": {"keyword": "", "keywords": ["backend"], "profile": None},
            "jobs": [],
            "errors": [],
            "error": None,
            "error_code": None,
            "counts": {"ats": 0, "linkedin": 0, "linkedin_external_ats": 0, "total": 0},
            "scored": False,
        }

        response = client.post(
            "/api/jobs/search",
            json={
                "source": "linkedin",
                "keyword": "",
                "keywords": ["backend"],
                "location": "",
                "profile": "",
                "time_filter": "week",
                "ats": "",
                "company": "",
            },
        )

        assert response.status_code == 200
        assert mock_usecase.call_args.kwargs["profile"] is None
        assert mock_usecase.call_args.kwargs["keywords"] == ["backend"]

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

    @patch("src.intake.search.search_linkedin")
    def test_jobs_search_linkedin_auth_required_returns_error_code(self, mock_linkedin, client):
        from src.intake.linkedin import LinkedInAuthRequiredError

        mock_linkedin.side_effect = LinkedInAuthRequiredError("login required")

        response = client.post(
            "/api/jobs/search",
            json={
                "source": "linkedin",
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
        assert payload["error_code"] == "linkedin_auth_required"
        assert "login required" in payload["error"]

    @patch("src.web.routes.api.get_linkedin_session_status_usecase")
    def test_linkedin_session_status_route(self, mock_status, client):
        mock_status.return_value = {
            "ok": True,
            "authenticated": False,
            "has_session_data": True,
            "message": "LinkedIn session is not authenticated.",
            "error": None,
            "error_code": None,
        }

        response = client.get("/api/jobs/linkedin/session")

        assert response.status_code == 200
        assert response.json()["authenticated"] is False

    @patch("src.web.routes.api.connect_linkedin_session_usecase")
    def test_linkedin_session_connect_route(self, mock_connect, client):
        mock_connect.return_value = {
            "ok": True,
            "authenticated": True,
            "has_session_data": True,
            "message": "LinkedIn session connected.",
            "error": None,
            "error_code": None,
        }

        response = client.post("/api/jobs/linkedin/session/connect")

        assert response.status_code == 200
        assert response.json()["authenticated"] is True

    @patch("src.web.routes.api.clear_linkedin_session_usecase")
    def test_linkedin_session_clear_route(self, mock_clear, client):
        mock_clear.return_value = {
            "ok": True,
            "authenticated": False,
            "has_session_data": False,
            "message": "LinkedIn session cleared.",
            "error": None,
            "error_code": None,
        }

        response = client.delete("/api/jobs/linkedin/session")

        assert response.status_code == 200
        assert response.json()["has_session_data"] is False

    @patch("src.web.routes.api.resolve_manual_apply_url_usecase")
    def test_manual_apply_target_route(self, mock_manual_apply, client):
        mock_manual_apply.return_value = {
            "ok": True,
            "url": "https://company.example/apply/123",
            "source_url": "https://www.linkedin.com/jobs/view/123",
            "ats_url": None,
            "error": None,
            "error_code": None,
        }

        response = client.post(
            "/api/jobs/manual-apply-target",
            json={"url": "https://www.linkedin.com/jobs/view/123"},
        )

        assert response.status_code == 200
        assert response.json()["url"] == "https://company.example/apply/123"

    @patch("src.web.routes.api.load_search_profiles_data")
    def test_filter_profiles_route(self, mock_profiles, client):
        mock_profiles.return_value = {
            "ok": True,
            "profiles": [{"id": "vancouver-software", "keywords": ["software"]}],
            "config_path": "config/search_profiles.yaml",
            "error": None,
            "error_code": None,
        }

        response = client.get("/api/jobs/filter-profiles")

        assert response.status_code == 200
        assert response.json()["profiles"][0]["id"] == "vancouver-software"

    @patch("src.web.routes.api.save_search_profile_data")
    def test_save_filter_profile_route(self, mock_save, client):
        mock_save.return_value = {
            "ok": True,
            "profiles": [{"id": "software", "keywords": ["software"]}],
            "message": "Saved filter profile 'software'.",
        }

        response = client.put(
            "/api/jobs/filter-profiles/software",
            json={
                "source": "linkedin",
                "keywords": ["software"],
                "locations": ["Vancouver"],
            },
        )

        assert response.status_code == 200
        assert response.json()["profiles"][0]["id"] == "software"

    @patch("src.web.routes.api.delete_search_profile_data")
    def test_delete_filter_profile_route(self, mock_delete, client):
        mock_delete.return_value = {
            "ok": True,
            "profiles": [],
            "message": "Deleted filter profile 'software'.",
        }

        response = client.delete("/api/jobs/filter-profiles/software")

        assert response.status_code == 200
        assert response.json()["profiles"] == []

    def test_search_profile_storage_rejects_invalid_profile_id(self, tmp_path):
        from src.application.search_profiles import save_search_profile_data

        with patch(
            "src.application.search_profiles.SEARCH_PROFILES_PATH",
            tmp_path / "search_profiles.yaml",
        ):
            result = save_search_profile_data(
                profile_id=":\n  injected: true",
                profile={"source": "linkedin", "keywords": ["software"]},
            )

        assert result["ok"] is False
        assert result["error_code"] == "invalid_search_profile_name"
        assert not (tmp_path / "search_profiles.yaml").exists()

    def test_save_filter_profile_route_rejects_invalid_profile_id(self, client, tmp_path):
        with patch(
            "src.application.search_profiles.SEARCH_PROFILES_PATH",
            tmp_path / "search_profiles.yaml",
        ):
            response = client.put(
                "/api/jobs/filter-profiles/bad:name",
                json={"source": "linkedin", "keywords": ["software"]},
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid filter profile name."
        assert not (tmp_path / "search_profiles.yaml").exists()

    def test_delete_filter_profile_route_rejects_invalid_profile_id(self, client, tmp_path):
        with patch(
            "src.application.search_profiles.SEARCH_PROFILES_PATH",
            tmp_path / "search_profiles.yaml",
        ):
            response = client.delete("/api/jobs/filter-profiles/bad:name")

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid filter profile name."

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

    @patch("src.web.routes.api.generate_material_for_job_usecase")
    def test_generate_material_route(self, mock_generate, client):
        mock_generate.return_value = {
            "ok": True,
            "job": {"company": "TestCo", "title": "SWE Intern"},
            "material_type": "resume_pdf",
            "artifact": {
                "type": "resume_pdf",
                "path": "data/output/resume.pdf",
                "filename": "resume.pdf",
            },
            "artifacts": {"resume_pdf": "data/output/resume.pdf"},
            "template": {"template_id": "ats_single_column_v1"},
            "requirements": {},
            "error": None,
            "error_code": None,
        }

        response = client.post(
            "/api/jobs/generate-material",
            json={
                "material_type": "resume_pdf",
                "template_id": "ats_single_column_v1",
                "profile_id": "default",
                "job": {"company": "TestCo", "title": "SWE Intern"},
            },
        )

        assert response.status_code == 200
        assert response.json()["artifact"]["filename"] == "resume.pdf"
        assert mock_generate.call_args.kwargs["material_type"] == "resume_pdf"
        assert mock_generate.call_args.kwargs["template_id"] == "ats_single_column_v1"
        assert mock_generate.call_args.kwargs["profile_id"] == "default"

    @patch("src.web.routes.api.generate_material_for_job_usecase")
    def test_generate_material_route_returns_400_for_profile_missing(
        self,
        mock_generate,
        client,
    ):
        mock_generate.return_value = {
            "ok": False,
            "error": "Profile not configured.",
            "error_code": "profile_missing",
        }

        response = client.post(
            "/api/jobs/generate-material",
            json={"material_type": "resume_pdf", "job": {"title": "SWE"}},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Profile not configured."

    @patch("src.web.routes.api.generate_material_for_job_usecase")
    def test_generate_material_route_returns_500_for_generation_failure(
        self,
        mock_generate,
        client,
    ):
        mock_generate.return_value = {
            "ok": False,
            "error": "Renderer failed.",
            "error_code": "material_generation_failed",
        }

        response = client.post(
            "/api/jobs/generate-material",
            json={"material_type": "resume_pdf", "job": {"title": "SWE"}},
        )

        assert response.status_code == 500
        assert response.json()["detail"] == "Renderer failed."

    @patch("src.web.routes.api.list_material_templates_usecase")
    def test_templates_route(self, mock_templates, client):
        mock_templates.return_value = {
            "templates": {
                "resume": [{"template_id": "ats_single_column_v1"}],
                "cover_letter": [{"template_id": "classic_v1"}],
            }
        }

        response = client.get("/api/templates")

        assert response.status_code == 200
        assert response.json()["templates"]["resume"][0]["template_id"] == "ats_single_column_v1"

    @patch("src.web.routes.api.upload_material_template_usecase")
    def test_template_upload_route(self, mock_upload, client):
        mock_upload.return_value = {
            "ok": True,
            "template": {"template_id": "custom_resume"},
            "templates": {"resume": [{"template_id": "custom_resume"}], "cover_letter": []},
        }

        response = client.post(
            "/api/templates/upload",
            data={"document_type": "resume", "template_name": "Custom Resume"},
            files={
                "template": (
                    "custom.docx",
                    b"docx-bytes",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )

        assert response.status_code == 200
        assert response.json()["template"]["template_id"] == "custom_resume"
        assert mock_upload.call_args.kwargs["document_type"] == "resume"
        assert mock_upload.call_args.kwargs["filename"] == "custom.docx"

    @patch("src.web.routes.api.upload_material_template_usecase")
    def test_template_upload_route_rejects_oversized_upload(
        self,
        mock_upload,
        client,
    ):
        with patch("src.web.routes.api.MAX_TEMPLATE_UPLOAD_BYTES", 4):
            response = client.post(
                "/api/templates/upload",
                data={"document_type": "resume", "template_name": "Too Large"},
                files={
                    "template": (
                        "large.docx",
                        b"12345",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )

        assert response.status_code == 413
        assert response.json()["detail"] == "Template upload is too large."
        mock_upload.assert_not_called()

    @patch("src.web.routes.api.create_material_template_usecase")
    def test_template_latex_create_route(self, mock_create, client):
        mock_create.return_value = {
            "ok": True,
            "template": {"template_id": "latex_resume", "renderer": "latex"},
            "templates": {"resume": [{"template_id": "latex_resume"}], "cover_letter": []},
        }

        response = client.post(
            "/api/templates/latex",
            json={"document_type": "resume", "template_name": "LaTeX Resume"},
        )

        assert response.status_code == 200
        assert response.json()["template"]["renderer"] == "latex"
        assert mock_create.call_args.kwargs["document_type"] == "resume"

    @patch("src.web.routes.api.get_material_template_usecase")
    def test_template_detail_route(self, mock_detail, client):
        mock_detail.return_value = {
            "ok": True,
            "template": {"template_id": "latex_resume", "content": "{{resume.sections}}"},
        }

        response = client.get("/api/templates/resume/latex_resume")

        assert response.status_code == 200
        assert response.json()["template"]["content"] == "{{resume.sections}}"

    @patch("src.web.routes.api.update_material_template_usecase")
    def test_template_update_route(self, mock_update, client):
        mock_update.return_value = {
            "ok": True,
            "template": {"template_id": "latex_resume", "validation": {"ok": True}},
            "templates": {"resume": [{"template_id": "latex_resume"}], "cover_letter": []},
        }

        response = client.put(
            "/api/templates/resume/latex_resume",
            json={"template_name": "LaTeX Resume", "content": "{{resume.sections}}"},
        )

        assert response.status_code == 200
        assert response.json()["template"]["validation"]["ok"] is True
        assert mock_update.call_args.kwargs["content"] == "{{resume.sections}}"

    @patch("src.web.routes.api.validate_material_template_usecase")
    def test_template_validate_route(self, mock_validate, client):
        mock_validate.return_value = {
            "ok": True,
            "template": {"template_id": "latex_resume", "validation": {"ok": False}},
            "validation": {"ok": False, "issues": [{"type": "missing_block"}]},
        }

        response = client.post("/api/templates/resume/latex_resume/validate")

        assert response.status_code == 200
        assert response.json()["validation"]["ok"] is False

    @patch("src.web.routes.api.delete_material_template_usecase")
    def test_template_delete_route(self, mock_delete, client):
        mock_delete.return_value = {
            "ok": True,
            "templates": {"resume": [], "cover_letter": []},
        }

        response = client.delete("/api/templates/resume/latex_resume")

        assert response.status_code == 200
        assert response.json()["templates"]["resume"] == []
        assert mock_delete.call_args.kwargs["document_type"] == "resume"
        assert mock_delete.call_args.kwargs["template_id"] == "latex_resume"

    @patch("src.web.routes.api.delete_material_template_usecase")
    def test_template_delete_route_protects_default(self, mock_delete, client):
        mock_delete.return_value = {
            "ok": False,
            "error": "Built-in default templates cannot be deleted.",
            "error_code": "template_default_protected",
        }

        response = client.delete("/api/templates/resume/ats_single_column_v1")

        assert response.status_code == 403
        assert response.json()["detail"] == "Built-in default templates cannot be deleted."

    def test_artifact_download_restricts_to_output_dir(self, client, tmp_path):
        output_dir = tmp_path / "data" / "output"
        output_dir.mkdir(parents=True)
        artifact = output_dir / "resume.pdf"
        artifact.write_bytes(b"pdf")
        outside = tmp_path / "secret.txt"
        outside.write_text("secret", encoding="utf-8")

        with patch("src.web.routes.api.PROJECT_ROOT", tmp_path):
            response = client.get(
                "/api/artifacts/download", params={"path": str(artifact)}
            )

        assert response.status_code == 200
        assert response.content == b"pdf"

        with patch("src.web.routes.api.PROJECT_ROOT", tmp_path):
            response = client.get(
                "/api/artifacts/download", params={"path": "data/output/resume.pdf"}
            )

        assert response.status_code == 200
        assert response.content == b"pdf"

        with patch("src.web.routes.api.PROJECT_ROOT", tmp_path):
            response = client.get(
                "/api/artifacts/download", params={"path": str(outside)}
            )

        assert response.status_code == 400


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
                "search_cache": {"enabled": True, "ttl_hours": 24},
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
                "search_cache": {"enabled": False, "ttl_hours": 12},
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
                    "cache_enabled": False,
                    "cache_ttl_hours": 12,
                },
            )

        assert response.status_code == 200
        assert response.json()["message"] == "LLM settings updated successfully."

    def test_settings_clear_search_cache(self, client):
        with patch(
            "src.web.routes.api.clear_search_cache_data",
            return_value={
                "ok": True,
                "message": "Cleared 3 cached LinkedIn search entries.",
                "llm": {
                    "primary_provider": "claude-cli",
                    "fallback_provider": "codex-cli",
                    "allow_fallback": True,
                },
                "search_cache": {"enabled": True, "ttl_hours": 24},
                "available_providers": {"claude-cli": True, "codex-cli": True},
                "config_path": "config/settings.yaml",
            },
        ):
            response = client.delete("/api/settings/search-cache")

        assert response.status_code == 200
        assert "Cleared 3" in response.json()["message"]


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
