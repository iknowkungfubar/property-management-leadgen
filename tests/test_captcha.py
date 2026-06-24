"""Tests for the CAPTCHA handler module."""

from __future__ import annotations

import sqlite3

import pytest

from src.captcha.handler import CaptchaHandler

CAPTCHA_HTML: str = (
    "<html><head><title>Just a moment...</title>"
    '<script src="cf-browser-verification"></script></head></html>'
)
CLEAN_HTML: str = "<html><body><h1>Welcome</h1><p>Normal page content.</p></body></html>"


@pytest.fixture
def captcha_handler() -> CaptchaHandler:
    """Provide a CaptchaHandler backed by an in-memory SQLite database."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return CaptchaHandler(conn)


# ── Detection tests ─────────────────────────────────────────────────


class TestDetectBlock:
    """Tests for CaptchaHandler.detect_block."""

    @staticmethod
    def test_detect_block_recognises_cf_verification() -> None:
        """detect_block returns True when cf-browser-verification is present."""
        assert CaptchaHandler.detect_block(CAPTCHA_HTML) is True

    @staticmethod
    def test_detect_block_recognises_recaptcha() -> None:
        """detect_block returns True for g-recaptcha indicator."""
        html = '<html><div class="g-recaptcha" data-sitekey="abc"></div></html>'
        assert CaptchaHandler.detect_block(html) is True

    @staticmethod
    def test_detect_block_recognises_hcaptcha() -> None:
        """detect_block returns True for h-captcha indicator."""
        html = '<html><div class="h-captcha"></div></html>'
        assert CaptchaHandler.detect_block(html) is True

    @staticmethod
    def test_detect_block_recognises_turnstile() -> None:
        """detect_block returns True for Cloudflare Turnstile indicator."""
        html = '<html><div id="turnstile-widget"></div></html>'
        assert CaptchaHandler.detect_block(html) is True

    @staticmethod
    def test_detect_block_returns_false_for_clean_html() -> None:
        """detect_block returns False for normal page content."""
        assert CaptchaHandler.detect_block(CLEAN_HTML) is False

    @staticmethod
    def test_detect_block_empty_string() -> None:
        """detect_block returns False for empty page source."""
        assert CaptchaHandler.detect_block("") is False

    @staticmethod
    def test_detect_block_is_case_insensitive() -> None:
        """detect_block should match indicators case-insensitively."""
        html = "<html>CHECKING YOUR BROWSER</html>"
        assert CaptchaHandler.detect_block(html) is True

    @staticmethod
    def test_detect_block_challenge_platform() -> None:
        """detect_block matches challenge-platform indicator."""
        html = '<html><script src="/cdn-cgi/challenge-platform/scripts/"></script></html>'
        assert CaptchaHandler.detect_block(html) is True

    @staticmethod
    def test_detect_block_cf_chl_opt() -> None:
        """detect_block matches _cf_chl_opt indicator."""
        html = "<html><script>var _cf_chl_opt = {}</script></html>"
        assert CaptchaHandler.detect_block(html) is True


# ── Session save / resume tests ──────────────────────────────────────


class TestSessionState:
    """Tests for CaptchaHandler session persistence."""

    @staticmethod
    def test_save_session_state_without_page(captcha_handler: CaptchaHandler) -> None:
        """save_session_state with no page creates a stub session row."""
        state_id = captcha_handler.save_session_state(target="Orange County Assessor")
        assert isinstance(state_id, str)
        assert len(state_id) == 16  # uuid4().hex[:16]

    @staticmethod
    def test_save_session_state_persists_to_db(captcha_handler: CaptchaHandler) -> None:
        """save_session_state actually writes to the captcha_sessions table."""
        state_id = captcha_handler.save_session_state(target="Test Portal")
        row = captcha_handler._db.execute(
            "SELECT data FROM captcha_sessions WHERE state_id = ?",
            (state_id,),
        ).fetchone()
        assert row is not None
        import json

        data = json.loads(row[0])
        assert data["target"] == "Test Portal"
        assert data["_stub"] is True

    @staticmethod
    def test_resume_from_session_reads_back_state(captcha_handler: CaptchaHandler) -> None:
        """resume_from_session returns the same data that was saved."""
        state_id = captcha_handler.save_session_state(target="Craigslist")
        result = captcha_handler.resume_from_session(state_id)
        assert "_error" not in result
        assert result["target"] == "Craigslist"
        assert result["_stub"] is True

    @staticmethod
    def test_resume_from_session_unknown_id(captcha_handler: CaptchaHandler) -> None:
        """resume_from_session returns error dict for unknown state_id.

        First saves a session to ensure the table exists, then queries
        a different (non-existent) ID.
        """
        captcha_handler.save_session_state(target="Priming")
        result = captcha_handler.resume_from_session("nonexistent-id")
        assert "_error" in result
        assert "No saved session" in result["_error"]

    @staticmethod
    def test_multiple_sessions_independent(captcha_handler: CaptchaHandler) -> None:
        """Multiple saved sessions can be independently retrieved."""
        id1 = captcha_handler.save_session_state(target="Portal A")
        id2 = captcha_handler.save_session_state(target="Portal B")

        r1 = captcha_handler.resume_from_session(id1)
        r2 = captcha_handler.resume_from_session(id2)

        assert r1["target"] == "Portal A"
        assert r2["target"] == "Portal B"

    @staticmethod
    def test_save_session_with_custom_db_table_creation(captcha_handler: CaptchaHandler) -> None:
        """save_session_state creates the captcha_sessions table if absent."""
        # Drop the table to test auto-creation
        captcha_handler._db.execute("DROP TABLE IF EXISTS captcha_sessions")
        state_id = captcha_handler.save_session_state(target="After Drop")
        assert isinstance(state_id, str)
        tables = captcha_handler._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='captcha_sessions'",
        ).fetchall()
        assert len(tables) == 1


# ── IPC event tests ──────────────────────────────────────────────────


class TestEmitCaptchaEvent:
    """Tests for CaptchaHandler.emit_captcha_event."""

    @staticmethod
    def test_emit_captcha_event_returns_correct_dict() -> None:
        """emit_captcha_event returns the expected IPC event shape."""
        event = CaptchaHandler.emit_captcha_event("Test Portal", state_id="abc123")
        assert event is not None
        assert event["event"] == "captcha_detected"
        assert event["target"] == "Test Portal"
        assert event["state_id"] == "abc123"

    @staticmethod
    def test_emit_captcha_event_returns_none_without_state_id() -> None:
        """emit_captcha_event returns None when state_id is not provided."""
        result = CaptchaHandler.emit_captcha_event("Test Portal")
        assert result is None

    @staticmethod
    def test_emit_captcha_event_round_trip(captcha_handler: CaptchaHandler) -> None:
        """emit_captcha_event with a real saved state_id produces a usable key."""
        state_id = captcha_handler.save_session_state(target="Real Portal")
        event = CaptchaHandler.emit_captcha_event("Real Portal", state_id=state_id)
        assert event is not None
        assert event["state_id"] == state_id

        # Verify the state_id is actually usable
        session = captcha_handler.resume_from_session(event["state_id"])
        assert "_error" not in session
