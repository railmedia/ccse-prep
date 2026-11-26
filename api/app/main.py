from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from app import __version__, db
from app.logging import configure_logging, request_id_var
from app.metrics import metrics
from app.routers import exams, health, questions, tutor
from app.settings import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    logger.info("api.starting", extra={"env": settings.env, "version": __version__})
    yield
    await db.dispose()
    logger.info("api.stopped")


def create_app() -> FastAPI:
    configure_logging(settings.log_level)

    app = FastAPI(
        title="CCSE Prep API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(
                    "request.failed",
                    extra={
                        "http_method": request.method,
                        "http_path": request.url.path,
                        "http_status": 500,
                    },
                )
                return JSONResponse(
                    {"detail": "internal error", "request_id": request_id},
                    status_code=500,
                    headers={"X-Request-ID": request_id},
                )

            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            metrics.inc(
                "ccse_requests_total",
                method=request.method,
                status=str(response.status_code),
                path=request.url.path,
            )
            metrics.observe("ccse_request_duration_ms", duration_ms, path=request.url.path)
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "request",
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_status": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response
        finally:
            request_id_var.reset(token)

    app.include_router(health.router)
    app.include_router(exams.router)
    app.include_router(questions.router)
    app.include_router(tutor.router)

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> PlainTextResponse:
        return PlainTextResponse(metrics.render())

    return app


app = create_app()
