"""Parent-process watchdog for the sidecar.

Monitors the parent PID (Tauri) and exits the sidecar gracefully if the
parent dies or re-parents us to init. Extracted from ``src/main.py``.
"""

from __future__ import annotations

import logging
import os
import sys
import threading

logger = logging.getLogger(__name__)


def _poll_parent(ppid: int) -> None:
    """Exit the process if *ppid* is no longer the parent.

    Two safety checks:
      1. Compare ``os.getppid()`` against the stored *ppid* — if they differ
         the process has been re-parented (e.g. Tauri exited and init adopted
         us), so we exit immediately.
      2. ``os.kill(ppid, 0)`` — confirms the original parent PID is still
         alive in the process table (catches the window before re-parenting).

    Runs as a daemon thread so it does not block normal shutdown.

    ``POLL_INTERVAL`` is read from ``src.main`` (the application root) so the
    existing ``tests/test_main.py`` patch (``patch("src.main.POLL_INTERVAL")``)
    is honoured at runtime.
    """
    import src.main as main_mod

    poll_interval = main_mod.POLL_INTERVAL
    while True:
        threading.Event().wait(poll_interval)

        # Primary check: detect re-parenting
        current_ppid = os.getppid()
        if current_ppid != ppid:
            logger.info(
                "Parent PID changed from %d to %d — shutting down sidecar.",
                ppid,
                current_ppid,
            )
            sys.exit(0)

        # Secondary check: original parent PID no longer exists
        try:
            os.kill(ppid, 0)  # signal 0 = test existence
        except OSError:
            logger.info("Parent PID %d is gone — shutting down sidecar.", ppid)
            sys.exit(0)


def _start_parent_watchdog() -> None:
    """Start the parent watchdog thread if we can determine the parent PID."""
    ppid = os.getppid()
    if ppid > 1:
        thread = threading.Thread(
            target=_poll_parent,
            args=(ppid,),
            daemon=True,
        )
        thread.start()
        logger.debug("Parent watchdog started for PID %d", ppid)
