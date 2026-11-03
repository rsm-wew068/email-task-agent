"""Provider resolution (plan D3): first provider key present wins; explicit
CHAT_MODEL / LLM_BASE_URL override."""

from __future__ import annotations

import pytest

from email_task_agent.config import Settings
from email_task_agent.llm import resolve_provider


def test_gemini_key_selects_google_endpoint_and_model():
    base, key, model = resolve_provider(Settings(gemini_api_key="g-key"))
    assert base == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert key == "g-key" and model == "gemini-3.8-flash"


def test_zai_key_selects_zai_endpoint():
    base, key, model = resolve_provider(Settings(zai_api_key="z-key"))
    assert base == "https://api.z.ai/api/paas/v4/"
    assert key == "z-key" and model == "glm-5.3-flash"


def test_gemini_wins_when_both_present():
    _, key, model = resolve_provider(Settings(gemini_api_key="g", zai_api_key="z"))
    assert key == "g" and model == "gemini-3.8-flash"


def test_explicit_overrides_beat_provider_defaults():
    base, key, model = resolve_provider(
        Settings(
            gemini_api_key="g",
            llm_base_url="https://custom.example/v1",
            chat_model="custom-model",
        )
    )
    assert (base, key, model) == ("https://custom.example/v1", "g", "custom-model")


def test_openai_requires_base_and_model():
    with pytest.raises(RuntimeError, match="LLM_BASE_URL"):
        resolve_provider(Settings(openai_api_key="o"))
    _base, _key, model = resolve_provider(
        Settings(openai_api_key="o", llm_base_url="https://api.openai.com/v1", chat_model="gpt-x")
    )
    assert model == "gpt-x"


def test_no_key_raises():
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        resolve_provider(Settings())
