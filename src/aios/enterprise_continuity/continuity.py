from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ContinuityPlanState(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RETIRED = "retired"


@dataclass
class ContinuityPlan:
    plan_id: str
    organization_id: str
    title: str
    critical_services: list[str]
    recovery_time_objective_minutes: int
    recovery_point_objective_minutes: int
    owner_id: str
    state: ContinuityPlanState = ContinuityPlanState.DRAFT
    dependencies: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def transition(self, state: ContinuityPlanState) -> None:
        allowed = {
            ContinuityPlanState.DRAFT: {ContinuityPlanState.APPROVED, ContinuityPlanState.RETIRED},
            ContinuityPlanState.APPROVED: {ContinuityPlanState.ACTIVE, ContinuityPlanState.RETIRED},
            ContinuityPlanState.ACTIVE: {ContinuityPlanState.SUSPENDED, ContinuityPlanState.RETIRED},
            ContinuityPlanState.SUSPENDED: {ContinuityPlanState.ACTIVE, ContinuityPlanState.RETIRED},
            ContinuityPlanState.RETIRED: set(),
        }
        if state not in allowed[self.state]:
            raise ValueError(f"invalid continuity transition: {self.state.value} -> {state.value}")
        self.state = state
        self.updated_at = datetime.now(timezone.utc)


class ContinuityRegistry:
    def __init__(self) -> None:
        self._plans: dict[str, ContinuityPlan] = {}

    def register(self, plan: ContinuityPlan) -> ContinuityPlan:
        if not plan.plan_id.strip() or not plan.organization_id.strip() or not plan.title.strip():
            raise ValueError("plan_id, organization_id and title are required")
        if not plan.critical_services:
            raise ValueError("critical_services cannot be empty")
        if plan.recovery_time_objective_minutes <= 0 or plan.recovery_point_objective_minutes < 0:
            raise ValueError("invalid recovery objectives")
        if plan.plan_id in self._plans:
            raise ValueError(f"duplicate continuity plan: {plan.plan_id}")
        self._plans[plan.plan_id] = plan
        return plan

    def get(self, plan_id: str) -> ContinuityPlan:
        try:
            return self._plans[plan_id]
        except KeyError as exc:
            raise LookupError(f"continuity plan not found: {plan_id}") from exc

    def list_for_organization(self, organization_id: str) -> list[ContinuityPlan]:
        return [plan for plan in self._plans.values() if plan.organization_id == organization_id]

    def active(self) -> list[ContinuityPlan]:
        return [plan for plan in self._plans.values() if plan.state is ContinuityPlanState.ACTIVE]
