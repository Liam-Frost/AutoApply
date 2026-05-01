"""Tests for Phase 5: CLI, tracking, and analytics.

Tests CLI command structure, tracker database operations, analytics
computations, and export functionality. Uses in-memory mocks where
DB is not available.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from src.core.state_machine import ApplicationState, AppStatus

# ──────────────────────────────────────────────
# CLI Structure Tests
# ──────────────────────────────────────────────


class TestCLIStructure:
    """Test that CLI commands load and have correct help."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_main_help(self, runner):
        from src.cli.main import cli

        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "AutoApply" in result.output
        assert "init" in result.output
        assert "search" in result.output
        assert "apply" in result.output
        assert "status" in result.output

    def test_init_help(self, runner):
        from src.cli.main import cli

        result = runner.invoke(cli, ["init", "--help"])
        assert result.exit_code == 0
        assert "--profile" in result.output
        assert "--resume" in result.output
        assert "--skip-db" in result.output
        assert "--skip-llm" in result.output
        assert "--llm-primary" in result.output
        assert "--llm-fallback" in result.output

    def test_search_help(self, runner):
        from src.cli.main import cli

        result = runner.invoke(cli, ["search", "--help"])
        assert result.exit_code == 0
        assert "--profile" in result.output
        assert "--ats" in result.output
        assert "--score" in result.output
        assert "--json" in result.output

    def test_apply_help(self, runner):
        from src.cli.main import cli

        result = runner.invoke(cli, ["apply", "--help"])
        assert result.exit_code == 0
        assert "--url" in result.output
        assert "--batch" in result.output
        assert "--auto-submit" in result.output
        assert "--dry-run" in result.output
        assert "--json" in result.output

    def test_status_help(self, runner):
        from src.cli.main import cli

        result = runner.invoke(cli, ["status", "--help"])
        assert result.exit_code == 0
        assert "--export-csv" in result.output
        assert "--company" in result.output
        assert "--outcome" in result.output
        assert "--json" in result.output

    def test_apply_requires_target(self, runner):
        from src.cli.main import cli

        result = runner.invoke(cli, ["apply"])
        assert result.exit_code != 0
        assert "Specify --url" in result.output

    def test_search_json_output(self, runner):
        from src.cli.main import cli

        payload = {
            "search_params": {"source": "ats"},
            "jobs": [{"company": "TestCo", "title": "SWE Intern"}],
            "errors": [],
            "error": None,
            "counts": {"ats": 1, "linkedin": 0, "linkedin_external_ats": 0, "total": 1},
            "scored": False,
        }

        with patch("src.cli.cmd_search.search_jobs_usecase", new=AsyncMock(return_value=payload)):
            result = runner.invoke(cli, ["search", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["protocol_version"] == "1.0"
        assert data["type"] == "autoapply.cli.result"
        assert data["command"] == "search"
        assert data["ok"] is True
        assert data["error"] is None
        assert data["data"]["jobs"][0]["company"] == "TestCo"

    def test_apply_json_output(self, runner):
        from src.cli.main import cli

        payload = {
            "mode": "url",
            "input": {"url": "https://boards.greenhouse.io/test/jobs/123"},
            "ok": True,
            "status": "REVIEW_REQUIRED",
            "job": {"company": "TestCo", "title": "SWE Intern"},
            "tracking_id": None,
            "result": {"status": "REVIEW_REQUIRED", "error": None},
            "artifacts": {"resume_path": None, "cover_letter_path": None, "qa_responses": None},
            "error": None,
            "error_code": None,
            "dry_run": False,
        }

        with patch("src.cli.cmd_apply.apply_to_url_usecase", new=AsyncMock(return_value=payload)):
            result = runner.invoke(
                cli,
                ["apply", "--url", "https://boards.greenhouse.io/test/jobs/123", "--json"],
            )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["protocol_version"] == "1.0"
        assert data["command"] == "apply"
        assert data["ok"] is True
        assert data["data"]["status"] == "REVIEW_REQUIRED"

    def test_status_json_output(self, runner):
        from src.cli.main import cli

        payload = {
            "ok": True,
            "filters": {"company": None, "status": None, "outcome": None, "limit": 20},
            "pipeline_counts": {"SUBMITTED": 1},
            "pipeline_summary": {
                "total_discovered": 1,
                "total_applied": 1,
                "total_failed": 0,
                "total_review": 0,
                "avg_match_score": 0.5,
                "avg_fields_filled_pct": 0.75,
            },
            "outcomes": {
                "total": 1,
                "pending": 1,
                "rejected": 0,
                "oa": 0,
                "interview": 0,
                "offer": 0,
                "rates": {"response_rate": 0.0, "positive_rate": 0.0},
            },
            "companies": [],
            "platforms": {},
            "recent_applications": [],
        }

        with patch("src.cli.cmd_status.load_status_data_usecase", return_value=payload):
            result = runner.invoke(cli, ["status", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["protocol_version"] == "1.0"
        assert data["command"] == "status"
        assert data["ok"] is True
        assert data["data"]["pipeline_summary"]["total_applied"] == 1

    def test_apply_json_error_envelope(self, runner):
        from src.cli.main import cli

        result = runner.invoke(cli, ["apply", "--json"])

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["protocol_version"] == "1.0"
        assert data["command"] == "apply"
        assert data["ok"] is False
        assert data["error"]["code"] == "missing_target"


class TestInitCommand:
    """Test init wizard with skips."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_init_skip_all(self, runner):
        from src.cli.main import cli

        result = runner.invoke(cli, ["init", "--skip-db", "--skip-llm"], input="3\n")
        assert result.exit_code == 0
        assert "[1/4]" in result.output
        assert "[2/4]" in result.output
        assert "skipped" in result.output

    def test_config_step_can_retry_then_succeed(self):
        from src.cli.cmd_init import _run_config_step

        with (
            patch("src.cli.cmd_init._check_config") as mock_check,
            patch("src.cli.cmd_init.click.prompt", side_effect=[1]),
        ):
            mock_check.side_effect = [(False, None), (True, {"database": {}, "logging": {}})]
            ok, config = _run_config_step()

        assert ok is True
        assert config == {"database": {}, "logging": {}}
        assert mock_check.call_count == 2

    def test_database_step_can_continue_without_db(self):
        from src.cli.cmd_init import _run_database_step

        with (
            patch("src.cli.cmd_init._setup_database", return_value=False),
            patch("src.cli.cmd_init.click.prompt", side_effect=[2]),
        ):
            ok = _run_database_step({})

        assert ok is False

    def test_llm_step_can_abort(self):
        from src.cli.cmd_init import _run_llm_step

        with (
            patch("src.cli.cmd_init._check_llm", return_value=False),
            patch("src.cli.cmd_init.click.prompt", side_effect=[3]),
        ):
            with pytest.raises(SystemExit):
                _run_llm_step({})

    def test_normalize_input_path_strips_quotes(self):
        from src.cli.cmd_init import _normalize_input_path

        path = _normalize_input_path('"C:\\Users\\Example\\Documents\\sample_resume.docx"')
        assert path == Path(r"C:\Users\Example\Documents\sample_resume.docx")

    def test_resume_prompt_uses_windows_example(self):
        from src.cli.cmd_init import _resume_path_prompt

        with patch("src.cli.cmd_init._is_windows", return_value=True):
            prompt = _resume_path_prompt()

        assert prompt == r"    Resume file path (C:\Users\Example\Documents\sample_resume.docx)"

    def test_setup_profile_normalizes_quoted_resume_input(self):
        from src.cli.cmd_init import _setup_profile

        with (
            patch("src.cli.cmd_init.PROFILE_FILE") as mock_profile_file,
            patch("src.cli.cmd_init.click.prompt") as mock_prompt,
            patch("src.cli.cmd_init._import_from_resume", return_value=True) as mock_import,
            patch("src.cli.cmd_init._is_windows", return_value=True),
        ):
            mock_profile_file.exists.return_value = False
            mock_prompt.side_effect = [1, '"C:\\Users\\Example\\Documents\\sample_resume.docx"']

            result = _setup_profile(None, None, None, True)

        assert result is True
        assert mock_import.call_args[0][0] == Path(r"C:\Users\Example\Documents\sample_resume.docx")

    def test_init_checks_llm_before_profile(self, runner):
        from src.cli.main import cli

        with (
            patch("src.cli.cmd_init._check_config", return_value=(True, {"llm": {}})),
            patch("src.cli.cmd_init._setup_database", return_value=True),
            patch("src.cli.cmd_init._check_llm", return_value=True),
            patch("src.cli.cmd_init._setup_profile", return_value=True),
        ):
            result = runner.invoke(cli, ["init"])

        assert result.exit_code == 0
        llm_index = result.output.index("[3/4] Checking LLM CLI availability")
        profile_index = result.output.index("[4/4] Setting up applicant profile")
        assert llm_index < profile_index

    def test_import_from_resume_shows_llm_progress(self, tmp_path, capsys):
        from src.cli.cmd_init import _import_from_resume

        resume_path = tmp_path / "sample_resume.docx"
        resume_path.write_text("placeholder", encoding="utf-8")

        with (
            patch(
                "src.utils.llm.get_llm_settings",
                return_value={
                    "primary_provider": "claude-cli",
                    "fallback_provider": "codex-cli",
                    "allow_fallback": True,
                    "timeout": 120,
                },
            ),
            patch(
                "src.memory.resume_importer.import_resume",
                return_value={"identity": {"full_name": "Test User", "email": "test@example.com"}},
            ),
            patch("src.cli.cmd_init.PROFILE_FILE", tmp_path / "profile.yaml"),
        ):
            assert _import_from_resume(resume_path, {"llm": {}}, True) is True

        out = capsys.readouterr().out
        assert "Invoking local LLM CLI" in out
        assert "This can take 10-60 seconds" in out


class TestStatusCommand:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_status_reports_schema_mismatch_cleanly(self, runner):
        from src.cli.main import cli

        with (
            patch(
                "src.cli.cmd_status.load_status_data_usecase",
                return_value={
                    "ok": False,
                    "error": "missing column",
                    "error_code": "schema_out_of_date",
                },
            ),
        ):
            result = runner.invoke(cli, ["status"])

        assert result.exit_code == 1
        assert "Database schema is out of date" in result.output
        assert "uv run alembic upgrade head" in result.output


class TestApplicationUseCases:
    def test_resolve_linkedin_keywords_prefers_keyword_tags(self):
        from src.application.jobs import _resolve_linkedin_keywords

        resolved = _resolve_linkedin_keywords("software engineer", ["software", "backend"])

        assert resolved == ["software", "backend"]

    def test_resolve_linkedin_search_locations_prefers_candidate_locations(self):
        from src.application.jobs import _resolve_linkedin_search_locations

        resolved = _resolve_linkedin_search_locations(
            source="linkedin",
            search_location="california",
            candidate_locations=["california", "new york"],
        )

        assert resolved == ["california", "new york"]

    def test_linkedin_max_pages_does_not_expand_when_search_location_is_used(self):
        from src.application.jobs import _linkedin_max_pages

        max_pages = _linkedin_max_pages(
            5,
            search_location="Vancouver",
            experience_levels=[],
            employment_types=[],
            location_types=[],
            locations=["vancouver"],
            pay_operator=None,
            experience_operator=None,
            education_levels=[],
        )

        assert max_pages == 5

    @pytest.mark.asyncio
    async def test_search_jobs_uses_profile_for_linkedin_source(self):
        from src.application.jobs import search_jobs

        with patch(
            "src.intake.search.search_linkedin", new=AsyncMock(return_value=[])
        ) as mock_search:
            result = await search_jobs(source="linkedin", profile="intern_only", keyword="intern")

        assert result["errors"] == []
        assert mock_search.call_args.kwargs["filter_profile"] == "intern_only"

    @pytest.mark.asyncio
    async def test_search_jobs_sets_auth_error_code_for_linkedin(self):
        from src.application.jobs import search_jobs
        from src.intake.linkedin import LinkedInAuthRequiredError

        with patch(
            "src.intake.search.search_linkedin",
            new=AsyncMock(side_effect=LinkedInAuthRequiredError("login required")),
        ):
            result = await search_jobs(source="linkedin", keyword="intern")

        assert result["error_code"] == "linkedin_auth_required"
        assert "login required" in result["error"]

    @pytest.mark.asyncio
    async def test_apply_to_url_resolves_linkedin_to_external_ats(self):
        from src.application.jobs import apply_to_url

        with (
            patch(
                "src.application.jobs.resolve_manual_apply_url",
                new=AsyncMock(
                    return_value={
                        "ok": True,
                        "url": "https://boards.greenhouse.io/example/jobs/123",
                        "source_url": "https://www.linkedin.com/jobs/view/123",
                        "ats_url": "https://boards.greenhouse.io/example/jobs/123",
                    }
                ),
            ),
            patch("src.application.jobs._load_job_for_application") as mock_load_job,
            patch("src.application.jobs._load_profile", return_value={"identity": {}}),
            patch(
                "src.application.jobs._run_application_for_job",
                new=AsyncMock(return_value={"ok": True, "status": "REVIEW_REQUIRED"}),
            ) as mock_run,
        ):
            mock_load_job.return_value = (
                SimpleNamespace(
                    id=uuid.uuid4(),
                    source="linkedin",
                    source_id="123",
                    company="Example",
                    title="Software Engineer",
                    location="Remote",
                    employment_type="unknown",
                    seniority="unknown",
                    description="Build great things at Example.",
                    application_url="https://boards.greenhouse.io/example/jobs/123",
                    ats_type="greenhouse",
                    raw_data={},
                    discovered_at=None,
                ),
                True,
            )
            await apply_to_url(url="https://www.linkedin.com/jobs/view/123")

        mock_load_job.assert_called_once_with(
            "https://boards.greenhouse.io/example/jobs/123",
            "greenhouse",
        )
        assert mock_run.await_count == 1

    @pytest.mark.asyncio
    async def test_apply_to_url_normalizes_ashby_linkedin_target_to_application_page(self):
        from src.application.jobs import apply_to_url

        with (
            patch(
                "src.application.jobs.resolve_manual_apply_url",
                new=AsyncMock(
                    return_value={
                        "ok": True,
                        "url": "https://jobs.ashbyhq.com/sentry/d2e3391f-9401-410a-b8a6-de3bf5f762b7",
                        "source_url": "https://www.linkedin.com/jobs/view/123",
                        "ats_url": "https://jobs.ashbyhq.com/sentry/d2e3391f-9401-410a-b8a6-de3bf5f762b7",
                    }
                ),
            ),
            patch("src.application.jobs._load_job_for_application") as mock_load_job,
            patch("src.application.jobs._load_profile", return_value={"identity": {}}),
            patch(
                "src.application.jobs._run_application_for_job",
                new=AsyncMock(return_value={"ok": True, "status": "REVIEW_REQUIRED"}),
            ) as mock_run,
        ):
            mock_load_job.return_value = (
                SimpleNamespace(
                    id=uuid.uuid4(),
                    source="linkedin",
                    source_id="123",
                    company="Sentry",
                    title="Software Engineer Intern",
                    location="Toronto",
                    employment_type="internship",
                    seniority="internship",
                    description="Sentry is hiring an intern...",
                    application_url="https://jobs.ashbyhq.com/sentry/d2e3391f-9401-410a-b8a6-de3bf5f762b7/application",
                    ats_type="ashby",
                    raw_data={},
                    discovered_at=None,
                ),
                True,
            )
            await apply_to_url(url="https://www.linkedin.com/jobs/view/123")

        mock_load_job.assert_called_once_with(
            "https://jobs.ashbyhq.com/sentry/d2e3391f-9401-410a-b8a6-de3bf5f762b7/application",
            "ashby",
        )
        assert mock_run.await_count == 1

    @pytest.mark.asyncio
    async def test_apply_to_url_uses_generic_adapter_for_unknown_external_site(self):
        from src.application.jobs import apply_to_url

        with (
            patch("src.application.jobs._load_job_for_application") as mock_load_job,
            patch("src.application.jobs._load_profile", return_value={"identity": {}}),
            patch(
                "src.application.jobs._run_application_for_job",
                new=AsyncMock(return_value={"ok": True, "status": "REVIEW_REQUIRED"}),
            ) as mock_run,
        ):
            mock_load_job.return_value = (
                SimpleNamespace(
                    id=uuid.uuid4(),
                    source="company_site",
                    source_id="123",
                    company="Example",
                    title="Software Engineer",
                    location="Remote",
                    employment_type="unknown",
                    seniority="unknown",
                    description="Build great things at Example.",
                    application_url="https://careers.example.com/jobs/123/apply",
                    ats_type="company_site",
                    raw_data={},
                    discovered_at=None,
                ),
                True,
            )
            await apply_to_url(url="https://careers.example.com/jobs/123/apply")

        mock_load_job.assert_called_once_with(
            "https://careers.example.com/jobs/123/apply",
            "company_site",
        )
        assert mock_run.await_count == 1

    @pytest.mark.asyncio
    async def test_apply_to_url_refuses_company_site_without_real_job_context(self):
        # When _load_job_for_application falls back to a synthesized stub
        # (hydrated=False) for a generic / Workday / Ashby URL we cannot
        # tailor materials, so apply_to_url must refuse rather than run
        # the LLM/template pipeline against a placeholder Job. See codex
        # review of feat/materials-refactor for context.
        from src.application.jobs import apply_to_url

        with (
            patch("src.application.jobs._load_job_for_application") as mock_load_job,
            patch("src.application.jobs._load_profile", return_value={"identity": {}}),
            patch(
                "src.application.jobs._run_application_for_job",
                new=AsyncMock(return_value={"ok": True, "status": "SUBMITTED"}),
            ) as mock_run,
        ):
            mock_load_job.return_value = (
                SimpleNamespace(
                    id=None,
                    source="company_site",
                    source_id="careers.example.com",
                    company="Example",
                    title="Unknown Role",
                    location=None,
                    employment_type="unknown",
                    seniority="unknown",
                    description=None,
                    application_url="https://careers.example.com/apply",
                    ats_type="company_site",
                    raw_data={},
                    discovered_at=None,
                ),
                False,
            )
            result = await apply_to_url(url="https://careers.example.com/apply")

        assert result["ok"] is False
        assert result["error_code"] == "job_context_required"
        assert "stored job" in result["error"]
        mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_apply_to_url_skips_linkedin_easy_apply_without_external_target(self):
        from src.application.jobs import apply_to_url

        with (
            patch(
                "src.application.jobs.resolve_manual_apply_url",
                new=AsyncMock(
                    return_value={
                        "ok": True,
                        "url": "https://www.linkedin.com/jobs/view/123/",
                        "source_url": "https://www.linkedin.com/jobs/view/123/",
                        "ats_url": None,
                    }
                ),
            ),
            patch("src.application.jobs._load_job_for_application") as mock_load_job,
        ):
            result = await apply_to_url(url="https://www.linkedin.com/jobs/view/123/")

        assert result["ok"] is False
        assert result["error_code"] == "unsupported_ats"
        mock_load_job.assert_not_called()

    def test_load_applications_data_uses_filtered_records_for_summaries(self):
        from src.application.tracking import load_applications_data

        app = SimpleNamespace(
            id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            status="SUBMITTED",
            match_score=0.75,
            outcome=None,
            created_at=None,
            updated_at=None,
            submitted_at=None,
            fields_filled=8,
            fields_total=10,
        )
        job = SimpleNamespace(
            id=uuid.uuid4(),
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
            patch("src.application.tracking.load_config", return_value={}),
            patch(
                "src.core.database.get_session_factory",
                return_value=MagicMock(return_value=session_cm),
            ),
            patch(
                "src.tracker.database.get_applications_with_jobs", return_value=[(app, job)]
            ) as mock_query,
        ):
            result = load_applications_data(outcome="pending", limit=20)

        assert result["pipeline"]["SUBMITTED"] == 1
        assert result["outcomes"]["total"] == 1
        assert result["outcomes"]["pending"] == 1
        assert result["applications"][0]["outcome"] == "pending"
        assert mock_query.call_args.kwargs["outcome"] == "pending"
        assert mock_query.call_args.kwargs["limit"] is None

    def test_load_status_data_uses_filtered_records_for_aggregates(self):
        from src.application.tracking import load_status_data

        app = SimpleNamespace(
            id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            status="REVIEW_REQUIRED",
            match_score=0.5,
            outcome=None,
            created_at=None,
            updated_at=None,
            submitted_at=None,
            fields_filled=4,
            fields_total=5,
        )
        job = SimpleNamespace(
            id=uuid.uuid4(),
            company="FilteredCo",
            title="Backend Intern",
            location="Remote",
            application_url="https://example.com/apply",
            ats_type="lever",
        )
        session = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__.return_value = session
        session_cm.__exit__.return_value = None

        with (
            patch("src.application.tracking.load_config", return_value={}),
            patch(
                "src.core.database.get_session_factory",
                return_value=MagicMock(return_value=session_cm),
            ),
            patch(
                "src.tracker.database.get_applications_with_jobs", return_value=[(app, job)]
            ) as mock_query,
        ):
            result = load_status_data(company="FilteredCo", limit=20)

        assert result["ok"] is True
        assert result["pipeline_summary"]["total_discovered"] == 1
        assert result["pipeline_summary"]["total_review"] == 1
        assert result["companies"][0]["company"] == "FilteredCo"
        assert result["platforms"]["lever"]["REVIEW_REQUIRED"] == 1
        assert mock_query.call_args.kwargs["company"] == "FilteredCo"
        assert mock_query.call_args.kwargs["limit"] is None

    @pytest.mark.asyncio
    async def test_search_jobs_applies_extended_filters(self):
        from src.application.jobs import search_jobs
        from src.intake.schema import JobRequirements, RawJob

        matching_job = RawJob(
            source="greenhouse",
            source_id="1",
            company="RemoteCo",
            title="Software Engineer Intern",
            location="New York, United States",
            employment_type="internship",
            description="Remote role with compensation of $120,000 to $140,000.",
            requirements=JobRequirements(education_level="Bachelor's", experience_years_min=1),
            ats_type="greenhouse",
        )
        filtered_out_job = RawJob(
            source="lever",
            source_id="2",
            company="ExecCo",
            title="Director of Engineering",
            location="Toronto, Canada",
            employment_type="fulltime",
            description="On-site role with compensation of $200,000 to $250,000.",
            requirements=JobRequirements(education_level="Master's", experience_years_min=8),
            ats_type="lever",
        )
        matching_job.requirements.remote_ok = True
        filtered_out_job.requirements.remote_ok = False

        with patch(
            "src.intake.search.search_jobs",
            return_value=[matching_job, filtered_out_job],
        ):
            result = await search_jobs(
                source="ats",
                experience_levels=["entry"],
                employment_types=["internship"],
                location_types=["remote"],
                locations=["new york", "united states"],
                pay_operator="gte",
                pay_amount=130000,
                experience_operator="lte",
                experience_years=2,
                education_levels=["bachelor"],
            )

        assert len(result["jobs"]) == 1
        assert result["jobs"][0]["company"] == "RemoteCo"
        assert result["jobs"][0]["location_type"] == "remote"
        assert result["jobs"][0]["pay_min"] == 120000
        assert result["jobs"][0]["pay_max"] == 140000

    def test_employment_category_prefers_explicit_internship_over_temporary_description(self):
        from src.application.jobs import _classify_employment_category
        from src.intake.schema import RawJob

        job = RawJob(
            source="linkedin",
            source_id="1",
            company="Sentry",
            title="Software Engineer, Intern (Fall 2026)",
            location="Toronto, ON (Hybrid)",
            employment_type="internship",
            seniority="internship",
            description=(
                "Temporary relocation support is available for the duration of your "
                "internship."
            ),
            ats_type="linkedin",
        )

        assert _classify_employment_category(job) == "internship"

    def test_employment_category_does_not_infer_internship_from_experience_note(self):
        from src.application.jobs import _classify_employment_category
        from src.intake.schema import RawJob

        job = RawJob(
            source="linkedin",
            source_id="2",
            company="Helic & Co.",
            title="Junior Software Quality Engineer",
            location="Canada (Remote)",
            employment_type="unknown",
            seniority="entry",
            description=(
                "0-2 years of experience in software testing or quality assurance "
                "(internships count)."
            ),
            ats_type="linkedin",
        )

        assert _classify_employment_category(job) == "unknown"

    def test_setup_profile_retries_resume_input_after_failure(self):
        from src.cli.cmd_init import _setup_profile

        with (
            patch("src.cli.cmd_init.PROFILE_FILE") as mock_profile_file,
            patch("src.cli.cmd_init.click.prompt") as mock_prompt,
            patch("src.cli.cmd_init._import_from_resume") as mock_import,
            patch("src.cli.cmd_init._is_windows", return_value=True),
        ):
            mock_profile_file.exists.return_value = False
            mock_prompt.side_effect = [1, r"C:\bad.docx", 1, r"C:\good.docx"]
            mock_import.side_effect = [False, True]

            result = _setup_profile(None, None, None, True)

        assert result is True
        assert mock_import.call_count == 2
        assert mock_import.call_args_list[0][0][0] == Path(r"C:\bad.docx")
        assert mock_import.call_args_list[1][0][0] == Path(r"C:\good.docx")

    def test_setup_profile_can_skip_after_resume_failure(self):
        from src.cli.cmd_init import _setup_profile

        with (
            patch("src.cli.cmd_init.PROFILE_FILE") as mock_profile_file,
            patch("src.cli.cmd_init.click.prompt") as mock_prompt,
            patch("src.cli.cmd_init._import_from_resume", return_value=False),
            patch("src.cli.cmd_init._is_windows", return_value=True),
        ):
            mock_profile_file.exists.return_value = False
            mock_prompt.side_effect = [1, r"C:\bad.docx", 3]

            result = _setup_profile(None, None, None, True)

        assert result is False

    def test_setup_profile_can_switch_to_template_after_resume_failure(self):
        from src.cli.cmd_init import _setup_profile

        with (
            patch("src.cli.cmd_init.PROFILE_FILE") as mock_profile_file,
            patch("src.cli.cmd_init.click.prompt") as mock_prompt,
            patch("src.cli.cmd_init._import_from_resume", return_value=False),
            patch("src.cli.cmd_init._create_template_profile", return_value=True) as mock_template,
            patch("src.cli.cmd_init._is_windows", return_value=True),
        ):
            mock_profile_file.exists.return_value = False
            mock_prompt.side_effect = [1, r"C:\bad.docx", 2]

            result = _setup_profile(None, None, None, True)

        assert result is True
        mock_template.assert_called_once()


# ──────────────────────────────────────────────
# ATS Detection Tests
# ──────────────────────────────────────────────


class TestATSDetection:
    def test_greenhouse_url(self):
        from src.cli.cmd_apply import _detect_ats_from_url

        assert _detect_ats_from_url("https://boards.greenhouse.io/company/jobs/123") == "greenhouse"

    def test_lever_url(self):
        from src.cli.cmd_apply import _detect_ats_from_url

        assert _detect_ats_from_url("https://jobs.lever.co/company/abc123/apply") == "lever"

    def test_unknown_url(self):
        from src.cli.cmd_apply import _detect_ats_from_url

        assert _detect_ats_from_url("https://careers.example.com/apply") == "company_site"

    def test_linkedin_url_is_not_generic_company_site(self):
        from src.cli.cmd_apply import _detect_ats_from_url

        assert _detect_ats_from_url("https://www.linkedin.com/jobs/view/123") is None

    def test_case_insensitive(self):
        from src.cli.cmd_apply import _detect_ats_from_url

        assert _detect_ats_from_url("https://BOARDS.GREENHOUSE.IO/test/jobs/1") == "greenhouse"

    def test_parse_greenhouse_locator(self):
        from src.cli.cmd_apply import _parse_ats_job_locator

        assert _parse_ats_job_locator(
            "https://boards.greenhouse.io/stripe/jobs/123456?gh_jid=123456",
            "greenhouse",
        ) == ("stripe", "123456")

    def test_parse_lever_locator(self):
        from src.cli.cmd_apply import _parse_ats_job_locator

        assert _parse_ats_job_locator(
            "https://jobs.lever.co/vercel/abc123/apply",
            "lever",
        ) == ("vercel", "abc123")


class TestMaterialGeneration:
    @pytest.mark.asyncio
    async def test_generate_materials_uses_job_specific_generators(self):
        from pathlib import Path

        from src.cli.cmd_apply import _generate_materials
        from src.intake.schema import RawJob

        job = RawJob(
            source="greenhouse",
            source_id="123",
            company="TestCo",
            title="SWE Intern",
            ats_type="greenhouse",
            application_url="https://boards.greenhouse.io/testco/jobs/123",
        )
        profile_data = {
            "identity": {"full_name": "Test User"},
            "education": [],
            "work_experiences": [],
            "projects": [],
            "skills": {},
            "qa_bank": [
                {
                    "question_pattern": "Are you legally authorized to work?",
                    "question_type": "authorization",
                    "canonical_answer": "Yes",
                }
            ],
        }

        with (
            patch("src.generation.resume_builder.generate_resume") as mock_resume,
            patch("src.generation.cover_letter.generate_cover_letter") as mock_cover,
            patch("src.generation.qa_responder.answer_questions") as mock_answers,
        ):
            mock_resume.return_value = {"pdf": Path("data/output/resume_testco_swe_intern.pdf")}
            mock_cover.return_value = {"txt": Path("data/output/cover_testco_swe_intern.txt")}
            mock_answers.return_value = [
                SimpleNamespace(
                    question="Are you legally authorized to work?",
                    answer="Yes",
                )
            ]

            resume_path, cover_path, qa_responses = await _generate_materials(profile_data, job)

        assert resume_path == Path("data/output/resume_testco_swe_intern.pdf")
        assert cover_path == Path("data/output/cover_testco_swe_intern.txt")
        assert qa_responses == {"Are you legally authorized to work?": "Yes"}
        mock_resume.assert_called_once()
        mock_cover.assert_called_once()
        mock_answers.assert_called_once()


# ──────────────────────────────────────────────
# Tracker Database Unit Tests (mocked session)
# ──────────────────────────────────────────────


class TestTrackerDatabase:
    """Test tracker operations with mocked DB session."""

    def test_create_application(self):
        from src.tracker.database import create_application

        session = MagicMock()
        job_id = uuid.uuid4()
        create_application(session, job_id, match_score=0.85)

        session.add.assert_called_once()
        session.flush.assert_called_once()
        added_app = session.add.call_args[0][0]
        assert added_app.job_id == job_id
        assert added_app.match_score == 0.85
        assert added_app.status == "DISCOVERED"

    def test_sync_state_to_db(self):
        from src.tracker.database import sync_state_to_db

        app_id = uuid.uuid4()
        mock_app = MagicMock()
        mock_app.submitted_at = None
        session = MagicMock()
        session.get.return_value = mock_app

        state = ApplicationState("test-job")
        state.transition(AppStatus.QUALIFIED)
        state.transition(AppStatus.MATERIALS_READY)
        state.transition(AppStatus.FORM_OPENED)
        state.fail("timeout error")

        result_data = {
            "fields_filled": 5,
            "fields_total": 8,
            "files_uploaded": ["resume.pdf"],
        }

        sync_state_to_db(session, app_id, state, result_data)

        assert mock_app.status == "FAILED"
        assert mock_app.fields_filled == 5
        assert mock_app.fields_total == 8
        assert mock_app.files_uploaded == ["resume.pdf"]
        assert mock_app.error_log == "timeout error"
        session.flush.assert_called_once()

    def test_sync_state_not_found(self):
        from src.tracker.database import sync_state_to_db

        session = MagicMock()
        session.get.return_value = None
        state = ApplicationState("test")

        with pytest.raises(ValueError, match="not found"):
            sync_state_to_db(session, uuid.uuid4(), state)

    def test_update_outcome_valid(self):
        from src.tracker.database import update_outcome

        mock_app = MagicMock()
        session = MagicMock()
        session.get.return_value = mock_app

        update_outcome(session, uuid.uuid4(), "interview")

        assert mock_app.outcome == "interview"
        assert mock_app.outcome_updated_at is not None
        session.flush.assert_called_once()

    def test_update_outcome_invalid(self):
        from src.tracker.database import update_outcome

        session = MagicMock()
        session.get.return_value = MagicMock()

        with pytest.raises(ValueError, match="Invalid outcome"):
            update_outcome(session, uuid.uuid4(), "magic")

    def test_get_applications_with_jobs_treats_pending_as_null(self):
        from src.tracker.database import get_applications_with_jobs

        session = MagicMock()
        execute_result = MagicMock()
        execute_result.all.return_value = []
        session.execute.return_value = execute_result

        get_applications_with_jobs(session, outcome="pending", limit=None)

        stmt = session.execute.call_args[0][0]
        assert "IS NULL" in str(stmt)


# ──────────────────────────────────────────────
# Analytics Unit Tests
# ──────────────────────────────────────────────


class TestOutcomeStats:
    def test_rates_empty(self):
        from src.tracker.analytics import OutcomeStats

        stats = OutcomeStats()
        assert stats.response_rate == 0.0
        assert stats.positive_rate == 0.0

    def test_response_rate(self):
        from src.tracker.analytics import OutcomeStats

        stats = OutcomeStats(
            total_submitted=10,
            pending=4,
            rejected=3,
            oa=1,
            interview=1,
            offer=1,
        )
        # 6 responded out of 10
        assert stats.response_rate == 0.6
        # 3 positive out of 10
        assert stats.positive_rate == 0.3

    def test_all_pending(self):
        from src.tracker.analytics import OutcomeStats

        stats = OutcomeStats(total_submitted=5, pending=5)
        assert stats.response_rate == 0.0
        assert stats.positive_rate == 0.0


# ──────────────────────────────────────────────
# Export Tests
# ──────────────────────────────────────────────


class TestFormatReport:
    def test_format_basic_report(self):
        from src.tracker.analytics import CompanyStats, OutcomeStats, PipelineStats
        from src.tracker.export import format_status_report

        pipeline = PipelineStats(
            total_discovered=50,
            total_applied=10,
            total_failed=3,
            total_review=2,
            avg_match_score=0.72,
        )
        outcomes = OutcomeStats(
            total_submitted=10,
            pending=5,
            rejected=3,
            interview=2,
        )
        companies = [
            CompanyStats(
                company="Google",
                applications=5,
                submitted=3,
                avg_match_score=0.8,
                outcomes={"interview": 1, "rejected": 1},
            ),
        ]
        platforms = {"greenhouse": {"SUBMITTED": 6, "FAILED": 2}, "lever": {"SUBMITTED": 4}}

        report = format_status_report(pipeline, outcomes, companies, platforms)

        assert "Pipeline Overview" in report
        assert "50" in report  # total discovered
        assert "10" in report  # applied
        assert "Outcomes" in report
        assert "Response rate" in report
        assert "By Platform" in report
        assert "greenhouse" in report
        assert "Top Companies" in report
        assert "Google" in report

    def test_format_empty_report(self):
        from src.tracker.analytics import OutcomeStats, PipelineStats
        from src.tracker.export import format_status_report

        report = format_status_report(PipelineStats(), OutcomeStats(), [], {})
        assert "Pipeline Overview" in report
        assert "0" in report
