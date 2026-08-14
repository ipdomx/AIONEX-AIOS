"""GS-04 durable content operations and deterministic publish simulation.

This module never performs a provider network call. Live publishing remains disabled.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    GrowthContentItem,
    GrowthContentPublishSimulation,
    GrowthContentSchedule,
    GrowthContentVariant,
    GrowthSocialAccount,
    GrowthSocialProviderCapability,
)
from app.services import growth_access
from app.services import growth_social_accounts as social_accounts

LIVE_PUBLISH_ALLOWED = False
CONTENT_TYPES = (
    "text",
    "image",
    "carousel",
    "video",
    "reel",
    "short",
    "story",
    "link",
    "poll",
    "gif",
)
RECURRENCES = ("none", "daily", "weekly", "monthly")
MEDIA_REF_PREFIXES = ("studio:", "asset:", "media:")
APPROVER_ROLES = {"Super Owner", "Owner", "Admin"}
_MEDIA_REF_RE = re.compile(r"^[A-Za-z0-9._:@/+\-]{3,500}$")


class GrowthContentError(RuntimeError):
    """Fail-closed GS-04 content operations error."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _access(session: AsyncSession, actor: UserRecord):
    decision = await growth_access.effective_access(session, actor, "content.publish")
    if not decision.allowed:
        raise GrowthContentError(f"access-denied:{decision.reason}")
    return decision


def validate_media_refs(values: list[str] | None) -> list[str]:
    refs: list[str] = []
    for raw in values or []:
        ref = str(raw).strip()
        if not ref.startswith(MEDIA_REF_PREFIXES):
            raise GrowthContentError("media-reference-must-be-opaque")
        if not _MEDIA_REF_RE.fullmatch(ref) or ".." in ref:
            raise GrowthContentError("invalid-media-reference")
        refs.append(ref)
    return refs


def _assert_safe_payload(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).strip().lower()
            if any(marker in lowered for marker in social_accounts.SENSITIVE_KEYS):
                raise GrowthContentError(f"sensitive-field-rejected:{path}.{key}")
            _assert_safe_payload(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_safe_payload(item, path=f"{path}[{index}]")


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized[:80] or "content"


def add_utm_parameters(
    url: str | None,
    *,
    source: str,
    campaign: str,
    content: str,
    medium: str = "social",
) -> str | None:
    if not url:
        return None
    split = urlsplit(url.strip())
    if split.scheme not in {"http", "https"} or not split.netloc:
        raise GrowthContentError("invalid-link-url")
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query.update(
        {
            "utm_source": source,
            "utm_medium": medium,
            "utm_campaign": campaign,
            "utm_content": content,
        }
    )
    return urlunsplit(
        (
            split.scheme,
            split.netloc,
            split.path,
            urlencode(sorted(query.items())),
            split.fragment,
        )
    )


def build_preview(
    *,
    content: GrowthContentItem,
    variant: GrowthContentVariant,
    account: GrowthSocialAccount | None,
) -> dict[str, Any]:
    media_refs = list(variant.media_refs or content.media_refs or [])
    text = variant.text if variant.text else content.base_text
    link = variant.link_url or content.link_url
    return {
        "content_id": content.id,
        "variant_id": variant.id,
        "provider": variant.provider,
        "account_id": variant.account_id,
        "account_kind": account.account_kind if account is not None else None,
        "content_type": content.content_type,
        "text": text,
        "text_length": len(text),
        "media_refs": media_refs,
        "media_count": len(media_refs),
        "link_url": link,
        "hashtags": list(variant.hashtags or []),
        "mentions": list(variant.mentions or []),
        "platform_overrides": dict(variant.platform_overrides or {}),
        "provider_limits_verified": False,
        "live_publish_allowed": False,
    }


def _fingerprint(preview: dict[str, Any], schedule_id: str) -> str:
    canonical = json.dumps(
        {"schedule_id": schedule_id, "preview": preview},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _public_item(row: GrowthContentItem) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "content_type": row.content_type,
        "base_text": row.base_text,
        "link_url": row.link_url,
        "media_refs": list(row.media_refs or []),
        "tags": list(row.tags or []),
        "status": row.status,
        "approval_status": row.approval_status,
        "approved_by_id": row.approved_by_id,
        "approved_at": row.approved_at,
        "approval_note": row.approval_note,
        "recycle_count": row.recycle_count,
        "content_metadata": dict(row.content_metadata or {}),
        "version": row.version,
        "live_publish_allowed": False,
    }


def _public_variant(row: GrowthContentVariant) -> dict[str, Any]:
    return {
        "id": row.id,
        "content_id": row.content_id,
        "account_id": row.account_id,
        "provider": row.provider,
        "text": row.text,
        "link_url": row.link_url,
        "media_refs": list(row.media_refs or []),
        "hashtags": list(row.hashtags or []),
        "mentions": list(row.mentions or []),
        "platform_overrides": dict(row.platform_overrides or {}),
        "status": row.status,
        "version": row.version,
        "live_publish_allowed": False,
    }


def _public_schedule(row: GrowthContentSchedule) -> dict[str, Any]:
    return {
        "id": row.id,
        "content_id": row.content_id,
        "variant_id": row.variant_id,
        "account_id": row.account_id,
        "provider": row.provider,
        "scheduled_for": row.scheduled_for,
        "timezone": row.timezone,
        "recurrence": row.recurrence,
        "priority": row.priority,
        "status": row.status,
        "approval_required": row.approval_required,
        "attempt_count": row.attempt_count,
        "recycle_of_schedule_id": row.recycle_of_schedule_id,
        "version": row.version,
        "live_publish_allowed": False,
    }


def _public_simulation(row: GrowthContentPublishSimulation) -> dict[str, Any]:
    return {
        "id": row.id,
        "schedule_id": row.schedule_id,
        "content_id": row.content_id,
        "variant_id": row.variant_id,
        "account_id": row.account_id,
        "provider": row.provider,
        "status": row.status,
        "fingerprint": row.fingerprint,
        "preview": dict(row.preview or {}),
        "reason_codes": list(row.reason_codes or []),
        "utm_url": row.utm_url,
        "live_publish_allowed": False,
        "simulated_at": row.simulated_at,
    }


def _audit(
    session: AsyncSession,
    actor: UserRecord,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details={"live_provider_call": False, **dict(details or {})},
        )
    )


