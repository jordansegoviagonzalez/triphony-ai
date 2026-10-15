"""Gemini Narrative Director and multimodal QA adapters."""

from __future__ import annotations

import json
from typing import Any, Callable

from providers.common import digest, provider_job, response_text
from providers.config import ProviderConfig
from providers.errors import ProviderError, ProviderErrorKind, translate_provider_exception
from providers.vertex import create_vertex_client
from triphony_lib.agents import NarrativeDirector, QAAgent
from triphony_lib.domain import (
    AgentCapabilities,
    AgentType,
    AssetVersion,
    MediaType,
    NarrativeDirectorRequest,
    NarrativeDirectorResult,
    ProviderJobStatus,
    QAAgentRequest,
    QAAgentResult,
    QAEvaluation,
    ScenePlan,
)


def _structured_config(schema: dict[str, Any]) -> dict[str, Any]:
    return {"response_mime_type": "application/json", "response_json_schema": schema}


def _parse_model(response: Any, model_type: type[Any]) -> Any:
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        return model_type.model_validate(parsed)
    try:
        return model_type.model_validate(json.loads(response_text(response)))
    except Exception as error:
        raise ProviderError(ProviderErrorKind.malformed, "provider returned invalid structured JSON") from error


def _has_safety_block(response: Any) -> bool:
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is None and isinstance(response, dict):
        feedback = response.get("prompt_feedback")
    if feedback is None:
        return False
    block_reason = getattr(feedback, "block_reason", None)
    if block_reason is None and isinstance(feedback, dict):
        block_reason = feedback.get("block_reason")
    return bool(block_reason and str(block_reason).lower() not in {"none", "unspecified"})


