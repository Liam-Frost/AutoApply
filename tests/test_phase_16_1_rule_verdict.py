"""Phase 16.1 tests -- structured ``RuleResult`` fields + ``ScoreBreakdown.job_snapshot_id``.

These pin the new contract surface ("Why was this filtered?" payload)
without re-asserting anything the existing ``tests/test_matching.py``
already covers about pass/fail semantics. The point is:

* ``RuleResult.rule_id`` is always set (defaults to ``rule_name`` when
  the caller did not provide one).
* ``RuleResult.verdict`` stays in sync with ``passed``.
* ``RuleResult.evidence_excerpt`` is the JD snippet (with surrounding
  context + collapsed whitespace + ellipsis) when the rule fired
  against JD text, or a structured marker (``"employment_type=fulltime"``,
  ``"title=...''"``) when the rule fired against a structured field, or
  ``None`` when no JD evidence is available.
* ``ScoreBreakdown`` carries ``job_snapshot_id``, ``disqualify_results``,
  and a clean ``to_dict()`` shape suitable for the trace store + the
  Phase 16.3 popover payload.
"""

from __future__ import annotations

from src.intake.schema import JobRequirements, RawJob
from src.matching.rules import (
    ApplicantContext,
    RuleResult,
    RuleVerdict,
    check_rules,
)
from src.matching.scorer import ScoreBreakdown, build_scoring_context, score_job, score_jobs

# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

_PROFILE = {
    "identity": {
        "location": "Vancouver, BC, Canada",
        "citizenship": "Chinese",
        "work_authorization": "Study Permit",
        "visa_sponsorship_needed": True,
    },
    "education": [{"degree": "Bachelor of Science"}],
    "work_experiences": [
        {
            "company": "Acme",
            "title": "Intern",
            "start_date": "2025-05",
            "end_date": "2025-08",
            "bullets": [{"text": "Built APIs", "tags": ["python"]}],
        }
    ],
    "skills": {"languages": ["Python"]},
}


def _make_job(**overrides) -> RawJob:
    defaults = {
        "source": "greenhouse",
        "source_id": "j1",
        "company": "TestCo",
        "title": "Software Engineering Intern",
        "location": "Vancouver, BC",
        "employment_type": "internship",
        "seniority": "internship",
        "description": (
            "Looking for a strong Python intern. Must have a Bachelor's degree. "
            "This role does not offer visa sponsorship at this time."
        ),
        "ats_type": "greenhouse",
        "application_url": "https://example.com/apply",
    }
    defaults.update(overrides)
    return RawJob(**defaults)


def _make_ctx(**overrides) -> ApplicantContext:
    defaults = {
        "visa_sponsorship_needed": True,
        "preferred_employment_types": ["internship", "coop"],
        "education_level": "Bachelor's",
    }
    defaults.update(overrides)
    return ApplicantContext(**defaults)


# --------------------------------------------------------------------------- #
# RuleResult shape                                                            #
# --------------------------------------------------------------------------- #


class TestRuleResultShape:
    def test_defaults_rule_id_to_rule_name_when_omitted(self):
        """Legacy call sites without rule_id should still emit a useful id."""
        r = RuleResult(rule_name="custom_check", passed=False, reason="bad")
        assert r.rule_id == "custom_check"
        assert r.verdict == "fail"

    def test_verdict_synced_to_passed_on_pass(self):
        r = RuleResult(rule_name="x", passed=True)
        assert r.verdict == "pass"

    def test_passed_true_overrides_explicit_fail_verdict(self):
        """Defensive: if a caller passes passed=True but verdict='fail', trust passed."""
        r = RuleResult(rule_name="x", passed=True, verdict="fail")
        assert r.verdict == "pass"

    def test_to_dict_round_trip(self):
        r = RuleResult(
            rule_id="exp",
            rule_name="experience",
            passed=False,
            verdict="fail",
            reason="not enough years",
            evidence_excerpt="...5+ years of experience...",
        )
        d = r.to_dict()
        assert d == {
            "rule_id": "exp",
            "rule_name": "experience",
            "verdict": "fail",
            "passed": False,
            "reason": "not enough years",
            "evidence_excerpt": "...5+ years of experience...",
        }


# --------------------------------------------------------------------------- #
# Evidence extraction                                                         #
# --------------------------------------------------------------------------- #


