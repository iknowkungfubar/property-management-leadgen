"""Entity Unmasking Agent — identifies principals behind LLCs and trusts.

When a recorded owner is an individual, the record passes through for
skip-tracing.  When the owner is an entity (LLC, Inc, Trust), the agent
performs a CA Secretary of State look-up to find the real human principals.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)

# CA SoS bizfile API endpoints
SOS_SEARCH_URL: str = (
    "https://bizfileonline.sos.ca.gov/api/search/entity-search"
)
SOS_PDF_BASE: str = "https://bizfileonline.sos.ca.gov"

# Indicators that the recorded owner is a business entity rather than a person
ENTITY_INDICATORS: list[re.Pattern[str]] = [
    re.compile(r"\bLLC\b", re.IGNORECASE),
    re.compile(r"\bL\.?L\.?C\.?\b", re.IGNORECASE),
    re.compile(r"\bINC\.?\b", re.IGNORECASE),
    re.compile(r"\bCORP\.?\b", re.IGNORECASE),
    re.compile(r"\bCORPORATION\b", re.IGNORECASE),
    re.compile(r"\bTRUST\b", re.IGNORECASE),
    re.compile(r"\bLP\b", re.IGNORECASE),
    re.compile(r"\bLLP\b", re.IGNORECASE),
    re.compile(r"\bLIMITED\b", re.IGNORECASE),
    re.compile(r"\bCOMPANY\b", re.IGNORECASE),
    re.compile(r"\bHOLDINGS?\b", re.IGNORECASE),
    re.compile(r"\bPROPERT(?:Y|IES)\b", re.IGNORECASE),
    re.compile(r"\bMANAGEMENT\b", re.IGNORECASE),
]


class EntityUnmaskingAgent:
    """Unmask entity ownership to find real human decision-makers."""

    def __init__(self, llm_client: LLMProvider | None = None) -> None:
        """Optionally inject an LLM client for SoS PDF parsing.

        Args:
            llm_client: An LLM provider.  If ``None``, the agent works in
                rule-based mode only.

        """
        self._llm = llm_client

    # ------------------------------------------------------------------
    # Entity detection
    # ------------------------------------------------------------------

    @staticmethod
    def is_entity(recorded_owner: str) -> bool:
        """Heuristically determine whether the owner is a business entity.

        Args:
            recorded_owner: The owner name from the tax roll.

        Returns:
            ``True`` if the name contains entity keywords.

        """
        return any(pattern.search(recorded_owner) for pattern in ENTITY_INDICATORS)

    @staticmethod
    def classify_entity_type(recorded_owner: str) -> str:
        """Classify the entity type from the owner string.

        Args:
            recorded_owner: The owner name.

        Returns:
            One of ``"llc"``, ``"corporation"``, ``"trust"``, ``"partnership"``,
            or ``"individual"``.

        """
        owner_upper = recorded_owner.upper()

        if re.search(r"\b(?:LLC|L\.?L\.?C\.?)\b", owner_upper):
            return "llc"
        if re.search(r"\b(?:INC|CORP|CORPORATION)\b", owner_upper):
            return "corporation"
        if re.search(r"\bTRUST\b", owner_upper):
            return "trust"
        if re.search(r"\b(?:LP|LLP|LIMITED PARTNERSHIP)\b", owner_upper):
            return "partnership"
        if re.search(r"\bLIMITED\b", owner_upper):
            return "llc"  # many "Limited" names are LLCs filed elsewhere
        return "individual"

    # ------------------------------------------------------------------
    # Unmask entry point
    # ------------------------------------------------------------------

    def unmask_entity(
        self,
        apn: str,
        recorded_owner: str,
        llm_client: LLMProvider | None = None,
    ) -> dict[str, Any]:
        """Analyse a recorded owner and return unmasking results.

        If the owner is an individual, the result flags them for skip-tracing.
        If the owner is an entity, a CA SoS look-up is recommended.

        Args:
            apn: The property APN (for cross-referencing).
            recorded_owner: Owner name from the tax roll.
            llm_client: Optional override LLM client.

        Returns:
            A dictionary with keys::

                - apn
                - recorded_owner
                - is_entity (bool)
                - entity_type (str)
                - needs_sos_lookup (bool)
                - unmasked_principal_name (str | None)
                - unmasked_principal_phone (str | None)

        """
        entity_flag = self.is_entity(recorded_owner)
        entity_type = self.classify_entity_type(recorded_owner)

        result: dict[str, Any] = {
            "apn": apn,
            "recorded_owner": recorded_owner,
            "is_entity": entity_flag,
            "entity_type": entity_type,
            "needs_sos_lookup": entity_flag,
            "unmasked_principal_name": None,
            "unmasked_principal_phone": None,
        }

        if not entity_flag:
            logger.info(
                "Owner '%s' appears to be an individual — marking for skip-trace.",
                recorded_owner,
            )
            result["unmasked_principal_name"] = recorded_owner
            return result

        # If we have an LLM, attempt to extract a principal from a SoS PDF
        # (the caller must have fetched the PDF and passed it separately)
        logger.info(
            "Owner '%s' is a %s — flagged for CA SoS look-up.",
            recorded_owner,
            entity_type,
        )
        return result

    # ------------------------------------------------------------------
    # CA SOS lookup
    # ------------------------------------------------------------------

    def perform_sos_lookup(
        self,
        recorded_owner: str,
        llm_client: LLMProvider | None = None,
    ) -> dict[str, Any]:
        """Search CA Secretary of State and parse the Statement of Information.

        This performs the actual SOS lookup that ``unmask_entity`` flags as
        needed.  The method is separate so callers can control when the HTTP
        and LLM cost of a lookup is incurred.

        Args:
            recorded_owner: The entity name to search (e.g. ``"Main St Holdings LLC"``).
            llm_client: An LLM provider for PDF text extraction.  If ``None``,
                only the search step is performed.

        Returns:
            A dict with keys::

                - sos_number (str | None)
                - status (str) — ``"found"``, ``"not_found"``, or ``"error"``
                - entity_type (str | None)
                - principals (list[dict]) — extracted principal info
                - registered_agent (dict | None)

        """
        result: dict[str, Any] = {
            "sos_number": None,
            "status": "not_found",
            "entity_type": None,
            "principals": [],
            "registered_agent": None,
        }

        try:
            sos_data = self._search_sos(recorded_owner)
        except Exception as exc:
            logger.exception("SOS search failed for '%s'", recorded_owner)
            result["status"] = "error"
            result["_error"] = str(exc)
            return result

        if not sos_data:
            logger.info("No SOS entity found for '%s'", recorded_owner)
            return result

        result["sos_number"] = sos_data.get("entityNumber")
        result["entity_type"] = sos_data.get("entityType")
        result["status"] = "found"

        # If we have an LLM, try to download and parse the Statement of Information
        if llm_client is not None and sos_data.get("entityNumber"):
            pdf_result = self._download_and_parse_sos_pdf(
                entity_number=sos_data["entityNumber"],
                entity_name=recorded_owner,
                llm_client=llm_client,
            )
            if pdf_result:
                result["principals"] = pdf_result.get("principals", [])
                result["registered_agent"] = {
                    "name": pdf_result.get("registered_agent_name"),
                    "address": pdf_result.get("registered_agent_address"),
                }

        return result

    @staticmethod
    def _search_sos(entity_name: str) -> dict[str, Any] | None:
        """Search the CA SoS bizfile API for an entity by name.

        Args:
            entity_name: The entity name to search for.

        Returns:
            The first matching entity dict, or ``None``.

        """
        try:
            resp = httpx.post(
                SOS_SEARCH_URL,
                json={"searchTerm": entity_name, "pageSize": 5},
                timeout=15.0,
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            hits: list[dict[str, Any]] = data.get("results", []) or data.get(
                "hits", [],
            )
            if hits:
                return hits[0]
        except httpx.RequestError as exc:
            logger.exception("SOS API request failed")
        except (KeyError, json.JSONDecodeError) as exc:
            logger.exception("Failed to parse SOS API response")
        return None

    @staticmethod
    def _get_sos_pdf_url(entity_number: str) -> str | None:
        """Get the Statement of Information PDF URL for an entity.

        Args:
            entity_number: The CA SOS entity number.

        Returns:
            A PDF download URL or ``None``.

        """
        # The CA SoS bizfile portal serves statements of information at a
        # known URL pattern.  This may change over time.
        return (
            f"{SOS_PDF_BASE}/api/document/"
            f"{entity_number}/statement-of-information"
        )

    @staticmethod
    def _download_and_parse_sos_pdf(
        entity_number: str,
        entity_name: str,
        llm_client: LLMProvider,
    ) -> dict[str, Any] | None:
        """Download a Statement of Information PDF and parse it via LLM.

        Args:
            entity_number: The CA SOS entity number.
            entity_name: The entity name (for logging).
            llm_client: An LLM provider for PDF text extraction.

        Returns:
            Parsed entity data, or ``None`` on failure.

        """
        from src.scrapers.ca_sos_parser import CASOSParser  # noqa: PLC0415

        pdf_url = EntityUnmaskingAgent._get_sos_pdf_url(entity_number)
        if not pdf_url:
            return None

        try:
            resp = httpx.get(pdf_url, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
        except httpx.RequestError:
            logger.exception(
                "Failed to download SOS PDF for %s (%s)",
                entity_name, entity_number,
            )
            return None

        # Save to a temporary file for CASOSParser
        import tempfile  # noqa: PLC0415

        with tempfile.NamedTemporaryFile(
            suffix=".pdf", delete=False,
        ) as tmp:
            tmp.write(resp.content)
            pdf_path = tmp.name

        try:
            parser = CASOSParser(llm_client)
            return parser.parse_statement_of_information(pdf_path)
        finally:
            Path(pdf_path).unlink(missing_ok=True)
