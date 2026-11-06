"""P3 posts: drafts, scheduling, publish-now, cancel and the calendar.

Tenancy: every read and write is scoped to the caller's organization and own
user id, and a post can only target accounts the caller connected through the
P3 OAuth flow (``connected_via == "oauth"``). Simulated GS-03/GS-04 accounts
can never be published to.

A post has one ``SocialPostTarget`` per account. Scheduling or publishing
validates every target against the platform rules first; the
``social_publish_worker`` then performs the real Graph calls. A post is
reported ``published`` only when every non-canceled target holds a Graph id.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    GrowthSocialAccount,
    SocialPost,
    SocialPostAttempt,
    SocialPostTarget,
)
from app.services import social_media_access as media_access
from app.services import social_publishing_rules as rules
from app.services.social_connections import CONNECTED_VIA
from app.services.social_connectors import SocialConnectorError

POST_STATUSES = (
    "draft",
    "scheduled",
    "publishing",
    "published",
    "partially_failed",
    "failed",
    "canceled",
)
TARGET_STATUSES = ("pending", "publishing", "retry_wait", "published", "failed", "canceled")
OPEN_TARGET_STATUSES = frozenset({"pending", "publishing", "retry_wait"})
EDITABLE_STATUSES = frozenset({"draft", "scheduled"})
DELETABLE_STATUSES = frozenset({"draft", "canceled"})
PUBLISHABLE_PROVIDERS = frozenset(rules.PROVIDERS)
MAX_TARGETS = 20
CAPTION_MAX = rules.FB_TEXT_MAX
SCHEDULE_MIN_LEAD = timedelta(minutes=1)
SCHEDULE_MAX_AHEAD = timedelta(days=180)
CALENDAR_MAX_RANGE = timedelta(days=100)
DEFAULT_RETRY_POLICY = {"max_attempts": 3, "backoff_seconds": 60}
_TIMEZONE_RE = re.compile(r"^(?:UTC|[A-Za-z]+(?:[/_+-][A-Za-z0-9_+-]+){0,3})$")
_KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,80}$")


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _audit(
    session: AsyncSession,
    actor_org: str,
    actor_user: str,
    action: str,
    resource_id: str,
    details: dict[str, Any],
    *,
    resource_type: str = "social_post",
) -> None:
    session.add(
        AuditEvent(
            organization_id=actor_org,
            user_id=actor_user,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details={"publishing": "p3", **details},
        )
    )


def target_idempotency_key(post_id: str, account_id: str) -> str:
    """Stable per (post, account): one target can never be created twice."""

    return hashlib.sha256(f"social-post-target:v1:{post_id}:{account_id}".encode()).hexdigest()


# --- input normalization -------------------------------------------------------------


def normalize_timezone(value: str | None) -> str:
    name = (value or "UTC").strip() or "UTC"
    if len(name) > 64 or not _TIMEZONE_RE.fullmatch(name):
        raise SocialConnectorError("timezone-invalid", status_code=422)
    return name


def resolve_schedule(
    scheduled_at: datetime, timezone_name: str, *, now: datetime | None = None
) -> datetime:
    """Return the UTC instant. A naive time is read in ``timezone_name``."""

    current = now or _now()
    if scheduled_at.tzinfo is None:
        try:
            zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            # Without a tz database the offset cannot be derived safely.
            raise SocialConnectorError("scheduled-at-needs-offset", status_code=422) from None
        scheduled_at = scheduled_at.replace(tzinfo=zone)
    instant = scheduled_at.astimezone(UTC)
    if instant < current + SCHEDULE_MIN_LEAD:
        raise SocialConnectorError("scheduled-at-in-past", status_code=422)
    if instant > current + SCHEDULE_MAX_AHEAD:
        raise SocialConnectorError("scheduled-at-too-far", status_code=422)
    return instant


def normalize_retry_policy(value: dict[str, Any] | None) -> dict[str, int]:
    policy = dict(DEFAULT_RETRY_POLICY)
    for key, low, high in (("max_attempts", 1, 5), ("backoff_seconds", 30, 3600)):
        if value and key in value:
            raw = value[key]
            if type(raw) is not int or not low <= raw <= high:
                raise SocialConnectorError(f"retry-policy-{key.replace('_', '-')}-invalid", status_code=422)
            policy[key] = raw
    return policy


def backoff_delay(policy: dict[str, Any], attempt: int) -> timedelta:
    base = int(policy.get("backoff_seconds") or DEFAULT_RETRY_POLICY["backoff_seconds"])
    return timedelta(seconds=min(base * (2 ** max(0, attempt - 1)), 3600))


def _normalize_overrides(raw: dict[str, Any] | None) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for key, value in (raw or {}).items():
        if key == "caption":
            if value is None:
                continue
            if not isinstance(value, str) or len(value) > CAPTION_MAX:
                raise SocialConnectorError("override-caption-invalid", status_code=422)
            overrides["caption"] = value
        elif key == "share_to_feed":
            if not isinstance(value, bool):
                raise SocialConnectorError("override-share-to-feed-invalid", status_code=422)
            overrides["share_to_feed"] = value
        else:
            raise SocialConnectorError("override-field-unsupported", status_code=422)
    return overrides


# --- serialization (allow-lists; never tokens) ---------------------------------------


def public_target(row: SocialPostTarget) -> dict[str, Any]:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "provider": row.provider,
        "account_name": row.account_name,
        "overrides": dict(row.overrides or {}),
        "status": row.status,
        "attempts": row.attempts,
        "max_attempts": row.max_attempts,
        "next_attempt_at": row.next_attempt_at,
        "remote_post_id": row.remote_post_id,
        "permalink": row.permalink,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "published_at": row.published_at,
        "last_attempt_at": row.last_attempt_at,
    }


def public_attempt(row: SocialPostAttempt) -> dict[str, Any]:
    return {
        "attempt_number": row.attempt_number,
        "outcome": row.outcome,
        "transient": row.transient,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "remote_post_id": row.remote_post_id,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


def public_post(post: SocialPost, targets: list[SocialPostTarget]) -> dict[str, Any]:
    return {
        "id": post.id,
        "status": post.status,
        "post_type": post.post_type,
        "caption": post.caption,
        "link_url": post.link_url,
        "media": list(post.media or []),
        "scheduled_at": post.scheduled_at,
        "timezone": post.timezone,
        "retry_policy": dict(post.retry_policy or {}),
        "published_at": post.published_at,
        "canceled_at": post.canceled_at,
        "created_at": post.created_at,
        "updated_at": post.updated_at,
        "targets": [public_target(row) for row in targets],
    }


def aggregate_status(post: SocialPost, statuses: list[str]) -> str:
    if not statuses:
        return post.status
    live = [status for status in statuses if status != "canceled"]
    if not live:
        return "canceled"
    if any(status in OPEN_TARGET_STATUSES for status in live):
        if post.status == "scheduled" and all(status == "pending" for status in live):
            return "scheduled"
        if post.status == "draft":
            return "draft"
        return "publishing"
    published = sum(1 for status in live if status == "published")
    if published == len(live):
        return "published"
    return "partially_failed" if published else "failed"


# --- loading ---------------------------------------------------------------------------


async def own_post(
    session: AsyncSession, actor: UserRecord, post_id: str, *, lock: bool = False
) -> SocialPost:
    statement = select(SocialPost).where(
        SocialPost.id == post_id,
        SocialPost.organization_id == actor.organization_id,
        SocialPost.user_id == actor.id,
    )
    if lock:
        statement = statement.with_for_update()
    row = await session.scalar(statement)
    if row is None:
        raise SocialConnectorError("post-not-found", status_code=404)
    return row


async def post_targets(
    session: AsyncSession, post_id: str, *, lock: bool = False
) -> list[SocialPostTarget]:
    statement = (
        select(SocialPostTarget)
        .where(SocialPostTarget.post_id == post_id)
        .order_by(SocialPostTarget.provider, SocialPostTarget.account_name, SocialPostTarget.id)
    )
    if lock:
        statement = statement.with_for_update()
    return list((await session.scalars(statement)).all())


async def _own_accounts(
    session: AsyncSession, actor: UserRecord, account_ids: list[str]
) -> list[GrowthSocialAccount]:
    wanted = list(dict.fromkeys(item.strip() for item in account_ids if item and item.strip()))
    if not wanted:
        raise SocialConnectorError("targets-required", status_code=422)
    if len(wanted) > MAX_TARGETS:
        raise SocialConnectorError("too-many-targets", status_code=422)
    rows = (
        await session.scalars(
            select(GrowthSocialAccount).where(
                GrowthSocialAccount.id.in_(wanted),
                GrowthSocialAccount.organization_id == actor.organization_id,
                GrowthSocialAccount.created_by_id == actor.id,
                GrowthSocialAccount.connected_via == CONNECTED_VIA,
                GrowthSocialAccount.status.in_(("active", "expired")),
            )
        )
    ).all()
    by_id = {row.id: row for row in rows}
    if any(item not in by_id for item in wanted):
        # Another member's, another tenant's or a simulated account: indistinguishable.
        raise SocialConnectorError("target-account-not-found", status_code=422)
    for row in rows:
        if row.provider not in PUBLISHABLE_PROVIDERS:
            raise SocialConnectorError("target-provider-not-supported", status_code=422)
    return [by_id[item] for item in wanted]


# --- validation ------------------------------------------------------------------------


def target_content(
    post: SocialPost, target_provider: str, overrides: dict[str, Any], media: list[rules.MediaInfo]
) -> rules.TargetContent:
    caption = overrides.get("caption")
    return rules.TargetContent(
        provider=target_provider,
        post_type=post.post_type,
        caption=caption if isinstance(caption, str) else (post.caption or ""),
        link_url=post.link_url,
        media=media,
        share_to_feed=bool(overrides.get("share_to_feed", True)),
    )


async def validate_post(
    session: AsyncSession, actor: UserRecord, post: SocialPost, targets: list[SocialPostTarget]
) -> dict[str, Any]:
    resolved = await media_access.resolve_media(
        session,
        organization_id=actor.organization_id,
        user_id=actor.id,
        refs=[str(item.get("ref")) for item in post.media or [] if isinstance(item, dict)],
    )
    infos = [item.info for item in resolved]
    results = []
    for target in targets:
        if target.status == "canceled":
            continue
        issues = rules.validate_target(
            target_content(post, target.provider, dict(target.overrides or {}), infos)
        )
        results.append(
            {"target_id": target.id, "account_id": target.account_id, "provider": target.provider, "issues": issues}
        )
    return {
        "valid": not any(rules.has_errors(item["issues"]) for item in results),
        "targets": results,
        "media": [
            {
                "ref": item.ref,
                "kind": item.kind,
                "media_type": item.media_type,
                "size_bytes": item.size_bytes,
                "width": item.width,
                "height": item.height,
                "duration_ms": item.duration_ms,
            }
            for item in infos
        ],
    }


async def preview_post(
    session: AsyncSession, actor: UserRecord, data: dict[str, Any]
) -> dict[str, Any]:
    """Validate unsaved composer content per target; nothing is persisted."""

    post = SocialPost(organization_id=actor.organization_id, user_id=actor.id, status="draft")
    _apply_content(post, data)
    accounts = await _own_accounts(session, actor, list(data.get("account_ids") or []))
    raw_overrides = data.get("overrides") or {}
    targets = [
        SocialPostTarget(
            account_id=account.id,
            provider=account.provider,
            account_name=account.display_name,
            overrides=_normalize_overrides(
                raw_overrides.get(account.id) if isinstance(raw_overrides, dict) else None
            ),
            status="pending",
        )
        for account in accounts
    ]
    report = await validate_post(session, actor, post, targets)
    report["rules"] = rules.public_rules()
    return report


# --- writes ----------------------------------------------------------------------------


def _apply_content(post: SocialPost, data: dict[str, Any]) -> None:
    post_type = str(data.get("post_type") or "")
    if post_type not in rules.POST_TYPES:
        raise SocialConnectorError("post-type-unsupported", status_code=422)
    caption = data.get("caption") or ""
    if not isinstance(caption, str) or len(caption) > CAPTION_MAX:
        raise SocialConnectorError("caption-invalid", status_code=422)
    link = data.get("link_url") or None
    if link is not None and not rules.valid_link(str(link)):
        raise SocialConnectorError("link-invalid", status_code=422)
    refs = [str(item) for item in data.get("media") or []]
    if len(refs) > media_access.MAX_MEDIA_PER_POST:
        raise SocialConnectorError("too-many-media-items", status_code=422)
    for ref in refs:
        if not media_access.REF_RE.fullmatch(ref):
            raise SocialConnectorError("media-reference-invalid", status_code=422)
    post.post_type = post_type
    post.caption = caption
    post.link_url = str(link) if link else None
    post.media = [{"ref": ref} for ref in dict.fromkeys(refs)]
    post.timezone = normalize_timezone(data.get("timezone"))
    post.retry_policy = normalize_retry_policy(data.get("retry_policy"))


async def _replace_targets(
    session: AsyncSession,
    actor: UserRecord,
    post: SocialPost,
    data: dict[str, Any],
) -> list[SocialPostTarget]:
    accounts = await _own_accounts(session, actor, list(data.get("account_ids") or []))
    raw_overrides = data.get("overrides") or {}
    if not isinstance(raw_overrides, dict) or any(key not in {a.id for a in accounts} for key in raw_overrides):
        raise SocialConnectorError("override-account-not-targeted", status_code=422)
    await session.execute(delete(SocialPostTarget).where(SocialPostTarget.post_id == post.id))
    await session.flush()
    max_attempts = int(post.retry_policy.get("max_attempts") or DEFAULT_RETRY_POLICY["max_attempts"])
    targets = []
    for account in accounts:
        row = SocialPostTarget(
            post_id=post.id,
            organization_id=actor.organization_id,
            user_id=actor.id,
            account_id=account.id,
            provider=account.provider,
            account_name=account.display_name[:240],
            overrides=_normalize_overrides(raw_overrides.get(account.id)),
            status="pending",
            idempotency_key=target_idempotency_key(post.id, account.id),
            attempts=0,
            max_attempts=max_attempts,
            version=1,
        )
        session.add(row)
        targets.append(row)
    await session.flush()
    return targets


async def create_draft(
    session: AsyncSession, actor: UserRecord, data: dict[str, Any]
) -> dict[str, Any]:
    key = data.get("client_idempotency_key")
    if key is not None:
        if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
            raise SocialConnectorError("idempotency-key-invalid", status_code=422)
        existing = await session.scalar(
            select(SocialPost).where(
                SocialPost.user_id == actor.id,
                SocialPost.organization_id == actor.organization_id,
                SocialPost.client_idempotency_key == key,
            )
        )
        if existing is not None:
            return public_post(existing, await post_targets(session, existing.id))
    post = SocialPost(
        organization_id=actor.organization_id,
        user_id=actor.id,
        status="draft",
        client_idempotency_key=key,
        version=1,
    )
    _apply_content(post, data)
    session.add(post)
    await session.flush()
    targets = await _replace_targets(session, actor, post, data)
    _audit(
        session,
        actor.organization_id,
        actor.id,
        "social.post.created",
        post.id,
        {"post_type": post.post_type, "targets": len(targets)},
    )
    await session.flush()
    return public_post(post, targets)


async def update_post(
    session: AsyncSession, actor: UserRecord, post_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    post = await own_post(session, actor, post_id, lock=True)
    if post.status not in EDITABLE_STATUSES:
        raise SocialConnectorError("post-not-editable", status_code=409)
    _apply_content(post, data)
    targets = await _replace_targets(session, actor, post, data)
    if post.status == "scheduled":
        # A scheduled post stays scheduled only while it is still publishable.
        report = await validate_post(session, actor, post, targets)
        if not report["valid"]:
            raise SocialConnectorError("post-validation-failed", status_code=422)
        for target in targets:
            target.next_attempt_at = post.scheduled_at
    post.version += 1
    _audit(
        session,
        actor.organization_id,
        actor.id,
        "social.post.updated",
        post.id,
        {"post_type": post.post_type, "targets": len(targets), "status": post.status},
    )
    await session.flush()
    return public_post(post, targets)


async def delete_post(session: AsyncSession, actor: UserRecord, post_id: str) -> dict[str, Any]:
    post = await own_post(session, actor, post_id, lock=True)
    if post.status not in DELETABLE_STATUSES:
        raise SocialConnectorError("post-not-deletable", status_code=409)
    _audit(session, actor.organization_id, actor.id, "social.post.deleted", post.id, {"status": post.status})
    await session.delete(post)
    await session.flush()
    return {"id": post_id, "deleted": True}


async def _arm(
    session: AsyncSession,
    actor: UserRecord,
    post: SocialPost,
    *,
    due: datetime,
    status: str,
) -> dict[str, Any]:
    targets = await post_targets(session, post.id, lock=True)
    if not targets:
        raise SocialConnectorError("targets-required", status_code=422)
    report = await validate_post(session, actor, post, targets)
    if not report["valid"]:
        raise SocialConnectorError("post-validation-failed", status_code=422)
    for target in targets:
        target.status = "pending"
        target.next_attempt_at = due
        target.error_code = None
        target.error_message = None
        target.version += 1
    post.status = status
    post.scheduled_at = due
    post.version += 1
    return public_post(post, targets)


async def schedule_post(
    session: AsyncSession,
    actor: UserRecord,
    post_id: str,
    *,
    scheduled_at: datetime,
    timezone_name: str | None,
) -> dict[str, Any]:
    post = await own_post(session, actor, post_id, lock=True)
    if post.status not in EDITABLE_STATUSES:
        raise SocialConnectorError("post-not-schedulable", status_code=409)
    post.timezone = normalize_timezone(timezone_name or post.timezone)
    due = resolve_schedule(scheduled_at, post.timezone)
    result = await _arm(session, actor, post, due=due, status="scheduled")
    _audit(
        session,
        actor.organization_id,
        actor.id,
        "social.post.scheduled",
        post.id,
        {"scheduled_at": due.isoformat(), "timezone": post.timezone},
    )
    await session.flush()
    return result


async def publish_now(session: AsyncSession, actor: UserRecord, post_id: str) -> dict[str, Any]:
    post = await own_post(session, actor, post_id, lock=True)
    if post.status not in EDITABLE_STATUSES:
        raise SocialConnectorError("post-not-publishable", status_code=409)
    result = await _arm(session, actor, post, due=_now(), status="publishing")
    _audit(
        session,
        actor.organization_id,
        actor.id,
        "social.post.publish_requested",
        post.id,
        {"targets": len(result["targets"])},
    )
    await session.flush()
    return result


async def cancel_post(session: AsyncSession, actor: UserRecord, post_id: str) -> dict[str, Any]:
    post = await own_post(session, actor, post_id, lock=True)
    if post.status not in {"scheduled", "publishing"}:
        raise SocialConnectorError("post-not-cancelable", status_code=409)
    targets = await post_targets(session, post.id, lock=True)
    now = _now()
    canceled = 0
    in_flight = 0
    for target in targets:
        leased = target.lease_expires_at is not None and (_aware(target.lease_expires_at) or now) > now
        if target.status in {"pending", "retry_wait"} and not leased and target.dispatch_started_at is None:
            target.status = "canceled"
            target.next_attempt_at = None
            target.version += 1
            canceled += 1
        elif target.status in OPEN_TARGET_STATUSES:
            in_flight += 1
    post.status = aggregate_status(post, [target.status for target in targets])
    if post.status == "canceled":
        post.canceled_at = now
    post.version += 1
    _audit(
        session,
        actor.organization_id,
        actor.id,
        "social.post.canceled",
        post.id,
        {"targets_canceled": canceled, "targets_in_flight": in_flight},
    )
    await session.flush()
    return public_post(post, targets)


# --- reads -----------------------------------------------------------------------------


async def get_post(session: AsyncSession, actor: UserRecord, post_id: str) -> dict[str, Any]:
    post = await own_post(session, actor, post_id)
    targets = await post_targets(session, post.id)
    payload = public_post(post, targets)
    if targets:
        attempts = (
            await session.scalars(
                select(SocialPostAttempt)
                .where(SocialPostAttempt.target_id.in_([row.id for row in targets]))
                .order_by(SocialPostAttempt.target_id, SocialPostAttempt.attempt_number)
            )
        ).all()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for attempt in attempts:
            grouped.setdefault(attempt.target_id, []).append(public_attempt(attempt))
        for item in payload["targets"]:
            item["attempt_log"] = grouped.get(item["id"], [])
    return payload


async def list_posts(
    session: AsyncSession,
    actor: UserRecord,
    *,
    start: datetime | None,
    end: datetime | None,
    status: str | None = None,
) -> dict[str, Any]:
    statement = select(SocialPost).where(
        SocialPost.organization_id == actor.organization_id,
        SocialPost.user_id == actor.id,
    )
    if status is not None:
        if status not in POST_STATUSES:
            raise SocialConnectorError("status-invalid", status_code=422)
        statement = statement.where(SocialPost.status == status)
    if start is not None or end is not None:
        if start is None or end is None:
            raise SocialConnectorError("range-incomplete", status_code=422)
        start, end = _aware(start), _aware(end)
        if start is None or end is None or end <= start or end - start > CALENDAR_MAX_RANGE:
            raise SocialConnectorError("range-invalid", status_code=422)
        statement = statement.where(
            or_(
                (SocialPost.scheduled_at >= start) & (SocialPost.scheduled_at < end),
                (SocialPost.published_at >= start) & (SocialPost.published_at < end),
            )
        )
        statement = statement.order_by(SocialPost.scheduled_at.asc(), SocialPost.id)
    else:
        statement = statement.order_by(SocialPost.updated_at.desc(), SocialPost.id)
    posts = list((await session.scalars(statement.limit(500))).all())
    targets_by_post: dict[str, list[SocialPostTarget]] = {post.id: [] for post in posts}
    if posts:
        rows = (
            await session.scalars(
                select(SocialPostTarget)
                .where(SocialPostTarget.post_id.in_(list(targets_by_post)))
                .order_by(SocialPostTarget.provider, SocialPostTarget.account_name)
            )
        ).all()
        for row in rows:
            targets_by_post[row.post_id].append(row)
    return {"items": [public_post(post, targets_by_post[post.id]) for post in posts]}
