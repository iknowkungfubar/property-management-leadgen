"""Tests for the HubSpot CRM API client."""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import httpx
import pytest

from src.utils.hubspot_client import (
    HubSpotAuthError,
    HubSpotClient,
    HubSpotError,
    HubSpotRateLimitError,
    HubSpotValidationError,
    _mask_sensitive,
    map_lead_to_hubspot_properties,
)

# ── Field mapping ──────────────────────────────────────────────────────────


class TestMapLeadToHubSpotProperties:
    """Mapping internal lead dicts to HubSpot property names."""

    @staticmethod
    def test_known_fields_mapped() -> None:
        lead = {
            "property_address": "123 Main St",
            "recorded_owner": "ABC LLC",
            "unmasked_principal_phone": "949-555-1234",
            "priority_score": 0.85,
            "apn": "936-193-14",
        }
        props = map_lead_to_hubspot_properties(lead)
        assert props["address"] == "123 Main St"
        assert props["hs_legal_entity_name"] == "ABC LLC"
        assert props["phone"] == "949-555-1234"
        assert props["hs_lead_score"] == "0.85"
        assert props["hs_lead_id"] == "936-193-14"

    @staticmethod
    def test_unknown_fields_dropped() -> None:
        lead = {"unknown_field": "should be dropped", "property_address": "456 Oak Ave"}
        props = map_lead_to_hubspot_properties(lead)
        assert "unknown_field" not in props
        assert props["address"] == "456 Oak Ave"

    @staticmethod
    def test_empty_values_skipped() -> None:
        lead = {"property_address": "", "priority_score": None}
        props = map_lead_to_hubspot_properties(lead)
        assert "address" not in props
        assert "hs_lead_score" not in props


# ── Sensitive-data masking ────────────────────────────────────────────────


class TestMaskSensitive:
    """Log-safe masking of sensitive fields."""

    @staticmethod
    def test_email_masked() -> None:
        result = _mask_sensitive({"email": "john.doe@example.com"})
        assert result["email"].startswith("jo")
        assert result["email"].endswith(".com")
        assert "****" in result["email"]

    @staticmethod
    def test_api_key_masked() -> None:
        result = _mask_sensitive({"apiKey": "pat-1234567890abcdef"})
        assert result["apiKey"] == "pa****"

    @staticmethod
    def test_non_sensitive_unmasked() -> None:
        result = _mask_sensitive({"firstname": "John", "phone": "949-555-1234"})
        assert result["firstname"] == "John"
        assert result["phone"] == "949-555-1234"

    @staticmethod
    def test_short_string_not_masked() -> None:
        result = _mask_sensitive({"apiKey": "ab"})
        assert result["apiKey"] == "ab"


# ── HubSpotClient (mocked HTTP) ───────────────────────────────────────────


@pytest.fixture
def client() -> HubSpotClient:
    """Return a HubSpotClient with a test token."""
    return HubSpotClient(api_key="test-pat-token")


class TestHubSpotClientInit:
    """Client construction and configuration."""

    @staticmethod
    def test_headers_set(client: HubSpotClient) -> None:
        """Authorization and content-type headers should be set."""
        assert client._client.headers["Authorization"] == "Bearer test-pat-token"
        assert client._client.headers["Content-Type"] == "application/json"


