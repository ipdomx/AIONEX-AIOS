"""Database-backed control plane for every Owner Dashboard surface.

The original dashboard mixed five live endpoints with browser-only state.  This
module centralizes the remaining owner contracts behind authenticated,
auditable, durable commands while reusing the relational platform models.
"""

from __future__ import annotations

import asyncio
import os
import re
import smtplib
import socket
import ssl
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.ext.asyncio import AsyncSession

from aios.completion_program import completion_program_snapshot
from app.core.auth import UserRecord, pwd_context, require_super_owner
from app.core.config import settings
from app.db.base import SessionLocal, get_db
from app.db.models import (
    AcademyAssessment,
    Alert,
    ApprovalRequest,
    AuditEvent,
    BackupRecord,
    DisasterRecoveryRun,
    GovernanceBody,
    GovernanceDecision,
    GovernancePolicy,
    Meeting,
    MetricSample,
    Notification,
    NotificationDelivery,
    NotificationRule,
    Organization,
    OwnerCommandRecord,
    OwnerControlRecord,
    Project,
    RefreshSession,
    Role,
    SupportMessage,
    SupportRequest,
    User,
    WorkforceMember,
    Workspace,
    uuid_str,
)
from app.db.redis import get_redis
from app.services import communications, work_management
from app.services import governance as governance_service
from app.services import operations_assurance
from app.services import workforce as workforce_service
from app.services.backup_executor import (
    BackupExecutionError,
    acquire_enqueue_lock,
    get_backup_executor,
)

router = APIRouter(prefix="/owner", tags=["owner-control-plane"])


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    current = value or _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat()


def _repo_version() -> str:
    repository_root = Path(
        os.getenv("AIOS_REPO_ROOT", str(Path(__file__).resolve().parents[5]))
    )
    version_file = repository_root / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return settings.APP_VERSION


