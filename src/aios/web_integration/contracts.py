from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DashboardCapability(str, Enum):
    PROJECTS_READ = "projects:read"
    PROJECTS_WRITE = "projects:write"
    USERS_READ = "users:read"
    USERS_MANAGE = "users:manage"
    NOTIFICATIONS_READ = "notifications:read"
    NOTIFICATIONS_MANAGE = "notifications:manage"
    ANALYTICS_READ = "analytics:read"
    MARKETPLACE_MANAGE = "marketplace:manage"
    OWNER_CONTROL = "owner:control"


@dataclass(frozen=True)
class DashboardRoute:
    route_id: str
    path: str
    capabilities: frozenset[DashboardCapability] = field(default_factory=frozenset)
    methods: frozenset[str] = field(default_factory=lambda: frozenset({"GET"}))
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.route_id.strip() or not self.path.startswith("/"):
            raise ValueError("route_id and absolute path are required")
        normalized = frozenset(method.upper() for method in self.methods)
        if not normalized:
            raise ValueError("at least one HTTP method is required")
        object.__setattr__(self, "methods", normalized)


@dataclass(frozen=True)
class DashboardManifest:
    dashboard_id: str
    name: str
    version: str
    routes: tuple[DashboardRoute, ...]
    api_base_path: str = "/api/dashboard"
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.dashboard_id.strip() or not self.name.strip() or not self.version.strip():
            raise ValueError("dashboard_id, name, and version are required")
        if not self.api_base_path.startswith("/"):
            raise ValueError("api_base_path must be absolute")
        route_ids = [route.route_id for route in self.routes]
        paths = [route.path for route in self.routes]
        if len(set(route_ids)) != len(route_ids):
            raise ValueError("dashboard route ids must be unique")
        if len(set(paths)) != len(paths):
            raise ValueError("dashboard route paths must be unique")
