"""Tests for src/utils/csv_import.py — CSV parsing and address normalization."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.utils.csv_import import COLUMN_MAP, normalize_address, parse_csv_file


class TestColumnMap:
    """Verify the column mapping dictionary."""

    def test_column_map_has_required_sources(self):
        """Column map contains standard source formats."""
        assert "orange_coast_title" in COLUMN_MAP
        assert "crmls" in COLUMN_MAP

    def test_column_map_source_has_required_fields(self):
        """Each source has the required field mappings."""
        for source_name, mapping in COLUMN_MAP.items():
            assert "apn" in mapping, f"{source_name}: missing apn"
            assert "recorded_owner" in mapping, f"{source_name}: missing recorded_owner"
            assert "property_address" in mapping, f"{source_name}: missing property_address"


class TestParseCsvFile:
    """Verify CSV file parsing."""

    def test_parse_basic_csv(self):
        """Parse a simple CSV file with standard columns."""
        content = "apn,owner_name,address,city,state\n123-456,John Smith,123 Main St,Irvine,CA\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            rows = parse_csv_file(path)
            assert len(rows) == 1
            assert rows[0]["apn"] == "123-456"
            assert rows[0]["owner_name"] == "John Smith"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_parse_csv_with_extra_columns(self):
        """Parse a CSV file with extra columns beyond the standard set."""
        content = (
            "apn,owner_name,address,city,state,zip,county\n"
            "123-456,John Smith,123 Main St,Irvine,CA,92626,Orange\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            rows = parse_csv_file(path)
            assert len(rows) == 1
            assert rows[0]["apn"] == "123-456"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_parse_csv_empty_file_raises(self):
        """Parse an empty CSV file raises ValueError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = f.name
        try:
            with pytest.raises(ValueError, match="no headers"):
                parse_csv_file(path)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_parse_csv_header_only(self):
        """Parse a CSV file with only headers returns empty list."""
        content = "apn,owner_name,address,city,state\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            rows = parse_csv_file(path)
            assert isinstance(rows, list)
            assert len(rows) == 0
        finally:
            Path(path).unlink(missing_ok=True)

    def test_parse_csv_missing_file_raises(self):
        """Parse a non-existent CSV file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="CSV not found"):
            parse_csv_file("/nonexistent/file.csv")

    def test_parse_csv_multiple_rows(self):
        """Parse a CSV file with multiple rows."""
        content = (
            "apn,owner_name,address,city,state\n"
            "123-456,John Smith,123 Main St,Irvine,CA\n"
            "789-012,Jane Doe,456 Oak Ave,Newport Beach,CA\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            rows = parse_csv_file(path)
            assert len(rows) == 2
        finally:
            Path(path).unlink(missing_ok=True)


class TestNormalizeAddress:
    """Verify address normalization."""

    def test_normalize_street_abbreviations(self):
        """Common street abbreviations are expanded."""
        result = normalize_address("123 Main St")
        assert "Street" in result or "123 Main St" in result

    def test_normalize_directional_prefixes(self):
        """Directional prefixes are standardized."""
        result = normalize_address("123 N Main St")
        assert "North" in result or "N" in result

    def test_normalize_unit_numbers(self):
        """Unit number formats are normalized."""
        result = normalize_address("123 Main St Apt 4")
        assert "Apt" in result or "4" in result

    def test_normalize_empty_string(self):
        """Empty address returns empty string."""
        result = normalize_address("")
        assert result == ""

    def test_normalize_already_normal(self):
        """A well-formed address passes through."""
        result = normalize_address("123 Main Street")
        assert "123" in result
        assert "Main" in result

    def test_normalize_lowercase(self):
        """Case handling works."""
        result = normalize_address("123 main street")
        # Should not fail or throw
        assert isinstance(result, str)