_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_MARKERS = {
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "privatekey",
    "reference",
    "secret",
    "session",
    "token",
}


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _redact_sensitive(value: Any) -> Any:
    """Recursively redact secrets before they reach durable audit JSON."""

    if isinstance(value, dict):
        return {
            key: (
                _REDACTED
                if any(
                    marker in _normalized_key(key) for marker in _SENSITIVE_KEY_MARKERS
                )
                else _redact_sensitive(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_sensitive(item) for item in value]
    return value


class OwnerResourceCollection(BaseModel):
    domain: str
    generatedAt: str
    items: list[dict[str, Any]]


class OwnerResourceCreate(BaseModel):
    id: str | None = Field(default=None, min_length=2, max_length=160)
    payload: dict[str, Any]


class OwnerResourceAction(BaseModel):
    action: str = Field(min_length=2, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)


class OwnerApprovalDecision(BaseModel):
    status: Literal["approved", "rejected", "changes_requested"]
    reason: str = Field(default="", max_length=1000)


class OwnerSupportMessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    visibility: Literal["requester", "internal"] = "requester"


class OwnerSupportStatusUpdate(BaseModel):
    status: Literal["open", "in_progress", "waiting_user", "resolved", "closed"]
    assigned_to_id: str | None = None


class OwnerLicenseAction(BaseModel):
    action: Literal["suspend", "restore"]
    seats: int | None = Field(default=None, ge=1, le=100000)


class OwnerNotificationRuleUpdate(BaseModel):
    name: str | None = None
    event: str | None = None
    audience: str | None = None
    channels: list[Literal["in_app", "email", "push", "telegram", "whatsapp"]] | None = None
    enabled: bool | None = None
    severity: Literal["info", "warning", "critical"] | None = None


class OwnerReleaseDecision(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=2000)


class OwnerReleaseEvidence(BaseModel):
    event: Literal["deployment", "rollback"]
    commit: str = Field(min_length=7, max_length=64)
    image_digests: dict[str, str] = Field(default_factory=dict)
    validated: bool = True
    note: str = Field(default="", max_length=2000)


class OwnerOperationRequest(BaseModel):
    entity: Literal["project", "organization", "user"]
    operation: Literal["create", "update", "suspend", "restore", "delete"]
    id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


RESOURCE_DOMAINS = {
    "access",
    "approvals",
    "audit",
    "billing",
    "communications",
    "compliance",
    "costs",
    "executive",
    "global-command",
    "governance",
    "health",
    "incidents",
    "integrations",
    "notifications",
    "organizations",
    "policies",
    "projects",
    "recovery",
    "release",
    "secrets",
    "services",
    "staff",
    "system-map",
}

CREATABLE_DOMAINS = {"governance", "policies", "secrets"}
MAX_EVIDENCE_REFERENCES = 100
RELEASE_EVIDENCE_WINDOW = timedelta(hours=24)
RELEASE_RECOVERY_OPERATIONS = {
    "restore_validation",
    "test",
}
PROJECT_PAUSABLE_STATUSES = frozenset({"active", "in_progress", "planning", "running"})
PROJECT_RESUMABLE_STATUSES = frozenset({"paused"})
PROJECT_APPROVABLE_STATUSES = frozenset({"review"})
ORGANIZATION_PLANS = frozenset({"enterprise", "professional", "starter"})


def _metric_health_status(labels: dict[str, Any] | None) -> str:
    raw_status = str((labels or {}).get("status", "")).lower()
    if raw_status in {"healthy", "ready", "ok", "operational"}:
        return "healthy"
    if raw_status in {"warning", "degraded"}:
        return "warning"
    if raw_status in {"critical", "failed", "error", "unhealthy"}:
        return "critical"
    return "unknown"


CONTROL_DEFAULTS: dict[str, list[dict[str, Any]]] = {
    "services": [
        {
            "id": "openai",
            "name": "OpenAI",
            "category": "AI Providers",
            "description": "Chat, vision, embeddings, image and audio interfaces.",
            "enabled": bool(settings.OPENAI_API_KEY),
            "scope": "Owner governed",
        },
        {
            "id": "anthropic",
            "name": "Anthropic",
            "category": "AI Providers",
            "description": "Claude messages, tools, vision and streaming.",
            "enabled": bool(settings.ANTHROPIC_API_KEY),
            "scope": "Owner governed",
        },
        {
            "id": "gemini",
            "name": "Gemini",
            "category": "AI Providers",
            "description": "Models, files, vision, tools and safety controls.",
            "enabled": bool(settings.GOOGLE_API_KEY),
            "scope": "Owner governed",
        },
        {
            "id": "openrouter",
            "name": "OpenRouter",
            "category": "AI Providers",
            "description": "Multi-provider routing and cost-aware model access.",
            "enabled": bool(settings.OPENROUTER_API_KEY),
            "scope": "Owner governed",
        },
        {
            "id": "github",
            "name": "GitHub",
            "category": "Engineering",
            "description": "Repositories, issues, pull requests and releases.",
            "enabled": False,
            "scope": "Credential required",
        },
        {
            "id": "digitalocean",
            "name": "DigitalOcean",
            "category": "Cloud",
            "description": "Droplets, networking, storage and managed services.",
            "enabled": False,
            "scope": "Credential required",
        },
        {
            "id": "aws",
            "name": "AWS",
            "category": "Cloud",
            "description": "Compute, storage, networking and managed databases.",
            "enabled": bool(settings.AWS_ACCESS_KEY_ID),
            "scope": "Owner governed",
        },
        {
            "id": "postgres",
            "name": "PostgreSQL",
            "category": "Data",
            "description": "Primary operational and identity datastore.",
            "enabled": True,
            "scope": "Core platform",
        },
        {
            "id": "redis",
            "name": "Redis",
            "category": "Data",
            "description": "Cache, sessions, queues and coordination.",
            "enabled": True,
            "scope": "Core platform",
        },
        {
            "id": "vault",
            "name": "Secrets Vault",
            "category": "Security",
            "description": "External protected secret references and rotation state.",
            "enabled": True,
            "scope": "Owner only",
        },
    ],
    "integrations": [
        {
            "id": "postgres",
            "name": "PostgreSQL",
            "category": "data",
            "provider": "PostgreSQL",
            "status": "connected",
            "enabled": True,
            "endpoint": settings.POSTGRES_HOST,
            "lastCheck": "Pending live check",
        },
        {
            "id": "redis",
            "name": "Redis",
            "category": "data",
            "provider": "Redis",
            "status": "connected",
            "enabled": True,
            "endpoint": "Configured by REDIS_URL",
            "lastCheck": "Pending live check",
        },
        {
            "id": "openai",
            "name": "OpenAI",
            "category": "ai",
            "provider": "OpenAI",
            "status": "connected" if settings.OPENAI_API_KEY else "pending",
            "enabled": bool(settings.OPENAI_API_KEY),
            "endpoint": "Environment secret",
            "lastCheck": "Configuration check",
        },
        {
            "id": "anthropic",
            "name": "Anthropic",
            "category": "ai",
            "provider": "Anthropic",
            "status": "connected" if settings.ANTHROPIC_API_KEY else "pending",
            "enabled": bool(settings.ANTHROPIC_API_KEY),
            "endpoint": "Environment secret",
            "lastCheck": "Configuration check",
        },
        {
            "id": "gemini",
            "name": "Gemini",
            "category": "ai",
            "provider": "Google",
            "status": "connected" if settings.GOOGLE_API_KEY else "pending",
            "enabled": bool(settings.GOOGLE_API_KEY),
            "endpoint": "Environment secret",
            "lastCheck": "Configuration check",
        },
        {
            "id": "aws",
            "name": "AWS",
            "category": "cloud",
            "provider": "AWS",
            "status": "connected" if settings.AWS_ACCESS_KEY_ID else "pending",
            "enabled": bool(settings.AWS_ACCESS_KEY_ID),
            "endpoint": settings.AWS_S3_REGION or "Not configured",
            "lastCheck": "Configuration check",
        },
    ],
    "communications": [
        {
            "id": "in_app",
            "name": "In-app",
            "description": "Persistent notifications in the AIOS dashboard.",
            "enabled": True,
            "ownerOnly": False,
            "status": "ready",
        },
        {
            "id": "email",
            "name": "Email",
            "description": "SMTP delivery for project and incident notices.",
            "enabled": bool(settings.SMTP_HOST),
            "ownerOnly": False,
            "status": "ready" if settings.SMTP_HOST else "unconfigured",
        },
        {
            "id": "push",
            "name": "Push",
            "description": "Mobile and web push after recipient consent.",
            "enabled": False,
            "ownerOnly": False,
            "status": "unconfigured",
        },
        {
            "id": "telegram",
            "name": "Telegram",
            "description": "Owner-verified Telegram chat delivery and escalation.",
            "enabled": False,
            "ownerOnly": True,
            "status": "unconfigured",
        },
        {
            "id": "whatsapp",
            "name": "WhatsApp",
            "description": "Owner-only critical escalation channel.",
            "enabled": False,
            "ownerOnly": True,
            "status": "unconfigured",
        },
    ],
    "notification-rules": [
        {
            "id": "project-completed",
            "name": "Project completion",
            "event": "project.completed",
            "audience": "organization",
            "channels": ["in_app", "email"],
            "enabled": True,
            "severity": "info",
        },
        {
            "id": "owner-approval",
            "name": "Owner approval required",
            "event": "owner.approval.required",
            "audience": "owner",
            "channels": ["in_app", "email"],
            "enabled": True,
            "severity": "warning",
        },
        {
            "id": "critical-incident",
            "name": "Critical incident",
            "event": "incident.critical",
            "audience": "owner",
            "channels": ["in_app", "email", "push", "telegram", "whatsapp"],
            "enabled": True,
            "severity": "critical",
        },
    ],
    "policies": [
        {
            "id": "owner-approval",
            "name": "Owner approval for privileged actions",
            "description": "Declaration that sensitive release, meeting and infrastructure actions should require owner approval.",
            "scope": "global",
            "target": "Privileged operations",
            "status": "draft",
            "enabled": False,
            "enforcement": "mandatory",
        },
        {
            "id": "provider-cost",
            "name": "Provider cost ceiling",
            "description": "Declaration for keeping AI provider use within owner-approved budgets.",
            "scope": "global",
            "target": "AI providers",
            "status": "draft",
            "enabled": False,
            "enforcement": "mandatory",
        },
        {
            "id": "medical-review",
            "name": "Internal staff medical oversight",
            "description": "Internal staff health reviews follow owner governance and privacy controls.",
            "scope": "global",
            "target": "Internal workforce",
            "status": "paused",
            "enabled": False,
            "enforcement": "advisory",
        },
    ],
    "compliance": [
        {
            "id": "iso-access",
            "framework": "ISO 27001",
            "control": "Privileged access review",
            "owner": "Security",
            "status": "not_assessed",
            "evidence": 0,
            "updatedAt": _iso(),
        },
        {
            "id": "soc-audit",
            "framework": "SOC 2",
            "control": "Owner action audit trail",
            "owner": "Governance",
            "status": "not_assessed",
            "evidence": 0,
            "updatedAt": _iso(),
        },
        {
            "id": "gdpr-retention",
            "framework": "GDPR",
            "control": "Data retention and deletion",
            "owner": "Privacy",
            "status": "not_assessed",
            "evidence": 0,
            "updatedAt": _iso(),
        },
    ],
    "costs": [
        {
            "id": "openai",
            "service": "OpenAI",
            "category": "AI Provider",
            "monthlyLimit": 0,
            "used": None,
            "enabled": bool(settings.OPENAI_API_KEY),
        },
        {
            "id": "anthropic",
            "service": "Anthropic",
            "category": "AI Provider",
            "monthlyLimit": 0,
            "used": None,
            "enabled": bool(settings.ANTHROPIC_API_KEY),
        },
        {
            "id": "aws",
            "service": "AWS",
            "category": "Infrastructure",
            "monthlyLimit": 0,
            "used": None,
            "enabled": bool(settings.AWS_ACCESS_KEY_ID),
        },
        {
            "id": "database",
            "service": "Managed Databases",
            "category": "Data",
            "monthlyLimit": 0,
            "used": None,
            "enabled": True,
        },
    ],
    "governance": [],
    "release": [
        {
            "id": "validation",
            "name": "Live Dependency Validation",
            "owner": "Chief Engineer",
            "status": "pending",
        },
        {
            "id": "security",
            "name": "Critical Incident Clearance",
            "owner": "Security Council",
            "status": "pending",
        },
        {
            "id": "performance",
            "name": "Performance Telemetry Status",
            "owner": "Platform Team",
            "status": "pending",
        },
        {
            "id": "backup",
            "name": "Backup & Restore Verification",
            "owner": "Operations",
            "status": "pending",
        },
        {
            "id": "approval",
            "name": "Final Owner Approval",
            "owner": "Owner",
            "status": "pending",
        },
    ],
}


def _normalize_default(domain: str, item: dict[str, Any]) -> OwnerControlRecord:
    payload = dict(item)
    resource_id = str(payload.pop("id"))
    record_status = str(payload.pop("status", "active"))
    enabled = bool(payload.pop("enabled", True))
    return OwnerControlRecord(
        domain=domain,
        resource_id=resource_id,
        status=record_status,
        enabled=enabled,
        payload=payload,
    )


async def _ensure_defaults(session: AsyncSession, domain: str) -> None:
    defaults = CONTROL_DEFAULTS.get(domain, [])
    if not defaults:
        return

    had_pending_work = bool(
        session.new
        or session.dirty
        or session.deleted
        or session.info.get("owner_mutation_active")
    )
    existing = set(
        (
            await session.scalars(
                select(OwnerControlRecord.resource_id).where(
                    OwnerControlRecord.domain == domain
                )
            )
        ).all()
    )
    missing = [item for item in defaults if item["id"] not in existing]
    if not missing:
        return

    now = _now()
    values: list[dict[str, Any]] = []
    for item in missing:
        record = _normalize_default(domain, item)
        values.append(
            {
                "id": uuid_str(),
                "domain": record.domain,
                "resource_id": record.resource_id,
                "status": record.status,
                "enabled": record.enabled,
                "payload": record.payload,
                "version": 1,
                "created_at": now,
                "updated_at": now,
            }
        )

    # Multiple API workers can serve the first GET simultaneously. A PostgreSQL
    # upsert keeps first-use seeding idempotent without the SELECT -> INSERT race.
    statement = (
        postgres_insert(OwnerControlRecord)
        .values(values)
        .on_conflict_do_nothing(
            index_elements=[
                OwnerControlRecord.domain,
                OwnerControlRecord.resource_id,
            ],
        )
    )
    if had_pending_work:
        # Never commit an in-flight owner command merely because it touched an
        # unseeded domain. Seed through an independent transaction instead.
        async with SessionLocal() as seed_session:
            await seed_session.execute(statement)
            await seed_session.commit()
    else:
        await session.execute(statement)
        # Defaults are durable configuration. Persist them even on a read request.
        await session.commit()


def _control_item(record: OwnerControlRecord) -> dict[str, Any]:
    item = dict(record.payload)
    item.update(
        id=record.resource_id,
        status=record.status,
        enabled=record.enabled,
        version=record.version,
        updatedAt=_iso(record.updated_at),
    )
    return item


async def _control_items(session: AsyncSession, domain: str) -> list[dict[str, Any]]:
    await _ensure_defaults(session, domain)
    records = (
        await session.scalars(
            select(OwnerControlRecord)
            .where(OwnerControlRecord.domain == domain)
            .order_by(OwnerControlRecord.created_at, OwnerControlRecord.resource_id)
        )
    ).all()
    return [_control_item(record) for record in records]


def _configured_integrations() -> dict[str, bool]:
    return {
        "postgres": True,
        "redis": True,
        "openai": bool(settings.OPENAI_API_KEY),
        "anthropic": bool(settings.ANTHROPIC_API_KEY),
        "gemini": bool(settings.GOOGLE_API_KEY),
        "aws": bool(settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY),
    }


async def _integration_items(session: AsyncSession) -> list[dict[str, Any]]:
    records = await _control_items(session, "integrations")
    configured = _configured_integrations()
    live_health = {item["id"]: item for item in await _health_items(session)}
    items: list[dict[str, Any]] = []
    for item in records:
        integration_id = item["id"]
        health_id = {"postgres": "database", "redis": "redis"}.get(integration_id)
        protected = health_id is not None
        is_configured = configured.get(integration_id, False)
        if health_id:
            health_status = str(live_health[health_id]["status"])
            status_value = "connected" if health_status == "healthy" else "unavailable"
            last_check = _iso()
        else:
            status_value = (
                "configured"
                if is_configured and item["enabled"]
                else "disabled" if is_configured else "unconfigured"
            )
            last_check = str(item.get("lastCheck", item["updatedAt"]))
        items.append(
            {
                **item,
                "configured": is_configured,
                "protected": protected,
                "status": status_value,
                "enabled": True if protected else item["enabled"],
                "lastCheck": last_check,
            }
        )
    return items


async def _service_items(session: AsyncSession) -> list[dict[str, Any]]:
    return [
        {
            **item,
            "protected": item["id"] in {"postgres", "redis", "vault"},
        }
        for item in await _control_items(session, "services")
    ]


async def _communication_items(session: AsyncSession) -> list[dict[str, Any]]:
    controls = {
        str(item["id"]): item for item in await _control_items(session, "communications")
    }
    statistics = await communications.delivery_statistics(session)
    channel_counts = statistics["by_channel"]
    items: list[dict[str, Any]] = []
    descriptions = {
        "in_app": "Persistent tenant-scoped notifications with read receipts.",
        "email": "SMTP delivery with durable attempts and receipts.",
        "push": "Firebase mobile and web push after endpoint registration.",
        "telegram": "Owner-verified Telegram chat delivery and escalation.",
        "whatsapp": "Owner-controlled WhatsApp critical escalation.",
    }
    for readiness in statistics["readiness"]:
        channel_id = str(readiness["id"])
        configured = bool(readiness["configured"])
        protected = channel_id == "in_app"
        requested_enabled = bool(controls.get(channel_id, {}).get("enabled", True))
        enabled = True if protected else bool(configured and requested_enabled)
        items.append(
            {
                "id": channel_id,
                "name": readiness["name"],
                "description": descriptions[channel_id],
                "configured": configured,
                "protected": protected,
                "ownerOnly": bool(readiness["owner_only"]),
                "enabled": enabled,
                "status": "ready" if enabled else ("disabled" if configured else "unconfigured"),
                "reason": readiness["reason"],
                "capabilities": readiness["capabilities"],
                "deliveries": int(channel_counts.get(channel_id, 0)),
            }
        )
    return items


def _send_owner_test_email(recipient: str) -> dict[str, Any]:
    if not settings.SMTP_HOST:
        raise RuntimeError("SMTP is not configured")

    message = EmailMessage()
    message["Subject"] = "AIONEX Owner channel test"
    message["From"] = settings.SMTP_USER or "noreply@aionex.local"
    message["To"] = recipient
    message.set_content(
        "The AIONEX Owner email notification channel is configured and reachable."
    )

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
        smtp.ehlo()
        if settings.SMTP_TLS:
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        if settings.SMTP_USER:
            if not settings.SMTP_PASSWORD:
                raise RuntimeError("SMTP password is not configured")
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        refused = smtp.send_message(message)
    if refused:
        raise RuntimeError("SMTP server refused one or more recipients")
    return {"recipient": recipient, "provider": settings.SMTP_HOST}


async def _organization_counts(
    session: AsyncSession,
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    user_rows = (
        await session.execute(
            select(User.organization_id, func.count(User.id))
            .where(User.deleted_at.is_(None))
            .group_by(User.organization_id)
        )
    ).all()
    project_rows = (
        await session.execute(
            select(Project.organization_id, func.count(Project.id)).group_by(
                Project.organization_id
            )
        )
    ).all()
    active_user_rows = (
        await session.execute(
            select(User.organization_id, func.count(User.id))
            .where(User.deleted_at.is_(None), User.status == "active")
            .group_by(User.organization_id)
        )
    ).all()
    return dict(user_rows), dict(active_user_rows), dict(project_rows)


async def _access_items(session: AsyncSession) -> list[dict[str, Any]]:
    user_counts = dict(
        (
            await session.execute(
                select(User.role_id, func.count(User.id))
                .where(User.deleted_at.is_(None))
                .group_by(User.role_id)
            )
        ).all()
    )
    rows = (
        await session.execute(
            select(Role, Organization.name)
            .outerjoin(Organization, Organization.id == Role.organization_id)
            .where(Role.status != "deleted")
            .order_by(Organization.name, Role.name, Role.id)
        )
    ).all()
    return [
        {
            "id": role.id,
            "name": role.name,
            "organization": organization_name or "Platform",
            "organizationId": role.organization_id,
            "scope": "Global" if role.name == "Super Owner" else "Organization",
            "users": user_counts.get(role.id, 0),
            "status": "protected" if role.name == "Super Owner" else role.status,
        }
        for role, organization_name in rows
    ]


async def _organization_items(
    session: AsyncSession,
    protected_organization_id: str | None = None,
) -> list[dict[str, Any]]:
    user_counts, active_user_counts, project_counts = await _organization_counts(
        session
    )
    organizations = (
        await session.scalars(select(Organization).order_by(Organization.name))
    ).all()
    return [
        {
            "id": item.id,
            "name": item.name,
            "organization": item.name,
            "plan": item.plan,
            "users": user_counts.get(item.id, 0),
            "activeUsers": active_user_counts.get(item.id, 0),
            "projects": project_counts.get(item.id, 0),
            "services": None,
            "status": item.status,
            "risk": "high" if item.status in {"suspended", "restricted"} else "low",
            "protected": item.id == protected_organization_id,
            "updatedAt": _iso(item.updated_at),
        }
        for item in organizations
    ]


async def _billing_items(
    session: AsyncSession,
    protected_organization_id: str | None = None,
) -> list[dict[str, Any]]:
    organizations = await _organization_items(session, protected_organization_id)
    display = {
        "free": "Free",
        "starter": "Starter",
        "team": "Team",
        "professional": "Professional",
        "enterprise": "Enterprise",
    }
    return [
        {
            "id": item["id"],
            "organization": item["name"],
            "plan": display.get(str(item["plan"]).lower(), str(item["plan"]).title()),
            "status": (
                "suspended"
                if item["status"] in {"suspended", "inactive", "restricted"}
                else "active"
            ),
            "seats": item["users"],
            "activeSeats": item["activeUsers"],
            "protected": item["protected"],
        }
        for item in organizations
    ]


async def _project_items(session: AsyncSession) -> list[dict[str, Any]]:
    approval_counts = dict(
        (
            await session.execute(
                select(Meeting.project_id, func.count(Meeting.id))
                .where(
                    Meeting.project_id.is_not(None),
                    Meeting.status.in_(["pending", "pending_approval"]),
                )
                .group_by(Meeting.project_id)
            )
        ).all()
    )
    rows = (
        await session.execute(
            select(Project, Organization.name, User.name)
            .join(Organization, Organization.id == Project.organization_id)
            .join(User, User.id == Project.owner_id)
            .order_by(Project.updated_at.desc())
        )
    ).all()
    return [
        {
            "id": project.id,
            "name": project.name,
            "owner": owner_name,
            "organization": organization_name,
            "status": project.status,
            "risk": project.risk,
            "priority": project.priority,
            "reviewStatus": project.review_status,
            "progress": project.progress,
            "approvals": approval_counts.get(project.id, 0),
            "approvedById": project.approved_by_id,
            "approvedAt": _iso(project.approved_at) if project.approved_at else None,
            "completedAt": _iso(project.completed_at) if project.completed_at else None,
            "archivedAt": _iso(project.archived_at) if project.archived_at else None,
            "version": project.version,
            "updatedAt": _iso(project.updated_at),
        }
        for project, organization_name, owner_name in rows
    ]


def _timeline_category(source: str | None, action: str) -> str:
    normalized = _normalized_key(source or "")
    normalized_action = _normalized_key(action)
    if normalized in {
        "project",
        "projects",
        "task",
        "tasks",
        "workflow",
        "workflows",
        "workspace",
        "workspaces",
    }:
        return "project"
    if normalized in {
        "access",
        "organization",
        "organizations",
        "permission",
        "permissions",
        "role",
        "roles",
        "staff",
        "user",
        "users",
    }:
        return "user"
    if normalized in {"approval", "approvals", "meeting", "meetings"}:
        return "approval"
    if normalized in {"alert", "alerts", "incident", "incidents"}:
        return "incident"
    if normalized in {
        "compliance",
        "secret",
        "secrets",
        "security",
        "securityintegration",
    } or any(
        marker in normalized_action
        for marker in ("auth", "permission", "role", "security", "session")
    ):
        return "security"
    return "service"


async def _audit_items(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(AuditEvent, User.name)
            .outerjoin(User, User.id == AuditEvent.user_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(250)
        )
    ).all()
    items = [
        {
            "id": event.id,
            "actor": user_name or "System",
            "action": event.action,
            "target": event.resource_id or event.resource_type or "platform",
            "category": _timeline_category(event.resource_type, event.action),
            "severity": event.details.get("severity", "info"),
            "status": event.details.get("status", "completed"),
            "timestamp": _iso(event.created_at),
        }
        for event, user_name in rows
    ]
    commands = (
        await session.scalars(
            select(OwnerCommandRecord)
            .order_by(OwnerCommandRecord.created_at.desc())
            .limit(250)
        )
    ).all()
    items.extend(
        {
            "id": command.id,
            "actor": "Super Owner",
            "action": f"{command.domain}.{command.action}",
            "target": command.resource_id or command.domain,
            "category": _timeline_category(command.domain, command.action),
            "severity": "critical" if command.status == "failed" else "info",
            "status": command.status,
            "timestamp": _iso(command.created_at),
        }
        for command in commands
    )
    return sorted(items, key=lambda item: item["timestamp"], reverse=True)[:250]


async def _notification_items(
    session: AsyncSession, actor: UserRecord
) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.scalars(
                select(Notification)
                .order_by(Notification.created_at.desc())
                .limit(200)
            )
        ).all()
    )
    ids = [item.id for item in rows]
    deliveries = (
        list(
            (
                await session.scalars(
                    select(NotificationDelivery).where(
                        NotificationDelivery.notification_id.in_(ids)
                    )
                )
            ).all()
        )
        if ids
        else []
    )
    delivery_map: dict[str, list[dict[str, Any]]] = {}
    for delivery in deliveries:
        delivery_map.setdefault(delivery.notification_id, []).append(
            communications.delivery_snapshot(delivery)
        )
    return [
        {
            "id": item.id,
            "organizationId": item.organization_id,
            "recipientId": item.recipient_id,
            "title": item.title,
            "message": item.message,
            "type": item.type,
            "event": item.event_key,
            "category": item.category,
            "severity": item.severity,
            "read": item.read_at is not None,
            "archived": item.archived_at is not None,
            "deliveries": delivery_map.get(item.id, []),
            "createdAt": _iso(item.created_at),
        }
        for item in rows
    ]


async def _incident_items(session: AsyncSession) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.scalars(
                select(Alert).order_by(Alert.created_at.desc()).limit(200)
            )
        ).all()
    )
    return [
        {
            **communications.incident_snapshot(item),
            "startedAt": _iso(item.created_at),
            "owner": item.assigned_to_id or "Platform Operations",
        }
        for item in rows
    ]


async def _backup_artifact_ready(
    backup: BackupRecord | None,
    *,
    verify_checksum: bool,
) -> bool:
    """Check live protected storage without blocking the async event loop."""

    if (
        backup is None
        or backup.status != "completed"
        or not backup.location
        or not backup.checksum
        or backup.size_bytes is None
        or backup.size_bytes <= 0
    ):
        return False
    try:
        await asyncio.to_thread(
            get_backup_executor().verify_artifact,
            backup.location,
            backup.checksum,
            backup.size_bytes,
            verify_checksum=verify_checksum,
        )
    except BackupExecutionError:
        return False
    return True


