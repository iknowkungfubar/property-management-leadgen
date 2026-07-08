"""HubSpot CRM API client for contact upsert and batch operations.

Uses the Private App token (OAuth2) for authentication against
HubSpot's REST API v3.  Implements client-side rate limiting to stay
within HubSpot's 100 requests per 10 seconds limit.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

import httpx

from src.utils.hubspot_client.errors import HubSpotError, HubSpotAuthError, HubSpotRateLimitError, HubSpotValidationError

logger = logging.getLogger(__name__)


# ── Constants ──
BASE_URL: str = "https://api.hubapi.com"
CONTACTS_ENDPOINT: str = f"{BASE_URL}/crm/v3/objects/contacts"
CONTACTS_BATCH_UPSERT: str = f"{BASE_URL}/crm/v3/objects/contacts/batch/upsert"
SEARCH_ENDPOINT: str = f"{BASE_URL}/crm/v3/objects/contacts/search"

# Rate limit: 100 requests per 10 seconds per app
MAX_REQUESTS: int = 100
WINDOW_SECONDS: float = 10.0

# HubSpot property name mappings from our internal fields
FIELD_MAP: dict[str, str] = {
    "property_address": "address",
    "recorded_owner": "hs_legal_entity_name",
    "unmasked_principal_name": "firstname",
    "unmasked_principal_phone": "phone",
    "unmasked_principal_email": "email",
    "priority_score": "hs_lead_score",
    "apn": "hs_lead_id",
    "county": "hs_city",
    "listing_status": "hs_marketing_status",
    "is_absentee": "hs_lead_status",
}
"""Maps internal lead field names to HubSpot contact property names."""


# ── Client ──


class HubSpotClient:
    """Client for the HubSpot CRM Contacts API.

    Handles authentication, request rate limiting, and error parsing.
    Uses ``httpx`` for HTTP calls.

    Args:
        api_key: HubSpot private app access token.

    """

    def __init__(self, api_key: str) -> None:
        """Initialise the client with a private app token.

        Args:
            api_key: HubSpot private app access token (starts with
                ``pat-`` for personal access tokens, or a standard
                private app token).

        """
        self._api_key: str = api_key
        self._client: httpx.Client = httpx.Client(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        # Request timestamps for client-side rate limiting
        self._request_timestamps: deque[float] = deque(maxlen=MAX_REQUESTS)

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _wait_if_needed(self) -> None:
        """Block until we are within the HubSpot rate limit.

        Maintains a sliding window of the last ``MAX_REQUESTS`` request
        timestamps.  If the window is full (100 requests), sleep until
        the oldest timestamp falls outside the 10-second window.
        """
        now = time.monotonic()

        # Prune timestamps outside the current window
        while self._request_timestamps and self._request_timestamps[0] <= now - WINDOW_SECONDS:
            self._request_timestamps.popleft()

        if len(self._request_timestamps) >= MAX_REQUESTS:
            # Need to wait — oldest request hasn't fallen out of window yet
            oldest = self._request_timestamps[0]
            sleep_for = oldest + WINDOW_SECONDS - now
            if sleep_for > 0:
                logger.debug(
                    "Rate limit reached — sleeping %.2fs (window: %d/%d)",
                    sleep_for,
                    len(self._request_timestamps),
                    MAX_REQUESTS,
                )
                time.sleep(sleep_for)

        self._request_timestamps.append(time.monotonic())

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_error(response: httpx.Response) -> HubSpotError:
        """Parse a HubSpot API error response into a typed exception.

        Args:
            response: The HTTP response from HubSpot.

        Returns:
            A ``HubSpotError`` subclass appropriate for the status code.

        """
        status = response.status_code
        body: str = response.text

        # Try to extract a human-readable message from the HubSpot error body
        message: str = f"HTTP {status}"
        try:
            payload: dict[str, Any] = response.json()
            if "message" in payload:
                message = payload["message"]
            elif "error" in payload:
                message = payload["error"]
            # HubSpot sometimes nests errors under "errors[].message"
            if "errors" in payload and isinstance(payload["errors"], list):
                details = "; ".join(
                    e.get("message", "") for e in payload["errors"] if isinstance(e, dict)
                )
                if details:
                    message = f"{message} — {details}"
        except (json.JSONDecodeError, ValueError):
            message = body[:200] if body else f"HTTP {status}"

        logger.error("HubSpot API error: %s", message)

        if status == 401 or status == 403:
            return HubSpotAuthError(message)
        if status == 429:
            return HubSpotRateLimitError(message)
        if status == 400:
            return HubSpotValidationError(message)
        return HubSpotError(message)

    # ------------------------------------------------------------------
    # Contact upsert (single)
    # ------------------------------------------------------------------

    def upsert_contact(self, email: str, properties: dict[str, str]) -> str:
        """Create or update a HubSpot contact identified by email.

        Uses the batch upsert endpoint with a single contact, matching
        on the ``email`` identity property.  This avoids a separate
        search-then-create round-trip.

        Args:
            email: Contact email address (used as the identity for upsert).
            properties: HubSpot property key-value pairs to set on the
                contact.

        Returns:
            The HubSpot contact ID of the created/updated contact.

        Raises:
            HubSpotAuthError: Invalid or missing API token.
            HubSpotRateLimitError: Rate limited by HubSpot.
            HubSpotValidationError: Invalid property names or values.
            HubSpotError: Other HubSpot API error.

        """
        # Merge email into properties if not already present
        props = dict(properties)
        if "email" not in props:
            props["email"] = email

        payload: dict[str, Any] = {
            "inputs": [
                {
                    "idProperty": "email",
                    "id": email,
                    "properties": props,
                }
            ],
        }

        self._wait_if_needed()
        logger.info(
            "Upserting contact email=%s properties=%s",
            email,
            _mask_sensitive(props),
        )

        try:
            response = self._client.post(
                CONTACTS_BATCH_UPSERT,
                content=json.dumps(payload),
            )
        except httpx.RequestError as exc:
            logger.error("HubSpot request failed for %s: %s", email, exc)
            raise HubSpotError(f"Request failed: {exc}") from exc

        if response.is_error:
            raise self._parse_error(response)

        result: dict[str, Any] = response.json()
        results: list[dict[str, Any]] = result.get("results", [])
        if results:
            contact_id: str = str(results[0].get("id", ""))
            logger.info("Contact upserted: id=%s email=%s", contact_id, email)
            return contact_id

        logger.warning("HubSpot batch upsert returned no results for %s", email)
        return ""

    # ------------------------------------------------------------------
    # Batch upsert
    # ------------------------------------------------------------------

    def batch_upsert(self, contacts: list[dict[str, Any]]) -> dict[str, Any]:
        """Upsert multiple contacts in a single API call.

        Each contact dict must have at least an ``email`` key.  All other
        keys are treated as HubSpot contact properties.

        Args:
            contacts: List of contact dicts, each containing at minimum
                an ``email`` field and optional property key-value pairs.

        Returns:
            A summary dict with:
            - ``total`` — number of contacts submitted.
            - ``succeeded`` — list of contact IDs that were created/updated.
            - ``failed`` — list of dicts with ``email`` and ``error`` for
              each failed contact.
            - ``errors`` — list of raw error messages from the API.

        Raises:
            HubSpotAuthError: Invalid or missing API token.
            HubSpotRateLimitError: Rate limited by HubSpot.
            HubSpotError: Other HubSpot API error.

        """
        if not contacts:
            logger.info("batch_upsert called with empty list — nothing to do.")
            return {"total": 0, "succeeded": [], "failed": [], "errors": []}

        inputs: list[dict[str, Any]] = []
        for contact in contacts:
            email = contact.get("email", "")
            if not email:
                logger.warning("Skipping contact without email: %s", _mask_sensitive(contact))
                continue

            props = dict(contact)
            props.pop("email", None)

            inputs.append(
                {
                    "idProperty": "email",
                    "id": email,
                    "properties": props,
                }
            )

        if not inputs:
            return {"total": 0, "succeeded": [], "failed": [], "errors": []}

        payload: dict[str, Any] = {"inputs": inputs}

        self._wait_if_needed()
        logger.info("Batch upserting %d contact(s) …", len(inputs))

        try:
            response = self._client.post(
                CONTACTS_BATCH_UPSERT,
                content=json.dumps(payload),
            )
        except httpx.RequestError as exc:
            logger.error("HubSpot batch request failed: %s", exc)
            raise HubSpotError(f"Batch request failed: {exc}") from exc

        if response.is_error:
            raise self._parse_error(response)

        result: dict[str, Any] = response.json()

        succeeded: list[str] = [str(r["id"]) for r in result.get("results", []) if r.get("id")]
        failed: list[dict[str, str]] = []
        raw_errors: list[str] = []
        for err in result.get("errors", []):
            email = err.get("id", err.get("email", "unknown"))
            message = err.get("message", "Unknown error")
            failed.append({"email": email, "error": message})
            raw_errors.append(f"{email}: {message}")

        logger.info(
            "Batch upsert complete: %d succeeded, %d failed",
            len(succeeded),
            len(failed),
        )
        if failed:
            logger.warning("Batch upsert failures: %s", "; ".join(raw_errors))

        return {
            "total": len(inputs),
            "succeeded": succeeded,
            "failed": failed,
            "errors": raw_errors,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP client and free resources."""
        self._client.close()
        logger.debug("HubSpot client connection closed.")


