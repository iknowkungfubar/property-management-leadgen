"""HubSpot client error types."""

from __future__ import annotations


class HubSpotError(Exception):
    """Generic HubSpot API error."""


class HubSpotAuthError(HubSpotError):
    """Authentication failure (401)."""


class HubSpotRateLimitError(HubSpotError):
    """Rate limit exceeded (429)."""


class HubSpotValidationError(HubSpotError):
    """Invalid request data (400)."""
