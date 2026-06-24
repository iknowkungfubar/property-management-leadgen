"""Discovery Agent — CSV import, address normalisation, absentee detection."""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any

from src.utils.csv_import import COLUMN_MAP, normalize_address

logger = logging.getLogger(__name__)

# Standard APN format patterns
# Orange County: XXX-XXX-XX (3-3-2 digits)
# Los Angeles County: XXXX-XXX-XXX (4-3-3 digits, or similar variants)
APN_PATTERNS: dict[str, re.Pattern[str]] = {
    "Orange County": re.compile(r"\d{3}-?\d{3}-?\d{2}"),
    "Los Angeles County": re.compile(r"\d{4}-?\d{3}-?\d{3}"),
}


class DiscoveryAgent:
    """Handles CSV import, address normalisation, and absentee-owner detection."""

    def __init__(self, db_conn: Any = None) -> None:
        """Store a reference to the database connection.

        Args:
            db_conn: SQLite connection (or mock for testing).
                ``None`` is permitted for agents used in rule-based /
                read-only mode; methods that write to the database will
                raise :class:`RuntimeError`.

        """
        self._db = db_conn

    # ------------------------------------------------------------------
    # CSV parsing
    # ------------------------------------------------------------------

    def parse_csv_import(self, file_path: str | Path) -> list[dict[str, Any]]:
        """Parse an Orange Coast Title or CRMLS CSV export into a normalised list.

        Heuristic detection: if the header contains known column names from
        either format, the matching column map is applied; otherwise every
        row is returned with raw headers as keys.

        Args:
            file_path: Path to a CSV file on disk.

        Returns:
            A list of dictionaries keyed by standard field names.

        Raises:
            FileNotFoundError: If the CSV does not exist.
            ValueError: If the CSV is empty or unreadable.

        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise ValueError("CSV file has no headers.")

            headers: list[str] = reader.fieldnames
            mapping = self._detect_format(headers)

            if mapping:
                logger.info(
                    "Detected format with %d columns, mapping applied.",
                    len(mapping),
                )
                records: list[dict[str, Any]] = []
                for row in reader:
                    mapped: dict[str, Any] = {
                        target: row.get(source, "").strip() for target, source in mapping.items()
                    }
                    records.append(mapped)
            else:
                logger.warning("Unknown CSV format — returning raw rows.")
                records = [dict(row) for row in reader]

        return records

    # ------------------------------------------------------------------
    # Database persistence
    # ------------------------------------------------------------------

    def save_to_database(
        self,
        records: list[dict[str, Any]],
    ) -> int:
        """Insert parsed CSV records into the ``properties`` and ``ownership`` tables.

        Each record is upserted (INSERT OR REPLACE) by APN into ``properties``,
        and the corresponding owner row is upserted into ``ownership``.

        Args:
            records: A list of dicts as returned by :meth:`parse_csv_import`.

        Returns:
            The number of records successfully stored.

        """
        saved = 0
        if self._db is None:
            raise RuntimeError(
                "DiscoveryAgent has no database connection — cannot save records.",
            )
        for rec in records:
            apn = rec.get("apn", "").strip()
            if not apn:
                logger.warning("Skipping record with empty APN: %s", rec)
                continue

            # Upsert into properties
            self._db.execute(
                """INSERT OR REPLACE INTO properties
                   (apn, county, property_address, property_type, assessed_value)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    apn,
                    rec.get("county", ""),
                    rec.get("property_address", ""),
                    rec.get("property_type"),
                    self._safe_int(rec.get("assessed_value")),
                ),
            )

            # Upsert into ownership
            recorded_owner = rec.get("recorded_owner", "")
            if recorded_owner:
                # Check for existing record
                existing = self._db.execute(
                    "SELECT id FROM ownership WHERE apn = ? AND recorded_owner = ?",
                    (apn, recorded_owner),
                ).fetchone()

                if existing:
                    self._db.execute(
                        """UPDATE ownership
                           SET mailing_address = ?,
                               is_absentee = ?,
                               updated_at = datetime('now')
                           WHERE id = ?""",
                        (
                            rec.get("mailing_address", ""),
                            1
                            if DiscoveryAgent.is_absentee_owner(
                                rec.get("property_address", ""),
                                rec.get("mailing_address"),
                            )
                            else 0,
                            existing["id"],
                        ),
                    )
                else:
                    self._db.execute(
                        """INSERT INTO ownership
                           (apn, recorded_owner, mailing_address, is_absentee)
                           VALUES (?, ?, ?, ?)""",
                        (
                            apn,
                            recorded_owner,
                            rec.get("mailing_address", ""),
                            1
                            if DiscoveryAgent.is_absentee_owner(
                                rec.get("property_address", ""),
                                rec.get("mailing_address"),
                            )
                            else 0,
                        ),
                    )

            saved += 1

        self._db.commit()
        logger.info("Saved %d CSV records to database.", saved)
        return saved

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        """Try to coerce *value* to int; return ``None`` on failure."""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _detect_format(headers: list[str]) -> dict[str, str]:
        """Detect CSV format by checking for known header patterns.

        Args:
            headers: Raw column names from the CSV.

        Returns:
            A column mapping dict {standard_name: source_header} or empty if
            no format matched.

        """
        header_set = {h.strip().lower() for h in headers}

        for format_name, mapping in COLUMN_MAP.items():
            # Check that at least 2 of the source columns are present
            source_cols = {v.lower() for v in mapping.values()}
            matches = header_set & source_cols
            if len(matches) >= 2:
                logger.debug("Matched CSV format: %s", format_name)
                return mapping

        return {}

    # ------------------------------------------------------------------
    # APN normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_apn(address: str, county: str) -> str | None:
        """Extract and normalise an APN from an address string.

        This is a best-effort placeholder.  Real APN look-up should use
        the county assessor's ArcGIS REST API.

        Args:
            address: Full property address.
            county: County name (e.g. ``"Orange County"``, ``"Los Angeles County"``).

        Returns:
            Normalised APN string, or ``None`` if not found.

        """
        # Try matching known APN patterns in the address
        pattern = APN_PATTERNS.get(county)
        if pattern:
            match = pattern.search(address)
            if match:
                return match.group(0)

        return None

    # ------------------------------------------------------------------
    # Address standardisation
    # ------------------------------------------------------------------

    def standardize_address(self, raw_address: str) -> str:
        """Standardise a raw address string using ``usaddress``.

        Falls back to stripping whitespace if parsing fails.

        Args:
            raw_address: The raw address text.

        Returns:
            A cleaned, standardised address string.

        """
        return normalize_address(raw_address)

    # ------------------------------------------------------------------
    # Absentee detection
    # ------------------------------------------------------------------

    @staticmethod
    def is_absentee_owner(
        property_address: str,
        mailing_address: str | None,
    ) -> bool:
        """Determine if the owner is absentee (mailing != property address).

        Args:
            property_address: The physical property address.
            mailing_address: The owner's mailing address on record.

        Returns:
            ``True`` if the mailing address differs from the property address.

        """
        if not mailing_address:
            return False

        prop_norm = DiscoveryAgent._addr_key(property_address)
        mail_norm = DiscoveryAgent._addr_key(mailing_address)
        return prop_norm != mail_norm

    @staticmethod
    def _addr_key(address: str) -> str:
        """Lower-case, strip punctuation, and collapse whitespace for comparison."""
        clean = re.sub(r"[^\w\s]", "", address).lower()
        return re.sub(r"\s+", " ", clean).strip()
