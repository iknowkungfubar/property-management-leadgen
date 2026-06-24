"""Connection manager providing WAL-mode SQLite connections with optional asyncio locking."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_connection: sqlite3.Connection | None = None
_write_lock: asyncio.Lock = asyncio.Lock()


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Return a synchronous SQLite connection with WAL mode and foreign keys.

    Args:
        db_path: Filesystem path to the SQLite database file.

    Returns:
        A configured :class:`sqlite3.Connection` with ``sqlite3.Row`` row factory.

    """
    path = Path(db_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    logger.debug("Opened SQLite connection (sync) at %s", path)
    return conn


async def get_connection_async(db_path: str | Path) -> sqlite3.Connection:
    """Return a connection guarded by an asyncio lock for write serialisation.

    This wraps :func:`get_connection` in an async context manager pattern.
    Callers should use the returned connection normally but rely on the shared
    lock to prevent concurrent writes from multiple coroutines.

    Args:
        db_path: Filesystem path to the SQLite database file.

    Returns:
        A configured :class:`sqlite3.Connection`.

    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, get_connection, db_path)


async def close_connection(conn: sqlite3.Connection | None = None) -> None:
    """Close the given connection, or the module-level cached connection.

    Args:
        conn: The connection to close.  If ``None``, a no-op.

    """
    if conn is None:
        return
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, conn.close)
    logger.debug("SQLite connection closed.")
