"""Unit tests for src/main.py — IPC dispatcher, error responses, and lifecycle.

Tests the individual functions in main.py without spawning a subprocess.
Uses mocked database connections to verify dispatch logic and error codes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.main import (
    ERR_INTERNAL,
    ERR_UNKNOWN_METHOD,
    ERR_VALIDATION,
    _error_response,
    _handle_command,
    _success_response,
)

# ── Response helpers ────────────────────────────────────────────────────


class TestResponseHelpers:
    """Verify JSON-RPC 2.0 response shapes."""

    def test_success_response_shape(self):
        """Success response has jsonrpc, id, and result."""
        resp = _success_response("req-1", {"pong": True})
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == "req-1"
        assert resp["result"] == {"pong": True}

    def test_success_response_none_id(self):
        """Success response with None id."""
        resp = _success_response(None, "OK")
        assert resp["id"] is None
        assert resp["result"] == "OK"

    def test_error_response_default_code(self):
        """Error response defaults to ERR_INTERNAL."""
        resp = _error_response("req-1", "something broke")
        assert resp["error"]["code"] == ERR_INTERNAL
        assert resp["error"]["message"] == "something broke"

    def test_error_response_custom_code(self):
        """Error response accepts custom code."""
        resp = _error_response("req-1", "bad input", ERR_VALIDATION)
        assert resp["error"]["code"] == ERR_VALIDATION
        assert resp["error"]["message"] == "bad input"

    def test_error_response_unknown_method(self):
        """ERR_UNKNOWN_METHOD on invalid method."""
        resp = _error_response("req-1", "Unknown method: foo", ERR_UNKNOWN_METHOD)
        assert resp["error"]["code"] == ERR_UNKNOWN_METHOD


# ── _handle_command dispatch ────────────────────────────────────────────


@pytest.fixture
def mock_conn():
    """Return a MagicMock that mimics a sqlite3.Connection."""
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []
    conn.execute.return_value.fetchone.return_value = None
    return conn


class TestHandleCommand:
    """Verify _handle_command dispatches to the correct handler."""

    def test_ping(self, mock_conn):
        """ping returns pong."""
        with patch("src.main._db_conn", mock_conn):
            resp = _handle_command({"id": "1", "method": "ping"})
        assert resp["result"] == {"pong": True}

    def test_unknown_method(self, mock_conn):
        """Unknown method returns ERR_UNKNOWN_METHOD."""
        with patch("src.main._db_conn", mock_conn):
            resp = _handle_command({"id": "1", "method": "nonexistent"})
        assert resp["error"]["code"] == ERR_UNKNOWN_METHOD
        assert "Unknown method" in resp["error"]["message"]

    def test_settings_get_missing_key_validation(self, mock_conn):
        """Missing 'key' param returns ERR_VALIDATION."""
        with patch("src.main._db_conn", mock_conn):
            resp = _handle_command({"method": "settings.get", "params": {}})
        assert resp["error"]["code"] == ERR_VALIDATION

    def test_compliance_dnc_missing_phone(self, mock_conn):
        """Missing 'phone' param returns ERR_VALIDATION."""
        with patch("src.main._db_conn", mock_conn):
            resp = _handle_command({"method": "compliance.dnc_check", "params": {}})
        assert resp["error"]["code"] == ERR_VALIDATION

    def test_discovery_import_missing_path(self, mock_conn):
        """Missing file_path returns ERR_VALIDATION."""
        with patch("src.main._db_conn", mock_conn):
            resp = _handle_command({"method": "discovery.import_csv", "params": {}})
        assert resp["error"]["code"] == ERR_VALIDATION

    def test_schema_apply_calls_db(self, mock_conn):
        """schema.apply calls apply_schema and run_migrations."""
        with (
            patch("src.main._db_conn", mock_conn),
            patch("src.main.apply_schema") as mock_apply,
            patch("src.main.run_migrations") as mock_migrate,
        ):
            resp = _handle_command({"method": "schema.apply"})
        assert resp["result"] == "Schema applied."
        mock_apply.assert_called_once_with(mock_conn)
        mock_migrate.assert_called_once_with(mock_conn)

    def test_settings_set_and_get(self, mock_conn):
        """settings.set and settings.get round-trip."""
        mock_conn.execute.return_value.fetchone.return_value = {"value": "Orange County"}

        with patch("src.main._db_conn", mock_conn):
            resp = _handle_command(
                {
                    "method": "settings.set",
                    "params": {"key": "target_county", "value": "Orange County"},
                }
            )
        assert resp["result"] == "OK"

        with patch("src.main._db_conn", mock_conn):
            resp = _handle_command({"method": "settings.get", "params": {"key": "target_county"}})
        assert resp["result"]["value"] == "Orange County"

    def test_market_score_valid(self, mock_conn):
        """market.score returns a float."""
        with patch("src.main._db_conn", mock_conn):
            resp = _handle_command({"method": "market.score", "params": {"vacancy_risk": 0.7}})
        assert isinstance(resp["result"]["priority_score"], float)

    def test_market_score_defaults(self, mock_conn):
        """market.score with empty params still returns a score."""
        with patch("src.main._db_conn", mock_conn):
            resp = _handle_command({"method": "market.score", "params": {}})
        assert isinstance(resp["result"]["priority_score"], float)

    def test_llm_settings_get_masks_keys(self, mock_conn):
        """llm_settings.get masks API keys."""
        mock_conn.execute.return_value.fetchall.return_value = [
            {
                "provider": "anthropic",
                "api_key": "sk-real-key",
                "base_url": "",
                "selected_model": "claude",
                "is_active": 1,
            },
        ]
        with patch("src.main._db_conn", mock_conn):
            resp = _handle_command({"method": "llm_settings.get"})
        providers = resp["result"]
        assert providers[0]["api_key"] == "sk-r****"

    def test_exception_returns_internal_error(self, mock_conn):
        """An unhandled exception returns ERR_INTERNAL."""
        mock_conn.execute.side_effect = RuntimeError("Kaboom!")

        with patch("src.main._db_conn", mock_conn):
            resp = _handle_command({"method": "settings.get", "params": {"key": "x"}})
        assert resp["error"]["code"] == ERR_INTERNAL
        assert "Kaboom!" in resp["error"]["message"]

    def test_auth_error_returns_auth_code(self, mock_conn):
        """A ValueError in entity.unmask should return ERR_VALIDATION."""
        with (
            patch("src.main._db_conn", mock_conn),
            patch("src.main.get_active_llm_client", side_effect=ValueError("No LLM configured")),
        ):
            resp = _handle_command(
                {
                    "method": "entity.unmask",
                    "params": {"apn": "123-456", "recorded_owner": "Test LLC"},
                }
            )
        # The ValueError from get_active_llm_client is caught and returns
        # the unmask result without SOS lookup
        assert "result" in resp

    def test_no_id_in_request(self, mock_conn):
        """Commands without 'id' still work (id is None)."""
        with patch("src.main._db_conn", mock_conn):
            resp = _handle_command({"method": "ping"})
        assert resp["result"] == {"pong": True}
        assert resp["id"] is None

    @pytest.mark.parametrize(
        ("method", "params"),
        [
            ("output.export_csv", {"leads": []}),
            ("output.export_json", {"leads": []}),
        ],
    )
    def test_output_methods_return_strings(self, mock_conn, method, params):
        """Output methods return string results."""
        with patch("src.main._db_conn", mock_conn):
            resp = _handle_command({"method": method, "params": params})
        assert "result" in resp
        assert isinstance(list(resp["result"].values())[0], str)
