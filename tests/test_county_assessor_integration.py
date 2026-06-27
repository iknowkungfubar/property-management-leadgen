"""Integration tests for county_assessor.py — mocked HTTP responses.

Uses ``unittest.mock.patch`` to intercept ``httpx.Client.get`` so no
real network calls are made during testing.  All scenarios that the
ArcGIS REST client can encounter are covered:

- Successful lookup (address → attributes, APN → attributes)
- Empty result set (no matching features)
- 404 / non-retryable HTTP error
- 503 with successful retry
- 503 with retry exhaustion
- Malformed JSON response
- HTTP timeout with retry exhaustion
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import httpx
import pytest

from src.scrapers.county_assessor import (
    MAX_RETRIES,
    get_assessed_value,
    lookup_apn_by_address,
    search_by_address,
    search_by_apn,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

SAMPLE_ATTRIBUTES_OC = {
    "APN": "123-456-789",
    "SITEADDR": "123 MAIN ST",
    "SITECITY": "SANTA ANA",
    "SITEZIP": "92701",
    "ASSESSEDVALUE": 500000,
    "PROPERTYTYPE": "RESIDENTIAL",
    "OWNERNAME": "JOHN DOE",
}

SAMPLE_ATTRIBUTES_LA = {
    "APN": "987-654-321",
    "SITE_ADDRESS": "456 OAK AVE",
    "SITE_CITY": "LOS ANGELES",
    "SITE_ZIP": "90012",
    "ASSESSED_VALUE": 750000,
    "PROPERTY_TYPE": "SFR",
}


def _mock_json_response(
    status: int = 200,
    attributes: dict | None = None,
    features: list[dict] | None = None,
) -> httpx.Response:
    """Build a mock ``httpx.Response`` with ``_request`` set.

    ``attributes`` is wrapped as a single-feature response unless
    ``features`` is provided explicitly.

    Args:
        status: HTTP status code.
        attributes: Feature attributes dict (wrapped into one feature).
        features: Explicit features list (takes precedence over attributes).

    Returns:
        A mock ``httpx.Response`` with JSON body and ``_request`` set.
    """
    if features is None:
        features = [{"attributes": attributes or {}}]
    body = {"features": features}
    resp = httpx.Response(status, json=body)
    # Set _request so raise_for_status() doesn't crash
    mock_request = Mock(spec=httpx.Request, url=httpx.URL("http://test"))
    object.__setattr__(resp, "_request", mock_request)
    return resp


# ------------------------------------------------------------------
# Fixture: patch httpx.Client.get for the entire test module
# ------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_http() -> None:
    """Ensure no real HTTP calls leak out of tests.

    This is a safety net — individual tests set up their own mocks
    via ``patch.object``.  If a test forgets to mock, the patched
    ``get`` will raise, failing fast rather than hitting a real server.
    """
    with patch.object(httpx.Client, "get") as mock_get:
        mock_get.side_effect = RuntimeError(
            "No HTTP mock configured for this test — use patch.object to "
            "set httpx.Client.get.return_value."
        )
        yield


# ------------------------------------------------------------------
# search_by_address
# ------------------------------------------------------------------


class TestSearchByAddress:
    """Tests for :func:`~src.scrapers.county_assessor.search_by_address`."""

    def test_success_returns_attributes(self) -> None:
        """Successful address lookup returns the full attributes dict."""
        mock_resp = _mock_json_response(200, attributes=SAMPLE_ATTRIBUTES_OC)
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = search_by_address("123 Main St", "Orange County")

        assert result is not None
        assert result["APN"] == "123-456-789"
        assert result["ASSESSEDVALUE"] == 500000
        assert result["SITECITY"] == "SANTA ANA"

    def test_no_results_returns_none(self) -> None:
        """Query with no matching features returns None."""
        mock_resp = _mock_json_response(200, attributes=None)
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = search_by_address("999 Nowhere Ln", "Orange County")

        assert result is None

    def test_http_404_returns_none(self) -> None:
        """Non-retryable HTTP 404 returns None immediately."""
        mock_resp = httpx.Response(404, text="Not found")
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = search_by_address("404 St", "Orange County")

        assert result is None

    def test_http_503_retry_then_success(self) -> None:
        """Retryable 503 is retried, and a subsequent success is returned."""
        success_resp = _mock_json_response(200, attributes=SAMPLE_ATTRIBUTES_OC)
        fail_resp = _mock_json_response(503, attributes=SAMPLE_ATTRIBUTES_OC)
        responses = iter([fail_resp, fail_resp, success_resp])

        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.side_effect = lambda *_args, **__kw: (
                next(responses)
            )
            result = search_by_address("123 Main St", "Orange County")

        assert result is not None
        assert result["APN"] == "123-456-789"

    def test_503_retry_exhaustion_returns_none(self) -> None:
        """All retry attempts exhausted on persistent 503 returns None."""
        fail_resp = _mock_json_response(503, attributes=SAMPLE_ATTRIBUTES_OC)
        n_attempts = 1 + MAX_RETRIES
        responses = iter([fail_resp] * n_attempts)

        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.side_effect = lambda *_args, **__kw: (
                next(responses)
            )
            result = search_by_address("123 Main St", "Orange County")

        assert result is None

    def test_timeout_retry_exhaustion_returns_none(self) -> None:
        """Timeout on every attempt returns None after retries."""
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.side_effect = httpx.TimeoutException(
                "Connection timed out", request=None
            )
            result = search_by_address("123 Main St", "Orange County")

        assert result is None

    def test_malformed_json_handled(self) -> None:
        """Response missing 'features' key is handled gracefully."""
        mock_resp = _mock_json_response(200, features=[{}])
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = search_by_address("123 Main St", "Orange County")

        assert result is None

    def test_empty_features_list_returns_none(self) -> None:
        """Response with empty features list returns None."""
        mock_resp = _mock_json_response(200, features=[])
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = search_by_address("123 Main St", "Orange County")

        assert result is None

    def test_feature_without_attributes_returns_none(self) -> None:
        """Feature entry without 'attributes' key returns None."""
        mock_resp = _mock_json_response(200, features=[{"foo": "bar"}])
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = search_by_address("123 Main St", "Orange County")

        assert result is None

    def test_los_angeles_county(self) -> None:
        """Query works for Los Angeles County as well."""
        mock_resp = _mock_json_response(200, attributes=SAMPLE_ATTRIBUTES_LA)
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = search_by_address("456 Oak Ave", "Los Angeles County")

        assert result is not None
        assert result["APN"] == "987-654-321"
        assert result["ASSESSED_VALUE"] == 750000

    def test_invalid_county_raises(self) -> None:
        """Unsupported county raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported county"):
            search_by_address("123 Main St", "San Diego County")

    def test_invalid_address_raises(self) -> None:
        """Empty address raises ValueError."""
        with pytest.raises(ValueError, match="Invalid address"):
            search_by_address("", "Orange County")


