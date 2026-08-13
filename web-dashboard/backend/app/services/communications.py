"""Durable Phase 29E communications, notification delivery, support, and incidents.

The in-app record is always written first. External channels are represented by
separate durable delivery rows, so missing credentials, provider outages, and
retry exhaustion can never erase the user-visible notification.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Iterable, Sequence

import httpx
from app.core.ai_runtime import ai_realtime_hub
from app.core.auth import UserRecord
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import (
    Alert,
    AuditEvent,
    CommunicationEndpoint,
    EscalationPolicy,
    Notification,
    NotificationDelivery,
    NotificationDeliveryAttempt,
    NotificationPreference,
    NotificationRule,
    Role,
    SupportMessage,
    SupportRequest,
    User,
    uuid_str,
)
from app.services.telegram_worker import TelegramBotAPI, load_bot_token
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, or_, select
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


def channel_readiness() -> list[dict[str, Any]]:
    """Return truthful deployment readiness without returning any credential."""

    email_ready = bool(settings.SMTP_HOST) and (
        not settings.SMTP_USER or bool(settings.SMTP_PASSWORD)
    )
    firebase_path = Path(settings.FIREBASE_ADMIN_CREDENTIALS_JSON or "")
    push_ready = bool(settings.FIREBASE_PROJECT_ID) and bool(
        settings.FIREBASE_ADMIN_CREDENTIALS_JSON
        and firebase_path.is_file()
        and not firebase_path.is_symlink()
    )
    telegram_ready = False
    telegram_reason = "token file is not configured"
    try:
        load_bot_token(settings.AIOS_TELEGRAM_BOT_TOKEN_FILE)
        telegram_ready = True
        telegram_reason = "ready"
    except (OSError, ValueError):
        pass
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
            True,
            ["delivery_receipt", "retry", "chat_endpoint"],
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
    if dedupe_key:
        existing = await session.scalar(
            select(Notification).where(
                Notification.organization_id == recipient.organization_id,
                Notification.dedupe_key == dedupe_key,
            )
        )
        if existing is not None:
            return existing
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
    if "email" in selected and "email" not in endpoint_by_channel:
        endpoint_by_channel["email"] = await ensure_email_endpoint(session, recipient)
    if "telegram" in selected and "telegram" not in endpoint_by_channel:
        telegram_endpoint = await ensure_owner_telegram_endpoint(session, recipient)
        if telegram_endpoint is not None:
            endpoint_by_channel["telegram"] = telegram_endpoint

    for channel in selected:
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
        session.add(
            NotificationDelivery(
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
        await ai_realtime_hub.publish(
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


def _send_email(address: str, notification: Notification) -> str:
    state = channel_state("email")
    if not state["ready"]:
        raise ProviderNotConfigured("email-provider-unconfigured")
    message = EmailMessage()
    message["Subject"] = notification.title
    message["From"] = settings.SMTP_USER or "noreply@aionex.local"
    message["To"] = address
    message.set_content(notification.message)
    smtp_host = settings.SMTP_HOST
    if not smtp_host:
        raise ProviderNotConfigured("email-provider-unconfigured")
    with smtplib.SMTP(smtp_host, settings.SMTP_PORT, timeout=15) as smtp:
        smtp.ehlo()
        if settings.SMTP_TLS:
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        if settings.SMTP_USER:
            if not settings.SMTP_PASSWORD:
                raise ProviderNotConfigured("smtp-password-unconfigured")
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        refused = smtp.send_message(message)
    if refused:
        raise PermanentDeliveryError("smtp-recipient-refused")
    return f"smtp:{notification.id}"


_firebase_app: Any | None = None


def _send_push(address: str, notification: Notification) -> str:
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
        return str(
            messaging.send(
                messaging.Message(
                    token=address,
                    notification=messaging.Notification(
                        title=notification.title,
                        body=notification.message[:1024],
                    ),
                    data={
                        "notification_id": notification.id,
                        "event_key": notification.event_key,
                        "severity": notification.severity,
                    },
                ),
                app=_firebase_app,
            )
        )
    except ProviderNotConfigured:
        raise
    except Exception as exc:
        name = type(exc).__name__
        if name in {"UnregisteredError", "SenderIdMismatchError", "InvalidArgumentError"}:
            raise PermanentDeliveryError(name) from exc
        raise CommunicationError(name) from exc


async def _send_telegram(address: str, notification: Notification) -> str:
    state = channel_state("telegram")
    if not state["ready"]:
        raise ProviderNotConfigured("telegram-provider-unconfigured")
    try:
        chat_id = int(address)
    except ValueError as exc:
        raise PermanentDeliveryError("telegram-chat-id-invalid") from exc
    token = load_bot_token(settings.AIOS_TELEGRAM_BOT_TOKEN_FILE)
    api = TelegramBotAPI(token)
    try:
        await api.send_message(chat_id, f"{notification.title}\n\n{notification.message}")
    finally:
        await api.close()
    return f"telegram:{notification.id}:{chat_id}"


async def _send_whatsapp(
    address: str,
    notification: Notification,
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
    async with httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(20, connect=10),
        follow_redirects=False,
    ) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise CommunicationError(type(exc).__name__) from exc
    if response.status_code in {400, 401, 403, 404, 422}:
        raise PermanentDeliveryError(f"whatsapp-http-{response.status_code}")
    if response.status_code >= 500 or response.status_code == 429:
        raise CommunicationError(f"whatsapp-http-{response.status_code}")
    if response.status_code not in {200, 201, 202}:
        raise PermanentDeliveryError(f"whatsapp-http-{response.status_code}")
    try:
        decoded = response.json()
        message_id = str(decoded["messages"][0]["id"])
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise CommunicationError("whatsapp-invalid-response") from exc
    return message_id


async def _dispatch(
    channel: str,
    address: str,
    notification: Notification,
    *,
    whatsapp_transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    if channel == "email":
        return await asyncio.to_thread(_send_email, address, notification)
    if channel == "push":
        return await asyncio.to_thread(_send_push, address, notification)
    if channel == "telegram":
        return await _send_telegram(address, notification)
    if channel == "whatsapp":
        return await _send_whatsapp(
            address, notification, transport=whatsapp_transport
        )
    raise PermanentDeliveryError("unsupported-channel")


async def process_delivery(
    session: AsyncSession,
    delivery_id: str,
    *,
    whatsapp_transport: httpx.AsyncBaseTransport | None = None,
) -> NotificationDelivery:
    delivery = await session.scalar(
        select(NotificationDelivery)
        .where(NotificationDelivery.id == delivery_id)
        .with_for_update()
    )
    if delivery is None:
        raise LookupError("Notification delivery not found")
    if delivery.status in {"delivered", "acknowledged"}:
        return delivery
    notification = await session.get(Notification, delivery.notification_id)
    if notification is None:
        delivery.status = "dead_letter"
        delivery.error_code = "notification_missing"
        delivery.dead_lettered_at = now()
        await session.commit()
        return delivery
    if delivery.channel == "in_app":
        delivery.status = "delivered"
        delivery.delivered_at = delivery.delivered_at or now()
        await session.commit()
        return delivery
    endpoint = await session.get(CommunicationEndpoint, delivery.endpoint_id)
    state = channel_state(delivery.channel)
    if not state["ready"]:
        delivery.status = "unconfigured"
        delivery.error_code = "provider_unconfigured"
        delivery.error_message = state["reason"]
        delivery.lease_token = None
        delivery.lease_expires_at = None
        await session.commit()
        return delivery
    if endpoint is None or endpoint.status != "active" or endpoint.verified_at is None:
        delivery.status = "dead_letter"
        delivery.error_code = "recipient_endpoint_unavailable"
        delivery.dead_lettered_at = now()
        delivery.lease_token = None
        delivery.lease_expires_at = None
        await session.commit()
        return delivery

    delivery.attempt_count += 1
    attempt = NotificationDeliveryAttempt(
        id=uuid_str(),
        delivery_id=delivery.id,
        attempt_number=delivery.attempt_count,
        status="started",
        started_at=now(),
    )
    session.add(attempt)
    await session.flush()
    try:
        provider_message_id = await _dispatch(
            delivery.channel,
            decrypt_address(endpoint.address_ciphertext),
            notification,
            whatsapp_transport=whatsapp_transport,
        )
        completed = now()
        attempt.status = "delivered"
        attempt.provider_message_id = provider_message_id
        attempt.completed_at = completed
        delivery.status = "delivered"
        delivery.provider_message_id = provider_message_id
        delivery.error_code = None
        delivery.error_message = None
        delivery.delivered_at = completed
        delivery.next_attempt_at = None
        endpoint.last_used_at = completed
    except ProviderNotConfigured as exc:
        attempt.status = "unconfigured"
        attempt.error_code = str(exc)
        attempt.completed_at = now()
        delivery.status = "unconfigured"
        delivery.error_code = str(exc)
        delivery.error_message = "Provider is not configured"
        delivery.next_attempt_at = None
    except PermanentDeliveryError as exc:
        attempt.status = "failed"
        attempt.error_code = str(exc)
        attempt.completed_at = now()
        delivery.status = "dead_letter"
        delivery.error_code = str(exc)
        delivery.error_message = "Permanent provider rejection"
        delivery.dead_lettered_at = now()
        delivery.next_attempt_at = None
    except Exception as exc:
        code = type(exc).__name__
        attempt.status = "failed"
        attempt.error_code = code
        attempt.completed_at = now()
        delivery.error_code = code
        delivery.error_message = "Transient provider failure"
        if delivery.attempt_count >= delivery.max_attempts:
            delivery.status = "dead_letter"
            delivery.dead_lettered_at = now()
            delivery.next_attempt_at = None
        else:
            delay = min(
                settings.COMMUNICATION_RETRY_BASE_SECONDS
                * (2 ** max(0, delivery.attempt_count - 1)),
                86400,
            )
            delivery.status = "retrying"
            delivery.next_attempt_at = now() + timedelta(seconds=delay)
    delivery.lease_token = None
    delivery.lease_expires_at = None
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
            },
        )
    )
    await session.commit()
    return delivery


async def claim_due_deliveries(
    session: AsyncSession, *, limit: int = 25
) -> list[str]:
    current = now()
    rows = list(
        (
            await session.scalars(
                select(NotificationDelivery)
                .where(
                    NotificationDelivery.status.in_({"queued", "retrying", "processing"}),
                    or_(
                        NotificationDelivery.next_attempt_at.is_(None),
                        NotificationDelivery.next_attempt_at <= current,
                    ),
                    or_(
                        NotificationDelivery.lease_expires_at.is_(None),
                        NotificationDelivery.lease_expires_at <= current,
                    ),
                )
                .order_by(
                    NotificationDelivery.priority.desc(),
                    NotificationDelivery.created_at,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    claimed: list[str] = []
    for delivery in rows:
        delivery.status = "processing"
        delivery.lease_token = uuid_str()
        delivery.lease_expires_at = current + timedelta(
            seconds=settings.COMMUNICATION_DELIVERY_LEASE_SECONDS
        )
        claimed.append(delivery.id)
    await session.commit()
    return claimed


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
    channel_rows = (
        await session.execute(
            select(NotificationDelivery.channel, func.count(NotificationDelivery.id)).group_by(
                NotificationDelivery.channel
            )
        )
    ).all()
    return {
        "by_status": {str(status): int(count) for status, count in status_rows},
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
