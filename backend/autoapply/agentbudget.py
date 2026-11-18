"""What an agent may spend on one piece of work: so many tool calls, and until a moment on the clock.

An agent is the model deciding what to do next, over and over, with the page in its hands - and it runs on the lane
that fills forms, one at a time. Each service counted in its own way (the Anthropic loop in model turns, the Claude
command line in its own turns, an OpenAI-compatible service in requests, the ChatGPT command line not at all), and the
only limit on time was between two messages, which an agent that keeps calling tools never reaches. So there is one
count and one clock, in one place - where the model's tool calls come through to this program (``llm.agent`` wraps
every tool with ``spend``) - and it is the same whichever service is doing the thinking:

- a step is a tool call; ``steps`` of them, counted across a backup service taking over part-way;
- ``deadline`` is a moment on the monotonic clock, set once, when the work starts - not a wait that starts again
  with every message;
- when either is used up the run ends, and says which: ``AgentResult.stopped`` is "max_steps" or "timeout"
  (and "end_turn" when the agent finished by itself). Ending means the model's run is stopped as well as the tools:
  a service that would go on thinking is interrupted.

How much each kind of work gets is in the settings (``agent.budgets``, by kind) - a form with eleven pages needs
more than a look at one field, and neither should be cut short to protect the other.
"""

from __future__ import annotations

import time
from typing import Any

FALLBACK = {"steps": 60, "minutes": 20}


class Spent(Exception):
    """Raised in place of a tool call the budget does not cover. ``why``: "max_steps" | "timeout"."""

    def __init__(self, why: str) -> None:
        super().__init__(f"this task's budget is used up ({why}); stop")
        self.why = why


class Budget:
    def __init__(self, steps: int, seconds: float, kind: str = "") -> None:
        self.kind = kind
        self.steps = max(1, int(steps))
        self.seconds = max(0.01, float(seconds))
        self.used = 0
        self.started = time.monotonic()
        self.deadline = self.started + self.seconds
        self.ended = ""

    def left(self) -> float:
        """Seconds until the deadline (never less than a moment: it is used as a wait)."""
        return max(0.05, self.deadline - time.monotonic())

    def expired(self) -> str:
        """"timeout" once the deadline has passed (and from then on), else what it ended on before, or ""."""
        if not self.ended and time.monotonic() >= self.deadline:
            self.ended = "timeout"
        return self.ended

    def spend(self) -> None:
        """One tool call is about to be carried out. Raises Spent when it may not be."""
        if self.expired():
            raise Spent(self.ended)
        if self.used >= self.steps:
            self.ended = "max_steps"
            raise Spent(self.ended)
        self.used += 1

    def summary(self) -> dict[str, Any]:
        return {"kind": self.kind, "steps": self.used, "of": self.steps, "seconds": round(time.monotonic() - self.started, 1), "limit_seconds": round(self.seconds),
                "ended": self.ended or "end_turn"}


LIMITS = {"steps": (1, 2000), "minutes": (1, 240)}


def _figures(kind: str, stored: dict[str, Any] | None = None) -> dict[str, float]:
    from . import config, db

    built_in = (config.DEFAULT_SETTINGS.get("agent.budgets") or {}).get(kind) or FALLBACK
    mine = ((db.get_setting("agent.budgets") if stored is None else stored) or {}).get(kind) or {}
    out = {}
    for key in ("steps", "minutes"):
        try:
            v = float(mine.get(key) or 0)
        except (TypeError, ValueError, AttributeError):
            v = 0
        out[key] = v if v > 0 else float(built_in[key])
    return out


def for_kind(kind: str) -> Budget:
    """The budget for a kind of work, as the settings have it (``agent.budgets``); a kind they do not name gets the
    built-in figures for it, or the fallback."""
    f = _figures(kind)
    return Budget(int(f["steps"]), f["minutes"] * 60, kind)


def table(stored: dict[str, Any] | None = None) -> dict[str, dict[str, float]]:
    """Every kind of work with its figures, for the settings page: what is stored, over what is built in."""
    from . import config

    kinds = list(config.DEFAULT_SETTINGS.get("agent.budgets") or {})
    return {k: {"steps": int(_figures(k, stored)["steps"]), "minutes": round(_figures(k, stored)["minutes"], 1)} for k in kinds}


def validate(settings: dict[str, Any]) -> None:
    """Raises ValueError when ``agent.budgets`` in ``settings`` is not a table of kinds with figures in range."""
    if "agent.budgets" not in settings:
        return
    t = settings["agent.budgets"]
    if not isinstance(t, dict) or not all(isinstance(v, dict) for v in t.values()):
        raise ValueError("agent.budgets must be a table: kind of work -> {steps, minutes}")
    for kind, row in t.items():
        for key, (lo, hi) in LIMITS.items():
            if key not in row:
                continue
            v = row[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
                raise ValueError(f"AI 每次能做多少：步数要在 {lo} 到 {hi} 之间（{kind}）" if key == "steps" else f"AI 每次能做多少：分钟数要在 {lo} 到 {hi} 之间（{kind}）")