async def _item(
    session: AsyncSession, actor: UserRecord, content_id: str
) -> GrowthContentItem:
    await _access(session, actor)
    row = await session.scalar(
        select(GrowthContentItem).where(
            GrowthContentItem.id == content_id,
            GrowthContentItem.organization_id == actor.organization_id,
        )
    )
    if row is None:
        raise GrowthContentError("content-not-found")
    return row


async def _variant(
    session: AsyncSession, actor: UserRecord, variant_id: str
) -> GrowthContentVariant:
    await _access(session, actor)
    row = await session.scalar(
        select(GrowthContentVariant).where(
            GrowthContentVariant.id == variant_id,
            GrowthContentVariant.organization_id == actor.organization_id,
        )
    )
    if row is None:
        raise GrowthContentError("variant-not-found")
    return row


async def _schedule(
    session: AsyncSession, actor: UserRecord, schedule_id: str
) -> GrowthContentSchedule:
    await _access(session, actor)
    row = await session.scalar(
        select(GrowthContentSchedule).where(
            GrowthContentSchedule.id == schedule_id,
            GrowthContentSchedule.organization_id == actor.organization_id,
        )
    )
    if row is None:
        raise GrowthContentError("schedule-not-found")
    return row


async def create_content(
    session: AsyncSession, actor: UserRecord, payload: dict[str, Any]
) -> GrowthContentItem:
    await _access(session, actor)
    content_type = str(payload.get("content_type") or "text").strip().lower()
    if content_type not in CONTENT_TYPES:
        raise GrowthContentError("unsupported-content-type")
    title = str(payload.get("title") or "").strip()
    if not title:
        raise GrowthContentError("content-title-required")
    metadata = dict(payload.get("content_metadata") or {})
    _assert_safe_payload(metadata, path="content_metadata")
    media_refs = validate_media_refs(payload.get("media_refs"))
    link_url = str(payload.get("link_url") or "").strip() or None
    if link_url:
        add_utm_parameters(
            link_url, source="preview", campaign="validation", content="validation"
        )
    row = GrowthContentItem(
        organization_id=actor.organization_id,
        created_by_id=actor.id,
        project_id=payload.get("project_id"),
        title=title[:240],
        content_type=content_type,
        base_text=str(payload.get("base_text") or ""),
        link_url=link_url,
        media_refs=media_refs,
        tags=[
            str(item).strip()[:80]
            for item in payload.get("tags") or []
            if str(item).strip()
        ],
        status="draft",
        approval_status="not_requested",
        recycle_count=0,
        content_metadata=metadata,
        version=1,
    )
    session.add(row)
    await session.flush()
    _audit(
        session,
        actor,
        "growth.content.created",
        "growth_content_item",
        row.id,
        {"content_type": content_type},
    )
    await session.flush()
    return row


