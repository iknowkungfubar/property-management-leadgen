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
from typing import Any

from src.agents.discovery import DiscoveryAgent
from src.agents.entity_unmasking import EntityUnmaskingAgent
from src.agents.market_intelligence import MarketIntelligenceAgent
from src.agents.output_synthesis import OutputSynthesisAgent
from src.captcha.handler import CaptchaHandler
from src.compliance.dnc_checker import check_dnc
from src.db.connection import get_connection
from src.db.migrations import run_migrations
from src.db.schema import apply_schema
from src.llm.factory import get_active_llm_client

logger = logging.getLogger(__name__)

POLL_INTERVAL: float = 5.0


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
    # PID 1 typically means orphaned (e.g. running via ``cargo tauri dev``
    # may re-parent).  Only watch if we have a real parent.
    if ppid > 1:
        thread = threading.Thread(
            target=_poll_parent,
            args=(ppid,),
            daemon=True,
        )
        thread.start()
        logger.debug("Parent watchdog started for PID %d", ppid)


# ── IPC dispatcher ────────────────────────────────────────────────────


def _error_response(
    request_id: str | None,
    message: str,
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -1, "message": message},
    }


def _success_response(
    request_id: str | None,
    result: Any,
) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _handle_command(
    cmd: dict[str, Any],
    db_path: str,
) -> dict[str, Any]:
    """Route a single command dict to the appropriate handler.

    Args:
        cmd: Parsed JSON command object.  Expected keys:
            ``id`` (optional str), ``method`` (str), ``params`` (dict).
        db_path: Path to the SQLite database file.

    Returns:
        Response dict following a simple JSON-RPC 2.0 shape.

    """
    req_id = cmd.get("id")
    method: str = cmd.get("method", "")
    params: dict[str, Any] = cmd.get("params", {})

    conn = get_connection(db_path)
    try:
        if method == "ping":
            return _success_response(req_id, {"pong": True})

        if method == "schema.apply":
            apply_schema(conn)
            run_migrations(conn)
            return _success_response(req_id, "Schema applied.")

        if method == "discovery.import_csv":
            agent = DiscoveryAgent(conn)
            file_path = params["file_path"]
            records = agent.parse_csv_import(file_path)
            stored = agent.save_to_database(records)
            return _success_response(req_id, {"imported": stored})

        if method == "discovery.normalize_apn":
            result = DiscoveryAgent.normalize_apn(
                params["address"], params["county"],
            )
            return _success_response(req_id, {"apn": result})

        if method == "entity.unmask":
            agent = EntityUnmaskingAgent()
            try:
                llm = get_active_llm_client(conn)
            except ValueError:
                llm = None
            result = agent.unmask_entity(
                apn=params["apn"],
                recorded_owner=params["recorded_owner"],
                llm_client=llm,
            )
            # If the entity needs SOS look-up, perform it now
            if result.get("needs_sos_lookup") and llm is not None:
                logger.info(
                    "Performing CA SoS look-up for '%s' …",
                    params["recorded_owner"],
                )
                sos_result = agent.perform_sos_lookup(
                    recorded_owner=params["recorded_owner"],
                    llm_client=llm,
                )
                if sos_result.get("status") == "found" and sos_result.get("principals"):
                    # Use the first principal's name and phone
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
            agent = OutputSynthesisAgent(conn)
            leads = params.get("leads", [])
            csv_output = agent.format_lead_export(leads, export_format="csv")
            return _success_response(req_id, {"csv": csv_output})

        if method == "output.export_json":
            agent = OutputSynthesisAgent(conn)
            leads = params.get("leads", [])
            json_output = agent.format_lead_export(leads, export_format="json")
            return _success_response(req_id, {"json": json_output})

        if method == "compliance.dnc_check":
            is_dnc = check_dnc(params["phone"])
            return _success_response(req_id, {"is_dnc": is_dnc})

        if method == "captcha.detect":
            handler = CaptchaHandler(db_path)
            detected = handler.detect_block(params.get("page_source", ""))
            return _success_response(req_id, {"blocked": detected})

        if method == "captcha.emit_event":
            handler = CaptchaHandler(db_path)
            target = params.get("target", "")
            # Persist a session state first so the state_id is real
            state_id = handler.save_session_state(target=target)
            event = CaptchaHandler.emit_captcha_event(target, state_id=state_id)
            # Write the event as a standalone JSON line BEFORE the response
            # so the Rust sidecar_command handler can buffer it as an
            # unsolicited event for the frontend to poll.
            if event is not None:
                sys.stdout.write(json.dumps(event) + "\n")
                sys.stdout.flush()
            return _success_response(req_id, event)

        if method == "llm_settings.set":
            conn.execute(
                "INSERT OR REPLACE INTO llm_settings "
                "(provider, api_key, base_url, selected_model, is_active) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    params["provider"],
                    params.get("api_key", ""),
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
            return _success_response(
                req_id, [dict(r) for r in rows],
            )

        if method == "settings.get":
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (params["key"],),
            ).fetchone()
            return _success_response(req_id, {"value": row["value"] if row else None})

        if method == "settings.set":
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (params["key"], params["value"]),
            )
            conn.commit()
            return _success_response(req_id, "OK")

        # Fallback
        return _error_response(req_id, f"Unknown method: {method}")

    except Exception as exc:
        logger.exception("Error handling method '%s'", method)
        return _error_response(req_id, str(exc))
    finally:
        conn.close()


# ── Main loop ─────────────────────────────────────────────────────────


def main() -> None:
    """Entry point: read JSON commands from stdin, write responses to stdout.

    The loop terminates cleanly on EOF (stdin close) which happens when
    the Tauri sidecar process is killed.

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
        os.path.join(os.path.expanduser("~"), ".leadgen", "leadgen.db"),
    )

    # Ensure the database and schema exist up front
    conn = get_connection(db_path)
    apply_schema(conn)
    run_migrations(conn)
    conn.close()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            cmd: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.exception("Invalid JSON from stdin: %s", exc)
            response = _error_response(None, f"Parse error: {exc}")
        else:
            response = _handle_command(cmd, db_path)

        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

    logger.info("Sidecar stdin closed — exiting.")


if __name__ == "__main__":
    main()