async def _recovery_items(session: AsyncSession) -> list[dict[str, Any]]:
    backups = (
        await session.scalars(
            select(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(100)
        )
    ).all()
    runs = (
        await session.scalars(
            select(DisasterRecoveryRun)
            .order_by(DisasterRecoveryRun.created_at.desc())
            .limit(100)
        )
    ).all()
    latest_artifact = await session.scalar(
        select(BackupRecord)
        .where(
            BackupRecord.status == "completed",
            BackupRecord.location.is_not(None),
            BackupRecord.checksum.is_not(None),
            BackupRecord.size_bytes.is_not(None),
            BackupRecord.size_bytes > 0,
        )
        .order_by(BackupRecord.completed_at.desc())
        .limit(1)
    )
    latest_artifact_ready = await _backup_artifact_ready(
        latest_artifact,
        verify_checksum=False,
    )

    def backup_item(item: BackupRecord) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.scope,
            "kind": item.kind,
            "requestedAt": _iso(item.created_at),
            "completedAt": _iso(item.completed_at) if item.completed_at else None,
            "status": item.status,
            "checksum": item.checksum,
            "artifactReady": bool(
                latest_artifact_ready
                and latest_artifact is not None
                and item.id == latest_artifact.id
            ),
        }

    items = [backup_item(item) for item in backups]
    items.extend(
        {
            "id": item.id,
            "name": item.region or "Platform",
            "kind": item.operation,
            "requestedAt": _iso(item.created_at),
            "completedAt": _iso(item.completed_at) if item.completed_at else None,
            "status": item.status,
            "checksum": None,
            "artifactReady": False,
        }
        for item in runs
    )
    visible = sorted(
        items,
        key=lambda item: item["requestedAt"],
        reverse=True,
    )[:100]
    if latest_artifact is not None and latest_artifact.id not in {
        item["id"] for item in visible
    }:
        visible = sorted(
            [*visible[:99], backup_item(latest_artifact)],
            key=lambda item: item["requestedAt"],
            reverse=True,
        )
    return visible


async def _staff_items(session: AsyncSession) -> list[dict[str, Any]]:
    organization_rows = (
        await session.execute(select(Organization.id, Organization.name))
    ).all()
    organization_names = {str(item[0]): str(item[1]) for item in organization_rows}
    for organization_id in organization_names:
        await workforce_service.sync_human_workforce(session, organization_id)

    legacy_records = list(
        (
            await session.scalars(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == "digital-workforce"
                )
            )
        ).all()
    )
    legacy_payload_by_member: dict[str, dict[str, Any]] = {}
    for record in legacy_records:
        payload = record.payload if isinstance(record.payload, dict) else {}
        organization_id = str(payload.get("organization_id") or "")
        if organization_id not in organization_names:
            continue
        key = f"legacy:{record.resource_id}"[:160]
        existing = await session.scalar(
            select(WorkforceMember).where(
                WorkforceMember.organization_id == organization_id,
                WorkforceMember.worker_key == key,
            )
        )
        if existing is None:
            existing = WorkforceMember(
                id=uuid_str(),
                organization_id=organization_id,
                worker_key=key,
                kind="digital",
                name=str(payload.get("worker_id") or record.resource_id),
                role=str(payload.get("role") or "Digital Worker"),
                department=str(payload.get("department") or "Unassigned"),
                ministry=(str(payload.get("ministry_id") or "").strip() or None),
                grade=int(payload.get("grade") or 1),
                status=str(payload.get("employment_state") or record.status),
                skills=list(payload.get("skills") or []),
                certifications=list(payload.get("certifications") or []),
                restrictions=list(payload.get("restrictions") or []),
                warnings=list(payload.get("warnings") or []),
                provider_neutral=True,
                profile_metadata={
                    "legacy_resource_id": record.resource_id,
                    "provider_activation": "deferred_to_29J",
                    "legacy_project_id": payload.get("project_id"),
                    "legacy_execution_id": payload.get("execution_id"),
                },
                version=max(1, record.version),
            )
            session.add(existing)
        else:
            existing.name = str(payload.get("worker_id") or existing.name)
            existing.role = str(payload.get("role") or existing.role)
            existing.department = str(payload.get("department") or existing.department)
            existing.ministry = str(payload.get("ministry_id") or "").strip() or existing.ministry
            existing.status = str(payload.get("employment_state") or record.status)
            existing.certifications = list(payload.get("certifications") or existing.certifications or [])
            existing.restrictions = list(payload.get("restrictions") or existing.restrictions or [])
            existing.warnings = list(payload.get("warnings") or existing.warnings or [])
            existing.profile_metadata = {
                **(existing.profile_metadata or {}),
                "legacy_resource_id": record.resource_id,
                "provider_activation": "deferred_to_29J",
                "legacy_project_id": payload.get("project_id"),
                "legacy_execution_id": payload.get("execution_id"),
            }
        legacy_payload_by_member[existing.id] = payload
    await session.flush()

    role_rows = (
        await session.execute(
            select(User.id, Role.name)
            .outerjoin(Role, Role.id == User.role_id)
            .where(User.deleted_at.is_(None))
        )
    ).all()
    roles = {str(user_id): str(role_name or "Unassigned") for user_id, role_name in role_rows}
    members = list(
        (
            await session.scalars(
                select(WorkforceMember).order_by(
                    WorkforceMember.kind,
                    WorkforceMember.name,
                )
            )
        ).all()
    )
    members = [
        item
        for item in members
        if not (item.kind == "human" and roles.get(str(item.user_id)) == "Super Owner")
    ]
    metrics = await workforce_service.member_metrics(
        session, [item.id for item in members]
    )
    assessments = list(
        (
            await session.scalars(
                select(AcademyAssessment).order_by(
                    AcademyAssessment.worker_id,
                    AcademyAssessment.created_at.desc(),
                )
            )
        ).all()
    )
    latest_assessment: dict[str, AcademyAssessment] = {}
    for assessment in assessments:
        latest_assessment.setdefault(assessment.worker_id, assessment)

    staff: list[dict[str, Any]] = []
    for item in members:
        current = metrics.get(item.id, {})
        performance = current.get("performance") or {}
        health = current.get("health")
        assessment = latest_assessment.get(item.id)
        legacy_payload = legacy_payload_by_member.get(item.id, {})

        def metric_value(
            name: str,
            fallback: Any = None,
            *,
            _performance: dict[str, Any] = performance,
            _legacy_payload: dict[str, Any] = legacy_payload,
        ) -> Any:
            value = _performance.get(name)
            if value is not None:
                return value
            return _legacy_payload.get(name, fallback)
        staff.append(
            {
                "id": item.id,
                "kind": item.kind,
                "name": item.name,
                "role": item.role,
                "department": item.department,
                "ministry": item.ministry,
                "organization": organization_names.get(
                    item.organization_id, item.organization_id
                ),
                "organizationId": item.organization_id,
                "status": item.status,
                "performance": metric_value("quality"),
                "operationalHealth": (
                    health.operational_health
                    if health is not None
                    else legacy_payload.get("operational_health")
                ),
                "trust": (
                    health.trust
                    if health is not None
                    else metric_value("policy", legacy_payload.get("trust"))
                ),
                "learning": (
                    health.learning
                    if health is not None
                    else metric_value("learning")
                ),
                "successCount": current.get(
                    "success_count", legacy_payload.get("success_count", 0)
                ),
                "failureCount": current.get(
                    "failure_count", legacy_payload.get("failure_count", 0)
                ),
                "recommendation": (
                    health.recommendation
                    if health is not None
                    else legacy_payload.get("recommendation")
                ),
                "restrictions": list(item.restrictions or []),
                "warnings": list(item.warnings or []),
                "certifications": list(item.certifications or []),
                "training": (
                    {
                        "course_id": assessment.course_id,
                        "score": assessment.score,
                        "passed": assessment.passed,
                    }
                    if assessment is not None
                    else legacy_payload.get("training")
                ),
                "lastEvaluatedAt": (
                    _iso(health.created_at)
                    if health is not None
                    else legacy_payload.get("last_evaluated_at")
                ),
                "projectId": legacy_payload.get("project_id"),
                "executionId": legacy_payload.get("execution_id"),
                "grade": item.grade,
                "providerNeutral": item.provider_neutral,
                "version": item.version,
            }
        )
    await session.commit()
    return sorted(
        staff,
        key=lambda item: (
            item["kind"] != "digital",
            str(item["organization"]).lower(),
            str(item["department"]).lower(),
            str(item["name"]).lower(),
        ),
    )


async def _system_map_items(session: AsyncSession) -> list[dict[str, Any]]:
    started = perf_counter()
    await session.execute(text("SELECT 1"))
    database_latency = max(1, round((perf_counter() - started) * 1000))
    database_connections: int | None = None
    if session.get_bind().dialect.name == "postgresql":
        database_connections = int(
            (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database()"
                    )
                )
            )
            or 0
        )
    try:
        load_average = os.getloadavg()[0]
        cpu_count = max(1, os.cpu_count() or 1)
        runtime_load: float | None = round(
            min(100, load_average / cpu_count * 100),
            1,
        )
    except (AttributeError, OSError):
        runtime_load = None
    redis_health = "offline"
    redis_latency: int | None = None
    redis_connections: int | None = None
    try:
        redis = await get_redis()
        redis_started = perf_counter()
        if await redis.ping():
            redis_health = "healthy"
            redis_latency = max(1, round((perf_counter() - redis_started) * 1000))
            try:
                client_info = await redis.info("clients")
                connected_clients = client_info.get("connected_clients")
                if isinstance(connected_clients, int):
                    redis_connections = connected_clients
            except Exception:
                redis_connections = None
    except Exception:
        redis_health = "offline"

    items: list[dict[str, Any]] = [
        {
            "id": "api-runtime",
            "name": socket.gethostname(),
            "kind": "server",
            "region": os.getenv("AIOS_REGION", "Configured runtime"),
            "health": "healthy",
            "latency": None,
            "load": runtime_load,
            "connections": None,
            "endpoint": None,
        },
        {
            "id": "postgres-primary",
            "name": settings.POSTGRES_HOST,
            "kind": "database",
            "region": os.getenv("AIOS_REGION", "Configured runtime"),
            "health": "healthy",
            "latency": database_latency,
            "load": None,
            "connections": database_connections,
            "endpoint": f"{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}",
        },
        {
            "id": "redis-primary",
            "name": "Redis",
            "kind": "service",
            "region": os.getenv("AIOS_REGION", "Configured runtime"),
            "health": redis_health,
            "latency": redis_latency,
            "load": None,
            "connections": redis_connections,
            "endpoint": "redis:6379",
        },
    ]
    try:
        inventory = await operations_assurance.service_inventory(session)
    except Exception:
        inventory = []
    existing = {item["id"] for item in items}
    for component in inventory:
        if component["id"] in existing or component["id"] == "backend":
            continue
        items.append(
            {
                "id": component["id"],
                "name": component["name"],
                "kind": component["kind"],
                "region": os.getenv("AIOS_REGION", "Configured runtime"),
                "health": component["health"],
                "latency": component.get("latency_ms"),
                "load": None,
                "connections": None,
                "endpoint": component.get("endpoint"),
            }
        )
    return items


async def _health_items(session: AsyncSession) -> list[dict[str, Any]]:
    nodes = await _system_map_items(session)
    nodes_by_id = {node["id"]: node for node in nodes}
    database = nodes_by_id.get("postgres-primary")
    redis = nodes_by_id.get("redis-primary")
    active_alerts = int(
        (
            await session.scalar(
                select(func.count(Alert.id)).where(Alert.status != "resolved")
            )
        )
        or 0
    )
    critical_alerts = int(
        (
            await session.scalar(
                select(func.count(Alert.id)).where(
                    Alert.status != "resolved",
                    Alert.severity == "critical",
                )
            )
        )
        or 0
    )
    component_failures = [
        node for node in nodes if node["id"] != "runtime-node" and node["health"] != "healthy"
    ]
    return [
        {
            "id": "database",
            "name": "PostgreSQL",
            "status": database["health"] if database else "unhealthy",
            "detail": (
                f"{database['latency']} ms query latency"
                if database and database.get("latency") is not None
                else "PostgreSQL probe unavailable"
            ),
        },
        {
            "id": "redis",
            "name": "Redis",
            "status": redis["health"] if redis else "unhealthy",
            "detail": (
                f"{redis['latency']} ms ping latency"
                if redis and redis.get("latency") is not None
                else "Redis ping unavailable"
            ),
        },
        {
            "id": "backend",
            "name": "Owner API",
            "status": nodes_by_id.get("api-runtime", {}).get("health", "unhealthy"),
            "detail": f"AIONEX AIOS {settings.APP_VERSION}",
        },
        {
            "id": "runtime-components",
            "name": "Runtime components",
            "status": "healthy" if not component_failures else "degraded",
            "detail": (
                f"{len(nodes)-1} component(s) probed, {len(component_failures)} unavailable"
            ),
        },
        {
            "id": "operations",
            "name": "Operations runtime",
            "status": "degraded" if critical_alerts or component_failures else "healthy",
            "detail": (
                f"{active_alerts} active alert(s), {critical_alerts} critical, "
                f"{len(component_failures)} unavailable component(s)"
            ),
        },
    ]


async def _global_command_items(
    session: AsyncSession,
    protected_organization_id: str | None = None,
) -> list[dict[str, Any]]:
    organizations = await _organization_items(session, protected_organization_id)
    projects = await _project_items(session)
    services = await _service_items(session)
    return [
        *[
            {
                "id": item["id"],
                "name": item["name"],
                "type": "organization",
                "owner": "Super Owner",
                "status": item["status"],
                "risk": item["risk"],
                "protected": item["protected"],
                "updatedAt": item["updatedAt"],
            }
            for item in organizations
        ],
        *[
            {
                "id": item["id"],
                "name": item["name"],
                "type": "project",
                "owner": item["owner"],
                "status": item["status"],
                "risk": item["risk"],
                "updatedAt": item["updatedAt"],
            }
            for item in projects
        ],
        *[
            {
                "id": item["id"],
                "name": item["name"],
                "type": "service",
                "owner": "Platform",
                "status": "active" if item["enabled"] else "paused",
                "risk": "low",
                "protected": item["protected"],
                "updatedAt": item["updatedAt"],
            }
            for item in services
        ],
    ]


async def _executive_items(session: AsyncSession) -> list[dict[str, Any]]:
    user_count = await session.scalar(
        select(func.count(User.id)).where(User.deleted_at.is_(None))
    )
    project_count = await session.scalar(select(func.count(Project.id)))
    organization_count = await session.scalar(select(func.count(Organization.id)))
    active_alerts = await session.scalar(
        select(func.count(Alert.id)).where(Alert.status != "resolved")
    )
    return [
        {
            "id": "organizations",
            "label": "Organizations",
            "value": int(organization_count or 0),
            "unit": "",
            "trend": None,
            "status": "good",
        },
        {
            "id": "projects",
            "label": "Projects",
            "value": int(project_count or 0),
            "unit": "",
            "trend": None,
            "status": "good",
        },
        {
            "id": "users",
            "label": "Users",
            "value": int(user_count or 0),
            "unit": "",
            "trend": None,
            "status": "good",
        },
        {
            "id": "alerts",
            "label": "Active incidents",
            "value": int(active_alerts or 0),
            "unit": "",
            "trend": None,
            "status": "watch" if active_alerts else "good",
        },
    ]


