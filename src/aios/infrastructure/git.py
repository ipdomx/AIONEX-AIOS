from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from .base import BaseInfrastructureIntegration
from .commands import CommandValidator
from .models import (ConnectionProfile, ConnectionState, HealthReport,
                     IntegrationCapability, IntegrationDescriptor, IntegrationKind)
from .retries import RetryPolicy

GitRunner = Callable[[tuple[str, ...], Path | None], Awaitable[dict[str, Any]]]


class GitProvider(BaseInfrastructureIntegration):
    OPERATIONS = {"clone", "pull", "fetch", "push", "commit", "branch", "checkout", "merge",
                  "rebase", "tag", "stash", "reset", "status", "diff", "log"}

    def __init__(self, runner: GitRunner | None = None, *, retry: RetryPolicy | None = None) -> None:
        super().__init__(IntegrationDescriptor(
            name="git", kind=IntegrationKind.SOURCE_CONTROL,
            capabilities=tuple(IntegrationCapability(name, destructive=name in {"push", "reset", "rebase"})
                               for name in sorted(self.OPERATIONS)),
        ))
        self._runner = runner or self._dry_runner
        self.retry = retry or RetryPolicy()
        self.repository: Path | None = None

    async def _connect(self, profile: ConnectionProfile, context: dict[str, Any]) -> None:
        path = profile.options.get("repository") or profile.endpoint
        self.repository = Path(path).expanduser() if path else None

    async def _disconnect(self) -> None:
        self.repository = None

    async def _health_check(self) -> HealthReport:
        state = ConnectionState.CONNECTED if self.profile else ConnectionState.DISCONNECTED
        return HealthReport(self.name, state, message="Git integration ready" if self.profile else "Git disconnected")

    async def _execute(self, capability: str, payload: dict[str, Any]) -> Any:
        args = self._build_args(capability, payload)
        async def operation() -> dict[str, Any]:
            return await self._runner(args, self.repository)
        return await self.retry.run(operation)

    def _build_args(self, capability: str, payload: dict[str, Any]) -> tuple[str, ...]:
        args: list[str] = ["git", capability]
        if capability == "clone":
            url = str(payload.get("url", "")).strip()
            if not url:
                raise ValueError("repository URL is required")
            args.append(url)
            if payload.get("destination"):
                args.append(str(payload["destination"]))
        elif capability == "commit":
            args += ["-m", str(payload.get("message", "AIOS automated commit"))]
        else:
            values = payload.get("args", ())
            if isinstance(values, str):
                values = (values,)
            args.extend(str(item) for item in values)
        return tuple(args)

    async def _dry_runner(self, args: tuple[str, ...], cwd: Path | None) -> dict[str, Any]:
        return {"provider": "git", "args": args, "cwd": str(cwd) if cwd else None, "exit_code": 0}
