"""Cost / token estimation for the agent loop.

The CLI providers we use today (claude-cli, codex-cli) do not expose
accurate token counts in their exec output. We still want the trace
viewer and eval reports to show *something* operators can budget
against, so we estimate.

Heuristic: ~4 chars per token for English mixed with JSON. Pricing is
configurable via env vars so a user with different rates (or the eval
suite running under a cheaper alias) can pin the numbers without code
changes:

    AUTOAPPLY_AGENT_COST_PROMPT_PER_1K  (default $0.003 / 1k tokens)
    AUTOAPPLY_AGENT_COST_OUTPUT_PER_1K  (default $0.015 / 1k tokens)

Numbers should not be trusted to the cent -- they exist to spot order-
of-magnitude regressions ("a single agent run cost $5") not to reconcile
provider invoices.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# 4 chars/token is the long-standing OpenAI rule of thumb. Real values
# range 3-5 depending on language and structure; we err toward 4 since
# the agent's transcripts are heavy on JSON which compresses well.
_CHARS_PER_TOKEN = 4

_DEFAULT_PROMPT_PER_1K = 0.003
_DEFAULT_OUTPUT_PER_1K = 0.015


@dataclass(frozen=True)
class CostRates:
    prompt_per_1k_usd: float
    output_per_1k_usd: float

    @classmethod
    def from_env(cls) -> CostRates:
        return cls(
            prompt_per_1k_usd=_float_env(
                "AUTOAPPLY_AGENT_COST_PROMPT_PER_1K", _DEFAULT_PROMPT_PER_1K
            ),
            output_per_1k_usd=_float_env(
                "AUTOAPPLY_AGENT_COST_OUTPUT_PER_1K", _DEFAULT_OUTPUT_PER_1K
            ),
        )


def estimate_tokens(text: str) -> int:
    """Best-effort token count: ceil(len/4). Returns 0 for empty input."""
    if not text:
        return 0
    # ceil division.
    return (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN


def estimate_cost_usd(
    *, prompt_tokens: int, output_tokens: int, rates: CostRates | None = None
) -> float:
    rates = rates or CostRates.from_env()
    cost = (prompt_tokens / 1000.0) * rates.prompt_per_1k_usd + (
        output_tokens / 1000.0
    ) * rates.output_per_1k_usd
    return round(cost, 6)


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default
