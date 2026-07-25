from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ObjectiveStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class StrategicObjective:
    objective_id: str
    title: str
    target_value: float | None = None
    current_value: float | None = None
    status: ObjectiveStatus = ObjectiveStatus.PLANNED
    dependencies: list[str] = field(default_factory=list)


@dataclass
class StrategicPlan:
    plan_id: str
    title: str
    objectives: list[StrategicObjective]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    owner: str | None = None


class StrategicPlanningEngine:
    def create_plan(
        self,
        plan_id: str,
        title: str,
        objectives: list[StrategicObjective],
        owner: str | None = None,
    ) -> StrategicPlan:
        if not plan_id.strip() or not title.strip():
            raise ValueError("plan id and title are required")
        if not objectives:
            raise ValueError("strategic plan requires objectives")
        objective_ids = [objective.objective_id for objective in objectives]
        if len(set(objective_ids)) != len(objective_ids):
            raise ValueError("objective ids must be unique")
        return StrategicPlan(plan_id=plan_id, title=title, objectives=list(objectives), owner=owner)

    def progress(self, plan: StrategicPlan) -> float:
        if not plan.objectives:
            return 0.0
        completed = sum(1 for objective in plan.objectives if objective.status is ObjectiveStatus.COMPLETED)
        return completed / len(plan.objectives)
