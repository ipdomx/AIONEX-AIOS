from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/owner/security-integration", tags=["owner-security-integration"])

SecurityStatus = Literal["secure", "warning", "critical"]
SecurityAction = Literal["validate", "rotate", "quarantine"]


class SecurityTarget(BaseModel):
    id: str
    name: str
    category: str
    status: SecurityStatus
    score: int = Field(ge=0, le=100)
    details: str
    last_checked_at: str


class SecuritySnapshot(BaseModel):
    generated_at: str
    completion: int = Field(ge=0, le=100)
    targets: list[SecurityTarget]


class SecurityCommand(BaseModel):
    action: SecurityAction


_TARGETS: dict[str, SecurityTarget] = {
    "identity-access": SecurityTarget(id="identity-access", name="Identity & Access", category="IAM", status="secure", score=96, details="Owner RBAC, MFA and privileged access policies are active.", last_checked_at="Just now"),
    "secrets-vault": SecurityTarget(id="secrets-vault", name="Secrets Vault", category="Secrets", status="secure", score=94, details="Secret storage, access auditing and rotation controls are connected.", last_checked_at="Just now"),
    "threat-defense": SecurityTarget(id="threat-defense", name="Threat Defense", category="Security", status="warning", score=82, details="Threat intelligence and defensive controls are active with one pending review.", last_checked_at="Just now"),
    "compliance": SecurityTarget(id="compliance", name="Compliance Enforcement", category="Governance", status="secure", score=91, details="Owner policies, approvals and compliance evidence are synchronized.", last_checked_at="Just now"),
}


def _snapshot() -> SecuritySnapshot:
    targets = list(_TARGETS.values())
    completion = round(sum(item.score for item in targets) / len(targets)) if targets else 0
    return SecuritySnapshot(generated_at=datetime.now(UTC).isoformat(), completion=completion, targets=targets)


@router.get("", response_model=SecuritySnapshot)
def get_security_integration() -> SecuritySnapshot:
    return _snapshot()


@router.post("/{target_id}/command", response_model=SecuritySnapshot)
def run_security_command(target_id: str, command: SecurityCommand) -> SecuritySnapshot:
    target = _TARGETS.get(target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Security target not found")

    if command.action == "validate":
        target.score = min(100, target.score + 1)
    elif command.action == "rotate":
        target.score = min(100, target.score + 3)
        target.status = "secure"
    elif command.action == "quarantine":
        target.status = "warning"
        target.details = "Target isolated for owner review and controlled remediation."

    target.last_checked_at = "Just now"
    return _snapshot()
