"""Final integration registry and contract validation for dashboard runtime services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class IntegrationContract:
    name: str
    required_routes: tuple[str, ...]
    health_check: Callable[[], bool] | None = None


class IntegrationRegistry:
    def __init__(self) -> None:
        self._contracts: dict[str, IntegrationContract] = {}

    def register(self, contract: IntegrationContract) -> None:
        if contract.name in self._contracts:
            raise ValueError(f"Integration contract already registered: {contract.name}")
        self._contracts[contract.name] = contract

    def validate(self, available_routes: set[str]) -> dict[str, object]:
        missing: dict[str, list[str]] = {}
        health: dict[str, bool] = {}
        for name, contract in self._contracts.items():
            absent = [route for route in contract.required_routes if route not in available_routes]
            if absent:
                missing[name] = absent
            health[name] = contract.health_check() if contract.health_check else not absent
        return {
            "valid": not missing and all(health.values()),
            "missing_routes": missing,
            "health": health,
            "contracts": sorted(self._contracts),
        }


integration_registry = IntegrationRegistry()
for _name, _routes in {
    "identity": ("/auth/me", "/users", "/organizations", "/roles", "/permissions"),
    "operations": ("/projects", "/tasks", "/workflows", "/meetings", "/reports"),
    "ai_runtime": ("/ai/agents", "/ai/providers", "/notifications", "/realtime/status"),
    "production": ("/monitoring/metrics", "/monitoring/alerts", "/security/events", "/monitoring/health"),
}.items():
    integration_registry.register(IntegrationContract(_name, _routes))
