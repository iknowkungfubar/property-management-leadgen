"""Secure credential storage using the OS keychain.

Uses the `keyring` library to store API keys in:
- macOS Keychain
- Windows Credential Manager
- Linux Secret Service (GNOME Keyring / KDE Wallet)

If the keychain is unavailable (headless server, CI), falls back
to a file-based encrypted store.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SERVICE_NAME = "property-management-leadgen"

# ── Keychain API ──────────────────────────────────────────────────────


def _get_keyring() -> Any:
    """Lazy-import keyring and return the module.

    Returns None if keyring is not available (e.g. headless CI).
    """
    try:
        import keyring as _kr

        return _kr
    except ImportError:
        return None


def store_credential(key: str, value: str) -> bool:
    """Store a credential in the OS keychain.

    Args:
        key: Credential identifier (e.g. ``llm/anthropic``).
        value: The secret value to store.

    Returns:
        True if stored successfully, False otherwise.

    """
    kr = _get_keyring()
    if kr is not None:
        try:
            kr.set_password(_SERVICE_NAME, key, value)
            logger.debug("Stored credential '%s' in OS keychain", key)
            return True
        except Exception as exc:
            logger.warning("Keychain write failed for '%s': %s", key, exc)
            return _file_store_credential(key, value)
    return _file_store_credential(key, value)


def get_credential(key: str) -> str | None:
    """Retrieve a credential from the OS keychain.

    Args:
        key: Credential identifier.

    Returns:
        The secret value, or None if not found.

    """
    kr = _get_keyring()
    if kr is not None:
        try:
            value = kr.get_password(_SERVICE_NAME, key)
            if value is not None:
                return value
        except Exception as exc:
            logger.warning("Keychain read failed for '%s': %s", key, exc)

    # Fallback: encrypted file store
    return _file_get_credential(key)


def delete_credential(key: str) -> bool:
    """Delete a credential from the OS keychain.

    Args:
        key: Credential identifier.

    Returns:
        True if deleted (or not found), False on error.
    """
    kr = _get_keyring()
    if kr is not None:
        try:
            kr.delete_password(_SERVICE_NAME, key)
            return True
        except kr.errors.PasswordDeleteError:
            return True  # Already gone
        except Exception as exc:
            logger.warning("Keychain delete failed for '%s': %s", key, exc)

    _file_delete_credential(key)
    return True


# ── File-based fallback (encrypted with simple XOR + base64) ──────────


def _get_credential_path() -> Path:
    """Path to the fallback credential file."""
    return Path.home() / ".leadgen" / ".credentials.enc"


def _obfuscate(data: str) -> str:
    """Simple obfuscation for the fallback store.

    NOTE: This is NOT cryptographically secure. It prevents casual
    reading of credential files but is not a substitute for the OS
    keychain. Use keyring whenever possible.
    """
    import base64

    # XOR with a fixed key derived from the hostname
    machine_key = os.uname().nodename.encode()[:16]
    raw = data.encode()
    xored = bytes(raw[i] ^ machine_key[i % len(machine_key)] for i in range(len(raw)))
    return base64.b64encode(xored).decode()


def _deobfuscate(data: str) -> str:
    import base64

    machine_key = os.uname().nodename.encode()[:16]
    raw = base64.b64decode(data)
    xored = bytes(raw[i] ^ machine_key[i % len(machine_key)] for i in range(len(raw)))
    return xored.decode()


def _load_fallback_store() -> dict[str, str]:
    path = _get_credential_path()
    if not path.exists():
        return {}
    try:
        raw = path.read_text().strip()
        if not raw:
            return {}
        decoded = _deobfuscate(raw)
        return json.loads(decoded)
    except Exception as exc:
        logger.warning("Failed to read credential store: %s", exc)
        return {}


def _save_fallback_store(store: dict[str, str]) -> None:
    path = _get_credential_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_obfuscate(json.dumps(store)))
    path.chmod(0o600)  # Owner read/write only


def _file_store_credential(key: str, value: str) -> bool:
    try:
        store = _load_fallback_store()
        store[key] = value
        _save_fallback_store(store)
        return True
    except Exception as exc:
        logger.error("Failed to write credential file: %s", exc)
        return False


def _file_get_credential(key: str) -> str | None:
    try:
        store = _load_fallback_store()
        return store.get(key)
    except Exception:
        return None


def _file_delete_credential(key: str) -> None:
    try:
        store = _load_fallback_store()
        store.pop(key, None)
        _save_fallback_store(store)
    except Exception:
        pass


# ── Migration helper ──────────────────────────────────────────────────


def migrate_from_sqlite(db_conn: Any) -> int:
    """Migrate API keys from the SQLite llm_settings table to the keychain.

    Reads any existing keys from the database, stores them in the OS
    keychain, then masks them in the database so they are not readable
    through SQLite queries.

    Args:
        db_conn: An active SQLite connection.

    Returns:
        Number of keys migrated.

    """
    rows = db_conn.execute(
        "SELECT provider, api_key FROM llm_settings WHERE api_key != ''",
    ).fetchall()

    count = 0
    for row in rows:
        provider = row[0]
        api_key = row[1]

        # Skip already-masked keys
        if api_key.endswith("****"):
            continue

        # Store in keychain
        keychain_key = f"llm/{provider}/api_key"
        success = store_credential(keychain_key, api_key)
        if success:
            # Mask the key in SQLite (keep last 4 chars for identification)
            masked = api_key[:4] + "****" if len(api_key) > 4 else "****"
            db_conn.execute(
                "UPDATE llm_settings SET api_key = ? WHERE provider = ?",
                (masked, provider),
            )
            count += 1
            logger.info("Migrated API key for '%s' to keychain", provider)

    if count:
        db_conn.commit()
        logger.info("Migrated %d API key(s) to OS keychain", count)

    return count