async def update_content(
    session: AsyncSession,
    actor: UserRecord,
    content_id: str,
    payload: dict[str, Any],
) -> GrowthContentItem:
    row = await _item(session, actor, content_id)
    if row.status == "archived":
        raise GrowthContentError("archived-content-is-read-only")
    changed = False
    for field in ("title", "base_text"):
        if field in payload:
            value = str(payload.get(field) or "")
            if field == "title" and not value.strip():
                raise GrowthContentError("content-title-required")
            setattr(row, field, value[:240] if field == "title" else value)
            changed = True
    if "link_url" in payload:
        link = str(payload.get("link_url") or "").strip() or None
        if link:
            add_utm_parameters(
                link, source="preview", campaign="validation", content="validation"
            )
        row.link_url = link
        changed = True
    if "media_refs" in payload:
        row.media_refs = validate_media_refs(payload.get("media_refs"))
        changed = True
    if "tags" in payload:
        row.tags = [
            str(item).strip()[:80]
            for item in payload.get("tags") or []
            if str(item).strip()
        ]
        changed = True
    if "content_metadata" in payload:
        metadata = dict(payload.get("content_metadata") or {})
        _assert_safe_payload(metadata, path="content_metadata")
        row.content_metadata = metadata
        changed = True
    if changed and row.approval_status == "approved":
        row.approval_status = "not_requested"
        row.approved_by_id = None
        row.approved_at = None
        row.approval_note = "approval-reset-after-content-change"
        row.status = "draft"
    if changed:
        row.version += 1
        _audit(session, actor, "growth.content.updated", "growth_content_item", row.id)
    await session.flush()
    return row


async def list_content(
    session: AsyncSession, actor: UserRecord
) -> list[dict[str, Any]]:
    await _access(session, actor)
    rows = (
        await session.scalars(
            select(GrowthContentItem)
            .where(GrowthContentItem.organization_id == actor.organization_id)
            .order_by(GrowthContentItem.created_at.desc())
            .limit(500)
        )
    ).all()
    return [_public_item(row) for row in rows]


async def create_variant(
    session: AsyncSession,
    actor: UserRecord,
    content_id: str,
    payload: dict[str, Any],
) -> GrowthContentVariant:
    content = await _item(session, actor, content_id)
    provider = str(payload.get("provider") or "").strip().lower()
    if provider not in social_accounts.PROVIDERS:
        raise GrowthContentError("unsupported-provider")
    account_id = payload.get("account_id")
    account = None
    if account_id:
        account = await session.scalar(
            select(GrowthSocialAccount).where(
                GrowthSocialAccount.id == account_id,
                GrowthSocialAccount.organization_id == actor.organization_id,
            )
        )
        if account is None:
            raise GrowthContentError("social-account-not-found")
        if account.provider != provider:
            raise GrowthContentError("provider-account-mismatch")
    overrides = dict(payload.get("platform_overrides") or {})
    _assert_safe_payload(overrides, path="platform_overrides")
    media_refs = validate_media_refs(payload.get("media_refs") or content.media_refs)
    link_url = str(payload.get("link_url") or content.link_url or "").strip() or None
    if link_url:
        add_utm_parameters(
            link_url, source=provider, campaign=_slug(content.title), content="preview"
        )
    row = GrowthContentVariant(
        organization_id=actor.organization_id,
        content_id=content.id,
        account_id=account.id if account else None,
        provider=provider,
        text=str(
            payload.get("text")
            if payload.get("text") is not None
            else content.base_text
        ),
        link_url=link_url,
        media_refs=media_refs,
        hashtags=[
            str(item).strip()[:100]
            for item in payload.get("hashtags") or []
            if str(item).strip()
        ],
        mentions=[
            str(item).strip()[:100]
            for item in payload.get("mentions") or []
            if str(item).strip()
        ],
        platform_overrides=overrides,
        status="ready",
        version=1,
    )
    session.add(row)
    await session.flush()
    _audit(
        session,
        actor,
        "growth.content.variant_created",
        "growth_content_variant",
        row.id,
        {"content_id": content.id, "provider": provider, "account_id": row.account_id},
    )
    await session.flush()
    return row


