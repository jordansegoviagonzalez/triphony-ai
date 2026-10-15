"""Validated provider configuration with secret-safe readiness reporting."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal


ProviderMode = Literal["fake", "real"]


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def is_placeholder_secret(value: str | None) -> bool:
    if not value:
        return True
    normalized = value.strip().lower()
    return normalized in {
        "change-me",
        "changeme",
        "example",
        "example-key",
        "your-api-key",
        "your_api_key",
        "xi-api-key",
        "test",
    } or normalized.startswith(("your-", "your_", "<", "{"))


@dataclass(frozen=True)
class ProviderConfig:
    mode: ProviderMode = "fake"
    google_cloud_project: str | None = None
    google_cloud_location: str = "global"
    google_genai_use_vertexai: bool = True
    gemini_model: str = "gemini-2.5-flash"
    veo_model: str = "veo-3.1-generate-001"
    veo_output_gcs_uri: str | None = None
    poll_interval_seconds: float = 15.0
    operation_timeout_seconds: float = 900.0
    max_generation_duration_seconds: int = 10
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None
    elevenlabs_tts_model: str = "eleven_multilingual_v2"
    elevenlabs_music_model: str = "music_v2_5"
    elevenlabs_output_format: str = "mp3_44100_128"
    request_timeout_seconds: float = 120.0
    max_audio_duration_seconds: int = 30
    max_audio_bytes: int = 25_000_000
    runway_api_secret: str | None = None
    runway_model: str = "gen4.5"
    runway_fallback_enabled: bool = False
    runway_poll_interval_seconds: float = 5.0
    runway_poll_deadline_seconds: float = 600.0
    runway_request_timeout_seconds: float = 120.0
    runway_max_duration_seconds: int = 10

    @classmethod
    def from_environment(cls) -> "ProviderConfig":
        raw_mode = os.getenv("PROVIDER_MODE", "fake").strip().lower()
        mode: ProviderMode
        if raw_mode == "mock":
            mode = "fake"
        elif raw_mode in {"fake", "real"}:
            mode = raw_mode  # type: ignore[assignment]
        else:
            raise ValueError("PROVIDER_MODE must be fake or real")
        return cls(
            mode=mode,
            google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT") or None,
            google_cloud_location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
            google_genai_use_vertexai=_env_bool("GOOGLE_GENAI_USE_VERTEXAI", True),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            veo_model=os.getenv("VEO_MODEL", "veo-3.1-generate-001"),
            veo_output_gcs_uri=os.getenv("VEO_OUTPUT_GCS_URI") or None,
            poll_interval_seconds=_env_float("PROVIDER_POLL_INTERVAL_SECONDS", 15.0),
            operation_timeout_seconds=_env_float("PROVIDER_OPERATION_TIMEOUT_SECONDS", 900.0),
            max_generation_duration_seconds=_env_int("MAX_GENERATION_DURATION_SECONDS", 10),
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY") or None,
            elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID") or None,
            elevenlabs_tts_model=os.getenv("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2"),
            elevenlabs_music_model=os.getenv("ELEVENLABS_MUSIC_MODEL", "music_v2_5"),
            elevenlabs_output_format=os.getenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128"),
            request_timeout_seconds=_env_float("PROVIDER_REQUEST_TIMEOUT_SECONDS", 120.0),
            max_audio_duration_seconds=_env_int("MAX_AUDIO_DURATION_SECONDS", 30),
            max_audio_bytes=_env_int("MAX_AUDIO_BYTES", 25_000_000),
            runway_api_secret=os.getenv("RUNWAY_API_SECRET") or None,
            runway_model=os.getenv("RUNWAY_MODEL", "gen4.5"),
            runway_fallback_enabled=_env_bool("RUNWAY_FALLBACK_ENABLED", False),
            runway_poll_interval_seconds=_env_float("RUNWAY_POLL_INTERVAL_SECONDS", 5.0),
            runway_poll_deadline_seconds=_env_float("RUNWAY_POLL_DEADLINE_SECONDS", 600.0),
            runway_request_timeout_seconds=_env_float("RUNWAY_REQUEST_TIMEOUT_SECONDS", 120.0),
            runway_max_duration_seconds=_env_int("RUNWAY_MAX_DURATION_SECONDS", 10),
        )

    @classmethod
    def from_settings(cls, value: Any) -> "ProviderConfig":
        raw_mode = getattr(value, "provider_mode", "fake")
        return cls(
            mode="fake" if raw_mode == "mock" else raw_mode,
            google_cloud_project=getattr(value, "google_cloud_project", None),
            google_cloud_location=getattr(value, "google_cloud_location", "global"),
            google_genai_use_vertexai=getattr(value, "google_genai_use_vertexai", True),
            gemini_model=getattr(value, "gemini_model", "gemini-2.5-flash"),
            veo_model=getattr(value, "veo_model", "veo-3.1-generate-001"),
            veo_output_gcs_uri=getattr(value, "veo_output_gcs_uri", None),
            poll_interval_seconds=getattr(value, "provider_poll_interval_seconds", 15.0),
            operation_timeout_seconds=getattr(value, "provider_operation_timeout_seconds", 900.0),
            max_generation_duration_seconds=getattr(value, "max_generation_duration_seconds", 10),
            elevenlabs_api_key=getattr(value, "elevenlabs_api_key", None),
            elevenlabs_voice_id=getattr(value, "elevenlabs_voice_id", None),
            elevenlabs_tts_model=getattr(value, "elevenlabs_tts_model", "eleven_multilingual_v2"),
            elevenlabs_music_model=getattr(value, "elevenlabs_music_model", "music_v2_5"),
            elevenlabs_output_format=getattr(value, "elevenlabs_output_format", "mp3_44100_128"),
            request_timeout_seconds=getattr(value, "provider_request_timeout_seconds", 120.0),
            max_audio_duration_seconds=getattr(value, "max_audio_duration_seconds", 30),
            max_audio_bytes=getattr(value, "max_audio_bytes", 25_000_000),
            runway_api_secret=getattr(value, "runway_api_secret", None),
            runway_model=getattr(value, "runway_model", "gen4.5"),
            runway_fallback_enabled=getattr(value, "runway_fallback_enabled", False),
            runway_poll_interval_seconds=getattr(value, "runway_poll_interval_seconds", 5.0),
            runway_poll_deadline_seconds=getattr(value, "runway_poll_deadline_seconds", 600.0),
            runway_request_timeout_seconds=getattr(value, "runway_request_timeout_seconds", 120.0),
            runway_max_duration_seconds=getattr(value, "runway_max_duration_seconds", 10),
        )

    def readiness_errors(self) -> list[str]:
        if self.mode == "fake":
            return []
        errors: list[str] = []
        if not self.google_genai_use_vertexai:
            errors.append("GOOGLE_GENAI_USE_VERTEXAI must be true for Vertex AI mode")
        if not self.google_cloud_project:
            errors.append("GOOGLE_CLOUD_PROJECT is required")
        if not self.google_cloud_location:
            errors.append("GOOGLE_CLOUD_LOCATION is required")
        if not self.veo_output_gcs_uri or not self.veo_output_gcs_uri.startswith("gs://"):
            errors.append("VEO_OUTPUT_GCS_URI must be a gs:// URI")
        if is_placeholder_secret(self.elevenlabs_api_key):
            errors.append("ELEVENLABS_API_KEY is missing or a placeholder")
        if is_placeholder_secret(self.elevenlabs_voice_id):
            errors.append("ELEVENLABS_VOICE_ID is missing or a placeholder")
        if self.poll_interval_seconds <= 0:
            errors.append("PROVIDER_POLL_INTERVAL_SECONDS must be positive")
        if self.operation_timeout_seconds <= 0:
            errors.append("PROVIDER_OPERATION_TIMEOUT_SECONDS must be positive")
        if self.max_audio_duration_seconds <= 0 or self.max_audio_bytes <= 0:
            errors.append("audio safety limits must be positive")
        if self.runway_fallback_enabled:
            if is_placeholder_secret(self.runway_api_secret):
                errors.append("RUNWAY_API_SECRET is missing or a placeholder")
            if self.runway_poll_interval_seconds < 5:
                errors.append("RUNWAY_POLL_INTERVAL_SECONDS must be at least 5 seconds")
            if self.runway_poll_deadline_seconds <= 0 or self.runway_max_duration_seconds <= 0:
                errors.append("Runway polling and output limits must be positive")
        return errors
