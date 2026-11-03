from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str | None = None
    openai_api_key: str | None = None
    instance_mode: str = "private"  # private | demo (D8: demo never holds real mail)

    # LLM wiring (plan §D3 via bake-off). Z.ai's API is OpenAI-compatible, so
    # any provider that speaks that protocol works through LLM_BASE_URL.
    zai_api_key: str | None = None  # Z.ai's native variable name
    llm_api_key: str | None = None  # generic alias
    llm_base_url: str = "https://api.z.ai/api/paas/v4/"
    chat_model: str = "glm-5.3-flash"
    extraction_model: str = "glm-5.3-flash"

    # Demo spend cap: max LLM chat turns per calendar day (plan §11).
    demo_daily_turn_cap: int = 100

    @property
    def api_key(self) -> str | None:
        return self.llm_api_key or self.zai_api_key or self.openai_api_key


@lru_cache
def settings() -> Settings:
    return Settings()
