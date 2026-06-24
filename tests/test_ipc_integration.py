"""Integration tests for the sidecar IPC protocol.

Spawns the Python sidecar as a subprocess, sends JSON commands via stdin,
and validates JSON-RPC 2.0 responses from stdout.

These tests verify the full IPC dispatch pipeline end-to-end without
needing the Tauri Rust layer.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Path to the sidecar entrypoint relative to the repo root
SIDECAR_MODULE = "src.main"
"""Module path for the sidecar entrypoint (used with python -m)."""

REPO_ROOT = Path(__file__).resolve().parent.parent
"""Repo root directory, added to PYTHONPATH for subprocess."""


@pytest.fixture
def sidecar_proc():
    """Spawn the sidecar subprocess with a temp DB and return the process + helpers.

    Yields a dict with:
        - proc: subprocess.Popen
        - send(cmd: dict) -> None: write JSON to stdin
        - recv() -> dict: read one JSON line from stdout
        - request(method, params) -> dict: send+recv in one call
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        env = os.environ.copy()
        env["LEADGEN_DB_PATH"] = db_path
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONPATH"] = str(REPO_ROOT) + ":" + env.get("PYTHONPATH", "")

        proc = subprocess.Popen(
            [sys.executable, "-m", SIDECAR_MODULE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
        )

        # Give the sidecar a moment to initialise
        time.sleep(0.4)

        # Check process is alive
        assert proc.poll() is None, f"Sidecar failed to start (rc={proc.poll()})"

        msg_id = 0

        def send(cmd: dict) -> None:
            proc.stdin.write(json.dumps(cmd) + "\n")
            proc.stdin.flush()

        def recv() -> dict:
            line = proc.stdout.readline()
            return json.loads(line)

        def request(method: str, params: dict | None = None) -> dict:
            nonlocal msg_id
            msg_id += 1
            cmd = {"id": str(msg_id), "method": method}
            if params is not None:
                cmd["params"] = params
            send(cmd)
            return recv()

        yield {
            "proc": proc,
            "send": send,
            "recv": recv,
            "request": request,
            "db_path": db_path,
        }

        # Teardown
        try:
            proc.stdin.close()
            proc.stdout.close()
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            proc.kill()

        # Collect any stderr for debugging failed tests
        _stderr = proc.stderr.read() if proc.stderr else ""
        if _stderr and "Traceback" in _stderr:
            print(f"\n[sidecar stderr]\n{_stderr[:2000]}")


# ── Basic protocol tests ──────────────────────────────────────────────


class TestProtocolBasics:
    """Verify the JSON-RPC 2.0 protocol structure."""

    def test_ping(self, sidecar_proc):
        """Ping returns pong."""
        resp = sidecar_proc["request"]("ping")
        assert resp["jsonrpc"] == "2.0"
        assert resp["result"] == {"pong": True}
        assert "id" in resp

    def test_schema_apply(self, sidecar_proc):
        """Schema.apply returns success and creates tables."""
        resp = sidecar_proc["request"]("schema.apply")
        assert resp["jsonrpc"] == "2.0"
        assert resp["result"] == "Schema applied."

        # Verify the DB was created and has tables
        import sqlite3

        conn = sqlite3.connect(sidecar_proc["db_path"])
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
        ).fetchall()
        table_names = {r[0] for r in tables}
        assert "properties" in table_names
        assert "ownership" in table_names
        assert "market_signals" in table_names
        assert "schema_version" in table_names
        conn.close()

    def test_unknown_method(self, sidecar_proc):
        """Unknown method returns error with ERR_UNKNOWN_METHOD code."""
        resp = sidecar_proc["request"]("nonexistent.method")
        assert "error" in resp
        assert resp["error"]["code"] == -60000  # ERR_UNKNOWN_METHOD
        assert "Unknown method" in resp["error"]["message"]


