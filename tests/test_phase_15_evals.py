"""Phase 15.9: eval suite registration + smoke runs.

The three suites (materials_docx_patch / materials_latex_template /
cover_letter) ship as JSON fixtures under tests/agent_evals/fixtures/.
We assert here that:

* The suites are discoverable via list_suites().
* Each runner produces JSON envelopes that pass every fixture's
  expectations.
* The JSON-field scorers (json_field_equals / json_field_contains)
  work end-to-end.
"""

from __future__ import annotations

from src.agent.eval.runner import list_suites, run_suite


def test_phase_15_suites_are_registered() -> None:
    suites = set(list_suites())
    assert {
        "materials_docx_patch",
        "materials_latex_template",
        "cover_letter",
    } <= suites


def test_materials_docx_patch_suite_passes() -> None:
    report = run_suite("materials_docx_patch")
    assert report.cases, "no fixtures loaded for materials_docx_patch"
    failures = [
        c for c in report.cases if not c.passed
    ]
    assert not failures, (
        "materials_docx_patch failures: "
        + ", ".join(f"{c.case_id}: {c.error or c.expectations}" for c in failures)
    )


def test_materials_latex_template_suite_passes() -> None:
    report = run_suite("materials_latex_template")
    assert report.cases, "no fixtures loaded for materials_latex_template"
    failures = [c for c in report.cases if not c.passed]
    assert not failures, (
        "materials_latex_template failures: "
        + ", ".join(f"{c.case_id}: {c.error or c.expectations}" for c in failures)
    )


def test_cover_letter_suite_passes() -> None:
    report = run_suite("cover_letter")
    assert report.cases, "no fixtures loaded for cover_letter"
    failures = [c for c in report.cases if not c.passed]
    assert not failures, (
        "cover_letter failures: "
        + ", ".join(f"{c.case_id}: {c.error or c.expectations}" for c in failures)
    )


def test_json_scorers_unknown_type_returns_unknown() -> None:
    """If a fixture asks for an unknown scorer type the case fails
    with a clear message rather than silently passing."""
    from src.agent.eval.scorers import score_expectations

    results = score_expectations(
        '{"a": 1}', [{"type": "does_not_exist"}]
    )
    assert results and results[0].passed is False
    assert "unknown" in results[0].detail.lower()


def test_json_field_equals_handles_missing_path() -> None:
    from src.agent.eval.scorers import score_expectations

    results = score_expectations(
        '{"a": {"b": 1}}', [{"type": "json_field_equals", "path": "a.c", "expected": 1}]
    )
    assert results[0].passed is False
    assert "not found" in results[0].detail


def test_json_field_contains_works_on_list_membership() -> None:
    from src.agent.eval.scorers import score_expectations

    results = score_expectations(
        '{"drift": ["99%", "50%"]}',
        [{"type": "json_field_contains", "path": "drift", "needle": "99%"}],
    )
    assert results[0].passed is True
