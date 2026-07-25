from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .base import BaseInfrastructureIntegration
from .commands import CommandValidator
from .models import (ConnectionProfile, ConnectionState, HealthReport,
                     IntegrationCapability, IntegrationDescriptor, IntegrationKind)
from .retries import RetryPolicy

SSHRunner = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class SSHSession:
    endpoint: str
    username: str | None = None
    connected_at: float = field(default_factory=time.time)


class SSHProvider(BaseInfrastructureIntegration):
    def __init__(self, runner: SSHRunner | None = None, *, validator: CommandValidator | None = None,
                 retry: RetryPolicy | None = None) -> None:
        super().__init__(IntegrationDescriptor(
            name="ssh", kind=IntegrationKind.SSH,
            capabilities=(
                IntegrationCapability("execute"), IntegrationCapability("upload"),
                IntegrationCapability("download"), IntegrationCapability("forward_port"),
            ),
        ))
        self._runner = runner or self._dry_runner
        self.validator = validator or CommandValidator()
        self.retry = retry or RetryPolicy()
        self.session: SSHSession | None = None
        self._context: dict[str, Any] = {}

    async def _connect(self, profile: ConnectionProfile, context: dict[str, Any]) -> None:
        if not profile.endpoint:
            raise ValueError("SSH endpoint is required")
        credential = context.get("credential")
        username = getattr(credential, "username", None)
        self.session = SSHSession(profile.endpoint, username)
        self._context = dict(context)

    async def _disconnect(self) -> None:
        self.session = None
        self._context = {}

    async def _health_check(self) -> HealthReport:
        state = ConnectionState.CONNECTED if self.session else ConnectionState.DISCONNECTED
        return HealthReport(self.name, state, message="SSH session active" if self.session else "SSH disconnected")

    async def _execute(self, capability: str, payload: dict[str, Any]) -> Any:
        if capability == "execute":
            payload = dict(payload)
            payload["command"] = self.validator.validate(
                str(payload.get("command", "")),
                destructive=bool(payload.get("destructive")),
                approved=bool(payload.get("approved")),
            )
        async def operation() -> dict[str, Any]:
            return await self._runner(capability, payload)
        return await self.retry.run(operation)

    async def _dry_runner(self, capability: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"provider": "ssh", "operation": capability, "payload": dict(payload), "exit_code": 0}
