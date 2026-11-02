from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str | None = None
    openai_api_key: str | None = None
    instance_mode: str = "private"  # private | demo (D8: demo never holds real mail)


@lru_cache
def settings() -> Settings:
    return Settings()
