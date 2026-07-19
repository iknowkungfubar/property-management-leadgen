"""Sidecar entry point — stdin/stdout JSON IPC loop.

This module is the application root for the sidecar. It owns the shared
stateful globals (``_db_conn``, ``_start_time``, ``POLL_INTERVAL``) and the
``main()`` loop, and re-exports the implementation living in the
``src.sidecar`` package (extracted from this file during the arch-extract
improvement). Re-exporting every symbol here keeps the ``src.main:main``
console-script entry point and the existing ``tests/test_main.py`` patches
(``patch("src.main.X")``) working unchanged.

The parent PID polling thread monitors the parent process — if the parent
(Tauri) dies, the sidecar gracefully exits.
"""

from __future__ import annotations

import sys

# When launched via ``python -m src.main``, Python executes this file with
# ``__name__ == "__main__"`` and does NOT register it as ``src.main`` in
# ``sys.modules``. The extracted submodules (``src.sidecar.dispatch``) import
# ``src.main`` lazily to read the live ``_db_conn`` global. Without the alias
# below, that import would create a *second*, uninitialised copy of this module
# (``_db_conn`` stays ``None``) and the sidecar would crash in production. Pull
# the running module into ``sys.modules["src.main"]`` up front so the two names
# resolve to the same object.
if __name__ == "__main__":
    sys.modules.setdefault("src.main", sys.modules["__main__"])

import json
import logging
import os
import sys
import threading  # Re-exported: tests patch ``src.main.threading``.
import time
from pathlib import Path
from typing import Any

from src.db.connection import get_connection
from src.db.migrations import run_migrations
from src.db.schema import apply_schema
from src.llm.factory import (
    get_active_llm_client,  # Re-exported: read by src.sidecar.dispatch.
)
from src.sidecar import (
    ERR_AUTH,
    ERR_INTERNAL,
    ERR_NOT_FOUND,
    ERR_RATELIMIT,
    ERR_UNKNOWN_METHOD,
    ERR_VALIDATION,
    _error_response,
    _get_dnc_config,
    _handle_command,
    _handle_signal,
    _poll_parent,
    _register_signal_handlers,
    _start_parent_watchdog,
    _success_response,
)
from src.utils.credentials import (
    get_credential,  # Re-exported: read by src.sidecar.dispatch.
    migrate_from_sqlite,
    store_credential,  # Re-exported: read by src.sidecar.dispatch.
)
from src.utils.logging import setup_logging

logger = logging.getLogger(__name__)

# Module-level globals shared with the extracted submodules. They are read
# lazily by ``src.sidecar.dispatch`` / ``src.sidecar.watchdog`` via
# ``import src.main`` so that ``patch("src.main.X")`` in tests stays live.
POLL_INTERVAL: float = 5.0

_db_conn: Any = None
"""Module-level persistent database connection. Set once in main()."""

_start_time: float = 0.0
"""Timestamp (monotonic clock) when the sidecar started. Used for health checks."""


def main() -> None:
    """Entry point: read JSON commands from stdin, write responses to stdout.

    Opens a persistent database connection at startup. The loop terminates
    cleanly on EOF (stdin close) which happens when the Tauri sidecar
    process is killed.

    """
    global _db_conn, _start_time

    _start_time = time.time()

    # Configure structured JSON logging (with rotation and crash recovery).
    setup_logging(level=logging.INFO, json_format=True)
    logger.info("Sidecar starting (PID %d)", os.getpid())

    _register_signal_handlers()
    _start_parent_watchdog()

    db_path = os.environ.get(
        "LEADGEN_DB_PATH",
        str(Path.home() / ".leadgen" / "leadgen.db"),
    )

    # Ensure the database and schema exist up front
    _db_conn = get_connection(db_path)
    apply_schema(_db_conn)
    run_migrations(_db_conn)

    # Migrate any existing plaintext API keys to OS keychain
    migrated = migrate_from_sqlite(_db_conn)
    if migrated:
        logger.info("Migrated %d API key(s) to OS keychain", migrated)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            cmd: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.exception("Invalid JSON from stdin: %s", exc)
            response = _error_response(None, f"Parse error: {exc}", ERR_VALIDATION)
        else:
            if not isinstance(cmd, dict):
                response = _error_response(
                    None,
                    "Parse error: Expected JSON object",
                    ERR_VALIDATION,
                )
            else:
                response = _handle_command(cmd)

        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

    logger.info("Sidecar stdin closed — exiting.")
    _db_conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.exception("Unhandled exception in main(): %s", exc)
        sys.exit(1)


__all__ = [
    "main",
    "_db_conn",
    "_start_time",
    "POLL_INTERVAL",
    "os",
    "threading",
    "json",
    "get_credential",
    "get_active_llm_client",
    "store_credential",
    "apply_schema",
    "run_migrations",
    "ERR_AUTH",
    "ERR_RATELIMIT",
    "ERR_NOT_FOUND",
    "ERR_INTERNAL",
    "ERR_VALIDATION",
    "ERR_UNKNOWN_METHOD",
    "_error_response",
    "_success_response",
    "_handle_command",
    "_get_dnc_config",
    "_poll_parent",
    "_start_parent_watchdog",
    "_handle_signal",
    "_register_signal_handlers",
]
