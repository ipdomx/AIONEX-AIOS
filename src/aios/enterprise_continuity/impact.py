from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ImpactLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    SEVERE = "severe"
    CATASTROPHIC = "catastrophic"


@dataclass(frozen=True)
class ImpactAssessment:
    assessment_id: str
    organization_id: str
    service_id: str
    level: ImpactLevel
    estimated_users_affected: int
    estimated_downtime_minutes: int
    financial_exposure: float = 0.0
    regulatory_exposure: bool = False
    safety_exposure: bool = False
    dependencies: tuple[str, ...] = ()
    assessed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BusinessImpactAnalyzer:
    def assess(
        self,
        assessment_id: str,
        organization_id: str,
        service_id: str,
        estimated_users_affected: int,
        estimated_downtime_minutes: int,
        financial_exposure: float = 0.0,
        regulatory_exposure: bool = False,
        safety_exposure: bool = False,
        dependencies: tuple[str, ...] = (),
    ) -> ImpactAssessment:
        if not assessment_id.strip() or not organization_id.strip() or not service_id.strip():
            raise ValueError("assessment_id, organization_id and service_id are required")
        if estimated_users_affected < 0 or estimated_downtime_minutes < 0 or financial_exposure < 0:
            raise ValueError("impact values cannot be negative")
        score = 0
        score += 4 if safety_exposure else 0
        score += 3 if regulatory_exposure else 0
        score += 3 if estimated_downtime_minutes >= 1440 else 2 if estimated_downtime_minutes >= 240 else 1 if estimated_downtime_minutes >= 60 else 0
        score += 2 if estimated_users_affected >= 10000 else 1 if estimated_users_affected >= 1000 else 0
        score += 2 if financial_exposure >= 1_000_000 else 1 if financial_exposure >= 100_000 else 0
        score += 1 if len(dependencies) >= 3 else 0
        if score >= 10:
            level = ImpactLevel.CATASTROPHIC
        elif score >= 7:
            level = ImpactLevel.SEVERE
        elif score >= 4:
            level = ImpactLevel.HIGH
        elif score >= 2:
            level = ImpactLevel.MODERATE
        else:
            level = ImpactLevel.LOW
        return ImpactAssessment(
            assessment_id=assessment_id,
            organization_id=organization_id,
            service_id=service_id,
            level=level,
            estimated_users_affected=estimated_users_affected,
            estimated_downtime_minutes=estimated_downtime_minutes,
            financial_exposure=financial_exposure,
            regulatory_exposure=regulatory_exposure,
            safety_exposure=safety_exposure,
            dependencies=dependencies,
        )
