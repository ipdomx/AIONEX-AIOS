"""Redis configuration."""

import redis.asyncio as aioredis
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
redis_client: aioredis.Redis | None = None


async def _close_client(client: aioredis.Redis) -> None:
    """Close Redis across redis-py 5.x and newer client APIs."""
    closer = getattr(client, "aclose", None)
    if closer is None:
        closer = client.close
    await closer()


async def init_redis():
    """Initialize one event-loop-owned Redis client."""
    global redis_client
    if redis_client is not None:
        await _close_client(redis_client)
        redis_client = None
    client = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        max_connections=settings.REDIS_POOL_SIZE,
    )
    try:
        await client.ping()
    except BaseException:
        await _close_client(client)
        raise
    redis_client = client
    logger.info("Redis connected")


async def close_redis():
    """Close Redis and clear the global reference before its event loop exits."""
    global redis_client
    client = redis_client
    redis_client = None
    if client is not None:
        await _close_client(client)
        logger.info("Redis disconnected")


async def get_redis() -> aioredis.Redis:
    """Get Redis client."""
    if redis_client is None:
        raise RuntimeError("Redis not initialized")
    return redis_client
