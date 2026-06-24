"""Do-Not-Call (DNC) compliance check.

This module provides a placeholder interface for checking phone numbers
against the National DNC Registry and state-level do-not-call lists.
A real implementation would integrate with a third-party scrubbing API.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Basic US phone number pattern (strips formatting)
PHONE_PATTERN: re.Pattern[str] = re.compile(r"^\+?1?\d{10}$")


def _normalise_phone(phone: str) -> str | None:
    """Strip non-digit characters and validate a 10-digit US phone number.

    Args:
        phone: Raw phone number string.

    Returns:
        Normalised 10-digit string, or ``None`` if invalid.

    """
    digits = re.sub(r"\D", "", phone)

    # Remove country code prefix if present
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    if len(digits) == 10:
        return digits
    logger.debug("Phone number '%s' is not a valid 10-digit US number.", phone)
    return None


def check_dnc(phone: str) -> bool:
    """Check whether a phone number is registered on the DNC list.

    Args:
        phone: The phone number to check (any common format).

    Returns:
        ``True`` if the number IS on the DNC registry (do not call).
        ``False`` if the number is clear or indeterminate.

    Notes:
        This is a **placeholder**.  Real DNC checking requires a paid
        subscription to the National DNC Registry or a compliance API.
        For development this always returns ``False`` (safe/default).

    """
    normalised = _normalise_phone(phone)
    if normalised is None:
        logger.warning("Skipping DNC check for invalid number: %s", phone)
        return False

    # TODO: integrate with a real DNC API.  For now, safe-default.
    logger.debug("DNC check for %s: not checked (placeholder — returning False).", normalised)
    return False
