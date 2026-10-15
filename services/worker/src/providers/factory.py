"""Single provider-selection boundary for worker business logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from providers.config import ProviderConfig
from providers.elevenlabs import ElevenLabsAudioAgent
from providers.gemini import GeminiNarrativeDirector, GeminiQAAgent
from providers.fallback import ActivePassiveVisualAgent
from providers.runway import RunwayVisualAgent
from providers.errors import ProviderErrorKind
from providers.veo import VeoVisualAgent
from providers.vertex import create_elevenlabs_client, create_vertex_client
from triphony_lib.agents import AudioAgent, NarrativeDirector, QAAgent, VisualAgent
from triphony_lib.fakes import FakeAudioAgent, FakeNarrativeDirector, FakeQAAgent, FakeVisualAgent
from resilience.circuit_breaker import RedisCircuitBreaker
import redis
import logging
from triphony_lib.observability import json_log, metric_inc


@dataclass(frozen=True)
class ProviderBundle:
    narrative: NarrativeDirector
    visual: VisualAgent
    audio: AudioAgent
    qa: QAAgent
    mode: str


def build_provider_bundle(
    config: ProviderConfig | None = None,
    *,
    settings_obj: Any | None = None,
    vertex_client_factory: Callable[[], Any] | None = None,
    elevenlabs_client_factory: Callable[[], Any] | None = None,
) -> ProviderBundle:
    if config is None:
        config = ProviderConfig.from_settings(settings_obj) if settings_obj is not None else ProviderConfig.from_environment()
    if config.mode == "fake":
        return ProviderBundle(
            narrative=FakeNarrativeDirector(),
            visual=FakeVisualAgent(),
            audio=FakeAudioAgent(),
            qa=FakeQAAgent(),
            mode="fake",
        )
    errors = config.readiness_errors()
    if errors:
        raise ValueError("Provider readiness failed: " + "; ".join(errors))
    vertex_factory = vertex_client_factory or (lambda: create_vertex_client(config))
    audio_factory = elevenlabs_client_factory or (lambda: create_elevenlabs_client(config))
    visual: VisualAgent = VeoVisualAgent(config, vertex_factory)
    if config.runway_fallback_enabled:
        def on_state_change(old: str, new: str, reason: str) -> None:
            metric_inc("triphony.circuit.state_changes", provider="google-vertex-ai", capability="video", state=new)
            json_log(logging.getLogger("triphony.provider"), logging.INFO, "circuit_state_change", provider="google-vertex-ai", capability="video", old_state=old, new_state=new, reason=reason)

        breaker = RedisCircuitBreaker(
            redis.Redis.from_url(settings_obj.redis_url if settings_obj is not None else "redis://localhost:6379/0", decode_responses=True),
            "veo:video",
            on_state_change=on_state_change,
        )
        visual = ActivePassiveVisualAgent(
            primary=visual,
            fallback=RunwayVisualAgent(config),
            fallback_enabled=True,
            circuit_open=lambda: not breaker.allow(),
            on_fallback=lambda reason: (metric_inc("triphony.provider.fallbacks", provider="runway", reason=reason), json_log(logging.getLogger("triphony.provider"), logging.INFO, "provider_fallback", provider="runway", reason=reason)),
            on_primary_success=breaker.record_success,
            on_primary_failure=lambda error: breaker.record_failure(infrastructure=error.kind in {
                ProviderErrorKind.unavailable, ProviderErrorKind.retryable, ProviderErrorKind.timeout,
            }),
        )
    return ProviderBundle(
        narrative=GeminiNarrativeDirector(config, vertex_factory),
        visual=visual,
        audio=ElevenLabsAudioAgent(config, audio_factory),
        qa=GeminiQAAgent(config, vertex_factory),
        mode="real",
    )
