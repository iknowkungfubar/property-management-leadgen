"""Real Do-Not-Call compliance checker with configurable blocking.

Checks phone numbers against:
1. Area code blocklist (configurable via DNCConfig)
2. Internal SQLite dnc_list table (user-managed)
3. International number blocking

Use the IPC endpoint ``compliance.add_dnc`` to add numbers at runtime.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────


@dataclass
class DNCConfig:
    """Configuration for DNC compliance checking.

    Attributes:
        enabled: Master switch. When False, all checks pass (allow calling).
        area_codes: Area codes that are always blocked (e.g. ``["212"]``).
        block_international: If True, non-US numbers are treated as DNC.
    """

    enabled: bool = True
    area_codes: list[str] = field(default_factory=list)
    block_international: bool = True


# ── Phone normalization ───────────────────────────────────────────────

PHONE_CLEAN: re.Pattern[str] = re.compile(r"\D")


def normalise_phone(phone: str) -> str | None:
    """Strip formatting and return a 10-digit US number.

    Args:
        phone: Raw phone number (e.g. ``+1 (949) 555-1234``).

    Returns:
        10-digit string, or ``None`` if the number is invalid.
    """
    digits = PHONE_CLEAN.sub("", phone)

    # Strip US country code
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    elif len(digits) == 12 and digits.startswith("11"):
        digits = digits[2:]

    if len(digits) == 10:
        return digits

    logger.debug("Phone '%s' is not a valid 10-digit US number", phone)
    return None


def _get_area_code(digits: str) -> str | None:
    """Extract the 3-digit area code from a 10-digit number."""
    if digits and len(digits) >= 3:
        return digits[:3]
    return None


# ── DNC check ─────────────────────────────────────────────────────────


def check_dnc(
    phone: str,
    config: DNCConfig | None = None,
    db_conn: sqlite3.Connection | None = None,
) -> bool:
    """Check whether a phone number is on the Do-Not-Call list.

    Args:
        phone: Phone number to check (any common format).
        config: Override the default DNC configuration.
        db_conn: Optional database connection for checking the dnc_list table.

    Returns:
        ``True`` if the number IS on the DNC list (do NOT call).
        ``False`` if the number is clear to call.
    """
    if config is None:
        config = DNCConfig()

    if not config.enabled:
        logger.debug("DNC checking is disabled — allowing all calls")
        return False

    # 1. International blocking (check before normalization, which strips +)
    if config.block_international:
        clean = phone.strip()
        if clean.startswith("+") and not clean.startswith("+1"):
            logger.info("DNC BLOCK: international number %s", clean[:20])
            return True

    normalized = normalise_phone(phone)
    if normalized is None:
        logger.warning("Cannot check DNC for invalid number: %s", phone)
        return False  # Can't block an unparseable number

    # 2. Area code blocklist
    area_code = _get_area_code(normalized)
    if area_code and config.area_codes and area_code in config.area_codes:
        logger.info("DNC BLOCK: area code %s is blocked", area_code)
        return True

    # 3. Internal dnc_list table
    if db_conn is not None:
        row = db_conn.execute("SELECT 1 FROM dnc_list WHERE phone = ?", (normalized,)).fetchone()
        if row is not None:
            logger.info("DNC BLOCK: %s found in internal blocklist", normalized)
            return True

    logger.debug("DNC OK: %s is clear to call", normalized)
    return False


def add_dnc_number(db_conn: sqlite3.Connection, phone: str, source: str = "manual") -> bool:
    """Add a phone number to the internal DNC blocklist.

    Args:
        db_conn: Active SQLite connection.
        phone: Phone number to block.
        source: Description of who added it (default: 'manual').

    Returns:
        True if the number was added, False if already present.
    """
    normalized = normalise_phone(phone)
    if normalized is None:
        logger.warning("Cannot add invalid phone to DNC list: %s", phone)
        return False

    try:
        db_conn.execute(
            "INSERT OR IGNORE INTO dnc_list (phone, source) VALUES (?, ?)",
            (normalized, source),
        )
        db_conn.commit()
        logger.info("Added %s to DNC blocklist (source: %s)", normalized, source)
        return True
    except Exception as exc:
        logger.error("Failed to add DNC entry: %s", exc)
        return False


def remove_dnc_number(db_conn: sqlite3.Connection, phone: str) -> bool:
    """Remove a phone number from the internal DNC blocklist.

    Args:
        db_conn: Active SQLite connection.
        phone: Phone number to unblock.

    Returns:
        True if removed, False if not found.
    """
    normalized = normalise_phone(phone)
    if normalized is None:
        return False

    cur = db_conn.execute("DELETE FROM dnc_list WHERE phone = ?", (normalized,))
    db_conn.commit()
    removed = cur.rowcount > 0
    if removed:
        logger.info("Removed %s from DNC blocklist", normalized)
    return removed
