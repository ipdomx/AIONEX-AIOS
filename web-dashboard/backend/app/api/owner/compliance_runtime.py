"""Owner compliance projection backed by shared identity and integration state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import UserRecord, current_user
from app.core.identity_store import identity_store
from app.core.integration_registry import integration_registry

router = APIRouter(
    prefix="/owner/compliance-controls",
    tags=["owner-compliance-runtime"],
)

ComplianceStatus = Literal["compliant", "warning", "noncompliant"]


class ComplianceControl(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    framework: str
    control: str
    owner: str
    status: ComplianceStatus
    evidence: int = Field(ge=0)
    updated_at: str = Field(alias="updatedAt")


def _available_api_routes(request: Request) -> set[str]:
    return {
        route.path.removeprefix("/api/v1")
        for route in request.app.routes
        if hasattr(route, "path")
    }


def _latest_audit_timestamp(resource_id: str | None = None) -> str:
    events = identity_store.audit_events
    if resource_id is not None:
        events = [
            event
            for event in events
            if event.get("resource_type") == "compliance_control"
            and event.get("resource_id") == resource_id
        ]
    if events:
        return str(events[0].get("timestamp") or "")
    return "Not recorded"


def build_compliance_controls(request: Request) -> list[ComplianceControl]:
    """Derive control state from the live shared stores without fallback records."""

    available_routes = _available_api_routes(request)
    super_owner_role = identity_store.role_by_name("Super Owner")
    required_permissions = set(identity_store.permissions)
    granted_permissions = (
        set(super_owner_role.permissions) if super_owner_role else set()
    )
    access_evidence = len(required_permissions.intersection(granted_permissions))
    access_ready = bool(
        super_owner_role
        and super_owner_role.is_system
        and required_permissions
        and required_permissions.issubset(granted_permissions)
    )

    integration_result = integration_registry.validate(available_routes)
    integration_evidence = len(available_routes)

    audit_evidence = len(identity_store.audit_events)
    generated_at = datetime.now(timezone.utc).isoformat()
    return [
        ComplianceControl(
            id="platform-access-control",
            framework="AIONEX RBAC",
            control="Privileged access control",
            owner="Identity",
            status="compliant" if access_ready else "noncompliant",
            evidence=access_evidence,
            updated_at=(
                super_owner_role.updated_at if super_owner_role else "Not configured"
            ),
        ),
        ComplianceControl(
            id="owner-audit-logging",
            framework="AIONEX Audit",
            control="Owner action audit logging",
            owner="Security",
            status="compliant" if audit_evidence else "warning",
            evidence=audit_evidence,
            updated_at=_latest_audit_timestamp(),
        ),
        ComplianceControl(
            id="integration-contracts",
            framework="AIONEX Integration",
            control="Required API contract availability",
            owner="Platform",
            status="compliant" if integration_result["valid"] else "noncompliant",
            evidence=integration_evidence,
            updated_at=generated_at,
        ),
    ]


@router.get("", response_model=list[ComplianceControl])
def list_compliance_controls(request: Request) -> list[ComplianceControl]:
    return build_compliance_controls(request)


@router.post(
    "/{control_id}/attest",
    response_model=ComplianceControl,
)
def attest_compliance_control(
    control_id: str,
    request: Request,
    actor: UserRecord = Depends(current_user),
) -> ComplianceControl:
    controls = {control.id: control for control in build_compliance_controls(request)}
    control = controls.get(control_id)
    if control is None:
        raise HTTPException(status_code=404, detail="Compliance control not found")
    if control.status == "noncompliant":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A non-compliant control cannot be attested before its evidence passes",
        )

    identity_store.record_audit(
        actor.id,
        "attest",
        "compliance_control",
        control_id,
        {
            "framework": control.framework,
            "evidence_count": control.evidence,
        },
    )
    return next(
        item for item in build_compliance_controls(request) if item.id == control_id
    )
