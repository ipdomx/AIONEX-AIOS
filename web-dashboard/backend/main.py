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
from app.websocket.manager import websocket_manager
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
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


def _preserve_public_api_cache(request: Request, response: Response) -> bool:
    """Preserve explicit public caching only for the read-only portal contract."""

    cache_control = response.headers.get("Cache-Control", "").strip().lower()
    return (
        request.method in {"GET", "HEAD"}
        and response.status_code in {200, 304}
        and _PUBLIC_CACHEABLE_API.fullmatch(request.url.path) is not None
        and cache_control.startswith("public")
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup_event()
    yield
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
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def production_security_boundary(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or request.headers.get("x-correlation-id") or secrets.token_hex(16)
    if _production():
        allowed = _allowed_hosts()
        host = request.headers.get("host", "").split(":", 1)[0].lower()
        if not allowed:
            logger.error("AIOS_ALLOWED_HOSTS is required in production")
            return JSONResponse(status_code=503, content={"detail": "Production host policy is not configured"})
        if host not in allowed:
            logger.warning("Rejected untrusted host", host=host, request_id=request_id)
            return JSONResponse(status_code=421, content={"detail": "Untrusted host"})
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self), payment=(), usb=()"
    if request.url.path.startswith("/api/") and not _preserve_public_api_cache(
        request, response
    ):
        response.headers["Cache-Control"] = "no-store"
    if "server" in response.headers:
        del response.headers["server"]
    return response


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
    await websocket_manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket_manager.broadcast(f"Client {client_id}: {data}")
    except WebSocketDisconnect:
        websocket_manager.disconnect(client_id)
    except Exception:
        logger.exception("WebSocket failure", client_id=client_id)
        websocket_manager.disconnect(client_id)


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
