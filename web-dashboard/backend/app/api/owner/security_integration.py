"""Security integration derived from persistent identity, incidents and controls."""

from datetime import UTC, datetime
from typing import Any, Literal

from app.api.owner.control_plane import _control_items, _run_audited_mutation
from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.db.models import Alert, Role
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(
    prefix="/owner/security-integration",
    tags=["owner-security-integration"],
)


class SecurityTarget(BaseModel):
    id: str
    name: str
    category: str
    status: Literal["secure", "warning", "critical"]
    score: int = Field(ge=0, le=100)
    details: str
    last_checked_at: str


class SecuritySnapshot(BaseModel):
    generated_at: str
    completion: int = Field(ge=0, le=100)
    targets: list[SecurityTarget]


class SecurityCommand(BaseModel):
    action: Literal["validate", "acknowledge"]


SECURITY_TARGET_IDS = frozenset(
    {"identity-access", "secrets-vault", "threat-defense", "compliance"}
)


async def _snapshot(session: AsyncSession) -> SecuritySnapshot:
    now = datetime.now(UTC).isoformat()
    suspended_roles = int(
        (
            await session.scalar(
                select(func.count(Role.id)).where(Role.status != "active")
            )
        )
        or 0
    )
    critical_alerts = int(
        (
            await session.scalar(
                select(func.count(Alert.id)).where(
                    Alert.severity == "critical",
                    Alert.status != "resolved",
                )
            )
        )
        or 0
    )
    secrets = await _control_items(session, "secrets")
    compliance = await _control_items(session, "compliance")
    compliance_failures = sum(
        item["status"] not in {"active", "compliant", "passed"} for item in compliance
    )
    targets = [
        SecurityTarget(
            id="identity-access",
            name="Identity & Access",
            category="IAM",
            status="warning" if suspended_roles else "secure",
            score=max(0, 100 - suspended_roles * 10),
            details=f"{suspended_roles} suspended role(s).",
            last_checked_at=now,
        ),
        SecurityTarget(
            id="secrets-vault",
            name="Secrets & References",
            category="Secrets",
            status=(
                "warning"
                if not secrets or any(item["status"] != "active" for item in secrets)
                else "secure"
            ),
            score=(
                70
                if not secrets
                else round(
                    100
                    * sum(item["status"] == "active" for item in secrets)
                    / len(secrets)
                )
            ),
            details=f"{len(secrets)} external vault reference(s) registered.",
            last_checked_at=now,
        ),
        SecurityTarget(
            id="threat-defense",
            name="Threat Defense",
            category="Security",
            status="critical" if critical_alerts else "secure",
            score=max(0, 100 - critical_alerts * 25),
            details=f"{critical_alerts} unresolved critical alert(s).",
            last_checked_at=now,
        ),
        SecurityTarget(
            id="compliance",
            name="Compliance Enforcement",
            category="Governance",
            status="warning" if compliance_failures else "secure",
            score=max(0, 100 - compliance_failures * 15),
            details=f"{compliance_failures} control(s) need attention.",
            last_checked_at=now,
        ),
    ]
    completion = round(sum(item.score for item in targets) / max(1, len(targets)))
    return SecuritySnapshot(
        generated_at=now,
        completion=completion,
        targets=targets,
    )


@router.get("", response_model=SecuritySnapshot)
async def get_security_integration(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> SecuritySnapshot:
    return await _snapshot(session)


@router.post("/{target_id}/command", response_model=SecuritySnapshot)
async def run_security_command(
    target_id: str,
    command: SecurityCommand,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> SecuritySnapshot:
    async def execute(_audit: object) -> dict[str, Any]:
        if target_id not in SECURITY_TARGET_IDS:
            raise HTTPException(
                status_code=404,
                detail="Security target not found",
            )
        affected = 0
        if command.action == "acknowledge":
            if target_id != "threat-defense":
                raise HTTPException(
                    status_code=409,
                    detail="Only the threat-defense target can acknowledge alerts",
                )
            alerts = (
                await session.scalars(
                    select(Alert).where(
                        Alert.severity == "critical",
                        Alert.status != "resolved",
                    )
                )
            ).all()
            for alert in alerts:
                alert.status = "investigating"
                alert.acknowledged_at = datetime.now(UTC)
            affected = len(alerts)
        return {"affected": affected}

    await _run_audited_mutation(
        session,
        actor=actor,
        domain="security-integration",
        resource_id=target_id,
        action=command.action,
        request=command.model_dump(mode="json"),
        mutation=execute,
    )
    return await _snapshot(session)
