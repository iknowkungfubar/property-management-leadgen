"""Sidecar package — implementation modules for the IPC entry point.

The previously-monolithic ``src/main.py`` (522 lines) was split into this
package during the arch-extract improvement:

  * ``responses``  — JSON-RPC 2.0 response helpers and error codes
  * ``watchdog``   — parent-process (Tauri) watchdog thread
  * ``dispatch``   — command routing / IPC method handlers
  * ``signals``    — graceful-shutdown signal handlers

Shared stateful globals (``_db_conn``, ``_start_time``, ``POLL_INTERVAL``)
and the ``main()`` entry point live in ``src.main`` (the application root),
which re-exports the symbols below so the ``src.main:main`` console-script
and the existing ``tests/test_main.py`` patches (``patch("src.main.X")``)
keep working.
"""

from __future__ import annotations

from src.sidecar.dispatch import _get_dnc_config, _handle_command
from src.sidecar.responses import (
    ERR_AUTH,
    ERR_INTERNAL,
    ERR_NOT_FOUND,
    ERR_RATELIMIT,
    ERR_UNKNOWN_METHOD,
    ERR_VALIDATION,
    _error_response,
    _success_response,
)
from src.sidecar.signals import _handle_signal, _register_signal_handlers
from src.sidecar.watchdog import _poll_parent, _start_parent_watchdog

__all__ = [
    "_get_dnc_config",
    "_handle_command",
    "_error_response",
    "_success_response",
    "_handle_signal",
    "_register_signal_handlers",
    "_poll_parent",
    "_start_parent_watchdog",
    "ERR_AUTH",
    "ERR_INTERNAL",
    "ERR_NOT_FOUND",
    "ERR_RATELIMIT",
    "ERR_UNKNOWN_METHOD",
    "ERR_VALIDATION",
]
