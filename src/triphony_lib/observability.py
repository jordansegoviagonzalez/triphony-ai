"""Vendor-neutral, no-export-by-default tracing and safe structured fields."""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import re
import time
from typing import Any, Iterator

try:
    from opentelemetry import trace
except ImportError:  # pragma: no cover - dependency is optional for local libraries
    trace = None  # type: ignore[assignment]


_SENSITIVE = re.compile(r"(authorization|cookie|token|secret|password|api[_-]?key|signed[_-]?url)", re.I)
_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("triphony_correlation_id", default=None)

try:
    from opentelemetry import metrics
except ImportError:  # pragma: no cover - dependency is optional for local libraries
    metrics = None  # type: ignore[assignment]

_meter = metrics.get_meter("triphony") if metrics is not None else None
_counters: dict[str, Any] = {}
_histograms: dict[str, Any] = {}


def safe_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {key: "[REDACTED]" if _SENSITIVE.search(key) else value for key, value in fields.items()}


def json_log(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    enriched = {"message": message, **safe_fields(fields)}
    if _correlation_id.get() and "correlation_id" not in enriched:
        enriched["correlation_id"] = _correlation_id.get()
    logger.log(level, json.dumps(enriched, sort_keys=True, default=str))


def set_correlation_id(value: str | None) -> contextvars.Token[str | None]:
    return _correlation_id.set(value)


def reset_correlation_id(token: contextvars.Token[str | None]) -> None:
    _correlation_id.reset(token)


def clear_correlation_id() -> None:
    _correlation_id.set(None)


def current_correlation_id() -> str | None:
    return _correlation_id.get()


def metric_inc(name: str, value: int = 1, **attributes: Any) -> None:
    if _meter is None:
        return
    counter = _counters.setdefault(name, _meter.create_counter(name))
    counter.add(value, safe_fields(attributes))


def metric_observe(name: str, value: float, **attributes: Any) -> None:
    if _meter is None:
        return
    histogram = _histograms.setdefault(name, _meter.create_histogram(name))
    histogram.record(value, safe_fields(attributes))


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    if trace is None:
        started = time.perf_counter()
        try:
            yield None
        finally:
            metric_observe("triphony.span.duration_ms", (time.perf_counter() - started) * 1000, span=name)
        return
    tracer = trace.get_tracer("triphony")
    enriched = dict(attributes)
    if _correlation_id.get() and "correlation_id" not in enriched:
        enriched["correlation_id"] = _correlation_id.get()
    started = time.perf_counter()
    try:
        with tracer.start_as_current_span(name, attributes=safe_fields(enriched)) as current:
            yield current
    finally:
        metric_observe("triphony.span.duration_ms", (time.perf_counter() - started) * 1000, span=name)
