"""Tests for Phase 4: Execution layer.

Covers state machine, form filler mapping, rate limiter, and ATS adapters.
Browser/Playwright interactions are tested with lightweight mocks since
they require a running browser.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.state_machine import ApplicationState, AppStatus, InvalidTransitionError
from src.execution.form_filler import (
    FormField,
    map_fields_to_profile,
)
from src.utils.rate_limiter import RateLimiter, RateLimiterConfig

# ──────────────────────────────────────────────
# State Machine Tests
# ──────────────────────────────────────────────


class TestAppStatus:
    """AppStatus enum tests."""

    def test_all_statuses_defined(self):
        expected = {
            "DISCOVERED",
            "QUALIFIED",
            "MATERIALS_READY",
            "FORM_OPENED",
            "FIELDS_MAPPED",
            "FILES_UPLOADED",
            "QUESTIONS_ANSWERED",
            "REVIEW_REQUIRED",
            "SUBMITTED",
            "FAILED",
            "NEEDS_RETRY",
        }
        assert {s.value for s in AppStatus} == expected

    def test_str_enum(self):
        assert str(AppStatus.DISCOVERED) == "DISCOVERED"
        assert AppStatus.SUBMITTED == "SUBMITTED"


class TestApplicationState:
    """State machine transition tests."""

    def test_initial_state(self):
        state = ApplicationState("job-123")
        assert state.status == AppStatus.DISCOVERED
        assert state.job_id == "job-123"
        assert len(state.history) == 1  # INIT event
        assert state.history[0]["event"] == "INIT"

    def test_happy_path_full_cycle(self):
        """Test the complete forward path through all states."""
        state = ApplicationState("job-001")
        transitions = [
            AppStatus.QUALIFIED,
            AppStatus.MATERIALS_READY,
            AppStatus.FORM_OPENED,
            AppStatus.FIELDS_MAPPED,
            AppStatus.FILES_UPLOADED,
            AppStatus.QUESTIONS_ANSWERED,
            AppStatus.REVIEW_REQUIRED,
            AppStatus.SUBMITTED,
        ]
        for target in transitions:
            state.transition(target)
        assert state.status == AppStatus.SUBMITTED
        assert state.is_terminal
        assert not state.is_active
        # INIT + 8 transitions
        assert len(state.history) == 9

    def test_auto_submit_path(self):
        """QUESTIONS_ANSWERED can go directly to SUBMITTED."""
        state = ApplicationState("job-002")
        for s in [
            AppStatus.QUALIFIED,
            AppStatus.MATERIALS_READY,
            AppStatus.FORM_OPENED,
            AppStatus.FIELDS_MAPPED,
            AppStatus.FILES_UPLOADED,
            AppStatus.QUESTIONS_ANSWERED,
        ]:
            state.transition(s)
        state.transition(AppStatus.SUBMITTED)
        assert state.status == AppStatus.SUBMITTED

    def test_invalid_skip_transition(self):
        """Cannot skip states."""
        state = ApplicationState("job-003")
        with pytest.raises(InvalidTransitionError):
            state.transition(AppStatus.FORM_OPENED)

    def test_invalid_backward_transition(self):
        """Cannot go backward."""
        state = ApplicationState("job-004")
        state.transition(AppStatus.QUALIFIED)
        with pytest.raises(InvalidTransitionError):
            state.transition(AppStatus.DISCOVERED)

    def test_terminal_state_no_transition(self):
        """Cannot transition from terminal states."""
        state = ApplicationState("job-005")
        state.fail("test error")
        assert state.is_terminal
        with pytest.raises(InvalidTransitionError):
            state.transition(AppStatus.QUALIFIED)

    def test_fail_from_any_active_state(self):
        """FAILED is reachable from any non-terminal state."""
        for start in [
            AppStatus.DISCOVERED,
            AppStatus.QUALIFIED,
            AppStatus.MATERIALS_READY,
            AppStatus.FORM_OPENED,
            AppStatus.FIELDS_MAPPED,
            AppStatus.FILES_UPLOADED,
            AppStatus.QUESTIONS_ANSWERED,
            AppStatus.REVIEW_REQUIRED,
        ]:
            state = ApplicationState("job-fail")
            state.status = start  # Force state for testing
            state.fail("some error")
            assert state.status == AppStatus.FAILED

    def test_retry_from_active_state(self):
        """NEEDS_RETRY is reachable from any non-terminal state."""
        state = ApplicationState("job-retry")
        state.transition(AppStatus.QUALIFIED)
        state.transition(AppStatus.MATERIALS_READY)
        state.transition(AppStatus.FORM_OPENED)
        state.retry("timeout")
        assert state.status == AppStatus.NEEDS_RETRY

    def test_retry_then_resume(self):
        """NEEDS_RETRY can resume to FORM_OPENED or MATERIALS_READY."""
        state = ApplicationState("job-resume")
        state.transition(AppStatus.QUALIFIED)
        state.transition(AppStatus.MATERIALS_READY)
        state.transition(AppStatus.FORM_OPENED)
        state.retry("error")
        state.transition(AppStatus.FORM_OPENED)
        assert state.status == AppStatus.FORM_OPENED

    def test_metadata_on_transition(self):
        state = ApplicationState("job-meta")
        state.transition(AppStatus.QUALIFIED, match_score=0.85)
        assert state.metadata["match_score"] == 0.85
        last_event = state.history[-1]
        assert last_event["meta"]["match_score"] == 0.85

    def test_can_transition(self):
        state = ApplicationState("job-can")
        assert state.can_transition(AppStatus.QUALIFIED)
        assert not state.can_transition(AppStatus.SUBMITTED)
        assert state.can_transition(AppStatus.FAILED)  # error always ok

    def test_to_dict(self):
        state = ApplicationState("job-dict")
        state.transition(AppStatus.QUALIFIED)
        d = state.to_dict()
        assert d["job_id"] == "job-dict"
        assert d["status"] == "QUALIFIED"
        assert isinstance(d["history"], list)
        assert isinstance(d["metadata"], dict)


# ──────────────────────────────────────────────
# Form Filler Mapping Tests
# ──────────────────────────────────────────────


class TestMapFieldsToProfile:
    """Tests for field-to-profile mapping logic."""

    @pytest.fixture
    def profile_data(self):
        return {
            "identity": {
                "full_name": "John Doe",
                "email": "john@example.com",
                "phone": "+1-555-0100",
                "linkedin_url": "https://linkedin.com/in/johndoe",
                "github_url": "https://github.com/johndoe",
                "portfolio_url": "https://johndoe.dev",
                "location": "Vancouver, BC",
            },
            "education": [
                {
                    "institution": "UBC",
                    "degree": "BSc Computer Science",
                    "field": "Computer Science",
                    "gpa": "3.8",
                }
            ],
        }

    def _make_field(self, label: str, field_type: str = "text") -> FormField:
        return FormField(selector=f"#{label.replace(' ', '_')}", label=label, field_type=field_type)

    def test_name_fields(self, profile_data):
        fields = [
            self._make_field("First Name"),
            self._make_field("Last Name"),
        ]
        mappings = map_fields_to_profile(fields, profile_data)
        assert mappings[0].value == "John"
        assert mappings[1].value == "Doe"

    def test_full_name(self, profile_data):
        fields = [self._make_field("Full Name")]
        mappings = map_fields_to_profile(fields, profile_data)
        assert mappings[0].value == "John Doe"

    def test_email(self, profile_data):
        fields = [self._make_field("Email Address")]
        mappings = map_fields_to_profile(fields, profile_data)
        assert mappings[0].value == "john@example.com"

    def test_phone(self, profile_data):
        fields = [self._make_field("Phone Number")]
        mappings = map_fields_to_profile(fields, profile_data)
        assert mappings[0].value == "+1-555-0100"

    def test_linkedin(self, profile_data):
        fields = [self._make_field("LinkedIn Profile")]
        mappings = map_fields_to_profile(fields, profile_data)
        assert mappings[0].value == "https://linkedin.com/in/johndoe"

    def test_github(self, profile_data):
        fields = [self._make_field("GitHub URL")]
        mappings = map_fields_to_profile(fields, profile_data)
        assert mappings[0].value == "https://github.com/johndoe"

    def test_portfolio(self, profile_data):
        fields = [self._make_field("Portfolio website")]
        mappings = map_fields_to_profile(fields, profile_data)
        assert mappings[0].value == "https://johndoe.dev"

    def test_location(self, profile_data):
        fields = [self._make_field("City / Location")]
        mappings = map_fields_to_profile(fields, profile_data)
        assert mappings[0].value == "Vancouver, BC"

    def test_education_fields(self, profile_data):
        fields = [
            self._make_field("University"),
            self._make_field("Degree"),
            self._make_field("Major / Field of Study"),
            self._make_field("GPA"),
        ]
        mappings = map_fields_to_profile(fields, profile_data)
        assert mappings[0].value == "UBC"
        assert mappings[1].value == "BSc Computer Science"
        assert mappings[2].value == "Computer Science"
        assert mappings[3].value == "3.8"

    def test_file_fields_skipped(self, profile_data):
        fields = [
            self._make_field("Resume", field_type="file"),
            self._make_field("Email"),
        ]
        mappings = map_fields_to_profile(fields, profile_data)
        assert len(mappings) == 1  # file field excluded
        assert mappings[0].value == "john@example.com"

    def test_qa_responses_fallback(self, profile_data):
        fields = [self._make_field("Are you authorized to work in Canada?")]
        qa = {"Are you authorized to work in Canada?": "Yes"}
        mappings = map_fields_to_profile(fields, profile_data, qa)
        assert mappings[0].value == "Yes"

    def test_unmatched_field_empty_value(self, profile_data):
        fields = [self._make_field("Favorite Color")]
        mappings = map_fields_to_profile(fields, profile_data)
        assert mappings[0].value == ""

    def test_empty_profile(self):
        fields = [self._make_field("Email")]
        mappings = map_fields_to_profile(fields, {})
        assert mappings[0].value == ""

    def test_no_education(self):
        fields = [self._make_field("University")]
        mappings = map_fields_to_profile(fields, {"identity": {}, "education": []})
        assert mappings[0].value == ""


# ──────────────────────────────────────────────
# Rate Limiter Tests
# ──────────────────────────────────────────────


class TestRateLimiterConfig:
    def test_defaults(self):
        cfg = RateLimiterConfig()
        assert cfg.min_delay == 3.0
        assert cfg.max_delay == 8.0
        assert cfg.cooldown_on_error == 60.0
        assert cfg.max_applications_per_hour == 15

    def test_custom(self):
        cfg = RateLimiterConfig(min_delay=1, max_delay=2, max_applications_per_hour=5)
        assert cfg.min_delay == 1
        assert cfg.max_applications_per_hour == 5


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_can_apply_initially(self):
        limiter = RateLimiter(RateLimiterConfig(max_applications_per_hour=3))
        assert await limiter.can_apply()
        assert limiter.remaining_this_hour == 3
        assert limiter.applications_this_hour == 0

    @pytest.mark.asyncio
    async def test_record_application_counts(self):
        limiter = RateLimiter(RateLimiterConfig(max_applications_per_hour=2))
        await limiter.record_application()
        assert limiter.applications_this_hour == 1
        assert limiter.remaining_this_hour == 1
        await limiter.record_application()
        assert not await limiter.can_apply()
        assert limiter.remaining_this_hour == 0

    @pytest.mark.asyncio
    async def test_old_timestamps_pruned(self):
        limiter = RateLimiter(RateLimiterConfig(max_applications_per_hour=1))
        # Simulate an old application (> 1 hour ago)
        limiter._application_timestamps = [time.monotonic() - 3700]
        assert await limiter.can_apply()

    @pytest.mark.asyncio
    async def test_wait_returns_delay(self):
        limiter = RateLimiter(RateLimiterConfig(min_delay=0.01, max_delay=0.02))
        delay = await limiter.wait()
        assert delay >= 0  # Could be 0 if enough time passed

    @pytest.mark.asyncio
    async def test_error_cooldown(self):
        from unittest.mock import AsyncMock, patch

        limiter = RateLimiter(RateLimiterConfig(cooldown_on_error=0.01))
        with patch("src.utils.rate_limiter.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await limiter.error_cooldown()

        mock_sleep.assert_awaited_once_with(0.01)


# ──────────────────────────────────────────────
# ATS Adapter Structure Tests
# ──────────────────────────────────────────────


class TestBaseATSAdapter:
    """Test adapter interface and result dataclass."""

    def test_application_result_defaults(self):
        from src.execution.ats.base import ApplicationResult

        result = ApplicationResult(job_id="j1", status=AppStatus.REVIEW_REQUIRED)
        assert result.fields_filled == 0
        assert result.files_uploaded == []
        assert result.error == ""

    def test_adapter_is_abstract(self):
        from src.execution.ats.base import BaseATSAdapter

        with pytest.raises(TypeError):
            BaseATSAdapter(browser=MagicMock())

    def test_greenhouse_adapter_ats_name(self):
        from src.execution.ats.greenhouse import GreenhouseAdapter

        adapter = GreenhouseAdapter(browser=MagicMock())
        assert adapter.ats_name == "greenhouse"

    def test_lever_adapter_ats_name(self):
        from src.execution.ats.lever import LeverAdapter

        adapter = LeverAdapter(browser=MagicMock())
        assert adapter.ats_name == "lever"


class TestATSApplyWorkflow:
    """Test the base apply() orchestration with mocked page interactions."""

    @pytest.fixture
    def mock_browser(self):
        bm = MagicMock()
        bm.goto = AsyncMock()
        bm.delay = AsyncMock()
        bm.screenshot = AsyncMock(return_value="screenshot.png")
        return bm

    @pytest.mark.asyncio
    async def test_apply_happy_path(self, mock_browser):
        from src.execution.ats.greenhouse import GreenhouseAdapter

        adapter = GreenhouseAdapter(browser=mock_browser)
        page = AsyncMock()
        page.wait_for_selector = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[])
        page.locator = MagicMock()
        page.locator.return_value.first = AsyncMock()
        page.locator.return_value.first.click = AsyncMock()

        state = ApplicationState("test-job-001")
        # Advance to MATERIALS_READY (pre-condition for apply)
        state.transition(AppStatus.QUALIFIED)
        state.transition(AppStatus.MATERIALS_READY)

        with (
            patch(
                "src.execution.ats.greenhouse.detect_fields",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("src.execution.ats.greenhouse.map_fields_to_profile", return_value=[]),
            patch(
                "src.execution.ats.greenhouse.fill_fields", new_callable=AsyncMock, return_value=[]
            ),
            patch(
                "src.execution.ats.greenhouse.upload_resume",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "src.execution.ats.greenhouse.upload_cover_letter",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await adapter.apply(
                page=page,
                application_url="https://boards.greenhouse.io/test/jobs/123",
                state=state,
                profile_data={"identity": {}},
                auto_submit=False,
            )

        assert result.status == AppStatus.REVIEW_REQUIRED
        assert state.status == AppStatus.REVIEW_REQUIRED

    @pytest.mark.asyncio
    async def test_apply_auto_submit(self, mock_browser):
        from src.execution.ats.lever import LeverAdapter

        adapter = LeverAdapter(browser=mock_browser)
        page = AsyncMock()
        page.wait_for_selector = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[])

        # Setup locator mock: submit button click + error indicator check
        submit_first = AsyncMock()
        submit_first.click = AsyncMock()
        error_first = AsyncMock()
        error_first.is_visible = AsyncMock(return_value=False)  # No error

        def locator_side_effect(selector):
            mock = MagicMock()
            if "error" in selector or "alert" in selector:
                mock.first = error_first
            else:
                mock.first = submit_first
            return mock

        page.locator = MagicMock(side_effect=locator_side_effect)

        state = ApplicationState("test-job-002")
        state.transition(AppStatus.QUALIFIED)
        state.transition(AppStatus.MATERIALS_READY)

        with (
            patch("src.execution.ats.lever.detect_fields", new_callable=AsyncMock, return_value=[]),
            patch("src.execution.ats.lever.map_fields_to_profile", return_value=[]),
            patch("src.execution.ats.lever.fill_fields", new_callable=AsyncMock, return_value=[]),
            patch(
                "src.execution.ats.lever.upload_resume", new_callable=AsyncMock, return_value=False
            ),
            patch(
                "src.execution.ats.lever.upload_cover_letter",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await adapter.apply(
                page=page,
                application_url="https://jobs.lever.co/test/123/apply",
                state=state,
                profile_data={"identity": {}},
                auto_submit=True,
            )

        assert result.status == AppStatus.SUBMITTED
        assert state.status == AppStatus.SUBMITTED

    @pytest.mark.asyncio
    async def test_apply_failure_captured(self, mock_browser):
        from src.execution.ats.greenhouse import GreenhouseAdapter

        mock_browser.goto = AsyncMock(side_effect=TimeoutError("page timeout"))
        adapter = GreenhouseAdapter(browser=mock_browser)
        page = AsyncMock()

        state = ApplicationState("test-job-003")
        state.transition(AppStatus.QUALIFIED)
        state.transition(AppStatus.MATERIALS_READY)

        result = await adapter.apply(
            page=page,
            application_url="https://boards.greenhouse.io/test/jobs/456",
            state=state,
            profile_data={"identity": {}},
        )

        assert result.status == AppStatus.FAILED
        assert "TimeoutError" in result.error
        assert state.status == AppStatus.FAILED


# ──────────────────────────────────────────────
# Package init tests
# ──────────────────────────────────────────────


class TestPackageExports:
    def test_ats_package_exports(self):
        from src.execution.ats import (
            ApplicationResult,
            BaseATSAdapter,
            GreenhouseAdapter,
            LeverAdapter,
        )

        assert ApplicationResult is not None
        assert BaseATSAdapter is not None
        assert GreenhouseAdapter is not None
        assert LeverAdapter is not None
