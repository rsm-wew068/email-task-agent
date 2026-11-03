from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str | None = None
    instance_mode: str = "private"  # private | demo (D8: demo never holds real mail)

    # LLM provider keys — the first present one selects the provider (plan D3;
    # bake-off can override with LLM_BASE_URL / CHAT_MODEL / EXTRACTION_MODEL).
    gemini_api_key: str | None = None  # Google AI Studio; OpenAI-compatible endpoint
    zai_api_key: str | None = None  # Z.ai (GLM)
    llm_api_key: str | None = None  # generic alias, pairs with LLM_BASE_URL
    openai_api_key: str | None = None  # OpenAI (requires explicit LLM_BASE_URL + CHAT_MODEL)

    llm_base_url: str | None = None  # explicit OpenAI-compatible endpoint override
    chat_model: str | None = None  # explicit model override
    extraction_model: str | None = None

    # Demo spend cap: max LLM chat turns per calendar day (plan §11).
    demo_daily_turn_cap: int = 100

    @property
    def api_key(self) -> str | None:
        return self.llm_api_key or self.zai_api_key or self.gemini_api_key or self.openai_api_key


@lru_cache
def settings() -> Settings:
    return Settings()
