"""Application lifecycle events."""

from app.core.logging import get_logger
from app.core.config import settings
from app.db.database import init_db, close_db
from app.db.redis import init_redis, close_redis
from app.realtime.runtime import realtime_event_runtime

logger = get_logger(__name__)


async def startup_event():
    """Application startup handler."""
    logger.info("Starting AIONEX AIOS API", environment=settings.ENVIRONMENT)

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Initialize Redis
    await init_redis()
    logger.info("Redis initialized")

    await realtime_event_runtime.start()
    logger.info("Distributed realtime event runtime initialized")

    logger.info("AIONEX AIOS API started successfully")


async def shutdown_event():
    """Application shutdown handler."""
    logger.info("Shutting down AIONEX AIOS API")

    await realtime_event_runtime.stop()
    logger.info("Distributed realtime event runtime stopped")

    # Close database connections
    await close_db()
    logger.info("Database connections closed")

    # Close Redis connections
    await close_redis()
    logger.info("Redis connections closed")

    logger.info("AIONEX AIOS API shutdown complete")