class TestHubSpotClientUpsertContact:
    """Single contact upsert via batch endpoint."""

    @staticmethod
    @patch("src.utils.hubspot_client.httpx.Client")
    def test_upsert_contact_success(mock_httpx: Mock) -> None:
        mock_response = Mock(spec=httpx.Response)
        mock_response.is_error = False
        mock_response.json.return_value = {
            "results": [{"id": "12345"}],
        }
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        hs = HubSpotClient(api_key="test-token")
        contact_id = hs.upsert_contact(
            email="john@example.com",
            properties={"firstname": "John"},
        )

        assert contact_id == "12345"
        mock_client_instance.post.assert_called_once()
        # Verify payload shape
        call_args = mock_client_instance.post.call_args
        payload = json.loads(call_args[1]["content"])
        assert payload["inputs"][0]["id"] == "john@example.com"
        assert payload["inputs"][0]["idProperty"] == "email"
        assert payload["inputs"][0]["properties"]["firstname"] == "John"

    @staticmethod
    @patch("src.utils.hubspot_client.httpx.Client")
    def test_upsert_contact_email_in_properties(mock_httpx: Mock) -> None:
        """If email is in properties, it shouldn't be duplicated."""
        mock_response = Mock(spec=httpx.Response)
        mock_response.is_error = False
        mock_response.json.return_value = {
            "results": [{"id": "67890"}],
        }
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        hs = HubSpotClient(api_key="test-token")
        contact_id = hs.upsert_contact(
            email="existing@example.com",
            properties={"email": "existing@example.com", "firstname": "Jane"},
        )
        assert contact_id == "67890"

    @staticmethod
    @patch("src.utils.hubspot_client.httpx.Client")
    def test_upsert_contact_http_error(mock_httpx: Mock) -> None:
        """HTTP errors should raise typed HubSpotError."""
        mock_response = Mock(spec=httpx.Response)
        mock_response.is_error = True
        mock_response.status_code = 401
        mock_response.text = '{"message": "Invalid access token"}'
        mock_response.json.return_value = {"message": "Invalid access token"}
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        hs = HubSpotClient(api_key="bad-token")
        with pytest.raises(HubSpotAuthError, match="Invalid access token"):
            hs.upsert_contact(email="john@example.com", properties={})

    @staticmethod
    @patch("src.utils.hubspot_client.httpx.Client")
    def test_upsert_contact_request_error(mock_httpx: Mock) -> None:
        """Network errors should raise HubSpotError."""
        mock_client_instance = Mock()
        mock_client_instance.post.side_effect = httpx.RequestError("Connection refused")
        mock_httpx.return_value = mock_client_instance

        hs = HubSpotClient(api_key="test-token")
        with pytest.raises(HubSpotError, match="Request failed"):
            hs.upsert_contact(email="john@example.com", properties={})


class TestHubSpotClientBatchUpsert:
    """Batch upsert of multiple contacts."""

    @staticmethod
    @patch("src.utils.hubspot_client.httpx.Client")
    def test_batch_upsert_success(mock_httpx: Mock) -> None:
        mock_response = Mock(spec=httpx.Response)
        mock_response.is_error = False
        mock_response.json.return_value = {
            "results": [{"id": "111"}, {"id": "222"}],
            "errors": [],
        }
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        hs = HubSpotClient(api_key="test-token")
        contacts = [
            {"email": "a@example.com", "firstname": "Alice"},
            {"email": "b@example.com", "firstname": "Bob"},
        ]
        result = hs.batch_upsert(contacts)
        assert result["total"] == 2
        assert result["succeeded"] == ["111", "222"]
        assert result["failed"] == []

    @staticmethod
    @patch("src.utils.hubspot_client.httpx.Client")
    def test_batch_upsert_empty(mock_httpx: Mock) -> None:
        """Empty input should skip the API call."""
        mock_client_instance = Mock()
        mock_httpx.return_value = mock_client_instance

        hs = HubSpotClient(api_key="test-token")
        result = hs.batch_upsert([])
        assert result["total"] == 0
        mock_client_instance.post.assert_not_called()

    @staticmethod
    @patch("src.utils.hubspot_client.httpx.Client")
    def test_batch_upsert_skips_missing_email(mock_httpx: Mock) -> None:
        """Contacts without email should be skipped."""
        mock_response = Mock(spec=httpx.Response)
        mock_response.is_error = False
        mock_response.json.return_value = {"results": [{"id": "333"}], "errors": []}
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        hs = HubSpotClient(api_key="test-token")
        contacts = [
            {"firstname": "No Email"},
            {"email": "c@example.com", "firstname": "Charlie"},
        ]
        result = hs.batch_upsert(contacts)
        assert result["total"] == 1
        assert result["succeeded"] == ["333"]

    @staticmethod
    @patch("src.utils.hubspot_client.httpx.Client")
    def test_batch_upsert_rate_limit(mock_httpx: Mock) -> None:
        """429 should raise HubSpotRateLimitError."""
        mock_response = Mock(spec=httpx.Response)
        mock_response.is_error = True
        mock_response.status_code = 429
        mock_response.text = '{"message": "Rate limit exceeded"}'
        mock_response.json.return_value = {"message": "Rate limit exceeded"}
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        hs = HubSpotClient(api_key="test-token")
        with pytest.raises(HubSpotRateLimitError, match="Rate limit exceeded"):
            hs.batch_upsert([{"email": "a@example.com", "firstname": "A"}])

    @staticmethod
    @patch("src.utils.hubspot_client.httpx.Client")
    def test_batch_upsert_validation_error(mock_httpx: Mock) -> None:
        """400 should raise HubSpotValidationError."""
        mock_response = Mock(spec=httpx.Response)
        mock_response.is_error = True
        mock_response.status_code = 400
        mock_response.text = '{"message": "Property does not exist"}'
        mock_response.json.return_value = {"message": "Property does not exist"}
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        hs = HubSpotClient(api_key="test-token")
        with pytest.raises(HubSpotValidationError, match="Property does not exist"):
            hs.batch_upsert([{"email": "a@example.com", "invalid_prop": "x"}])


