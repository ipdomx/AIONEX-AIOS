"""Redis configuration."""

import redis.asyncio as aioredis
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
redis_client: aioredis.Redis | None = None


async def init_redis():
    """Initialize Redis connection."""
    global redis_client
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        max_connections=settings.REDIS_POOL_SIZE,
    )
    await redis_client.ping()
    logger.info("Redis connected")


async def close_redis():
    """Close Redis connection."""
    global redis_client
    if redis_client:
        await redis_client.close()
        logger.info("Redis disconnected")


async def get_redis() -> aioredis.Redis:
    """Get Redis client."""
    if redis_client is None:
        raise RuntimeError("Redis not initialized")
    return redis_client
