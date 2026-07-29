"""
AIONEX AIOS — Enterprise AI Operating System
FastAPI Backend Application
"""

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

# Setup logging
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    await startup_event()
    yield
    await shutdown_event()


# Create FastAPI application
app = FastAPI(
    title="AIONEX AIOS API",
    description="Enterprise AI Operating System — Backend API",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# API Routes
app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "aionex-aios-api",
        "version": "1.0.0",
        "environment": settings.ENVIRONMENT,
    }


@app.get("/ready", tags=["System"])
async def readiness_check(response: Response):
    """Probe the dependencies required by authenticated dashboard requests."""
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
    return {
        "status": "ready" if ready else "not_ready",
        "database": database_status,
        "redis": redis_status,
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "code": "INTERNAL_ERROR"},
    )


# WebSocket endpoint
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket endpoint for real-time updates."""
    await websocket_manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket_manager.broadcast(f"Client {client_id}: {data}")
    except WebSocketDisconnect:
        websocket_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        websocket_manager.disconnect(client_id)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        workers=1 if settings.DEBUG else settings.WORKERS,
        log_level="info" if settings.DEBUG else "warning",
    )
