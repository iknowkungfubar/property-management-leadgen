"""Signal handlers for graceful sidecar shutdown.

Extracted from the monolithic ``src/main.py``.
"""

from __future__ import annotations

import logging
import signal
import sys

logger = logging.getLogger(__name__)


def _handle_signal(signum: int, _frame: object) -> None:
    """Flush logs and exit cleanly on SIGTERM / SIGINT."""
    sig_name = signal.Signals(signum).name
    logger.info("Received %s — shutting down sidecar.", sig_name)
    logging.shutdown()
    sys.exit(0)


def _register_signal_handlers() -> None:
    """Register graceful shutdown handlers for termination signals."""
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    logger.debug("Signal handlers registered (SIGTERM, SIGINT).")
