"""County Assessor ArcGIS REST API scrapers for Orange and Los Angeles counties."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from src.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

rate_limiter = RateLimiter()


# ------------------------------------------------------------------
# Safe SQL escaping for ArcGIS REST ``where`` parameters
# ------------------------------------------------------------------


def _escape_sql_literal(value: str) -> str:
    """Escape a string literal for safe use in an ArcGIS ``where`` clause.

    Doubles single-quote characters and discards any non-printable /
    control characters.  This is the standard SQL escape mechanism — the
    ArcGIS REST API does not support parameterised ``where`` clauses.

    Args:
        value: The raw user input.

    Returns:
        A safely escaped string suitable for embedding in a SQL ``WHERE``
        clause.

    """
    # Strip control characters except tab/newline, then double single quotes
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
    return cleaned.replace("'", "''")


def _validate_address(address: str) -> str:
    """Validate and sanitize an address string for ArcGIS queries.

    Only allows alphanumeric characters, spaces, hyphens, forward slashes,
    commas, periods, and hash signs — blocks any SQL-metacharacter input.

    Args:
        address: Raw address input.

    Returns:
        Sanitized address safe for embedding in a WHERE clause.

    Raises:
        ValueError: If the address contains disallowed characters.

    """
    sanitized = re.sub(r"[^\w\s\-/,.#]", "", address).strip()
    if not sanitized or len(sanitized) < 3:
        msg = f"Invalid address: '{address}'"
        raise ValueError(msg)
    return sanitized


def _validate_apn(apn: str) -> str:
    """Validate an APN string — only allows digits and hyphens.

    Args:
        apn: Raw APN input.

    Returns:
        Sanitized APN.

    Raises:
        ValueError: If the APN contains invalid characters.

    """
    sanitized = re.sub(r"[^\d\-]", "", apn).strip()
    if not sanitized:
        msg = f"Invalid APN: '{apn}'"
        raise ValueError(msg)
    return sanitized


# Known ArcGIS REST endpoints (discovered from county assessor portals)
# These are the parcel/map-server query URLs for each county.
COUNTY_ENDPOINTS: dict[str, str] = {
    "Orange County": (
        "https://maps.ocgov.com/ocgis/rest/services/"
        "Assessor/Parcels/MapServer/0/query"
    ),
    "Los Angeles County": (
        "https://gis.lacounty.gov/server/rest/services/"
        "Tax_Assessor/Assessor_Parcels/MapServer/0/query"
    ),
}


# ------------------------------------------------------------------
# APN lookup by address
# ------------------------------------------------------------------


def lookup_apn_by_address(address: str, county: str) -> str | None:
    """Query the county assessor ArcGIS server for an APN matching *address*.

    Args:
        address: The street address to look up.
        county: ``"Orange County"`` or ``"Los Angeles County"``.

    Returns:
        The APN string if found, else ``None``.

    Raises:
        ValueError: If the county is not supported.

    """
    endpoint = COUNTY_ENDPOINTS.get(county)
    if not endpoint:
        raise ValueError(f"Unsupported county: {county}")

    rate_limiter.wait_if_needed(county)

    safe_address = _escape_sql_literal(_validate_address(address))
    params: dict[str, Any] = {
        "where": f"UPPER(SITEADDR) LIKE '%{safe_address}%'",
        "outFields": "APN",
        "returnGeometry": "false",
        "f": "json",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(endpoint, params=params)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
    except httpx.RequestError as exc:
        logger.exception("ArcGIS request failed for %s: %s", county, exc)
        rate_limiter.record_failure(county)
        return None

    try:
        features: list[dict[str, Any]] = data.get("features", [])
        if features:
            apn: str = str(features[0]["attributes"].get("APN", ""))
            logger.info("Found APN '%s' for '%s' in %s", apn, address, county)
            rate_limiter.record_success(county)
            return apn
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("Unexpected ArcGIS response structure: %s", exc)

    rate_limiter.record_success(county)
    logger.info("No APN found for '%s' in %s", address, county)
    return None


# ------------------------------------------------------------------
# Assessed value lookup
# ------------------------------------------------------------------


def get_assessed_value(apn: str, county: str) -> int | None:
    """Retrieve the assessed value of a parcel by APN.

    Args:
        apn: The 10-11 digit APN string.
        county: ``"Orange County"`` or ``"Los Angeles County"``.

    Returns:
        The assessed value in whole dollars, or ``None``.

    Raises:
        ValueError: If the county is not supported.

    """
    endpoint = COUNTY_ENDPOINTS.get(county)
    if not endpoint:
        raise ValueError(f"Unsupported county: {county}")

    rate_limiter.wait_if_needed(county)

    # APN format varies by county; the outFields column may differ
    value_field = "ASSESSEDVALUE" if county == "Orange County" else "ASSESSED_VALUE"
    safe_apn = _escape_sql_literal(_validate_apn(apn))
    params: dict[str, Any] = {
        "where": f"APN = '{safe_apn}'",
        "outFields": value_field,
        "returnGeometry": "false",
        "f": "json",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(endpoint, params=params)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
    except httpx.RequestError as exc:
        logger.exception("ArcGIS value lookup failed for APN %s: %s", apn, exc)
        rate_limiter.record_failure(county)
        return None

    try:
        features = data.get("features", [])
        if features:
            raw = features[0]["attributes"].get(value_field)
            if raw is not None:
                rate_limiter.record_success(county)
                return int(raw)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("Could not parse assessed value for APN %s: %s", apn, exc)

    rate_limiter.record_success(county)
    return None
