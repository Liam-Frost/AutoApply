"""Semantic matching — embedding-based similarity between JD and applicant profile.

Computes cosine similarity between job description text and applicant's
skills, experiences, and project descriptions. Uses Claude CLI for embedding
generation with a keyword-overlap fallback when embeddings are unavailable.

Scores:
  0.0 — no overlap
  1.0 — perfect semantic match
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any

logger = logging.getLogger("autoapply.matching.semantic")


def compute_skill_overlap(
    job_skills: list[str],
    applicant_skills: list[str],
) -> float:
    """Compute normalized skill overlap score.

    Args:
        job_skills: Skills required/preferred by the job.
        applicant_skills: All skills from applicant profile.

    Returns:
        Score in [0.0, 1.0]. 1.0 means applicant has all required skills.
    """
    if not job_skills:
        return 0.5  # No skills listed — neutral score

    job_normalized = {_normalize(s) for s in job_skills}
    app_normalized = {_normalize(s) for s in applicant_skills}

    # Direct matches
    direct = job_normalized & app_normalized

    # Fuzzy matches: check if any applicant skill contains the job skill or vice versa
    fuzzy = set()
    for js in job_normalized - direct:
        for aps in app_normalized:
            if js in aps or aps in js:
                fuzzy.add(js)
                break

    matched = len(direct) + len(fuzzy) * 0.7  # Fuzzy matches count 70%
    score = matched / len(job_normalized)
    return min(score, 1.0)


def compute_keyword_similarity(
    job_description: str,
    applicant_text: str,
) -> float:
    """TF-based keyword similarity between JD and applicant profile text.

    This is the fallback when embeddings are not available.
    Uses term frequency overlap with IDF-like weighting for technical terms.

    Returns:
        Score in [0.0, 1.0].
    """
    if not job_description or not applicant_text:
        return 0.0

    job_tokens = _tokenize(job_description)
    app_tokens = _tokenize(applicant_text)

    if not job_tokens or not app_tokens:
        return 0.0

    # Count frequencies
    job_freq = Counter(job_tokens)
    app_freq = Counter(app_tokens)

    # Technical terms get higher weight (less common words matter more)
    # Simple IDF proxy: terms appearing in fewer than 20% of tokens
    total_job = len(job_tokens)
    important_terms = {
        term for term, count in job_freq.items()
        if count / total_job < 0.05 and len(term) > 2
    }

    # Compute weighted overlap
    numerator = 0.0
    denominator = 0.0

    for term, count in job_freq.items():
        weight = 2.0 if term in important_terms else 1.0
        denominator += count * weight
        if term in app_freq:
            numerator += min(count, app_freq[term]) * weight

    if denominator == 0:
        return 0.0

    return min(numerator / denominator, 1.0)


def compute_cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Cosine similarity between two vectors.

    For use with embeddings when available.
    """
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


def build_applicant_text(profile_data: dict[str, Any]) -> str:
    """Flatten applicant profile into a single text block for similarity comparison.

    Combines skills, experience bullets, and project descriptions.
    """
    parts = []

    # Skills
    skills = profile_data.get("skills", {})
    if isinstance(skills, dict):
        for category, items in skills.items():
            if isinstance(items, list):
                parts.extend(str(item) for item in items)

    # Experience bullets
    for exp in profile_data.get("work_experiences", []):
        if isinstance(exp, dict):
            if exp.get("title"):
                parts.append(exp["title"])
            for bullet in exp.get("bullets", []):
                if isinstance(bullet, dict) and bullet.get("text"):
                    parts.append(bullet["text"])

    # Project descriptions
    for proj in profile_data.get("projects", []):
        if isinstance(proj, dict):
            if proj.get("name"):
                parts.append(proj["name"])
            if proj.get("description"):
                parts.append(proj["description"])
            for tech in proj.get("tech_stack", []):
                parts.append(str(tech))

    return " ".join(parts)


def collect_applicant_skills(profile_data: dict[str, Any]) -> list[str]:
    """Extract all skills from profile for overlap scoring."""
    all_skills = []

    skills = profile_data.get("skills", {})
    if isinstance(skills, dict):
        for category, items in skills.items():
            if isinstance(items, list):
                all_skills.extend(str(item) for item in items)

    # Also extract skill tags from experiences and projects
    for section in ("work_experiences", "projects"):
        for item in profile_data.get(section, []):
            if isinstance(item, dict):
                for bullet in item.get("bullets", []):
                    if isinstance(bullet, dict):
                        all_skills.extend(bullet.get("tags", []))
                all_skills.extend(item.get("tech_stack", []))

    return list(set(all_skills))


def _normalize(s: str) -> str:
    """Normalize a skill name for comparison."""
    s = s.lower().strip()
    s = re.sub(r"[.\-/]", "", s)
    # Common aliases
    aliases = {
        "js": "javascript",
        "ts": "typescript",
        "py": "python",
        "pg": "postgresql",
        "postgres": "postgresql",
        "k8s": "kubernetes",
        "tf": "terraform",
        "gcp": "google cloud",
        "aws": "amazon web services",
        "react js": "react",
        "reactjs": "react",
        "vue js": "vue",
        "vuejs": "vue",
        "node js": "nodejs",
        "express js": "expressjs",
        "next js": "nextjs",
    }
    return aliases.get(s, s)


# Stop words for keyword similarity
_STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would shall should can could may might must need of in to for "
    "with on at by from as into through during before after above below "
    "between out off over under again further then once here there when "
    "where why how all each every both few more most other some such no "
    "not only own same so than too very and but if or because until while "
    "about against we you your they their this that these those it its "
    "what which who whom our".split()
)


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase words, removing stop words."""
    words = re.findall(r"[a-zA-Z0-9#+.]+", text.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 1]
