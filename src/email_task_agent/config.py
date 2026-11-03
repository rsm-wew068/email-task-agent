from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str | None = None
    instance_mode: str = "private"  # private | demo (demo never holds real mail)

    # LLM providers: HF Inference Providers primary, OpenRouter failover — a
    # provider-level error (throttled, out of credits, down) on the primary
    # retries the same request on the fallback. Bake-off overrides below still win.
    hf_token: str | None = None  # HF Inference Providers router (settings access token)
    or_api_key: str | None = None  # OpenRouter, deepseek/deepseek-v4.1-flash-1017

    llm_base_url: str | None = None  # explicit OpenAI-compatible endpoint override
    chat_model: str | None = None  # explicit model override
    extraction_model: str | None = None

    # Demo spend cap: max LLM chat turns per calendar day.
    demo_daily_turn_cap: int = 100

    @property
    def api_key(self) -> str | None:
        return self.hf_token or self.or_api_key


@lru_cache
def settings() -> Settings:
    return Settings()
