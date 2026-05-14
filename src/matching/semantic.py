"""Semantic matching — embedding-based similarity between JD and applicant profile.

Computes cosine similarity between job description text and applicant's
skills, experiences, and project descriptions. Falls back to keyword
overlap when embeddings are unavailable.

Scores:
  0.0 — no overlap
  1.0 — perfect semantic match

Phase 12.5 adds :func:`embed_text` -- a cache-wrapped OpenAI embeddings
client that populates the L1+L2 cache under the ``embedding`` namespace
with a 30-day TTL. Returns ``None`` gracefully if the OpenAI provider
isn't configured so callers can fall back to the keyword path.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import Counter
from typing import Any

logger = logging.getLogger("autoapply.matching.semantic")

# Default embedding model. text-embedding-3-small is 1536-dim, matching
# the pgvector columns on ``BulletPool.text_embedding``,
# ``StoryBank.content_embedding``, and ``RawJob.description_embedding``
# (see ``src/core/models.py``). Bumping the default would invalidate
# existing pgvector data, so it's a deliberate choice -- treat it as
# part of the cache key.
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

# Cap on the input length sent to the embeddings endpoint. OpenAI's
# 8k token limit is well above this character cap; the cap here is
# defensive against pathological inputs that would blow up the cache
# key size and the API bill.
_MAX_EMBED_INPUT_CHARS = 32_000


def _resolve_openai_provider() -> tuple[str, str] | None:
    """Return ``(api_key, base_url)`` for the registered OpenAI provider.

    ``api_key`` is resolved via :meth:`ApiKeyProvider.get_api_key`,
    which checks credentials first, then ``OPENAI_API_KEY``. Returns
    ``None`` on any miss (no registry, provider not registered, no
    credentials AND no env var, or a registry hiccup) so callers can
    degrade silently.

    Resolved up-front (before cache lookup) so the cache key can
    include the base URL -- a compatible proxy using the same model
    name but a different embedding space must not share a key with
    the public endpoint.
    """
    try:
        from src.providers import get_registry  # noqa: PLC0415
        from src.providers.base import ProviderError  # noqa: PLC0415

        registry = get_registry()
        provider = registry.maybe_get("openai")
        if provider is None:
            return None
        try:
            api_key = provider.get_api_key()  # type: ignore[attr-defined]
        except ProviderError:
            return None
        if not api_key:
            return None
        base_url = (
            provider._base_url() if hasattr(provider, "_base_url") else None
        ) or "https://api.openai.com/v1"
        return api_key, base_url
    except Exception as exc:  # noqa: BLE001 -- registry hiccup -> no embedding
        logger.debug("Embedding provider lookup failed (%s).", exc)
        return None


def embed_text(
    text: str,
    *,
    model: str = DEFAULT_EMBEDDING_MODEL,
    cache: bool = True,
    timeout: int = 30,
) -> list[float] | None:
    """Return the embedding vector for ``text`` from OpenAI, or ``None``.

    Phase 12.5: cache-wrapped. Default ``cache=True`` because
    embeddings are deterministic given ``(model, base_url, text)`` --
    repeat calls should never round-trip to the API. The 30-day TTL
    is set by :data:`src.cache.base.NAMESPACE_TTLS`.

    Returns ``None`` (not raises) when:
      * ``text`` is empty / whitespace-only after stripping
      * the OpenAI provider isn't registered or configured
        (neither credential nor ``OPENAI_API_KEY`` env var)
      * the HTTP call fails (transport, auth, quota, parse, etc.)

    Callers (``src/matching/`` etc.) read ``None`` as "no embedding
    available; fall back to the keyword path" so a misconfigured
    deployment degrades to lower-quality matching instead of
    raising. Only successful results are cached -- a failure does
    not poison the namespace.
    """
    if not text or not text.strip():
        return None
    # Truncate before fingerprinting so the cache key matches what
    # we'd actually send to the API.
    text = text[:_MAX_EMBED_INPUT_CHARS]

    resolved = _resolve_openai_provider()
    if resolved is None:
        return None
    api_key, base_url = resolved

    cache_key: str | None = None
    if cache:
        # Cache key is ``(model, base_url, text)``: a different base
        # URL can mean a different embedding space (e.g. a proxy that
        # routes ``text-embedding-3-small`` to a different backend),
        # so vectors from different endpoints must NOT collide. The
        # cache CACHE_VERSION already gates serialisation-format
        # changes; bumping it is the escape hatch for any wider
        # invalidation.
        digest = hashlib.sha256(
            f"{model}\x00{base_url}\x00{text}".encode()
        ).hexdigest()
        cache_key = digest
        try:
            from src.cache import get_cache  # noqa: PLC0415

            cached = get_cache().get("embedding", cache_key)
        except Exception as exc:  # noqa: BLE001 -- cache must never break embed
            logger.debug("Embedding cache lookup skipped (%s).", exc)
            cached = None
        if cached is not None:
            return cached

    vector = _call_openai_embeddings(
        text, model=model, api_key=api_key, base_url=base_url, timeout=timeout
    )
    if vector is None:
        return None

    if cache and cache_key is not None:
        try:
            from src.cache import get_cache  # noqa: PLC0415

            get_cache().set("embedding", cache_key, vector)
        except Exception as exc:  # noqa: BLE001 -- cache failures never block
            logger.debug("Embedding cache write skipped (%s).", exc)
    return vector


def _call_openai_embeddings(
    text: str, *, model: str, api_key: str, base_url: str, timeout: int
) -> list[float] | None:
    """POST to ``{base_url}/embeddings`` and return the first vector.

    We deliberately do NOT depend on the openai SDK; the REST shape
    is stable and tiny, and a hard SDK dep would conflict with the
    project's "subprocess CLI first, REST second" provider philosophy.
    """
    try:
        import httpx  # noqa: PLC0415

        response = httpx.post(
            f"{base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "input": text},
            timeout=timeout,
        )
        if response.status_code != 200:
            logger.warning(
                "Embedding API returned %s: %s",
                response.status_code,
                response.text[:200],
            )
            return None
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 -- HTTP/JSON failure -> no embedding
        logger.warning("Embedding API call failed: %s", exc)
        return None

    # Defensive shape validation: the embeddings endpoint shape is
    # documented, but a misbehaving proxy or a non-200 path that
    # still set status_code=200 could return a top-level array, a
    # bare string, or a ``data`` list of non-objects. Any of those
    # would AttributeError on the ``.get`` chain and propagate out
    # of this function, breaking the documented graceful-fallback
    # contract. Type-check each layer before reading from it.
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    if not isinstance(first, dict):
        return None
    vector = first.get("embedding")
    if not isinstance(vector, list) or not all(
        isinstance(v, int | float) for v in vector
    ):
        return None
    return [float(v) for v in vector]


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
        term for term, count in job_freq.items() if count / total_job < 0.05 and len(term) > 2
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
