"""IPC router — routes Tauri commands to registered handlers.

Extracted from main.py to make each command handler independently testable.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Error codes
ERR_VALIDATION = -32000
ERR_EXECUTION = -32001
ERR_NOT_FOUND = -32002

# Handler type: (params) -> dict
CommandHandler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


class IpcRouter:
    """Routes JSON-RPC-style commands to registered handlers."""

    def __init__(self):
        self._handlers: dict[str, CommandHandler] = {}
        self._shared: dict[str, Any] = {}  # shared state (db conn, etc.)

    def register(self, method: str, handler: CommandHandler) -> None:
        """Register a handler for a method name."""
        self._handlers[method] = handler

    def set_shared(self, key: str, value: Any) -> None:
        """Set shared state accessible to handlers."""
        self._shared[key] = value

    def handle(self, cmd: dict[str, Any]) -> dict[str, Any]:
        """Route a command to its registered handler.

        Args:
            cmd: JSON-RPC-style command with id, method, params.

        Returns:
            Response dict with result or error.
        """
        req_id = cmd.get("id")
        method: str = cmd.get("method", "")
        params: dict[str, Any] = cmd.get("params", {})

        handler = self._handlers.get(method)
        if handler is None:
            return _error_response(req_id, f"Unknown method: {method}", ERR_NOT_FOUND)

        try:
            result = handler(params, self._shared)
            return _success_response(req_id, result)
        except Exception as e:
            logger.exception("Handler failed for method: %s", method)
            return _error_response(req_id, str(e), ERR_EXECUTION)


def _success_response(req_id: Any, data: Any) -> dict[str, Any]:
    """Build a success response matching JSON-RPC 2.0 shape."""
    return {"id": req_id, "result": data, "error": None}


def _error_response(req_id: Any, message: str, code: int = ERR_EXECUTION) -> dict[str, Any]:
    """Build an error response matching JSON-RPC 2.0 shape."""
    return {"id": req_id, "result": None, "error": {"message": message, "code": code}}
