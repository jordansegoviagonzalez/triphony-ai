from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Use DATABASE_URL directly so you can swap Postgres/SQLite quickly.
    database_url: str
    redis_url: str
    artifacts_dir: str
    provider_mode: str = "mock"  # "mock" for local dev/testing, "real" for production API integration
    video_generation_api_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
