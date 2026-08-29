"""LLM client — OpenAI-compatible API (Phase 7).

Uses httpx to call any OpenAI-compatible /chat/completions endpoint
(OpenAI, 阿里云百炼, DeepSeek, local proxies, etc.).

If no api_key is configured, the client reports itself as unavailable —
the QA pipeline then falls back to evidence-only mode (retrieval
results shown with provenance, no generated answer). We never invent
answers without a real LLM response.
"""

from __future__ import annotations

import httpx

from src.core.config import get_config
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.llm")


class LLMError(Exception):
    """Raised when the LLM call fails."""


class LLMClient:
    """Minimal OpenAI-compatible chat client."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ):
        cfg = get_config()
        self.base_url = (base_url or cfg.llm_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else cfg.llm_api_key
        self.model = model or cfg.llm_model
        self.max_tokens = max_tokens if max_tokens is not None else cfg.llm_max_tokens
        self.temperature = (
            temperature if temperature is not None else cfg.llm_temperature
        )

    @property
    def available(self) -> bool:
        """Whether a real LLM can be called (api_key configured)."""
        return bool(self.api_key)

    def chat(
        self,
        messages: list[dict],
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: float = 60.0,
    ) -> str:
        """Send a chat completion request.

        Args:
            messages: List of {"role": ..., "content": ...} dicts.
            max_tokens: Override max tokens.
            temperature: Override temperature.
            timeout: Request timeout in seconds.

        Returns:
            The assistant's text content.

        Raises:
            LLMError: if request fails.
        """
        if not self.available:
            raise LLMError("LLM 未配置 API Key（无法调用）")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature,
        }

        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:300] if e.response is not None else ""
            raise LLMError(f"LLM HTTP {e.response.status_code}: {detail}") from e
        except Exception as e:
            raise LLMError(f"LLM 调用失败: {e}") from e

    def system_prompt(self, instructions: str) -> dict:
        return {"role": "system", "content": instructions}


def get_llm_client() -> LLMClient:
    """Build the configured LLM client."""
    return LLMClient()
