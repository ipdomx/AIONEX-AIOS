from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from .contracts import DashboardCapability, DashboardRoute
from .registry import DashboardRegistry
from .sessions import DashboardSessionManager
from .tokens import DashboardTokenService


@dataclass(frozen=True)
class DashboardRequest:
    dashboard_id: str
    route_id: str
    method: str
    session_id: str
    payload: dict[str, object] = field(default_factory=dict)
    correlation_id: str | None = None


@dataclass(frozen=True)
class DashboardResponse:
    status_code: int
    data: dict[str, object]
    correlation_id: str | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DashboardGateway:
    def __init__(
        self,
        registry: DashboardRegistry,
        sessions: DashboardSessionManager,
        tokens: DashboardTokenService,
    ) -> None:
        self.registry = registry
        self.sessions = sessions
        self.tokens = tokens
        self._handlers: dict[tuple[str, str], Callable[[DashboardRequest], DashboardResponse]] = {}

    def register_handler(
        self,
        dashboard_id: str,
        route_id: str,
        handler: Callable[[DashboardRequest], DashboardResponse],
    ) -> None:
        self._handlers[(dashboard_id, route_id)] = handler

    def dispatch(self, request: DashboardRequest) -> DashboardResponse:
        manifest = self.registry.get(request.dashboard_id)
        route = self._find_route(manifest.routes, request.route_id)
        if not route.enabled:
            raise PermissionError("dashboard route is disabled")
        if request.method.upper() not in route.methods:
            raise PermissionError("dashboard method not allowed")
        session = self.sessions.get(request.session_id)
        if not session.is_active():
            raise PermissionError("dashboard session inactive")
        if session.dashboard_id != request.dashboard_id:
            raise PermissionError("dashboard session audience mismatch")
        self.tokens.validate(session.token_id, request.dashboard_id, set(route.capabilities))
        try:
            handler = self._handlers[(request.dashboard_id, request.route_id)]
        except KeyError as exc:
            raise LookupError(f"dashboard route handler missing: {request.route_id}") from exc
        return handler(request)

    @staticmethod
    def _find_route(routes: tuple[DashboardRoute, ...], route_id: str) -> DashboardRoute:
        for route in routes:
            if route.route_id == route_id:
                return route
        raise LookupError(f"dashboard route not found: {route_id}")
