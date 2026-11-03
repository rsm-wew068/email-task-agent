"""LLM model construction (provider wiring, D3 via bake-off).

Z.ai's API is OpenAI-compatible, so GLM models work through pydantic-ai's
OpenAI provider with a custom base URL. Everything is env-driven — no model
names are hardcoded (the old gpt-4o-mini default was deprecated by OpenAI):

  LLM_API_KEY        API key (falls back to OPENAI_API_KEY)
  LLM_BASE_URL       OpenAI-compatible endpoint (default: Z.ai)
  CHAT_MODEL         chat model id        (default: glm-5.3-flash)
  EXTRACTION_MODEL   extraction model id  (default: glm-5.3-flash)
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from email_task_agent.config import settings


@lru_cache
def _provider() -> OpenAIProvider:
    key = settings().api_key
    if not key:
        raise RuntimeError("no LLM API key configured (set LLM_API_KEY in .env)")
    return OpenAIProvider(base_url=settings().llm_base_url, api_key=key)


def build_model(model_name: str | None = None) -> Model:
    return OpenAIChatModel(model_name or settings().chat_model, provider=_provider())
