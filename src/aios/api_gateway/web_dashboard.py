from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class DashboardModule:
    module_id: str
    title: str
    route: str
    required_scope: str
    enabled: bool = True
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class DashboardManifest:
    owner_id: str
    generated_at: datetime
    modules: list[DashboardModule]


class WebDashboardService:
    def __init__(self) -> None:
        self._modules: dict[str, DashboardModule] = {}

    def register(self, module: DashboardModule) -> DashboardModule:
        if module.module_id in self._modules:
            raise ValueError(f"duplicate dashboard module: {module.module_id}")
        self._modules[module.module_id] = module
        return module

    def set_enabled(self, module_id: str, enabled: bool) -> DashboardModule:
        module = self._modules[module_id]
        module.enabled = enabled
        return module

    def manifest_for(self, owner_id: str, scopes: set[str]) -> DashboardManifest:
        modules = [
            module
            for module in self._modules.values()
            if module.enabled and module.required_scope in scopes
        ]
        modules.sort(key=lambda module: (module.route, module.module_id))
        return DashboardManifest(
            owner_id=owner_id,
            generated_at=datetime.now(timezone.utc),
            modules=modules,
        )
