"""Provider-neutral error normalization with safe operational details."""

from __future__ import annotations

from enum import Enum
from typing import Any

from triphony_lib.agents import AgentError
from triphony_lib.domain import FailureCategory, FailureInfo


class ProviderErrorKind(str, Enum):
    configuration = "configuration_error"
    authentication = "authentication_error"
    authorization = "authorization_error"
    quota = "quota_or_rate_limit"
    invalid_request = "invalid_provider_request"
    safety = "moderation_or_safety_rejection"
    unavailable = "provider_unavailable"
    timeout = "timeout"
    malformed = "malformed_provider_response"
    unsupported = "unsupported_capability"
    terminal = "terminal_generation_failure"
    retryable = "retryable_generation_failure"


class ProviderError(AgentError):
    def __init__(
        self,
        kind: ProviderErrorKind,
        message: str,
        *,
        provider_request_id: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.safe_message = message
        self.provider_request_id = provider_request_id
        self.retryable = retryable

    def failure_info(self) -> FailureInfo:
        category = FailureCategory.timeout if self.kind is ProviderErrorKind.timeout else FailureCategory.provider
        details = {"provider_request_id": self.provider_request_id} if self.provider_request_id else {}
        return FailureInfo(
            code=self.kind.value,
            message=self.safe_message,
            category=category,
            retryable=self.retryable,
            details=details,
        )


def _request_id(value: Any) -> str | None:
    candidate = getattr(value, "request_id", None) or getattr(value, "trace_id", None)
    if candidate is None and isinstance(getattr(value, "headers", None), dict):
        candidate = value.headers.get("request-id") or value.headers.get("x-trace-id")
    if isinstance(candidate, str) and 0 < len(candidate) <= 255:
        return candidate
    return None


def translate_provider_exception(error: BaseException) -> ProviderError:
    """Translate an SDK exception without copying its potentially sensitive text."""

    if isinstance(error, ProviderError):
        return error
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    status_text = str(status).lower() if status is not None else ""
    name = type(error).__name__.lower()
    request_id = _request_id(error)
    if isinstance(error, (TimeoutError,)) or "timeout" in name:
        return ProviderError(ProviderErrorKind.timeout, "provider request timed out", provider_request_id=request_id, retryable=True)
    if status in {401, 403} or "auth" in name or "permission" in name:
        kind = ProviderErrorKind.authentication if status == 401 or "auth" in name else ProviderErrorKind.authorization
        return ProviderError(kind, "provider authentication or authorization failed", provider_request_id=request_id)
    if status == 429 or "quota" in name or "rate" in name:
        return ProviderError(ProviderErrorKind.quota, "provider quota or rate limit was reached", provider_request_id=request_id, retryable=True)
    if "safety" in name or "moderation" in name or "blocked" in name or "policy" in name:
        return ProviderError(ProviderErrorKind.safety, "provider rejected the request for safety reasons", provider_request_id=request_id)
    if status in {400, 404, 422} or "invalid" in name or "badrequest" in name:
        return ProviderError(ProviderErrorKind.invalid_request, "provider rejected the request", provider_request_id=request_id)
    if status_text.startswith("5") or "unavailable" in name or "connection" in name:
        return ProviderError(ProviderErrorKind.unavailable, "provider is temporarily unavailable", provider_request_id=request_id, retryable=True)
    return ProviderError(ProviderErrorKind.terminal, "provider operation failed", provider_request_id=request_id)
