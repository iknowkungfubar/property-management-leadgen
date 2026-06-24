"""LLM provider factory — reads active configuration from the database."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.llm.anthropic_provider import AnthropicProvider
from src.llm.openai_compatible import OpenAICompatibleProvider

if TYPE_CHECKING:
    import sqlite3

    from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)


def get_active_llm_client(db_conn: sqlite3.Connection) -> LLMProvider:
    """Read the active LLM configuration from ``llm_settings`` and return a provider.

    Args:
        db_conn: Open SQLite connection.

    Returns:
        A configured :class:`LLMProvider` instance.

    Raises:
        ValueError: If no active provider is configured.

    """
    row = db_conn.execute(
        "SELECT provider, api_key, base_url, selected_model "
        "FROM llm_settings WHERE is_active = 1 "
        "ORDER BY provider LIMIT 1",
    ).fetchone()

    if not row:
        raise ValueError(
            "No active LLM provider configured. Please configure one in Settings.",
        )

    provider_name: str = row["provider"]
    api_key: str | None = row["api_key"]
    base_url: str | None = row["base_url"]
    model: str = row["selected_model"]

    logger.info("Creating LLM client for provider '%s', model '%s'", provider_name, model)

    if provider_name == "anthropic":
        if not api_key:
            raise ValueError("Anthropic provider selected but no API key set.")
        return AnthropicProvider(
            api_key=api_key,
            model=model,
            base_url=base_url or AnthropicProvider.ANTHROPIC_API_URL,  # type: ignore[attr-defined]
        )

    if provider_name in ("openai", "openpipe", "local_ollama"):
        return OpenAICompatibleProvider(
            api_key=api_key or "sk-unused",
            model=model,
            base_url=base_url or "https://api.openai.com/v1",
        )

    raise ValueError(f"Unknown LLM provider: {provider_name}")
