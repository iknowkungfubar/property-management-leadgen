"""Connection manager providing WAL-mode SQLite connections.

Every call to :func:`get_connection` opens a fresh synchronous connection.
The async variants use ``run_in_executor`` to avoid blocking the event loop
but do **not** serialise writes — callers are responsible for their own
concurrency control at the agent level.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


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
    """Return a fresh connection, offloaded from the event loop via executor.

    This avoids blocking the event loop during sqlite3 connect/setup.  It does
    **not** provide any write serialisation — wrap call sites in an agent-level
    lock if you need sequential writes across coroutines.

    Args:
        db_path: Filesystem path to the SQLite database file.

    Returns:
        A configured :class:`sqlite3.Connection`.

    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, get_connection, db_path)


async def close_connection(conn: sqlite3.Connection | None = None) -> None:
    """Close a SQLite connection without blocking the event loop.

    Args:
        conn: The connection to close.  If ``None``, a no-op.

    """
    if conn is None:
        return
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, conn.close)
    logger.debug("SQLite connection closed.")