async def preview_variant(
    session: AsyncSession, actor: UserRecord, variant_id: str
) -> dict[str, Any]:
    variant = await _variant(session, actor, variant_id)
    content = await session.get(GrowthContentItem, variant.content_id)
    if content is None or content.organization_id != actor.organization_id:
        raise GrowthContentError("content-not-found")
    account = (
        await session.get(GrowthSocialAccount, variant.account_id)
        if variant.account_id
        else None
    )
    preview = build_preview(content=content, variant=variant, account=account)
    preview["utm_url"] = add_utm_parameters(
        variant.link_url or content.link_url,
        source=variant.provider,
        campaign=_slug(content.title),
        content=variant.id,
    )
    return preview


async def request_approval(
    session: AsyncSession, actor: UserRecord, content_id: str
) -> GrowthContentItem:
    row = await _item(session, actor, content_id)
    row.approval_status = "pending"
    row.status = "pending_approval"
    row.approved_by_id = None
    row.approved_at = None
    row.approval_note = None
    row.version += 1
    _audit(
        session,
        actor,
        "growth.content.approval_requested",
        "growth_content_item",
        row.id,
    )
    await session.flush()
    return row


async def decide_approval(
    session: AsyncSession,
    actor: UserRecord,
    content_id: str,
    *,
    approved: bool,
    note: str | None = None,
) -> GrowthContentItem:
    row = await _item(session, actor, content_id)
    if actor.role not in APPROVER_ROLES:
        raise GrowthContentError("approval-role-required")
    if row.approval_status != "pending":
        raise GrowthContentError("approval-not-pending")
    row.approval_status = "approved" if approved else "rejected"
    row.status = "approved" if approved else "draft"
    row.approved_by_id = actor.id if approved else None
    row.approved_at = _utcnow() if approved else None
    row.approval_note = (note or "").strip()[:2000] or None
    row.version += 1
    _audit(
        session,
        actor,
        "growth.content.approval_decided",
        "growth_content_item",
        row.id,
        {"approved": approved},
    )
    await session.flush()
    return row


async def schedule_variant(
    session: AsyncSession,
    actor: UserRecord,
    variant_id: str,
    payload: dict[str, Any],
) -> GrowthContentSchedule:
    decision = await _access(session, actor)
    variant = await _variant(session, actor, variant_id)
    content = await session.get(GrowthContentItem, variant.content_id)
    if content is None or content.organization_id != actor.organization_id:
        raise GrowthContentError("content-not-found")
    if not variant.account_id:
        raise GrowthContentError("variant-account-required")
    account = await session.scalar(
        select(GrowthSocialAccount).where(
            GrowthSocialAccount.id == variant.account_id,
            GrowthSocialAccount.organization_id == actor.organization_id,
        )
    )
    if account is None:
        raise GrowthContentError("social-account-not-found")
    if account.provider != variant.provider:
        raise GrowthContentError("provider-account-mismatch")
    if account.status != "active":
        raise GrowthContentError("social-account-not-active")
    approval_required = bool(decision.approval_required)
    if approval_required and content.approval_status != "approved":
        raise GrowthContentError("approval-required")
    recurrence = str(payload.get("recurrence") or "none").strip().lower()
    if recurrence not in RECURRENCES:
        raise GrowthContentError("unsupported-recurrence")
    scheduled_for = payload.get("scheduled_for")
    if not isinstance(scheduled_for, datetime):
        raise GrowthContentError("scheduled-for-required")
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
    priority = max(0, min(100, int(payload.get("priority", 50))))
    row = GrowthContentSchedule(
        organization_id=actor.organization_id,
        content_id=content.id,
        variant_id=variant.id,
        account_id=account.id,
        provider=variant.provider,
        scheduled_for=scheduled_for,
        timezone=str(payload.get("timezone") or "UTC")[:80],
        recurrence=recurrence,
        priority=priority,
        status="queued",
        approval_required=approval_required,
        attempt_count=0,
        version=1,
    )
    session.add(row)
    content.status = "scheduled"
    content.version += 1
    await session.flush()
    _audit(
        session,
        actor,
        "growth.content.scheduled",
        "growth_content_schedule",
        row.id,
        {"content_id": content.id, "provider": row.provider, "priority": priority},
    )
    await session.flush()
    return row


