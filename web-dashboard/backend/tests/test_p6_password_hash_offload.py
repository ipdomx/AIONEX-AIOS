"""P6 gate 6.1 capacity fix: Argon2 hashing never blocks the API event loop."""
from __future__ import annotations

import asyncio
import threading

import pytest

from app.core import auth
from app.core.config import settings


@pytest.mark.asyncio
async def test_hash_and_verify_round_trip() -> None:
    password = "P6-Offload-Password-123!"
    hashed = await auth.hash_password(password)
    assert hashed.startswith("$argon2id$")
    assert await auth.verify_password(password, hashed) is True
    assert await auth.verify_password("wrong-password-123!", hashed) is False
    verified, replacement = await auth.verify_and_update_password(password, hashed)
    assert verified is True and replacement is None


@pytest.mark.asyncio
async def test_argon2_runs_on_the_bounded_password_pool() -> None:
    executor = auth._password_hash_executor()
    assert executor is auth._password_hash_executor()
    assert executor._max_workers == settings.PASSWORD_HASH_THREADS
    loop = asyncio.get_running_loop()
    name = await loop.run_in_executor(executor, lambda: threading.current_thread().name)
    assert name.startswith("aionex-password-hash")


@pytest.mark.asyncio
async def test_event_loop_keeps_serving_during_a_login_burst() -> None:
    password = "P6-Offload-Password-123!"
    hashed = await auth.hash_password(password)
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        results = await asyncio.gather(
            *(auth.verify_and_update_password(password, hashed) for _ in range(4))
        )
    finally:
        task.cancel()
    assert all(ok for ok, _ in results)
    # Four Argon2id (64 MiB, t=3) verifications take well over 20 ms; a blocked
    # loop would record no ticks at all while they ran.
    assert ticks >= 3


def test_password_hash_threads_setting_is_bounded() -> None:
    field = type(settings).model_fields["PASSWORD_HASH_THREADS"]
    assert field.default == 2
    bounds = {type(item).__name__: item for item in field.metadata}
    assert bounds["Ge"].ge == 1 and bounds["Le"].le == 16
