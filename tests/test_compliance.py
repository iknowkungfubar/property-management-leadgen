"""Tests for the DNC compliance module."""

from __future__ import annotations

from src.compliance.dnc_checker import _normalise_phone, check_dnc

# ── Phone normalisation tests ────────────────────────────────────────


class TestNormalisePhone:
    """Tests for _normalise_phone."""

    @staticmethod
    def test_strips_us_country_code() -> None:
        """+1 prefix should be stripped, leaving 10 digits."""
        assert _normalise_phone("+19495551234") == "9495551234"

    @staticmethod
    def test_strips_formatting_from_us_number() -> None:
        """+1 (949) 555-1234 should normalise to 9495551234."""
        assert _normalise_phone("+1 (949) 555-1234") == "9495551234"

    @staticmethod
    def test_strips_dashes() -> None:
        """949-555-1234 should normalise to 9495551234."""
        assert _normalise_phone("949-555-1234") == "9495551234"

    @staticmethod
    def test_strips_dots() -> None:
        """949.555.1234 should normalise to 9495551234."""
        assert _normalise_phone("949.555.1234") == "9495551234"

    @staticmethod
    def test_strips_spaces() -> None:
        """949 555 1234 should normalise to 9495551234."""
        assert _normalise_phone("949 555 1234") == "9495551234"

    @staticmethod
    def test_handles_international_format_without_plus() -> None:
        """1 949 555 1234 (US country code without +) should work."""
        assert _normalise_phone("1 949 555 1234") == "9495551234"

    @staticmethod
    def test_returns_none_for_short_number() -> None:
        """A number with fewer than 10 digits returns None."""
        assert _normalise_phone("555-1234") is None

    @staticmethod
    def test_returns_none_for_empty_string() -> None:
        """An empty string returns None."""
        assert _normalise_phone("") is None

    @staticmethod
    def test_returns_none_for_nonsense() -> None:
        """Non-numeric input returns None."""
        assert _normalise_phone("not-a-phone") is None

    @staticmethod
    def test_preserves_11_digit_us_caller() -> None:
        """18005551234 (11 digits starting with 1) should strip the leading 1."""
        assert _normalise_phone("18005551234") == "8005551234"

    @staticmethod
    def test_handles_mixed_formatting() -> None:
        """Mixed formatting with parens and spaces is normalised."""
        assert _normalise_phone(" (949) 555-1234 ") == "9495551234"


# ── DNC check tests ──────────────────────────────────────────────────


class TestCheckDnc:
    """Tests for check_dnc stub implementation."""

    @staticmethod
    def test_returns_false_for_unknown_number() -> None:
        """check_dnc returns False for a normal US number (safe default)."""
        result = check_dnc("+1 (949) 555-1234")
        assert result is False

    @staticmethod
    def test_returns_correct_type() -> None:
        """check_dnc should return a boolean."""
        result = check_dnc("+1 (949) 555-1234")
        assert isinstance(result, bool)

    @staticmethod
    def test_returns_false_for_invalid_number() -> None:
        """check_dnc returns False (not an exception) for invalid numbers."""
        result = check_dnc("555-1234")
        assert result is False

    @staticmethod
    def test_returns_false_for_empty_string() -> None:
        """check_dnc returns False for empty input."""
        result = check_dnc("")
        assert result is False

    @staticmethod
    def test_returns_false_for_nonsense() -> None:
        """check_dnc gracefully handles complete nonsense."""
        result = check_dnc("abc-def-ghij")
        assert result is False

    @staticmethod
    def test_normalised_number_happy_path() -> None:
        """check_dnc works with already-normalised 10-digit numbers."""
        result = check_dnc("9495551234")
        assert isinstance(result, bool)
