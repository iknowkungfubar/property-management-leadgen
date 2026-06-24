"""Anthropic Messages API provider with structured JSON extraction."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from src.llm.base import LLMProvider, strip_json_fences

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL: str = "https://api.anthropic.com"
ANTHROPIC_VERSION: str = "2023-06-01"
DEFAULT_MAX_TOKENS: int = 4096
DEFAULT_MODEL: str = "claude-sonnet-4-20250514"
REQUEST_TIMEOUT: float = 120.0


class AnthropicProvider(LLMProvider):
    """LLM provider backed by Anthropic's Messages API."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = ANTHROPIC_API_URL,
    ) -> None:
        """Store credentials and model choice.

        Args:
            api_key: Anthropic API key.
            model: Model name string (e.g. ``claude-sonnet-4-20250514``).
            base_url: Override the API endpoint (for proxies / mirrors).

        """
        self._api_key: str = api_key
        self._model: str = model
        self._base_url: str = base_url.rstrip("/")

    def _build_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "model": self._model,
            "max_tokens": kwargs.get("max_tokens", DEFAULT_MAX_TOKENS),
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }

    def generate_structured_json(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call the Anthropic Messages API and extract a JSON content block.

        Args:
            system_prompt: System-level instruction.
            user_prompt: The user message.
            **kwargs: Passed through to the API payload.

        Returns:
            Parsed JSON dictionary from the first ``text`` content block.

        Raises:
            RuntimeError: On HTTP or parsing errors.

        """
        headers = self._build_headers()
        payload = self._build_payload(system_prompt, user_prompt, **kwargs)

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                response = client.post(
                    f"{self._base_url}/v1/messages",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data: dict[str, Any] = response.json()
        except httpx.HTTPStatusError as exc:
            logger.exception("Anthropic API error: %s — %s", exc, exc.response.text)
            raise RuntimeError(
                f"Anthropic API returned {exc.response.status_code}",
            ) from exc
        except httpx.RequestError as exc:
            logger.exception("Anthropic request failed: %s", exc)
            raise RuntimeError(f"Anthropic request error: {exc}") from exc

        # Extract the first text content block
        try:
            content_blocks: list[dict[str, Any]] = data["content"]
            text_block = next(
                b for b in content_blocks if b.get("type") == "text"
            )
            raw_text: str = text_block["text"]
        except (KeyError, StopIteration, TypeError) as exc:
            raise RuntimeError(
                "No text content block in Anthropic response",
            ) from exc

        cleaned = strip_json_fences(raw_text)

        try:
            return dict(json.loads(cleaned))
        except (json.JSONDecodeError, TypeError) as exc:
            logger.exception("Failed to parse Anthropic response as JSON: %s", raw_text)
            raise RuntimeError(
                f"Could not parse LLM response as JSON: {exc}",
            ) from exc


if __name__ == "__main__":
    # Quick smoke test — requires ANTHROPIC_API_KEY in environment
    import os

    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        provider = AnthropicProvider(api_key=key)
        result = provider.generate_structured_json(
            "You are a helpful assistant. Respond with JSON.",
            'Return {"hello": "world"}',
        )
    else:
        pass
