"""CAPTCHA/interactive-block detection and Tauri modal integration.

When an automated agent detects an anti-bot page, it captures the current
browser session state, pauses automation, and emits an IPC event so the
Tauri frontend can display a modal.  The user resolves the challenge in a
headed browser, then resumes from the saved session.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

CAPTCHA_INDICATORS: list[str] = [
    "cf-browser-verification",
    "g-recaptcha",
    "h-captcha",
    "turnstile",
    "challenge-platform",
    "_cf_chl_opt",
    "just a moment",
    "checking your browser",
]


class CaptchaHandler:
    """Manage CAPTCHA detection, session save/restore, and IPC events."""

    def __init__(self, db_path: str) -> None:
        """Store the database path for session persistence.

        Args:
            db_path: Filesystem path to the SQLite database.

        """
        self._db_path = db_path

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    @staticmethod
    def detect_block(page_source: str) -> bool:
        """Check whether the page HTML contains common anti-bot indicators.

        Args:
            page_source: The full HTML source of the rendered page.

        Returns:
            ``True`` if at least one CAPTCHA/challenge indicator is found.

        """
        lowered = page_source.lower()
        for indicator in CAPTCHA_INDICATORS:
            if indicator in lowered:
                logger.info("CAPTCHA indicator detected: '%s'", indicator)
                return True
        return False

    # ------------------------------------------------------------------
    # Session save / resume
    # ------------------------------------------------------------------

    def save_session_state(
        self,
        page: Any = None,  # playwright Page (optional — saves minimal entry when absent)
        target: str = "",
    ) -> str:
        """Capture browser cookies and localStorage, persist them, return a state ID.

        When *page* is ``None``, a minimal entry (target-only) is saved so the
        returned state ID is always usable with :meth:`resume_from_session`.

        Args:
            page: A Playwright ``Page`` instance, or ``None`` for a stub entry.
            target: Human-readable name of the portal triggering the block.

        Returns:
            A unique state ID string that can be used to resume later.

        """
        state_id = uuid.uuid4().hex[:16]
        session_data: dict[str, Any]

        if page is not None:
            try:
                import playwright.sync_api  # noqa: PLC0415 — lazy import
            except ImportError:
                logger.warning("Playwright not available — using stub session data.")
                session_data = {"target": target, "url": "", "_stub": True}
            else:
                try:
                    cookies = page.context.cookies()
                    storage = page.evaluate("() => JSON.stringify(localStorage)")
                    session_data = {
                        "cookies": cookies,
                        "local_storage": storage,
                        "target": target,
                        "url": page.url,
                    }
                except Exception as exc:
                    logger.exception("Failed to capture session state: %s", exc)
                    url = getattr(page, "url", "")
                    session_data = {
                        "cookies": [],
                        "local_storage": "{}",
                        "target": target,
                        "url": url,
                    }
        else:
            session_data = {"target": target, "url": "", "_stub": True}

        # Persist the session data as JSON
        import sqlite3  # noqa: PLC0415

        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS captcha_sessions ("
            "  state_id TEXT PRIMARY KEY,"
            "  data TEXT NOT NULL,"
            "  created_at TEXT DEFAULT (datetime('now'))"
            ")",
        )
        conn.execute(
            "INSERT OR REPLACE INTO captcha_sessions (state_id, data) VALUES (?, ?)",
            (state_id, json.dumps(session_data)),
        )
        conn.commit()
        conn.close()

        logger.info("Session state saved as '%s' from %s", state_id, target)
        return state_id

    def resume_from_session(self, state_id: str) -> dict[str, Any]:
        """Read a previously saved session state.

        Args:
            state_id: The ID returned by :meth:`save_session_state`.

        Returns:
            The stored session data dictionary, or an error dict if missing.

        """
        import sqlite3  # noqa: PLC0415

        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT data FROM captcha_sessions WHERE state_id = ?",
            (state_id,),
        ).fetchone()
        conn.close()

        if not row:
            logger.warning("No session found for state_id '%s'", state_id)
            return {"_error": f"No saved session for id '{state_id}'"}

        try:
            return dict(json.loads(row[0]))
        except (json.JSONDecodeError, TypeError) as exc:
            logger.exception("Corrupt session data for '%s': %s", state_id, exc)
            return {"_error": f"Corrupt session data: {exc}"}

    # ------------------------------------------------------------------
    # IPC event
    # ------------------------------------------------------------------

    @staticmethod
    def emit_captcha_event(
        target: str,
        state_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return a structured event dict the Tauri frontend can display.

        *state_id* MUST have been previously persisted via
        :meth:`save_session_state` so the frontend can later call
        :meth:`resume_from_session` with a valid key.

        Args:
            target: Name of the portal triggering the CAPTCHA.
            state_id: A persisted session ID from :meth:`save_session_state`.
                When ``None``, ``None`` is returned and no event is emitted.

        Returns:
            An event dict matching the IPC schema::

                { "event": "captcha_detected", "target": str, "state_id": str }

            or ``None`` when *state_id* is not provided.

        """
        if state_id is None:
            logger.warning(
                "emit_captcha_event called without a state_id — no event emitted.",
            )
            return None

        event: dict[str, Any] = {
            "event": "captcha_detected",
            "target": target,
            "state_id": state_id,
        }
        logger.info("Emitting CAPTCHA event: %s", event)
        return event
