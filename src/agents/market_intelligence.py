"""Market Intelligence Agent — vacancy detection, priority scoring, and listing checks."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class MarketIntelligenceAgent:
    """Assess property-level market signals and compute lead priority scores.

    The L_score formula combines vacancy risk, rental yield delta, and
    competitor sentiment to rank leads:

        L_score = α · R_vac + β · (M_target - M_current) - γ · S_comp
    """

    def __init__(self, db_conn: Any = None) -> None:
        """Store database reference.

        Args:
            db_conn: SQLite connection (or mock for testing).
                ``None`` is permitted — the agent's static analysis
                methods work without a connection.

        """
        self._db = db_conn

    # ------------------------------------------------------------------
    # Priority score
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_priority_score(
        vacancy_risk: float = 0.0,
        rental_yield_delta: float = 0.0,
        competitor_sentiment: float = 0.0,
        alpha: float = 0.4,
        beta: float = 0.4,
        gamma: float = 0.2,
    ) -> float:
        """Compute the L_score lead priority metric.

        Args:
            vacancy_risk: Probability-like score (0-1) indicating vacancy.
            rental_yield_delta: Difference between target and current yield
                (positive means upside).
            competitor_sentiment: Normalised competition intensity (0-1).
            alpha: Weight for vacancy risk.
            beta: Weight for rental yield delta.
            gamma: Weight for competitor sentiment.

        Returns:
            A float score; higher values indicate higher-priority leads.

        """
        score = (
            alpha * vacancy_risk
            + beta * rental_yield_delta
            - gamma * competitor_sentiment
        )
        return round(score, 4)

    # ------------------------------------------------------------------
    # Listing checks (placeholders for real scrapers)
    # ------------------------------------------------------------------

    def check_listing_status(self, property_address: str) -> dict[str, Any]:
        """Check whether a property is listed on rental or sale platforms.

        This is a placeholder that returns an empty result.  Real
        implementations will search FRBO, Craigslist, and MLS data.

        Args:
            property_address: The street address to check.

        Returns:
            A dictionary with keys::

                - address (str)
                - listing_status (str | None)
                - days_on_market (int | None)
                - source (str | None)

        """
        # TODO: wire up rental_listings.scraper when available
        logger.debug("Listing status check requested for: %s", property_address)
        return {
            "address": property_address,
            "listing_status": None,
            "days_on_market": None,
            "source": None,
        }

    # ------------------------------------------------------------------
    # Batch scoring
    # ------------------------------------------------------------------

    def score_properties(
        self,
        properties: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Add a ``priority_score`` to each property dict.

        Args:
            properties: List of property dictionaries that may include
                ``vacancy_risk``, ``rental_yield_delta``, and
                ``competitor_sentiment`` keys.

        Returns:
            The same list with the ``priority_score`` key set.

        """
        for prop in properties:
            prop["priority_score"] = self.calculate_priority_score(
                vacancy_risk=prop.get("vacancy_risk", 0.0),
                rental_yield_delta=prop.get("rental_yield_delta", 0.0),
                competitor_sentiment=prop.get("competitor_sentiment", 0.0),
            )
        return properties
