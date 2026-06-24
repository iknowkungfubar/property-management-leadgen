"""CSV import utilities — column mapping and address normalisation."""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

import usaddress

logger = logging.getLogger(__name__)

# ── Known CSV format column maps ──────────────────────────────────────
# Maps our internal field name to the source column header.
# We detect the format by checking which source headers are present.

COLUMN_MAP: dict[str, dict[str, str]] = {
    "orange_coast_title": {
        "apn": "APN",
        "county": "COUNTY",
        "property_address": "SITUS ADDRESS",
        "property_type": "PROPERTY TYPE",
        "assessed_value": "ASSESSED VALUE",
        "recorded_owner": "ASSESSED OWNER",
        "mailing_address": "MAILING ADDRESS",
    },
    "crmls": {
        "apn": "APN/Parcel Number",
        "county": "County",
        "property_address": "Full Address",
        "property_type": "Property Type",
        "assessed_value": "Assessed Value",
        "recorded_owner": "Owner Name",
        "mailing_address": "Owner Mailing Address",
    },
}


def parse_csv_file(file_path: str | Path) -> list[dict[str, str]]:
    """Read a CSV file and return a list of raw rows.

    Args:
        file_path: Path to the CSV file.

    Returns:
        List of dictionaries keyed by the CSV header.

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If the CSV is empty or has no headers.

    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {file_path}")

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError("CSV file has no headers.")
        rows: list[dict[str, str]] = [
            {k: v.strip() if v else "" for k, v in row.items()} for row in reader
        ]

    logger.info("Parsed %d rows from %s", len(rows), path.name)
    return rows


def normalize_address(raw: str) -> str:
    """Parse and reformat a US address using ``usaddress``.

    Falls back to stripping excessive whitespace if parsing fails.

    Args:
        raw: The raw address string.

    Returns:
        Cleaned address string.

    """
    if not raw or not raw.strip():
        return ""

    try:
        parsed, _ = usaddress.tag(raw)
        # Build a readable address: AddressNumber StreetName StreetPostType …
        components = [
            parsed.get("AddressNumber", ""),
            parsed.get("StreetNamePreDirectional", ""),
            parsed.get("StreetName", ""),
            parsed.get("StreetNamePostType", ""),
            parsed.get("OccupancyType", ""),
            parsed.get("OccupancyIdentifier", ""),
            parsed.get("PlaceName", ""),
            parsed.get("StateName", ""),
            parsed.get("ZipCode", ""),
        ]
        cleaned = " ".join(part for part in components if part)
        return re.sub(r"\s+", " ", cleaned).strip()
    except (usaddress.RepeatedLabelError, usaddress.ParsingException) as exc:
        logger.debug("usaddress parsing failed: %s — falling back to raw.", exc)
        return re.sub(r"\s+", " ", raw.strip())