def _recurrence_next(value: datetime, recurrence: str) -> datetime | None:
    if recurrence == "daily":
        return value + timedelta(days=1)
    if recurrence == "weekly":
        return value + timedelta(days=7)
    if recurrence == "monthly":
        return value + timedelta(days=30)
    return None


async def _mark_provider_simulated(
    session: AsyncSession, provider: str, account_kind: str
) -> None:
    await social_accounts.ensure_capability_matrix(session)
    row = await session.scalar(
        select(GrowthSocialProviderCapability).where(
            GrowthSocialProviderCapability.provider == provider,
            GrowthSocialProviderCapability.capability == "content.publish",
        )
    )
    if row is None:
        raise GrowthContentError("provider-capability-matrix-missing")
    if row.verification_state != "verified":
        row.verification_state = "simulated"
        row.simulated_at = _utcnow()
        row.verified_at = None
        row.evidence = {
            "source": "gs04-content-publish-simulator",
            "live_verified": False,
            "account_kind": account_kind,
        }
        row.version += 1


async def simulate_schedule(
    session: AsyncSession,
    actor: UserRecord,
    schedule_id: str,
    *,
    now: datetime | None = None,
) -> GrowthContentPublishSimulation:
    await _access(session, actor)
    schedule = await _schedule(session, actor, schedule_id)
    if schedule.status != "queued":
        raise GrowthContentError("schedule-not-queued")
    current = now or _utcnow()
    due = schedule.scheduled_for
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    if due > current:
        raise GrowthContentError("schedule-not-due")
    content = await session.get(GrowthContentItem, schedule.content_id)
    variant = await session.get(GrowthContentVariant, schedule.variant_id)
    account = await session.get(GrowthSocialAccount, schedule.account_id)
    if content is None or variant is None or account is None:
        raise GrowthContentError("schedule-target-missing")
    if (
        content.organization_id != actor.organization_id
        or account.organization_id != actor.organization_id
    ):
        raise GrowthContentError("schedule-tenant-mismatch")

    reasons = ["simulation-only", "no-provider-call", "live-publish-disabled"]
    blocked = False
    if schedule.approval_required and content.approval_status != "approved":
        blocked = True
        reasons.append("approval-not-approved")
    if account.status != "active":
        blocked = True
        reasons.append(f"account-status:{account.status}")
    if account.health_state in {"expired", "revoked", "paused", "rate_limited"}:
        blocked = True
        reasons.append(f"account-health:{account.health_state}")
    if account.health_state in {"unknown", "expiring"}:
        reasons.append(f"account-health:{account.health_state}")

    preview = build_preview(content=content, variant=variant, account=account)
    utm_url = add_utm_parameters(
        variant.link_url or content.link_url,
        source=variant.provider,
        campaign=_slug(content.title),
        content=variant.id,
    )
    preview["utm_url"] = utm_url
    status = "simulated_blocked" if blocked else "simulated_success"
    record = GrowthContentPublishSimulation(
        organization_id=actor.organization_id,
        schedule_id=schedule.id,
        content_id=content.id,
        variant_id=variant.id,
        account_id=account.id,
        provider=variant.provider,
        status=status,
        fingerprint=_fingerprint(preview, schedule.id),
        preview=preview,
        reason_codes=reasons,
        utm_url=utm_url,
        live_publish_allowed=False,
        simulated_at=current,
    )
    session.add(record)
    schedule.attempt_count += 1
    schedule.status = "blocked" if blocked else "simulated_published"
    schedule.simulated_at = current
    schedule.version += 1
    if not blocked:
        content.status = "simulated_published"
        content.version += 1
        await _mark_provider_simulated(session, account.provider, account.account_kind)
        next_time = _recurrence_next(schedule.scheduled_for, schedule.recurrence)
        if next_time is not None:
            next_schedule = GrowthContentSchedule(
                organization_id=actor.organization_id,
                content_id=content.id,
                variant_id=variant.id,
                account_id=account.id,
                provider=variant.provider,
                scheduled_for=next_time,
                timezone=schedule.timezone,
                recurrence=schedule.recurrence,
                priority=schedule.priority,
                status="queued",
                approval_required=schedule.approval_required,
                attempt_count=0,
                recycle_of_schedule_id=schedule.id,
                version=1,
            )
            session.add(next_schedule)
            content.recycle_count += 1
    await session.flush()
    _audit(
        session,
        actor,
        "growth.content.publish_simulated",
        "growth_content_publish_simulation",
        record.id,
        {"schedule_id": schedule.id, "status": status, "reason_codes": reasons},
    )
    await session.flush()
    return record


