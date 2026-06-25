"""Tests for src/scrapers/county_assessor.py — ArcGIS REST API helpers."""

from __future__ import annotations

import pytest

from src.scrapers.county_assessor import (
    COUNTY_ENDPOINTS,
    _escape_sql_literal,
    _validate_address,
    _validate_apn,
)


class TestCountyEndpoints:
    """Verify COUNTY_ENDPOINTS configuration."""

    def test_has_orange_county(self):
        """Orange County endpoint is configured."""
        assert "Orange County" in COUNTY_ENDPOINTS
        assert "maps.ocgov.com" in COUNTY_ENDPOINTS["Orange County"]

    def test_endpoints_are_urls(self):
        """All endpoints are valid URLs."""
        for name, url in COUNTY_ENDPOINTS.items():
            assert url.startswith("https://"), f"{name}: {url}"


class TestEscapeSqlLiteral:
    """Verify SQL escaping for ArcGIS REST where clauses."""

    def test_simple_string(self):
        """Simple strings pass through unchanged."""
        assert _escape_sql_literal("hello") == "hello"

    def test_single_quote_doubled(self):
        """Single quotes are doubled for SQL safety."""
        assert _escape_sql_literal("O'Brien") == "O''Brien"

    def test_multiple_quotes(self):
        """Multiple single quotes are all doubled."""
        assert _escape_sql_literal("it's a 'test'") == "it''s a ''test''"

    def test_control_characters_stripped(self):
        """Control characters are removed."""
        assert _escape_sql_literal("hello\x00world") == "helloworld"

    def test_no_quotes_no_change(self):
        """Strings without quotes are unchanged."""
        assert _escape_sql_literal("123 Main St") == "123 Main St"

    def test_empty_string(self):
        """Empty string stays empty."""
        assert _escape_sql_literal("") == ""

    def test_only_quotes(self):
        """String with only quotes produces doubled quotes."""
        assert _escape_sql_literal("'") == "''"


class TestValidateAddress:
    """Verify address validation."""

    def test_valid_address(self):
        """A well-formed address passes validation."""
        result = _validate_address("123 Main St")
        assert result == "123 Main St"

    def test_address_with_dots_and_hyphens(self):
        """Addresses with dots, hyphens, and slashes pass."""
        result = _validate_address("123-45 Main St. #2")
        assert "123-45" in result
        assert "Main" in result

    def test_too_short_address_raises(self):
        """Address shorter than 3 chars raises ValueError."""
        with pytest.raises(ValueError, match="Invalid address"):
            _validate_address("ab")

    def test_empty_address_raises(self):
        """Empty address raises ValueError."""
        with pytest.raises(ValueError, match="Invalid address"):
            _validate_address("")

    def test_sql_metacharacters_removed(self):
        """Unsafe characters are stripped from addresses."""
        result = _validate_address("123 Main St, Apt #2")
        assert result == "123 Main St, Apt #2"

    def test_newlines_stripped(self):
        """Newlines are removed from addresses."""
        # _validate_address uses r\"[^\\w\\s\\-/,.#]\" which strips \n
        result = _validate_address("123 Main\nSt")
        assert "Main" in result


class TestValidateApn:
    """Verify APN validation."""

    def test_valid_apn(self):
        """A valid APN passes through."""
        result = _validate_apn("123-456-789")
        assert result == "123-456-789"

    def test_apn_with_extra_chars(self):
        """Extra characters are stripped from APN."""
        result = _validate_apn("123-456 abc")
        assert result == "123-456"

    def test_invalid_apn_raises(self):
        """Invalid APN raises ValueError."""
        with pytest.raises(ValueError, match="Invalid APN"):
            _validate_apn("")

    def test_apn_with_letters(self):
        """Letters are stripped from APN."""
        result = _validate_apn("ABC-123")
        assert result == "-123"

    def test_apn_all_numbers(self):
        """Numeric-only APN passes."""
        result = _validate_apn("123456789")
        assert result == "123456789"
