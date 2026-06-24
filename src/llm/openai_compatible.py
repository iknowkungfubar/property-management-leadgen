"""OpenAI-compatible /chat/completions provider.

Supports OpenAI, OpenPipe, Groq, and any local server (Ollama, vLLM, …)
that exposes the standard ``/chat/completions`` endpoint.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from src.llm.base import LLMProvider, strip_json_fences

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT: float = 120.0
DEFAULT_MODEL: str = "gpt-4o"


class OpenAICompatibleProvider(LLMProvider):
    """LLM provider for any ``/chat/completions``-compatible backend.

    Uses ``response_format={"type": "json_object"}`` when available to
    guarantee structured output.  Falls back to prompt-based instructions
    for backends that do not support the parameter (e.g. Groq, Ollama).
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        """Store connection details.

        Args:
            api_key: API key (may be a dummy value for local servers).
            model: Model identifier.
            base_url: Root URL of the ``/chat/completions`` endpoint.

        """
        self._api_key: str = api_key
        self._model: str = model
        self._base_url: str = base_url.rstrip("/")

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
        }

    def generate_structured_json(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call ``/chat/completions`` and return parsed JSON.

        Args:
            system_prompt: System-level instruction.
            user_prompt: The user message.
            **kwargs: Passed through to the API payload (temperature, etc.).

        Returns:
            Parsed JSON dictionary from the response content.

        Raises:
            RuntimeError: On HTTP or parsing errors.

        """
        headers = self._build_headers()

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": kwargs.get("temperature", 0.1),
            "max_tokens": kwargs.get("max_tokens", 4096),
        }

        # Request JSON mode if the backend supports it
        if "json_object" in (kwargs.get("supported_response_formats") or ["json_object"]):
            payload["response_format"] = {"type": "json_object"}

        try:
            with httpx.Client(timeout=kwargs.get("timeout", DEFAULT_TIMEOUT)) as client:
                response = client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data: dict[str, Any] = response.json()
        except httpx.HTTPStatusError as exc:
            logger.exception("OpenAI-compatible API error: %s — %s", exc, exc.response.text)
            raise RuntimeError(
                f"API returned {exc.response.status_code}: {exc.response.text}",
            ) from exc
        except httpx.RequestError as exc:
            logger.exception("Request to OpenAI-compatible endpoint failed: %s", exc)
            raise RuntimeError(f"Request error: {exc}") from exc

        try:
            content: str = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                "Unexpected response structure from /chat/completions",
            ) from exc

        cleaned = strip_json_fences(content)

        try:
            return dict(json.loads(cleaned))
        except (json.JSONDecodeError, TypeError) as exc:
            logger.exception("Failed to parse response as JSON: %s", content)
            raise RuntimeError(f"Could not parse LLM response as JSON: {exc}") from exc


if __name__ == "__main__":
    import os

    key = os.environ.get("OPENAI_API_KEY", "sk-placeholder")
    provider = OpenAICompatibleProvider(api_key=key)
    result = provider.generate_structured_json(
        "You are a helpful assistant.",
        'Return {"hello": "world"}',
    )
