"""Durable security, threat, audit, policy, and session controls for Phase 29G."""

from __future__ import annotations


from app.core.auth import UserRecord, require_permissions, require_super_owner
from app.core.config import settings
from app.db.base import get_db
from app.db.models import Alert, AuditEvent, OwnerControlRecord, RefreshSession, User
from app.services import operations_assurance
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get("/events")
async def get_security_events(
    type: str | None = None,
    user_id: str | None = None,
    risk_level: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    actor: UserRecord = Depends(require_permissions("security:read")),
    session: AsyncSession = Depends(get_db),
):
    rows = await operations_assurance.security_events(
        session,
        organization_id=actor.organization_id,
        super_owner=actor.role == "Super Owner",
        limit=min(500, skip + limit + 100),
    )
    if type:
        rows = [row for row in rows if row["type"] == type]
    if user_id:
        rows = [row for row in rows if row.get("user_id") == user_id]
    if risk_level:
        rows = [row for row in rows if row["risk_level"] == risk_level]
    return rows[skip : skip + limit]


@router.post("/events", status_code=status.HTTP_201_CREATED)
async def create_security_event(
    event_type: str,
    risk_score: int = Query(..., ge=0, le=100),
    result: str = "detected",
    user_id: str | None = None,
    ip: str | None = None,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    if user_id:
        target = await session.scalar(select(User).where(User.id == user_id))
        if target is None:
            raise HTTPException(status_code=404, detail="Security event user not found")
    event = AuditEvent(
        organization_id=actor.organization_id,
        user_id=user_id,
        action="security.event",
        resource_type="security_event",
        resource_id=event_type.strip(),
        ip_address=(ip or "").strip() or None,
        details={
            "event_type": event_type.strip(),
            "risk_score": risk_score,
            "result": result.strip(),
            "severity": "critical" if risk_score >= 80 else "high" if risk_score >= 60 else "medium" if risk_score >= 30 else "low",
            "status": "completed",
        },
    )
    session.add(event)
    if risk_score >= 60:
        session.add(
            Alert(
                organization_id=actor.organization_id,
                title=f"Security event: {event_type.strip()}",
                description=f"Durable security evidence recorded with risk score {risk_score}",
                severity="critical" if risk_score >= 80 else "high",
                status="active",
                source="security",
                details={"security_event_id": event.id, "risk_score": risk_score},
            )
        )
    await session.commit()
    return (await operations_assurance.security_events(
        session,
        organization_id=actor.organization_id,
        super_owner=True,
        limit=1,
    ))[0]


@router.get("/threats")
async def get_threats(
    severity: str | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    actor: UserRecord = Depends(require_permissions("security:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(Alert).where(Alert.source == "security")
    if actor.role != "Super Owner":
        statement = statement.where(
            or_(Alert.organization_id == actor.organization_id, Alert.organization_id.is_(None))
        )
    if severity:
        statement = statement.where(Alert.severity == severity)
    if status:
        statement = statement.where(Alert.status == status)
    rows = list(
        (
            await session.scalars(
                statement.order_by(Alert.created_at.desc()).offset(skip).limit(limit)
            )
        ).all()
    )
    return [
        {
            "id": row.id,
            "title": row.title,
            "description": row.description,
            "severity": row.severity,
            "status": row.status,
            "source": row.source,
            "source_ip": (row.details or {}).get("source_ip"),
            "detected_at": operations_assurance.iso(row.created_at),
            "acknowledged_at": operations_assurance.iso(row.acknowledged_at) if row.acknowledged_at else None,
            "resolved_at": operations_assurance.iso(row.resolved_at) if row.resolved_at else None,
        }
        for row in rows
    ]


@router.get("/audit")
async def get_audit_events(
    action: str | None = None,
    actor_name: str | None = Query(default=None, alias="actor"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    actor: UserRecord = Depends(require_permissions("audit:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = (
        select(AuditEvent, User.name)
        .outerjoin(User, User.id == AuditEvent.user_id)
        .where(
            or_(
                AuditEvent.organization_id == actor.organization_id,
                AuditEvent.organization_id.is_(None) if actor.role == "Super Owner" else False,
            )
        )
    )
    if action:
        statement = statement.where(AuditEvent.action == action)
    if actor_name:
        statement = statement.where(User.name.ilike(f"%{actor_name.strip()}%"))
    rows = (
        await session.execute(
            statement.order_by(AuditEvent.created_at.desc()).offset(skip).limit(limit)
        )
    ).all()
    return [
        {
            "id": event.id,
            "timestamp": operations_assurance.iso(event.created_at),
            "actor": user_name or "System",
            "action": event.action,
            "resource": event.resource_id or event.resource_type or "platform",
            "metadata": event.details or {},
        }
        for event, user_name in rows
    ]


@router.post("/audit", status_code=status.HTTP_201_CREATED)
async def create_audit_event(
    action: str,
    resource: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    event = AuditEvent(
        organization_id=actor.organization_id,
        user_id=actor.id,
        action=action.strip(),
        resource_type="operator_audit",
        resource_id=resource.strip(),
        details={"status": "completed", "source": "explicit-owner-audit"},
    )
    session.add(event)
    await session.commit()
    return {
        "id": event.id,
        "timestamp": operations_assurance.iso(event.created_at),
        "actor": actor.name,
        "action": event.action,
        "resource": event.resource_id,
        "metadata": event.details,
    }


@router.get("/policies")
async def get_policies(
    actor: UserRecord = Depends(require_permissions("security:read")),
    session: AsyncSession = Depends(get_db),
):
    del actor
    rows = list(
        (
            await session.scalars(
                select(OwnerControlRecord)
                .where(OwnerControlRecord.domain.in_({"policies", "security-policies"}))
                .order_by(OwnerControlRecord.resource_id)
            )
        ).all()
    )
    policies = [
        {
            "id": "password-policy",
            "name": "Password Policy",
            "status": "active",
            "rules": {"minimum_length": 12, "hashing": "pbkdf2-sha256", "plaintext_storage": False},
            "source": "enforced-auth-runtime",
        },
        {
            "id": "session-policy",
            "name": "Session Policy",
            "status": "active",
            "rules": {"access_minutes": settings.ACCESS_TOKEN_EXPIRE_MINUTES, "refresh_days": settings.REFRESH_TOKEN_EXPIRE_DAYS, "revocation_persistent": True},
            "source": "enforced-auth-runtime",
        },
        {
            "id": "audit-policy",
            "name": "Audit Policy",
            "status": "active",
            "rules": {"durable_sql": True, "owner_commands_append_only": True},
            "source": "database-schema",
        },
    ]
    policies.extend(
        {
            "id": row.resource_id,
            "name": (row.payload or {}).get("name", row.resource_id),
            "status": row.status,
            "rules": (row.payload or {}).get("rules", {}),
            "source": "owner-governed",
            "version": row.version,
        }
        for row in rows
    )
    return policies


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(100, ge=1, le=500),
    actor: UserRecord = Depends(require_permissions("security:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(RefreshSession, User).join(User, User.id == RefreshSession.user_id)
    if actor.role != "Super Owner":
        statement = statement.where(User.organization_id == actor.organization_id)
    rows = (
        await session.execute(
            statement.order_by(RefreshSession.created_at.desc()).limit(limit)
        )
    ).all()
    return [
        {
            "id": refresh.id,
            "user_id": user.id,
            "user": user.name,
            "organization_id": user.organization_id,
            "expires_at": operations_assurance.iso(refresh.expires_at),
            "revoked_at": operations_assurance.iso(refresh.revoked_at) if refresh.revoked_at else None,
            "ip_address": refresh.ip_address,
            "user_agent": refresh.user_agent,
            "active": refresh.revoked_at is None and refresh.expires_at > operations_assurance.now(),
            "created_at": operations_assurance.iso(refresh.created_at),
        }
        for refresh, user in rows
    ]


@router.delete("/sessions/{session_id}")
async def terminate_session(
    session_id: str,
    actor: UserRecord = Depends(require_permissions("security:write")),
    session: AsyncSession = Depends(get_db),
):
    record = await operations_assurance.revoke_refresh_session(
        session,
        session_id=session_id,
        actor_id=actor.id,
        organization_id=actor.organization_id,
        super_owner=actor.role == "Super Owner",
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await session.commit()
    return {"message": "Session revoked", "session_id": record.id, "revoked_at": operations_assurance.iso(record.revoked_at)}


@router.get("/compliance")
async def compliance_evidence(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    rows = list(
        (
            await session.scalars(
                select(OwnerControlRecord)
                .where(OwnerControlRecord.domain == "compliance")
                .order_by(OwnerControlRecord.resource_id)
            )
        ).all()
    )
    return [
        {
            "id": row.resource_id,
            "status": row.status,
            "evidence_count": len((row.payload or {}).get("evidenceReferences", [])),
            "evidence_references": list((row.payload or {}).get("evidenceReferences", [])),
            "version": row.version,
            "updated_at": operations_assurance.iso(row.updated_at),
        }
        for row in rows
    ]
