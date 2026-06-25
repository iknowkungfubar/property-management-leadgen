"""Sidecar entrypoint — stdin/stdout JSON IPC loop.

Reads JSON command objects from stdin line-by-line, dispatches to the
appropriate module, and writes JSON response objects to stdout.

The parent PID polling thread monitors the parent process — if the parent
(Tauri) dies, the sidecar gracefully exits.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

from src.agents.discovery import DiscoveryAgent
from src.agents.entity_unmasking import EntityUnmaskingAgent
from src.agents.market_intelligence import MarketIntelligenceAgent
from src.agents.output_synthesis import OutputSynthesisAgent
from src.captcha.handler import CaptchaHandler
from src.compliance.dnc_checker import (
    DNCConfig,
    add_dnc_number,
    check_dnc,
    remove_dnc_number,
)
from src.db.connection import get_connection
from src.db.migrations import run_migrations
from src.db.schema import apply_schema
from src.llm.factory import get_active_llm_client
from src.utils.credentials import (
    get_credential,
    migrate_from_sqlite,
    store_credential,
)
from src.utils.hubspot_client import (
    HubSpotAuthError,
    HubSpotClient,
    HubSpotRateLimitError,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL: float = 5.0

# ── Error codes ─────────────────────────────────────────────────────

ERR_AUTH: int = -10000
ERR_RATELIMIT: int = -20000
ERR_NOT_FOUND: int = -30000
ERR_INTERNAL: int = -40000
ERR_VALIDATION: int = -50000
ERR_UNKNOWN_METHOD: int = -60000

# ── Persistent DB connection ────────────────────────────────────────

_db_conn: Any = None
"""Module-level persistent database connection. Set once in main()."""


# ── Parent watchdog ──────────────────────────────────────────────────


def _poll_parent(ppid: int) -> None:
    """Exit the process if *ppid* is no longer the parent.

    Two safety checks:
      1. Compare ``os.getppid()`` against the stored *ppid* — if they differ
         the process has been re‑parented (e.g. Tauri exited and init adopted
         us), so we exit immediately.
      2. ``os.kill(ppid, 0)`` — confirms the original parent PID is still
         alive in the process table (catches the window before re‑parenting).

    Runs as a daemon thread so it does not block normal shutdown.
    """
    while True:
        threading.Event().wait(POLL_INTERVAL)

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


def _get_dnc_config(conn) -> DNCConfig:
    """Read DNC configuration from the settings table."""
    row = conn.execute(
        "SELECT value FROM settings WHERE key = 'dnc_blocked_area_codes'",
    ).fetchone()
    area_codes = []
    if row and row[0]:
        area_codes = [c.strip() for c in row[0].split(",") if c.strip()]
    return DNCConfig(
        enabled=True,
        area_codes=area_codes,
        block_international=True,
    )


# ── IPC dispatcher ────────────────────────────────────────────────────


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


def _handle_command(
    cmd: dict[str, Any],
) -> dict[str, Any]:
    """Route a single command dict to the appropriate handler.

    Args:
        cmd: Parsed JSON command object with ``id``, ``method``, ``params``.

    Returns:
        Response dict following a simple JSON-RPC 2.0 shape.

    """
    req_id = cmd.get("id")
    method: str = cmd.get("method", "")
    params: dict[str, Any] = cmd.get("params", {})

    conn = _db_conn
    try:
        if method == "ping":
            return _success_response(req_id, {"pong": True})

        if method == "schema.apply":
            apply_schema(conn)
            run_migrations(conn)
            return _success_response(req_id, "Schema applied.")

        if method == "discovery.import_csv":
            agent = DiscoveryAgent(conn)
            file_path: str = params.get("file_path", "")
            if not file_path:
                return _error_response(req_id, "Missing file_path", ERR_VALIDATION)
            # Resolve path and prevent traversal attacks
            resolved = Path(file_path).resolve()
            if ".." in Path(file_path).parts or not resolved.is_file():
                return _error_response(req_id, "Invalid file path", ERR_VALIDATION)
            records = agent.parse_csv_import(str(resolved))
            stored = agent.save_to_database(records)
            return _success_response(req_id, {"imported": stored})

        if method == "discovery.normalize_apn":
            result = DiscoveryAgent.normalize_apn(
                params.get("address", ""),
                params.get("county", ""),
            )
            return _success_response(req_id, {"apn": result})

        if method == "entity.unmask":
            agent = EntityUnmaskingAgent()
            try:
                llm = get_active_llm_client(conn)
            except ValueError:
                llm = None
            apn = params.get("apn", "")
            recorded_owner = params.get("recorded_owner", "")
            if not apn or not recorded_owner:
                return _error_response(req_id, "Missing apn or recorded_owner", ERR_VALIDATION)
            result = agent.unmask_entity(
                apn=apn,
                recorded_owner=recorded_owner,
            )
            if result.get("needs_sos_lookup") and llm is not None:
                logger.info("Performing CA SoS look-up for '%s' …", recorded_owner)
                sos_result = agent.perform_sos_lookup(
                    recorded_owner=recorded_owner,
                    llm_client=llm,
                )
                if sos_result.get("status") == "found" and sos_result.get("principals"):
                    first = sos_result["principals"][0]
                    result["unmasked_principal_name"] = first.get("name")
                    result["unmasked_principal_phone"] = first.get("phone")
                result["sos_lookup"] = sos_result
            return _success_response(req_id, result)

        if method == "market.score":
            agent = MarketIntelligenceAgent(conn)
            score = agent.calculate_priority_score(
                vacancy_risk=params.get("vacancy_risk", 0.0),
                rental_yield_delta=params.get("rental_yield_delta", 0.0),
                competitor_sentiment=params.get("competitor_sentiment", 0.0),
            )
            return _success_response(req_id, {"priority_score": score})

        if method == "output.export_csv":
            agent = OutputSynthesisAgent()
            leads = params.get("leads", [])
            csv_output = agent.format_lead_export(leads, export_format="csv")
            return _success_response(req_id, {"csv": csv_output})

        if method == "output.export_json":
            agent = OutputSynthesisAgent()
            leads = params.get("leads", [])
            json_output = agent.format_lead_export(leads, export_format="json")
            return _success_response(req_id, {"json": json_output})

        if method == "output.export_hubspot":
            # Read HubSpot API key from settings
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'hubspot_api_key'",
            ).fetchone()
            api_key: str = (row["value"] if row else "") or ""
            if not api_key:
                return _error_response(
                    req_id,
                    "HubSpot API key not configured — set hubspot_api_key in settings",
                    ERR_VALIDATION,
                )

            hubspot_client = HubSpotClient(api_key)
            agent = OutputSynthesisAgent(hubspot_client=hubspot_client)
            leads = params.get("leads", [])
            if not leads:
                return _error_response(req_id, "Missing leads parameter", ERR_VALIDATION)

            try:
                result = agent.export_to_hubspot(leads)
                return _success_response(req_id, result)
            except HubSpotAuthError as exc:
                return _error_response(
                    req_id,
                    f"HubSpot authentication failed: {exc}",
                    ERR_AUTH,
                )
            except HubSpotRateLimitError as exc:
                return _error_response(
                    req_id,
                    f"HubSpot rate limit exceeded: {exc}",
                    ERR_RATELIMIT,
                )
            except ValueError as exc:
                return _error_response(req_id, str(exc), ERR_VALIDATION)
            finally:
                hubspot_client.close()

        if method == "compliance.dnc_check":
            phone = params.get("phone", "")
            if not phone:
                return _error_response(req_id, "Missing 'phone' parameter", ERR_VALIDATION)
            is_dnc = check_dnc(phone, db_conn=conn)
            config = _get_dnc_config(conn)
            return _success_response(
                req_id,
                {
                    "is_dnc": is_dnc,
                    "enabled": config.enabled,
                },
            )

        if method == "compliance.add_dnc":
            phone = params.get("phone", "")
            source = params.get("source", "manual")
            if not phone:
                return _error_response(req_id, "Missing 'phone' parameter", ERR_VALIDATION)
            added = add_dnc_number(conn, phone, source)
            return _success_response(req_id, {"added": added})

        if method == "compliance.remove_dnc":
            phone = params.get("phone", "")
            if not phone:
                return _error_response(req_id, "Missing 'phone' parameter", ERR_VALIDATION)
            removed = remove_dnc_number(conn, phone)
            return _success_response(req_id, {"removed": removed})

        if method == "captcha.detect":
            handler = CaptchaHandler(_db_conn)
            detected = handler.detect_block(params.get("page_source", ""))
            return _success_response(req_id, {"blocked": detected})

        if method == "captcha.emit_event":
            handler = CaptchaHandler(_db_conn)
            target = params.get("target", "")
            state_id = handler.save_session_state(target=target)
            event = CaptchaHandler.emit_captcha_event(target, state_id=state_id)
            if event is not None:
                sys.stdout.write(json.dumps(event) + "\n")
                sys.stdout.flush()
            return _success_response(req_id, event)

        if method == "llm_settings.set":
            provider = params.get("provider", "")
            api_key = params.get("api_key", "")
            # Store key in OS keychain if provided
            if api_key and not api_key.endswith("****"):
                store_credential(f"llm/{provider}/api_key", api_key)
            conn.execute(
                "INSERT OR REPLACE INTO llm_settings "
                "(provider, api_key, base_url, selected_model, is_active) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    provider,
                    api_key[:4] + "****" if api_key and len(api_key) > 4 else (api_key or ""),
                    params.get("base_url", ""),
                    params.get("selected_model", ""),
                    1 if params.get("is_active") else 0,
                ),
            )
            conn.commit()
            return _success_response(req_id, "OK")
        if method == "llm_settings.get":
            rows = conn.execute(
                "SELECT provider, api_key, base_url, selected_model, is_active "
                "FROM llm_settings ORDER BY provider",
            ).fetchall()
            # Mask API keys in responses; try keychain for full key
            masked = []
            for r in rows:
                d = dict(r)
                if d.get("api_key"):
                    # Try to get the real key from keychain
                    keychain_key = f"llm/{d['provider']}/api_key"
                    real_key = get_credential(keychain_key)
                    if real_key:
                        d["api_key"] = real_key[:4] + "****"
                    else:
                        d["api_key"] = (
                            d["api_key"][:4] + "****" if len(d["api_key"]) > 4 else "****"
                        )
                masked.append(d)
            return _success_response(req_id, masked)

        if method == "settings.get":
            key = params.get("key", "")
            if not key:
                return _error_response(req_id, "Missing key", ERR_VALIDATION)
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                (key,),
            ).fetchone()
            return _success_response(req_id, {"value": row["value"] if row else None})

        if method == "settings.set":
            key = params.get("key", "")
            value = params.get("value", "")
            if not key:
                return _error_response(req_id, "Missing key", ERR_VALIDATION)
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
            conn.commit()
            return _success_response(req_id, "OK")

        return _error_response(req_id, f"Unknown method: {method}", ERR_UNKNOWN_METHOD)

    except KeyError as exc:
        logger.exception("Missing required parameter for '%s': %s", method, exc)
        return _error_response(req_id, f"Missing parameter: {exc}", ERR_VALIDATION)
    except ValueError as exc:
        logger.exception("Validation error in '%s': %s", method, exc)
        return _error_response(req_id, str(exc), ERR_VALIDATION)
    except Exception as exc:
        logger.exception("Error handling method '%s'", method)
        return _error_response(req_id, str(exc), ERR_INTERNAL)


# ── Main loop ─────────────────────────────────────────────────────────


def main() -> None:
    """Entry point: read JSON commands from stdin, write responses to stdout.

    Opens a persistent database connection at startup. The loop terminates
    cleanly on EOF (stdin close) which happens when the Tauri sidecar
    process is killed.

    """
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logger.info("Sidecar starting (PID %d)", os.getpid())

    _start_parent_watchdog()

    db_path = os.environ.get(
        "LEADGEN_DB_PATH",
        str(Path.home() / ".leadgen" / "leadgen.db"),
    )

    # Ensure the database and schema exist up front
    global _db_conn
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
    main()
