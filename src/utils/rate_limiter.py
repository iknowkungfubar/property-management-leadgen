"""Rate limiter with exponential backoff and per-domain jitter.

T_sleep = t_base × 2^n + random_jitter

where ``t_base`` is the initial delay, ``n`` is the consecutive failure
count for that domain, and ``jitter`` is a random offset between 0 and 1
seconds.
"""

from __future__ import annotations

import logging
import random
import time

logger = logging.getLogger(__name__)

DEFAULT_BASE: float = 1.0  # seconds
MAX_BACKOFF: float = 300.0  # 5 minutes
MIN_INTERVAL: float = 0.5  # minimum gap between requests to the same domain


class RateLimiter:
    """Per-domain rate limiter with exponential backoff for error states.

    Thread-safe for asyncio use (no shared mutable state across coroutines
    beyond this object — callers should use one instance per scraper or
    pass a shared instance wrapped in a lock).
    """

    def __init__(self, base_delay: float = DEFAULT_BASE) -> None:
        """Initialise state for all domains.

        Args:
            base_delay: Initial delay in seconds (``t_base`` in the formula).

        """
        self._base: float = base_delay
        self._failures: dict[str, int] = {}
        self._last_call: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def wait_if_needed(self, domain: str) -> None:
        """Block (sleep) if the minimum interval has not elapsed for *domain*.

        Should be called *before* every request.  The first call to any
        domain never waits; subsequent calls respect ``MIN_INTERVAL``.

        Args:
            domain: A string identifying the target (e.g. ``"orange_county"``,
                ``"ca_sos"``).

        """
        now = time.monotonic()
        n = self._failures.get(domain, 0)

        # Exponential backoff from failures — only when there are failures
        backoff = min(self._base * 2**n + random.random(), MAX_BACKOFF) if n > 0 else 0.0

        # Minimum interval between calls to the same domain
        # (only applies after the first known call)
        if domain in self._last_call:
            elapsed = now - self._last_call[domain]
            min_gap = max(0.0, MIN_INTERVAL - elapsed)
        else:
            min_gap = 0.0

        wait = max(min_gap, backoff, 0.0)
        if wait > 0:
            logger.debug("Rate-limit wait %.2fs for '%s' (failures=%d)", wait, domain, n)
            time.sleep(wait)

    def record_failure(self, domain: str) -> None:
        """Increment the failure counter for *domain*.

        Args:
            domain: Target identifier.

        """
        current = self._failures.get(domain, 0)
        self._failures[domain] = current + 1
        logger.debug("Recorded failure for '%s' (total: %d)", domain, current + 1)

    def record_success(self, domain: str) -> None:
        """Reset the failure counter for *domain* after a successful request.

        Args:
            domain: Target identifier.

        """
        self._failures.pop(domain, None)
        logger.debug("Recorded success for '%s' — failures reset.", domain)

    def reset(self, domain: str | None = None) -> None:
        """Reset failure state for one or all domains.

        Args:
            domain: If given, reset only that domain.  If ``None``, reset all.

        """
        if domain:
            self._failures.pop(domain, None)
            self._last_call.pop(domain, None)
        else:
            self._failures.clear()
            self._last_call.clear()
        logger.debug("Rate limiter reset for '%s'.", domain or "ALL")
