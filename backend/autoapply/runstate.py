"""Saying "this copy is running", for the installers.

An installer must not replace the program's files under a running copy, and it does not kill anything: it asks for
the program to be quit. To know, it looks for the mark left here - a file per running process in data/run, named by
its role and holding its process id - and checks that the process is still alive. Asking the system which process
runs out of which folder gives different answers on different systems (a relative path, a link to the interpreter);
a mark the program leaves itself does not.
"""

from __future__ import annotations

import atexit
import os
from pathlib import Path


def mark(role: str) -> Path | None:
    """Leave the mark for this process; it is removed when the process ends in order. A mark that outlives its
    process (a crash, a kill) is recognised as stale by whoever reads it."""
    from . import config

    try:
        folder = config.DATA / "run"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{role}-{os.getpid()}.pid"
        path.write_text(str(os.getpid()), encoding="ascii")
    except OSError:
        return None

    def clear() -> None:
        try:
            path.unlink()
        except OSError:
            pass

    atexit.register(clear)
    return path
