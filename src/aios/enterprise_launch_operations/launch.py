from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class LaunchStage(str, Enum):
    PLANNING = "planning"
    PILOT = "pilot"
    CONTROLLED = "controlled"
    GENERAL = "general"


class LaunchStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"


@dataclass
class LaunchPlan:
    launch_id: str
    version: str
    owner_id: str
    stage: LaunchStage = LaunchStage.PLANNING
    status: LaunchStatus = LaunchStatus.DRAFT
    required_gates: set[str] = field(default_factory=set)
    passed_gates: set[str] = field(default_factory=set)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, str] = field(default_factory=dict)

    def ready(self) -> bool:
        return self.required_gates.issubset(self.passed_gates)


class EnterpriseLaunchManager:
    def __init__(self) -> None:
        self._plans: dict[str, LaunchPlan] = {}

    def create(self, plan: LaunchPlan) -> LaunchPlan:
        if not plan.launch_id.strip() or not plan.version.strip() or not plan.owner_id.strip():
            raise ValueError("launch_id, version, and owner_id are required")
        if plan.launch_id in self._plans:
            raise ValueError(f"duplicate launch_id: {plan.launch_id}")
        self._plans[plan.launch_id] = plan
        return plan

    def get(self, launch_id: str) -> LaunchPlan:
        try:
            return self._plans[launch_id]
        except KeyError as exc:
            raise LookupError(f"launch not found: {launch_id}") from exc

    def pass_gate(self, launch_id: str, gate: str) -> LaunchPlan:
        if not gate.strip():
            raise ValueError("gate is required")
        plan = self.get(launch_id)
        plan.passed_gates.add(gate)
        if plan.ready() and plan.status is LaunchStatus.DRAFT:
            plan.status = LaunchStatus.READY
        return plan

    def activate(self, launch_id: str) -> LaunchPlan:
        plan = self.get(launch_id)
        if not plan.ready():
            missing = sorted(plan.required_gates - plan.passed_gates)
            raise ValueError(f"launch gates incomplete: {', '.join(missing)}")
        if plan.status not in {LaunchStatus.READY, LaunchStatus.PAUSED}:
            raise ValueError(f"launch cannot activate from {plan.status.value}")
        plan.status = LaunchStatus.ACTIVE
        return plan

    def pause(self, launch_id: str) -> LaunchPlan:
        plan = self.get(launch_id)
        if plan.status is not LaunchStatus.ACTIVE:
            raise ValueError("only active launches can be paused")
        plan.status = LaunchStatus.PAUSED
        return plan

    def complete(self, launch_id: str) -> LaunchPlan:
        plan = self.get(launch_id)
        if plan.status is not LaunchStatus.ACTIVE:
            raise ValueError("only active launches can be completed")
        plan.status = LaunchStatus.COMPLETED
        return plan

    def rollback(self, launch_id: str) -> LaunchPlan:
        plan = self.get(launch_id)
        if plan.status not in {LaunchStatus.ACTIVE, LaunchStatus.PAUSED}:
            raise ValueError("launch is not rollback eligible")
        plan.status = LaunchStatus.ROLLED_BACK
        return plan
