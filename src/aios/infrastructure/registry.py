from __future__ import annotations

from .base import BaseInfrastructureIntegration
from .models import IntegrationKind


class IntegrationRegistry:
    def __init__(self) -> None:
        self._integrations: dict[str, BaseInfrastructureIntegration] = {}

    def register(self, integration: BaseInfrastructureIntegration, *, replace: bool = False) -> None:
        if integration.name in self._integrations and not replace:
            raise ValueError(f"integration already registered: {integration.name}")
        self._integrations[integration.name] = integration

    def unregister(self, name: str) -> None:
        self._integrations.pop(name, None)

    def get(self, name: str) -> BaseInfrastructureIntegration:
        try:
            return self._integrations[name]
        except KeyError as exc:
            raise KeyError(f"unknown integration: {name}") from exc

    def all(self) -> tuple[BaseInfrastructureIntegration, ...]:
        return tuple(self._integrations[name] for name in sorted(self._integrations))

    def by_kind(self, kind: IntegrationKind) -> tuple[BaseInfrastructureIntegration, ...]:
        return tuple(item for item in self.all() if item.descriptor.kind == kind)

    def discover(self, capability: str) -> tuple[BaseInfrastructureIntegration, ...]:
        return tuple(
            item for item in self.all()
            if any(entry.name == capability for entry in item.descriptor.capabilities)
        )
