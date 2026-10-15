"""Provider-neutral typed interfaces for Triphony's four logical agents."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from triphony_lib.domain import (
    AgentCapabilities,
    AudioAgentRequest,
    AudioAgentResult,
    NarrativeDirectorRequest,
    NarrativeDirectorResult,
    QAAgentRequest,
    QAAgentResult,
    VisualAgentRequest,
    VisualAgentResult,
)


class AgentError(Exception):
    """Base error for provider-neutral agent execution."""


class RetryableAgentError(AgentError):
    """An operation may be retried with the same idempotency key."""


class NonRetryableAgentError(AgentError):
    """An operation must be corrected or rejected instead of retried."""


class AgentCancelledError(AgentError):
    """An operation was cancelled before completion."""


class IdempotencyConflictError(NonRetryableAgentError):
    """An idempotency key was reused for a different request."""


@runtime_checkable
class NarrativeDirector(Protocol):
    capabilities: AgentCapabilities

    def plan(self, request: NarrativeDirectorRequest) -> NarrativeDirectorResult:
        """Create a validated plan from a user request."""

    def cancel(self, job_id: str) -> None:
        """Cancel a queued or running planning job."""


@runtime_checkable
class VisualAgent(Protocol):
    capabilities: AgentCapabilities

    def generate(self, request: VisualAgentRequest) -> VisualAgentResult:
        """Create provider-neutral visual job and asset metadata."""

    def cancel(self, job_id: str) -> None:
        """Cancel a queued or running visual job."""


@runtime_checkable
class AudioAgent(Protocol):
    capabilities: AgentCapabilities

    def generate(self, request: AudioAgentRequest) -> AudioAgentResult:
        """Create provider-neutral audio job and asset metadata."""

    def cancel(self, job_id: str) -> None:
        """Cancel a queued or running audio job."""


@runtime_checkable
class QAAgent(Protocol):
    capabilities: AgentCapabilities

    def evaluate(self, request: QAAgentRequest) -> QAAgentResult:
        """Evaluate plan and generated asset metadata."""

    def cancel(self, job_id: str) -> None:
        """Cancel a queued or running QA job."""