async def _resource_items(
    session: AsyncSession, domain: str, actor: UserRecord
) -> list[dict[str, Any]]:
    if domain not in RESOURCE_DOMAINS:
        raise HTTPException(status_code=404, detail="Unknown owner resource domain")
    if domain == "access":
        return await _access_items(session)
    if domain == "approvals":
        return await _approval_items(session)
    if domain == "audit":
        return await _audit_items(session)
    if domain == "billing":
        return await _billing_items(session, actor.organization_id)
    if domain == "communications":
        return await _communication_items(session)
    if domain == "executive":
        return await _executive_items(session)
    if domain == "global-command":
        return await _global_command_items(session, actor.organization_id)
    if domain == "health":
        return await _health_items(session)
    if domain == "incidents":
        return await _incident_items(session)
    if domain == "integrations":
        return await _integration_items(session)
    if domain == "notifications":
        return await _notification_items(session, actor)
    if domain == "organizations":
        return await _organization_items(session, actor.organization_id)
    if domain == "projects":
        return await _project_items(session)
    if domain == "recovery":
        return await _recovery_items(session)
    if domain == "staff":
        return await _staff_items(session)
    if domain == "services":
        return await _service_items(session)
    if domain == "system-map":
        return await _system_map_items(session)
    return await _control_items(session, domain)


async def _collection(
    session: AsyncSession, domain: str, actor: UserRecord
) -> OwnerResourceCollection:
    return OwnerResourceCollection(
        domain=domain,
        generatedAt=_iso(),
        items=await _resource_items(session, domain, actor),
    )


async def _record_command(
    session: AsyncSession,
    actor: UserRecord,
    domain: str,
    resource_id: str | None,
    action: str,
    request: dict[str, Any],
) -> OwnerCommandRecord:
    command = OwnerCommandRecord(
        actor_id=actor.id,
        domain=domain,
        resource_id=resource_id,
        action=action,
        request=_redact_sensitive(request),
        status="accepted",
    )
    session.add(command)
    await session.flush()
    return command


def _finish_command(
    command: OwnerCommandRecord, result: dict[str, Any] | None = None
) -> None:
    command.status = "completed"
    command.result = _redact_sensitive(result or {})
    command.completed_at = _now()


def _failure_result(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, HTTPException):
        return {
            "statusCode": exc.status_code,
            "detail": _redact_sensitive(exc.detail),
        }
    # Database driver messages can include connection URLs. Persist the
    # exception class for diagnosis without risking credential disclosure.
    return {"exception": type(exc).__name__}


async def _persist_failed_command(
    session: AsyncSession,
    *,
    command: OwnerCommandRecord,
    actor: UserRecord,
    request: dict[str, Any],
    exc: Exception,
) -> None:
    """Rollback the failed unit of work and persist its audit independently."""

    snapshot = {
        "id": command.id,
        "domain": command.domain,
        "resource_id": command.resource_id,
        "action": command.action,
        "created_at": command.created_at or _now(),
    }
    try:
        await session.rollback()
    except Exception:
        # The independent session below may still be able to record a driver or
        # transaction failure after the request session became invalid.
        pass

    failure = _failure_result(exc)
    try:
        async with SessionLocal() as audit_session:
            audit_session.add(
                OwnerCommandRecord(
                    id=snapshot["id"],
                    actor_id=actor.id,
                    domain=snapshot["domain"],
                    resource_id=snapshot["resource_id"],
                    action=snapshot["action"],
                    status="failed",
                    request=_redact_sensitive(request),
                    result=failure,
                    error=(
                        str(_redact_sensitive(exc.detail))[:2000]
                        if isinstance(exc, HTTPException)
                        else type(exc).__name__
                    ),
                    created_at=snapshot["created_at"],
                    completed_at=_now(),
                )
            )
            audit_session.add(
                AuditEvent(
                    organization_id=actor.organization_id,
                    user_id=actor.id,
                    action=f"owner.{snapshot['domain']}.{snapshot['action']}",
                    resource_type=snapshot["domain"],
                    resource_id=snapshot["resource_id"],
                    details={"status": "failed", "result": failure},
                )
            )
            await audit_session.commit()
    except Exception:
        # Never replace the original domain/HTTP/database failure with an audit
        # persistence failure.
        pass


