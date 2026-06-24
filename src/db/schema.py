"""SQLite schema definitions and table creation with WAL mode."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger(__name__)

SCHEMA_SQL: str = """
CREATE TABLE IF NOT EXISTS properties (
    apn TEXT PRIMARY KEY,
    county TEXT NOT NULL,
    property_address TEXT NOT NULL,
    property_type TEXT,
    assessed_value INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ownership (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    apn TEXT NOT NULL REFERENCES properties(apn),
    recorded_owner TEXT NOT NULL,
    mailing_address TEXT,
    is_absentee INTEGER DEFAULT 0,
    is_llc INTEGER DEFAULT 0,
    entity_type TEXT,
    unmasked_principal_name TEXT,
    unmasked_principal_phone TEXT,
    unmasked_principal_email TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS market_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    apn TEXT NOT NULL REFERENCES properties(apn),
    listing_status TEXT,
    days_on_market INTEGER,
    code_violations TEXT DEFAULT '[]',
    tax_delinquent INTEGER DEFAULT 0,
    priority_score REAL DEFAULT 0.0,
    competitor_sentiment REAL DEFAULT 0.0,
    vacancy_risk REAL DEFAULT 0.0,
    rental_yield_delta REAL DEFAULT 0.0,
    last_checked TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_settings (
    provider TEXT PRIMARY KEY
        CHECK(provider IN ("anthropic", "openai", "openpipe", "local_ollama")),
    api_key TEXT,
    base_url TEXT,
    selected_model TEXT NOT NULL,
    is_active INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);
"""


def create_tables(conn: sqlite3.Connection) -> None:
    """Execute the full schema DDL against the given connection.

    Args:
        conn: An open SQLite connection.

    """
    logger.info("Creating database tables if they do not exist…")
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def apply_schema(conn: sqlite3.Connection) -> None:
    """Ensure schema and critical seed data exist.

    This is idempotent — safe to call on every application start.

    Args:
        conn: An open SQLite connection.

    """
    create_tables(conn)

    # Seed default settings if absent
    defaults: list[tuple[str, str]] = [
        ("target_county", "Orange County"),
        ("target_state", "CA"),
        ("search_radius_miles", "25"),
        ("default_alpha", "0.4"),
        ("default_beta", "0.4"),
        ("default_gamma", "0.2"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", defaults,
    )
    conn.commit()
    logger.info("Schema applied, seed data inserted.")
