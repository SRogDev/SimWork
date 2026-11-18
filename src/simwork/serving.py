"""One serving lifecycle for the CLI (architecture review 2026-11-18,
candidate 4).

`serve` and `mock` both start a server and block until Ctrl-C; the
lifecycle — enter, banner, wait, stop — was duplicated between them,
and `cmd_serve` called `router.__enter__()` directly instead of using
the context manager. This module owns that lifecycle: enter the
server with `with`, print the banner, block, and stop on Ctrl-C.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from typing import Any


def serve(
    server: Any,
    *,
    banner: Callable[[Any], Iterable[str]],
    stopping: str,
) -> None:
    """Serve until Ctrl-C: enter `server`, print the banner, wait, stop.

    `server` is any context manager. `banner` is called with the
    started server — its address and env overrides are only known
    after start — and returns the lines to print. A failure to start
    propagates unchanged; the stopping message is only printed after
    a clean Ctrl-C.
    """
    with server:
        for line in banner(server):
            print(line, flush=True)
        print("Press Ctrl-C to stop.", flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print(f"\n{stopping}")