async def _run_audited_mutation(
    session: AsyncSession,
    *,
    actor: UserRecord,
    domain: str,
    resource_id: str | None,
    action: str,
    request: dict[str, Any],
    mutation: Callable[[OwnerCommandRecord], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Run one Owner mutation with a single completed-or-failed audit record."""

    # Seed a domain before inserting the command. Otherwise a first mutation on
    # an unseeded domain could accidentally commit the flushed `accepted`
    # command while making the defaults durable.
    await _ensure_defaults(session, domain)
    session_info = getattr(session, "info", None)
    if isinstance(session_info, dict):
        session_info["owner_mutation_active"] = True
    command = await _record_command(
        session,
        actor,
        domain,
        resource_id,
        action,
        request,
    )
    try:
        result = await mutation(command)
        _finish_command(command, result)
        session.add(
            AuditEvent(
                organization_id=actor.organization_id,
                user_id=actor.id,
                action=f"owner.{domain}.{action}",
                resource_type=domain,
                resource_id=command.resource_id,
                details={
                    "status": "completed",
                    "result": _redact_sensitive(result),
                },
            )
        )
        await session.commit()
        return result
    except Exception as exc:
        await _persist_failed_command(
            session,
            command=command,
            actor=actor,
            request=request,
            exc=exc,
        )
        raise
    finally:
        if isinstance(session_info, dict):
            session_info.pop("owner_mutation_active", None)


async def _revoke_user_sessions(
    session: AsyncSession,
    *,
    user_id: str | None = None,
    organization_id: str | None = None,
    role_id: str | None = None,
) -> None:
    scopes = [user_id, organization_id, role_id]
    if sum(scope is not None for scope in scopes) != 1:
        raise ValueError("Provide exactly one session-revocation scope")
    user_predicate = (
        User.id == user_id
        if user_id is not None
        else (
            User.organization_id == organization_id
            if organization_id is not None
            else User.role_id == role_id
        )
    )
    affected_users = select(User.id).where(user_predicate)
    await session.execute(
        update(RefreshSession)
        .where(
            RefreshSession.user_id.in_(affected_users),
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
    # Access tokens are stateless. Advancing the user's authentication
    # generation ensures a token issued before suspension never becomes valid
    # again merely because the user, organization, or role is restored.
    await session.execute(
        update(User).where(user_predicate).values(auth_version=User.auth_version + 1)
    )


async def _assignable_role(
    session: AsyncSession,
    *,
    role_id: str,
    organization_id: str,
    current_role_id: str | None = None,
) -> Role:
    role = await session.get(Role, role_id)
    if role is None or role.status != "active":
        raise HTTPException(status_code=404, detail="Active role not found")
    if role.name == "Super Owner":
        raise HTTPException(
            status_code=409,
            detail="Super Owner assignment is protected",
        )
    if role.organization_id != organization_id:
        raise HTTPException(
            status_code=409,
            detail="Role belongs to a different organization",
        )
    if current_role_id and current_role_id != role.id:
        current_role = await session.get(Role, current_role_id)
        if current_role is not None and current_role.name == "Super Owner":
            raise HTTPException(
                status_code=409,
                detail="Super Owner demotion is protected",
            )
    return role


async def _control_record(
    session: AsyncSession, domain: str, resource_id: str
) -> OwnerControlRecord:
    await _ensure_defaults(session, domain)
    record = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == domain,
            OwnerControlRecord.resource_id == resource_id,
        )
        .with_for_update()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Owner resource not found")
    return record


async def _apply_control_action(
    session: AsyncSession,
    domain: str,
    resource_id: str,
    action: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    record = await _control_record(session, domain, resource_id)
    if (
        domain == "secrets"
        and record.status == "revoked"
        and action
        in {
            "activate",
            "approve",
            "enable",
            "restore",
            "resume",
            "rotate",
            "toggle",
            "update",
        }
    ):
        raise HTTPException(
            status_code=409,
            detail="Revoked secret references are terminal; register a new reference",
        )
    if domain == "secrets" and action == "update":
        raise HTTPException(
            status_code=422,
            detail="Use the audited rotate or revoke action for secret references",
        )
    if action in {"toggle"}:
        record.enabled = not record.enabled
    elif action in {"enable", "restore", "resume"}:
        record.enabled = True
        record.status = "active"
    elif action in {"disable", "pause", "suspend"}:
        record.enabled = False
        record.status = "suspended" if action == "suspend" else "paused"
    elif action in {"approve", "activate", "compliant"}:
        record.status = "active"
        record.enabled = True
    elif action in {"validate", "recover"}:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{action.title()} is unavailable for this resource because "
                "no evidence-producing backend operation is registered"
            ),
        )
    elif action in {"reject", "restrict", "revoke"}:
        record.status = {
            "reject": "rejected",
            "restrict": "restricted",
            "revoke": "revoked",
        }[action]
        record.enabled = False
    elif action in {
        "health-check",
        "refresh",
        "reconnect",
        "synchronize",
        "test",
        "send-test",
    }:
        record.payload = {**record.payload, "lastCheck": _iso()}
    elif action == "rotate":
        record.status = "active"
        record.enabled = True
        record.payload = {
            **record.payload,
            "lastRotated": _now().date().isoformat(),
        }
    elif action == "offline":
        record.status = "offline"
        record.enabled = False
    elif action in {"save", "update", "set-limit", "change-plan", "attest"}:
        pass
    else:
        raise HTTPException(status_code=422, detail="Unsupported owner action")

    blocked = {"id", "domain", "resource_id", "maskedValue", "secret", "token"}
    updates = {key: value for key, value in payload.items() if key not in blocked}
    record.payload = {**record.payload, **updates}
    if "status" in updates:
        record.status = str(updates["status"])
        record.payload.pop("status", None)
    if "enabled" in updates:
        record.enabled = bool(updates["enabled"])
        record.payload.pop("enabled", None)
    record.version += 1
    return _control_item(record)


def _validated_evidence_reference(payload: dict[str, Any]) -> str:
    raw_reference = payload.get("reference")
    if not isinstance(raw_reference, str):
        raise HTTPException(
            status_code=422,
            detail="Evidence reference must be a string",
        )
    reference = raw_reference.strip()
    if not 3 <= len(reference) <= 500:
        raise HTTPException(
            status_code=422,
            detail="Evidence reference must contain between 3 and 500 characters",
        )
    if any(ord(character) < 32 for character in reference):
        raise HTTPException(
            status_code=422,
            detail="Evidence reference contains unsupported control characters",
        )

    lowered = reference.casefold()
    inline_secret_markers = {
        "authorization:",
        "bearer ",
        "password=",
        "token=",
        "secret=",
        "api_key=",
        "apikey=",
    }
    if any(marker in lowered for marker in inline_secret_markers):
        raise HTTPException(
            status_code=422,
            detail="Evidence must be an external reference, never inline credentials",
        )
    if "://" in reference:
        parsed = urlsplit(reference)
        if not parsed.scheme or not parsed.netloc:
            raise HTTPException(status_code=422, detail="Evidence URL is invalid")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Evidence URLs cannot contain credentials, query parameters "
                    "or fragments"
                ),
            )
    return reference


def _validated_secret_reference(raw_reference: Any) -> str:
    if not isinstance(raw_reference, str):
        raise HTTPException(
            status_code=422,
            detail="Secret reference must be a string",
        )
    reference = raw_reference.strip()
    if not 8 <= len(reference) <= 600:
        raise HTTPException(
            status_code=422,
            detail="Secret reference must contain between 8 and 600 characters",
        )
    if any(ord(character) < 32 for character in reference) or any(
        character.isspace() for character in reference
    ):
        raise HTTPException(
            status_code=422,
            detail="Secret reference contains unsupported whitespace or controls",
        )
    lowered = reference.casefold()
    if any(
        marker in lowered
        for marker in (
            "authorization:",
            "bearer ",
            "password=",
            "token=",
            "secret=",
            "api_key=",
            "apikey=",
        )
    ):
        raise HTTPException(
            status_code=422,
            detail="Store only a reference, never inline secret material",
        )

    if reference.startswith("arn:"):
        if not re.fullmatch(
            (
                r"arn:(?:aws|aws-us-gov|aws-cn):secretsmanager:"
                r"[a-z0-9-]+:\d{12}:secret:[A-Za-z0-9/_+=.@-]+"
            ),
            reference,
        ):
            raise HTTPException(
                status_code=422,
                detail="AWS Secrets Manager ARN is invalid",
            )
        return reference

    parsed = urlsplit(reference)
    allowed_schemes = {
        "vault",
        "aws-secretsmanager",
        "gcp-secret-manager",
        "azure-key-vault",
    }
    if (
        parsed.scheme not in allowed_schemes
        or not parsed.netloc
        or not parsed.path.strip("/")
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Secret reference must use vault://, aws-secretsmanager://, "
                "gcp-secret-manager://, azure-key-vault:// or a Secrets Manager ARN"
            ),
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(
            status_code=422,
            detail=(
                "Secret references cannot contain credentials, query parameters "
                "or fragments"
            ),
        )
    return reference


async def _validate_release_gate(
    session: AsyncSession,
    record: OwnerControlRecord,
) -> dict[str, Any]:
    checked_at = _iso()
    resource_id = record.resource_id
    if resource_id == "validation":
        health = await _health_items(session)
        passed = bool(health) and all(item["status"] == "healthy" for item in health)
        last_result = (
            "All live dependencies are healthy"
            if passed
            else "One or more live dependencies are unavailable"
        )
        evidence: dict[str, Any] = {"dependencies": health}
    elif resource_id == "security":
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
        passed = critical_alerts == 0
        last_result = f"{critical_alerts} unresolved critical alert(s)"
        evidence = {"unresolvedCriticalAlerts": critical_alerts}
    elif resource_id == "performance":
        samples = (
            await session.scalars(
                select(MetricSample)
                .where(MetricSample.timestamp >= _now() - timedelta(hours=24))
                .order_by(MetricSample.timestamp.desc())
                .limit(100)
            )
        ).all()
        unknown = sum("status" not in (sample.labels or {}) for sample in samples)
        unhealthy = sum(
            "status" in (sample.labels or {})
            and _metric_health_status(sample.labels) != "healthy"
            for sample in samples
        )
        passed = bool(samples) and unknown == 0 and unhealthy == 0
        last_result = (
            (
                f"{len(samples)} recent metric sample(s), {unhealthy} unhealthy, "
                f"{unknown} without an explicit status"
            )
            if samples
            else "No metric samples were recorded in the last 24 hours"
        )
        evidence = {
            "sampleCount": len(samples),
            "unhealthySampleCount": unhealthy,
            "unknownStatusSampleCount": unknown,
            "windowHours": 24,
        }
    elif resource_id == "backup":
        cutoff = _now() - RELEASE_EVIDENCE_WINDOW
        completed_backup = await session.scalar(
            select(BackupRecord)
            .where(
                BackupRecord.status == "completed",
                BackupRecord.completed_at.is_not(None),
                BackupRecord.completed_at >= cutoff,
                BackupRecord.location.is_not(None),
                BackupRecord.checksum.is_not(None),
                BackupRecord.size_bytes.is_not(None),
            )
            .order_by(BackupRecord.completed_at.desc())
            .limit(1)
        )
        recovery_runs = (
            await session.scalars(
                select(DisasterRecoveryRun)
                .where(
                    DisasterRecoveryRun.status == "completed",
                    DisasterRecoveryRun.completed_at.is_not(None),
                    DisasterRecoveryRun.completed_at >= cutoff,
                    DisasterRecoveryRun.operation.in_(RELEASE_RECOVERY_OPERATIONS),
                )
                .order_by(DisasterRecoveryRun.completed_at.desc())
                .limit(100)
            )
        ).all()
        recovery_run = None
        artifact_ready = await _backup_artifact_ready(
            completed_backup,
            verify_checksum=True,
        )
        if completed_backup is not None and artifact_ready:
            for candidate in recovery_runs:
                details = candidate.details or {}
                if details.get("backup_id") != completed_backup.id:
                    continue
                if not details.get("validated"):
                    continue
                if details.get("checksum") != completed_backup.checksum:
                    continue
                if details.get("size_bytes") != completed_backup.size_bytes:
                    continue
                recovery_run = candidate
                break
        passed = (
            completed_backup is not None and artifact_ready and recovery_run is not None
        )
        last_result = (
            "A recent completed backup and successful restore/DR run are available"
            if passed
            else (
                "No completed backup from the last 24 hours is available"
                if completed_backup is None
                else (
                    "The latest completed backup failed full artifact integrity "
                    "verification"
                    if not artifact_ready
                    else (
                        "No successful restore or DR run from the last 24 hours "
                        "is available"
                    )
                )
            )
        )
        evidence = {
            "windowHours": int(RELEASE_EVIDENCE_WINDOW.total_seconds() // 3600),
            "backupId": (completed_backup.id if completed_backup is not None else None),
            "artifactIntegrity": (
                "unavailable"
                if completed_backup is None
                else "verified" if artifact_ready else "failed"
            ),
            "recoveryRunId": recovery_run.id if recovery_run is not None else None,
            "recoveryOperation": (
                recovery_run.operation if recovery_run is not None else None
            ),
        }
    else:
        raise HTTPException(
            status_code=409,
            detail=f"Release gate {resource_id!r} has no live validator",
        )

    record.status = "passed" if passed else "blocked"
    record.payload = {
        **record.payload,
        "lastResult": last_result,
        "checkedAt": checked_at,
        "evidence": evidence,
    }
    record.version += 1
    return _control_item(record)


async def _revalidate_non_owner_release_gates(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    await _ensure_defaults(session, "release")
    records = (
        await session.scalars(
            select(OwnerControlRecord)
            .where(
                OwnerControlRecord.domain == "release",
                OwnerControlRecord.resource_id != "approval",
            )
            .order_by(OwnerControlRecord.created_at)
            .with_for_update()
        )
    ).all()
    expected_gate_ids = {"validation", "security", "performance", "backup"}
    actual_gate_ids = {record.resource_id for record in records}
    if actual_gate_ids != expected_gate_ids:
        missing = sorted(expected_gate_ids - actual_gate_ids)
        unsupported = sorted(actual_gate_ids - expected_gate_ids)
        problems = []
        if missing:
            problems.append(f"missing validators: {', '.join(missing)}")
        if unsupported:
            problems.append(f"unsupported gates: {', '.join(unsupported)}")
        raise HTTPException(
            status_code=409,
            detail="Release approval cannot be validated (" + "; ".join(problems) + ")",
        )
    return [await _validate_release_gate(session, record) for record in records]


async def _apply_live_action(
    session: AsyncSession,
    actor: UserRecord,
    domain: str,
    resource_id: str,
    action: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if domain == "approvals":
        normalized = {
            "approve": "approved",
            "approved": "approved",
            "reject": "rejected",
            "rejected": "rejected",
            "changes-requested": "changes_requested",
            "changes_requested": "changes_requested",
        }.get(action)
        if normalized is None:
            raise HTTPException(status_code=422, detail="Unsupported approval action")
        request = await session.get(ApprovalRequest, resource_id)
        if request is None:
            request = await session.scalar(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.target_type == "meeting",
                    ApprovalRequest.target_id == resource_id,
                    ApprovalRequest.status.in_({"pending", "changes_requested"}),
                )
                .order_by(ApprovalRequest.created_at.desc())
            )
        if request is not None:
            try:
                request, _record, notifications = await governance_service.decide_approval(
                    session,
                    actor,
                    request,
                    decision=normalized,
                    reason=str(payload.get("reason", "")),
                    metadata={"owner_control": True},
                )
            except (LookupError, ValueError) as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            session.info.setdefault("phase29e_notifications", []).extend(notifications)
            return governance_service.approval_snapshot(request)
        meeting = await session.get(Meeting, resource_id)
        if meeting is None or meeting.status not in {"pending", "pending_approval"}:
            raise HTTPException(status_code=404, detail="Approval request not found")
        meeting.status = (
            "scheduled"
            if normalized == "approved"
            else (
                "changes_requested" if normalized == "changes_requested" else "rejected"
            )
        )
        if normalized == "approved":
            meeting.approved_by_id = actor.id
            meeting.approved_at = _now()
        return {"id": meeting.id, "status": normalized, "legacy": True}

    if domain == "access":
        role = await session.get(Role, resource_id)
        if role is None:
            raise HTTPException(status_code=404, detail="Role not found")
        if role.name == "Super Owner":
            raise HTTPException(status_code=409, detail="Super Owner role is protected")
        if role.status == "deleted":
            raise HTTPException(
                status_code=409,
                detail="Deleted roles cannot be restored from Owner access controls",
            )
        if action not in {"toggle", "suspend", "restore"}:
            raise HTTPException(status_code=422, detail="Unsupported role action")
        if role.status not in {"active", "suspended"}:
            raise HTTPException(
                status_code=409,
                detail=f"Role status {role.status} cannot be changed here",
            )
        if action == "suspend" and role.status != "active":
            raise HTTPException(status_code=409, detail="Role is not active")
        if action == "restore" and role.status != "suspended":
            raise HTTPException(status_code=409, detail="Role is not suspended")
        role.status = (
            "suspended"
            if action == "suspend" or (action == "toggle" and role.status == "active")
            else "active"
        )
        if role.status == "suspended":
            await _revoke_user_sessions(session, role_id=role.id)
        return {"id": role.id, "status": role.status}

    if domain in {"organizations", "billing"}:
        organization = await session.get(Organization, resource_id)
        if organization is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        if organization.id == actor.organization_id and action in {
            "suspend",
            "restrict",
        }:
            raise HTTPException(
                status_code=409,
                detail="The Super Owner organization cannot be suspended",
            )
        if action in {"suspend", "restrict"}:
            organization.status = "suspended" if action == "suspend" else "restricted"
            await _revoke_user_sessions(
                session,
                organization_id=organization.id,
            )
        elif action in {"restore", "activate"}:
            organization.status = "active"
        elif action in {"change-plan", "save", "update"}:
            if "plan" not in payload:
                raise HTTPException(
                    status_code=422,
                    detail="An organization plan is required",
                )
            plan = str(payload["plan"]).lower()
            if plan not in ORGANIZATION_PLANS:
                raise HTTPException(
                    status_code=422,
                    detail="Unsupported organization plan",
                )
            organization.plan = plan
        elif action != "review":
            raise HTTPException(
                status_code=422, detail="Unsupported organization action"
            )
        return {"id": organization.id, "status": organization.status}

    if domain == "projects":
        project = await session.get(Project, resource_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if action == "validate":
            organization = await session.get(Organization, project.organization_id)
            workspace = await session.get(Workspace, project.workspace_id)
            owner = await session.get(User, project.owner_id)
            evidence = {
                "organization": bool(
                    organization is not None and organization.status == "active"
                ),
                "workspace": bool(
                    workspace is not None
                    and workspace.organization_id == project.organization_id
                    and workspace.status == "active"
                ),
                "owner": bool(
                    owner is not None
                    and owner.organization_id == project.organization_id
                    and owner.status == "active"
                    and owner.deleted_at is None
                ),
                "slug": bool(project.slug.strip()),
            }
            if not all(evidence.values()):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Project relationship validation failed",
                        "evidence": evidence,
                    },
                )
            return {
                "id": project.id,
                "status": project.status,
                "validated": True,
                "evidence": evidence,
            }
        normalized_action = {
            "request-review": "request_review",
            "request_review": "request_review",
        }.get(action, action)
        try:
            await work_management.transition_project(
                session,
                actor,
                project,
                action=normalized_action,
                reason=str(payload.get("reason", "")),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "id": project.id,
            "status": project.status,
            "reviewStatus": project.review_status,
            "version": project.version,
        }

    if domain == "incidents":
        incident = await session.get(Alert, resource_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        try:
            notifications = []
            if action in {"investigate", "acknowledge"}:
                await communications.acknowledge_incident(session, actor, incident)
            elif action == "escalate":
                incident, notifications = await communications.escalate_incident(
                    session, actor, incident
                )
            elif action == "resolve":
                await communications.resolve_incident(session, actor, incident)
            else:
                raise HTTPException(status_code=422, detail="Unsupported incident action")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        session.info.setdefault("phase29e_notifications", []).extend(notifications)
        return communications.incident_snapshot(incident)

    if domain == "integrations":
        record = await _control_record(session, "integrations", resource_id)
        configured = _configured_integrations().get(resource_id, False)
        protected = resource_id in {"postgres", "redis"}
        if action == "toggle":
            if protected:
                raise HTTPException(
                    status_code=409,
                    detail="Core data integrations cannot be disabled here",
                )
            if not configured and not record.enabled:
                raise HTTPException(
                    status_code=409,
                    detail="Configure deployment credentials before enabling",
                )
            record.enabled = not record.enabled
        elif action == "health-check":
            if not configured:
                raise HTTPException(
                    status_code=409,
                    detail="Integration credentials are not configured",
                )
            checked_at = _iso()
            if protected:
                health_id = {
                    "postgres": "database",
                    "redis": "redis",
                }[resource_id]
                evidence = next(
                    item
                    for item in await _health_items(session)
                    if item["id"] == health_id
                )
                if evidence["status"] != "healthy":
                    raise HTTPException(
                        status_code=503,
                        detail={
                            "message": "Live integration probe failed",
                            "evidence": evidence,
                        },
                    )
                record.payload = {
                    **record.payload,
                    "lastCheck": checked_at,
                    "validationMode": "live",
                    "lastResult": evidence,
                }
            else:
                record.payload = {
                    **record.payload,
                    "lastCheck": checked_at,
                    "validationMode": "configuration",
                    "lastResult": {
                        "configured": True,
                        "liveProbe": False,
                        "message": (
                            "Required deployment credentials are present; "
                            "no provider network call was made"
                        ),
                    },
                }
        else:
            raise HTTPException(
                status_code=422,
                detail="Unsupported integration action",
            )
        record.status = (
            "connected"
            if protected
            else (
                "configured"
                if configured and record.enabled
                else "disabled" if configured else "unconfigured"
            )
        )
        record.version += 1
        return _control_item(record)

    if domain == "services":
        record = await _control_record(session, "services", resource_id)
        disabling_actions = {"disable", "offline", "pause", "suspend"}
        if record.resource_id in {"postgres", "redis", "vault"} and (
            action == "toggle" or action in disabling_actions
        ):
            raise HTTPException(
                status_code=409,
                detail="Core data service policy is protected",
            )
        if action == "toggle":
            record.enabled = not record.enabled
        elif action in {"enable", "activate", "restore", "resume"}:
            record.enabled = True
        elif action in disabling_actions:
            record.enabled = False
        else:
            raise HTTPException(
                status_code=422,
                detail="Unsupported service policy action",
            )
        record.status = "active" if record.enabled else "paused"
        record.version += 1
        return _control_item(record)

    if domain == "notifications":
        if action == "mark-all-read":
            notifications = (
                await session.scalars(
                    select(Notification).where(
                        Notification.recipient_id == actor.id,
                        Notification.read_at.is_(None),
                    )
                )
            ).all()
            for notification in notifications:
                notification.read_at = _now()
            return {"updated": len(notifications)}
        notification = await session.get(Notification, resource_id)
        if notification is None or notification.recipient_id != actor.id:
            raise HTTPException(status_code=404, detail="Notification not found")
        if action != "mark-read":
            raise HTTPException(
                status_code=422, detail="Unsupported notification action"
            )
        notification.read_at = _now()
        return {"id": notification.id, "read": True}

    if domain == "communications":
        record = await _control_record(session, "communications", resource_id)
        try:
            readiness = communications.channel_state(resource_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        configured = bool(readiness["configured"])
        if action == "toggle":
            if resource_id == "in_app":
                raise HTTPException(
                    status_code=409,
                    detail="The in-app Owner channel is a protected core service",
                )
            if not configured:
                raise HTTPException(
                    status_code=409,
                    detail="Configure the delivery provider before enabling it",
                )
            record.enabled = not record.enabled
            record.status = "ready" if record.enabled else "disabled"
            record.version += 1
            return _control_item(record)
        if action not in {"send-test", "test"}:
            raise HTTPException(
                status_code=422,
                detail="Unsupported communication action",
            )
        if not configured or (resource_id != "in_app" and not record.enabled):
            raise HTTPException(
                status_code=409,
                detail="Communication channel is not configured or enabled",
            )
        recipient = await session.get(User, actor.id)
        if recipient is None:
            raise HTTPException(status_code=404, detail="Owner account not found")
        notification = await communications.create_notification(
            session,
            recipient,
            event_key="owner.channel.test",
            category="system",
            title=f"{readiness['name']} channel test",
            message=f"AIONEX queued a governed test for the {readiness['name']} channel.",
            severity="info",
            channels=[resource_id],
            source_type="communication_channel",
            source_id=resource_id,
            correlation_id=f"owner-test:{resource_id}:{uuid_str()}",
            actor_id=actor.id,
        )
        session.info.setdefault("phase29e_notifications", []).append(notification)
        delivery = await session.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == notification.id,
                NotificationDelivery.channel == resource_id,
            )
        )
        record.payload = {
            **record.payload,
            "lastCheck": _iso(),
            "lastResult": delivery.status if delivery else "persisted",
        }
        record.version += 1
        return {
            "id": notification.id,
            "delivered": bool(delivery and delivery.status == "delivered"),
            "queued": bool(delivery and delivery.status in {"queued", "retrying"}),
            "channel": resource_id,
            "status": delivery.status if delivery else "persisted",
        }

    if domain == "compliance":
        record = await _control_record(session, "compliance", resource_id)
        if action == "record-evidence":
            reference = _validated_evidence_reference(payload)
            existing_references = list(
                dict.fromkeys(
                    str(item)
                    for item in record.payload.get("evidenceReferences", [])
                    if isinstance(item, str)
                )
            )
            duplicate = reference in existing_references
            if not duplicate:
                if len(existing_references) >= MAX_EVIDENCE_REFERENCES:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Evidence reference limit reached for this control; "
                            "archive obsolete references before adding another"
                        ),
                    )
                existing_references.append(reference)
            evidence_count = len(existing_references)
            if record.status == "not_assessed":
                record.status = "partial"
            record.payload = {
                **record.payload,
                "evidenceReferences": existing_references,
                "evidence": evidence_count,
                "updatedAt": _iso(),
            }
            record.version += 1
            return {
                **_control_item(record),
                "recorded": not duplicate,
                "evidenceCount": evidence_count,
                "duplicate": duplicate,
            }
        if action not in {"save", "update", "attest"}:
            raise HTTPException(
                status_code=422,
                detail="Unsupported compliance action",
            )
        requested_status = str(payload.get("status", record.status))
        allowed_statuses = {
            "compliant",
            "partial",
            "non_compliant",
            "not_applicable",
            "not_assessed",
        }
        if requested_status not in allowed_statuses:
            raise HTTPException(
                status_code=422,
                detail="Unsupported compliance status",
            )
        evidence_references = list(
            dict.fromkeys(
                str(item)
                for item in record.payload.get("evidenceReferences", [])
                if isinstance(item, str)
            )
        )
        evidence_count = len(evidence_references)
        if requested_status == "compliant" and evidence_count <= 0:
            raise HTTPException(
                status_code=409,
                detail="Compliance cannot be attested without linked evidence",
            )
        record.status = requested_status
        record.payload = {
            **record.payload,
            **{
                key: value
                for key, value in payload.items()
                if key not in {"id", "status", "evidence", "evidenceReferences"}
            },
            "evidenceReferences": evidence_references,
            "evidence": evidence_count,
            "updatedAt": _iso(),
        }
        record.version += 1
        return _control_item(record)

    if domain == "recovery":
        if action == "create-backup":
            kind = str(payload.get("kind", "on-demand")).strip()
            scope = str(payload.get("scope", "platform")).strip()
            if not kind or not scope or len(kind) > 80 or len(scope) > 160:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Backup kind or scope is empty or exceeds its supported "
                        "length"
                    ),
                )
            await acquire_enqueue_lock(session, f"backup:{scope}")
            active = await session.scalar(
                select(BackupRecord.id)
                .where(
                    BackupRecord.scope == scope,
                    BackupRecord.status.in_({"pending", "running"}),
                )
                .limit(1)
            )
            if active is not None:
                raise HTTPException(
                    status_code=409,
                    detail="A backup is already queued or running for this scope",
                )
            backup_record = BackupRecord(
                kind=kind,
                scope=scope,
                status="pending",
            )
            session.add(backup_record)
            await session.flush()
            return {
                "id": backup_record.id,
                "status": backup_record.status,
            }
        if action in {"validate-restore", "dr-drill"}:
            await acquire_enqueue_lock(session, "restore-validation")
            active_run = await session.scalar(
                select(DisasterRecoveryRun.id)
                .where(
                    DisasterRecoveryRun.status.in_({"pending", "running"}),
                    DisasterRecoveryRun.operation.in_({"restore_validation", "test"}),
                )
                .limit(1)
            )
            if active_run is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "A restore validation or disaster-recovery drill is "
                        "already queued or running"
                    ),
                )
            backup_statement = select(BackupRecord).where(
                BackupRecord.status == "completed",
                BackupRecord.completed_at.is_not(None),
                BackupRecord.location.is_not(None),
                BackupRecord.checksum.is_not(None),
                BackupRecord.size_bytes.is_not(None),
                BackupRecord.size_bytes > 0,
            )
            if action == "validate-restore" and resource_id not in {
                "latest",
                "platform",
                "all",
            }:
                backup_statement = backup_statement.where(
                    BackupRecord.id == resource_id
                )
            backup = await session.scalar(
                backup_statement.order_by(BackupRecord.completed_at.desc()).limit(1)
            )
            if backup is None:
                raise HTTPException(
                    status_code=409,
                    detail="A completed backup is required for restore validation",
                )
            if not await _backup_artifact_ready(backup, verify_checksum=False):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "The selected backup artifact is missing or failed live "
                        "readiness verification"
                    ),
                )
            operation = "restore_validation" if action == "validate-restore" else "test"
            region = payload.get("region")
            if region is not None and (
                not isinstance(region, str) or len(region) > 120
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Recovery region must be a string of at most 120 characters",
                )
            run = DisasterRecoveryRun(
                operation=operation,
                status="pending",
                region=region,
                details={
                    "backup_id": backup.id,
                    "dry_run": True,
                    "requested_by": actor.id,
                },
            )
            session.add(run)
            await session.flush()
            return {
                "id": run.id,
                "status": run.status,
                "backup_id": backup.id,
                "operation": run.operation,
            }
        raise HTTPException(status_code=422, detail="Unsupported recovery action")

    if domain == "release":
        record = await _control_record(session, "release", resource_id)
        if resource_id == "approval":
            if record.payload.get("platformClosedAt"):
                raise HTTPException(
                    status_code=409,
                    detail="The final platform readiness record is already closed",
                )
            if action == "reject":
                record.status = "rejected"
                record.enabled = False
                record.payload = {
                    **record.payload,
                    "lastResult": "Release rejected by the Super Owner",
                    "checkedAt": _iso(),
                }
            elif action == "approve":
                gates = await _revalidate_non_owner_release_gates(session)
                blockers = [
                    item["name"] for item in gates if item["status"] != "passed"
                ]
                if blockers:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Release approval is blocked by: " + ", ".join(blockers)
                        ),
                    )
                record.status = "passed"
                record.enabled = True
                record.payload = {
                    **record.payload,
                    "lastResult": "All live release gates passed; Owner approval recorded",
                    "checkedAt": _iso(),
                }
            else:
                raise HTTPException(
                    status_code=422,
                    detail="Unsupported release approval action",
                )
        elif action != "validate":
            raise HTTPException(
                status_code=422,
                detail="Release gates support validation only",
            )
        else:
            return await _validate_release_gate(session, record)
        record.version += 1
        return _control_item(record)

    if domain == "global-command":
        if action not in {"resume", "pause", "validate", "activate", "offline"}:
            raise HTTPException(status_code=422, detail="Unsupported global action")
        if resource_id == "all":
            if action in {"resume", "pause"}:
                eligible_statuses = (
                    PROJECT_RESUMABLE_STATUSES
                    if action == "resume"
                    else PROJECT_PAUSABLE_STATUSES - {"planning"}
                )
                projects = (
                    await session.scalars(
                        select(Project)
                        .where(Project.status.in_(eligible_statuses))
                        .with_for_update()
                    )
                ).all()
                for project in projects:
                    project.status = "active" if action == "resume" else "paused"
                return {"updated": len(projects)}
            if action != "validate":
                raise HTTPException(
                    status_code=409,
                    detail="This global action is not supported for all resources",
                )
            health_evidence = await _health_items(session)
            validated = all(item["status"] == "healthy" for item in health_evidence)
            if not validated:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "message": "Global validation failed",
                        "evidence": health_evidence,
                    },
                )
            return {
                "validated": True,
                "checkedAt": _iso(),
                "evidence": health_evidence,
            }
        for target_domain in ("projects", "organizations"):
            try:
                mapped = {
                    "activate": "resume" if target_domain == "projects" else "activate",
                    "offline": "pause" if target_domain == "projects" else "restrict",
                }.get(action, action)
                return await _apply_live_action(
                    session,
                    actor,
                    target_domain,
                    resource_id,
                    mapped,
                    payload,
                )
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
        return await _apply_live_action(
            session,
            actor,
            "services",
            resource_id,
            action,
            payload,
        )

    if domain == "health":
        if action not in {"refresh", "validate"}:
            raise HTTPException(status_code=409, detail="Unsupported health action")
        health_evidence = await _health_items(session)
        healthy = all(item["status"] == "healthy" for item in health_evidence)
        if action == "validate" and not healthy:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "Platform health validation failed",
                    "evidence": health_evidence,
                },
            )
        return {
            "checkedAt": _iso(),
            "healthy": healthy,
            "evidence": health_evidence,
        }

    if domain == "system-map":
        if action != "refresh":
            raise HTTPException(
                status_code=409,
                detail="Unsupported system map action",
            )
        nodes = await _system_map_items(session)
        return {
            "checkedAt": _iso(),
            "nodes": nodes,
            "healthy": all(node["health"] == "healthy" for node in nodes),
        }

    if domain == "audit":
        if action not in {"refresh", "review"}:
            raise HTTPException(status_code=409, detail="Unsupported audit action")
        events = await _audit_items(session)
        return {
            "reviewedAt": _iso(),
            "records": len(events),
            "latest": events[0] if events else None,
        }

    if domain == "executive":
        if action not in {"refresh", "review"}:
            raise HTTPException(
                status_code=409,
                detail="Unsupported executive action",
            )
        return {
            "generatedAt": _iso(),
            "metrics": await _executive_items(session),
        }

    if domain == "staff":
        if action in {"refresh", "review"}:
            staff = await _staff_items(session)
            return {
                "reviewedAt": _iso(),
                "records": len(staff),
                "active": sum(item["status"] == "active" for item in staff),
            }
        member = await session.scalar(
            select(WorkforceMember)
            .where(WorkforceMember.id == resource_id)
            .with_for_update()
        )
        if member is None:
            raise HTTPException(status_code=404, detail="Workforce member not found")
        normalized_action = {
            "supervision": "supervise",
            "training": "retrain",
            "promotion": "promote",
            "suspension": "suspend",
            "retirement": "retire",
        }.get(action, action)
        try:
            await workforce_service.transition_member(
                session,
                actor,
                member,
                action=normalized_action,
                reason=str(payload.get("reason", "")),
                grade=(
                    int(payload["grade"])
                    if payload.get("grade") is not None
                    else None
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return workforce_service.member_snapshot(member)

    return await _apply_control_action(session, domain, resource_id, action, payload)


async def _approval_items(session: AsyncSession) -> list[dict[str, Any]]:
    requests = list(
        (
            await session.scalars(
                select(ApprovalRequest)
                .order_by(ApprovalRequest.updated_at.desc())
                .limit(250)
            )
        ).all()
    )
    items = []
    for item in requests:
        snapshot = governance_service.approval_snapshot(item)
        if item.target_type == "meeting":
            snapshot = {
                **snapshot,
                "id": item.target_id,
                "approvalId": item.id,
            }
        items.append(snapshot)
    represented_meetings = {
        item.target_id for item in requests if item.target_type == "meeting"
    }
    status_map = {
        "pending": "pending",
        "pending_approval": "pending",
        "scheduled": "approved",
        "rejected": "rejected",
        "changes_requested": "changes_requested",
    }
    meetings = list(
        (
            await session.scalars(
                select(Meeting)
                .where(
                    Meeting.status.in_(list(status_map)),
                    Meeting.id.notin_(represented_meetings)
                    if represented_meetings
                    else text("TRUE"),
                )
                .order_by(Meeting.updated_at.desc())
                .limit(250)
            )
        ).all()
    )
    items.extend(
        {
            "id": item.id,
            "title": item.title,
            "requester": item.organizer_id,
            "requester_id": item.organizer_id,
            "target_type": "meeting",
            "target_id": item.id,
            "scope": item.project_id or item.organization_id,
            "category": "meeting",
            "type": "Meeting (legacy)",
            "status": status_map[item.status],
            "priority": "medium",
            "risk": "medium" if status_map[item.status] == "pending" else "low",
            "createdAt": _iso(item.created_at),
            "updatedAt": _iso(item.updated_at),
            "decidedAt": _iso(item.approved_at) if item.approved_at else None,
            "legacy": True,
        }
        for item in meetings
    )
    return sorted(items, key=lambda item: item.get("updatedAt") or item.get("createdAt") or "", reverse=True)[:250]


@router.get(
    "/resources/{domain}",
    response_model=OwnerResourceCollection,
)
async def get_owner_resources(
    domain: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> OwnerResourceCollection:
    return await _collection(session, domain, actor)


@router.post(
    "/resources/{domain}",
    response_model=OwnerResourceCollection,
    status_code=status.HTTP_201_CREATED,
)
async def create_owner_resource(
    domain: str,
    data: OwnerResourceCreate,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> OwnerResourceCollection:
    resource_id = data.id or f"{domain.rstrip('s')}-{uuid_str()}"

    async def create(command: OwnerCommandRecord) -> dict[str, Any]:
        if domain not in CREATABLE_DOMAINS:
            raise HTTPException(
                status_code=405,
                detail="Owner resource is not creatable",
            )
        payload = dict(data.payload)
        lowered_keys = {key.lower() for key in payload}
        if domain == "secrets":
            forbidden = {"value", "secret", "token", "password", "apikey", "api_key"}
            if lowered_keys & forbidden:
                raise HTTPException(
                    status_code=422,
                    detail="Store only an external vault reference, never a secret value",
                )
            required = {"name", "provider", "scope", "reference"}
            if not required <= set(payload):
                raise HTTPException(
                    status_code=422,
                    detail="Secret name, provider, scope and reference are required",
                )
            allowed_metadata = {
                "name",
                "provider",
                "scope",
                "reference",
                "status",
                "enabled",
            }
            unexpected = set(payload) - allowed_metadata
            if unexpected:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Unsupported secret metadata: " + ", ".join(sorted(unexpected))
                    ),
                )
            name = str(payload["name"]).strip()
            provider = str(payload["provider"]).strip()
            scope = str(payload["scope"]).strip().lower()
            if not 2 <= len(name) <= 200 or not 2 <= len(provider) <= 120:
                raise HTTPException(
                    status_code=422,
                    detail="Secret name and provider metadata are invalid",
                )
            if scope not in {"global", "organization", "project", "service"}:
                raise HTTPException(
                    status_code=422,
                    detail="Unsupported secret reference scope",
                )
            safe_reference = _validated_secret_reference(payload["reference"])
            payload = {
                "name": name,
                "provider": provider,
                "scope": scope,
                "reference": safe_reference,
                **({"status": payload["status"]} if "status" in payload else {}),
                **({"enabled": payload["enabled"]} if "enabled" in payload else {}),
            }
            payload["maskedValue"] = "External vault reference"
            payload["lastRotated"] = _now().date().isoformat()
        elif "name" not in payload:
            raise HTTPException(status_code=422, detail="Resource name is required")

        existing = await session.scalar(
            select(OwnerControlRecord.id).where(
                OwnerControlRecord.domain == domain,
                OwnerControlRecord.resource_id == resource_id,
            )
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail="Owner resource already exists",
            )
        default_status = (
            "draft"
            if domain == "policies"
            else "pending" if domain == "governance" else "active"
        )
        record_status = str(payload.pop("status", default_status))
        enabled = bool(payload.pop("enabled", True))
        session.add(
            OwnerControlRecord(
                domain=domain,
                resource_id=resource_id,
                status=record_status,
                enabled=enabled,
                payload=payload,
            )
        )
        command.resource_id = resource_id
        return {"resource_id": resource_id}

    await _run_audited_mutation(
        session,
        actor=actor,
        domain=domain,
        resource_id=resource_id,
        action="create",
        request=data.model_dump(mode="json"),
        mutation=create,
    )
    notifications = list(session.info.pop("phase29e_notifications", []))
    await communications.publish_many(notifications)
    return await _collection(session, domain, actor)


@router.post(
    "/resources/{domain}/{resource_id}/actions",
    response_model=OwnerResourceCollection,
)
async def execute_owner_resource_action(
    domain: str,
    resource_id: str,
    data: OwnerResourceAction,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> OwnerResourceCollection:
    async def apply(_command: OwnerCommandRecord) -> dict[str, Any]:
        if domain not in RESOURCE_DOMAINS:
            raise HTTPException(
                status_code=404,
                detail="Unknown owner resource domain",
            )
        return await _apply_live_action(
            session,
            actor,
            domain,
            resource_id,
            data.action,
            data.payload,
        )

    await _run_audited_mutation(
        session,
        actor=actor,
        domain=domain,
        resource_id=resource_id,
        action=data.action,
        request=data.payload,
        mutation=apply,
    )
    notifications = list(session.info.pop("phase29e_notifications", []))
    await communications.publish_many(notifications)
    return await _collection(session, domain, actor)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or uuid_str()


async def _execute_owner_operation(
    data: OwnerOperationRequest,
    actor: UserRecord,
    session: AsyncSession,
) -> dict[str, Any]:
    if data.operation != "create" and not data.id:
        raise HTTPException(status_code=422, detail="Record id is required")
    mutable_fields = {
        "organization": {
            "create": {"name", "slug", "plan"},
            "update": {"name", "plan"},
        },
        "project": {
            "create": {
                "name",
                "organization_id",
                "description",
                "priority",
            },
            "update": {"name", "description", "priority", "progress"},
        },
        "user": {
            "create": {
                "name",
                "email",
                "password",
                "role_id",
                "organization_id",
            },
            "update": {"name", "role_id"},
        },
    }
    allowed_fields = mutable_fields[data.entity].get(data.operation, set())
    unexpected_fields = set(data.payload) - allowed_fields
    if unexpected_fields:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported fields: {', '.join(sorted(unexpected_fields))}",
        )
    if data.operation == "update" and not data.payload:
        raise HTTPException(status_code=422, detail="At least one update is required")
    if data.operation not in {"create", "update"} and data.payload:
        raise HTTPException(
            status_code=422,
            detail="This operation does not accept a payload",
        )

    if "name" in data.payload and len(str(data.payload["name"]).strip()) < 2:
        raise HTTPException(status_code=422, detail="Name is too short")
    if (
        "plan" in data.payload
        and str(data.payload["plan"]).lower() not in ORGANIZATION_PLANS
    ):
        raise HTTPException(status_code=422, detail="Unsupported organization plan")
    if "priority" in data.payload and str(data.payload["priority"]).lower() not in {
        "low",
        "medium",
        "high",
        "critical",
    }:
        raise HTTPException(status_code=422, detail="Unsupported project priority")
    if "progress" in data.payload:
        progress = data.payload["progress"]
        if (
            not isinstance(progress, int)
            or isinstance(progress, bool)
            or not 0 <= progress <= 100
        ):
            raise HTTPException(
                status_code=422,
                detail="Project progress must be an integer from 0 to 100",
            )

    command = await _record_command(
        session,
        actor,
        "operations",
        data.id,
        f"{data.entity}.{data.operation}",
        {"fields": sorted(data.payload)},
    )

    resource_id = data.id
    if data.entity == "organization":
        if data.operation == "create":
            name = str(data.payload.get("name", "")).strip()
            if len(name) < 2:
                raise HTTPException(
                    status_code=422,
                    detail="Organization name is required",
                )
            slug = _slug(str(data.payload.get("slug") or name))
            if await session.scalar(
                select(Organization.id).where(Organization.slug == slug)
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Organization slug already exists",
                )
            organization = Organization(
                name=name,
                slug=slug,
                plan=str(data.payload.get("plan", "enterprise")).lower(),
                status="active",
            )
            session.add(organization)
            await session.flush()
            resource_id = organization.id
        else:
            organization = await session.get(Organization, data.id)
            if organization is None:
                raise HTTPException(status_code=404, detail="Organization not found")
            if organization.id == actor.organization_id and data.operation in {
                "suspend",
                "delete",
            }:
                raise HTTPException(
                    status_code=409,
                    detail="The Super Owner organization is protected",
                )
            if data.operation == "update":
                if "name" in data.payload:
                    organization.name = str(data.payload["name"]).strip()
                if "plan" in data.payload:
                    organization.plan = str(data.payload["plan"]).lower()
            elif data.operation == "suspend":
                organization.status = "suspended"
                await _revoke_user_sessions(
                    session,
                    organization_id=organization.id,
                )
            elif data.operation == "restore":
                organization.status = "active"
            elif data.operation == "delete":
                organization.status = "inactive"
                await _revoke_user_sessions(
                    session,
                    organization_id=organization.id,
                )

    elif data.entity == "project":
        if data.operation == "create":
            name = str(data.payload.get("name", "")).strip()
            if len(name) < 2:
                raise HTTPException(status_code=422, detail="Project name is required")
            organization_id = str(
                data.payload.get("organization_id") or actor.organization_id
            )
            organization = await session.get(Organization, organization_id)
            if organization is None or organization.status != "active":
                raise HTTPException(
                    status_code=404,
                    detail="Active project organization not found",
                )
            workspace = await session.scalar(
                select(Workspace)
                .where(
                    Workspace.organization_id == organization_id,
                    Workspace.status == "active",
                )
                .order_by(Workspace.created_at)
            )
            if workspace is None:
                workspace = Workspace(
                    organization_id=organization_id,
                    name="Owner Workspace",
                    slug=f"owner-{uuid_str()[:8]}",
                    description="Created through the Owner control plane",
                )
                session.add(workspace)
                await session.flush()
            project_owner_id = (
                actor.id
                if actor.organization_id == organization_id
                else await session.scalar(
                    select(User.id)
                    .where(
                        User.organization_id == organization_id,
                        User.status == "active",
                        User.deleted_at.is_(None),
                    )
                    .order_by(User.created_at)
                    .limit(1)
                )
            )
            if project_owner_id is None:
                raise HTTPException(
                    status_code=409,
                    detail="Project organization has no active owner candidate",
                )
            project_slug = _slug(name)
            if await session.scalar(
                select(Project.id).where(
                    Project.organization_id == organization_id,
                    Project.slug == project_slug,
                )
            ):
                project_slug = f"{project_slug}-{uuid_str()[:8]}"
            project = Project(
                organization_id=organization_id,
                workspace_id=workspace.id,
                owner_id=project_owner_id,
                name=name,
                slug=project_slug,
                description=data.payload.get("description"),
                status="planning",
                priority=str(data.payload.get("priority", "medium")),
            )
            session.add(project)
            await session.flush()
            resource_id = project.id
        else:
            project = await session.get(Project, data.id)
            if project is None:
                raise HTTPException(status_code=404, detail="Project not found")
            if data.operation == "update":
                for field in ("name", "description", "priority", "progress"):
                    if field in data.payload:
                        setattr(project, field, data.payload[field])
                if "name" in data.payload:
                    project_slug = _slug(str(data.payload["name"]))
                    duplicate = await session.scalar(
                        select(Project.id).where(
                            Project.organization_id == project.organization_id,
                            Project.slug == project_slug,
                            Project.id != project.id,
                        )
                    )
                    if duplicate:
                        raise HTTPException(
                            status_code=409,
                            detail="Project slug already exists",
                        )
                    project.slug = project_slug
            elif data.operation == "suspend":
                project.status = "paused"
            elif data.operation == "restore":
                project.status = "active"
            elif data.operation == "delete":
                project.status = "deleted"

    else:
        if data.operation == "create":
            required = {"name", "email", "password", "role_id", "organization_id"}
            if not required <= set(data.payload):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "User name, email, password, role_id and "
                        "organization_id are required"
                    ),
                )
            email = str(data.payload["email"]).strip().lower()
            if await session.scalar(select(User.id).where(User.email == email)):
                raise HTTPException(status_code=409, detail="Email already exists")
            organization = await session.get(
                Organization, str(data.payload["organization_id"])
            )
            if organization is None or organization.status != "active":
                raise HTTPException(
                    status_code=404,
                    detail="Active user organization not found",
                )
            role = await _assignable_role(
                session,
                role_id=str(data.payload["role_id"]),
                organization_id=organization.id,
            )
            if len(str(data.payload["password"])) < settings.PASSWORD_MIN_LENGTH:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "User password must contain at least "
                        f"{settings.PASSWORD_MIN_LENGTH} characters"
                    ),
                )
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                raise HTTPException(status_code=422, detail="User email is invalid")
            user = User(
                organization_id=organization.id,
                role_id=role.id,
                email=email,
                name=str(data.payload["name"]).strip(),
                password_hash=pwd_context.hash(str(data.payload["password"])),
                status="active",
            )
            session.add(user)
            await session.flush()
            resource_id = user.id
        else:
            user = await session.get(User, data.id)
            if user is None or user.deleted_at is not None:
                raise HTTPException(status_code=404, detail="User not found")
            current_role = (
                await session.get(Role, user.role_id)
                if user.role_id is not None
                else None
            )
            if (
                user.id == actor.id
                or (current_role is not None and current_role.name == "Super Owner")
            ) and data.operation in {"suspend", "delete"}:
                raise HTTPException(
                    status_code=409,
                    detail="The Super Owner account is protected",
                )
            if data.operation == "update":
                if "name" in data.payload:
                    user.name = str(data.payload["name"]).strip()
                if "role_id" in data.payload:
                    role = await _assignable_role(
                        session,
                        role_id=str(data.payload["role_id"]),
                        organization_id=user.organization_id,
                        current_role_id=user.role_id,
                    )
                    user.role_id = role.id
            elif data.operation == "suspend":
                user.status = "suspended"
                await _revoke_user_sessions(session, user_id=user.id)
            elif data.operation == "restore":
                user.status = "active"
            elif data.operation == "delete":
                user.status = "inactive"
                user.deleted_at = _now()
                await _revoke_user_sessions(session, user_id=user.id)

    command.resource_id = resource_id
    result = {"entity": data.entity, "resource_id": resource_id}
    _finish_command(command, result)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action=f"owner.operations.{data.entity}.{data.operation}",
            resource_type=data.entity,
            resource_id=resource_id,
            details={"status": "completed"},
        )
    )
    await session.commit()
    return {
        "ok": True,
        "operationId": command.id,
        "message": (f"{data.entity.title()} {data.operation} completed successfully"),
        "completedAt": _iso(command.completed_at),
    }


@router.post("/operations")
async def execute_owner_operation(
    data: OwnerOperationRequest,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await _execute_owner_operation(data, actor, session)
    except Exception as exc:
        command = OwnerCommandRecord(
            id=uuid_str(),
            actor_id=actor.id,
            domain="operations",
            resource_id=data.id,
            action=f"{data.entity}.{data.operation}",
            request={},
            status="accepted",
            created_at=_now(),
        )
        await _persist_failed_command(
            session,
            command=command,
            actor=actor,
            request=data.model_dump(mode="json"),
            exc=exc,
        )
        raise


@router.get("/runtime")
async def owner_runtime(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user_rows = (
        await session.execute(
            select(User, Role.name, Organization.name)
            .outerjoin(Role, Role.id == User.role_id)
            .join(Organization, Organization.id == User.organization_id)
            .where(User.deleted_at.is_(None))
            .order_by(User.created_at.desc())
            .limit(250)
        )
    ).all()
    return {
        "generatedAt": _iso(),
        "projects": await _project_items(session),
        "organizations": await _organization_items(session, actor.organization_id),
        "users": [
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": role_name or "Unassigned",
                "organization": organization_name,
                "status": user.status,
            }
            for user, role_name, organization_name in user_rows
        ],
    }


@router.get("/executive")
async def owner_executive(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    metrics = await _executive_items(session)
    alerts = await _incident_items(session)
    return {
        "generatedAt": _iso(),
        "metrics": metrics,
        "insights": [
            {
                "id": alert["id"],
                "title": alert["title"],
                "summary": f"{alert['source']} · {alert['status']}",
                "severity": alert["severity"],
                "recommendation": "Review the incident in Owner Incident Command.",
            }
            for alert in alerts[:10]
        ],
    }


@router.get("/realtime")
async def owner_realtime(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    latest_metrics = (
        await session.scalars(
            select(MetricSample).order_by(MetricSample.timestamp.desc()).limit(50)
        )
    ).all()
    audit = await _audit_items(session)
    return {
        "generatedAt": _iso(),
        "metrics": [
            {
                "id": metric.id,
                "label": metric.name,
                "value": metric.value,
                "unit": str(metric.labels.get("unit", "")),
                "status": _metric_health_status(metric.labels),
                "updatedAt": _iso(metric.timestamp),
            }
            for metric in latest_metrics
        ],
        "events": [
            {
                "id": item["id"],
                "source": item["actor"],
                "message": item["action"],
                "severity": item["severity"],
                "createdAt": item["timestamp"],
            }
            for item in audit[:25]
        ],
    }


@router.get("/timeline")
async def owner_timeline(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    events = await _audit_items(session)
    return {
        "events": [
            {
                "id": item["id"],
                "occurredAt": item["timestamp"],
                "actor": item["actor"],
                "category": item["category"],
                "action": item["action"],
                "target": item["target"],
                "severity": item["severity"],
                "details": item["status"],
            }
            for item in events
        ]
    }


@router.get("/approvals")
async def owner_approvals(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"approvals": await _approval_items(session)}


@router.patch("/approvals/{approval_id}")
async def decide_owner_approval(
    approval_id: str,
    data: OwnerApprovalDecision,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async def decide(_command: OwnerCommandRecord) -> dict[str, Any]:
        return await _apply_live_action(
            session,
            actor,
            "approvals",
            approval_id,
            data.status,
            {"reason": data.reason},
        )

    result = await _run_audited_mutation(
        session,
        actor=actor,
        domain="approvals",
        resource_id=approval_id,
        action=data.status,
        request=data.model_dump(mode="json"),
        mutation=decide,
    )
    notifications = list(session.info.pop("phase29e_notifications", []))
    await communications.publish_many(notifications)
    return result


@router.get("/communications/overview")
async def owner_communications_overview(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await communications.delivery_statistics(session)


@router.get("/communications/deliveries")
async def owner_communication_deliveries(
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    channel: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=250, ge=1, le=1000),
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    statement = select(NotificationDelivery)
    if status_filter:
        statement = statement.where(NotificationDelivery.status == status_filter)
    if channel:
        statement = statement.where(NotificationDelivery.channel == channel)
    rows = list(
        (
            await session.scalars(
                statement.order_by(NotificationDelivery.created_at.desc()).limit(limit)
            )
        ).all()
    )
    return [communications.delivery_snapshot(item) for item in rows]


@router.post("/communications/deliveries/{delivery_id}/retry")
async def owner_retry_communication_delivery(
    delivery_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    delivery = await session.scalar(
        select(NotificationDelivery)
        .where(NotificationDelivery.id == delivery_id)
        .with_for_update()
    )
    if delivery is None:
        raise HTTPException(status_code=404, detail="Notification delivery not found")
    try:
        await communications.retry_delivery(session, delivery, actor_id=actor.id)
        await session.commit()
    except communications.ProviderNotConfigured as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Delivery provider is not configured") from exc
    except (communications.PermanentDeliveryError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return communications.delivery_snapshot(delivery)


@router.get("/support/requests")
async def owner_support_requests(
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    limit: int = Query(default=250, ge=1, le=1000),
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    statement = select(SupportRequest)
    if status_filter:
        statement = statement.where(SupportRequest.status == status_filter)
    rows = list(
        (
            await session.scalars(
                statement.order_by(SupportRequest.updated_at.desc()).limit(limit)
            )
        ).all()
    )
    return [communications.support_snapshot(item) for item in rows]


@router.get("/support/requests/{request_id}")
async def owner_support_request(
    request_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ticket = await session.get(SupportRequest, request_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Support request not found")
    messages = list(
        (
            await session.scalars(
                select(SupportMessage)
                .where(SupportMessage.support_request_id == ticket.id)
                .order_by(SupportMessage.created_at)
            )
        ).all()
    )
    return {
        **communications.support_snapshot(ticket, messages=len(messages)),
        "messages": [
            communications.support_message_snapshot(item) for item in messages
        ],
    }


@router.post("/support/requests/{request_id}/messages", status_code=status.HTTP_201_CREATED)
async def owner_support_reply(
    request_id: str,
    data: OwnerSupportMessageCreate,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ticket = await session.scalar(
        select(SupportRequest)
        .where(SupportRequest.id == request_id)
        .with_for_update()
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="Support request not found")
    try:
        message, notifications = await communications.add_support_message(
            session,
            actor,
            ticket,
            message=data.message,
            visibility=data.visibility,
            manager=True,
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await communications.publish_many(notifications)
    return communications.support_message_snapshot(message)


@router.patch("/support/requests/{request_id}")
async def owner_update_support_request(
    request_id: str,
    data: OwnerSupportStatusUpdate,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ticket = await session.scalar(
        select(SupportRequest)
        .where(SupportRequest.id == request_id)
        .with_for_update()
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="Support request not found")
    try:
        await communications.update_support_status(
            session,
            actor,
            ticket,
            status=data.status,
            assigned_to_id=data.assigned_to_id,
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return communications.support_snapshot(ticket)


@router.get("/governance/overview")
async def owner_governance_overview(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    bodies = int(await session.scalar(select(func.count(GovernanceBody.id))) or 0)
    policies = int(await session.scalar(select(func.count(GovernancePolicy.id))) or 0)
    decisions = int(await session.scalar(select(func.count(GovernanceDecision.id))) or 0)
    pending = int(
        await session.scalar(
            select(func.count(ApprovalRequest.id)).where(
                ApprovalRequest.status == "pending"
            )
        )
        or 0
    )
    return {
        "bodies": bodies,
        "policies": policies,
        "decisions": decisions,
        "pending_approvals": pending,
        "generated_at": _iso(),
    }


@router.get("/compliance-controls")
async def compliance_controls(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    return await _control_items(session, "compliance")


@router.post("/compliance-controls/{control_id}/attest")
async def attest_compliance(
    control_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async def attest(_command: OwnerCommandRecord) -> dict[str, Any]:
        return await _apply_live_action(
            session,
            actor,
            "compliance",
            control_id,
            "attest",
            {"status": "compliant"},
        )

    await _run_audited_mutation(
        session,
        actor=actor,
        domain="compliance",
        resource_id=control_id,
        action="attest",
        request={},
        mutation=attest,
    )
    record = await _control_record(session, "compliance", control_id)
    return _control_item(record)


def _notification_rule_item(rule: NotificationRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "code": rule.code,
        "name": rule.name,
        "event": rule.event_pattern,
        "audience": rule.audience,
        "channels": rule.channels,
        "enabled": rule.enabled,
        "severity": rule.severity,
        "system": rule.system,
        "version": rule.version,
        "escalationPolicyId": rule.escalation_policy_id,
        "createdAt": _iso(rule.created_at),
        "updatedAt": _iso(rule.updated_at),
    }


@router.get("/notification-rules")
async def notification_rules(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    await communications.ensure_defaults(session)
    await session.commit()
    rows = list(
        (
            await session.scalars(
                select(NotificationRule).order_by(NotificationRule.code)
            )
        ).all()
    )
    return [_notification_rule_item(item) for item in rows]


@router.patch("/notification-rules/{rule_id}")
async def update_notification_rule(
    rule_id: str,
    data: OwnerNotificationRuleUpdate,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    updates = data.model_dump(exclude_none=True)

    async def apply(_command: OwnerCommandRecord) -> dict[str, Any]:
        await communications.ensure_defaults(session)
        rule = await session.scalar(
            select(NotificationRule)
            .where(
                or_(NotificationRule.id == rule_id, NotificationRule.code == rule_id)
            )
            .with_for_update()
        )
        if rule is None:
            raise HTTPException(status_code=404, detail="Notification rule not found")
        if "name" in updates:
            rule.name = str(updates["name"]).strip()
        if "event" in updates:
            event = str(updates["event"]).strip().lower()
            if not event or len(event) > 160:
                raise HTTPException(status_code=422, detail="Notification event is invalid")
            rule.event_pattern = event
        if "audience" in updates:
            audience = str(updates["audience"]).strip().lower()
            if audience not in {"user", "organization", "workforce", "owner", "all"}:
                raise HTTPException(status_code=422, detail="Unsupported notification audience")
            rule.audience = audience
        if "channels" in updates:
            channels = list(dict.fromkeys(str(value) for value in updates["channels"]))
            if not channels or any(value not in communications.CHANNELS for value in channels):
                raise HTTPException(status_code=422, detail="Unsupported notification channel")
            if "in_app" not in channels:
                channels.insert(0, "in_app")
            rule.channels = channels
        if "enabled" in updates:
            rule.enabled = bool(updates["enabled"])
        if "severity" in updates:
            rule.severity = str(updates["severity"])
        rule.version += 1
        session.add(
            AuditEvent(
                organization_id=actor.organization_id,
                user_id=actor.id,
                action="notification.rule.updated",
                resource_type="notification_rule",
                resource_id=rule.id,
                details={"updated": sorted(updates), "code": rule.code},
            )
        )
        return _notification_rule_item(rule)

    result = await _run_audited_mutation(
        session,
        actor=actor,
        domain="notification-rules",
        resource_id=rule_id,
        action="update",
        request=updates,
        mutation=apply,
    )
    return result


@router.get("/licenses")
async def licenses(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    organizations = await _billing_items(session, actor.organization_id)
    plan_names = {
        "Enterprise": "enterprise",
        "Professional": "professional",
        "Team": "professional",
        "Starter": "starter",
        "Free": "starter",
    }
    return [
        {
            "id": item["id"],
            "organization": item["organization"],
            "plan": plan_names.get(
                str(item["plan"]),
                str(item["plan"]).strip().lower(),
            ),
            "seats": item["seats"],
            "activeSeats": item["activeSeats"],
            "status": item["status"],
            "protected": item["protected"],
        }
        for item in organizations
    ]


@router.patch("/licenses/{license_id}")
async def update_license(
    license_id: str,
    data: OwnerLicenseAction,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    request = data.model_dump(exclude_none=True)

    async def apply(_command: OwnerCommandRecord) -> dict[str, Any]:
        return await _apply_live_action(
            session,
            actor,
            "billing",
            license_id,
            data.action,
            {"seats": data.seats} if data.seats else {},
        )

    await _run_audited_mutation(
        session,
        actor=actor,
        domain="licenses",
        resource_id=license_id,
        action=data.action,
        request=request,
        mutation=apply,
    )
    items = await licenses(actor, session)
    return next(item for item in items if item["id"] == license_id)


@router.get("/releases")
async def releases(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    gates = await _control_items(session, "release")
    approval_gate = next(
        (item for item in gates if item["id"] == "approval"),
        None,
    )
    closed_at = (
        approval_gate.get("platformClosedAt") if approval_gate is not None else None
    )
    if approval_gate is not None and approval_gate["status"] == "rejected":
        release_status = "rejected"
    elif closed_at:
        release_status = "released"
    elif any(item["status"] != "passed" for item in gates):
        release_status = "blocked"
    else:
        release_status = "ready"
    created_at = min(
        (str(item["updatedAt"]) for item in gates),
        default=_iso(),
    )
    if hasattr(session, "scalars"):
        evidence_rows = list(
            (
                await session.scalars(
                    select(AuditEvent)
                    .where(
                        AuditEvent.action.in_({"release.deployment", "release.rollback"}),
                        AuditEvent.resource_type == "release_candidate",
                        AuditEvent.resource_id == "current-release",
                    )
                    .order_by(AuditEvent.created_at.desc())
                    .limit(100)
                )
            ).all()
        )
    else:
        # Compatibility for pure unit-contract callers that supply a sentinel
        # instead of a database session; production requests always use SQL.
        evidence_rows = []
    latest_evidence: dict[str, dict[str, Any]] = {}
    for event in evidence_rows:
        kind = "deployment" if event.action == "release.deployment" else "rollback"
        if kind in latest_evidence:
            continue
        details = dict(event.details or {})
        latest_evidence[kind] = {
            "id": event.id,
            "event": kind,
            "commit": details.get("commit"),
            "imageDigests": details.get("image_digests", {}),
            "validated": bool(details.get("validated")),
            "note": details.get("note"),
            "recordedBy": event.user_id or "system",
            "recordedAt": _iso(event.created_at),
        }
    return [
        {
            "id": "current-release",
            "version": _repo_version(),
            "environment": "production",
            "status": release_status,
            "closed": bool(closed_at),
            "closedAt": str(closed_at) if closed_at else None,
            "requestedBy": "Owner readiness registry",
            "createdAt": created_at,
            "deploymentEvidence": latest_evidence.get("deployment"),
            "rollbackEvidence": latest_evidence.get("rollback"),
            "gates": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "status": item["status"],
                    "ownerRequired": item["id"] == "approval",
                    "updatedAt": item["updatedAt"],
                }
                for item in gates
            ],
        }
    ]


@router.post("/releases/{candidate_id}/evidence", status_code=status.HTTP_201_CREATED)
async def record_release_evidence(
    candidate_id: str,
    data: OwnerReleaseEvidence,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if candidate_id != "current-release":
        raise HTTPException(status_code=404, detail="Release candidate not found")
    commit = data.commit.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{7,64}", commit):
        raise HTTPException(status_code=422, detail="Release evidence commit is invalid")
    image_digests: dict[str, str] = {}
    for name, digest in data.image_digests.items():
        clean_name = str(name).strip()
        clean_digest = str(digest).strip().lower()
        if not clean_name or len(clean_name) > 120:
            raise HTTPException(status_code=422, detail="Release image name is invalid")
        if clean_digest and not re.fullmatch(r"sha256:[0-9a-f]{64}", clean_digest):
            raise HTTPException(status_code=422, detail="Release image digest is invalid")
        if clean_digest:
            image_digests[clean_name] = clean_digest
    if data.validated is not True:
        raise HTTPException(status_code=409, detail="Only validated deployment or rollback evidence can be recorded")
    event = AuditEvent(
        organization_id=actor.organization_id,
        user_id=actor.id,
        action=f"release.{data.event}",
        resource_type="release_candidate",
        resource_id=candidate_id,
        details={
            "commit": commit,
            "image_digests": image_digests,
            "validated": True,
            "note": data.note.strip() or None,
            "status": "completed",
        },
    )
    session.add(event)
    await session.commit()
    return {
        "id": event.id,
        "event": data.event,
        "commit": commit,
        "imageDigests": image_digests,
        "validated": True,
        "note": data.note.strip() or None,
        "recordedBy": actor.id,
        "recordedAt": _iso(event.created_at),
    }


@router.post("/releases/{candidate_id}/decision")
async def decide_release(
    candidate_id: str,
    data: OwnerReleaseDecision,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async def decide(_command: OwnerCommandRecord) -> dict[str, Any]:
        if candidate_id != "current-release":
            raise HTTPException(
                status_code=404,
                detail="Release candidate not found",
            )
        return await _apply_live_action(
            session,
            actor,
            "release",
            "approval",
            data.decision,
            {},
        )

    await _run_audited_mutation(
        session,
        actor=actor,
        domain="release",
        resource_id=candidate_id,
        action=data.decision,
        request=data.model_dump(mode="json"),
        mutation=decide,
    )
    return (await releases(actor, session))[0]


@router.get("/finalization")
async def finalization(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    health = await _health_items(session)
    health_checks = [
        {
            "id": item["id"],
            "label": item["name"],
            "category": ("reliability" if item["id"] == "database" else "integration"),
            "status": (
                "passed"
                if item["status"] == "healthy"
                else (
                    "warning" if item["status"] in {"degraded", "warning"} else "failed"
                )
            ),
            "details": item["detail"],
        }
        for item in health
    ]
    release_category = {
        "validation": "integration",
        "security": "security",
        "performance": "performance",
        "backup": "reliability",
        "approval": "usability",
    }
    stored_release_gates = await _control_items(session, "release")
    approval_gate = next(
        (item for item in stored_release_gates if item["id"] == "approval"),
        None,
    )
    release_gates = await _revalidate_non_owner_release_gates(session)
    if approval_gate is not None:
        release_gates.append(approval_gate)
    release_checks = [
        {
            "id": f"release-{item['id']}",
            "label": item["name"],
            "category": release_category.get(item["id"], "reliability"),
            "status": (
                "passed"
                if item["status"] == "passed"
                else (
                    "failed"
                    if item["status"] in {"blocked", "failed", "rejected"}
                    else "warning"
                )
            ),
            "details": str(
                item.get(
                    "lastResult",
                    (
                        "Owner approval is recorded."
                        if item["id"] == "approval" and item["status"] == "passed"
                        else f"Release gate status: {item['status']}."
                    ),
                )
            ),
        }
        for item in release_gates
    ]
    checks = [*health_checks, *release_checks]
    completion = round(
        100 * sum(item["status"] == "passed" for item in checks) / max(1, len(checks))
    )
    return {
        "generatedAt": _iso(),
        "completion": completion,
        "checks": checks,
        "program": completion_program_snapshot(),
    }
