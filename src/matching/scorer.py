"""Composite job scorer — combines rule checks, skill overlap, and text similarity.

Produces a final match score in [0.0, 1.0] for each job, along with
a breakdown of component scores for transparency and debugging.

Scoring formula:
  final_score = (
      w_skill * skill_overlap_score
    + w_text  * keyword_similarity_score
    + w_rule  * rule_bonus
  ) * quality_multiplier

Where:
  - skill_overlap: how many required skills the applicant has
  - keyword_similarity: TF-based overlap between JD and profile text
  - rule_bonus: 1.0 if all rules pass, 0.0 if any hard rule fails
  - quality_multiplier: penalizes low-quality postings (short JD, vague title)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.intake.schema import RawJob
from src.matching.rules import ApplicantContext, RuleVerdict, check_rules
from src.matching.semantic import (
    build_applicant_text,
    collect_applicant_skills,
    compute_keyword_similarity,
    compute_skill_overlap,
)

logger = logging.getLogger("autoapply.matching.scorer")

# Default scoring weights (should sum to ~1.0 for the non-rule components)
DEFAULT_WEIGHTS = {
    "skill_overlap": 0.45,
    "keyword_similarity": 0.35,
    "rule_bonus": 0.20,
}


@dataclass
class ScoreBreakdown:
    """Detailed scoring breakdown for a single job."""

    job_id: str
    company: str
    title: str
    final_score: float = 0.0
    skill_overlap: float = 0.0
    keyword_similarity: float = 0.0
    rule_bonus: float = 0.0
    quality_multiplier: float = 1.0
    rule_verdict: RuleVerdict | None = None
    disqualified: bool = False
    disqualify_reasons: list[str] = field(default_factory=list)


@dataclass
class ScoringContext:
    """Pre-computed applicant data for batch scoring."""

    applicant_ctx: ApplicantContext
    applicant_skills: list[str]
    applicant_text: str
    weights: dict[str, float] = field(default_factory=lambda: DEFAULT_WEIGHTS.copy())


def build_scoring_context(
    profile_data: dict[str, Any],
    applicant_ctx: ApplicantContext | None = None,
    weights: dict[str, float] | None = None,
) -> ScoringContext:
    """Pre-compute applicant data for efficient batch scoring.

    Args:
        profile_data: Full applicant profile dict (from YAML or DB).
        applicant_ctx: Pre-built context (if None, built from profile_data).
        weights: Custom scoring weights (if None, uses defaults).
    """
    from src.matching.rules import load_applicant_context

    return ScoringContext(
        applicant_ctx=applicant_ctx or load_applicant_context(profile_data),
        applicant_skills=collect_applicant_skills(profile_data),
        applicant_text=build_applicant_text(profile_data),
        weights=weights or DEFAULT_WEIGHTS.copy(),
    )


def score_job(job: RawJob, ctx: ScoringContext) -> ScoreBreakdown:
    """Score a single job against the applicant profile.

    Returns a ScoreBreakdown with the final score and all component scores.
    """
    breakdown = ScoreBreakdown(
        job_id=str(job.id),
        company=job.company,
        title=job.title,
    )

    # 1. Hard rule check
    verdict = check_rules(job, ctx.applicant_ctx)
    breakdown.rule_verdict = verdict

    if not verdict.passed:
        breakdown.disqualified = True
        breakdown.disqualify_reasons = verdict.fail_reasons
        breakdown.final_score = 0.0
        return breakdown

    breakdown.rule_bonus = 1.0

    # 2. Skill overlap (must-haves weighted 70%, preferred 30%)
    must_score = compute_skill_overlap(job.requirements.must_have_skills, ctx.applicant_skills)
    pref_score = compute_skill_overlap(job.requirements.preferred_skills, ctx.applicant_skills)
    breakdown.skill_overlap = must_score * 0.7 + pref_score * 0.3

    # 3. Keyword similarity
    jd_text = job.description or job.title
    breakdown.keyword_similarity = compute_keyword_similarity(jd_text, ctx.applicant_text)

    # 4. Quality multiplier
    breakdown.quality_multiplier = _compute_quality_multiplier(job)

    # 5. Weighted final score
    w = ctx.weights
    raw_score = (
        w.get("skill_overlap", 0.45) * breakdown.skill_overlap
        + w.get("keyword_similarity", 0.35) * breakdown.keyword_similarity
        + w.get("rule_bonus", 0.20) * breakdown.rule_bonus
    )
    breakdown.final_score = round(raw_score * breakdown.quality_multiplier, 4)

    return breakdown


def score_jobs(
    jobs: list[RawJob],
    ctx: ScoringContext,
) -> list[ScoreBreakdown]:
    """Score and rank a batch of jobs.

    Returns list sorted by final_score descending. Disqualified jobs are
    included (at the bottom with score 0.0) for audit trail.
    """
    results = [score_job(job, ctx) for job in jobs]
    results.sort(key=lambda s: s.final_score, reverse=True)

    qualified = sum(1 for r in results if not r.disqualified)
    logger.info(
        "Scored %d jobs: %d qualified, %d disqualified",
        len(results),
        qualified,
        len(results) - qualified,
    )

    return results


def print_ranking(scores: list[ScoreBreakdown], top_n: int = 20) -> None:
    """Pretty-print the top-N scored jobs to stdout."""
    qualified = [s for s in scores if not s.disqualified]

    print(f"\n{'=' * 80}")
    print(f" Top {min(top_n, len(qualified))} of {len(qualified)} qualified jobs")
    print(f"{'=' * 80}\n")

    for i, s in enumerate(qualified[:top_n], 1):
        print(f"  [{i:3d}] {s.final_score:.3f}  {s.company} — {s.title}")
        print(
            f"        skill={s.skill_overlap:.2f}  text={s.keyword_similarity:.2f}  "
            f"quality={s.quality_multiplier:.2f}"
        )
        print()

    disqualified = [s for s in scores if s.disqualified]
    if disqualified:
        print(f"  --- {len(disqualified)} jobs disqualified ---")
        for s in disqualified[:5]:
            print(f"    ✗ {s.company} — {s.title}: {s.disqualify_reasons[0]}")
        if len(disqualified) > 5:
            print(f"    ... and {len(disqualified) - 5} more")
        print()


def _compute_quality_multiplier(job: RawJob) -> float:
    """Penalize low-quality job postings.

    Signals:
      - Very short description → likely incomplete / spam
      - No application URL → can't apply
      - Generic title → likely ghost posting
    """
    multiplier = 1.0

    desc_len = len(job.description or "")
    if desc_len < 100:
        multiplier *= 0.5  # Very short JD
    elif desc_len < 300:
        multiplier *= 0.8  # Sparse JD

    if not job.application_url:
        multiplier *= 0.7  # No apply link

    return round(multiplier, 2)
