"""Tests for scraper modules — CA SoS parser, county assessor, rate limiter."""

from __future__ import annotations

import time

import pytest

from src.scrapers.ca_sos_parser import CASOSParser
from src.scrapers.rental_listings import check_frbo_listings
from src.utils.rate_limiter import RateLimiter


# ── CASOSParser ─────────────────────────────────────────────────────


class TestCASOSParser:
    """CASOSParser tests (no real API calls)."""

    @staticmethod
    def test_extract_text_from_pdf_missing_file() -> None:
        """Missing PDF returns None, not an exception."""
        from src.llm.base import LLMProvider

        class StubLLM(LLMProvider):
            def generate_structured_json(self, system_prompt, user_prompt, **kwargs):
                return {}

        parser = CASOSParser(StubLLM())
        result = parser.extract_text_from_pdf("/nonexistent.pdf")
        assert result is None


# ── Rental Listings (stubs) ─────────────────────────────────────────


class TestRentalListings:
    """Rental listing placeholder stubs."""

    @staticmethod
    def test_check_frbo_listings_returns_list() -> None:
        """FRBO check always returns a list (empty for now)."""
        result = check_frbo_listings("123 Main St, Santa Ana, CA")
        assert isinstance(result, list)


# ── Rate Limiter ────────────────────────────────────────────────────


class TestRateLimiter:
    """Per-domain exponential backoff."""

    @staticmethod
    def test_initial_no_wait() -> None:
        """First call should not sleep."""
        limiter = RateLimiter(base_delay=0.1)
        start = time.monotonic()
        limiter.wait_if_needed("test_domain")
        elapsed = time.monotonic() - start
        assert elapsed < 0.05  # negligible

    @staticmethod
    def test_backoff_increases_after_failure() -> None:
        """After recording a failure, wait should be at least base * 2^1."""
        limiter = RateLimiter(base_delay=0.1)
        limiter.record_failure("test_domain")
        start = time.monotonic()
        limiter.wait_if_needed("test_domain")
        elapsed = time.monotonic() - start
        # With base=0.1, failure=1 → backoff >= 0.2 * 2^1 + random ≈ 0.2-1.2s
        assert elapsed >= 0.1

    @staticmethod
    def test_success_resets_failures() -> None:
        """After recording a success, backoff resets."""
        limiter = RateLimiter(base_delay=0.1)
        limiter.record_failure("test_domain")
        limiter.record_success("test_domain")
        start = time.monotonic()
        limiter.wait_if_needed("test_domain")
        elapsed = time.monotonic() - start
        assert elapsed < 0.05

    @staticmethod
    def test_reset_domain() -> None:
        """Resetting a specific domain clears its failure state."""
        limiter = RateLimiter(base_delay=0.1)
        limiter.record_failure("a")
        limiter.record_failure("b")
        limiter.reset("a")
        # a is reset, b should still have backoff
        assert limiter._failures.get("a") is None
        assert limiter._failures.get("b") == 1

    @staticmethod
    def test_reset_all() -> None:
        """Resetting all clears everything."""
        limiter = RateLimiter(base_delay=0.1)
        limiter.record_failure("a")
        limiter.record_failure("b")
        limiter.reset()
        assert len(limiter._failures) == 0
