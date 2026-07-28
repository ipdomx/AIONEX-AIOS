from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class RouteState(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass(slots=True)
class GatewayRoute:
    route_id: str
    path: str
    method: HttpMethod
    target_service: str
    required_scopes: set[str] = field(default_factory=set)
    state: RouteState = RouteState.ACTIVE
    rate_limit_per_minute: int = 60
    timeout_seconds: float = 30.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise ValueError("route path must start with '/'")
        if self.rate_limit_per_minute <= 0:
            raise ValueError("rate limit must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout must be positive")


@dataclass(slots=True, frozen=True)
class GatewayRequest:
    request_id: str
    path: str
    method: HttpMethod
    principal_id: str
    scopes: frozenset[str]
    organization_id: str | None = None
    project_id: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    body: object | None = None


@dataclass(slots=True, frozen=True)
class GatewayDecision:
    allowed: bool
    status_code: int
    reason: str
    route_id: str | None = None
    target_service: str | None = None
