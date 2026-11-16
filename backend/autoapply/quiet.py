"""No console windows.

The server runs without a console of its own (the launcher starts it that way). On Windows, a console program started
from such a process gets a brand-new console window - one for every call to the Claude command line, to PowerShell for a
document conversion, to a browser driver. They flash up over whatever the user is doing.

Every one of those starts goes through ``subprocess.Popen`` (``subprocess.run``, asyncio's and anyio's process calls
included), so that is where the window is turned off: a child gets CREATE_NO_WINDOW unless the caller asked for a console
of its own. Programs with a window of their own - the browser the applicant signs in with - are not console programs
and are not affected.
"""

from __future__ import annotations

import subprocess
import sys

_done = False


def install() -> None:
    global _done
    if _done or sys.platform != "win32":
        return
    _done = True
    no_window = subprocess.CREATE_NO_WINDOW
    own_console = subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS
    real = subprocess.Popen.__init__

    def init(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        flags = kwargs.get("creationflags") or 0
        if not flags & own_console:
            kwargs["creationflags"] = flags | no_window
        real(self, *args, **kwargs)

    subprocess.Popen.__init__ = init  # type: ignore[method-assign]