# ------------------------------------------------------------------
# search_by_apn
# ------------------------------------------------------------------


class TestSearchByApn:
    """Tests for :func:`~src.scrapers.county_assessor.search_by_apn`."""

    def test_success_returns_attributes(self) -> None:
        """Successful APN lookup returns the full attributes dict."""
        mock_resp = _mock_json_response(200, attributes=SAMPLE_ATTRIBUTES_OC)
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = search_by_apn("123-456-789", "Orange County")

        assert result is not None
        assert result["APN"] == "123-456-789"
        assert result["ASSESSEDVALUE"] == 500000

    def test_no_results_returns_none(self) -> None:
        """Unmatched APN returns None."""
        mock_resp = _mock_json_response(200, attributes=None)
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = search_by_apn("000-000-000", "Orange County")

        assert result is None

    def test_invalid_county_raises(self) -> None:
        """Unsupported county raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported county"):
            search_by_apn("123-456-789", "Riverside County")

    def test_invalid_apn_raises(self) -> None:
        """Invalid APN raises ValueError."""
        with pytest.raises(ValueError, match="Invalid APN"):
            search_by_apn("", "Orange County")


# ------------------------------------------------------------------
# Backward-compatible wrappers
# ------------------------------------------------------------------


class TestLookupApnByAddress:
    """Tests for :func:`~src.scrapers.county_assessor.lookup_apn_by_address`."""

    def test_returns_apn_string(self) -> None:
        """Wrapper extracts APN from full attributes."""
        mock_resp = _mock_json_response(200, attributes=SAMPLE_ATTRIBUTES_OC)
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            apn = lookup_apn_by_address("123 Main St", "Orange County")

        assert apn == "123-456-789"

    def test_no_match_returns_none(self) -> None:
        """Wrapper returns None when no match."""
        mock_resp = _mock_json_response(200, attributes=None)
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            apn = lookup_apn_by_address("999 Nowhere Ln", "Orange County")

        assert apn is None


class TestGetAssessedValue:
    """Tests for :func:`~src.scrapers.county_assessor.get_assessed_value`."""

    def test_returns_assessed_value(self) -> None:
        """Wrapper extracts assessed value from full attributes."""
        mock_resp = _mock_json_response(200, attributes=SAMPLE_ATTRIBUTES_OC)
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            value = get_assessed_value("123-456-789", "Orange County")

        assert value == 500000

    def test_la_county_field_name(self) -> None:
        """Wrapper uses the right field name for Los Angeles County."""
        mock_resp = _mock_json_response(200, attributes=SAMPLE_ATTRIBUTES_LA)
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            value = get_assessed_value("987-654-321", "Los Angeles County")

        assert value == 750000

    def test_no_match_returns_none(self) -> None:
        """Wrapper returns None when no APN match."""
        mock_resp = _mock_json_response(200, attributes=None)
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            value = get_assessed_value("000-000-000", "Orange County")

        assert value is None

    def test_missing_value_field_returns_none(self) -> None:
        """Wrapper handles missing assessed value field gracefully."""
        attributes = {**SAMPLE_ATTRIBUTES_OC}
        del attributes["ASSESSEDVALUE"]
        mock_resp = _mock_json_response(200, attributes=attributes)
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            value = get_assessed_value("123-456-789", "Orange County")

        assert value is None

    def test_non_numeric_value_field_returns_none(self) -> None:
        """Wrapper handles non-numeric assessed value gracefully."""
        attributes = {**SAMPLE_ATTRIBUTES_OC, "ASSESSEDVALUE": "NOT_A_NUMBER"}
        mock_resp = _mock_json_response(200, attributes=attributes)
        with patch.object(httpx, "Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            value = get_assessed_value("123-456-789", "Orange County")

        assert value is None
