"""LLM provider resolution + model construction (plan D3; bake-off via env).

Provider = first key present in order GEMINI_API_KEY -> ZAI_API_KEY ->
LLM_API_KEY -> OPENAI_API_KEY. Explicit LLM_BASE_URL / CHAT_MODEL /
EXTRACTION_MODEL always beat the provider defaults.

  GEMINI_API_KEY -> Google AI Studio's OpenAI-compatible endpoint, gemini-3.8-flash
  ZAI_API_KEY    -> Z.ai (GLM), glm-5.3-flash
  LLM_API_KEY    -> whatever LLM_BASE_URL points at (set CHAT_MODEL too)
  OPENAI_API_KEY -> api.openai.com (set CHAT_MODEL too)

CHAT_MODEL / EXTRACTION_MODEL always override the provider's default model.
"""

from __future__ import annotations

from typing import Literal

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from email_task_agent.config import Settings, settings

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
_ZAI_BASE = "https://api.z.ai/api/paas/v4/"


def resolve_provider(s: Settings | None = None) -> tuple[str, str, str]:
    """(base_url, api_key, default_model) for the first provider key present.

    Explicit LLM_BASE_URL / CHAT_MODEL always override provider defaults.
    """
    s = s or settings()
    if s.gemini_api_key:
        return (s.llm_base_url or _GEMINI_BASE), s.gemini_api_key, s.chat_model or "gemini-3.8-flash"
    if s.zai_api_key or s.llm_api_key:
        key = s.llm_api_key or s.zai_api_key
        return (s.llm_base_url or _ZAI_BASE), key, s.chat_model or "glm-5.3-flash"
    if s.openai_api_key:
        if not s.llm_base_url or not s.chat_model:
            raise RuntimeError("OPENAI_API_KEY needs LLM_BASE_URL and CHAT_MODEL set in .env")
        return s.llm_base_url, s.openai_api_key, s.chat_model
    raise RuntimeError("no LLM key configured (set GEMINI_API_KEY or ZAI_API_KEY in .env)")


def build_model(model_name: str | None = None) -> Model:
    base_url, api_key, provider_default = resolve_provider()
    provider = OpenAIProvider(base_url=base_url, api_key=api_key)
    return OpenAIChatModel(model_name or provider_default, provider=provider)


def model_for_purpose(purpose: Literal["chat", "extraction"]) -> Model:
    """Provider default unless CHAT_MODEL / EXTRACTION_MODEL override it."""
    s = settings()
    override = s.chat_model if purpose == "chat" else s.extraction_model
    return build_model(override)
