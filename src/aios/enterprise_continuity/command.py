from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .continuity import ContinuityPlan, ContinuityPlanState
from .impact import ImpactAssessment, ImpactLevel


class ContinuityDecision(str, Enum):
    OBSERVE = "observe"
    ACTIVATE = "activate"
    ESCALATE = "escalate"
    SUSPEND = "suspend"
    STAND_DOWN = "stand_down"


@dataclass(frozen=True)
class ContinuityDirective:
    directive_id: str
    plan_id: str
    decision: ContinuityDecision
    issued_by: str
    reason: str
    owner_approved: bool
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ContinuityCommandCenter:
    def __init__(self) -> None:
        self._directives: list[ContinuityDirective] = []

    def recommend(self, assessment: ImpactAssessment) -> ContinuityDecision:
        if assessment.level in {ImpactLevel.CATASTROPHIC, ImpactLevel.SEVERE}:
            return ContinuityDecision.ESCALATE
        if assessment.level is ImpactLevel.HIGH:
            return ContinuityDecision.ACTIVATE
        if assessment.level is ImpactLevel.MODERATE:
            return ContinuityDecision.OBSERVE
        return ContinuityDecision.OBSERVE

    def issue(
        self,
        directive: ContinuityDirective,
        plan: ContinuityPlan,
    ) -> ContinuityDirective:
        if not directive.directive_id.strip() or not directive.issued_by.strip() or not directive.reason.strip():
            raise ValueError("directive_id, issued_by and reason are required")
        if directive.plan_id != plan.plan_id:
            raise ValueError("directive plan mismatch")
        if directive.decision in {ContinuityDecision.ACTIVATE, ContinuityDecision.ESCALATE, ContinuityDecision.SUSPEND, ContinuityDecision.STAND_DOWN} and not directive.owner_approved:
            raise PermissionError("owner approval is required")
        if directive.decision in {ContinuityDecision.ACTIVATE, ContinuityDecision.ESCALATE}:
            if plan.state is ContinuityPlanState.APPROVED:
                plan.transition(ContinuityPlanState.ACTIVE)
            elif plan.state is not ContinuityPlanState.ACTIVE:
                raise ValueError("plan must be approved or active")
        elif directive.decision is ContinuityDecision.SUSPEND:
            plan.transition(ContinuityPlanState.SUSPENDED)
        elif directive.decision is ContinuityDecision.STAND_DOWN and plan.state is ContinuityPlanState.SUSPENDED:
            plan.transition(ContinuityPlanState.ACTIVE)
        self._directives.append(directive)
        return directive

    def history(self, plan_id: str | None = None) -> list[ContinuityDirective]:
        if plan_id is None:
            return list(self._directives)
        return [item for item in self._directives if item.plan_id == plan_id]
