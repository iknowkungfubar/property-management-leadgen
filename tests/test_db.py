"""Tests for database schema, connection, and migrations."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from src.db.connection import get_connection
from src.db.migrations import get_current_version, run_migrations
from src.db.schema import apply_schema


@pytest.fixture
def db_path() -> str:
    """Provide a temporary database path for each test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def conn(db_path: str) -> sqlite3.Connection:
    """Provide an open connection with schema applied."""
    c = get_connection(db_path)
    apply_schema(c)
    yield c
    c.close()


# ── Connection tests ────────────────────────────────────────────────


def test_get_connection_wal_mode(db_path: str) -> None:
    """Verify the connection uses WAL journal mode and has foreign keys."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row is not None
        assert row[0].upper() == "WAL"

        fk = conn.execute("PRAGMA foreign_keys").fetchone()
        assert fk is not None
        assert fk[0] == 1
    finally:
        conn.close()


def test_get_connection_row_factory(db_path: str) -> None:
    """Row factory should return dict-like rows."""
    conn = get_connection(db_path)
    try:
        conn.execute("CREATE TABLE t (a INT)")
        conn.execute("INSERT INTO t VALUES (42)")
        row = conn.execute("SELECT a FROM t").fetchone()
        assert row is not None
        assert row["a"] == 42
    finally:
        conn.close()


# ── Schema tests ────────────────────────────────────────────────────


def test_create_tables_creates_all_tables(conn: sqlite3.Connection) -> None:
    """All expected tables should exist after schema creation."""
    tables = [
        "properties",
        "ownership",
        "market_signals",
        "settings",
        "llm_settings",
        "schema_version",
    ]
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    existing_names = {row[0] for row in existing}
    for t in tables:
        assert t in existing_names, f"Table '{t}' is missing"


def test_schema_version_exists(conn: sqlite3.Connection) -> None:
    """The schema_version table should contain version 1."""
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    assert row is not None
    assert row[0] == 1


def test_seed_settings_inserted(conn: sqlite3.Connection) -> None:
    """Default settings should be seeded by apply_schema."""
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    keys = {r["key"] for r in rows}
    assert "target_county" in keys
    assert "target_state" in keys
    assert "search_radius_miles" in keys


# ── Migration tests ─────────────────────────────────────────────────


def test_get_current_version(conn: sqlite3.Connection) -> None:
    """get_current_version returns the version from schema_version."""
    assert get_current_version(conn) == 1


def test_run_migrations_noop_when_current(conn: sqlite3.Connection) -> None:
    """run_migrations with no pending migrations is a no-op."""
    run_migrations(conn)
    assert get_current_version(conn) == 1


def test_schema_applied_idempotent(conn: sqlite3.Connection) -> None:
    """apply_schema can be called multiple times safely."""
    apply_schema(conn)
    apply_schema(conn)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    assert len(tables) >= 6


# ── Foreign keys ────────────────────────────────────────────────────


def test_foreign_key_enforcement(db_path: str) -> None:
    """Inserting an ownership row without a matching property should fail."""
    conn = get_connection(db_path)
    apply_schema(conn)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO ownership (apn, recorded_owner) VALUES (?, ?)",
                ("non-existent-apn", "Test Owner"),
            )
        conn.commit()
    finally:
        conn.close()
