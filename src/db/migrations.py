"""Sequential schema migrations driven by PRAGMA user_version."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# A mapping from version number to a migration function.
# Each function receives the connection and applies its changes.
MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    # ── Migration 2 placeholder ──────────────────────────────────────────
    # 2: _migrate_v2,
}


def get_current_version(conn: sqlite3.Connection) -> int:
    """Read the schema version from the ``schema_version`` table.

    Args:
        conn: An open SQLite connection.

    Returns:
        The current schema version integer, or 0 if not yet initialised.

    """
    row = conn.execute(
        "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1",
    ).fetchone()
    version: int = row[0] if row else 0
    return version


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply all pending migrations sequentially.

    Reads the current version from ``schema_version``, then applies
    every migration whose key is greater than that version, in
    ascending key order.

    Args:
        conn: An open SQLite connection.

    """
    current = get_current_version(conn)
    logger.info("Current schema version: %d", current)

    for version in sorted(MIGRATIONS):
        if version > current:
            logger.info("Applying migration %d …", version)
            MIGRATIONS[version](conn)
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                (version,),
            )
            conn.commit()
            logger.info("Migration %d applied.", version)

    logger.info("All migrations current at version %d.", get_current_version(conn))
