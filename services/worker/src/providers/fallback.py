"""Policy-controlled active/passive Veo -> Runway visual fallback."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from providers.errors import ProviderError, ProviderErrorKind
from triphony_lib.agents import VisualAgent
from triphony_lib.domain import VisualAgentRequest, VisualAgentResult


ELIGIBLE_FALLBACK_ERRORS = frozenset({
    ProviderErrorKind.unavailable, ProviderErrorKind.retryable, ProviderErrorKind.timeout,
})


def fallback_allowed(error: ProviderError, *, circuit_open: bool = False) -> bool:
    return circuit_open or error.kind in ELIGIBLE_FALLBACK_ERRORS


@dataclass
class ActivePassiveVisualAgent(VisualAgent):
    primary: VisualAgent
    fallback: VisualAgent
    fallback_enabled: bool
    circuit_open: Callable[[], bool] = lambda: False
    on_fallback: Callable[[str], None] = lambda _reason: None
    on_primary_success: Callable[[], None] = lambda: None
    on_primary_failure: Callable[[ProviderError], None] = lambda _error: None
    _fallback_results: dict[str, VisualAgentResult] = field(default_factory=dict, init=False, repr=False)

    @property
    def capabilities(self):
        return self.primary.capabilities

    def generate(self, request: VisualAgentRequest) -> VisualAgentResult:
        cached = self._fallback_results.get(request.idempotency.key)
        if cached is not None:
            return cached

        def use_fallback(reason: str) -> VisualAgentResult:
            self.on_fallback(reason)
            result = self.fallback.generate(request)
            result = result.model_copy(update={
                "job": result.job.model_copy(update={
                    "job_id": request.idempotency.key,
                    "provenance": result.job.provenance.model_copy(update={
                        "metadata": {**result.job.provenance.metadata, "fallback_from": "google-vertex-ai", "fallback_reason": reason}
                    }),
                })
            })
            self._fallback_results[request.idempotency.key] = result
            return result

        if self.fallback_enabled and self.circuit_open():
            return use_fallback("veo_circuit_open")
        try:
            result = self.primary.generate(request)
            self.on_primary_success()
            return result
        except ProviderError as error:
            self.on_primary_failure(error)
            if not self.fallback_enabled or not fallback_allowed(error, circuit_open=self.circuit_open()):
                raise
            return use_fallback(error.kind.value)

    def cancel(self, job_id: str) -> None:
        first_error: Exception | None = None
        for agent in (self.primary, self.fallback):
            try:
                agent.cancel(job_id)
            except Exception as error:
                first_error = first_error or error
        if first_error is not None:
            raise first_error
