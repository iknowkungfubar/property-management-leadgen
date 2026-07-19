"""Tests for the OS-keychain credential store and its file fallback.

These exercise the file-based fallback path, which is the active code path
in headless CI (no OS keychain available). keyring import is patched away so
store/get/delete route through the encrypted-file store deterministically.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import src.utils.credentials as credentials


@pytest.fixture
def temp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect Path.home() to a temp dir so the fallback file is isolated."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))  # noqa: ARG005
    # Ensure keyring is treated as unavailable so we hit the file fallback.
    monkeypatch.setattr(credentials, "_get_keyring", lambda: None)
    return tmp_path


def test_store_then_get_roundtrip(temp_home: Path) -> None:
    """A stored credential can be retrieved from the file fallback."""
    assert credentials.store_credential("llm/anthropic", "sk-secret") is True
    assert credentials.get_credential("llm/anthropic") == "sk-secret"


def test_get_missing_credential_returns_none(temp_home: Path) -> None:
    """Reading an unknown key returns None rather than raising."""
    assert credentials.get_credential("llm/nonexistent") is None


def test_overwrite_credential(temp_home: Path) -> None:
    """Storing the same key twice keeps only the latest value."""
    credentials.store_credential("llm/openai", "v1")
    credentials.store_credential("llm/openai", "v2")
    assert credentials.get_credential("llm/openai") == "v2"


def test_delete_credential(temp_home: Path) -> None:
    """Deleting a stored credential removes it from the fallback store."""
    credentials.store_credential("llm/gemini", "abc")
    assert credentials.get_credential("llm/gemini") == "abc"
    assert credentials.delete_credential("llm/gemini") is True
    assert credentials.get_credential("llm/gemini") is None


def test_delete_unknown_credential_is_safe(temp_home: Path) -> None:
    """Deleting a key that was never stored does not raise."""
    assert credentials.delete_credential("llm/ghost") is True


def test_fallback_file_is_obfuscated_and_perms_0600(temp_home: Path) -> None:
    """The on-disk file is not plaintext and is owner-only readable."""
    credentials.store_credential("llm/test", "plaintext-secret")

    cred_file = temp_home / ".leadgen" / ".credentials.enc"
    raw = cred_file.read_text()

    # Not stored in cleartext
    assert "plaintext-secret" not in raw
    # Round-trips through deobfuscation to valid JSON
    decoded = json.loads(credentials._deobfuscate(raw))
    assert decoded["llm/test"] == "plaintext-secret"
    # Permissions are owner read/write only
    assert oct(cred_file.stat().st_mode & 0o777) == "0o600"


def test_obfuscate_roundtrip_is_stable() -> None:
    """_obfuscate / _deobfuscate are inverses for arbitrary input."""
    sample = "aR4nd0m-s3cr3t!@#$"
    assert credentials._deobfuscate(credentials._obfuscate(sample)) == sample


def test_load_fallback_store_handles_corrupt_file(temp_home: Path) -> None:
    """A corrupt credential file yields an empty store, not an exception."""
    cred_file = temp_home / ".leadgen" / ".credentials.enc"
    cred_file.parent.mkdir(parents=True, exist_ok=True)
    cred_file.write_text("not-valid-base64-@@@")

    assert credentials._load_fallback_store() == {}


def test_migrate_from_sqlite_masks_keys_and_counts(temp_home: Path) -> None:
    """migrate_from_sqlite moves keys to the keychain and masks them in DB."""
    import sqlite3

    db = temp_home / "settings.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE llm_settings (provider TEXT, api_key TEXT)")
    conn.execute(
        "INSERT INTO llm_settings (provider, api_key) VALUES ('anthropic', 'sk-ant-123')"
    )
    conn.execute(
        "INSERT INTO llm_settings (provider, api_key) VALUES ('openai', 'sk-oa-456')"
    )
    conn.commit()

    migrated = credentials.migrate_from_sqlite(conn)
    assert migrated == 2

    # Keys now live in the fallback store
    assert credentials.get_credential("llm/anthropic/api_key") == "sk-ant-123"
    assert credentials.get_credential("llm/openai/api_key") == "sk-oa-456"

    # DB values are masked, keeping the first 4 chars
    rows = conn.execute("SELECT provider, api_key FROM llm_settings").fetchall()
    masked = dict(rows)
    assert masked["anthropic"].startswith("sk-a")
    assert masked["anthropic"].endswith("****")
    assert "sk-ant-123" not in masked["anthropic"]

    conn.close()


def test_migrate_skips_already_masked_keys(temp_home: Path) -> None:
    """Keys already ending in **** are not re-migrated."""
    import sqlite3

    db = temp_home / "settings2.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE llm_settings (provider TEXT, api_key TEXT)")
    conn.execute(
        "INSERT INTO llm_settings (provider, api_key) VALUES ('openai', 'sk-o****')"
    )
    conn.commit()

    assert credentials.migrate_from_sqlite(conn) == 0
    assert credentials.get_credential("llm/openai/api_key") is None

    conn.close()


def test_store_credential_fallback_write_failure_returns_false(temp_home: Path) -> None:
    """When the fallback write fails, store_credential returns False."""
    with patch.object(
        credentials, "_save_fallback_store", side_effect=OSError("disk full")
    ):
        assert credentials.store_credential("llm/x", "val") is False