# ── Helpers ────────────────────────────────────────────────────────────────


def _mask_sensitive(props: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *props* with sensitive fields masked for logging.

    Masks ``apiKey``, ``access_token``, and ``email`` values beyond the
    first two characters.

    Args:
        props: Dictionary of property key-value pairs.

    Returns:
        A new dict with sensitive values truncated.

    """
    masked: dict[str, Any] = {}
    sensitive_keys: set[str] = {"apiKey", "access_token"}
    for k, v in props.items():
        if k in sensitive_keys and isinstance(v, str) and len(v) > 4:
            masked[k] = v[:2] + "****"
        elif k == "email" and isinstance(v, str) and len(v) > 4:
            masked[k] = v[:2] + "****" + v[-4:] if "@" in v else v[:2] + "****"
        else:
            masked[k] = v
    return masked


# ── Field mapping helper ───────────────────────────────────────────────────


def map_lead_to_hubspot_properties(lead: dict[str, Any]) -> dict[str, str]:
    """Convert an internal lead dict to HubSpot contact properties.

    Uses ``FIELD_MAP`` to translate internal field names to HubSpot
    property names.  Unknown fields are dropped.  All values are
    converted to strings for the HubSpot API.

    Args:
        lead: Internal lead dictionary with keys matching ``LEAD_FIELDS``.

    Returns:
        Dictionary of HubSpot property names to string values.

    """
    props: dict[str, str] = {}
    for internal_key, hubspot_key in FIELD_MAP.items():
        value = lead.get(internal_key)
        if value is not None and value != "":
            props[hubspot_key] = str(value)
    return props
