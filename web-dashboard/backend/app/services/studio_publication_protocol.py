"""Process-local bridge contract for owned Studio filesystem publication.

The worker installs a synchronous observer in its owned storage thread. Direct
local package-library calls may remain unjournaled; they are not host-drain
coverage. Observers must acknowledge persistence before returning.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

PublicationObserver = Callable[[str, dict[str, Any]], None]
_observer: ContextVar[PublicationObserver | None] = ContextVar(
    "studio_publication_observer", default=None,
)


@contextmanager
def publication_observer(observer: PublicationObserver) -> Iterator[None]:
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


def publication_event(operation: str, payload: dict[str, Any]) -> None:
    observer = _observer.get()
    if observer is not None:
        observer(operation, payload)
