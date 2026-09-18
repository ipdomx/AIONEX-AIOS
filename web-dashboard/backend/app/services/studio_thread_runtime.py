"""Join Studio blocking functions before propagating caller cancellation.

This is process-local completion evidence only. It does not create durable
resource ownership, settle an attempt, delete files or prove host drain. A file
published during cancellation must remain unresolved for later reconciliation.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextvars
from functools import partial
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


class StudioThreadUncertain(RuntimeError):
    """An executor future was cancelled without observing its function finish."""


async def joined_studio_thread(
    function: Callable[P, T], *args: P.args, **kwargs: P.kwargs,
) -> T:
    """Keep the executor future alive through repeated caller cancellation.

    Like to_thread, the submission carries the current context. The executor
    future is strongly referenced and is never explicitly cancelled here. Caller
    cancellation is re-raised only after completion, with any function failure
    attached as its cause. No timeout is treated as a stopped thread.
    """
    context = contextvars.copy_context()
    future = asyncio.get_running_loop().run_in_executor(
        None, context.run, partial(function, *args, **kwargs),
    )
    cancellation: asyncio.CancelledError | None = None
    while not future.done():
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
            if future.cancelled():
                raise StudioThreadUncertain(
                    "Studio executor completion is unverified"
                ) from exc
        except BaseException:
            if not future.done():
                raise
    if future.cancelled():
        raise StudioThreadUncertain("Studio executor completion is unverified")
    if cancellation is not None:
        raise cancellation from future.exception()
    return future.result()
