"""Secret-safe provider configuration inspection command."""

from __future__ import annotations

import json
import sys
from typing import Any

from providers.config import ProviderConfig


def provider_readiness(config: ProviderConfig | None = None) -> dict[str, Any]:
    config = config or ProviderConfig.from_environment()
    errors = config.readiness_errors()
    vertex_present = bool(
        config.google_cloud_project
        and config.google_cloud_location
        and config.google_genai_use_vertexai
        and config.veo_output_gcs_uri
    )
    eleven_present = bool(config.elevenlabs_api_key and config.elevenlabs_voice_id)
    return {
        "mode": config.mode,
        "ready": not errors,
        "required_providers": ["google-vertex-ai", "elevenlabs"],
        "configuration_present": {
            "google-vertex-ai": vertex_present if config.mode == "real" else True,
            "elevenlabs": eleven_present if config.mode == "real" else True,
        },
        "capabilities": {
            "narrative_director": config.mode == "fake" or vertex_present,
            "visual_veo": config.mode == "fake" or vertex_present,
            "visual_runway_fallback": config.mode == "fake" or (config.runway_fallback_enabled and bool(config.runway_api_secret)),
            "qa_gemini": config.mode == "fake" or vertex_present,
            "audio_narration": config.mode == "fake" or eleven_present,
            "audio_music": config.mode == "fake" or eleven_present,
            "audio_sound_effects": config.mode == "fake" or eleven_present,
        },
        "errors": errors,
        "live_verification_executed": False,
        "note": "Configuration presence does not prove provider connectivity.",
    }


def main() -> int:
    try:
        report = provider_readiness()
    except ValueError as error:
        report = {"mode": "invalid", "ready": False, "errors": [str(error)], "live_verification_executed": False}
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("ready") else 1


if __name__ == "__main__":
    sys.exit(main())
