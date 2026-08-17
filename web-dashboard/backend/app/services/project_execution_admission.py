"""Distributed backpressure for durable project-execution submissions.

Workers and tests intentionally keep SQLAlchemy ``NullPool`` while production API
processes use a bounded connection pool. A burst of authenticated project submissions
still must be bounded before the project-execution route opens its request-scoped
database work. The guard has two layers:

* a small per-process semaphore bounds Redis acquisition loops;
* a Redis sorted-set lease is the cross-process/cross-replica admission authority.

Only opaque random lease IDs are stored in Redis. No tenant ID, prompt, project
payload, provider identifier, or credential enters the admission key.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator
from uuid import uuid4
from weakref import WeakKeyDictionary

from redis.exceptions import RedisError

from app.core.config import settings
from app.core.logging import get_logger
from app.db.redis import get_redis

logger = get_logger(__name__)


class ProjectExecutionAdmissionTimeout(RuntimeError):
    """The bounded admission window stayed saturated past its wait budget."""


class ProjectExecutionAdmissionUnavailable(RuntimeError):
    """Distributed admission could not be enforced safely."""


@dataclass(slots=True)
class _AdmissionState:
    semaphore: asyncio.BoundedSemaphore
    capacity: int
    active: int = 0
    waiting: int = 0
    peak_active: int = 0
    distributed_active: int = 0
    peak_distributed_active: int = 0
    distributed_enabled: int = 0


_STATES: WeakKeyDictionary[asyncio.AbstractEventLoop, _AdmissionState] = WeakKeyDictionary()

# Redis TIME is used so every API replica evaluates lease expiry against the same
# authority rather than relying on local host clock skew.
_ACQUIRE_SCRIPT = """
local now = redis.call('TIME')
local now_ms = (tonumber(now[1]) * 1000) + math.floor(tonumber(now[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms)
local current = redis.call('ZCARD', KEYS[1])
if current >= tonumber(ARGV[2]) then
  return 0
end
local expires_ms = now_ms + tonumber(ARGV[3])
redis.call('ZADD', KEYS[1], expires_ms, ARGV[1])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[3]) + 5000)
return 1
"""

_RELEASE_SCRIPT = """
return redis.call('ZREM', KEYS[1], ARGV[1])
"""


def _state() -> _AdmissionState:
    loop = asyncio.get_running_loop()
    capacity = int(settings.PROJECT_EXECUTION_ADMISSION_CONCURRENCY)
    state = _STATES.get(loop)
    if state is None or state.capacity != capacity:
        state = _AdmissionState(
            semaphore=asyncio.BoundedSemaphore(capacity),
            capacity=capacity,
        )
        _STATES[loop] = state
    return state


def _test_environment() -> bool:
    return settings.ENVIRONMENT.strip().lower() in {"test", "testing", "ci"}


async def _redis_client() -> Any | None:
    try:
        return await get_redis()
    except RuntimeError:
        if _test_environment():
            # Some focused endpoint tests construct a FastAPI app without running
            # the application lifespan. Local fallback is test-only; production
            # fails closed because cross-replica backpressure cannot be proven.
            return None
        raise ProjectExecutionAdmissionUnavailable(
            "distributed project admission is unavailable"
        )


async def _acquire_distributed(
    *,
    client: Any,
    key: str,
    token: str,
    deadline: float,
) -> None:
    loop = asyncio.get_running_loop()
    retry_seconds = max(
        0.005,
        float(settings.PROJECT_EXECUTION_ADMISSION_RETRY_MILLISECONDS) / 1000.0,
    )
    lease_ms = int(settings.PROJECT_EXECUTION_ADMISSION_LEASE_SECONDS) * 1000
    global_limit = int(settings.PROJECT_EXECUTION_ADMISSION_GLOBAL_LIMIT)
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise ProjectExecutionAdmissionTimeout(
                "project execution admission is temporarily saturated"
            )
        try:
            acquired = await client.eval(
                _ACQUIRE_SCRIPT,
                1,
                key,
                token,
                global_limit,
                lease_ms,
            )
        except RedisError as exc:
            raise ProjectExecutionAdmissionUnavailable(
                "distributed project admission is unavailable"
            ) from exc
        if int(acquired or 0) == 1:
            return
        await asyncio.sleep(min(retry_seconds, max(0.005, remaining)))


async def _release_distributed(*, client: Any, key: str, token: str) -> None:
    try:
        await client.eval(_RELEASE_SCRIPT, 1, key, token)
    except RedisError:
        # The sorted-set member has a bounded server-side lease and self-cleans.
        # Do not turn an already-durable user submission into a false failure solely
        # because best-effort admission cleanup lost Redis connectivity afterward.
        logger.warning("Project execution admission lease release deferred to TTL")


@asynccontextmanager
async def project_execution_admission_slot() -> AsyncIterator[None]:
    """Bound one project admission locally and across all API replicas."""

    state = _state()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + float(settings.PROJECT_EXECUTION_ADMISSION_WAIT_SECONDS)
    state.waiting += 1
    local_acquired = False
    active_recorded = False
    distributed_acquired = False
    client: Any | None = None
    token = uuid4().hex
    key = settings.PROJECT_EXECUTION_ADMISSION_REDIS_KEY.strip()
    try:
        try:
            await asyncio.wait_for(
                state.semaphore.acquire(),
                timeout=max(0.001, deadline - loop.time()),
            )
            local_acquired = True
        except TimeoutError as exc:
            raise ProjectExecutionAdmissionTimeout(
                "project execution admission is temporarily saturated"
            ) from exc
        finally:
            state.waiting = max(0, state.waiting - 1)

        client = await _redis_client()
        if client is not None:
            if not key:
                raise ProjectExecutionAdmissionUnavailable(
                    "distributed project admission key is not configured"
                )
            await _acquire_distributed(
                client=client,
                key=key,
                token=token,
                deadline=deadline,
            )
            distributed_acquired = True
            state.distributed_enabled = 1
            state.distributed_active += 1
            state.peak_distributed_active = max(
                state.peak_distributed_active,
                state.distributed_active,
            )

        state.active += 1
        active_recorded = True
        state.peak_active = max(state.peak_active, state.active)
        yield
    finally:
        if active_recorded:
            state.active = max(0, state.active - 1)
        if distributed_acquired and client is not None:
            state.distributed_active = max(0, state.distributed_active - 1)
            await _release_distributed(client=client, key=key, token=token)
        if local_acquired:
            state.semaphore.release()


def project_execution_admission_snapshot() -> dict[str, int]:
    """Return non-sensitive process-local admission telemetry."""

    state = _state()
    return {
        "capacity": state.capacity,
        "active": state.active,
        "waiting": state.waiting,
        "peak_active": state.peak_active,
        "distributed_active": state.distributed_active,
        "peak_distributed_active": state.peak_distributed_active,
        "distributed_enabled": state.distributed_enabled,
        "global_limit": int(settings.PROJECT_EXECUTION_ADMISSION_GLOBAL_LIMIT),
    }