async def simulate_due_queue(
    session: AsyncSession,
    actor: UserRecord,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    await _access(session, actor)
    current = now or _utcnow()
    rows = (
        await session.scalars(
            select(GrowthContentSchedule)
            .where(
                GrowthContentSchedule.organization_id == actor.organization_id,
                GrowthContentSchedule.status == "queued",
                GrowthContentSchedule.scheduled_for <= current,
            )
            .order_by(
                desc(GrowthContentSchedule.priority),
                GrowthContentSchedule.scheduled_for,
            )
            .limit(max(1, min(100, limit)))
        )
    ).all()
    results = []
    for row in rows:
        result = await simulate_schedule(session, actor, row.id, now=current)
        results.append(_public_simulation(result))
    return results


async def recycle_schedule(
    session: AsyncSession,
    actor: UserRecord,
    schedule_id: str,
    scheduled_for: datetime,
) -> GrowthContentSchedule:
    decision = await _access(session, actor)
    original = await _schedule(session, actor, schedule_id)
    content = await session.get(GrowthContentItem, original.content_id)
    if content is None:
        raise GrowthContentError("content-not-found")
    when = (
        scheduled_for
        if scheduled_for.tzinfo
        else scheduled_for.replace(tzinfo=timezone.utc)
    )
    row = GrowthContentSchedule(
        organization_id=actor.organization_id,
        content_id=original.content_id,
        variant_id=original.variant_id,
        account_id=original.account_id,
        provider=original.provider,
        scheduled_for=when,
        timezone=original.timezone,
        recurrence="none",
        priority=original.priority,
        status="queued",
        approval_required=bool(decision.approval_required),
        attempt_count=0,
        recycle_of_schedule_id=original.id,
        version=1,
    )
    if row.approval_required and content.approval_status != "approved":
        raise GrowthContentError("approval-required")
    session.add(row)
    content.recycle_count += 1
    content.status = "scheduled"
    content.version += 1
    await session.flush()
    _audit(
        session,
        actor,
        "growth.content.recycled",
        "growth_content_schedule",
        row.id,
        {"source_schedule_id": original.id},
    )
    await session.flush()
    return row


async def cancel_schedule(
    session: AsyncSession, actor: UserRecord, schedule_id: str
) -> GrowthContentSchedule:
    row = await _schedule(session, actor, schedule_id)
    if row.status != "queued":
        raise GrowthContentError("only-queued-schedule-can-cancel")
    row.status = "cancelled"
    row.cancelled_at = _utcnow()
    row.version += 1
    _audit(
        session,
        actor,
        "growth.content.schedule_cancelled",
        "growth_content_schedule",
        row.id,
    )
    await session.flush()
    return row


async def queue_snapshot(
    session: AsyncSession, actor: UserRecord
) -> list[dict[str, Any]]:
    await _access(session, actor)
    rows = (
        await session.scalars(
            select(GrowthContentSchedule)
            .where(GrowthContentSchedule.organization_id == actor.organization_id)
            .order_by(
                desc(GrowthContentSchedule.priority),
                GrowthContentSchedule.scheduled_for,
            )
            .limit(500)
        )
    ).all()
    return [_public_schedule(row) for row in rows]


async def item_with_variants(
    session: AsyncSession, actor: UserRecord, content_id: str
) -> dict[str, Any]:
    item = await _item(session, actor, content_id)
    variants = (
        await session.scalars(
            select(GrowthContentVariant)
            .where(
                GrowthContentVariant.organization_id == actor.organization_id,
                GrowthContentVariant.content_id == item.id,
            )
            .order_by(GrowthContentVariant.provider, GrowthContentVariant.created_at)
        )
    ).all()
    return {
        "item": _public_item(item),
        "variants": [_public_variant(row) for row in variants],
        "live_publish_allowed": False,
    }