class TestEvidenceExtraction:
    def test_visa_sponsorship_excerpt_contains_trigger_phrase(self):
        job = _make_job()
        job.requirements = JobRequirements(visa_sponsorship=False)
        verdict = check_rules(job, _make_ctx())
        assert not verdict.passed
        fails = verdict.fail_results
        wa = next(r for r in fails if r.rule_id == "work_authorization")
        assert wa.evidence_excerpt is not None
        # "does not offer visa sponsorship" appears in the fixture JD.
        assert "sponsorship" in wa.evidence_excerpt.lower()

    def test_us_auth_excerpt_extracted(self):
        job = _make_job(
            description="Must be a US Citizen or hold a Green Card. Strong Python required."
        )
        job.requirements = JobRequirements(us_work_auth_required=True)
        verdict = check_rules(job, _make_ctx(work_authorization="Study Permit"))
        wa = next(r for r in verdict.fail_results if r.rule_id == "work_authorization")
        assert wa.evidence_excerpt is not None
        excerpt = wa.evidence_excerpt.lower()
        assert ("us citizen" in excerpt) or ("green card" in excerpt)

    def test_experience_excerpt_extracted(self):
        job = _make_job(
            description=(
                "We are hiring a senior engineer. Minimum of 5+ years of experience "
                "with distributed systems required."
            )
        )
        job.requirements = JobRequirements(experience_years_min=5)
        verdict = check_rules(job, _make_ctx())
        exp = next(r for r in verdict.fail_results if r.rule_id == "experience")
        assert exp.evidence_excerpt is not None
        assert "year" in exp.evidence_excerpt.lower()

    def test_education_excerpt_extracted(self):
        job = _make_job(
            description="Applicants must hold a PhD in Computer Science or related field."
        )
        job.requirements = JobRequirements(education_level="PhD")
        verdict = check_rules(job, _make_ctx(education_level="Bachelor's"))
        edu = next(r for r in verdict.fail_results if r.rule_id == "education")
        assert edu.evidence_excerpt is not None
        assert "phd" in edu.evidence_excerpt.lower()

    def test_employment_type_excerpt_is_structured_field(self):
        """For employment_type, evidence is the structured field, not a JD snippet."""
        job = _make_job(employment_type="fulltime")
        verdict = check_rules(job, _make_ctx(preferred_employment_types=["internship"]))
        et = next(r for r in verdict.fail_results if r.rule_id == "employment_type")
        assert et.evidence_excerpt == "employment_type=fulltime"

    def test_spam_excerpt_from_description(self):
        job = _make_job(
            description=(
                "Our staffing agency works with top employers. Send us your resume "
                "and we'll match you to roles."
            )
        )
        verdict = check_rules(job, _make_ctx())
        spam = next(r for r in verdict.fail_results if r.rule_id == "spam_filter")
        assert spam.evidence_excerpt is not None
        assert "staffing agency" in spam.evidence_excerpt.lower()

    def test_short_title_excerpt_uses_title_marker(self):
        job = _make_job(title="Job")
        verdict = check_rules(job, _make_ctx())
        spam = next(r for r in verdict.fail_results if r.rule_id == "spam_filter")
        assert spam.evidence_excerpt is not None
        assert spam.evidence_excerpt.startswith("title=")

    def test_excerpt_bounded_to_max_length(self):
        """Long descriptions should produce truncated excerpts."""
        long_desc = (
            "We are hiring. " + ("blah " * 200) + "5+ years of experience required " + ("blah " * 200)
        )
        job = _make_job(description=long_desc)
        job.requirements = JobRequirements(experience_years_min=5)
        verdict = check_rules(job, _make_ctx())
        exp = next(r for r in verdict.fail_results if r.rule_id == "experience")
        # Bounded ~200 chars; allow a bit of slack for ellipsis chars.
        assert exp.evidence_excerpt is not None
        assert len(exp.evidence_excerpt) <= 210


# --------------------------------------------------------------------------- #
# ScoreBreakdown wiring                                                       #
# --------------------------------------------------------------------------- #


