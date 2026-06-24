"""Abstract base class for all LLM providers.

Every provider enforces structured JSON output so downstream agents can
reliably destructure responses across different backends.
"""

from __future__ import annotations

import abc
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Shared helpers for LLM response parsing
# ------------------------------------------------------------------


def strip_json_fences(raw: str) -> str:
    """Remove optional markdown code fences around a JSON response.

    Many LLMs wrap JSON output in `` ```json … ``` `` fences even when
    asked to return raw JSON.  This helper strips them safely.

    Args:
        raw: The raw text returned by the model.

    Returns:
        Cleaned text with any surrounding fences removed.

    """
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (````json```` or plain ``````)
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        if "```" in cleaned:
            cleaned = cleaned[: cleaned.rindex("```")]
        cleaned = cleaned.strip()
    return cleaned


class LLMProvider(abc.ABC):
    """Polymorphic LLM interface.

    Subclasses must implement :meth:`generate_structured_json`, which
    returns a Python dictionary parsed from the model's response.
    """

    @abc.abstractmethod
    def generate_structured_json(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a prompt pair to the LLM and return parsed JSON.

        Args:
            system_prompt: The system-level instruction (role/meta).
            user_prompt: The user message containing the actual request.
            **kwargs: Backend-specific overrides (temperature, max_tokens, …).

        Returns:
            A dictionary parsed from the model's JSON response.

        Raises:
            RuntimeError: If the API call fails or the response cannot be
                parsed as JSON.

        """
        ...