class GeminiNarrativeDirector(NarrativeDirector):
    capabilities = AgentCapabilities(
        agent_type=AgentType.narrative_director,
        provider_name="google-vertex-ai",
        supported_media_types=[MediaType.narrative],
        asynchronous_jobs=False,
        cancellation_supported=False,
        deterministic=False,
    )

    def __init__(self, config: ProviderConfig, client_factory: Callable[[], Any] | None = None) -> None:
        self.config = config
        self._client_factory = client_factory or (lambda: create_vertex_client(config))
        self._client: Any | None = None
        self._results: dict[str, tuple[str, NarrativeDirectorResult]] = {}

    def _client_or_create(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def plan(self, request: NarrativeDirectorRequest) -> NarrativeDirectorResult:
        fingerprint = digest(request.model_dump(mode="json"))
        cached = self._results.get(request.idempotency.key)
        if cached:
            if cached[0] != fingerprint:
                raise ProviderError(ProviderErrorKind.invalid_request, "idempotency key was reused for a different request")
            return cached[1]
        prompt = (
            "You are Triphony's Narrative Director. Create a cinematic short-form scene plan. "
            "Return only JSON matching the supplied schema. Do not describe or request a 3D environment, "
            "interactive walk-around, or unsupported capability. Keep shot timing ordered, non-overlapping, "
            f"and within the requested output specifications. User prompt: {request.user_prompt}\n"
            f"Scene ID: {request.scene_id}\nConstraints: {json.dumps(request.constraints, sort_keys=True)}"
        )
        try:
            response = self._client_or_create().models.generate_content(
                model=self.config.gemini_model,
                contents=prompt,
                config=_structured_config(ScenePlan.model_json_schema()),
            )
            if _has_safety_block(response):
                raise ProviderError(ProviderErrorKind.safety, "provider rejected the narrative request for safety reasons")
            plan = _parse_model(response, ScenePlan)
            if plan.scene_id != request.scene_id:
                raise ProviderError(ProviderErrorKind.malformed, "provider returned a plan for the wrong scene")
            requested_specs = {(item.media_type, item.mime_type) for item in request.output_requirements}
            returned_specs = {(item.media_type, item.mime_type) for item in plan.output_requirements}
            if not requested_specs.issubset(returned_specs):
                raise ProviderError(ProviderErrorKind.malformed, "provider omitted a requested output specification")
            job = provider_job(
                job_id=f"vertex-gemini-{digest(request.idempotency.key)[:20]}",
                scene_id=request.scene_id,
                agent_type=AgentType.narrative_director,
                media_type=MediaType.narrative,
                idempotency=request.idempotency,
                provider="google-vertex-ai",
                model=self.config.gemini_model,
                status=ProviderJobStatus.succeeded,
            )
            result = NarrativeDirectorResult(job=job, plan=plan)
            self._results[request.idempotency.key] = (fingerprint, result)
            return result
        except ProviderError:
            raise
        except Exception as error:
            raise translate_provider_exception(error) from error

    def cancel(self, job_id: str) -> None:
        del job_id


class GeminiQAAgent(QAAgent):
    capabilities = AgentCapabilities(
        agent_type=AgentType.qa,
        provider_name="google-vertex-ai",
        supported_media_types=[MediaType.video, MediaType.audio, MediaType.narrative],
        asynchronous_jobs=False,
        cancellation_supported=False,
        deterministic=False,
    )

    def __init__(self, config: ProviderConfig, client_factory: Callable[[], Any] | None = None) -> None:
        self.config = config
        self._client_factory = client_factory or (lambda: create_vertex_client(config))
        self._client: Any | None = None
        self._results: dict[str, tuple[str, QAAgentResult]] = {}

    def _client_or_create(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def evaluate(self, request: QAAgentRequest) -> QAAgentResult:
        fingerprint = digest(request.model_dump(mode="json"))
        cached = self._results.get(request.idempotency.key)
        if cached:
            if cached[0] != fingerprint:
                raise ProviderError(ProviderErrorKind.invalid_request, "idempotency key was reused for a different request")
            return cached[1]
        asset_metadata = [
            {
                "asset_version_id": asset.asset_version_id,
                "media_type": asset.media_type.value,
                "artifact_uri": asset.artifact_uri,
                "provenance": asset.provenance.model_dump(mode="json"),
            }
            for asset in request.assets
        ]
        prompt = (
            "You are Triphony's multimodal QA Agent. Evaluate the approved cinematic scene plan and the "
            "provider-neutral generated asset metadata for visual, narrative, audio, and cross-modal adherence. "
            "Return only JSON matching the schema. Recommend an action; do not regenerate anything.\n"
            f"Scene plan: {request.plan.model_dump_json()}\nAssets: {json.dumps(asset_metadata, sort_keys=True)}"
        )
        try:
            response = self._client_or_create().models.generate_content(
                model=self.config.gemini_model,
                contents=prompt,
                config=_structured_config(QAEvaluation.model_json_schema()),
            )
            if _has_safety_block(response):
                raise ProviderError(ProviderErrorKind.safety, "provider rejected the QA request for safety reasons")
            evaluation = _parse_model(response, QAEvaluation)
            expected_ids = {asset.asset_version_id for asset in request.assets}
            if evaluation.scene_id != request.plan.scene_id or set(evaluation.evaluated_asset_version_ids) != expected_ids:
                raise ProviderError(ProviderErrorKind.malformed, "provider returned QA for the wrong scene or assets")
            known_shots = {shot.shot_id for shot in request.plan.shots}
            if any(finding.shot_id and finding.shot_id not in known_shots for finding in evaluation.findings):
                raise ProviderError(ProviderErrorKind.malformed, "provider returned a finding for an unknown shot")
            job = provider_job(
                job_id=f"vertex-gemini-qa-{digest(request.idempotency.key)[:20]}",
                scene_id=request.plan.scene_id,
                agent_type=AgentType.qa,
                media_type=MediaType.narrative,
                idempotency=request.idempotency,
                provider="google-vertex-ai",
                model=self.config.gemini_model,
                status=ProviderJobStatus.succeeded,
            )
            result = QAAgentResult(job=job, evaluation=evaluation)
            self._results[request.idempotency.key] = (fingerprint, result)
            return result
        except ProviderError:
            raise
        except Exception as error:
            raise translate_provider_exception(error) from error

    def cancel(self, job_id: str) -> None:
        del job_id