class TestHubSpotClientRateLimiting:
    """Client-side sliding window rate limiter."""

    @staticmethod
    @patch("src.utils.hubspot_client.time")
    def test_wait_if_needed_no_wait(mock_time: Mock) -> None:
        """With an empty window, no sleep should occur."""
        hs = HubSpotClient(api_key="test-token")
        mock_time.monotonic.return_value = 100.0

        hs._wait_if_needed()
        mock_time.sleep.assert_not_called()

    @staticmethod
    @patch("src.utils.hubspot_client.time")
    def test_wait_if_needed_waits(mock_time: Mock) -> None:
        """With a full window, should sleep until oldest drops out."""
        hs = HubSpotClient(api_key="test-token")
        mock_time.monotonic.return_value = 0.0

        # Fill the window with 100 timestamps
        for i in range(100):
            hs._request_timestamps.append(0.0 + i * 0.05)  # 50ms apart

        # Now advance time so earliest request is 9.5s ago (still within 10s)
        mock_time.monotonic.return_value = 9.5
        hs._wait_if_needed()
        # We have 100 timestamps from 0.0 to 4.95, now at 9.5
        # oldest is 0.0, so need to wait: 0.0 + 10.0 - 9.5 = 0.5s
        mock_time.sleep.assert_called_once()
        assert abs(mock_time.sleep.call_args[0][0] - 0.5) < 0.01


class TestHubSpotClientErrorParsing:
    """Error response parsing."""

    @staticmethod
    def test_parse_auth_error() -> None:
        """401 maps to HubSpotAuthError."""
        response = Mock(spec=httpx.Response)
        response.status_code = 401
        response.text = '{"message": "Invalid token"}'
        response.json.return_value = {"message": "Invalid token"}

        exc = HubSpotClient._parse_error(response)
        assert isinstance(exc, HubSpotAuthError)
        assert "Invalid token" in str(exc)

    @staticmethod
    def test_parse_rate_limit_error() -> None:
        """429 maps to HubSpotRateLimitError."""
        response = Mock(spec=httpx.Response)
        response.status_code = 429
        response.text = '{"message": "Rate limit hit"}'
        response.json.return_value = {"message": "Rate limit hit"}

        exc = HubSpotClient._parse_error(response)
        assert isinstance(exc, HubSpotRateLimitError)

    @staticmethod
    def test_parse_validation_error() -> None:
        """400 maps to HubSpotValidationError."""
        response = Mock(spec=httpx.Response)
        response.status_code = 400
        response.text = '{"message": "Bad request"}'
        response.json.return_value = {"message": "Bad request"}

        exc = HubSpotClient._parse_error(response)
        assert isinstance(exc, HubSpotValidationError)

    @staticmethod
    def test_parse_server_error() -> None:
        """500 maps to generic HubSpotError."""
        response = Mock(spec=httpx.Response)
        response.status_code = 500
        response.text = "Internal Server Error"
        response.json.side_effect = json.JSONDecodeError("Not JSON", "", 0)

        exc = HubSpotClient._parse_error(response)
        assert isinstance(exc, HubSpotError)
        assert "Internal Server Error" in str(exc)


class TestHubSpotClientClose:
    """Resource cleanup."""

    @staticmethod
    @patch("src.utils.hubspot_client.httpx.Client")
    def test_close_called(mock_httpx: Mock) -> None:
        mock_client_instance = Mock()
        mock_httpx.return_value = mock_client_instance

        hs = HubSpotClient(api_key="test-token")
        hs.close()
        mock_client_instance.close.assert_called_once()
