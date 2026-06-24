"""Tests for the four core agents."""

from __future__ import annotations

import pytest

from src.agents.discovery import DiscoveryAgent
from src.agents.entity_unmasking import EntityUnmaskingAgent
from src.agents.market_intelligence import MarketIntelligenceAgent
from src.agents.output_synthesis import OutputSynthesisAgent

# ── Discovery Agent ─────────────────────────────────────────────────


class TestDiscoveryAgent:
    """Discovery agent — CSV parsing, APN normalisation, absentee detection."""

    @staticmethod
    def test_is_absentee_owner_different_address() -> None:
        """Mailing address different from property address → absentee."""
        assert DiscoveryAgent.is_absentee_owner(
            "123 Main St, Santa Ana, CA",
            "PO Box 4421, Newport Beach, CA",
        )

    @staticmethod
    def test_is_absentee_owner_same_address() -> None:
        """Same mailing and property address → not absentee."""
        assert not DiscoveryAgent.is_absentee_owner(
            "123 Main St, Santa Ana, CA",
            "123 Main St, Santa Ana, CA",
        )

    @staticmethod
    def test_is_absentee_owner_no_mailing() -> None:
        """Missing mailing address → not absentee."""
        assert not DiscoveryAgent.is_absentee_owner(
            "123 Main St, Santa Ana, CA",
            None,
        )

    @staticmethod
    def test_normalize_apn_orange_county() -> None:
        """OC APN format XXX-XXX-XX should be detected."""
        apn = DiscoveryAgent.normalize_apn(
            "APN 936-193-14, 123 Main St", "Orange County"
        )
        assert apn == "936-193-14"

    @staticmethod
    def test_normalize_apn_no_match() -> None:
        """No APN in address → None."""
        apn = DiscoveryAgent.normalize_apn(
            "123 Main St, Santa Ana, CA", "Orange County"
        )
        assert apn is None

    @staticmethod
    def test_parse_csv_invalid_path() -> None:
        """Non-existent CSV raises FileNotFoundError."""
        agent = DiscoveryAgent()
        with pytest.raises(FileNotFoundError):
            agent.parse_csv_import("/nonexistent/file.csv")


# ── Entity Unmasking Agent ──────────────────────────────────────────


class TestEntityUnmaskingAgent:
    """Entity classification and unmasking logic."""

    @staticmethod
    def test_is_entity_llc() -> None:
        assert EntityUnmaskingAgent.is_entity("Main St Holdings LLC")

    @staticmethod
    def test_is_entity_trust() -> None:
        assert EntityUnmaskingAgent.is_entity("Smith Family Trust")

    @staticmethod
    def test_is_not_entity_individual() -> None:
        assert not EntityUnmaskingAgent.is_entity("John A. Smith")

    @staticmethod
    def test_classify_entity_type_llc() -> None:
        assert EntityUnmaskingAgent.classify_entity_type("ABC Properties LLC") == "llc"

    @staticmethod
    def test_classify_entity_type_individual() -> None:
        assert (
            EntityUnmaskingAgent.classify_entity_type("Maria Garcia") == "individual"
        )

    @staticmethod
    def test_unmask_entity_individual() -> None:
        """Individual owner should pass through without SOS flag."""
        agent = EntityUnmaskingAgent()
        result = agent.unmask_entity("936-193-14", "Maria Garcia")
        assert result["is_entity"] is False
        assert result["needs_sos_lookup"] is False
        assert result["unmasked_principal_name"] == "Maria Garcia"

    @staticmethod
    def test_unmask_entity_llc() -> None:
        """LLC owner should be flagged for SOS lookup."""
        agent = EntityUnmaskingAgent()
        result = agent.unmask_entity("936-193-14", "Main St Holdings LLC")
        assert result["is_entity"] is True
        assert result["needs_sos_lookup"] is True
        assert result["unmasked_principal_name"] is None


# ── Market Intelligence Agent ───────────────────────────────────────


class TestMarketIntelligenceAgent:
    """Priority score calculation."""

    @staticmethod
    def test_calculate_priority_score_all_zero() -> None:
        """All-zero inputs yield zero."""
        score = MarketIntelligenceAgent.calculate_priority_score()
        assert score == 0.0

    @staticmethod
    def test_calculate_priority_score_high_vacancy() -> None:
        """High vacancy risk drives score up."""
        score = MarketIntelligenceAgent.calculate_priority_score(
            vacancy_risk=1.0, rental_yield_delta=0.0, competitor_sentiment=0.0
        )
        assert score == 0.4  # alpha=0.4 * 1.0

    @staticmethod
    def test_calculate_priority_score_competitor_reduces() -> None:
        """High competition sentiment reduces score."""
        score = MarketIntelligenceAgent.calculate_priority_score(
            vacancy_risk=0.5, rental_yield_delta=0.5, competitor_sentiment=1.0
        )
        expected = 0.4 * 0.5 + 0.4 * 0.5 - 0.2 * 1.0
        assert score == pytest.approx(expected)

    @staticmethod
    def test_score_properties_batch() -> None:
        """Batch scoring adds priority_score to each dict."""
        agent = MarketIntelligenceAgent()
        props = [
            {"vacancy_risk": 0.8, "rental_yield_delta": 0.2, "competitor_sentiment": 0.1},
            {"vacancy_risk": 0.0, "rental_yield_delta": 0.0, "competitor_sentiment": 0.0},
        ]
        result = agent.score_properties(props)
        assert len(result) == 2
        assert result[0]["priority_score"] > 0
        assert result[1]["priority_score"] == 0.0


# ── Output Synthesis Agent ──────────────────────────────────────────


class TestOutputSynthesisAgent:
    """Export formatting and deduplication."""

    @staticmethod
    def test_deduplicate_removes_duplicates() -> None:
        """Leads with the same APN should be deduplicated (last wins)."""
        leads = [
            {"apn": "936-193-14", "property_address": "Old Address"},
            {"apn": "430-121-07", "property_address": "Other"},
            {"apn": "936-193-14", "property_address": "New Address"},
        ]
        agent = OutputSynthesisAgent()
        result = agent.deduplicate(leads)
        assert len(result) == 2
        assert result[0]["property_address"] == "New Address"

    @staticmethod
    def test_format_csv_includes_header() -> None:
        """CSV export should include a header row."""
        leads = [
            {"apn": "936-193-14", "property_address": "123 Main St", "priority_score": 0.5},
        ]
        agent = OutputSynthesisAgent()
        csv_out = agent.format_lead_export(leads, export_format="csv")
        assert csv_out.startswith("apn,")
        assert "936-193-14" in csv_out

    @staticmethod
    def test_format_json_valid() -> None:
        """JSON export should produce parseable output."""
        leads = [
            {"apn": "936-193-14", "property_address": "123 Main St", "priority_score": 0.5},
        ]
        agent = OutputSynthesisAgent()
        json_out = agent.format_lead_export(leads, export_format="json")
        import json

        parsed = json.loads(json_out)
        assert len(parsed) == 1
        assert parsed[0]["apn"] == "936-193-14"

    @staticmethod
    def test_format_unsupported_format() -> None:
        """Unsupported format raises ValueError."""
        agent = OutputSynthesisAgent()
        with pytest.raises(ValueError):
            agent.format_lead_export([], export_format="xml")
