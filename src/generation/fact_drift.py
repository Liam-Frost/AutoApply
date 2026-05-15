"""Phase 15.7: fact-drift post-guard for cover-letter generation.

The cover-letter agent emits a structured IR (paragraphs with evidence
citations); the deterministic renderer turns that into DOCX/PDF. The
post-guard runs *between* the IR and the renderer: it asserts that the
paragraphs only contain claims traceable to the source evidence and
the JD snapshot.

Why we need it (D024 / D005): an agent can confidently emit a
plausible-sounding sentence that invents a number, a team size, or a
location. The materials router cannot ship LLM-fabricated facts on a
cover letter that will be read by a recruiter -- the failure mode is
expensive (interview rescinded, reputational damage).

Checks performed:

* **Number drift** -- every numeric token in the rewritten text must
  appear in the source evidence, the JD snapshot, or the applicant
  profile. Numbers that show up only in the generated text count as
  drift.
* **Entity drift** -- proper nouns that look like company / school
  names (capitalized tokens of length >= 3) must be grounded in the
  evidence or JD. Detection is intentionally conservative -- the
  guard reports candidates, not violations, so the cover-letter agent
  has actionable feedback without falsely blocking common adjectives.
* **Length sanity** -- IR paragraphs longer than ~3x the average
  evidence sentence length are flagged. An evidence-cited paragraph
  that balloons usually means the LLM padded with fluff.

The guard returns a :class:`FactDriftReport`; callers decide whether
to gate. The default 15.7 wiring treats *any* number drift as a hard
block (deterministic fallback) and *any* entity drift as a warning.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Numeric tokens: 40%, 10k, 2.5x, $1.2M, etc.
_NUMERIC_RE = re.compile(
    r"""
    (?:\$)?           # optional currency
    \d+               # integer part
    (?:\.\d+)?        # optional decimal
    (?:%|x|k|m|b|K|M|B)?  # optional unit suffix
    (?:\s*-\s*\d+)?   # optional range (e.g. 5-10)
    """,
    re.VERBOSE,
)

# Conservative proper-noun detector: capitalised word of 3+ chars, NOT
# at sentence start (we accept some false negatives to keep noise low).
_PROPER_RE = re.compile(r"(?<=\s)([A-Z][A-Za-z0-9]{2,}(?:[ -][A-Z][A-Za-z0-9]{2,})*)")

# Function / sentence-start words that are ALWAYS capitalised at the
# start of a sentence and should never trigger entity drift.
_COMMON_INITIAL_CAPITALS: frozenset[str] = frozenset(
    {
        "The",
        "This",
        "These",
        "That",
        "Those",
        "It",
        "I",
        "We",
        "My",
        "Our",
        "As",
        "At",
        "In",
        "On",
        "For",
        "From",
        "After",
        "Before",
        "While",
        "When",
        "However",
        "Therefore",
        "Additionally",
        "Furthermore",
        "Moreover",
        "Although",
        "Through",
        "With",
        "Without",
        "During",
        "Beyond",
        "Also",
    }
)


@dataclass
class FactDriftReport:
    """Returned from :func:`check_fact_drift`. ``has_blocking_drift``
    is True when any number drift was found (per Phase 15.7's default
    policy)."""

    has_blocking_drift: bool
    number_drift: list[str] = field(default_factory=list)
    entity_drift: list[str] = field(default_factory=list)
    length_warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def check_fact_drift(
    generated_text: str,
    *,
    evidence_texts: list[str] | None = None,
    jd_snapshot_text: str | None = None,
    profile_text: str | None = None,
) -> FactDriftReport:
    """Run the post-guard against ``generated_text``.

    All ``*_text`` sources are concatenated to form the "grounded
    corpus". Tokens / numbers that appear in the generated text but
    NOT in the corpus are reported as drift.
    """
    sources: list[str] = []
    if evidence_texts:
        sources.extend(s for s in evidence_texts if s)
    if jd_snapshot_text:
        sources.append(jd_snapshot_text)
    if profile_text:
        sources.append(profile_text)
    corpus = " ".join(sources)
    corpus_lower = corpus.lower()

    report = FactDriftReport(has_blocking_drift=False)

    # ----- numbers -----------------------------------------------------
    generated_numbers = _extract_numbers(generated_text)
    corpus_numbers = set(_extract_numbers(corpus))
    drift_numbers = [
        token
        for token in generated_numbers
        if _normalize_number(token) not in {_normalize_number(c) for c in corpus_numbers}
    ]
    if drift_numbers:
        # Dedupe while preserving order.
        seen: set[str] = set()
        unique = [n for n in drift_numbers if not (n in seen or seen.add(n))]
        report.number_drift = unique
        report.has_blocking_drift = True

    # ----- entities ----------------------------------------------------
    candidates = _extract_proper_nouns(generated_text)
    drift_entities: list[str] = []
    for cand in candidates:
        # Look up in case-insensitive corpus.
        if cand.lower() in corpus_lower:
            continue
        # Common capitalised initial words are noise.
        first_token = cand.split()[0] if cand else ""
        if first_token in _COMMON_INITIAL_CAPITALS and " " not in cand:
            continue
        drift_entities.append(cand)
    # Order-preserving dedupe.
    seen_e: set[str] = set()
    report.entity_drift = [e for e in drift_entities if not (e in seen_e or seen_e.add(e))]

    # ----- length sanity ----------------------------------------------
    if evidence_texts:
        evidence_sentences = [
            s.strip() for s in re.split(r"[.!?]", " ".join(evidence_texts)) if s.strip()
        ]
        if evidence_sentences:
            avg = sum(len(s) for s in evidence_sentences) / len(evidence_sentences)
            for paragraph in re.split(r"\n\s*\n", generated_text or ""):
                paragraph = paragraph.strip()
                if not paragraph:
                    continue
                if len(paragraph) > 3 * avg and len(paragraph) > 300:
                    snippet = paragraph[:80].replace("\n", " ")
                    report.length_warnings.append(
                        f"paragraph length {len(paragraph)} > 3x evidence avg "
                        f"({int(avg)}): {snippet!r}..."
                    )

    if not report.has_blocking_drift and not report.entity_drift and not report.length_warnings:
        report.notes.append("no drift detected")
    return report


# ---- Helpers --------------------------------------------------------


def _extract_numbers(text: str) -> list[str]:
    if not text:
        return []
    return [m.group(0).strip() for m in _NUMERIC_RE.finditer(text) if m.group(0).strip()]


def _normalize_number(token: str) -> str:
    """Strip whitespace + currency + unit so '40%' / ' 40% ' / '40 %'
    all compare equal.

    Suffixes like ``k`` / ``M`` get expanded so the cover letter saying
    "10k requests" matches evidence saying "10,000 requests".
    """
    cleaned = re.sub(r"[\s,$]", "", token).lower()
    if cleaned.endswith("%"):
        return cleaned
    multipliers = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
    suffix = cleaned[-1:] if cleaned else ""
    if suffix in multipliers:
        try:
            return str(int(float(cleaned[:-1]) * multipliers[suffix]))
        except ValueError:
            return cleaned
    return cleaned


def _extract_proper_nouns(text: str) -> list[str]:
    if not text:
        return []
    return [m.group(1) for m in _PROPER_RE.finditer(text)]


__all__ = ["FactDriftReport", "check_fact_drift"]
