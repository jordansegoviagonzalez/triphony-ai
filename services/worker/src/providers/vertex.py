"""Lazy official Google Gen AI SDK client construction."""

from __future__ import annotations

from typing import Any

from providers.config import ProviderConfig
from providers.errors import ProviderError, ProviderErrorKind


def create_vertex_client(config: ProviderConfig) -> Any:
    if config.mode != "real":
        raise ProviderError(ProviderErrorKind.configuration, "Vertex client creation requires real provider mode")
    if config.readiness_errors():
        raise ProviderError(ProviderErrorKind.configuration, "Vertex provider configuration is incomplete")
    try:
        from google import genai

        return genai.Client(
            vertexai=config.google_genai_use_vertexai,
            project=config.google_cloud_project,
            location=config.google_cloud_location,
        )
    except ProviderError:
        raise
    except Exception as error:
        raise ProviderError(ProviderErrorKind.configuration, "Vertex SDK client could not be created") from error


def create_elevenlabs_client(config: ProviderConfig) -> Any:
    if config.mode != "real":
        raise ProviderError(ProviderErrorKind.configuration, "ElevenLabs client creation requires real provider mode")
    if config.readiness_errors():
        raise ProviderError(ProviderErrorKind.configuration, "ElevenLabs provider configuration is incomplete")
    try:
        from elevenlabs.client import ElevenLabs

        return ElevenLabs(api_key=config.elevenlabs_api_key)
    except ProviderError:
        raise
    except Exception as error:
        raise ProviderError(ProviderErrorKind.configuration, "ElevenLabs SDK client could not be created") from error