class TestScoreBreakdownPhase16:
    def test_job_snapshot_id_flows_through(self):
        job = _make_job()
        ctx = build_scoring_context(_PROFILE)
        bd = score_job(job, ctx, job_snapshot_id="snap-abc")
        assert bd.job_snapshot_id == "snap-abc"

    def test_default_snapshot_id_is_none(self):
        bd = score_job(_make_job(), build_scoring_context(_PROFILE))
        assert bd.job_snapshot_id is None

    def test_disqualified_breakdown_carries_structured_results(self):
        job = _make_job()
        job.requirements = JobRequirements(visa_sponsorship=False)
        bd = score_job(job, build_scoring_context(_PROFILE))
        assert bd.disqualified
        # New: structured per-rule failures
        assert len(bd.disqualify_results) >= 1
        wa = next(r for r in bd.disqualify_results if r.rule_id == "work_authorization")
        assert wa.evidence_excerpt is not None
        # Old: string list still present
        assert any("sponsorship" in s for s in bd.disqualify_reasons)

    def test_qualified_breakdown_has_empty_disqualify_results(self):
        bd = score_job(_make_job(), build_scoring_context(_PROFILE))
        assert not bd.disqualified
        assert bd.disqualify_results == []

    def test_to_dict_shape(self):
        job = _make_job()
        job.requirements = JobRequirements(visa_sponsorship=False)
        bd = score_job(job, build_scoring_context(_PROFILE), job_snapshot_id="snap-1")
        d = bd.to_dict()
        assert d["job_snapshot_id"] == "snap-1"
        assert d["disqualified"] is True
        assert isinstance(d["disqualify_results"], list)
        assert d["disqualify_results"][0]["rule_id"] == "work_authorization"
        assert "evidence_excerpt" in d["disqualify_results"][0]
        assert d["rule_verdict"]["passed"] is False

    def test_score_jobs_threads_snapshot_ids(self):
        job_a = _make_job(source_id="a")
        job_b = _make_job(source_id="b")
        ctx = build_scoring_context(_PROFILE)
        out = score_jobs(
            [job_a, job_b],
            ctx,
            snapshot_ids={str(job_a.id): "snap-a", str(job_b.id): "snap-b"},
        )
        snapshot_for = {bd.job_id: bd.job_snapshot_id for bd in out}
        assert snapshot_for[str(job_a.id)] == "snap-a"
        assert snapshot_for[str(job_b.id)] == "snap-b"

    def test_score_jobs_missing_snapshot_id_is_none(self):
        job = _make_job()
        ctx = build_scoring_context(_PROFILE)
        out = score_jobs([job], ctx, snapshot_ids={})
        assert out[0].job_snapshot_id is None


# --------------------------------------------------------------------------- #
# Aggregate RuleVerdict                                                       #
# --------------------------------------------------------------------------- #


class TestRuleVerdictAggregate:
    def test_fail_results_excludes_passes(self):
        job = _make_job()
        job.requirements = JobRequirements(visa_sponsorship=False)
        verdict = check_rules(job, _make_ctx())
        assert all(not r.passed for r in verdict.fail_results)
        assert len(verdict.fail_results) >= 1

    def test_to_dict_includes_per_rule_breakdown(self):
        job = _make_job()
        job.requirements = JobRequirements(visa_sponsorship=False)
        verdict = check_rules(job, _make_ctx())
        d = verdict.to_dict()
        assert d["passed"] is False
        assert isinstance(d["results"], list)
        ids = [r["rule_id"] for r in d["results"]]
        # All five rules should be present in the aggregate dict.
        assert "work_authorization" in ids
        assert "experience" in ids
        assert "education" in ids
        assert "employment_type" in ids
        assert "spam_filter" in ids

    def test_passing_verdict_has_no_fail_results(self):
        verdict = check_rules(_make_job(), _make_ctx())
        assert verdict.passed
        assert verdict.fail_results == []


# --------------------------------------------------------------------------- #
# Backward compatibility                                                      #
# --------------------------------------------------------------------------- #


class TestBackwardCompatibility:
    def test_legacy_fail_reasons_string_list_preserved(self):
        """Existing callers reading verdict.fail_reasons as ``list[str]`` keep working."""
        job = _make_job()
        job.requirements = JobRequirements(visa_sponsorship=False)
        verdict = check_rules(job, _make_ctx())
        assert isinstance(verdict.fail_reasons, list)
        assert all(isinstance(s, str) for s in verdict.fail_reasons)

    def test_score_breakdown_disqualify_reasons_string_list_preserved(self):
        job = _make_job()
        job.requirements = JobRequirements(visa_sponsorship=False)
        bd = score_job(job, build_scoring_context(_PROFILE))
        assert isinstance(bd.disqualify_reasons, list)
        assert all(isinstance(s, str) for s in bd.disqualify_reasons)

    def test_score_job_without_snapshot_id_arg_works(self):
        """Existing two-arg callers (no kwarg) must keep working."""
        bd = score_job(_make_job(), build_scoring_context(_PROFILE))
        assert isinstance(bd, ScoreBreakdown)
        assert bd.job_snapshot_id is None
