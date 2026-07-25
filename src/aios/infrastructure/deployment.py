from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable


class DeploymentStrategy(str, Enum):
    ROLLING = "rolling"
    BLUE_GREEN = "blue_green"
    CANARY = "canary"


class DeploymentState(str, Enum):
    PLANNED = "planned"
    VALIDATED = "validated"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True, slots=True)
class DeploymentTarget:
    environment: str
    cluster: str | None = None
    namespace: str | None = None
    region: str | None = None


@dataclass(slots=True)
class DeploymentPlan:
    release_id: str
    service: str
    version: str
    image: str
    target: DeploymentTarget
    strategy: DeploymentStrategy = DeploymentStrategy.ROLLING
    replicas: int = 1
    canary_percent: int = 10
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.release_id.strip() or not self.service.strip() or not self.version.strip():
            raise ValueError("release_id, service and version are required")
        if not self.image.strip():
            raise ValueError("deployment image is required")
        if self.replicas < 1:
            raise ValueError("replicas must be at least 1")
        if self.strategy is DeploymentStrategy.CANARY and not 1 <= self.canary_percent <= 100:
            raise ValueError("canary_percent must be between 1 and 100")


@dataclass(frozen=True, slots=True)
class DeploymentEvent:
    release_id: str
    state: DeploymentState
    message: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, Any] = field(default_factory=dict)


class DeploymentEngine:
    """Pure orchestration layer; adapters execute provider-specific commands."""

    def __init__(self) -> None:
        self._events: dict[str, list[DeploymentEvent]] = {}

    def plan(self, plan: DeploymentPlan) -> DeploymentEvent:
        plan.validate()
        return self._record(plan.release_id, DeploymentState.PLANNED, "deployment planned", {
            "strategy": plan.strategy.value,
            "target": plan.target.environment,
        })

    def commands(self, plan: DeploymentPlan) -> tuple[dict[str, Any], ...]:
        plan.validate()
        base = {
            "service": plan.service,
            "version": plan.version,
            "image": plan.image,
            "target": plan.target,
            "replicas": plan.replicas,
        }
        if plan.strategy is DeploymentStrategy.BLUE_GREEN:
            return (
                {"action": "deploy_slot", "slot": "green", **base},
                {"action": "health_check", "slot": "green", **base},
                {"action": "switch_traffic", "from": "blue", "to": "green", **base},
            )
        if plan.strategy is DeploymentStrategy.CANARY:
            return (
                {"action": "deploy_canary", "percent": plan.canary_percent, **base},
                {"action": "observe_canary", "percent": plan.canary_percent, **base},
                {"action": "promote_canary", **base},
            )
        return (
            {"action": "rolling_update", **base},
            {"action": "health_check", **base},
        )

    def start(self, release_id: str) -> DeploymentEvent:
        return self._record(release_id, DeploymentState.RUNNING, "deployment started")

    def complete(self, release_id: str, details: dict[str, Any] | None = None) -> DeploymentEvent:
        return self._record(release_id, DeploymentState.SUCCEEDED, "deployment completed", details)

    def fail(self, release_id: str, reason: str, details: dict[str, Any] | None = None) -> DeploymentEvent:
        payload = dict(details or {})
        payload["reason"] = reason
        return self._record(release_id, DeploymentState.FAILED, "deployment failed", payload)

    def history(self, release_id: str) -> tuple[DeploymentEvent, ...]:
        return tuple(self._events.get(release_id, ()))

    def _record(self, release_id: str, state: DeploymentState, message: str,
                details: dict[str, Any] | None = None) -> DeploymentEvent:
        event = DeploymentEvent(release_id, state, message, details=dict(details or {}))
        self._events.setdefault(release_id, []).append(event)
        return event
