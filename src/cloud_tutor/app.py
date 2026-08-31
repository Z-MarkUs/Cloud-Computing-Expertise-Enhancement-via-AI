"""FastAPI application and stable operational/API contracts."""

from __future__ import annotations

import inspect
import logging
import re
import secrets
import time
import uuid
from collections.abc import AsyncIterator, MutableMapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint

from cloud_tutor import __version__
from cloud_tutor.config import Settings, get_settings
from cloud_tutor.errors import CloudTutorError
from cloud_tutor.metrics import ServiceMetrics
from cloud_tutor.models import (
    ChatRequest,
    ChatResponse,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    PublicConfig,
)
from cloud_tutor.providers.factory import build_service
from cloud_tutor.service import RagService

LOGGER = logging.getLogger("cloud_tutor")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class SPAStaticFiles(StaticFiles):
    """Serve an SPA index for non-file routes while preserving real 404s for assets."""

    async def get_response(self, path: str, scope: MutableMapping[str, Any]) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as error:
            if error.status_code == 404 and "." not in Path(path).name:
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404 and "." not in Path(path).name:
            return await super().get_response("index.html", scope)
        return response


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=_request_id(request),
            details=details,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers=headers,
    )


def _validation_details(error: RequestValidationError) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for item in error.errors():
        location = ".".join(str(part) for part in item.get("loc", ()) if part != "body")
        details.append(
            {
                "field": location or "request",
                "message": str(item.get("msg", "Invalid value")),
            }
        )
    return details


