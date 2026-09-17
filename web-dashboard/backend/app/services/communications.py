"""Durable Phase 29E communications, notification delivery, support, and incidents.

The in-app record is always written first. External channels are represented by
separate durable delivery rows, so missing credentials, provider outages, and
retry exhaustion can never erase the user-visible notification.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import smtplib
import ssl
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Sequence, TypeVar, cast

import httpx
from app.realtime.runtime import realtime_event_runtime
from app.core.auth import UserRecord
from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.db.models import (
    Alert,
    AuditEvent,
    CommunicationEndpoint,
    EscalationPolicy,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationRule,
    Role,
    SupportMessage,
    SupportRequest,
    User,
    uuid_str,
)
from app.services import host_maintenance_notifications as notification_maintenance
from app.services.telegram_worker import TelegramBotAPI, load_bot_token
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Table, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

CHANNELS = ("in_app", "email", "push", "telegram", "whatsapp")
EXTERNAL_CHANNELS = tuple(channel for channel in CHANNELS if channel != "in_app")
SEVERITY_RANK = {"info": 0, "success": 0, "warning": 1, "critical": 2}
DELIVERY_TERMINAL = frozenset(
    {"delivered", "acknowledged", "skipped", "unconfigured", "dead_letter"}
)


class CommunicationError(RuntimeError):
    """Base class for sanitized delivery failures."""


class ProviderNotConfigured(CommunicationError):
    """The deployment does not have the required provider credentials."""


class PermanentDeliveryError(CommunicationError):
    """The provider rejected a destination or payload permanently."""


def now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    )
    return Fernet(key)


def encrypt_address(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_address(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise PermanentDeliveryError("endpoint-decryption-failed") from exc


def address_hash(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def mask_address(channel: str, address: str) -> str:
    value = address.strip()
    if channel == "email" and "@" in value:
        local, domain = value.split("@", 1)
        return f"{local[:2]}***@{domain}"
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***{value[-3:]}"



def _telegram_scope_token_file(scope: str) -> str:
    if scope == "user":
        return settings.AIOS_USER_TELEGRAM_BOT_TOKEN_FILE
    if scope == "owner":
        return settings.AIOS_TELEGRAM_BOT_TOKEN_FILE
    raise ValueError("Unsupported Telegram bot scope")


def _telegram_scope_ready(scope: str) -> bool:
    try:
        load_bot_token(_telegram_scope_token_file(scope))
        return True
    except (OSError, ValueError):
        return False


def telegram_scope_state(scope: str) -> dict[str, Any]:
    ready = _telegram_scope_ready(scope)
    return {
        "ready": ready,
        "reason": "ready" if ready else f"{scope} Telegram bot token is not configured",
    }


def channel_readiness() -> list[dict[str, Any]]:
    """Return truthful deployment readiness without returning any credential."""

    email_ready = bool(settings.SMTP_HOST) and (
        not settings.SMTP_USER or bool(settings.SMTP_PASSWORD)
    )
    firebase_path = Path(settings.FIREBASE_ADMIN_CREDENTIALS_JSON or "")
    push_ready = False
    if settings.FIREBASE_PROJECT_ID and settings.FIREBASE_ADMIN_CREDENTIALS_JSON:
        try:
            firebase_document = json.loads(firebase_path.read_text(encoding="utf-8"))
            push_ready = bool(
                firebase_path.is_file()
                and not firebase_path.is_symlink()
                and isinstance(firebase_document, dict)
                and firebase_document.get("type") == "service_account"
                and firebase_document.get("project_id") == settings.FIREBASE_PROJECT_ID
                and all(
                    str(firebase_document.get(key) or "").strip()
                    for key in ("client_email", "private_key")
                )
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            push_ready = False
    owner_telegram_ready = _telegram_scope_ready("owner")
    user_telegram_ready = _telegram_scope_ready("user")
    telegram_ready = owner_telegram_ready or user_telegram_ready
    telegram_reason = (
        "ready"
        if telegram_ready
        else "owner and user Telegram token files are not configured"
    )
    whatsapp_ready = bool(
        settings.WHATSAPP_ACCESS_TOKEN
        and settings.WHATSAPP_PHONE_NUMBER_ID
        and settings.WHATSAPP_API_BASE
    )
    values = {
        "in_app": (True, "ready", False, ["persistent", "realtime", "read_receipt"]),
        "email": (
            email_ready,
            "ready" if email_ready else "SMTP host/credentials are not configured",
            False,
            ["delivery_receipt", "retry"],
        ),
        "push": (
            push_ready,
            "ready" if push_ready else "Firebase Admin credentials are not configured",
            False,
            ["delivery_receipt", "retry", "device_endpoint"],
        ),
        "telegram": (
            telegram_ready,
            telegram_reason,
            not user_telegram_ready,
            [
                "delivery_receipt",
                "retry",
                "chat_endpoint",
                *(["owner_bot"] if owner_telegram_ready else []),
                *(["user_bot"] if user_telegram_ready else []),
            ],
        ),
        "whatsapp": (
            whatsapp_ready,
            "ready"
            if whatsapp_ready
            else "WhatsApp API base, phone number ID, or token is not configured",
            True,
            ["delivery_receipt", "retry", "phone_endpoint"],
        ),
    }
    labels = {
        "in_app": "In-app",
        "email": "Email",
        "push": "Push",
        "telegram": "Telegram",
        "whatsapp": "WhatsApp",
    }
    return [
        {
            "id": channel,
            "name": labels[channel],
            "configured": ready,
            "ready": ready,
            "status": "ready" if ready else "unconfigured",
            "reason": reason,
            "owner_only": owner_only,
            "capabilities": capabilities,
        }
        for channel, (ready, reason, owner_only, capabilities) in values.items()
    ]


def channel_state(channel: str) -> dict[str, Any]:
    try:
        return next(item for item in channel_readiness() if item["id"] == channel)
    except StopIteration as exc:
        raise ValueError(f"Unsupported communication channel: {channel}") from exc


DEFAULT_ESCALATION_POLICIES: tuple[dict[str, Any], ...] = (
    {
        "code": "owner-critical",
        "name": "Critical Owner Escalation",
        "description": "Escalate critical platform events to the protected owner audience.",
        "severity_threshold": "critical",
        "steps": [
            {"delay_seconds": 0, "channels": ["in_app", "email"]},
            {"delay_seconds": 300, "channels": ["push", "telegram"]},
            {"delay_seconds": 900, "channels": ["whatsapp"]},
        ],
    },
    {
        "code": "approval-reminder",
        "name": "Approval Reminder",
        "description": "Keep owner approval requests visible until decided.",
        "severity_threshold": "warning",
        "steps": [
            {"delay_seconds": 0, "channels": ["in_app", "email"]},
            {"delay_seconds": 1800, "channels": ["push", "telegram"]},
        ],
    },
)

DEFAULT_RULES: tuple[dict[str, Any], ...] = (
    {
        "code": "project-completed",
        "name": "Project completion",
        "event_pattern": "project.completed",
        "audience": "organization",
        "channels": ["in_app", "email", "push"],
        "severity": "info",
    },
    {
        "code": "owner-approval",
        "name": "Owner approval required",
        "event_pattern": "owner.approval.required",
        "audience": "owner",
        "channels": ["in_app", "email", "push", "telegram"],
        "severity": "warning",
        "escalation": "approval-reminder",
    },
    {
        "code": "critical-incident",
        "name": "Critical incident",
        "event_pattern": "incident.critical",
        "audience": "owner",
        "channels": ["in_app", "email", "push", "telegram", "whatsapp"],
        "severity": "critical",
        "escalation": "owner-critical",
    },
    {
        "code": "support-created",
        "name": "Support request created",
        "event_pattern": "support.request.created",
        "audience": "owner",
        "channels": ["in_app", "email"],
        "severity": "warning",
    },
    {
        "code": "support-reply",
        "name": "Support request updated",
        "event_pattern": "support.request.updated",
        "audience": "user",
        "channels": ["in_app", "email", "push"],
        "severity": "info",
    },
    {
        "code": "three-d-processing",
        "name": "3D generation progress",
        "event_pattern": "3d.job.processing",
        "audience": "user",
        "channels": ["in_app", "push"],
        "severity": "info",
    },
    {
        "code": "three-d-completed",
        "name": "3D generation completed",
        "event_pattern": "3d.job.completed",
        "audience": "user",
        "channels": ["in_app", "email", "push"],
        "severity": "success",
    },
    {
        "code": "three-d-clarification",
        "name": "3D clarification required",
        "event_pattern": "3d.job.clarification_required",
        "audience": "user",
        "channels": ["in_app", "email", "push"],
        "severity": "warning",
    },
    {
        "code": "three-d-cancelled",
        "name": "3D generation cancelled",
        "event_pattern": "3d.job.cancelled",
        "audience": "user",
        "channels": ["in_app", "push"],
        "severity": "warning",
    },
    {
        "code": "three-d-failed",
        "name": "3D generation failed",
        "event_pattern": "3d.job.failed",
        "audience": "user",
        "channels": ["in_app", "email", "push"],
        "severity": "warning",
    },
    {
        "code": "meeting-invitation",
        "name": "Meeting invitation",
        "event_pattern": "meeting.invited",
        "audience": "user",
        "channels": ["in_app", "email", "push"],
        "severity": "info",
    },
    {
        "code": "meeting-decision",
        "name": "Meeting approval decision",
        "event_pattern": "meeting.approval.decided",
        "audience": "user",
        "channels": ["in_app", "email", "push"],
        "severity": "warning",
    },
    {
        "code": "governance-decision",
        "name": "Governance decision",
        "event_pattern": "governance.decision.decided",
        "audience": "organization",
        "channels": ["in_app", "email"],
        "severity": "warning",
    },
)


async def ensure_defaults(session: AsyncSession) -> None:
    policies: dict[str, EscalationPolicy] = {}
    for data in DEFAULT_ESCALATION_POLICIES:
        item = await session.scalar(
            select(EscalationPolicy).where(EscalationPolicy.code == data["code"])
        )
        if item is None:
            item = EscalationPolicy(id=uuid_str(), **data)
            session.add(item)
            await session.flush()
        policies[item.code] = item
    for data in DEFAULT_RULES:
        rule = await session.scalar(
            select(NotificationRule).where(NotificationRule.code == data["code"])
        )
        if rule is None:
            values = dict(data)
            escalation = values.pop("escalation", None)
            rule = NotificationRule(
                id=uuid_str(),
                escalation_policy_id=(policies[escalation].id if escalation else None),
                system=True,
                **values,
            )
            session.add(rule)
    await session.flush()


def endpoint_snapshot(endpoint: CommunicationEndpoint) -> dict[str, Any]:
    masked = str(endpoint.endpoint_metadata.get("masked_address") or "***")
    return {
        "id": endpoint.id,
        "channel": endpoint.channel,
        "label": endpoint.label,
        "status": endpoint.status,
        "verified": endpoint.verified_at is not None,
        "verified_at": iso(endpoint.verified_at),
        "last_used_at": iso(endpoint.last_used_at),
        "masked_address": masked,
        "created_at": iso(endpoint.created_at),
        "updated_at": iso(endpoint.updated_at),
    }


async def register_endpoint(
    session: AsyncSession,
    actor: UserRecord,
    *,
    channel: str,
    address: str,
    label: str = "Primary",
    verified: bool | None = None,
) -> CommunicationEndpoint:
    normalized_channel = channel.strip().lower()
    normalized_address = address.strip()
    if normalized_channel not in EXTERNAL_CHANNELS:
        raise ValueError("Only external communication endpoints can be registered")
    if not normalized_address or len(normalized_address) > 2048:
        raise ValueError("Communication endpoint is invalid")
    digest = address_hash(normalized_address)
    endpoint = await session.scalar(
        select(CommunicationEndpoint).where(
            CommunicationEndpoint.user_id == actor.id,
            CommunicationEndpoint.channel == normalized_channel,
            CommunicationEndpoint.address_hash == digest,
        )
    )
    automatic_verification = normalized_channel in {"email", "push"}
    verified_at = now() if (automatic_verification if verified is None else verified) else None
    if endpoint is None:
        endpoint = CommunicationEndpoint(
            id=uuid_str(),
            organization_id=actor.organization_id,
            user_id=actor.id,
            channel=normalized_channel,
            address_ciphertext=encrypt_address(normalized_address),
            address_hash=digest,
            label=label.strip() or "Primary",
            status="active",
            verified_at=verified_at,
            endpoint_metadata={
                "masked_address": mask_address(normalized_channel, normalized_address)
            },
        )
        session.add(endpoint)
    else:
        endpoint.address_ciphertext = encrypt_address(normalized_address)
        endpoint.label = label.strip() or endpoint.label
        endpoint.status = "active"
        endpoint.verified_at = endpoint.verified_at or verified_at
        endpoint.endpoint_metadata = {
            **endpoint.endpoint_metadata,
            "masked_address": mask_address(normalized_channel, normalized_address),
        }
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="communication.endpoint.registered",
            resource_type="communication_endpoint",
            resource_id=endpoint.id,
            details={"channel": normalized_channel, "verified": bool(endpoint.verified_at)},
        )
    )
    await session.flush()
    return endpoint


async def ensure_email_endpoint(
    session: AsyncSession, user: User
) -> CommunicationEndpoint:
    digest = address_hash(user.email)
    endpoint = await session.scalar(
        select(CommunicationEndpoint).where(
            CommunicationEndpoint.user_id == user.id,
            CommunicationEndpoint.channel == "email",
            CommunicationEndpoint.address_hash == digest,
        )
    )
    if endpoint is None:
        endpoint = CommunicationEndpoint(
            id=uuid_str(),
            organization_id=user.organization_id,
            user_id=user.id,
            channel="email",
            address_ciphertext=encrypt_address(user.email),
            address_hash=digest,
            label="Account email",
            status="active",
            verified_at=now(),
            endpoint_metadata={"masked_address": mask_address("email", user.email)},
        )
        session.add(endpoint)
        await session.flush()
    return endpoint


async def ensure_owner_telegram_endpoint(
    session: AsyncSession, user: User
) -> CommunicationEndpoint | None:
    """Bind the single configured owner Telegram identity to the Super Owner.

    The Telegram operations worker already enforces ``AIOS_TELEGRAM_ALLOWED_USERS``.
    When exactly one Telegram identity is allowlisted, that identity is
    unambiguous and can safely become the Super Owner's verified notification
    endpoint. Multiple allowlisted identities remain an explicit configuration
    boundary and are never guessed. Existing inactive/deleted endpoints are
    respected rather than silently reactivated.
    """

    allowed = [str(value).strip() for value in settings.AIOS_TELEGRAM_ALLOWED_USERS]
    allowed = [value for value in allowed if value]
    if len(allowed) != 1 or user.role_id is None:
        return None
    role = await session.get(Role, user.role_id)
    if role is None or role.name != "Super Owner":
        return None
    address = allowed[0]
    digest = address_hash(address)
    endpoint = await session.scalar(
        select(CommunicationEndpoint).where(
            CommunicationEndpoint.user_id == user.id,
            CommunicationEndpoint.channel == "telegram",
            CommunicationEndpoint.address_hash == digest,
        )
    )
    if endpoint is not None:
        if endpoint.status == "active" and endpoint.verified_at is not None:
            return endpoint
        return None
    endpoint = CommunicationEndpoint(
        id=uuid_str(),
        organization_id=user.organization_id,
        user_id=user.id,
        channel="telegram",
        address_ciphertext=encrypt_address(address),
        address_hash=digest,
        label="Owner Telegram",
        status="active",
        verified_at=now(),
        endpoint_metadata={
            "masked_address": mask_address("telegram", address),
            "source": "single_owner_allowlist",
        },
    )
    session.add(endpoint)
    await session.flush()
    return endpoint


async def list_endpoints(
    session: AsyncSession, actor: UserRecord
) -> list[CommunicationEndpoint]:
    return list(
        (
            await session.scalars(
                select(CommunicationEndpoint)
                .where(
                    CommunicationEndpoint.organization_id == actor.organization_id,
                    CommunicationEndpoint.user_id == actor.id,
                    CommunicationEndpoint.status != "deleted",
                )
                .order_by(CommunicationEndpoint.channel, CommunicationEndpoint.created_at)
            )
        ).all()
    )


async def delete_endpoint(
    session: AsyncSession, actor: UserRecord, endpoint_id: str
) -> CommunicationEndpoint:
    endpoint = await session.scalar(
        select(CommunicationEndpoint)
        .where(
            CommunicationEndpoint.id == endpoint_id,
            CommunicationEndpoint.organization_id == actor.organization_id,
            CommunicationEndpoint.user_id == actor.id,
            CommunicationEndpoint.status != "deleted",
        )
        .with_for_update()
    )
    if endpoint is None:
        raise LookupError("Communication endpoint not found")
    endpoint.status = "deleted"
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="communication.endpoint.deleted",
            resource_type="communication_endpoint",
            resource_id=endpoint.id,
            details={"channel": endpoint.channel},
        )
    )
    return endpoint


def preference_snapshot(preference: NotificationPreference) -> dict[str, Any]:
    return {
        "id": preference.id,
        "category": preference.category,
        "enabled": preference.enabled,
        "channels": preference.channels,
        "minimum_severity": preference.minimum_severity,
        "quiet_hours_start": preference.quiet_hours_start,
        "quiet_hours_end": preference.quiet_hours_end,
        "timezone": preference.timezone,
        "digest_mode": preference.digest_mode,
        "updated_at": iso(preference.updated_at),
    }


async def get_preferences(
    session: AsyncSession, actor: UserRecord
) -> list[NotificationPreference]:
    rows = list(
        (
            await session.scalars(
                select(NotificationPreference)
                .where(
                    NotificationPreference.organization_id == actor.organization_id,
                    NotificationPreference.user_id == actor.id,
                )
                .order_by(NotificationPreference.category)
            )
        ).all()
    )
    if not rows:
        default = NotificationPreference(
            id=uuid_str(),
            organization_id=actor.organization_id,
            user_id=actor.id,
            category="*",
            enabled=True,
            channels=["in_app", "email", "push"],
            minimum_severity="info",
            timezone="UTC",
            digest_mode="immediate",
        )
        session.add(default)
        await session.flush()
        rows = [default]
    return rows


async def update_preference(
    session: AsyncSession,
    actor: UserRecord,
    *,
    category: str,
    enabled: bool,
    channels: Sequence[str],
    minimum_severity: str,
    quiet_hours_start: str | None = None,
    quiet_hours_end: str | None = None,
    timezone: str = "UTC",
    digest_mode: str = "immediate",
) -> NotificationPreference:
    normalized_channels = list(dict.fromkeys(item.strip().lower() for item in channels))
    if any(item not in CHANNELS for item in normalized_channels):
        raise ValueError("Unsupported notification channel")
    if minimum_severity not in SEVERITY_RANK:
        raise ValueError("Unsupported notification severity")
    if digest_mode not in {"immediate", "hourly", "daily"}:
        raise ValueError("Unsupported digest mode")
    normalized_category = category.strip().lower() or "*"
    preference = await session.scalar(
        select(NotificationPreference)
        .where(
            NotificationPreference.user_id == actor.id,
            NotificationPreference.category == normalized_category,
        )
        .with_for_update()
    )
    if preference is None:
        preference = NotificationPreference(
            id=uuid_str(),
            organization_id=actor.organization_id,
            user_id=actor.id,
            category=normalized_category,
        )
        session.add(preference)
    preference.enabled = enabled
    preference.channels = normalized_channels or ["in_app"]
    preference.minimum_severity = minimum_severity
    preference.quiet_hours_start = quiet_hours_start
    preference.quiet_hours_end = quiet_hours_end
    preference.timezone = timezone.strip() or "UTC"
    preference.digest_mode = digest_mode
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="notification.preference.updated",
            resource_type="notification_preference",
            resource_id=preference.id,
            details={
                "category": normalized_category,
                "enabled": enabled,
                "channels": normalized_channels,
                "minimum_severity": minimum_severity,
            },
        )
    )
    await session.flush()
    return preference


async def _matching_rule(
    session: AsyncSession, organization_id: str, event_key: str
) -> NotificationRule | None:
    await ensure_defaults(session)
    rules = list(
        (
            await session.scalars(
                select(NotificationRule)
                .where(
                    NotificationRule.enabled.is_(True),
                    or_(
                        NotificationRule.organization_id.is_(None),
                        NotificationRule.organization_id == organization_id,
                    ),
                )
                .order_by(NotificationRule.organization_id.desc().nullslast())
            )
        ).all()
    )
    for rule in rules:
        pattern = rule.event_pattern
        if pattern == event_key or (pattern.endswith("*") and event_key.startswith(pattern[:-1])):
            return rule
    return None


async def _effective_channels(
    session: AsyncSession,
    user_id: str,
    category: str,
    severity: str,
    proposed: Sequence[str],
) -> list[str]:
    preferences = list(
        (
            await session.scalars(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == user_id,
                    NotificationPreference.category.in_({"*", category}),
                )
            )
        ).all()
    )
    preference = next((item for item in preferences if item.category == category), None)
    preference = preference or next((item for item in preferences if item.category == "*"), None)
    channels = list(dict.fromkeys(proposed))
    if preference is not None:
        if not preference.enabled or SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK.get(
            preference.minimum_severity, 0
        ):
            return ["in_app"]
        channels = [item for item in channels if item in preference.channels]
    if "in_app" not in channels:
        channels.insert(0, "in_app")
    return [item for item in channels if item in CHANNELS]


def notification_snapshot(notification: Notification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "organization_id": notification.organization_id,
        "user_id": notification.recipient_id,
        "type": notification.type,
        "category": notification.category,
        "event_key": notification.event_key,
        "audience": notification.audience,
        "title": notification.title,
        "message": notification.message,
        "severity": notification.severity,
        "source_type": notification.source_type,
        "source_id": notification.source_id,
        "correlation_id": notification.correlation_id,
        "payload": notification.payload,
        "read": notification.read_at is not None,
        "archived": notification.archived_at is not None,
        "read_at": iso(notification.read_at),
        "archived_at": iso(notification.archived_at),
        "created_at": iso(notification.created_at),
        "updated_at": iso(notification.updated_at),
    }


def delivery_snapshot(delivery: NotificationDelivery) -> dict[str, Any]:
    return {
        "id": delivery.id,
        "notification_id": delivery.notification_id,
        "channel": delivery.channel,
        "status": delivery.status,
        "attempt_count": delivery.attempt_count,
        "max_attempts": delivery.max_attempts,
        "next_attempt_at": iso(delivery.next_attempt_at),
        "provider_message_id": delivery.provider_message_id,
        "error_code": delivery.error_code,
        "delivered_at": iso(delivery.delivered_at),
        "acknowledged_at": iso(delivery.acknowledged_at),
        "dead_lettered_at": iso(delivery.dead_lettered_at),
        "created_at": iso(delivery.created_at),
        "updated_at": iso(delivery.updated_at),
    }


async def _ensure_notification_deliveries(
    session: AsyncSession,
    recipient: User,
    notification: Notification,
    selected: Sequence[str],
    *,
    severity: str,
) -> list[NotificationDelivery]:
    existing_channels = set(
        (
            await session.scalars(
                select(NotificationDelivery.channel).where(
                    NotificationDelivery.notification_id == notification.id
                )
            )
        ).all()
    )
    missing = [channel for channel in selected if channel not in existing_channels]
    if not missing:
        return []

    endpoints = list(
        (
            await session.scalars(
                select(CommunicationEndpoint).where(
                    CommunicationEndpoint.user_id == recipient.id,
                    CommunicationEndpoint.status == "active",
                    CommunicationEndpoint.verified_at.is_not(None),
                )
            )
        ).all()
    )
    endpoint_by_channel: dict[str, CommunicationEndpoint] = {}
    for endpoint in endpoints:
        endpoint_by_channel.setdefault(endpoint.channel, endpoint)
    if "email" in missing and "email" not in endpoint_by_channel:
        endpoint_by_channel["email"] = await ensure_email_endpoint(session, recipient)
    if "telegram" in missing and "telegram" not in endpoint_by_channel:
        telegram_endpoint = await ensure_owner_telegram_endpoint(session, recipient)
        if telegram_endpoint is not None:
            endpoint_by_channel["telegram"] = telegram_endpoint

    created: list[NotificationDelivery] = []
    for channel in missing:
        state = channel_state(channel)
        selected_endpoint = endpoint_by_channel.get(channel)
        if channel == "in_app":
            delivery_status = "delivered"
            delivered_at = now()
            error_code = None
        elif not state["ready"]:
            delivery_status = "unconfigured"
            delivered_at = None
            error_code = "provider_unconfigured"
        elif selected_endpoint is None:
            delivery_status = "skipped"
            delivered_at = None
            error_code = "recipient_endpoint_missing"
        else:
            delivery_status = "queued"
            delivered_at = None
            error_code = None
        delivery = NotificationDelivery(
            id=uuid_str(),
            organization_id=recipient.organization_id,
            notification_id=notification.id,
            endpoint_id=selected_endpoint.id if selected_endpoint else None,
            channel=channel,
            status=delivery_status,
            priority=100 if severity == "critical" else 50,
            max_attempts=settings.COMMUNICATION_MAX_ATTEMPTS,
            next_attempt_at=now() if delivery_status == "queued" else None,
            delivered_at=delivered_at,
            error_code=error_code,
            idempotency_key=f"{notification.id}:{channel}",
            delivery_metadata={
                "provider_ready_at_queue_time": state["ready"],
                "recipient_endpoint_present": selected_endpoint is not None,
            },
        )
        session.add(delivery)
        created.append(delivery)
    await session.flush()
    return created


async def create_notification(
    session: AsyncSession,
    recipient: User,
    *,
    event_key: str,
    category: str,
    title: str,
    message: str,
    severity: str = "info",
    audience: str = "user",
    channels: Sequence[str] | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    correlation_id: str | None = None,
    dedupe_key: str | None = None,
    payload: dict[str, Any] | None = None,
    actor_id: str | None = None,
    respect_preferences: bool = True,
) -> Notification:
    if severity not in SEVERITY_RANK:
        raise ValueError("Unsupported notification severity")
    normalized_event = event_key.strip().lower()
    normalized_category = category.strip().lower() or "system"
    rule = await _matching_rule(session, recipient.organization_id, normalized_event)
    proposed = list(channels or (rule.channels if rule else ["in_app"]))
    if respect_preferences:
        selected = await _effective_channels(
            session, recipient.id, normalized_category, severity, proposed
        )
    else:
        selected = [item for item in dict.fromkeys(proposed) if item in CHANNELS]
        if "in_app" not in selected:
            selected.insert(0, "in_app")
    if dedupe_key:
        existing = await session.scalar(
            select(Notification).where(
                Notification.organization_id == recipient.organization_id,
                Notification.dedupe_key == dedupe_key,
            )
        )
        if existing is not None:
            added = await _ensure_notification_deliveries(
                session, recipient, existing, selected, severity=existing.severity
            )
            if added:
                session.add(
                    AuditEvent(
                        organization_id=recipient.organization_id,
                        user_id=actor_id,
                        action="notification.delivery.channels_reconciled",
                        resource_type="notification",
                        resource_id=existing.id,
                        details={"channels": [item.channel for item in added]},
                    )
                )
                await session.flush()
            return existing
    notification = Notification(
        id=uuid_str(),
        organization_id=recipient.organization_id,
        recipient_id=recipient.id,
        type=normalized_event,
        category=normalized_category,
        event_key=normalized_event,
        audience=audience,
        title=title.strip(),
        message=message.strip(),
        severity=severity,
        source_type=source_type,
        source_id=source_id,
        correlation_id=correlation_id,
        dedupe_key=dedupe_key,
        payload=payload or {},
    )
    session.add(notification)
    await session.flush()

    await _ensure_notification_deliveries(
        session, recipient, notification, selected, severity=severity
    )

    session.add(
        AuditEvent(
            organization_id=recipient.organization_id,
            user_id=actor_id,
            action="notification.created",
            resource_type="notification",
            resource_id=notification.id,
            details={
                "event_key": normalized_event,
                "category": normalized_category,
                "severity": severity,
                "channels": selected,
                "recipient_id": recipient.id,
            },
        )
    )
    await session.flush()
    return notification


async def publish_realtime(notification: Notification) -> None:
    try:
        await realtime_event_runtime.publish(
            notification.organization_id,
            {"type": "notification.created", "notification": notification_snapshot(notification)},
        )
    except Exception:
        logger.warning(
            "Notification persisted but realtime publish failed",
            notification_id=notification.id,
        )


async def audience_users(
    session: AsyncSession,
    *,
    organization_id: str,
    audience: str,
    explicit_user_ids: Sequence[str] | None = None,
) -> list[User]:
    statement = (
        select(User)
        .outerjoin(Role, Role.id == User.role_id)
        .where(User.deleted_at.is_(None), User.status.in_({"active", "online"}))
    )
    if audience not in {"owner", "platform_owner"}:
        statement = statement.where(User.organization_id == organization_id)
    if audience == "owner":
        statement = statement.where(
            Role.name.in_({"Super Owner", "Owner"}),
            or_(
                User.organization_id == organization_id,
                Role.name == "Super Owner",
            ),
        )
    elif audience == "platform_owner":
        statement = statement.where(Role.name == "Super Owner")
    elif audience == "workforce":
        statement = statement.where(Role.name.notin_({"Super Owner", "Owner"}))
    elif audience == "user":
        ids = list(dict.fromkeys(explicit_user_ids or []))
        if not ids:
            return []
        statement = statement.where(User.id.in_(ids))
    elif audience not in {"organization", "all", "platform_owner"}:
        raise ValueError("Unsupported notification audience")
    return list((await session.scalars(statement.order_by(User.id))).all())


async def notify_audience(
    session: AsyncSession,
    *,
    organization_id: str,
    audience: str,
    event_key: str,
    category: str,
    title: str,
    message: str,
    severity: str = "info",
    explicit_user_ids: Sequence[str] | None = None,
    channels: Sequence[str] | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    correlation_id: str | None = None,
    dedupe_prefix: str | None = None,
    payload: dict[str, Any] | None = None,
    actor_id: str | None = None,
    respect_preferences: bool = True,
) -> list[Notification]:
    users = await audience_users(
        session,
        organization_id=organization_id,
        audience=audience,
        explicit_user_ids=explicit_user_ids,
    )
    notifications: list[Notification] = []
    for user in users:
        notification = await create_notification(
            session,
            user,
            event_key=event_key,
            category=category,
            title=title,
            message=message,
            severity=severity,
            audience=audience,
            channels=channels,
            source_type=source_type,
            source_id=source_id,
            correlation_id=correlation_id,
            dedupe_key=f"{dedupe_prefix}:{user.id}" if dedupe_prefix else None,
            payload=payload,
            actor_id=actor_id,
            respect_preferences=respect_preferences,
        )
        notifications.append(notification)
    return notifications


def _send_email(address: str, notification: NotificationMessageData) -> str:
    state = channel_state("email")
    if not state["ready"]:
        raise ProviderNotConfigured("email-provider-unconfigured")
    message = EmailMessage()
    message["Subject"] = notification.title
    message["From"] = settings.SMTP_FROM_EMAIL or settings.SMTP_USER or "noreply@aionex.local"
    message["To"] = address
    message.set_content(notification.message)
    smtp_host = settings.SMTP_HOST
    if not smtp_host:
        raise ProviderNotConfigured("email-provider-unconfigured")
    tls_context = ssl.create_default_context()
    smtp_client: smtplib.SMTP | smtplib.SMTP_SSL
    if settings.SMTP_SSL:
        smtp_client = smtplib.SMTP_SSL(
            smtp_host, settings.SMTP_PORT, timeout=15, context=tls_context
        )
    else:
        smtp_client = smtplib.SMTP(smtp_host, settings.SMTP_PORT, timeout=15)

    operation_error: BaseException | None = None
    refused: dict[str, Any] = {}
    try:
        with smtp_client as smtp:
            try:
                smtp.ehlo()
                if settings.SMTP_TLS and not settings.SMTP_SSL:
                    smtp.starttls(context=tls_context)
                    smtp.ehlo()
                if settings.SMTP_USER:
                    if not settings.SMTP_PASSWORD:
                        raise ProviderNotConfigured("smtp-password-unconfigured")
                    smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                refused = smtp.send_message(message)
            except BaseException as exc:
                operation_error = exc
    except BaseException:
        if isinstance(operation_error, asyncio.CancelledError):
            operation_error.add_note("SMTP client cleanup was not confirmed")
            raise operation_error
        raise NotificationDispatchUncertain("smtp-client-cleanup-unconfirmed") from None
    if operation_error is not None:
        if isinstance(operation_error, smtplib.SMTPRecipientsRefused):
            # Only send_message can supply this proof; close errors never do.
            recipients = operation_error.recipients
            response_codes = [
                value[0] for value in recipients.values()
                if isinstance(value, tuple) and value and type(value[0]) is int
            ]
            retryable = bool(response_codes) and len(response_codes) == len(
                recipients
            ) and all(400 <= code < 500 for code in response_codes)
            raise _DefiniteDeliveryRejection(
                "smtp-all-recipients-refused", retryable=retryable
            ) from None
        raise operation_error
    if refused:
        raise NotificationDispatchUncertain("smtp-partial-recipient-refusal")
    return f"smtp:{notification.id}"


_firebase_app: Any | None = None


def _send_push(address: str, notification: NotificationMessageData) -> str:
    global _firebase_app
    state = channel_state("push")
    if not state["ready"]:
        raise ProviderNotConfigured("push-provider-unconfigured")
    try:
        import firebase_admin  # type: ignore[import-untyped]
        from firebase_admin import credentials, messaging  # type: ignore[import-untyped]

        if _firebase_app is None:
            try:
                _firebase_app = firebase_admin.get_app("aionex-communications")
            except ValueError:
                _firebase_app = firebase_admin.initialize_app(
                    credentials.Certificate(settings.FIREBASE_ADMIN_CREDENTIALS_JSON),
                    {"projectId": settings.FIREBASE_PROJECT_ID},
                    name="aionex-communications",
                )
        result = messaging.send(messaging.Message(token=address, notification=messaging.Notification(title=notification.title, body=notification.message[:1024]), data={'notification_id': notification.id, 'event_key': notification.event_key, 'severity': notification.severity}), app=_firebase_app)
        if not isinstance(result, str) or not result.strip() or len(result) > 255:
            raise NotificationDispatchUncertain("push-acknowledgement-invalid")
        return result
    except ProviderNotConfigured:
        raise
    except Exception as exc:
        name = type(exc).__name__
        if name in {"UnregisteredError", "SenderIdMismatchError", "InvalidArgumentError"}:
            raise PermanentDeliveryError(name) from exc
        raise CommunicationError(name) from exc


async def _send_telegram(
    address: str,
    notification: NotificationMessageData,
    *,
    scope: str = "owner",
) -> str:
    state = telegram_scope_state(scope)
    if not state["ready"]:
        raise ProviderNotConfigured("telegram-provider-unconfigured")
    try:
        chat_id = int(address)
    except ValueError as exc:
        raise _NoSendDeliveryError("telegram-chat-id-invalid") from exc
    api = TelegramBotAPI(load_bot_token(_telegram_scope_token_file(scope)))
    try:
        response = await api.send_message_response(
            chat_id, f"{notification.title}\n\n{notification.message}"
        )
        try:
            decoded = response.json()
        except ValueError:
            raise NotificationDispatchUncertain("telegram-invalid-response") from None
        if not isinstance(decoded, dict):
            raise NotificationDispatchUncertain("telegram-invalid-response")
        if response.status_code == 200 and decoded.get("ok") is True:
            result = decoded.get("result")
            message_id = result.get("message_id") if isinstance(result, dict) else None
            chat = result.get("chat") if isinstance(result, dict) else None
            recipient_id = chat.get("id") if isinstance(chat, dict) else None
            sent_at = result.get("date") if isinstance(result, dict) else None
            if (
                type(message_id) is not int
                or message_id <= 0
                or type(recipient_id) is not int
                or recipient_id != chat_id
                or type(sent_at) is not int
                or sent_at <= 0
                or "error_code" in decoded
            ):
                raise NotificationDispatchUncertain("telegram-acknowledgement-invalid")
            return f"telegram:{scope}:{notification.id}:{message_id}"
        parameters = decoded.get("parameters")
        retry_after = (
            parameters.get("retry_after") if isinstance(parameters, dict) else None
        )
        if (
            response.status_code == 429
            and decoded.get("ok") is False
            and type(decoded.get("error_code")) is int
            and decoded["error_code"] == 429
            and type(retry_after) is int
            and 0 < retry_after <= 30 * 86400
        ):
            # Telegram documents retry_after for a rejected flood-control request.
            raise _DefiniteDeliveryRejection(
                "telegram-flood-control",
                retryable=True,
                retry_after_seconds=retry_after,
            )
        raise NotificationDispatchUncertain("telegram-outcome-uncertain")
    finally:
        pending = sys.exception()
        try:
            await api.close()
        except BaseException:
            if isinstance(pending, asyncio.CancelledError):
                pending.add_note("Telegram client cleanup was not confirmed")
                raise pending
            raise NotificationDispatchUncertain(
                "telegram-client-cleanup-unconfirmed"
            ) from None


async def _send_whatsapp(
    address: str,
    notification: NotificationMessageData,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    state = channel_state("whatsapp")
    if not state["ready"]:
        raise ProviderNotConfigured("whatsapp-provider-unconfigured")
    base = str(settings.WHATSAPP_API_BASE).rstrip("/")
    url = f"{base}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": address,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": f"{notification.title}\n\n{notification.message}"[:4096],
        },
    }
    client = httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(20, connect=10),
        follow_redirects=False,
    )
    try:
        response = await client.post(url, headers=headers, json=payload)
    finally:
        pending = sys.exception()
        try:
            await client.aclose()
        except BaseException:
            if isinstance(pending, asyncio.CancelledError):
                pending.add_note("WhatsApp client cleanup was not confirmed")
                raise pending
            raise NotificationDispatchUncertain(
                "whatsapp-client-cleanup-unconfirmed"
            ) from None
    if response.status_code not in {200, 201, 202}:
        raise NotificationDispatchUncertain("whatsapp-outcome-uncertain")
    try:
        decoded = response.json()
        messages = decoded["messages"]
        message_id = messages[0]["id"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise NotificationDispatchUncertain("whatsapp-invalid-response") from None
    if (
        not isinstance(decoded, dict)
        or decoded.get("error") is not None
        or not isinstance(message_id, str)
        or not message_id.strip()
        or len(message_id) > 255
    ):
        raise NotificationDispatchUncertain("whatsapp-acknowledgement-invalid")
    return message_id


@dataclass(frozen=True)
class NotificationMessageData:
    """Immutable notification text carried across the provider boundary."""

    id: str
    title: str = field(repr=False)
    message: str = field(repr=False)
    event_key: str
    severity: str


@dataclass(frozen=True)
class NotificationDispatchData:
    """A committed attempt's immutable send input, without ORM state."""

    channel: str
    address: str = field(repr=False)
    notification: NotificationMessageData = field(repr=False)
    telegram_scope: str = "owner"
    endpoint_id: str | None = field(default=None, repr=False)
    max_attempts: int = 5


