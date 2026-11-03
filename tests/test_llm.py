"""Provider resolution + failover classification: first provider key
present wins (HF primary, OpenRouter second); explicit CHAT_MODEL / LLM_BASE_URL
override."""

from __future__ import annotations

import httpx
import openai
import pytest

from email_task_agent.config import Settings
from email_task_agent.llm import provider_failure, resolve_provider


def test_hf_token_selects_hf_router_and_deepseek():
    base, key, model = resolve_provider(Settings(hf_token="hf-key"))
    assert base == "https://router.huggingface.co/v1"
    assert key == "hf-key" and model == "deepseek-ai/DeepSeek-V4.1-Flash-1017"


def test_hf_token_wins_over_openrouter():
    _, key, model = resolve_provider(Settings(hf_token="hf", or_api_key="o"))
    assert key == "hf" and model == "deepseek-ai/DeepSeek-V4.1-Flash-1017"


def test_openrouter_key_selects_openrouter_and_deepseek():
    base, key, model = resolve_provider(Settings(or_api_key="o-key"))
    assert base == "https://openrouter.ai/api/v1"
    assert key == "o-key" and model == "deepseek/deepseek-v4.1-flash-1017"


def test_explicit_overrides_beat_provider_defaults():
    base, key, model = resolve_provider(
        Settings(
            hf_token="hf",
            llm_base_url="https://custom.example/v1",
            chat_model="custom-model",
        )
    )
    assert (base, key, model) == ("https://custom.example/v1", "hf", "custom-model")


def test_no_key_raises():
    with pytest.raises(RuntimeError, match="HF_TOKEN"):
        resolve_provider(Settings())


# -- provider_failure (runtime failover classification) --------------------------------


def _status_error(cls, status: int):
    request = httpx.Request("POST", "https://router.example/v1/chat/completions")
    return cls("provider error", response=httpx.Response(status, request=request), body=None)


def test_throttle_and_quota_are_provider_failures():
    assert provider_failure(_status_error(openai.RateLimitError, 429))
    assert provider_failure(_status_error(openai.APIStatusError, 402))
    assert provider_failure(openai.APIConnectionError(request=httpx.Request("POST", "https://x")))


def test_auth_error_is_a_provider_failure():
    assert provider_failure(_status_error(openai.AuthenticationError, 401))


def test_bad_request_is_not_a_provider_failure():
    assert not provider_failure(_status_error(openai.BadRequestError, 400))


def test_programming_and_tool_errors_are_not_provider_failures():
    assert not provider_failure(TypeError("x"))
    assert not provider_failure(KeyError("x"))
    assert not provider_failure(RuntimeError("connection reset after sending"))  # a tool crash