async def _close_service(service: RagService | object) -> None:
    closed: set[int] = set()
    providers = [
        provider
        for provider in (
            getattr(service, "retriever", None),
            getattr(service, "generator", None),
            service,
        )
        if provider is not None
    ]
    for provider in providers:
        if id(provider) in closed:
            continue
        closed.add(id(provider))
        close = getattr(provider, "aclose", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result


def create_app(
    settings: Settings | None = None,
    service: RagService | None = None,
) -> FastAPI:
    """Create an isolated app instance for production or integration tests."""
    runtime_settings = settings or get_settings()
    metrics = ServiceMetrics()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = runtime_settings
        application.state.metrics = metrics
        application.state.service = service or build_service(runtime_settings)
        yield
        await _close_service(application.state.service)

    application = FastAPI(
        title=runtime_settings.app_name,
        version=__version__,
        description=(
            "A source-grounded cloud tutor with a credential-free deterministic demo "
            "mode and an optional Azure RAG provider."
        ),
        lifespan=lifespan,
        docs_url="/docs" if runtime_settings.environment != "production" else None,
        redoc_url=None,
        openapi_url=("/openapi.json" if runtime_settings.environment != "production" else None),
    )

    origins = runtime_settings.allowed_origins()
    if origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )

    @application.middleware("http")
    async def observe_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied_id = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            supplied_id if REQUEST_ID_PATTERN.fullmatch(supplied_id) else str(uuid.uuid4())
        )
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        finally:
            route_object = request.scope.get("route")
            route = getattr(route_object, "path", request.url.path)
            duration = time.perf_counter() - started
            metrics.http_requests.labels(request.method, route, str(status_code)).inc()
            metrics.http_duration.labels(request.method, route).observe(duration)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-Frame-Options"] = "DENY"
        if runtime_settings.environment == "production":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; base-uri 'none'; connect-src 'self'; "
                "font-src 'self'; frame-ancestors 'none'; img-src 'self' data:; "
                "object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'"
            )
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            request=request,
            status_code=422,
            code="validation_error",
            message="The request did not match the API contract.",
            details=_validation_details(error),
        )

    @application.exception_handler(CloudTutorError)
    async def domain_error_handler(request: Request, error: CloudTutorError) -> JSONResponse:
        LOGGER.warning(
            "Expected application failure request_id=%s code=%s",
            _request_id(request),
            error.code,
        )
        return _error_response(
            request=request,
            status_code=error.status_code,
            code=error.code,
            message=error.public_message,
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
        detail = error.detail if isinstance(error.detail, str) else "The request failed."
        code = {
            401: "authentication_required",
            404: "not_found",
            413: "request_too_large",
            422: "validation_error",
        }.get(error.status_code, "http_error")
        return _error_response(
            request=request,
            status_code=error.status_code,
            code=code,
            message=detail,
            headers=dict(error.headers) if error.headers is not None else None,
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, error: Exception) -> JSONResponse:
        LOGGER.exception(
            "Unhandled request failure request_id=%s",
            _request_id(request),
            exc_info=error,
        )
        return _error_response(
            request=request,
            status_code=500,
            code="internal_error",
            message="An unexpected error occurred while processing the request.",
        )

    def authorize(api_key: str | None) -> None:
        expected = runtime_settings.api_key
        if expected is None:
            return
        supplied = api_key or ""
        expected_value = (
            expected.get_secret_value() if hasattr(expected, "get_secret_value") else str(expected)
        )
        if not secrets.compare_digest(expected_value, supplied):
            raise HTTPException(
                status_code=401,
                detail="A valid API key is required.",
                headers={"WWW-Authenticate": "ApiKey"},
            )

    @application.get("/api/config", response_model=PublicConfig, tags=["configuration"])
    async def public_config(request: Request) -> PublicConfig:
        retrieval_strategy = str(request.app.state.service.retriever.strategy)
        return PublicConfig(
            app_name=runtime_settings.app_name,
            version=__version__,
            mode=runtime_settings.mode,
            environment=runtime_settings.environment,
            model=(
                "deterministic extractive demo"
                if runtime_settings.mode == "demo"
                else "Azure OpenAI"
            ),
            retrieval_strategy=retrieval_strategy,
            default_top_k=runtime_settings.default_top_k,
            max_top_k=runtime_settings.max_top_k,
            max_message_chars=runtime_settings.max_message_chars,
            max_history_turns=runtime_settings.max_history_turns,
            authentication_required=runtime_settings.api_key is not None,
            features=[
                "citations",
                "multi-turn-context",
                "retrieval-trace",
                "offline-demo",
                "azure-provider",
            ],
        )

    def live_response() -> HealthResponse:
        return HealthResponse(
            status="ok",
            mode=runtime_settings.mode,
            version=__version__,
            checks={"process": "running"},
        )

    @application.get("/healthz", response_model=HealthResponse, tags=["health"])
    async def healthz() -> HealthResponse:
        return live_response()

    @application.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def health_live() -> HealthResponse:
        return live_response()

    @application.get(
        "/health/ready",
        response_model=HealthResponse,
        responses={503: {"model": HealthResponse}},
        tags=["health"],
    )
    async def health_ready(request: Request) -> HealthResponse | JSONResponse:
        ready, checks = await request.app.state.service.readiness()
        payload = HealthResponse(
            status="ready" if ready else "not_ready",
            mode=runtime_settings.mode,
            version=__version__,
            checks=checks,
        )
        if not ready:
            return JSONResponse(status_code=503, content=payload.model_dump(mode="json"))
        return payload

    @application.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        return Response(
            content=generate_latest(metrics.registry),
            media_type=CONTENT_TYPE_LATEST,
        )

    @application.post(
        "/api/chat",
        response_model=ChatResponse,
        responses={
            401: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
        tags=["chat"],
    )
    async def chat(
        request: Request,
        payload: ChatRequest,
        x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> ChatResponse:
        authorize(x_api_key)
        if len(payload.message) > runtime_settings.max_message_chars:
            raise HTTPException(
                status_code=413,
                detail=f"message exceeds {runtime_settings.max_message_chars} characters",
            )
        if len(payload.history) > runtime_settings.max_history_turns:
            raise HTTPException(
                status_code=422,
                detail=f"history exceeds {runtime_settings.max_history_turns} turns",
            )
        if payload.top_k and payload.top_k > runtime_settings.max_top_k:
            raise HTTPException(
                status_code=422,
                detail=f"top_k cannot exceed {runtime_settings.max_top_k}",
            )

        try:
            rag_service = cast(RagService, request.app.state.service)
            result = await rag_service.chat(payload, _request_id(request))
        except Exception:
            metrics.chat_requests.labels(runtime_settings.mode, "error").inc()
            raise
        metrics.chat_requests.labels(runtime_settings.mode, "success").inc()
        metrics.retrieval_confidence.labels(runtime_settings.mode).observe(result.trace.confidence)
        return result

    frontend_directory = runtime_settings.frontend_dist_dir
    if frontend_directory is not None and frontend_directory.is_dir():
        application.mount(
            "/",
            SPAStaticFiles(directory=frontend_directory, html=True),
            name="frontend",
        )

    return application


app = create_app()
