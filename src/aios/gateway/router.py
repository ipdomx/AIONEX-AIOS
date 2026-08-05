from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from .models import GatewayDecision, GatewayRequest, GatewayRoute, RouteState


class ApiGatewayRouter:
    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], GatewayRoute] = {}
        self._requests: dict[tuple[str, str], deque[datetime]] = defaultdict(deque)

    def register(self, route: GatewayRoute) -> GatewayRoute:
        key = (route.method.value, route.path)
        if key in self._routes:
            raise ValueError(f"duplicate route: {route.method.value} {route.path}")
        self._routes[key] = route
        return route

    def disable(self, route_id: str) -> GatewayRoute:
        route = self._find_by_id(route_id)
        route.state = RouteState.DISABLED
        return route

    def evaluate(self, request: GatewayRequest) -> GatewayDecision:
        route = self._routes.get((request.method.value, request.path))
        if route is None:
            return GatewayDecision(False, 404, "route_not_found")
        if route.state is not RouteState.ACTIVE:
            return GatewayDecision(False, 503, "route_disabled", route_id=route.route_id)
        if not route.required_scopes.issubset(request.scopes):
            return GatewayDecision(False, 403, "insufficient_scope", route_id=route.route_id)
        if not self._consume_rate_limit(request.principal_id, route):
            return GatewayDecision(False, 429, "rate_limit_exceeded", route_id=route.route_id)
        return GatewayDecision(
            True,
            200,
            "allowed",
            route_id=route.route_id,
            target_service=route.target_service,
        )

    def _consume_rate_limit(self, principal_id: str, route: GatewayRoute) -> bool:
        key = (principal_id, route.route_id)
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=1)
        bucket = self._requests[key]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= route.rate_limit_per_minute:
            return False
        bucket.append(now)
        return True

    def _find_by_id(self, route_id: str) -> GatewayRoute:
        for route in self._routes.values():
            if route.route_id == route_id:
                return route
        raise KeyError(f"unknown route: {route_id}")