@dataclass(frozen=True)
class NotificationDispatchResult:
    """Non-owning business result returned only after confirmed settlement."""

    delivery_id: str
    status: str
    attempt_count: int
    provider_message_id: str | None = field(repr=False)
    dead_lettered_at: datetime | None


class NotificationDispatchUncertain(CommunicationError):
    """Provider execution or local settlement cannot be proved complete."""


class _NoSendDeliveryError(CommunicationError):
    """A local check proved that no notification provider send was invoked."""

    def __init__(self, code: str, *, delivery_status: str = "dead_letter") -> None:
        super().__init__(code)
        self.code = code
        self.delivery_status = delivery_status


class _DefiniteDeliveryRejection(CommunicationError):
    """A documented provider response proves rejection after client cleanup."""

    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


NotificationSessionFactory = Callable[[], AsyncSession]
NotificationDispatcher = Callable[[NotificationDispatchData], Awaitable[str]]
_NotificationTaskResult = TypeVar("_NotificationTaskResult")


async def _dispatch(
    channel: str,
    address: str,
    notification: NotificationMessageData,
    *,
    telegram_scope: str = "owner",
    whatsapp_transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Keep each client's full operation and cleanup within the retained task."""
    if channel == "email":
        return await asyncio.to_thread(_send_email, address, notification)
    if channel == "push":
        return await asyncio.to_thread(_send_push, address, notification)
    if channel == "telegram":
        return await _send_telegram(address, notification, scope=telegram_scope)
    if channel == "whatsapp":
        return await _send_whatsapp(
            address, notification, transport=whatsapp_transport
        )
    raise _NoSendDeliveryError("unsupported-channel")


async def _prepare_owned_notification_dispatch(
    ownership: notification_maintenance.NotificationActivityOwnership,
    *,
    session_factory: NotificationSessionFactory,
) -> NotificationDispatchData:
    """Copy the fenced delivery input, then release the database transaction."""
    async with session_factory() as session:
        async with session.begin():
            await notification_maintenance.require_owned_notification_activity(
                session, ownership
            )
            delivery = await session.get(NotificationDelivery, ownership.delivery_id)
            if delivery is None:
                raise notification_maintenance.NotificationActivityOwnershipLost(
                    "Notification delivery disappeared"
                )
            notification = await session.get(Notification, delivery.notification_id)
            if notification is None:
                raise _NoSendDeliveryError("notification-missing")
            endpoint = (
                await session.get(CommunicationEndpoint, delivery.endpoint_id)
                if delivery.endpoint_id is not None
                else None
            )
            if (
                endpoint is None
                or endpoint.status != "active"
                or endpoint.verified_at is None
                or endpoint.channel != delivery.channel
                or endpoint.organization_id != delivery.organization_id
                or endpoint.user_id != notification.recipient_id
            ):
                raise _NoSendDeliveryError("recipient-endpoint-unavailable")
            telegram_scope = "owner"
            if delivery.channel == "telegram":
                telegram_scope = str(
                    dict(endpoint.endpoint_metadata or {}).get("bot_scope") or "owner"
                ).strip().lower()
                if telegram_scope not in {"owner", "user"}:
                    raise _NoSendDeliveryError("telegram-scope-invalid")
            state = (
                telegram_scope_state(telegram_scope)
                if delivery.channel == "telegram"
                else channel_state(delivery.channel)
            )
            if not state["ready"]:
                raise _NoSendDeliveryError(
                    "provider-unconfigured", delivery_status="unconfigured"
                )
            try:
                address = decrypt_address(endpoint.address_ciphertext)
            except PermanentDeliveryError as exc:
                raise _NoSendDeliveryError("endpoint-decryption-failed") from exc
            return NotificationDispatchData(
                channel=delivery.channel,
                address=address,
                notification=NotificationMessageData(
                    id=notification.id,
                    title=notification.title,
                    message=notification.message,
                    event_key=notification.event_key,
                    severity=notification.severity,
                ),
                telegram_scope=telegram_scope,
                endpoint_id=endpoint.id,
                max_attempts=delivery.max_attempts,
            )


async def _settle_owned_notification_dispatch(
    ownership: notification_maintenance.NotificationActivityOwnership,
    *,
    session_factory: NotificationSessionFactory,
    outcome: str,
    delivery_status: str,
    provider_message_id: str | None = None,
    error_code: str | None = None,
    next_attempt_at: datetime | None = None,
) -> NotificationDispatchResult:
    """Publish the business result under the same exact ownership fence."""
    async with session_factory() as session:
        async with session.begin():
            await notification_maintenance.settle_notification_dispatch(
                session,
                ownership,
                outcome=outcome,
                delivery_status=delivery_status,
                provider_message_id=provider_message_id,
                error_code=error_code,
                error_message=(
                    None
                    if outcome == "accepted"
                    else "Notification was not accepted by the provider"
                ),
                next_attempt_at=next_attempt_at,
            )
            delivery = await session.get(
                NotificationDelivery, ownership.delivery_id, populate_existing=True
            )
            if delivery is None:
                raise notification_maintenance.NotificationActivityOwnershipLost(
                    "Notification delivery disappeared during settlement"
                )
            if outcome == "accepted" and delivery.endpoint_id is not None:
                endpoint = await session.get(CommunicationEndpoint, delivery.endpoint_id)
                if endpoint is not None:
                    endpoint.last_used_at = now()
            session.add(
                AuditEvent(
                    organization_id=delivery.organization_id,
                    user_id=None,
                    action="notification.delivery.processed",
                    resource_type="notification_delivery",
                    resource_id=delivery.id,
                    details={
                        "channel": delivery.channel,
                        "status": delivery.status,
                        "attempt_count": delivery.attempt_count,
                        "error_code": delivery.error_code,
                        "dispatch_outcome": outcome,
                    },
                )
            )
            result = NotificationDispatchResult(
                delivery_id=delivery.id,
                status=delivery.status,
                attempt_count=delivery.attempt_count,
                provider_message_id=delivery.provider_message_id,
                dead_lettered_at=delivery.dead_lettered_at,
            )
        return result


async def _execute_owned_notification_dispatch(
    ownership: notification_maintenance.NotificationActivityOwnership,
    *,
    session_factory: NotificationSessionFactory,
    dispatcher: NotificationDispatcher | None,
    whatsapp_transport: httpx.AsyncBaseTransport | None,
) -> NotificationDispatchResult:
    data: NotificationDispatchData | None = None
    provider_message_id: str | None = None
    error_code: str | None = None
    next_attempt_at: datetime | None = None
    try:
        data = await _prepare_owned_notification_dispatch(
            ownership, session_factory=session_factory
        )
        if dispatcher is None:
            provider_message_id = await _dispatch(
                data.channel,
                data.address,
                data.notification,
                telegram_scope=data.telegram_scope,
                whatsapp_transport=whatsapp_transport,
            )
        else:
            provider_message_id = await dispatcher(data)
        if (
            not isinstance(provider_message_id, str)
            or not provider_message_id.strip()
            or len(provider_message_id) > 255
        ):
            raise NotificationDispatchUncertain("provider-acknowledgement-invalid")
        outcome = "accepted"
        delivery_status = "delivered"
    except _NoSendDeliveryError as exc:
        outcome = "no_send"
        delivery_status = exc.delivery_status
        error_code = exc.code
    except ProviderNotConfigured:
        # This typed error is raised only before a provider's send operation.
        outcome = "no_send"
        delivery_status = "unconfigured"
        error_code = "provider-unconfigured"
    except _DefiniteDeliveryRejection as exc:
        outcome = "rejected"
        error_code = exc.code
        maximum = data.max_attempts if data is not None else 1
        if exc.retryable and ownership.attempt_number < maximum:
            delay = (
                exc.retry_after_seconds
                if exc.retry_after_seconds is not None
                else min(
                    settings.COMMUNICATION_RETRY_BASE_SECONDS
                    * (2 ** max(0, ownership.attempt_number - 1)),
                    86400,
                )
            )
            delivery_status = "retrying"
            next_attempt_at = now() + timedelta(seconds=delay)
        else:
            delivery_status = "dead_letter"
    except asyncio.CancelledError:
        raise
    except Exception:
        raise NotificationDispatchUncertain("provider-outcome-uncertain") from None
    return await _settle_owned_notification_dispatch(
        ownership,
        session_factory=session_factory,
        outcome=outcome,
        delivery_status=delivery_status,
        provider_message_id=provider_message_id,
        error_code=error_code,
        next_attempt_at=next_attempt_at,
    )


async def _await_actual_notification_task(
    task: asyncio.Task[_NotificationTaskResult],
    *,
    health_callback: Callable[[], None] | None,
    health_interval_seconds: float,
) -> _NotificationTaskResult:
    """Join the retained operation even if its waiter is cancelled repeatedly."""
    while True:
        try:
            return await asyncio.wait_for(
                asyncio.shield(task), timeout=max(0.01, health_interval_seconds)
            )
        except asyncio.CancelledError:
            if task.done():
                return task.result()
            continue
        except TimeoutError:
            if task.done():
                return task.result()
            if health_callback is not None:
                try:
                    health_callback()
                except Exception:
                    logger.debug("Notification control-plane health update failed")
            continue


async def _mark_notification_unresolved_safely(
    ownership: notification_maintenance.NotificationActivityOwnership,
    *,
    reason: str,
    session_factory: NotificationSessionFactory,
    health_callback: Callable[[], None] | None,
    health_interval_seconds: float,
) -> None:
    marker = asyncio.create_task(
        notification_maintenance.mark_notification_activity_unresolved(
            ownership, reason=reason, session_factory=session_factory
        )
    )
    try:
        await _await_actual_notification_task(
            marker,
            health_callback=health_callback,
            health_interval_seconds=health_interval_seconds,
        )
    except BaseException:
        # The already-committed activity/started attempt remain independent blockers.
        logger.error("Notification uncertainty could not be recorded")


async def _heartbeat_owned_notification_dispatch(
    ownership: notification_maintenance.NotificationActivityOwnership,
    stop: asyncio.Event,
    *,
    session_factory: NotificationSessionFactory,
    interval_seconds: float,
    health_callback: Callable[[], None] | None,
) -> None:
    while not stop.is_set():
        await notification_maintenance.heartbeat_notification_activity(
            ownership, session_factory=session_factory
        )
        if health_callback is not None:
            health_callback()
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


async def process_delivery(
    ownership: notification_maintenance.NotificationActivityOwnership,
    *,
    session_factory: NotificationSessionFactory = SessionLocal,
    dispatcher: NotificationDispatcher | None = None,
    whatsapp_transport: httpx.AsyncBaseTransport | None = None,
    heartbeat_interval_seconds: float = 20.0,
    health_callback: Callable[[], None] | None = None,
) -> NotificationDispatchResult:
    """Consume one durable capability and retain it until actual I/O settles."""
    if heartbeat_interval_seconds <= 0:
        raise ValueError("Notification heartbeat interval must be positive")
    began = False
    try:
        async with session_factory() as session:
            async with session.begin():
                await notification_maintenance.begin_notification_dispatch(
                    session, ownership
                )
                began = True
    except BaseException:
        if began:
            await _mark_notification_unresolved_safely(
                ownership,
                reason="notification-begin-commit-unconfirmed",
                session_factory=session_factory,
                health_callback=health_callback,
                health_interval_seconds=heartbeat_interval_seconds,
            )
        raise

    heartbeat_stop = asyncio.Event()
    operation_task = asyncio.create_task(
        _execute_owned_notification_dispatch(
            ownership,
            session_factory=session_factory,
            dispatcher=dispatcher,
            whatsapp_transport=whatsapp_transport,
        )
    )
    heartbeat_task = asyncio.create_task(
        _heartbeat_owned_notification_dispatch(
            ownership,
            heartbeat_stop,
            session_factory=session_factory,
            interval_seconds=heartbeat_interval_seconds,
            health_callback=health_callback,
        )
    )
    reason = "notification-execution-unsettled"
    try:
        done, _pending = await asyncio.wait(
            {operation_task, heartbeat_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if heartbeat_task in done:
            reason = "notification-heartbeat-unconfirmed"
            await heartbeat_task
            raise NotificationDispatchUncertain("notification-heartbeat-stopped")
        result = await asyncio.shield(operation_task)
        heartbeat_stop.set()
        # A current caller cancellation must reach the uncertainty path below.
        await asyncio.shield(heartbeat_task)
        reason = "notification-finish-unconfirmed"
        await notification_maintenance.finish_notification_activity(
            ownership, session_factory=session_factory
        )
        return result
    except BaseException as exc:
        heartbeat_stop.set()
        if isinstance(exc, asyncio.CancelledError):
            reason = "notification-dispatch-cancelled"
        await _mark_notification_unresolved_safely(
            ownership,
            reason=reason,
            session_factory=session_factory,
            health_callback=health_callback,
            health_interval_seconds=heartbeat_interval_seconds,
        )
        for task in (operation_task, heartbeat_task):
            try:
                await _await_actual_notification_task(
                    task,
                    health_callback=health_callback,
                    health_interval_seconds=heartbeat_interval_seconds,
                )
            except BaseException:
                logger.debug("Notification task settled with a secondary failure")
        raise


async def claim_due_deliveries(
    session: AsyncSession, *, worker_incarnation: str, limit: int = 1
) -> list[notification_maintenance.NotificationActivityOwnership]:
    """Admit one attempt atomically; lease age never authorizes takeover."""
    if limit != 1:
        raise ValueError("Notification dispatch claims exactly one delivery per cycle")
    await notification_maintenance.require_notification_admission(session)
    current = now()
    table = cast(Table, NotificationDelivery.__table__)
    delivery = await session.scalar(
        select(NotificationDelivery)
        .where(
            *notification_maintenance.eligible_notification_delivery_conditions(table),
            or_(
                NotificationDelivery.next_attempt_at.is_(None),
                NotificationDelivery.next_attempt_at <= current,
            ),
        )
        .order_by(
            NotificationDelivery.priority.desc(), NotificationDelivery.created_at,
            NotificationDelivery.id,
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if delivery is None:
        await session.commit()
        return []
    ownership = await notification_maintenance.register_notification_activity(
        session, delivery_id=delivery.id, worker_incarnation=worker_incarnation
    )
    await session.commit()
    return [ownership]


async def retry_delivery(
    session: AsyncSession,
    delivery: NotificationDelivery,
    *,
    actor_id: str | None,
) -> NotificationDelivery:
    if delivery.status not in {"dead_letter", "unconfigured", "skipped", "failed"}:
        raise ValueError("Only failed, skipped, unconfigured, or dead-letter deliveries can retry")
    state = channel_state(delivery.channel)
    if not state["ready"]:
        raise ProviderNotConfigured("provider-unconfigured")
    if delivery.channel != "in_app" and delivery.endpoint_id is None:
        raise PermanentDeliveryError("recipient-endpoint-missing")
    delivery.status = "queued"
    delivery.error_code = None
    delivery.error_message = None
    delivery.dead_lettered_at = None
    delivery.next_attempt_at = now()
    delivery.lease_token = None
    delivery.lease_expires_at = None
    session.add(
        AuditEvent(
            organization_id=delivery.organization_id,
            user_id=actor_id,
            action="notification.delivery.requeued",
            resource_type="notification_delivery",
            resource_id=delivery.id,
            details={"channel": delivery.channel, "attempt_count": delivery.attempt_count},
        )
    )
    return delivery


async def acknowledge_delivery(
    session: AsyncSession,
    delivery: NotificationDelivery,
    *,
    actor_id: str,
) -> NotificationDelivery:
    if delivery.status not in {"delivered", "acknowledged"}:
        raise ValueError("Only a delivered notification can be acknowledged")
    delivery.status = "acknowledged"
    delivery.acknowledged_at = delivery.acknowledged_at or now()
    session.add(
        AuditEvent(
            organization_id=delivery.organization_id,
            user_id=actor_id,
            action="notification.delivery.acknowledged",
            resource_type="notification_delivery",
            resource_id=delivery.id,
            details={"channel": delivery.channel},
        )
    )
    return delivery


async def delivery_statistics(session: AsyncSession) -> dict[str, Any]:
    status_rows = (
        await session.execute(
            select(NotificationDelivery.status, func.count(NotificationDelivery.id)).group_by(
                NotificationDelivery.status
            )
        )
    ).all()
    historical_expr = (
        NotificationDelivery.delivery_metadata["historical_actionable"]
        .as_boolean()
        .is_(False)
    )
    historical_rows = (
        await session.execute(
            select(NotificationDelivery.status, func.count(NotificationDelivery.id))
            .where(historical_expr)
            .group_by(NotificationDelivery.status)
        )
    ).all()
    actionable_rows = (
        await session.execute(
            select(NotificationDelivery.status, func.count(NotificationDelivery.id))
            .where(or_(historical_expr.is_(False), historical_expr.is_(None)))
            .group_by(NotificationDelivery.status)
        )
    ).all()
    channel_rows = (
        await session.execute(
            select(NotificationDelivery.channel, func.count(NotificationDelivery.id)).group_by(
                NotificationDelivery.channel
            )
        )
    ).all()
    return {
        "by_status": {str(status): int(count) for status, count in status_rows},
        "actionable_by_status": {
            str(status): int(count) for status, count in actionable_rows
        },
        "historical_reconciled_by_status": {
            str(status): int(count) for status, count in historical_rows
        },
        "by_channel": {str(channel): int(count) for channel, count in channel_rows},
        "readiness": channel_readiness(),
    }


def support_snapshot(request: SupportRequest, messages: int | None = None) -> dict[str, Any]:
    return {
        "id": request.id,
        "organization_id": request.organization_id,
        "requester_id": request.requester_id,
        "assigned_to_id": request.assigned_to_id,
        "subject": request.subject,
        "category": request.category,
        "priority": request.priority,
        "status": request.status,
        "message_count": messages,
        "last_message_at": iso(request.last_message_at),
        "escalated_at": iso(request.escalated_at),
        "resolved_at": iso(request.resolved_at),
        "closed_at": iso(request.closed_at),
        "created_at": iso(request.created_at),
        "updated_at": iso(request.updated_at),
    }


def support_message_snapshot(message: SupportMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "support_request_id": message.support_request_id,
        "sender_id": message.sender_id,
        "visibility": message.visibility,
        "message": message.message,
        "attachments": message.attachments,
        "created_at": iso(message.created_at),
    }


async def create_support_request(
    session: AsyncSession,
    actor: UserRecord,
    *,
    subject: str,
    message: str,
    category: str = "general",
    priority: str = "normal",
    request_metadata: dict[str, Any] | None = None,
) -> tuple[SupportRequest, list[Notification]]:
    ticket = SupportRequest(
        id=uuid_str(),
        organization_id=actor.organization_id,
        requester_id=actor.id,
        subject=subject.strip(),
        category=category.strip().lower() or "general",
        priority=priority,
        status="open",
        last_message_at=now(),
        request_metadata=request_metadata or {},
    )
    session.add(ticket)
    await session.flush()
    session.add(
        SupportMessage(
            id=uuid_str(),
            support_request_id=ticket.id,
            sender_id=actor.id,
            visibility="requester",
            message=message.strip(),
            attachments=[],
            created_at=now(),
        )
    )
    notifications = await notify_audience(
        session,
        organization_id=actor.organization_id,
        audience="owner",
        event_key="support.request.created",
        category="support",
        title=f"Support: {ticket.subject}",
        message=f"{actor.name} opened support request {ticket.id}.",
        severity="warning" if priority in {"high", "urgent"} else "info",
        source_type="support_request",
        source_id=ticket.id,
        correlation_id=ticket.id,
        dedupe_prefix=f"support-created:{ticket.id}",
        payload={"request_id": ticket.id, "priority": priority, "category": category},
        actor_id=actor.id,
    )
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="support.request.created",
            resource_type="support_request",
            resource_id=ticket.id,
            details={"category": ticket.category, "priority": ticket.priority},
        )
    )
    await session.flush()
    return ticket, notifications


async def add_support_message(
    session: AsyncSession,
    actor: UserRecord,
    ticket: SupportRequest,
    *,
    message: str,
    visibility: str = "requester",
    manager: bool = False,
) -> tuple[SupportMessage, list[Notification]]:
    if ticket.status in {"closed", "cancelled", "suspended"}:
        raise ValueError(f"{ticket.status.title()} support requests cannot receive messages")
    entry = SupportMessage(
        id=uuid_str(),
        support_request_id=ticket.id,
        sender_id=actor.id,
        visibility=visibility if manager else "requester",
        message=message.strip(),
        attachments=[],
        created_at=now(),
    )
    session.add(entry)
    ticket.last_message_at = now()
    if manager and ticket.status == "open":
        ticket.status = "in_progress"
        ticket.assigned_to_id = ticket.assigned_to_id or actor.id
    if not manager and ticket.status == "resolved":
        ticket.status = "open"
        ticket.resolved_at = None
    recipient_ids = [ticket.requester_id] if manager else []
    audience = "user" if manager else "owner"
    notifications = await notify_audience(
        session,
        organization_id=ticket.organization_id,
        audience=audience,
        explicit_user_ids=recipient_ids,
        event_key="support.request.updated",
        category="support",
        title=f"Support update: {ticket.subject}",
        message=f"Support request {ticket.id} received a new message.",
        severity="info",
        source_type="support_request",
        source_id=ticket.id,
        correlation_id=ticket.id,
        dedupe_prefix=f"support-message:{entry.id}",
        actor_id=actor.id,
    )
    session.add(
        AuditEvent(
            organization_id=ticket.organization_id,
            user_id=actor.id,
            action="support.message.created",
            resource_type="support_request",
            resource_id=ticket.id,
            details={"message_id": entry.id, "visibility": entry.visibility},
        )
    )
    await session.flush()
    return entry, notifications


async def update_support_status(
    session: AsyncSession,
    actor: UserRecord,
    ticket: SupportRequest,
    *,
    status: str,
    assigned_to_id: str | None = None,
) -> SupportRequest:
    if status not in {"open", "in_progress", "waiting_user", "resolved", "closed", "suspended", "cancelled"}:
        raise ValueError("Unsupported support status")
    current = now()
    ticket.status = status
    if assigned_to_id is not None:
        ticket.assigned_to_id = assigned_to_id
    if status == "resolved":
        ticket.resolved_at = current
    elif status in {"closed", "cancelled"}:
        ticket.closed_at = current
    elif status == "open":
        ticket.resolved_at = None
        ticket.closed_at = None
    metadata = dict(ticket.request_metadata or {})
    if status == "suspended":
        metadata["suspended_at"] = iso(current)
    elif status == "cancelled":
        metadata["cancelled_at"] = iso(current)
    elif status in {"open", "in_progress", "waiting_user", "resolved", "closed"}:
        metadata.pop("suspended_at", None)
        if status != "closed":
            metadata.pop("cancelled_at", None)
    ticket.request_metadata = metadata
    session.add(
        AuditEvent(
            organization_id=ticket.organization_id,
            user_id=actor.id,
            action="support.request.status_changed",
            resource_type="support_request",
            resource_id=ticket.id,
            details={"status": status, "assigned_to_id": ticket.assigned_to_id},
        )
    )
    return ticket


def incident_snapshot(incident: Alert) -> dict[str, Any]:
    return {
        "id": incident.id,
        "organization_id": incident.organization_id,
        "title": incident.title,
        "description": incident.description,
        "severity": incident.severity,
        "status": incident.status,
        "source": incident.source,
        "assigned_to_id": incident.assigned_to_id,
        "acknowledged_by_id": incident.acknowledged_by_id,
        "resolved_by_id": incident.resolved_by_id,
        "escalation_level": incident.escalation_level,
        "last_escalated_at": iso(incident.last_escalated_at),
        "acknowledged_at": iso(incident.acknowledged_at),
        "resolved_at": iso(incident.resolved_at),
        "created_at": iso(incident.created_at),
        "updated_at": iso(incident.updated_at),
    }


async def create_incident(
    session: AsyncSession,
    *,
    organization_id: str | None,
    title: str,
    description: str,
    severity: str,
    source: str,
    actor_id: str | None,
    details: dict[str, Any] | None = None,
) -> tuple[Alert, list[Notification]]:
    if severity not in {"info", "warning", "critical"}:
        raise ValueError("Unsupported incident severity")
    incident = Alert(
        id=uuid_str(),
        organization_id=organization_id,
        title=title.strip(),
        description=description.strip(),
        severity=severity,
        status="active",
        source=source.strip(),
        details=details or {},
    )
    session.add(incident)
    await session.flush()
    notifications: list[Notification] = []
    if organization_id:
        notifications = await notify_audience(
            session,
            organization_id=organization_id,
            audience="owner",
            event_key="incident.critical" if severity == "critical" else "incident.created",
            category="incident",
            title=incident.title,
            message=incident.description or "A platform incident requires review.",
            severity=severity,
            source_type="incident",
            source_id=incident.id,
            correlation_id=incident.id,
            dedupe_prefix=f"incident-created:{incident.id}",
            actor_id=actor_id,
        )
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=actor_id,
            action="incident.created",
            resource_type="incident",
            resource_id=incident.id,
            details={"severity": severity, "source": source},
        )
    )
    return incident, notifications


async def acknowledge_incident(
    session: AsyncSession, actor: UserRecord, incident: Alert
) -> Alert:
    if incident.status == "resolved":
        raise ValueError("Resolved incidents cannot be acknowledged")
    incident.status = "investigating"
    incident.acknowledged_by_id = actor.id
    incident.acknowledged_at = now()
    incident.assigned_to_id = incident.assigned_to_id or actor.id
    session.add(
        AuditEvent(
            organization_id=incident.organization_id,
            user_id=actor.id,
            action="incident.acknowledged",
            resource_type="incident",
            resource_id=incident.id,
            details={"status": incident.status},
        )
    )
    return incident


async def escalate_incident(
    session: AsyncSession, actor: UserRecord, incident: Alert
) -> tuple[Alert, list[Notification]]:
    if incident.status == "resolved":
        raise ValueError("Resolved incidents cannot be escalated")
    incident.escalation_level += 1
    incident.last_escalated_at = now()
    incident.status = "investigating"
    notifications: list[Notification] = []
    if incident.organization_id:
        notifications = await notify_audience(
            session,
            organization_id=incident.organization_id,
            audience="owner",
            event_key="incident.critical",
            category="incident",
            title=f"Escalation L{incident.escalation_level}: {incident.title}",
            message=incident.description or "Escalated incident requires owner action.",
            severity="critical",
            source_type="incident",
            source_id=incident.id,
            correlation_id=incident.id,
            dedupe_prefix=f"incident-escalation:{incident.id}:{incident.escalation_level}",
            actor_id=actor.id,
        )
    session.add(
        AuditEvent(
            organization_id=incident.organization_id,
            user_id=actor.id,
            action="incident.escalated",
            resource_type="incident",
            resource_id=incident.id,
            details={"level": incident.escalation_level},
        )
    )
    return incident, notifications


async def resolve_incident(
    session: AsyncSession, actor: UserRecord, incident: Alert
) -> Alert:
    incident.status = "resolved"
    incident.resolved_by_id = actor.id
    incident.resolved_at = now()
    session.add(
        AuditEvent(
            organization_id=incident.organization_id,
            user_id=actor.id,
            action="incident.resolved",
            resource_type="incident",
            resource_id=incident.id,
            details={"status": "resolved"},
        )
    )
    return incident


async def publish_many(notifications: Iterable[Notification]) -> None:
    for notification in notifications:
        await publish_realtime(notification)
