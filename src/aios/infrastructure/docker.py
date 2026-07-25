from __future__ import annotations

from typing import Any, Awaitable, Callable

from .base import BaseInfrastructureIntegration
from .commands import CommandValidator
from .models import (ConnectionProfile, ConnectionState, HealthReport,
                     IntegrationCapability, IntegrationDescriptor, IntegrationKind)
from .retries import RetryPolicy

DockerRunner = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class DockerProvider(BaseInfrastructureIntegration):
    CAPABILITIES = ("images", "containers", "networks", "volumes", "build", "pull", "push", "logs",
                    "exec", "stats", "restart", "remove", "compose")

    def __init__(self, runner: DockerRunner | None = None, *, validator: CommandValidator | None = None,
                 retry: RetryPolicy | None = None) -> None:
        super().__init__(IntegrationDescriptor(
            name="docker", kind=IntegrationKind.CONTAINER,
            capabilities=tuple(IntegrationCapability(item, destructive=item == "remove") for item in self.CAPABILITIES),
        ))
        self._runner = runner or self._dry_runner
        self.validator = validator or CommandValidator()
        self.retry = retry or RetryPolicy()
        self.endpoint = ""

    async def _connect(self, profile: ConnectionProfile, context: dict[str, Any]) -> None:
        self.endpoint = profile.endpoint or "unix:///var/run/docker.sock"

    async def _disconnect(self) -> None:
        self.endpoint = ""

    async def _health_check(self) -> HealthReport:
        state = ConnectionState.CONNECTED if self.endpoint else ConnectionState.DISCONNECTED
        return HealthReport(self.name, state, message="Docker engine ready" if self.endpoint else "Docker disconnected")

    async def _execute(self, capability: str, payload: dict[str, Any]) -> Any:
        payload = dict(payload)
        if capability == "exec":
            payload["command"] = self.validator.validate(str(payload.get("command", "")))
        if capability == "remove":
            self.validator.validate("docker remove", destructive=True, approved=bool(payload.get("approved")))
        async def operation() -> dict[str, Any]:
            return await self._runner(capability, payload)
        return await self.retry.run(operation)

    async def _dry_runner(self, capability: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"provider": "docker", "endpoint": self.endpoint, "operation": capability,
                "payload": dict(payload), "exit_code": 0}
