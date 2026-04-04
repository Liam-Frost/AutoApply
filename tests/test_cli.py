"""Tests for Phase 5: CLI, tracking, and analytics.

Tests CLI command structure, tracker database operations, analytics
computations, and export functionality. Uses in-memory mocks where
DB is not available.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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

    def test_apply_help(self, runner):
        from src.cli.main import cli

        result = runner.invoke(cli, ["apply", "--help"])
        assert result.exit_code == 0
        assert "--url" in result.output
        assert "--batch" in result.output
        assert "--auto-submit" in result.output
        assert "--dry-run" in result.output

    def test_status_help(self, runner):
        from src.cli.main import cli

        result = runner.invoke(cli, ["status", "--help"])
        assert result.exit_code == 0
        assert "--export-csv" in result.output
        assert "--company" in result.output
        assert "--outcome" in result.output

    def test_apply_requires_target(self, runner):
        from src.cli.main import cli

        result = runner.invoke(cli, ["apply"])
        assert result.exit_code != 0
        assert "Specify --url" in result.output


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

        assert _detect_ats_from_url("https://careers.example.com/apply") is None

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
