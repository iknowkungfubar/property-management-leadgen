"""County Assessor ArcGIS REST API scrapers for Orange and Los Angeles counties.

Provides address-to-APN and APN-to-parcel-data lookup against public
ArcGIS MapServer endpoints maintained by each county's assessor office.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from src.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

rate_limiter = RateLimiter()

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

REQUEST_TIMEOUT: float = 30.0  # seconds — configurable per caller via _arcgis_query
MAX_RETRIES: int = 3
"""Number of *additional* attempts after the initial request (1 + 3 = 4 total)."""

RETRY_BACKOFF: tuple[float, ...] = (1.0, 2.0, 4.0)
"""Sleep between retries in seconds (exponential).  ``RETRY_BACKOFF[attempt -1]``."""

# Status codes that warrant a retry
RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 502, 503, 504})

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
        "https://maps.ocgov.com/ocgis/rest/services/Assessor/Parcels/MapServer/0/query"
    ),
    "Los Angeles County": (
        "https://gis.lacounty.gov/server/rest/services/"
        "Tax_Assessor/Assessor_Parcels/MapServer/0/query"
    ),
}

# ------------------------------------------------------------------
# Internal: shared ArcGIS query helper with retry
# ------------------------------------------------------------------


def _arcgis_query(
    endpoint: str,
    params: dict[str, Any],
    *,
    domain: str = "unknown",
    timeout: float = REQUEST_TIMEOUT,
) -> dict[str, Any] | None:
    """Execute an ArcGIS REST query with retry and exponential backoff.

    Args:
        endpoint: Full ArcGIS MapServer query URL.
        params: URL query-string parameters (``where``, ``outFields``, …).
        domain: Label passed to the rate limiter for pacing.
        timeout: HTTP request timeout in seconds (default 30 s).

    Returns:
        The first feature's ``attributes`` dict, or ``None`` when no result
        is found or all retries are exhausted.

    """
    rate_limiter.wait_if_needed(domain)

    last_exc: Exception | None = None

    for attempt in range(1 + MAX_RETRIES):
        try:
            with httpx.Client() as client:
                resp = client.get(endpoint, params=params, timeout=timeout)

            # Non-retryable client error (4xx except 429)
            if resp.status_code in (400, 401, 403, 404, 422):
                logger.warning(
                    "ArcGIS request failed (HTTP %d) for '%s': %s",
                    resp.status_code,
                    domain,
                    resp.text[:200],
                )
                rate_limiter.record_failure(domain)
                return None

            resp.raise_for_status()
            data: dict[str, Any] = resp.json()

        except httpx.TimeoutException as exc:
            last_exc = exc
            logger.warning(
                "ArcGIS timeout (attempt %d/%d) for '%s'",
                attempt + 1,
                1 + MAX_RETRIES,
                domain,
            )
            rate_limiter.record_failure(domain)
            _retry_sleep(attempt)
            continue

        except httpx.HTTPStatusError as exc:
            last_exc = exc
            status = exc.response.status_code
            if status in RETRYABLE_STATUSES:
                logger.warning(
                    "ArcGIS retryable HTTP %d (attempt %d/%d) for '%s'",
                    status,
                    attempt + 1,
                    1 + MAX_RETRIES,
                    domain,
                )
                rate_limiter.record_failure(domain)
                _retry_sleep(attempt)
                continue
            logger.error(
                "ArcGIS non-retryable HTTP %d for '%s': %s",
                status,
                domain,
                exc.response.text[:200],
            )
            rate_limiter.record_failure(domain)
            return None

        except httpx.RequestError as exc:
            last_exc = exc
            logger.warning(
                "ArcGIS connection error (attempt %d/%d) for '%s': %s",
                attempt + 1,
                1 + MAX_RETRIES,
                domain,
                exc,
            )
            rate_limiter.record_failure(domain)
            _retry_sleep(attempt)
            continue

        # ---- Parse the JSON response ----
        try:
            features: list[dict[str, Any]] = data.get("features", [])
            if not features:
                logger.debug("ArcGIS returned 0 features for '%s'", domain)
                rate_limiter.record_success(domain)
                return None

            attributes: dict[str, Any] = features[0].get("attributes", {})
            if not attributes:
                logger.warning("ArcGIS feature missing 'attributes' key for '%s'", domain)
                rate_limiter.record_success(domain)
                return None

            logger.debug(
                "ArcGIS query OK for '%s' — %d feature(s), %d attribute(s)",
                domain,
                len(features),
                len(attributes),
            )
            rate_limiter.record_success(domain)
            return attributes

        except (KeyError, IndexError, TypeError) as exc:
            logger.warning(
                "ArcGIS malformed response for '%s': %s — data=%s",
                domain,
                exc,
                str(data)[:300],
            )
            rate_limiter.record_failure(domain)
            return None

    # All retries exhausted
    logger.error(
        "ArcGIS query failed for '%s' after %d retries: %s",
        domain,
        MAX_RETRIES,
        last_exc,
    )
    return None


def _retry_sleep(attempt: int) -> None:
    """Block for the exponential-backoff duration for *attempt*.

    Args:
        attempt: The zero-based attempt index (0 → first backoff at 1 s).

    """
    if attempt < len(RETRY_BACKOFF):
        delay = RETRY_BACKOFF[attempt]
    else:
        delay = RETRY_BACKOFF[-1]  # cap at the last value
    logger.debug("Retry backoff %.1f s (attempt %d)", delay, attempt + 1)
    time.sleep(delay)


def _get_endpoint(county: str) -> str:
    """Look up the ArcGIS endpoint for *county*.

    Args:
        county: ``"Orange County"`` or ``"Los Angeles County"``.

    Returns:
        The query endpoint URL.

    Raises:
        ValueError: If *county* is not in ``COUNTY_ENDPOINTS``.

    """
    endpoint = COUNTY_ENDPOINTS.get(county)
    if not endpoint:
        raise ValueError(f"Unsupported county: {county}")
    return endpoint


def _domain_label(county: str) -> str:
    """Return a rate-limiter domain label for a county name.

    Uses a short slug suitable for the rate limiter's per-domain tracking.
    """
    return county.lower().replace(" ", "_")


# ------------------------------------------------------------------
# Public API — search methods  (preferred entry points)
# ------------------------------------------------------------------


def search_by_address(
    address: str,
    county: str,
    *,
    timeout: float = REQUEST_TIMEOUT,
) -> dict[str, Any] | None:
    """Look up a parcel by street address via the county ArcGIS server.

    Args:
        address: Street address to search for (e.g. ``"123 Main St"``).
        county: ``"Orange County"`` or ``"Los Angeles County"``.
        timeout: HTTP request timeout in seconds.

    Returns:
        A dictionary of feature attributes (APN, assessed value, property
        type, …) or ``None`` if no match is found.

    Raises:
        ValueError: If *county* is unsupported or *address* is invalid.

    """
    endpoint = _get_endpoint(county)
    safe_address = _escape_sql_literal(_validate_address(address))
    params: dict[str, Any] = {
        "where": f"UPPER(SITEADDR) LIKE '%{safe_address}%'",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }

    logger.info("Searching for address '%s' in %s", address, county)
    return _arcgis_query(endpoint, params, domain=_domain_label(county), timeout=timeout)


def search_by_apn(
    apn: str,
    county: str,
    *,
    timeout: float = REQUEST_TIMEOUT,
) -> dict[str, Any] | None:
    """Look up a parcel by APN via the county ArcGIS server.

    Args:
        apn: Assessor's Parcel Number (e.g. ``"123-456-789"``).
        county: ``"Orange County"`` or ``"Los Angeles County"``.
        timeout: HTTP request timeout in seconds.

    Returns:
        A dictionary of feature attributes or ``None`` if no match is found.

    Raises:
        ValueError: If *county* is unsupported or *apn* is invalid.

    """
    endpoint = _get_endpoint(county)
    safe_apn = _escape_sql_literal(_validate_apn(apn))
    params: dict[str, Any] = {
        "where": f"APN = '{safe_apn}'",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }

    logger.info("Searching for APN '%s' in %s", apn, county)
    return _arcgis_query(endpoint, params, domain=_domain_label(county), timeout=timeout)


# ------------------------------------------------------------------
# Backward-compatible convenience wrappers
# ------------------------------------------------------------------


def lookup_apn_by_address(address: str, county: str) -> str | None:
    """Query the county assessor ArcGIS server for an APN matching *address*.

    This is a convenience wrapper around :func:`search_by_address` and
    will eventually be removed in favour of the richer return value.

    Args:
        address: The street address to look up.
        county: ``"Orange County"`` or ``"Los Angeles County"``.

    Returns:
        The APN string if found, else ``None``.

    """
    attributes = search_by_address(address, county)
    if attributes:
        apn: str = str(attributes.get("APN", "") or "")
        if apn:
            logger.info("Found APN '%s' for '%s' in %s", apn, address, county)
            return apn
        logger.warning(
            "ArcGIS returned features but no APN field for '%s' in %s",
            address,
            county,
        )
    else:
        logger.info("No APN found for '%s' in %s", address, county)
    return None


def get_assessed_value(apn: str, county: str) -> int | None:
    """Retrieve the assessed value of a parcel by APN.

    This is a convenience wrapper around :func:`search_by_apn` and will
    eventually be removed in favour of the richer return value.

    Args:
        apn: The 10-11 digit APN string.
        county: ``"Orange County"`` or ``"Los Angeles County"``.

    Returns:
        The assessed value in whole dollars, or ``None``.

    """
    # APN format varies by county; the field name may differ
    value_field = "ASSESSEDVALUE" if county == "Orange County" else "ASSESSED_VALUE"
    attributes = search_by_apn(apn, county)
    if attributes:
        raw = attributes.get(value_field)
        if raw is not None:
            try:
                return int(raw)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "Could not parse assessed value for APN %s: %s (raw=%r)",
                    apn,
                    exc,
                    raw,
                )
        else:
            logger.debug(
                "No assessed value field '%s' in response for APN %s",
                value_field,
                apn,
            )
    return None
