"""Owner-governed free-user registration, quotas, consent, and telemetry.

The implementation deliberately reuses ``OwnerControlRecord`` so existing
installations upgrade without a schema migration.  The global policy is owned by
the Super Owner, while each free account has a durable usage record and a
separate registration telemetry record.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, current_user, pwd_context
from app.core.config import settings
from app.db.base import get_db
from app.db.models import (
    AuditEvent,
    Notification,
    Organization,
    OwnerControlRecord,
    Permission,
    Project,
    Role,
    RolePermission,
    User,
    Workspace,
    uuid_str,
)

FREE_USER_ROLE_NAME = "Free User"
FREE_PLAN_NAME = "free"
FREE_TIER_POLICY_DOMAIN = "free-tier-policy"
FREE_TIER_POLICY_RESOURCE = "default"
FREE_TIER_ACCOUNT_DOMAIN = "free-tier-account"
REGISTRATION_TELEMETRY_DOMAIN = "registration-telemetry"
FREE_USERNAME_IDENTITY_DOMAIN = "free-identity-username"
FREE_PHONE_IDENTITY_DOMAIN = "free-identity-phone"
FREE_NETWORK_IDENTITY_DOMAIN = "free-identity-network"
FREE_DEVICE_IDENTITY_DOMAIN = "free-identity-device"
FREE_USER_PERMISSIONS = (
    "profile:read",
    "projects:read",
    "projects:write",
)

DEFAULT_FREE_TIER_POLICY: dict[str, Any] = {
    "enabled": True,
    "project_limit": 1,
    "monthly_user_message_limit": 100,
    "monthly_assistant_response_limit": 100,
    "storage_limit_bytes": 100 * 1024 * 1024,
    "max_message_characters": 6000,
    "registrations_per_ip_per_day": 1,
    "minimum_age": 18,
    "require_phone_verification": True,
    "require_device_signals": True,
    "one_account_per_network": True,
    "one_account_per_device": True,
    "telemetry_retention_days": 90,
    "consent_version": "2026-07-31",
    "require_country": True,
    "require_cookie_consent": True,
}

_TELEMETRY_TEXT_LIMITS = {
    "timezone": 80,
    "language": 32,
    "platform": 160,
    "user_agent": 512,
    "screen": 80,
    "connection_type": 40,
    "effective_type": 40,
    "referrer": 500,
    "vendor": 160,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _as_utc(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _policy_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    merged = {**DEFAULT_FREE_TIER_POLICY, **(payload or {})}
    return {
        "enabled": bool(merged["enabled"]),
        "project_limit": int(merged["project_limit"]),
        "monthly_user_message_limit": int(merged["monthly_user_message_limit"]),
        "monthly_assistant_response_limit": int(
            merged["monthly_assistant_response_limit"]
        ),
        "storage_limit_bytes": int(merged["storage_limit_bytes"]),
        "max_message_characters": int(merged["max_message_characters"]),
        "registrations_per_ip_per_day": int(
            merged["registrations_per_ip_per_day"]
        ),
        "minimum_age": int(merged["minimum_age"]),
        "require_phone_verification": bool(
            merged["require_phone_verification"]
        ),
        "require_device_signals": bool(merged["require_device_signals"]),
        "one_account_per_network": bool(merged["one_account_per_network"]),
        "one_account_per_device": bool(merged["one_account_per_device"]),
        "telemetry_retention_days": int(merged["telemetry_retention_days"]),
        "consent_version": str(merged["consent_version"]),
        "require_country": bool(merged["require_country"]),
        "require_cookie_consent": bool(merged["require_cookie_consent"]),
    }


async def _ensure_policy_record(
    session: AsyncSession,
    *,
    lock: bool = False,
) -> OwnerControlRecord:
    statement = select(OwnerControlRecord).where(
        OwnerControlRecord.domain == FREE_TIER_POLICY_DOMAIN,
        OwnerControlRecord.resource_id == FREE_TIER_POLICY_RESOURCE,
    )
    if lock:
        statement = statement.with_for_update()
    record = await session.scalar(statement)
    if record is None:
        now = _now()
        await session.execute(
            pg_insert(OwnerControlRecord)
            .values(
                id=uuid_str(),
                domain=FREE_TIER_POLICY_DOMAIN,
                resource_id=FREE_TIER_POLICY_RESOURCE,
                status="active",
                enabled=True,
                payload=DEFAULT_FREE_TIER_POLICY,
                version=1,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_owner_control_domain_resource")
        )
        record = await session.scalar(statement)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Free-tier policy could not be initialized",
        )
    normalized = _policy_payload(record.payload)
    if record.payload != normalized:
        record.payload = normalized
        record.version += 1
    return record


async def get_free_tier_policy(session: AsyncSession) -> dict[str, Any]:
    record = await _ensure_policy_record(session)
    return _policy_payload(record.payload)


async def update_free_tier_policy(
    session: AsyncSession,
    updates: dict[str, Any],
) -> dict[str, Any]:
    record = await _ensure_policy_record(session, lock=True)
    record.payload = _policy_payload({**record.payload, **updates})
    record.enabled = bool(record.payload["enabled"])
    record.status = "active" if record.enabled else "suspended"
    record.version += 1
    return dict(record.payload)


def public_free_tier_policy(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": policy["enabled"],
        "plan": FREE_PLAN_NAME,
        "limits": {
            "projects": policy["project_limit"],
            "user_messages_per_month": policy["monthly_user_message_limit"],
            "assistant_responses_per_month": policy[
                "monthly_assistant_response_limit"
            ],
            "storage_bytes": policy["storage_limit_bytes"],
            "max_message_characters": policy["max_message_characters"],
        },
        "consent_version": policy["consent_version"],
        "identity": {
            "minimum_age": policy["minimum_age"],
            "phone_verification_required": policy[
                "require_phone_verification"
            ],
            "device_signals_required": policy["require_device_signals"],
            "one_account_per_network": policy["one_account_per_network"],
            "one_account_per_device": policy["one_account_per_device"],
        },
        "required_registration_data": [
            "declared country",
            "IP address",
            "browser and user agent",
            "device capabilities",
            "timezone and language",
            "available network quality metadata",
            "verified mobile phone",
            "date of birth and minimum-age validation",
            "unique username",
            "essential-cookie consent",
        ],
    }


def _new_usage_payload(now: datetime | None = None) -> dict[str, Any]:
    started = now or _now()
    return {
        "plan": FREE_PLAN_NAME,
        "period_started_at": _iso(started),
        "period_ends_at": _iso(started + timedelta(days=30)),
        "user_messages_used": 0,
        "assistant_responses_used": 0,
        "storage_bytes_used": 0,
    }


async def _ensure_account_record(
    session: AsyncSession,
    user_id: str,
    *,
    lock: bool = False,
) -> OwnerControlRecord:
    statement = select(OwnerControlRecord).where(
        OwnerControlRecord.domain == FREE_TIER_ACCOUNT_DOMAIN,
        OwnerControlRecord.resource_id == user_id,
    )
    if lock:
        statement = statement.with_for_update()
    record = await session.scalar(statement)
    if record is None:
        now = _now()
        await session.execute(
            pg_insert(OwnerControlRecord)
            .values(
                id=uuid_str(),
                domain=FREE_TIER_ACCOUNT_DOMAIN,
                resource_id=user_id,
                status="active",
                enabled=True,
                payload=_new_usage_payload(now),
                version=1,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_owner_control_domain_resource")
        )
        record = await session.scalar(statement)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Free-tier account state could not be initialized",
        )
    return record


def _reset_usage_if_needed(record: OwnerControlRecord) -> None:
    payload = {**_new_usage_payload(), **(record.payload or {})}
    period_end = _as_utc(payload.get("period_ends_at"))
    if period_end is None or period_end <= _now():
        payload = _new_usage_payload()
        record.version += 1
    record.payload = payload


async def get_free_tier_status(
    session: AsyncSession,
    actor: UserRecord,
) -> dict[str, Any]:
    if actor.organization_plan != FREE_PLAN_NAME and actor.role != FREE_USER_ROLE_NAME:
        return {"plan": actor.organization_plan, "free_tier": False}
    policy = await get_free_tier_policy(session)
    record = await _ensure_account_record(session, actor.id)
    _reset_usage_if_needed(record)
    project_count = int(
        await session.scalar(
            select(func.count(Project.id)).where(
                Project.organization_id == actor.organization_id,
                Project.status != "deleted",
            )
        )
        or 0
    )
    usage = record.payload
    limits = {
        "projects": policy["project_limit"],
        "user_messages": policy["monthly_user_message_limit"],
        "assistant_responses": policy["monthly_assistant_response_limit"],
        "storage_bytes": policy["storage_limit_bytes"],
        "max_message_characters": policy["max_message_characters"],
    }
    consumed = {
        "projects": project_count,
        "user_messages": int(usage.get("user_messages_used", 0)),
        "assistant_responses": int(usage.get("assistant_responses_used", 0)),
        "storage_bytes": int(usage.get("storage_bytes_used", 0)),
    }
    return {
        "plan": FREE_PLAN_NAME,
        "free_tier": True,
        "enabled": policy["enabled"],
        "limits": limits,
        "usage": consumed,
        "remaining": {
            key: max(0, int(limits[key]) - int(consumed[key]))
            for key in ("projects", "user_messages", "assistant_responses", "storage_bytes")
        },
        "period_started_at": usage.get("period_started_at"),
        "period_ends_at": usage.get("period_ends_at"),
    }


async def _consume_counter(
    session: AsyncSession,
    actor: UserRecord,
    *,
    counter: str,
    policy_key: str,
    amount: int = 1,
) -> None:
    if actor.role != FREE_USER_ROLE_NAME and actor.organization_plan != FREE_PLAN_NAME:
        return
    if amount < 1:
        raise ValueError("Usage amount must be positive")
    policy = await get_free_tier_policy(session)
    if not policy["enabled"]:
        raise HTTPException(status_code=403, detail="Free-tier access is suspended")
    record = await _ensure_account_record(session, actor.id, lock=True)
    _reset_usage_if_needed(record)
    payload = dict(record.payload)
    current = int(payload.get(counter, 0))
    limit = int(policy[policy_key])
    if current + amount > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Free-tier {counter.replace('_used', '').replace('_', ' ')} limit reached",
        )
    payload[counter] = current + amount
    record.payload = payload
    record.version += 1


async def consume_user_message(
    session: AsyncSession,
    actor: UserRecord,
    *,
    characters: int,
) -> None:
    policy = await get_free_tier_policy(session)
    if characters < 1 or characters > int(policy["max_message_characters"]):
        raise HTTPException(
            status_code=422,
            detail=(
                "Message length exceeds the owner-configured free-tier maximum of "
                f"{policy['max_message_characters']} characters"
            ),
        )
    await _consume_counter(
        session,
        actor,
        counter="user_messages_used",
        policy_key="monthly_user_message_limit",
    )


async def consume_assistant_response(
    session: AsyncSession,
    actor: UserRecord,
) -> None:
    await _consume_counter(
        session,
        actor,
        counter="assistant_responses_used",
        policy_key="monthly_assistant_response_limit",
    )


async def adjust_storage_usage(
    session: AsyncSession,
    actor: UserRecord,
    delta_bytes: int,
) -> None:
    if actor.role != FREE_USER_ROLE_NAME and actor.organization_plan != FREE_PLAN_NAME:
        return
    policy = await get_free_tier_policy(session)
    record = await _ensure_account_record(session, actor.id, lock=True)
    _reset_usage_if_needed(record)
    payload = dict(record.payload)
    next_usage = max(0, int(payload.get("storage_bytes_used", 0)) + delta_bytes)
    if next_usage > int(policy["storage_limit_bytes"]):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Free-tier storage limit reached",
        )
    payload["storage_bytes_used"] = next_usage
    record.payload = payload
    record.version += 1


async def assert_free_project_creation_allowed(
    session: AsyncSession,
    actor: UserRecord,
) -> None:
    if actor.role != FREE_USER_ROLE_NAME and actor.organization_plan != FREE_PLAN_NAME:
        return
    policy = await get_free_tier_policy(session)
    if not policy["enabled"]:
        raise HTTPException(status_code=403, detail="Free-tier access is suspended")
    project_count = int(
        await session.scalar(
            select(func.count(Project.id)).where(
                Project.organization_id == actor.organization_id,
                Project.status != "deleted",
            )
        )
        or 0
    )
    if project_count >= int(policy["project_limit"]):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Free project limit reached",
        )


async def enforce_free_project_request(
    request: Request,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> UserRecord:
    if actor.role == FREE_USER_ROLE_NAME and request.method.upper() == "POST":
        await assert_free_project_creation_allowed(session, actor)
    return actor


async def enforce_free_workspace_request(
    request: Request,
    actor: UserRecord = Depends(current_user),
) -> UserRecord:
    if actor.role == FREE_USER_ROLE_NAME and request.method.upper() != "GET":
        raise HTTPException(
            status_code=403,
            detail="Free accounts use their protected personal workspace",
        )
    return actor


async def require_non_free_user(
    actor: UserRecord = Depends(current_user),
) -> UserRecord:
    if actor.role == FREE_USER_ROLE_NAME:
        raise HTTPException(
            status_code=403,
            detail="This capability is not included in the free-user plan",
        )
    return actor


def client_ip_from_request(request: Request) -> str:
    candidates = [
        request.headers.get("cf-connecting-ip"),
        request.headers.get("x-real-ip"),
        (request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip(),
        request.client.host if request.client else None,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return str(ipaddress.ip_address(candidate.strip()))
        except ValueError:
            continue
    return "unknown"


def _safe_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def sanitize_registration_telemetry(telemetry: dict[str, Any] | None) -> dict[str, Any]:
    source = telemetry or {}
    result: dict[str, Any] = {}
    for key, limit in _TELEMETRY_TEXT_LIMITS.items():
        value = _safe_text(source.get(key), limit)
        if value is not None:
            result[key] = value
    for key in (
        "screen_width",
        "screen_height",
        "color_depth",
        "device_memory_gb",
        "hardware_concurrency",
        "max_touch_points",
        "downlink_mbps",
        "rtt_ms",
    ):
        value = source.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = max(0, value)
    for key in ("cookie_enabled", "do_not_track", "save_data", "webdriver"):
        value = source.get(key)
        if isinstance(value, bool):
            result[key] = value
    return result


def avatar_data_size(value: str | None) -> int:
    if not value:
        return 0
    prefix = "base64,"
    if prefix not in value:
        return len(value.encode("utf-8"))
    encoded = value.split(prefix, 1)[1]
    try:
        return len(base64.b64decode(encoded, validate=True))
    except ValueError:
        return len(encoded.encode("utf-8"))


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid phone verification token",
        ) from exc


def verify_phone_verification_token(
    token: str,
    phone_number: str,
) -> dict[str, Any]:
    """Validate a signed assertion from the configured phone-verification service.

    The provider must sign ``base64url(JSON).base64url(HMAC-SHA256(payload))`` and
    attest that the number is a currently verified mobile line.  The application
    fails closed when no production secret is configured.
    """

    secret = os.getenv("AIOS_PHONE_VERIFICATION_SECRET", "").encode("utf-8")
    if len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Phone verification provider is not configured",
        )

    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        payload_bytes = _b64url_decode(encoded_payload)
        signature = _b64url_decode(encoded_signature)
        expected = hmac.new(
            secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        payload = json.loads(payload_bytes)
        if not isinstance(payload, dict):
            raise TypeError("phone assertion payload must be an object")
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid phone verification token",
        ) from exc

    expires_at = _as_utc(payload.get("expires_at"))
    line_type = str(payload.get("line_type") or "").strip().lower()
    blocked_types = {
        "voip",
        "virtual",
        "fixed_voip",
        "landline",
        "toll_free",
        "premium",
        "unknown",
    }
    if (
        payload.get("phone_number") != phone_number
        or payload.get("verified") is not True
        or line_type != "mobile"
        or line_type in blocked_types
        or expires_at is None
        or expires_at <= _now()
        or not str(payload.get("provider") or "").strip()
    ):
        raise HTTPException(
            status_code=422,
            detail="A currently verified real mobile number is required",
        )

    payload["line_type"] = line_type
    return payload


def _age_on(birth_date: date, today: date) -> int:
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


def _assert_real_device_signals(telemetry: dict[str, Any]) -> None:
    user_agent = str(telemetry.get("user_agent") or "").strip()
    platform = str(telemetry.get("platform") or "").strip()
    browser_automation = re.compile(
        r"headless|phantomjs|selenium|playwright|puppeteer|webdriver",
        re.IGNORECASE,
    )
    if (
        telemetry.get("cookie_enabled") is not True
        or telemetry.get("webdriver") is True
        or int(telemetry.get("hardware_concurrency") or 0) < 1
        or not user_agent
        or not platform
        or browser_automation.search(user_agent)
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Registration requires enabled cookies and supported real-device "
                "browser signals"
            ),
        )


def _identity_hmac(value: str) -> str:
    configured = os.getenv("AIOS_IDENTITY_HASH_SECRET") or os.getenv(
        "AIOS_PHONE_VERIFICATION_SECRET"
    )
    secret = (configured or settings.SECRET_KEY).encode("utf-8")
    if len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity protection secret is not configured",
        )
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _device_fingerprint(telemetry: dict[str, Any]) -> str:
    stable = {
        key: telemetry.get(key)
        for key in (
            "platform",
            "user_agent",
            "screen_width",
            "screen_height",
            "color_depth",
            "device_memory_gb",
            "hardware_concurrency",
            "max_touch_points",
            "timezone",
            "language",
        )
    }
    return _identity_hmac(json.dumps(stable, sort_keys=True, separators=(",", ":")))


async def _reserve_identity(
    session: AsyncSession,
    *,
    domain: str,
    resource_id: str,
    user_id: str,
    duplicate_detail: str,
) -> None:
    now = _now()
    reserved_id = await session.scalar(
        pg_insert(OwnerControlRecord)
        .values(
            id=uuid_str(),
            domain=domain,
            resource_id=resource_id,
            status="reserved",
            enabled=True,
            payload={"user_id": user_id},
            version=1,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_owner_control_domain_resource")
        .returning(OwnerControlRecord.id)
    )
    if reserved_id is None:
        raise HTTPException(status_code=409, detail=duplicate_detail)


async def _registration_rate_check(
    session: AsyncSession,
    *,
    ip_address: str,
    policy: dict[str, Any],
) -> None:
    if ip_address == "unknown":
        return
    registrations = int(
        await session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action == "auth.free_register",
                AuditEvent.ip_address == ip_address,
                AuditEvent.created_at >= _now() - timedelta(days=1),
            )
        )
        or 0
    )
    if registrations >= int(policy["registrations_per_ip_per_day"]):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Free-account registration limit reached for this network",
        )


async def register_free_account(
    session: AsyncSession,
    request: Request,
    *,
    username: str,
    email: str,
    password: str,
    name: str,
    birth_date: date,
    country_code: str,
    phone_number: str,
    phone_verification_token: str,
    consent_accepted: bool,
    consent_version: str,
    telemetry: dict[str, Any] | None,
) -> User:
    policy = await get_free_tier_policy(session)
    if not policy["enabled"]:
        raise HTTPException(status_code=403, detail="Free registration is disabled")
    if policy["require_cookie_consent"] and not consent_accepted:
        raise HTTPException(
            status_code=422,
            detail="Essential-cookie, privacy, and terms consent is required",
        )
    if consent_version != policy["consent_version"]:
        raise HTTPException(
            status_code=409,
            detail="The registration consent notice has changed; review it again",
        )

    normalized_username = username.strip().lower()
    normalized_email = email.strip().lower()
    normalized_name = name.strip()
    normalized_country = country_code.strip().upper()
    normalized_phone = phone_number.strip()

    if not re.fullmatch(r"[a-z0-9_.-]{3,32}", normalized_username):
        raise HTTPException(status_code=422, detail="Username is invalid")
    if len(normalized_name) < 2:
        raise HTTPException(status_code=422, detail="Name is too short")
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters",
        )
    if policy["require_country"] and (
        len(normalized_country) != 2 or not normalized_country.isalpha()
    ):
        raise HTTPException(
            status_code=422,
            detail="A two-letter country code is required",
        )
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", normalized_phone):
        raise HTTPException(
            status_code=422,
            detail="A valid international mobile number is required",
        )
    if birth_date > _now().date() or _age_on(birth_date, _now().date()) < int(
        policy["minimum_age"]
    ):
        raise HTTPException(
            status_code=422,
            detail="Minimum registration age is not met",
        )

    phone_assertion = (
        verify_phone_verification_token(
            phone_verification_token,
            normalized_phone,
        )
        if policy["require_phone_verification"]
        else {"provider": "disabled", "line_type": "mobile", "verified": False}
    )
    sanitized = sanitize_registration_telemetry(telemetry)
    if policy["require_device_signals"]:
        _assert_real_device_signals(sanitized)

    if await session.scalar(select(User.id).where(User.email == normalized_email)):
        raise HTTPException(status_code=409, detail="Email already registered")

    ip_address = client_ip_from_request(request)
    if ip_address == "unknown":
        raise HTTPException(
            status_code=422,
            detail="A verifiable client network address is required",
        )
    await _registration_rate_check(
        session,
        ip_address=ip_address,
        policy=policy,
    )

    user_id = uuid_str()
    phone_hash = _identity_hmac(normalized_phone)
    network_hash = _identity_hmac(ip_address)
    device_hash = _device_fingerprint(sanitized)
    await _reserve_identity(
        session,
        domain=FREE_USERNAME_IDENTITY_DOMAIN,
        resource_id=normalized_username,
        user_id=user_id,
        duplicate_detail="Username already registered",
    )
    await _reserve_identity(
        session,
        domain=FREE_PHONE_IDENTITY_DOMAIN,
        resource_id=phone_hash,
        user_id=user_id,
        duplicate_detail="Phone number already registered",
    )
    if policy["one_account_per_network"]:
        await _reserve_identity(
            session,
            domain=FREE_NETWORK_IDENTITY_DOMAIN,
            resource_id=network_hash,
            user_id=user_id,
            duplicate_detail="A free account already exists on this network",
        )
    if policy["one_account_per_device"]:
        await _reserve_identity(
            session,
            domain=FREE_DEVICE_IDENTITY_DOMAIN,
            resource_id=device_hash,
            user_id=user_id,
            duplicate_detail="A free account already exists on this device",
        )

    organization = Organization(
        name=f"{normalized_name} Personal",
        slug=f"free-{secrets.token_hex(8)}",
        plan=FREE_PLAN_NAME,
        status="active",
    )
    session.add(organization)
    await session.flush()

    role = Role(
        organization_id=organization.id,
        name=FREE_USER_ROLE_NAME,
        description="Restricted personal free-plan account.",
        system=True,
        status="active",
    )
    session.add(role)
    await session.flush()

    permission_rows = list(
        (
            await session.scalars(
                select(Permission).where(Permission.code.in_(FREE_USER_PERMISSIONS))
            )
        ).all()
    )
    by_code = {permission.code: permission for permission in permission_rows}
    missing = sorted(set(FREE_USER_PERMISSIONS) - set(by_code))
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"missing_free_user_permissions": missing},
        )
    session.add_all(
        [
            RolePermission(role_id=role.id, permission_id=by_code[code].id)
            for code in FREE_USER_PERMISSIONS
        ]
    )

    workspace = Workspace(
        organization_id=organization.id,
        name="Personal Workspace",
        slug="personal",
        description="Protected workspace for the free project.",
        status="active",
    )
    session.add(workspace)

    user = User(
        id=user_id,
        organization_id=organization.id,
        role_id=role.id,
        email=normalized_email,
        name=normalized_name,
        password_hash=pwd_context.hash(password),
        status="active",
    )
    session.add(user)
    await session.flush()

    now = _now()
    session.add(
        OwnerControlRecord(
            domain=FREE_TIER_ACCOUNT_DOMAIN,
            resource_id=user.id,
            status="active",
            enabled=True,
            payload=_new_usage_payload(now),
            version=1,
        )
    )

    detected_country = _safe_text(
        request.headers.get("cf-ipcountry")
        or request.headers.get("x-country-code"),
        2,
    )
    session.add(
        OwnerControlRecord(
            domain=REGISTRATION_TELEMETRY_DOMAIN,
            resource_id=user.id,
            status="active",
            enabled=True,
            payload={
                "username": normalized_username,
                "birth_date": birth_date.isoformat(),
                "declared_country": normalized_country,
                "detected_country": detected_country.upper()
                if detected_country
                else None,
                "phone_hash": phone_hash,
                "phone_masked": f"{normalized_phone[:3]}***{normalized_phone[-4:]}",
                "phone_verification": {
                    "verified": bool(phone_assertion.get("verified", True)),
                    "provider": str(phone_assertion.get("provider") or "unknown"),
                    "line_type": str(phone_assertion.get("line_type") or "unknown"),
                    "verified_at": str(
                        phone_assertion.get("verified_at") or _iso(now)
                    ),
                },
                "identity_status": "verified",
                "network_hash": network_hash,
                "device_hash": device_hash,
                "ip_address": ip_address,
                "server_user_agent": _safe_text(
                    request.headers.get("user-agent"), 512
                ),
                "accept_language": _safe_text(
                    request.headers.get("accept-language"), 160
                ),
                "telemetry": sanitized,
                "consent": {
                    "accepted": True,
                    "version": consent_version,
                    "accepted_at": _iso(now),
                    "categories": ["essential", "security", "quota", "device"],
                },
            },
            version=1,
        )
    )
    session.add(
        AuditEvent(
            organization_id=organization.id,
            user_id=user.id,
            action="auth.free_register",
            resource_type="user",
            resource_id=user.id,
            details={
                "plan": FREE_PLAN_NAME,
                "username": normalized_username,
                "declared_country": normalized_country,
                "phone_provider": phone_assertion.get("provider"),
                "phone_line_type": phone_assertion.get("line_type"),
                "identity_status": "verified",
                "consent_version": consent_version,
            },
            ip_address=ip_address,
        )
    )

    owner = await session.scalar(
        select(User)
        .join(Role, Role.id == User.role_id)
        .where(
            Role.name == "Super Owner",
            User.deleted_at.is_(None),
        )
        .order_by(User.created_at)
        .limit(1)
    )
    if owner is not None:
        session.add(
            Notification(
                organization_id=owner.organization_id,
                recipient_id=owner.id,
                type="free_user_registered",
                title="New free user registered",
                message=f"{normalized_name} registered from {normalized_country}.",
                severity="info",
                payload={"user_id": user.id, "organization_id": organization.id},
            )
        )

    cutoff = now - timedelta(days=int(policy["telemetry_retention_days"]))
    await session.execute(
        delete(OwnerControlRecord).where(
            OwnerControlRecord.domain == REGISTRATION_TELEMETRY_DOMAIN,
            OwnerControlRecord.updated_at < cutoff,
        )
    )
    await session.flush()
    return user


async def list_free_accounts(
    session: AsyncSession,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(User, Organization)
            .join(Organization, Organization.id == User.organization_id)
            .join(Role, Role.id == User.role_id)
            .where(
                Organization.plan == FREE_PLAN_NAME,
                Role.name == FREE_USER_ROLE_NAME,
                User.deleted_at.is_(None),
            )
            .order_by(User.created_at.desc())
            .limit(limit)
        )
    ).all()
    result: list[dict[str, Any]] = []
    for user, organization in rows:
        actor = UserRecord(
            id=user.id,
            email=user.email,
            name=user.name,
            role=FREE_USER_ROLE_NAME,
            password_hash=user.password_hash,
            organization_id=organization.id,
            organization_name=organization.name,
            organization_plan=organization.plan,
            permissions=list(FREE_USER_PERMISSIONS),
            status=user.status,
            auth_version=user.auth_version,
        )
        telemetry_record = await session.scalar(
            select(OwnerControlRecord).where(
                OwnerControlRecord.domain == REGISTRATION_TELEMETRY_DOMAIN,
                OwnerControlRecord.resource_id == user.id,
            )
        )
        result.append(
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "status": user.status,
                "created_at": user.created_at.isoformat(),
                "quota": await get_free_tier_status(session, actor),
                "registration": telemetry_record.payload
                if telemetry_record is not None
                else None,
            }
        )
    return result
