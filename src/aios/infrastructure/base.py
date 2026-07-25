from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import ConnectionProfile, ConnectionState, HealthReport, IntegrationDescriptor


class BaseInfrastructureIntegration(ABC):
    def __init__(self, descriptor: IntegrationDescriptor) -> None:
        self.descriptor = descriptor
        self._state = ConnectionState.UNKNOWN
        self._profile: ConnectionProfile | None = None
        self._enabled = True

    @property
    def name(self) -> str:
        return self.descriptor.name

    @property
    def state(self) -> ConnectionState:
        return ConnectionState.DISABLED if not self._enabled else self._state

    @property
    def profile(self) -> ConnectionProfile | None:
        return self._profile

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False
        self._state = ConnectionState.DISABLED

    async def connect(self, profile: ConnectionProfile, context: dict[str, Any] | None = None) -> None:
        if not self._enabled or not profile.enabled:
            raise RuntimeError(f"integration {self.name} is disabled")
        if profile.integration != self.name:
            raise ValueError(f"profile {profile.name} targets {profile.integration}, expected {self.name}")
        self._state = ConnectionState.CONNECTING
        try:
            await self._connect(profile, context or {})
            self._profile = profile
            self._state = ConnectionState.CONNECTED
        except Exception:
            self._state = ConnectionState.FAILED
            raise

    async def disconnect(self) -> None:
        try:
            await self._disconnect()
        finally:
            self._profile = None
            self._state = ConnectionState.DISCONNECTED

    async def health_check(self) -> HealthReport:
        if not self._enabled:
            return HealthReport(self.name, ConnectionState.DISABLED, message="integration disabled")
        report = await self._health_check()
        self._state = report.state
        return report

    async def execute(self, capability: str, payload: dict[str, Any] | None = None) -> Any:
        if self.state not in {ConnectionState.CONNECTED, ConnectionState.DEGRADED}:
            raise RuntimeError(f"integration {self.name} is not connected")
        supported = {item.name for item in self.descriptor.capabilities}
        if capability not in supported:
            raise KeyError(f"unsupported capability {self.name}/{capability}")
        return await self._execute(capability, payload or {})

    @abstractmethod
    async def _connect(self, profile: ConnectionProfile, context: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def _disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def _health_check(self) -> HealthReport:
        raise NotImplementedError

    @abstractmethod
    async def _execute(self, capability: str, payload: dict[str, Any]) -> Any:
        raise NotImplementedError
