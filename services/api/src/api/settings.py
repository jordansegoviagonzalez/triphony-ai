from __future__ import annotations

from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5433/ai_art_studio"
    redis_url: str = "redis://localhost:6379/0"
    artifacts_dir: str = "artifacts"
    provider_mode: Literal["fake", "mock", "real"] = "fake"
    google_cloud_project: str | None = None
    google_cloud_location: str = "global"
    google_genai_use_vertexai: bool = True
    gemini_model: str = "gemini-2.5-flash"
    veo_model: str = "veo-3.1-generate-001"
    veo_output_gcs_uri: str | None = None
    provider_poll_interval_seconds: float = 15.0
    provider_operation_timeout_seconds: float = 900.0
    max_generation_duration_seconds: int = 10
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None
    elevenlabs_tts_model: str = "eleven_multilingual_v2"
    elevenlabs_music_model: str = "music_v2_5"
    elevenlabs_output_format: str = "mp3_44100_128"
    provider_request_timeout_seconds: float = 120.0
    max_audio_duration_seconds: int = 30
    max_audio_bytes: int = 25_000_000
    runway_api_secret: str | None = None
    runway_model: str = "gen4.5"
    runway_fallback_enabled: bool = False
    runway_poll_interval_seconds: float = 5.0
    runway_poll_deadline_seconds: float = 600.0
    runway_request_timeout_seconds: float = 120.0
    runway_max_duration_seconds: int = 10
    artifact_storage_backend: Literal["local", "s3"] = "local"
    aws_region: str = "us-west-2"
    s3_bucket: str | None = None
    s3_key_prefix: str = "triphony"
    s3_server_side_encryption: Literal["AES256", "aws:kms"] = "AES256"
    s3_kms_key_id: str | None = None
    s3_presigned_url_expiration: int = 300
    s3_multipart_threshold_bytes: int = 64 * 1024 * 1024
    max_artifact_bytes: int = 512 * 1024 * 1024
    csrf_cookie_name: str = "triphony_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    trusted_hosts: str = "localhost,127.0.0.1"
    max_prompt_length: int = 4000
    max_shots: int = 16
    max_requested_duration_seconds: int = 60
    max_concurrent_workflows: int = 2
    daily_generation_quota: int = 20
    submission_rate_limit_seconds: int = 5
    celery_concurrency: int = 2
    celery_task_time_limit_seconds: int = 900
    celery_task_soft_time_limit_seconds: int = 840
    secret_key: str = "triphony-local-development-secret-change-me"
    auth_cookie_name: str = "triphony_session"
    auth_cookie_secure: bool = False
    auth_cookie_max_age: int = 60 * 60 * 24 * 7
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("SECRET_KEY must contain at least 32 characters")
        return value

    @model_validator(mode="after")
    def validate_real_mode_security(self) -> "Settings":
        if self.provider_mode == "real" and self.secret_key == "triphony-local-development-secret-change-me":
            raise ValueError("SECRET_KEY must be explicitly configured when PROVIDER_MODE=real")
        if self.provider_mode == "real" and not self.auth_cookie_secure:
            raise ValueError("AUTH_COOKIE_SECURE must be true when PROVIDER_MODE=real")
        return self

    @property
    def allowed_origins(self) -> set[str]:
        return {origin.strip() for origin in self.cors_origins.split(",") if origin.strip()}

    @property
    def allowed_hosts(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]


settings = Settings()
