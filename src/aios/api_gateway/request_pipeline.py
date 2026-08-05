from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping


@dataclass(slots=True)
class GatewayRequest:
    request_id: str
    method: str
    path: str
    principal_id: str
    headers: dict[str, str] = field(default_factory=dict)
    body: object | None = None
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class GatewayResponse:
    status_code: int
    body: object | None = None
    headers: dict[str, str] = field(default_factory=dict)


Middleware = Callable[[GatewayRequest, Callable[[GatewayRequest], GatewayResponse]], GatewayResponse]
Handler = Callable[[GatewayRequest], GatewayResponse]


class RequestPipeline:
    def __init__(self, handler: Handler, middleware: list[Middleware] | None = None) -> None:
        self._handler = handler
        self._middleware = list(middleware or [])

    def execute(self, request: GatewayRequest) -> GatewayResponse:
        current: Handler = self._handler
        for component in reversed(self._middleware):
            next_handler = current

            def wrapped(req: GatewayRequest, component: Middleware = component, next_handler: Handler = next_handler) -> GatewayResponse:
                return component(req, next_handler)

            current = wrapped
        response = current(request)
        response.headers.setdefault("x-request-id", request.request_id)
        return response


def request_context_middleware(
    allowed_headers: Mapping[str, str] | None = None,
) -> Middleware:
    defaults = dict(allowed_headers or {})

    def middleware(request: GatewayRequest, next_handler: Handler) -> GatewayResponse:
        request.headers = {key.lower(): value for key, value in request.headers.items()}
        response = next_handler(request)
        for key, value in defaults.items():
            response.headers.setdefault(key, value)
        return response

    return middleware
