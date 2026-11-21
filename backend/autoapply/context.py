"""What a piece of work belongs to, on whichever thread does it.

A task runs on one of the two worker threads and hands parts of itself to helper threads: several listings fetched at
once, several postings read by the model at once. What the task is goes with every part of it:

- whose model use it is, and how far it has got    ``metering`` (task, workflow, feature, stages)
- its own count of model calls                     ``llm.usage``
- the browser it was told to use                   ``browser_policy.task_backend``
- whether the applicant asked for it by hand       ``tasks.by_hand``, ``tasks.running_by_hand``

Each of these is a context variable, so that one copy of the context carries all of them - and whatever is added
later, without anybody remembering to. (They were a thread-local here and a context variable there, and the helper
threads were handed the first kind only: a task told to use the ordinary browser fetched its listings in the other one,
and a task's own count of model calls missed the ones its helpers made.)

Not carried, on purpose: what belongs to a thread and not to a task - the page a thread has open (``browser._now``) and the model service one call is trying at the moment (``llm._tls.entry``).
"""

from __future__ import annotations

import contextvars
from typing import Any, Callable


def carried(fn: Callable[..., Any]) -> Callable[..., Any]:
    """``fn`` for the helper threads of the work that is running now.

    Every call runs in a copy of its own of the context as it is here, at the time of wrapping: one context cannot be
    entered by two threads at once, and what one piece of work sets (the feature it names, the call it is making) is
    not the next one's. What is the task's as a whole - its stages, its count of model calls - is the same object in
    every copy."""
    here = contextvars.copy_context()

    def run(*a: Any, **k: Any) -> Any:
        return here.copy().run(_begin, fn, a, k)

    return run


def _begin(fn: Callable[..., Any], a: tuple, k: dict) -> Any:
    from . import metering

    metering.own_calls()
    return fn(*a, **k)
