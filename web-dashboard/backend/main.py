"""
AIONEX AIOS — Enterprise AI Operating System
FastAPI Backend Application
"""

import os
import re
import secrets
from contextlib import asynccontextmanager

import uvicorn
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.events import shutdown_event, startup_event
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.redis import get_redis
from app.services.conversation_worker import conversation_worker
from app.services.host_maintenance_media_http import close_media_file_admission
from fastapi import FastAPI, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from sqlalchemy import text

setup_logging()
logger = get_logger(__name__)


def _production() -> bool:
    return settings.ENVIRONMENT.strip().lower() == "production" and not settings.DEBUG


def _allowed_hosts() -> set[str]:
    configured = os.getenv("AIOS_ALLOWED_HOSTS", "")
    return {item.strip().lower() for item in configured.split(",") if item.strip()}


_PUBLIC_CACHEABLE_API = re.compile(
    r"^/api/v1/portal/(?:published|assets/[0-9a-f]{32})$"
)


def _preserve_public_api_cache_values(
    method: str, path: str, status_code: int, cache_control: str,
) -> bool:
    """Fail-closed portal caching decision shared by ASGI and tests."""
    return (
        method in {"GET", "HEAD"}
        and status_code in {200, 304}
        and _PUBLIC_CACHEABLE_API.fullmatch(path) is not None
        and cache_control.strip().lower().startswith("public")
    )


def _preserve_public_api_cache(request: Request, response: Response) -> bool:
    """Preserve the public cache contract for callers of the existing helper."""
    return _preserve_public_api_cache_values(
        request.method,
        request.url.path,
        response.status_code,
        response.headers.get("Cache-Control", ""),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup_event()
    await conversation_worker.start()
    try:
        yield
    finally:
        await conversation_worker.stop()
        try:
            await close_media_file_admission()
        finally:
            await shutdown_event()


app = FastAPI(
    title="AIONEX AIOS API",
    description="Enterprise AI Operating System — Backend API",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Correlation-ID", "X-CSRF-Token"],
    expose_headers=["Content-Disposition"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


class ProductionSecurityASGIMiddleware:
    """Enforce production hosts and headers without BaseHTTPMiddleware tasks.

    The ASGI send hook preserves streaming behavior and security headers for
    successful and error responses; WebSockets and lifespan are untouched.
    """

    def __init__(self, downstream):
        self.downstream = downstream

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.downstream(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = (
            headers.get("x-request-id")
            or headers.get("x-correlation-id")
            or secrets.token_hex(16)
        )
        if _production():
            allowed = _allowed_hosts()
            host = headers.get("host", "").split(":", 1)[0].lower()
            if not allowed:
                logger.error("AIOS_ALLOWED_HOSTS is required in production")
                response = JSONResponse(
                    status_code=503,
                    content={"detail": "Production host policy is not configured"},
                )
                await response(scope, receive, send)
                return
            if host not in allowed:
                logger.warning("Rejected untrusted host", host=host, request_id=request_id)
                response = JSONResponse(
                    status_code=421, content={"detail": "Untrusted host"}
                )
                await response(scope, receive, send)
                return

        async def secure_send(message):
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Request-ID"] = request_id
                response_headers["X-Content-Type-Options"] = "nosniff"
                response_headers["X-Frame-Options"] = "DENY"
                response_headers["Referrer-Policy"] = "no-referrer"
                response_headers["Permissions-Policy"] = (
                    "camera=(), geolocation=(), microphone=(self), payment=(), usb=()"
                )
                if (
                    scope["path"].startswith("/api/")
                    and not _preserve_public_api_cache_values(
                        scope["method"],
                        scope["path"],
                        message["status"],
                        response_headers.get("Cache-Control", ""),
                    )
                ):
                    response_headers["Cache-Control"] = "no-store"
                if "server" in response_headers:
                    del response_headers["server"]
            await send(message)

        await self.downstream(scope, receive, secure_send)


app.add_middleware(ProductionSecurityASGIMiddleware)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "aionex-aios-api", "version": "1.0.0"}


@app.get("/ready", tags=["System"])
async def readiness_check(response: Response):
    database_status = "unavailable"
    redis_status = "unavailable"
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        database_status = "connected"
    except Exception:
        logger.exception("Readiness database probe failed")
    try:
        redis = await get_redis()
        if await redis.ping():
            redis_status = "connected"
    except Exception:
        logger.exception("Readiness Redis probe failed")

    ready = database_status == "connected" and redis_status == "connected"
    response.status_code = 200 if ready else 503
    return {"status": "ready" if ready else "not_ready"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled request exception", exc_info=True, path=request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "code": "INTERNAL_ERROR"})


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    # Preserve the existing proxy denial at the application boundary as well.
    # Client-chosen identifiers must never enable unauthenticated global fanout.
    del client_id
    await websocket.close(code=4403)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        workers=1 if settings.DEBUG else settings.WORKERS,
        log_level="info" if settings.DEBUG else "warning",
        server_header=False,
        date_header=False,
    )
