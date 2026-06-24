"""Rental listing scrapers — FRBO, Craigslist, and portal-based vacancy detection.

These are scaffolding modules that will later use Playwright for headed
browser automation.  For now they serve as API stubs.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def check_frbo_listings(address: str) -> list[dict[str, Any]]:
    """Search "For Rent By Owner" listings for matching properties.

    Args:
        address: The property street address.

    Returns:
        A list of listing dicts with keys::

            - source (str): e.g. ``"frbo.com"``
            - url (str | None)
            - price (int | None)
            - listed_date (str | None)
            - status (str): ``"active"``, ``"pending"``, or ``"not_found"``

    Notes:
        Real implementation will use Playwright to query FRBO and similar
        portals.  This stub returns an empty list.

    """
    logger.debug("FRBO check called for: %s (stub)", address)
    return []


async def check_craigslist(address: str) -> list[dict[str, Any]]:
    """Search Craigslist housing ads for matching properties.

    Args:
        address: The property street address.

    Returns:
        A list of listing dicts with the same shape as :func:`check_frbo_listings`.

    """
    logger.debug("Craigslist check called for: %s (stub)", address)
    return []


async def check_zillow(address: str) -> list[dict[str, Any]]:
    """Check Zillow for rental or for-sale listings at *address*.

    Args:
        address: The property street address.

    Returns:
        A list of listing dicts.

    """
    logger.debug("Zillow check called for: %s (stub)", address)
    return []
