"""FastAPI application factory and centralized error handling."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.auth.presentation.router import router as auth_router
from app.bootstrap.container import ContainerFactory, build_container
from app.bootstrap.lifespan import create_lifespan
from app.core.config import Settings, get_settings
from app.core.errors import ApplicationError
from app.core.logging import configure_logging
from app.presentation.health import router as health_router
from app.realtime.presentation.reports_ws import router as reports_realtime_router
from app.realtime.presentation.router import router as realtime_router
from app.reports.presentation.router import router as reports_router
from app.seismic.presentation.router import router as seismic_router

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    container_factory: ContainerFactory = build_container,
) -> FastAPI:
    """Build a fully wired application. Tests inject a fake container."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    app = FastAPI(
        title="HydroAlert API",
        description=(
            "INETER seismic events, community reports, and real-time "
            "emergency notifications via WebSocket."
        ),
        version=__version__,
        lifespan=create_lifespan(resolved_settings, container_factory),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    origins = resolved_settings.cors_origins
    allow_credentials = resolved_settings.cors_allow_credentials
    if "*" in origins and allow_credentials:
        logger.warning(
            "CORS wildcard is incompatible with credentials; disabling credentials",
            extra={"event": "cors_configuration_adjusted"},
        )
        allow_credentials = False

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    _register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(reports_router, prefix="/api/v1")
    app.include_router(seismic_router, prefix="/api/v1")
    # Also support routes without /api/v1 prefix for direct API_BASE_URL compatibility
    app.include_router(auth_router, include_in_schema=False)
    app.include_router(reports_router, include_in_schema=False)
    app.include_router(realtime_router)
    app.include_router(reports_realtime_router)

    @app.get("/", include_in_schema=False)
    async def liveness() -> dict[str, str]:
        """Liveness probe used by the Docker healthcheck."""
        return {"status": "ok", "service": "seismic-events-api", "version": __version__}

    return app


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def application_error_handler(
        request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        logger.warning(
            "application error",
            extra={
                "event": "application_error",
                "path": request.url.path,
                "error_code": exc.code,
                "status_code": exc.status_code,
            },
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                },
                "message": exc.message,
            },
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        # The auth contract documents 400 for a malformed body; report
        # creation keeps FastAPI's 422 for multipart validation.
        auth_request = request.url.path.endswith(
            ("/auth/register", "/auth/login")
        )
        if auth_request:
            msg = "The request body is invalid."
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "invalid_request",
                        "message": msg,
                        "details": jsonable_encoder(exc.errors()),
                    },
                    "message": msg,
                },
            )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": jsonable_encoder(exc.errors()),
                },
                "message": "Request validation error.",
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled application exception",
            extra={
                "event": "unhandled_exception",
                "path": request.url.path,
                "method": request.method,
            },
        )
        msg = "Internal server error"
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": msg,
                },
                "message": msg,
            },
        )
