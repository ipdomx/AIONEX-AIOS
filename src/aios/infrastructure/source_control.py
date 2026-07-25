from __future__ import annotations

from typing import Any, Awaitable, Callable

from .base import BaseInfrastructureIntegration
from .models import (ConnectionProfile, ConnectionState, HealthReport,
                     IntegrationCapability, IntegrationDescriptor, IntegrationKind)
from .retries import RetryPolicy

APIRunner = Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]]


class _SourceControlAPIProvider(BaseInfrastructureIntegration):
    def __init__(self, name: str, capabilities: tuple[str, ...], runner: APIRunner | None = None,
                 retry: RetryPolicy | None = None) -> None:
        super().__init__(IntegrationDescriptor(
            name=name, kind=IntegrationKind.SOURCE_CONTROL,
            capabilities=tuple(IntegrationCapability(item) for item in capabilities),
        ))
        self._runner = runner or self._dry_runner
        self.retry = retry or RetryPolicy()
        self.endpoint = ""

    async def _connect(self, profile: ConnectionProfile, context: dict[str, Any]) -> None:
        self.endpoint = profile.endpoint or self.default_endpoint
        credential = context.get("credential")
        if credential is not None and not (getattr(credential, "token", None) or getattr(credential, "password", None)):
            raise ValueError(f"{self.name} token is required")

    async def _disconnect(self) -> None:
        self.endpoint = ""

    async def _health_check(self) -> HealthReport:
        state = ConnectionState.CONNECTED if self.endpoint else ConnectionState.DISCONNECTED
        return HealthReport(self.name, state, message=f"{self.name} API ready" if self.endpoint else "disconnected")

    async def _execute(self, capability: str, payload: dict[str, Any]) -> Any:
        async def operation() -> dict[str, Any]:
            return await self._runner(self.endpoint, capability, payload)
        return await self.retry.run(operation)

    async def _dry_runner(self, endpoint: str, capability: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"provider": self.name, "endpoint": endpoint, "operation": capability, "payload": dict(payload)}


class GitHubProvider(_SourceControlAPIProvider):
    default_endpoint = "https://api.github.com"
    def __init__(self, runner: APIRunner | None = None, *, retry: RetryPolicy | None = None) -> None:
        super().__init__("github", ("repositories", "pull_requests", "issues", "actions", "releases",
                                    "secrets", "webhooks", "labels", "teams"), runner, retry)


class GitLabProvider(_SourceControlAPIProvider):
    default_endpoint = "https://gitlab.com/api/v4"
    def __init__(self, runner: APIRunner | None = None, *, retry: RetryPolicy | None = None) -> None:
        super().__init__("gitlab", ("projects", "merge_requests", "pipelines", "registry", "variables",
                                    "webhooks", "groups"), runner, retry)
