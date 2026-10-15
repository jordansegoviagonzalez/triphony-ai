"""ElevenLabs narration, music, ambience, and effects adapter."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Callable

from providers.common import digest, provider_job
from providers.config import ProviderConfig
from providers.errors import ProviderError, ProviderErrorKind, translate_provider_exception
from providers.vertex import create_elevenlabs_client
from triphony_lib.agents import AudioAgent
from triphony_lib.domain import (
    AgentCapabilities,
    AgentType,
    AssetVersion,
    AssetVersionStatus,
    AudioAgentRequest,
    AudioAgentResult,
    MediaType,
    ProviderJobStatus,
    ProvenanceMetadata,
)


def _as_bytes(payload: Any, max_bytes: int) -> tuple[bytes, str | None, str | None]:
    headers = getattr(payload, "headers", None)
    content_type = getattr(payload, "content_type", None)
    request_id = None
    if isinstance(headers, dict):
        content_type = content_type or headers.get("content-type")
        request_id = headers.get("request-id") or headers.get("x-trace-id")
    data = getattr(payload, "data", payload)
    if hasattr(data, "content") and isinstance(data.content, bytes):
        data = data.content
    if isinstance(data, bytes):
        result = data
    elif isinstance(data, bytearray):
        result = bytes(data)
    elif isinstance(data, Iterable) and not isinstance(data, (str, dict)):
        chunks: list[bytes] = []
        size = 0
        for chunk in data:
            if not isinstance(chunk, (bytes, bytearray)):
                raise ProviderError(ProviderErrorKind.malformed, "audio provider returned a non-binary chunk")
            size += len(chunk)
            if size > max_bytes:
                raise ProviderError(ProviderErrorKind.invalid_request, "audio output exceeded the configured size limit")
            chunks.append(bytes(chunk))
        result = b"".join(chunks)
    else:
        raise ProviderError(ProviderErrorKind.malformed, "audio provider returned an unsupported response")
    if not result:
        raise ProviderError(ProviderErrorKind.malformed, "audio provider returned empty content")
    if len(result) > max_bytes:
        raise ProviderError(ProviderErrorKind.invalid_request, "audio output exceeded the configured size limit")
    if content_type and not content_type.lower().split(";", 1)[0].startswith("audio/"):
        raise ProviderError(ProviderErrorKind.malformed, "audio provider returned an invalid content type")
    return result, content_type or "audio/mpeg", request_id


def _extension(output_format: str) -> str:
    return "wav" if output_format.startswith(("pcm", "wav")) else "mp3"


class ElevenLabsAudioAgent(AudioAgent):
    capabilities = AgentCapabilities(
        agent_type=AgentType.audio,
        provider_name="elevenlabs",
        supported_media_types=[MediaType.narration, MediaType.music, MediaType.ambience, MediaType.sound_effect],
        asynchronous_jobs=False,
        cancellation_supported=False,
        deterministic=False,
    )

    def __init__(self, config: ProviderConfig, client_factory: Callable[[], Any] | None = None) -> None:
        self.config = config
        self._client_factory = client_factory or (lambda: create_elevenlabs_client(config))
        self._client: Any | None = None
        self._results: dict[str, tuple[str, AudioAgentResult]] = {}

    def _client_or_create(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def _asset(
        self,
        *,
        job_id: str,
        scene_id: str,
        media_type: MediaType,
        content: bytes,
        content_type: str,
        request_id: str | None,
        content_text: str | None = None,
        duration_seconds: float | None = None,
    ) -> AssetVersion:
        if duration_seconds is not None and duration_seconds > self.config.max_audio_duration_seconds:
            raise ProviderError(ProviderErrorKind.invalid_request, "audio output exceeded the configured duration limit")
        asset_version_id = f"asset-{digest({'job': job_id, 'type': media_type.value})[:24]}"
        extension = _extension(self.config.elevenlabs_output_format)
        metadata: dict[str, Any] = {
            "mime_type": content_type,
            "byte_length": len(content),
            "filename": f"{asset_version_id}.{extension}",
        }
        if duration_seconds is not None:
            metadata["duration_seconds"] = duration_seconds
        if request_id:
            metadata["provider_request_id"] = request_id
        return AssetVersion(
            asset_version_id=asset_version_id,
            scene_id=scene_id,
            asset_id=f"audio-{media_type.value}",
            version=1,
            media_type=media_type,
            status=AssetVersionStatus.draft,
            artifact_uri=f"provider://elevenlabs/{asset_version_id}.{extension}",
            content_text=content_text,
            provenance=ProvenanceMetadata(
                source="provider",
                provider="elevenlabs",
                model=self.config.elevenlabs_tts_model if media_type is MediaType.narration else self.config.elevenlabs_music_model,
                metadata=metadata,
            ),
        )

    def _generate_one(self, request: AudioAgentRequest, media_type: MediaType, prompt: str) -> AssetVersion:
        client = self._client_or_create()
        try:
            if media_type is MediaType.narration:
                payload = client.text_to_speech.convert(
                    text=prompt,
                    voice_id=self.config.elevenlabs_voice_id,
                    model_id=self.config.elevenlabs_tts_model,
                    output_format=self.config.elevenlabs_output_format,
                )
            elif media_type is MediaType.music:
                payload = client.music.compose(
                    prompt=prompt,
                    music_length_ms=min(request.plan.total_duration_ms, self.config.max_audio_duration_seconds * 1000),
                    model_id=self.config.elevenlabs_music_model,
                    output_format=self.config.elevenlabs_output_format,
                )
            else:
                payload = client.text_to_sound_effects.convert(
                    text=prompt,
                    model_id="eleven_text_to_sound_v2",
                    output_format=self.config.elevenlabs_output_format,
                    duration_seconds=min(self.config.max_audio_duration_seconds, 30),
                )
            content, content_type, request_id = _as_bytes(payload, self.config.max_audio_bytes)
            duration = getattr(payload, "duration_seconds", None)
            return self._asset(
                job_id=f"elevenlabs-{digest(request.idempotency.key)[:20]}",
                scene_id=request.plan.scene_id,
                media_type=media_type,
                content=content,
                content_type=content_type,
                request_id=request_id,
                content_text=prompt if media_type is MediaType.narration else None,
                duration_seconds=duration,
            )
        except ProviderError:
            raise
        except Exception as error:
            raise translate_provider_exception(error) from error

    def generate_narration(self, request: AudioAgentRequest) -> AssetVersion:
        prompt = "\n".join(shot.narration.narration_text or shot.narration.summary for shot in request.plan.shots)
        return self._generate_one(request, MediaType.narration, prompt)

    def generate_music(self, request: AudioAgentRequest) -> AssetVersion:
        prompt = "; ".join(shot.audio.music for shot in request.plan.shots)
        return self._generate_one(request, MediaType.music, prompt)

    def generate_ambience(self, request: AudioAgentRequest) -> AssetVersion:
        prompt = "; ".join(shot.audio.ambience for shot in request.plan.shots)
        return self._generate_one(request, MediaType.ambience, prompt)

    def generate_sound_effect(self, request: AudioAgentRequest) -> AssetVersion:
        prompt = "; ".join(effect for shot in request.plan.shots for effect in shot.audio.sound_effects)
        return self._generate_one(request, MediaType.sound_effect, prompt)

    def generate(self, request: AudioAgentRequest) -> AudioAgentResult:
        fingerprint = digest(request.model_dump(mode="json"))
        cached = self._results.get(request.idempotency.key)
        if cached:
            if cached[0] != fingerprint:
                raise ProviderError(ProviderErrorKind.invalid_request, "idempotency key was reused for a different request")
            return cached[1]
        assets = [
            self.generate_narration(request),
            self.generate_music(request),
            self.generate_ambience(request),
            self.generate_sound_effect(request),
        ]
        job = provider_job(
            job_id=f"elevenlabs-{digest(request.idempotency.key)[:20]}",
            scene_id=request.plan.scene_id,
            agent_type=AgentType.audio,
            media_type=MediaType.audio,
            idempotency=request.idempotency,
            provider="elevenlabs",
            model=self.config.elevenlabs_music_model,
            status=ProviderJobStatus.succeeded,
        )
        result = AudioAgentResult(job=job, assets=assets)
        self._results[request.idempotency.key] = (fingerprint, result)
        return result

    def cancel(self, job_id: str) -> None:
        del job_id

