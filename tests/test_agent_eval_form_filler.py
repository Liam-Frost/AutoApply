"""Tests for the Phase 9.3 form_filler eval suite + scorers.

Exercises:

* the new ``field_mapping_match`` and ``no_proposal_for_label`` scorers,
* the ``_form_filler_runner`` end-to-end on the bundled fixtures,
* CLI integration via ``autoapply eval --suite form_filler``.

The fixtures themselves act as their own integration tests; we add a
``test_baseline_pass_rate`` to pin behaviour so a future regression in
the parser or scoring shows up loudly in CI.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from src.agent.eval.runner import list_suites, run_suite
from src.agent.eval.scorers import (
    SCORERS,
    score_expectations,
)
from src.core.config import PROJECT_ROOT

# ---------------------------------------------------------------------------
# Scorer unit tests
# ---------------------------------------------------------------------------


class TestFieldMappingMatchScorer:
    def test_pass_on_full_match(self) -> None:
        output = json.dumps(
            {
                "proposals": [
                    {"field_label": "Email", "value": "a@b"},
                    {"field_label": "Name", "value": "Liam"},
                ]
            }
        )
        results = score_expectations(
            output,
            [
                {
                    "type": "field_mapping_match",
                    "expected": {"Email": "a@b", "Name": "Liam"},
                }
            ],
        )
        assert results[0].passed
        assert "2/2" in results[0].detail

    def test_substring_match_is_default(self) -> None:
        output = json.dumps(
            {
                "proposals": [
                    {
                        "field_label": "School",
                        "value": "University of British Columbia",
                    }
                ]
            }
        )
        results = score_expectations(
            output,
            [
                {
                    "type": "field_mapping_match",
                    "expected": {"School": "british columbia"},
                }
            ],
        )
        assert results[0].passed

    def test_exact_mode_is_strict(self) -> None:
        output = json.dumps(
            {"proposals": [{"field_label": "X", "value": "Yes"}]}
        )
        results = score_expectations(
            output,
            [
                {
                    "type": "field_mapping_match",
                    "expected": {"X": "yes"},
                    "exact": True,
                }
            ],
        )
        assert not results[0].passed

    def test_partial_match_with_min_rate(self) -> None:
        output = json.dumps(
            {
                "proposals": [
                    {"field_label": "Email", "value": "a@b"},
                    {"field_label": "Name", "value": "wrong"},
                ]
            }
        )
        results = score_expectations(
            output,
            [
                {
                    "type": "field_mapping_match",
                    "expected": {"Email": "a@b", "Name": "Liam"},
                    "min_match_rate": 0.5,
                }
            ],
        )
        assert results[0].passed

    def test_fail_when_proposals_missing(self) -> None:
        results = score_expectations(
            "{\"foo\": []}",
            [{"type": "field_mapping_match", "expected": {"X": "y"}}],
        )
        assert not results[0].passed
        assert "proposals" in results[0].detail

    def test_fail_when_output_not_json(self) -> None:
        results = score_expectations(
            "not json at all",
            [{"type": "field_mapping_match", "expected": {"X": "y"}}],
        )
        assert not results[0].passed

    def test_extracts_json_from_noisy_output(self) -> None:
        output = "INFO: starting\n{\"proposals\":[{\"field_label\":\"E\",\"value\":\"v\"}]}\nEND"
        results = score_expectations(
            output,
            [{"type": "field_mapping_match", "expected": {"E": "v"}}],
        )
        assert results[0].passed


class TestNoProposalForLabelScorer:
    def test_pass_when_label_absent(self) -> None:
        out = json.dumps({"proposals": [{"field_label": "Email", "value": "x"}]})
        results = score_expectations(
            out, [{"type": "no_proposal_for_label", "label": "Resume"}]
        )
        assert results[0].passed

    def test_fail_when_label_present(self) -> None:
        out = json.dumps(
            {"proposals": [{"field_label": "Resume", "value": "/r.pdf"}]}
        )
        results = score_expectations(
            out, [{"type": "no_proposal_for_label", "label": "Resume"}]
        )
        assert not results[0].passed
        assert "Resume" in results[0].detail


class TestRegistry:
    def test_new_scorers_registered(self) -> None:
        assert "field_mapping_match" in SCORERS
        assert "no_proposal_for_label" in SCORERS


# ---------------------------------------------------------------------------
# Suite-level
# ---------------------------------------------------------------------------


class TestFormFillerSuite:
    def test_suite_listed(self) -> None:
        assert "form_filler" in list_suites()

    def test_full_suite_passes(self) -> None:
        report = run_suite("form_filler")
        assert report.total == 5
        assert report.pass_rate == 1.0, [
            (c.case_id, c.error, [(e.type, e.passed, e.detail) for e in c.expectations])
            for c in report.cases
            if not c.passed
        ]

    def test_baseline_locked(self) -> None:
        baseline_path = (
            PROJECT_ROOT
            / "tests"
            / "agent_evals"
            / "baselines"
            / "form_filler.json"
        )
        assert baseline_path.exists(), "baseline JSON should be tracked in git"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        assert baseline["suite"] == "form_filler"
        # If we ever drop a fixture, force the dev to update the baseline.
        report = run_suite("form_filler")
        baseline_ids = {c["id"] for c in baseline["cases"]}
        actual_ids = {c.case_id for c in report.cases}
        assert baseline_ids == actual_ids, (
            f"baseline drifted from fixtures (baseline={baseline_ids} actual={actual_ids})"
        )


class TestCLIIntegration:
    def test_cli_runs_form_filler_suite(self, tmp_path: Path) -> None:
        # We invoke the CLI module directly as a subprocess so we exercise
        # the registered command rather than its internals.
        result = subprocess.run(
            [
                str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"),
                "-m",
                "src.cli.main",
                "eval",
                "--suite",
                "form_filler",
                "--min-pass-rate",
                "0.85",
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        # Either exit 0 (passed >= threshold) or 2 (CLI usage); never crash.
        assert result.returncode == 0, result.stderr
        assert "form_filler" in result.stdout
        assert "PASS" in result.stdout
