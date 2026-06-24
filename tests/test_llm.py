"""Tests for LLM provider abstraction, factory, and mock providers."""

from __future__ import annotations

import sqlite3

import pytest

from src.llm.base import LLMProvider
from src.llm.factory import get_active_llm_client

# ── Mock provider for testing ───────────────────────────────────────


class MockLLMProvider(LLMProvider):
    """A deterministic LLM provider for testing."""

    def __init__(self, response: dict | None = None) -> None:
        self._response = response or {"hello": "world"}
        self.last_system: str = ""
        self.last_user: str = ""

    def generate_structured_json(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs,
    ) -> dict:
        self.last_system = system_prompt
        self.last_user = user_prompt
        return dict(self._response)


# ── Abstract base ───────────────────────────────────────────────────


class TestLLMProviderBase:
    """Abstract base contract tests."""

    @staticmethod
    def test_mock_provider_returns_expected() -> None:
        provider = MockLLMProvider({"test": "value"})
        result = provider.generate_structured_json("sys", "usr")
        assert result == {"test": "value"}

    @staticmethod
    def test_mock_provider_captures_prompts() -> None:
        provider = MockLLMProvider()
        provider.generate_structured_json("Hello", "World")
        assert provider.last_system == "Hello"
        assert provider.last_user == "World"

    @staticmethod
    def test_base_class_cannot_be_instantiated() -> None:
        with pytest.raises(TypeError):
            LLMProvider()  # type: ignore[abstract]


# ── Factory tests ───────────────────────────────────────────────────


class TestGetActiveLlmClient:
    """Factory reading from the llm_settings table."""

    @staticmethod
    @pytest.fixture
    def db_conn() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")

        conn.execute(
            """CREATE TABLE llm_settings (
                provider TEXT PRIMARY KEY
                    CHECK(provider IN ("anthropic", "openai", "openpipe", "local_ollama")),
                api_key TEXT,
                base_url TEXT,
                selected_model TEXT NOT NULL,
                is_active INTEGER DEFAULT 0
            )"""
        )

        # Seed the table with an active Anthropic entry
        conn.execute(
            """INSERT INTO llm_settings (provider, api_key, base_url, selected_model, is_active)
                VALUES (
                    "anthropic",
                    "sk-test",
                    "https://api.anthropic.com",
                    "claude-sonnet-4-20250514",
                    1
                )"""
        )
        conn.commit()
        return conn

    @staticmethod
    def test_factory_returns_anthropic_provider(db_conn: sqlite3.Connection) -> None:
        """When anthropic is active, factory should return AnthropicProvider."""
        from src.llm.anthropic_provider import AnthropicProvider

        client = get_active_llm_client(db_conn)
        assert isinstance(client, AnthropicProvider)
        assert client._model == "claude-sonnet-4-20250514"

    @staticmethod
    def test_factory_no_active_provider() -> None:
        """No active provider should raise ValueError."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE llm_settings (
                provider TEXT PRIMARY KEY
                    CHECK(provider IN ("anthropic", "openai", "openpipe", "local_ollama")),
                api_key TEXT,
                base_url TEXT,
                selected_model TEXT NOT NULL,
                is_active INTEGER DEFAULT 0
            )"""
        )
        conn.commit()
        with pytest.raises(ValueError, match="No active LLM provider"):
            get_active_llm_client(conn)

    @staticmethod
    def test_factory_openai_compatible(db_conn: sqlite3.Connection) -> None:
        """An openai-compatible provider entry returns OpenAICompatibleProvider."""
        from src.llm.openai_compatible import OpenAICompatibleProvider

        # Deactivate anthropic, activate openai
        db_conn.execute("UPDATE llm_settings SET is_active = 0")
        db_conn.execute(
            """INSERT OR REPLACE INTO llm_settings
               (provider, api_key, base_url, selected_model, is_active)
               VALUES ("openai", "sk-openai", "https://api.openai.com/v1", "gpt-4o", 1)"""
        )
        db_conn.commit()

        client = get_active_llm_client(db_conn)
        assert isinstance(client, OpenAICompatibleProvider)
        assert client._model == "gpt-4o"


# ── Anthropic provider structure ────────────────────────────────────


class TestAnthropicProvider:
    """Structural tests for AnthropicProvider (no real API call)."""

    @staticmethod
    def test_build_headers() -> None:
        from src.llm.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(api_key="sk-test")
        headers = provider._build_headers()
        assert headers["x-api-key"] == "sk-test"
        assert headers["anthropic-version"] == "2023-06-01"
        assert headers["content-type"] == "application/json"

    @staticmethod
    def test_build_payload() -> None:
        from src.llm.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(api_key="sk-test")
        payload = provider._build_payload("system msg", "user msg")
        assert payload["model"] == "claude-sonnet-4-20250514"
        assert payload["system"] == "system msg"
        assert payload["messages"][0]["content"] == "user msg"


# ── OpenAI-compatible provider structure ────────────────────────────


class TestOpenAICompatibleProvider:
    """Structural tests (no real API call)."""

    @staticmethod
    def test_build_headers() -> None:
        from src.llm.openai_compatible import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(api_key="sk-test")
        headers = provider._build_headers()
        assert headers["Authorization"] == "Bearer sk-test"
