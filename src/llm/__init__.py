"""LLM integration — OpenAI-compatible API (Phase 7)."""

from src.llm.client import LLMClient, LLMError, get_llm_client

__all__ = ["LLMClient", "LLMError", "get_llm_client"]