class TestSettingsRoundTrip:
    """Settings CRUD via IPC."""

    def test_settings_set_and_get(self, sidecar_proc):
        """Set a setting then retrieve it."""
        set_resp = sidecar_proc["request"](
            "settings.set",
            {
                "key": "target_county",
                "value": "Orange County",
            },
        )
        assert set_resp["result"] == "OK"

        get_resp = sidecar_proc["request"](
            "settings.get",
            {
                "key": "target_county",
            },
        )
        assert get_resp["result"]["value"] == "Orange County"

    def test_settings_get_missing(self, sidecar_proc):
        """Getting a nonexistent key returns null value."""
        resp = sidecar_proc["request"](
            "settings.get",
            {
                "key": "nonexistent_key",
            },
        )
        assert resp["result"]["value"] is None

    def test_settings_get_missing_key(self, sidecar_proc):
        """Missing 'key' param returns validation error."""
        resp = sidecar_proc["request"]("settings.get", {})
        assert "error" in resp
        assert resp["error"]["code"] == -50000  # ERR_VALIDATION


class TestLLMSettings:
    """LLM provider configuration via IPC."""

    def test_set_and_get_llm_settings(self, sidecar_proc):
        """Set an LLM provider then verify it's stored."""
        set_resp = sidecar_proc["request"](
            "llm_settings.set",
            {
                "provider": "anthropic",
                "api_key": "sk-test-key-12345",
                "base_url": "",
                "selected_model": "claude-sonnet-4",
                "is_active": True,
            },
        )
        assert set_resp["result"] == "OK"

        get_resp = sidecar_proc["request"]("llm_settings.get")
        providers = get_resp["result"]
        assert isinstance(providers, list)
        anthropic = next(p for p in providers if p["provider"] == "anthropic")
        assert anthropic["is_active"] == 1
        # API key should be masked
        assert anthropic["api_key"] == "sk-t****"
        assert anthropic["api_key"] != "sk-test-key-12345"  # not leaking


class TestCompliance:
    """DNC compliance checking via IPC."""

    def test_dnc_check_valid_number(self, sidecar_proc):
        """A valid phone number returns a boolean."""
        resp = sidecar_proc["request"](
            "compliance.dnc_check",
            {
                "phone": "+1 949-555-1234",
            },
        )
        assert "result" in resp
        assert isinstance(resp["result"]["is_dnc"], bool)

    def test_dnc_check_missing_phone(self, sidecar_proc):
        """Missing phone param returns validation error."""
        resp = sidecar_proc["request"]("compliance.dnc_check", {})
        assert "error" in resp
        assert resp["error"]["code"] == -50000  # ERR_VALIDATION


class TestOutputSynthesis:
    """Output export via IPC."""

    def test_export_csv_empty(self, sidecar_proc):
        """Export empty leads as CSV returns header."""
        resp = sidecar_proc["request"]("output.export_csv", {"leads": []})
        assert "result" in resp
        csv = resp["result"]["csv"]
        assert isinstance(csv, str)
        assert "apn" in csv.lower() or "lead" in csv.lower()

    def test_export_json_empty(self, sidecar_proc):
        """Export empty leads as JSON returns empty array."""
        resp = sidecar_proc["request"]("output.export_json", {"leads": []})
        assert "result" in resp
        json_out = resp["result"]["json"]
        assert isinstance(json_out, str)
        parsed = json.loads(json_out)
        assert parsed == []


class TestPriorityScore:
    """Market intelligence scoring via IPC."""

    def test_score_default_weights(self, sidecar_proc):
        """Calculate priority score with default values."""
        resp = sidecar_proc["request"]("market.score", {})
        assert "result" in resp
        score = resp["result"]["priority_score"]
        assert isinstance(score, float)
        assert score >= 0.0


class TestMalformedInput:
    """Robustness against malformed input."""

    def test_missing_method(self, sidecar_proc):
        """Request with empty method returns unknown method error."""
        resp = sidecar_proc["request"]("")
        assert "error" in resp

    def test_invalid_json(self, sidecar_proc):
        """Non-JSON input returns parse error."""
        sidecar_proc["send"]("this is not json")
        resp = sidecar_proc["recv"]()
        assert "error" in resp
        assert (
            "Parse error" in resp["error"]["message"] or "parse" in resp["error"]["message"].lower()
        )
