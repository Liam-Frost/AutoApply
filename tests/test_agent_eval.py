"""Tests for the Phase 8.4 eval harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from src.agent.eval.runner import (
    EvalCase,
    list_suites,
    load_cases,
    run_eval,
    run_suite,
)
from src.agent.eval.scorers import score_expectations
from src.cli.cmd_eval import eval_cmd


class TestScorers:
    def test_contains_all_pass_and_fail(self):
        ok = score_expectations(
            "hello world",
            [{"type": "contains_all", "values": ["hello", "world"]}],
        )
        assert ok[0].passed
        bad = score_expectations(
            "hello", [{"type": "contains_all", "values": ["hello", "world"]}]
        )
        assert not bad[0].passed
        assert "missing" in bad[0].detail

    def test_contains_any(self):
        ok = score_expectations("a", [{"type": "contains_any", "values": ["x", "a"]}])
        assert ok[0].passed
        bad = score_expectations("a", [{"type": "contains_any", "values": ["x", "y"]}])
        assert not bad[0].passed

    def test_equals_strips_by_default(self):
        ok = score_expectations(" hi  ", [{"type": "equals", "value": "hi"}])
        assert ok[0].passed

    def test_equals_can_disable_strip(self):
        bad = score_expectations(
            " hi ", [{"type": "equals", "value": "hi", "strip": False}]
        )
        assert not bad[0].passed

    def test_regex(self):
        ok = score_expectations("step 42 done", [{"type": "regex", "pattern": r"\d+"}])
        assert ok[0].passed
        bad = score_expectations("nothing", [{"type": "regex", "pattern": r"\d+"}])
        assert not bad[0].passed

    def test_length_between(self):
        ok = score_expectations(
            "one two three",
            [{"type": "length_between", "unit": "words", "min": 2, "max": 5}],
        )
        assert ok[0].passed
        bad = score_expectations(
            "one",
            [{"type": "length_between", "unit": "words", "min": 2, "max": 5}],
        )
        assert not bad[0].passed

    def test_unknown_scorer_records_failure(self):
        results = score_expectations("x", [{"type": "made_up"}])
        assert not results[0].passed
        assert "unknown scorer" in results[0].detail


class TestEvalRunner:
    def _case(self, expectations):
        return EvalCase(
            id="c1", description="", input={"text": "hello"}, expectations=expectations
        )

    def test_passes_when_all_expectations_pass(self):
        case = self._case([{"type": "contains_all", "values": ["hello"]}])
        report = run_eval("toy", [case], lambda inp: inp["text"])
        assert report.passed_count == 1
        assert report.pass_rate == 1.0

    def test_fails_when_any_expectation_fails(self):
        case = self._case(
            [
                {"type": "contains_all", "values": ["hello"]},
                {"type": "regex", "pattern": r"\d+"},
            ]
        )
        report = run_eval("toy", [case], lambda inp: inp["text"])
        assert report.passed_count == 0

    def test_runner_exception_records_error(self):
        case = self._case([{"type": "equals", "value": "x"}])

        def boom(_inp):
            raise RuntimeError("kaboom")

        report = run_eval("toy", [case], boom)
        assert report.passed_count == 0
        assert "kaboom" in (report.cases[0].error or "")

    def test_no_expectations_means_fail(self):
        case = self._case([])
        report = run_eval("toy", [case], lambda inp: inp["text"])
        assert not report.cases[0].passed


class TestSuites:
    def test_smoke_suite_listed(self):
        assert "agent_smoke" in list_suites()

    def test_run_smoke_suite_all_pass(self):
        report = run_suite("agent_smoke")
        assert report.total == 3
        assert report.passed_count == 3, [
            (c.case_id, [e.to_dict() for e in c.expectations], c.error)
            for c in report.cases
            if not c.passed
        ]

    def test_unknown_suite_raises(self):
        with pytest.raises(KeyError):
            run_suite("nope")

    def test_load_cases_reads_json_files(self, tmp_path: Path):
        (tmp_path / "a.json").write_text(
            json.dumps(
                {
                    "id": "a",
                    "description": "",
                    "input": {},
                    "expectations": [{"type": "equals", "value": "x"}],
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "b.json").write_text(
            json.dumps(
                {
                    "id": "b",
                    "description": "",
                    "input": {},
                    "expectations": [],
                }
            ),
            encoding="utf-8",
        )
        cases = load_cases(tmp_path)
        assert [c.id for c in cases] == ["a", "b"]


class TestEvalCli:
    def test_list_flag(self):
        result = CliRunner().invoke(eval_cmd, ["--list"])
        assert result.exit_code == 0
        assert "agent_smoke" in result.output

    def test_run_smoke(self):
        result = CliRunner().invoke(eval_cmd, ["--suite", "agent_smoke"])
        assert result.exit_code == 0
        assert "3/3 passed" in result.output

    def test_unknown_suite_exits_2(self):
        result = CliRunner().invoke(eval_cmd, ["--suite", "ghost"])
        assert result.exit_code == 2

    def test_min_pass_rate_threshold(self):
        # Smoke is all-pass, so threshold 1.0 still succeeds.
        ok = CliRunner().invoke(eval_cmd, ["--suite", "agent_smoke", "--min-pass-rate", "1.0"])
        assert ok.exit_code == 0
        # Threshold above 1.0 cannot be satisfied.
        bad = CliRunner().invoke(eval_cmd, ["--suite", "agent_smoke", "--min-pass-rate", "1.1"])
        assert bad.exit_code == 1

    def test_json_output(self):
        result = CliRunner().invoke(eval_cmd, ["--suite", "agent_smoke", "--json"])
        assert result.exit_code == 0
        body = json.loads(result.output)
        assert body["suite"] == "agent_smoke"
        assert body["passed"] == body["total"]
