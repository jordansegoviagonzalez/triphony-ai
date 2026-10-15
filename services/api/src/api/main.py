from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
import redis
import os
from sqlalchemy import text

from api.routes import router
from api.db import engine
from api.settings import settings
import logging

from triphony_lib.observability import json_log, metric_inc, reset_correlation_id, set_correlation_id, span


def create_app() -> FastAPI:
    app = FastAPI(title="AI Art Studio API", version="1.0.0")

    origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]

    # Dev-friendly CORS; tighten in production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", settings.csrf_header_name, "Range"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts + ["testserver"])

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 2 * 1024 * 1024:
            return JSONResponse(status_code=413, content={"detail": "request body too large"})
        request.state.correlation_id = request.headers.get("X-Correlation-ID") or __import__("uuid").uuid4().hex
        correlation_token = set_correlation_id(request.state.correlation_id)
        try:
            with span("http.request", method=request.method, route=str(request.url.path), correlation_id=request.state.correlation_id):
                response = await call_next(request)
        finally:
            reset_correlation_id(correlation_token)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        metric_inc("triphony.http.requests", method=request.method, route=str(request.url.path), status=str(response.status_code))
        json_log(logging.getLogger("triphony.api"), logging.INFO, "http_request", method=request.method, route=str(request.url.path), status=response.status_code, correlation_id=request.state.correlation_id)
        return response

    app.include_router(router)

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/ready")
    def readiness() -> dict:
        checks: dict[str, str] = {"storage": "configured", "provider_live_verification": "not_performed"}
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "unavailable"
        try:
            redis.Redis.from_url(os.getenv("REDIS_URL") or settings.redis_url).ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "unavailable"
        ready = all(checks[key] == "ok" for key in ("database", "redis"))
        checks["provider_configuration"] = "fake_mode" if settings.provider_mode in {"fake", "mock"} else "configured"
        return {"status": "ready" if ready else "not_ready", "checks": checks}

    return app


app = create_app()
