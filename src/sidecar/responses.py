"""JSON-RPC 2.0 response helpers and error codes for the sidecar IPC loop.

Extracted from the monolithic ``src/main.py`` during the arch-extract
improvement so the dispatcher and response shaping live in one focused module.
"""

from __future__ import annotations

from typing import Any

# ── Error codes ─────────────────────────────────────────────────────

ERR_AUTH: int = -10000
ERR_RATELIMIT: int = -20000
ERR_NOT_FOUND: int = -30000
ERR_INTERNAL: int = -40000
ERR_VALIDATION: int = -50000
ERR_UNKNOWN_METHOD: int = -60000


def _error_response(
    request_id: str | None,
    message: str,
    code: int = ERR_INTERNAL,
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _success_response(
    request_id: str | None,
    result: Any,
) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}
