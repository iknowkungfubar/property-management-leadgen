"""Tests for the DNC compliance module."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.compliance.dnc_checker import (
    DNCConfig,
    add_dnc_number,
    check_dnc,
    normalise_phone,
    remove_dnc_number,
)


class TestNormalisePhone:
    """Tests for normalise_phone."""

    def test_strips_us_country_code(self) -> None:
        """+1 prefix stripped, leaving 10 digits."""
        assert normalise_phone("+1919-719-1234") == "9197191234"

    def test_strips_formatting(self) -> None:
        """+1 (949) 555-1234 normalises to 9495551234."""
        assert normalise_phone("+1 (949) 555-1234") == "9495551234"

    def test_strips_dashes(self) -> None:
        """949-555-1234 normalises to 9495551234."""
        assert normalise_phone("949-555-1234") == "9495551234"

    def test_strips_dots(self) -> None:
        """949.555.1234 normalises to 9495551234."""
        assert normalise_phone("949.555.1234") == "9495551234"

    def test_strips_spaces(self) -> None:
        """949 555 1234 normalises to 9495551234."""
        assert normalise_phone("949 555 1234") == "9495551234"

    def test_handles_11_digit_us(self) -> None:
        """1 949 555 1234 (11 digits) strips the leading 1."""
        assert normalise_phone("1 949 555 1234") == "9495551234"

    def test_returns_none_for_short(self) -> None:
        """Fewer than 10 digits returns None."""
        assert normalise_phone("555-1234") is None

    def test_returns_none_for_empty(self) -> None:
        """Empty string returns None."""
        assert normalise_phone("") is None

    def test_returns_none_for_nonsense(self) -> None:
        """Non-numeric input returns None."""
        assert normalise_phone("not-a-phone") is None

    def test_preserves_800_number(self) -> None:
        """18005551234 (11 digits starting with 1) strips leading 1."""
        assert normalise_phone("18005551234") == "8005551234"

    def test_handles_mixed_formatting(self) -> None:
        """(949) 555-1234 normalises to 9495551234."""
        assert normalise_phone(" (949) 555-1234 ") == "9495551234"


class TestCheckDnc:
    """Tests for check_dnc."""

    def test_unknown_no_db(self) -> None:
        """Without DB, unknown numbers are clear."""
        assert check_dnc("+1 (949) 555-1234") is False

    def test_returns_bool(self) -> None:
        """check_dnc returns a boolean always."""
        assert isinstance(check_dnc("+1 (949) 555-1234"), bool)

    def test_invalid_number_safe(self) -> None:
        """Invalid numbers return False."""
        assert check_dnc("555-1234") is False

    def test_empty_safe(self) -> None:
        """Empty input returns False."""
        assert check_dnc("") is False

    def test_area_code_blocked(self) -> None:
        """Blocked area code returns True."""
        config = DNCConfig(area_codes=["212"])
        assert check_dnc("+1 (212) 555-1234", config=config) is True

    def test_area_code_allowed(self) -> None:
        """Non-blocked area code returns False."""
        config = DNCConfig(area_codes=["212"])
        assert check_dnc("+1 (949) 555-1234", config=config) is False

    def test_international_blocked(self) -> None:
        """International numbers blocked by default."""
        assert check_dnc("+4420-7946-0958") is True

    def test_international_allowed_when_disabled(self) -> None:
        """International blocking can be disabled."""
        config = DNCConfig(block_international=False)
        assert check_dnc("+4420-7946-0958", config=config) is False

    def test_disabled_allows_all(self) -> None:
        """When DNC is disabled, all numbers pass."""
        config = DNCConfig(enabled=False)
        assert check_dnc("+1 (212) 555-1234", config=config) is False

    def test_db_blocklist_hit(self) -> None:
        """Numbers in dnc_list are blocked."""
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = (1,)
        assert check_dnc("9495551234", db_conn=mock_db) is True

    def test_db_blocklist_miss(self) -> None:
        """Numbers not in dnc_list are clear."""
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = None
        assert check_dnc("9495551234", db_conn=mock_db) is False


class TestAddDncNumber:
    """Tests for add_dnc_number."""

    def test_adds_valid(self) -> None:
        """A valid number is added."""
        mock_db = MagicMock()
        assert add_dnc_number(mock_db, "+1 (949) 555-1234") is True

    def test_rejects_invalid(self) -> None:
        """Invalid numbers are rejected."""
        mock_db = MagicMock()
        assert add_dnc_number(mock_db, "555-1234") is False

    def test_passes_source(self) -> None:
        """Source is passed through to the DB."""
        mock_db = MagicMock()
        add_dnc_number(mock_db, "9495551234", source="api")
        args = mock_db.execute.call_args[0]
        assert args[1][1] == "api"


class TestRemoveDncNumber:
    """Tests for remove_dnc_number."""

    def test_removes_existing(self) -> None:
        """Existing number is removed."""
        mock_db = MagicMock()
        mock_db.execute.return_value.rowcount = 1
        assert remove_dnc_number(mock_db, "9495551234") is True

    def test_rejects_invalid(self) -> None:
        """Invalid input is rejected."""
        mock_db = MagicMock()
        assert remove_dnc_number(mock_db, "") is False
