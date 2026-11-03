"""LLM provider resolution + model construction (plan D3; bake-off via env).

Primary = HF Inference Providers (HF_TOKEN) → OpenRouter (OR_API_KEY). The
non-primary key, when present, is the RUNTIME FAILOVER: a provider-level
failure (throttled, out of credits, down) retries the same request on it.

Explicit LLM_BASE_URL / CHAT_MODEL / EXTRACTION_MODEL always beat defaults:

  HF_TOKEN       -> router.huggingface.co, deepseek-ai/DeepSeek-V4.1-Flash-1017
  OR_API_KEY     -> openrouter.ai, deepseek/deepseek-v4.1-flash-1017
"""

from __future__ import annotations

from typing import Literal

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from email_task_agent.config import Settings, settings

_HF_BASE = "https://router.huggingface.co/v1"
_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_OPENROUTER_MODEL = "deepseek/deepseek-v4.1-flash-1017"


def resolve_provider(s: Settings | None = None) -> tuple[str, str, str]:
    """(base_url, api_key, default_model) for the first provider key present.

    Explicit LLM_BASE_URL / CHAT_MODEL always override provider defaults.
    """
    s = s or settings()
    if s.hf_token:
        return (s.llm_base_url or _HF_BASE), s.hf_token, s.chat_model or "deepseek-ai/DeepSeek-V4.1-Flash-1017"
    if s.or_api_key:
        return (s.llm_base_url or _OPENROUTER_BASE), s.or_api_key, s.chat_model or _OPENROUTER_MODEL
    raise RuntimeError("no LLM key configured (set HF_TOKEN or OR_API_KEY in .env)")


def openrouter_fallback(s: Settings | None = None) -> Model | None:
    """The OpenRouter model when HF is the primary and OR_API_KEY is set —
    handed to ChatService for runtime failover. None otherwise."""
    s = s or settings()
    if not s.hf_token or not s.or_api_key:
        return None
    return OpenAIChatModel(
        _OPENROUTER_MODEL,
        provider=OpenAIProvider(base_url=_OPENROUTER_BASE, api_key=s.or_api_key),
    )


def provider_failure(exc: Exception) -> bool:
    """True for provider-level failures worth a fallback retry: throttled,
    out of credits, bad auth, provider down, connection/timeout. Everything
    else — tool errors, programming errors, malformed requests (400) — is not:
    those are our bug, and a second provider would only mask them."""
    module = type(exc).__module__.split(".")[0]
    if module == "openai":
        import openai

        return not isinstance(exc, openai.BadRequestError)
    if module == "pydantic_ai":
        from pydantic_ai.exceptions import ModelHTTPError

        return isinstance(exc, ModelHTTPError) and exc.status_code not in (400, 422)
    return False


def build_model(model_name: str | None = None) -> Model:
    base_url, api_key, provider_default = resolve_provider()
    provider = OpenAIProvider(base_url=base_url, api_key=api_key)
    return OpenAIChatModel(model_name or provider_default, provider=provider)


def model_for_purpose(purpose: Literal["chat", "extraction"]) -> Model:
    """Provider default unless CHAT_MODEL / EXTRACTION_MODEL override it."""
    s = settings()
    override = s.chat_model if purpose == "chat" else s.extraction_model
    return build_model(override)
