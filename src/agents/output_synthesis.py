"""Output Synthesis Agent — dedup, compliance filtering, and CRM export."""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

LEAD_FIELDS: list[str] = [
    "apn",
    "county",
    "property_address",
    "recorded_owner",
    "mailing_address",
    "is_absentee",
    "entity_type",
    "unmasked_principal_name",
    "unmasked_principal_phone",
    "unmasked_principal_email",
    "listing_status",
    "priority_score",
]


class OutputSynthesisAgent:
    """Format, deduplicate, and export lead data."""

    def __init__(self, db_conn: Any = None) -> None:
        """Store database reference.

        Args:
            db_conn: SQLite connection (or mock for testing).
                ``None`` is permitted — formatting and dedup methods
                work without a connection.

        """
        self._db = db_conn

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    @staticmethod
    def deduplicate(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove duplicate leads by APN, keeping the last occurrence.

        Args:
            leads: List of lead dictionaries.

        Returns:
            Deduplicated list (last-wins for each APN).

        """
        seen: dict[str, dict[str, Any]] = {}
        for lead in leads:
            apn = lead.get("apn")
            if apn:
                seen[apn] = lead
        return list(seen.values())

    # ------------------------------------------------------------------
    # Format export
    # ------------------------------------------------------------------

    def format_lead_export(
        self,
        leads: list[dict[str, Any]],
        export_format: str = "csv",
    ) -> str:
        """Format a list of leads into a string for export.

        Args:
            leads: Lead dictionaries.
            export_format: One of ``"csv"`` or ``"json"``.

        Returns:
            Formatted string content ready to write to a file or send to
            a CRM API.

        Raises:
            ValueError: If the format is not supported.

        """
        cleaned = self.deduplicate(leads)

        # Normalise each lead to the standard field set
        normalised: list[dict[str, Any]] = []
        for lead in cleaned:
            row: dict[str, Any] = {}
            for field in LEAD_FIELDS:
                row[field] = lead.get(field, "")
            normalised.append(row)

        if export_format == "csv":
            return self._to_csv(normalised)
        if export_format == "json":
            return json.dumps(normalised, indent=2, default=str)
        raise ValueError(f"Unsupported export format: {export_format}")

    @staticmethod
    def _to_csv(rows: list[dict[str, Any]]) -> str:
        """Render a list of dicts as a CSV string."""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=LEAD_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

    # ------------------------------------------------------------------
    # CRM-specific formatting
    # ------------------------------------------------------------------

    def format_hubspot_import(self, leads: list[dict[str, Any]]) -> str:
        """Format leads for HubSpot CSV import with mapped columns.

        Args:
            leads: Lead dictionaries.

        Returns:
            CSV string with HubSpot-compatible headers.

        """
        hubspot_fields: list[str] = [
            "Property Address",
            "Owner Name",
            "Owner Phone",
            "Owner Email",
            "Lead Score",
            "Notes",
        ]
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(hubspot_fields)

        for lead in self.deduplicate(leads):
            writer.writerow(
                [
                    lead.get("property_address", ""),
                    lead.get("unmasked_principal_name") or lead.get("recorded_owner", ""),
                    lead.get("unmasked_principal_phone", ""),
                    lead.get("unmasked_principal_email", ""),
                    lead.get("priority_score", 0.0),
                    f"APN: {lead.get('apn', '')} | County: {lead.get('county', '')}",
                ]
            )
        return output.getvalue()
