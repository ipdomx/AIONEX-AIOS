"""P3 unified inbox: Facebook Page comments, Messenger, Instagram comments and DMs.

Store: ``ingest_items`` writes normalized Meta changes (from the signed
webhook or the poll fallback) into ``social_inbox_conversations`` and
``social_inbox_messages``. Inserts use ``ON CONFLICT DO NOTHING`` on the Meta
id per account, so any number of redeliveries store one message and count it
unread once. A change is stored only for OAuth-connected, non-revoked
accounts whose provider id matches; each conversation belongs to the account
owner.

Tenancy: every read and action is scoped to the caller's organization *and*
the caller's own accounts (``user_id`` of the conversation), exactly like
the connector and publishing services.

Actions go to the Graph API through ``MetaInboxClient``: reply to a comment,
hide or unhide a comment, and reply to a Messenger or Instagram DM. A DM
reply is refused outside Meta's 24-hour standard messaging window (measured
from the customer's last message); nothing is sent with a message tag.
Success is recorded only with the id Graph returned. The AI suggestion uses
``social_ai_assist.suggest_reply`` with the shared plan quota and never sends.

The reused vocabulary (``comment``/``dm`` threads, sentiment) comes from the
GS-07 simulation inbox (``growth_unified_inbox``), whose tables stay
simulation-only.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import ACTIVE_USER_STATUSES, UserRecord
from app.core.config import settings
from app.db.models import (
    AuditEvent,
    GrowthSocialAccount,
    SocialInboxConversation,
    SocialInboxMessage,
    User,
)
from app.services import social_connectors as framework
from app.services import social_meta_webhooks as webhooks
from app.services.growth_unified_inbox import classify_text
from app.services.social_connections import CONNECTED_VIA
from app.services.social_connectors import SocialConnectorError
from app.services.social_meta_inbox import REPLY_MAX, InboxItem, MetaInboxClient
from app.services.social_meta_publisher import GraphPublishError

MESSAGING_WINDOW = timedelta(hours=24)
PROVIDERS = ("facebook", "instagram")
CHANNELS = ("comment", "dm")
STATUSES = ("open", "pending", "closed")
LIST_LIMIT = 100
THREAD_MESSAGES = 200
PREVIEW_MAX = 280
# Permissions each inbox capability needs (Meta App Review names).
REQUIRED_SCOPES: dict[str, tuple[str, ...]] = {
    "facebook": (
        "pages_messaging",
        "pages_read_engagement",
        "pages_read_user_content",
        "pages_manage_engagement",
        "pages_manage_metadata",
    ),
    "instagram": (
        "instagram_basic",
        "instagram_manage_comments",
        "instagram_manage_messages",
        "pages_manage_metadata",
    ),
}
_ACCOUNT_LIVE_STATUSES = ("active", "paused", "expired", "error")
# Graph permission errors: #10 (permission denied) and #200-#299 (missing permission).
_PERMISSION_ERROR_RE = re.compile(r"-error-(?:10|2\d\d)(?:-|$)")


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _preview(text: str) -> str:
    return " ".join(text.split())[:PREVIEW_MAX]


def _audit(
    session: AsyncSession,
    actor: UserRecord,
    action: str,
    resource_id: str,
    details: dict[str, Any],
) -> None:
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action=action,
            resource_type="social_inbox_conversation",
            resource_id=resource_id,
            details={"inbox": "p3", **details},
        )
    )


# --- public shapes (allow-lists; no token or ciphertext) ---------------------------


def reply_window(row: SocialInboxConversation, *, now: datetime | None = None) -> dict[str, Any]:
    if row.channel != "dm":
        return {"applies": False, "open": True, "expires_at": None}
    last = _aware(row.last_inbound_at)
    if last is None:
        return {"applies": True, "open": False, "expires_at": None}
    expires = last + MESSAGING_WINDOW
    return {"applies": True, "open": (now or _now()) < expires, "expires_at": expires}


def public_conversation(
    row: SocialInboxConversation, account: GrowthSocialAccount | None
) -> dict[str, Any]:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "account_name": account.display_name if account else None,
        "account_handle": account.public_handle if account else None,
        "account_status": account.status if account else "revoked",
        "provider": row.provider,
        "channel": row.channel,
        "object_ref": row.object_ref,
        "participant_ref": row.participant_ref,
        "participant_name": row.participant_name,
        "status": row.status,
        "unread_count": row.unread_count,
        "assigned_to_id": row.assigned_to_id,
        "last_message_at": row.last_message_at,
        "last_inbound_at": row.last_inbound_at,
        "last_message_preview": row.last_message_preview,
        "sentiment": row.sentiment,
        "tags": list(row.tags or []),
        "reply_window": reply_window(row),
        "version": row.version,
    }


def public_message(row: SocialInboxMessage) -> dict[str, Any]:
    return {
        "id": row.id,
        "external_message_ref": row.external_message_ref,
        "parent_ref": row.parent_ref,
        "direction": row.direction,
        "kind": row.kind,
        "author_name": row.author_name,
        "body": "" if row.removed else row.body,
        "attachments": list(row.attachments or []),
        "hidden": row.hidden,
        "removed": row.removed,
        "source": row.source,
        "sent_by_id": row.sent_by_id,
        "sent_at": row.sent_at,
    }


# --- ingestion -----------------------------------------------------------------------


async def matching_accounts(
    session: AsyncSession, provider: str, external_id: str
) -> list[GrowthSocialAccount]:
    return list(
        (
            await session.scalars(
                select(GrowthSocialAccount).where(
                    GrowthSocialAccount.provider == provider,
                    GrowthSocialAccount.external_account_id == external_id,
                    GrowthSocialAccount.connected_via == CONNECTED_VIA,
                    GrowthSocialAccount.status.in_(_ACCOUNT_LIVE_STATUSES),
                    GrowthSocialAccount.token_ciphertext.is_not(None),
                )
            )
        ).all()
    )


async def _conversation_for(
    session: AsyncSession, account: GrowthSocialAccount, item: InboxItem
) -> SocialInboxConversation:
    await session.execute(
        pg_insert(SocialInboxConversation)
        .values(
            organization_id=account.organization_id,
            user_id=account.created_by_id,
            account_id=account.id,
            provider=account.provider,
            channel=item.channel,
            external_thread_ref=item.thread_ref,
            object_ref=item.object_ref,
            participant_ref=item.participant_ref,
            participant_name=item.participant_name,
            status="open",
            unread_count=0,
            last_message_preview="",
            sentiment="neutral",
            tags=[],
            version=1,
        )
        .on_conflict_do_nothing(constraint="uq_social_inbox_conversations_thread")
    )
    row = await session.scalar(
        select(SocialInboxConversation)
        .where(
            SocialInboxConversation.account_id == account.id,
            SocialInboxConversation.external_thread_ref == item.thread_ref,
        )
        .with_for_update()
    )
    if row is None:  # pragma: no cover - the insert above guarantees a row
        raise SocialConnectorError("inbox-conversation-missing", status_code=500)
    return row


async def apply_item(
    session: AsyncSession,
    account: GrowthSocialAccount,
    item: InboxItem,
    *,
    source: str,
) -> bool:
    """Store one change for one account. Returns True when something changed."""

    if item.action in {"remove", "hide", "unhide", "edited"}:
        existing = await session.scalar(
            select(SocialInboxMessage)
            .where(
                SocialInboxMessage.account_id == account.id,
                SocialInboxMessage.external_message_ref == item.message_ref,
            )
            .with_for_update()
        )
        if existing is not None:
            if item.action == "remove":
                existing.removed = True
                existing.body = ""
            elif item.action in {"hide", "unhide"}:
                existing.hidden = item.action == "hide"
            elif item.body:
                existing.body = item.body
            return True
        if item.action != "edited":
            return False

    conversation = await _conversation_for(session, account, item)
    inserted = await session.scalar(
        pg_insert(SocialInboxMessage)
        .values(
            conversation_id=conversation.id,
            organization_id=account.organization_id,
            account_id=account.id,
            external_message_ref=item.message_ref,
            parent_ref=item.parent_ref,
            direction=item.direction,
            kind=item.channel if item.direction == "inbound" else "reply",
            author_ref=item.author_ref,
            author_name=item.author_name,
            body=item.body,
            attachments=[dict(entry) for entry in item.attachments],
            hidden=False,
            removed=False,
            source=source,
            sent_at=item.sent_at,
        )
        .on_conflict_do_nothing(constraint="uq_social_inbox_messages_external")
        .returning(SocialInboxMessage.id)
    )
    if inserted is None:
        return False
    sent_at = _aware(item.sent_at) or _now()
    newest = _aware(conversation.last_message_at)
    if newest is None or sent_at >= newest:
        conversation.last_message_at = sent_at
        conversation.last_message_preview = _preview(item.body) or (
            "[attachment]" if item.attachments else ""
        )
    if item.direction == "inbound":
        conversation.unread_count += 1
        last_in = _aware(conversation.last_inbound_at)
        if last_in is None or sent_at > last_in:
            conversation.last_inbound_at = sent_at
        if conversation.status == "closed":
            conversation.status = "open"
        if item.body:
            classification = classify_text(item.body)
            conversation.sentiment = classification.sentiment
            conversation.tags = classification.tags
        if item.participant_name and not conversation.participant_name:
            conversation.participant_name = item.participant_name
        if item.participant_ref and not conversation.participant_ref:
            conversation.participant_ref = item.participant_ref
    conversation.version += 1
    return True


async def ingest_items(
    session: AsyncSession,
    items: list[InboxItem],
    *,
    source: str,
    account: GrowthSocialAccount | None = None,
) -> tuple[int, int]:
    """Apply changes; returns (matched account count, stored change count)."""

    matched = 0
    stored = 0
    cache: dict[tuple[str, str], list[GrowthSocialAccount]] = {}
    for item in items:
        if account is not None:
            targets = (
                [account]
                if (account.provider, account.external_account_id)
                == (item.provider, item.account_external_id)
                else []
            )
        else:
            key = (item.provider, item.account_external_id)
            if key not in cache:
                cache[key] = await matching_accounts(session, *key)
            targets = cache[key]
        matched += len(targets)
        for target in targets:
            if await apply_item(session, target, item, source=source):
                stored += 1
    await session.flush()
    return matched, stored


# --- reads ---------------------------------------------------------------------------


async def _own_accounts(session: AsyncSession, actor: UserRecord) -> dict[str, GrowthSocialAccount]:
    rows = (
        await session.scalars(
            select(GrowthSocialAccount).where(
                GrowthSocialAccount.organization_id == actor.organization_id,
                GrowthSocialAccount.created_by_id == actor.id,
                GrowthSocialAccount.connected_via == CONNECTED_VIA,
                GrowthSocialAccount.provider.in_(PROVIDERS),
            )
        )
    ).all()
    return {row.id: row for row in rows}


async def _own_conversation(
    session: AsyncSession, actor: UserRecord, conversation_id: str, *, lock: bool = False
) -> SocialInboxConversation:
    query = select(SocialInboxConversation).where(
        SocialInboxConversation.id == conversation_id,
        SocialInboxConversation.organization_id == actor.organization_id,
        SocialInboxConversation.user_id == actor.id,
    )
    if lock:
        query = query.with_for_update()
    row = await session.scalar(query)
    if row is None:
        raise SocialConnectorError("conversation-not-found", status_code=404)
    return row


async def list_conversations(
    session: AsyncSession,
    actor: UserRecord,
    *,
    platform: str | None = None,
    channel: str | None = None,
    unread: bool | None = None,
    status: str | None = None,
    before: datetime | None = None,
) -> dict[str, Any]:
    if platform and platform not in PROVIDERS:
        raise SocialConnectorError("platform-invalid", status_code=422)
    if channel and channel not in CHANNELS:
        raise SocialConnectorError("channel-invalid", status_code=422)
    if status and status not in STATUSES:
        raise SocialConnectorError("status-invalid", status_code=422)
    accounts = await _own_accounts(session, actor)
    query = select(SocialInboxConversation).where(
        SocialInboxConversation.organization_id == actor.organization_id,
        SocialInboxConversation.user_id == actor.id,
    )
    if platform:
        query = query.where(SocialInboxConversation.provider == platform)
    if channel:
        query = query.where(SocialInboxConversation.channel == channel)
    if unread is True:
        query = query.where(SocialInboxConversation.unread_count > 0)
    elif unread is False:
        query = query.where(SocialInboxConversation.unread_count == 0)
    if status:
        query = query.where(SocialInboxConversation.status == status)
    if before is not None:
        query = query.where(SocialInboxConversation.last_message_at < before)
    rows = (
        await session.scalars(
            query.order_by(
                SocialInboxConversation.last_message_at.desc().nulls_last(),
                SocialInboxConversation.id,
            ).limit(LIST_LIMIT)
        )
    ).all()
    unread_total = await session.scalar(
        select(func.count(SocialInboxConversation.id)).where(
            SocialInboxConversation.organization_id == actor.organization_id,
            SocialInboxConversation.user_id == actor.id,
            SocialInboxConversation.unread_count > 0,
        )
    )
    return {
        "items": [public_conversation(row, accounts.get(row.account_id)) for row in rows],
        "unread_conversations": int(unread_total or 0),
        "has_more": len(rows) == LIST_LIMIT,
    }


async def get_conversation(
    session: AsyncSession, actor: UserRecord, conversation_id: str
) -> dict[str, Any]:
    row = await _own_conversation(session, actor, conversation_id)
    accounts = await _own_accounts(session, actor)
    messages = (
        await session.scalars(
            select(SocialInboxMessage)
            .where(SocialInboxMessage.conversation_id == row.id)
            .order_by(SocialInboxMessage.sent_at.desc(), SocialInboxMessage.id)
            .limit(THREAD_MESSAGES)
        )
    ).all()
    return {
        **public_conversation(row, accounts.get(row.account_id)),
        "messages": [public_message(item) for item in reversed(messages)],
    }


async def update_conversation(
    session: AsyncSession,
    actor: UserRecord,
    conversation_id: str,
    *,
    read: bool | None = None,
    status: str | None = None,
    assigned_to_id: str | None = None,
    unassign: bool = False,
) -> dict[str, Any]:
    row = await _own_conversation(session, actor, conversation_id, lock=True)
    changes: dict[str, Any] = {}
    if read is True and row.unread_count:
        row.unread_count = 0
        changes["read"] = True
    elif read is False and row.unread_count == 0:
        row.unread_count = 1
        changes["read"] = False
    if status is not None:
        if status not in STATUSES:
            raise SocialConnectorError("status-invalid", status_code=422)
        if status != row.status:
            row.status = status
            changes["status"] = status
    if unassign:
        if row.assigned_to_id is not None:
            row.assigned_to_id = None
            changes["assigned"] = None
    elif assigned_to_id is not None and assigned_to_id != row.assigned_to_id:
        member = await session.scalar(
            select(User.id).where(
                User.id == assigned_to_id,
                User.organization_id == actor.organization_id,
                User.status.in_(ACTIVE_USER_STATUSES),
            )
        )
        if member is None:
            raise SocialConnectorError("assignee-not-found", status_code=422)
        row.assigned_to_id = assigned_to_id
        changes["assigned"] = "member"
    if changes:
        row.version += 1
        _audit(session, actor, "social.inbox.updated", row.id, {"changes": changes})
    await session.flush()
    return await get_conversation(session, actor, row.id)


# --- actions -------------------------------------------------------------------------


async def _action_account(
    session: AsyncSession, actor: UserRecord, row: SocialInboxConversation
) -> tuple[GrowthSocialAccount, str]:
    account = await session.scalar(
        select(GrowthSocialAccount).where(
            GrowthSocialAccount.id == row.account_id,
            GrowthSocialAccount.organization_id == actor.organization_id,
            GrowthSocialAccount.created_by_id == actor.id,
            GrowthSocialAccount.connected_via == CONNECTED_VIA,
        )
    )
    if account is None or account.status == "revoked" or not account.token_ciphertext:
        raise SocialConnectorError("account-disconnected", status_code=409)
    if account.status == "expired":
        raise SocialConnectorError("account-reconnect-required", status_code=409)
    return account, framework.open_token(account.token_ciphertext)


def _graph_failure(exc: GraphPublishError) -> SocialConnectorError:
    if exc.token_expired:
        return SocialConnectorError("account-reconnect-required", status_code=409)
    if exc.code == "provider-not-configured":
        return SocialConnectorError("provider-not-configured", status_code=409)
    if exc.ambiguous:
        return SocialConnectorError("reply-outcome-unknown", status_code=502)
    if _PERMISSION_ERROR_RE.search(exc.code):
        # The app or the Page lacks the permission (App Review or Page role).
        return SocialConnectorError("meta-permission-required", status_code=403)
    return SocialConnectorError("meta-action-failed", status_code=502)


def _mark_expired(account: GrowthSocialAccount) -> None:
    account.status = "expired"
    account.health_state = "invalid"
    account.health_reasons = ["account-reconnect-required"]
    account.version += 1


async def reply(
    session: AsyncSession,
    actor: UserRecord,
    conversation_id: str,
    text: str,
    *,
    client: MetaInboxClient | None = None,
) -> dict[str, Any]:
    body = (text or "").strip()
    if not body:
        raise SocialConnectorError("reply-text-required", status_code=422)
    if len(body) > REPLY_MAX:
        raise SocialConnectorError("reply-too-long", status_code=422)
    row = await _own_conversation(session, actor, conversation_id, lock=True)
    window = reply_window(row)
    if window["applies"] and not window["open"]:
        raise SocialConnectorError("messaging-window-closed", status_code=409)
    account, token = await _action_account(session, actor, row)
    graph = client or MetaInboxClient()
    root = row.external_thread_ref.split(":", 1)[1]
    try:
        if row.channel == "comment":
            remote = await graph.reply_to_comment(
                provider=row.provider, comment_id=root, token=token, text=body
            )
        else:
            page_id = account.external_account_id
            if row.provider == "instagram":
                page_id = str((account.provider_metadata or {}).get("linked_external_id") or "")
            remote = await graph.send_message(
                page_id=page_id, token=token, recipient_id=root, text=body
            )
    except GraphPublishError as exc:
        if exc.token_expired:
            _mark_expired(account)
        _audit(
            session,
            actor,
            "social.inbox.reply_failed",
            row.id,
            {"provider": row.provider, "channel": row.channel, "code": exc.code},
        )
        await session.commit()
        raise _graph_failure(exc) from exc
    now = _now()
    session.add(
        SocialInboxMessage(
            conversation_id=row.id,
            organization_id=row.organization_id,
            account_id=account.id,
            external_message_ref=remote,
            parent_ref=root,
            direction="outbound",
            kind="reply",
            author_ref=account.external_account_id,
            author_name=account.display_name,
            body=body,
            attachments=[],
            hidden=False,
            removed=False,
            source="reply",
            sent_by_id=actor.id,
            sent_at=now,
        )
    )
    row.last_message_at = now
    row.last_message_preview = _preview(body)
    row.unread_count = 0
    if row.status == "open":
        row.status = "pending"
    row.version += 1
    _audit(
        session,
        actor,
        "social.inbox.replied",
        row.id,
        {"provider": row.provider, "channel": row.channel, "remote_id": remote},
    )
    await session.flush()
    return await get_conversation(session, actor, row.id)


async def set_message_hidden(
    session: AsyncSession,
    actor: UserRecord,
    message_id: str,
    hidden: bool,
    *,
    client: MetaInboxClient | None = None,
) -> dict[str, Any]:
    message = await session.scalar(
        select(SocialInboxMessage)
        .join(
            SocialInboxConversation,
            SocialInboxConversation.id == SocialInboxMessage.conversation_id,
        )
        .where(
            SocialInboxMessage.id == message_id,
            SocialInboxConversation.organization_id == actor.organization_id,
            SocialInboxConversation.user_id == actor.id,
        )
        .with_for_update()
    )
    if message is None:
        raise SocialConnectorError("message-not-found", status_code=404)
    row = await _own_conversation(session, actor, message.conversation_id, lock=True)
    if row.channel != "comment" or message.direction != "inbound" or message.removed:
        raise SocialConnectorError("message-not-moderatable", status_code=409)
    account, token = await _action_account(session, actor, row)
    graph = client or MetaInboxClient()
    try:
        ok = await graph.set_comment_hidden(
            provider=row.provider,
            comment_id=message.external_message_ref,
            token=token,
            hidden=hidden,
        )
    except GraphPublishError as exc:
        if exc.token_expired:
            _mark_expired(account)
            await session.commit()
        raise _graph_failure(exc) from exc
    if not ok:
        raise SocialConnectorError("meta-action-failed", status_code=502)
    message.hidden = hidden
    row.version += 1
    _audit(
        session,
        actor,
        "social.inbox.comment_hidden" if hidden else "social.inbox.comment_unhidden",
        row.id,
        {"provider": row.provider, "message_id": message.id},
    )
    await session.flush()
    return await get_conversation(session, actor, row.id)


async def suggestion_context(
    session: AsyncSession, actor: UserRecord, conversation_id: str
) -> tuple[SocialInboxConversation, list[tuple[str, str]]]:
    row = await _own_conversation(session, actor, conversation_id)
    messages = (
        await session.scalars(
            select(SocialInboxMessage)
            .where(
                SocialInboxMessage.conversation_id == row.id,
                SocialInboxMessage.removed.is_(False),
            )
            .order_by(SocialInboxMessage.sent_at.desc())
            .limit(12)
        )
    ).all()
    history = [(item.direction, item.body) for item in reversed(messages) if item.body]
    if not any(direction == "inbound" for direction, _body in history):
        raise SocialConnectorError("ai-nothing-to-answer", status_code=422)
    return row, history


# --- readiness and webhook subscription ---------------------------------------------


def account_readiness(account: GrowthSocialAccount) -> dict[str, Any]:
    granted = set(account.scopes or [])
    missing = [scope for scope in REQUIRED_SCOPES.get(account.provider, ()) if scope not in granted]
    metadata = dict(account.provider_metadata or {})
    if account.status == "revoked" or not account.token_ciphertext:
        state = "disconnected"
    elif account.status == "expired":
        state = "reconnect_required"
    elif missing:
        state = "awaiting_permission"
    else:
        state = "ready"
    return {
        "account_id": account.id,
        "provider": account.provider,
        "display_name": account.display_name,
        "handle": account.public_handle,
        "state": state,
        "missing_scopes": missing,
        "webhook_subscribed_at": metadata.get("inbox_subscribed_at"),
    }


async def readiness(session: AsyncSession, actor: UserRecord) -> dict[str, Any]:
    accounts = [
        row
        for row in (await _own_accounts(session, actor)).values()
        if row.status in _ACCOUNT_LIVE_STATUSES
    ]
    meta_status = framework.get_connector("meta").status()
    base = str(settings.SOCIAL_MEDIA_PUBLIC_BASE_URL or "").rstrip("/")
    return {
        "meta_app_configured": meta_status.configured,
        "webhook_configured": webhooks.webhook_configured(),
        "webhook_url": f"{base}/api/v1/social/meta/webhooks",
        "poll_enabled": bool(settings.SOCIAL_INBOX_POLL_ENABLED),
        "poll_seconds": int(settings.SOCIAL_INBOX_POLL_SECONDS),
        "messaging_window_hours": int(MESSAGING_WINDOW.total_seconds() // 3600),
        # Honest state: live delivery with real accounts is verified before launch.
        "live_verified": False,
        "accounts": sorted(
            (account_readiness(row) for row in accounts),
            key=lambda item: (item["provider"], item["display_name"]),
        ),
    }


async def subscribe_account(
    session: AsyncSession,
    actor: UserRecord,
    account_id: str,
    *,
    client: MetaInboxClient | None = None,
) -> dict[str, Any]:
    account = (await _own_accounts(session, actor)).get(account_id)
    if account is None:
        raise SocialConnectorError("account-not-found", status_code=404)
    if account.status == "revoked" or not account.token_ciphertext:
        raise SocialConnectorError("account-disconnected", status_code=409)
    page_id = account.external_account_id
    if account.provider == "instagram":
        page_id = str((account.provider_metadata or {}).get("linked_external_id") or "")
    token = framework.open_token(account.token_ciphertext)
    try:
        ok = await (client or MetaInboxClient()).subscribe_page(page_id=page_id, token=token)
    except GraphPublishError as exc:
        if exc.token_expired:
            _mark_expired(account)
            await session.commit()
        raise _graph_failure(exc) from exc
    if not ok:
        raise SocialConnectorError("meta-action-failed", status_code=502)
    metadata = dict(account.provider_metadata or {})
    metadata["inbox_subscribed_at"] = _now().isoformat()
    account.provider_metadata = metadata
    account.version += 1
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="social.inbox.webhooks_subscribed",
            resource_type="growth_social_account",
            resource_id=account.id,
            details={"inbox": "p3", "provider": account.provider},
        )
    )
    await session.flush()
    return account_readiness(account)


async def delete_account_inbox(session: AsyncSession, account_ids: list[str]) -> int:
    """Delete every stored conversation (and, by cascade, message) of these accounts."""

    if not account_ids:
        return 0
    rows = (
        await session.scalars(
            select(SocialInboxConversation).where(
                SocialInboxConversation.account_id.in_(account_ids)
            )
        )
    ).all()
    for row in rows:
        await session.delete(row)
    await session.flush()
    return len(rows)
