from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    GrowthInboxMessage,
    GrowthInboxNote,
    GrowthInboxThread,
    GrowthLeadRecord,
    GrowthQuickReplyDraft,
    User,
)
from app.services.growth_access import effective_access

LIVE_PROVIDER_CALL_ALLOWED = False
EXTERNAL_SEND_ALLOWED = False
LIVE_BLOCK_ALLOWED = False
LIVE_MUTE_ALLOWED = False
LIVE_MODERATION_ALLOWED = False

THREAD_TYPES = {"comment", "dm", "mention", "review", "reply"}
MESSAGE_TYPES = {"text", "comment", "dm", "mention", "review", "reply"}
SENTIMENTS = {"positive", "neutral", "negative"}


class GrowthInboxError(RuntimeError): ...


@dataclass(frozen=True)
class Classification:
    sentiment: str
    spam_score: float
    tags: list[str]


def classify_text(text: str) -> Classification:
    lowered = text.lower()
    positive = ("thank", "great", "love", "excellent", "شكرا", "رائع", "ممتاز")
    negative = ("bad", "hate", "angry", "refund", "سيء", "غاضب", "استرجاع")
    spam = (
        "buy now",
        "free money",
        "crypto profit",
        "click here",
        "ربح مضمون",
        "اضغط هنا",
    )
    pos = sum(token in lowered for token in positive)
    neg = sum(token in lowered for token in negative)
    sentiment = "positive" if pos > neg else "negative" if neg > pos else "neutral"
    spam_hits = sum(token in lowered for token in spam)
    spam_score = min(1.0, round(0.35 * spam_hits, 3))
    tags = [f"sentiment:{sentiment}"]
    if spam_score >= 0.5:
        tags.append("spam:suspected")
    return Classification(sentiment, spam_score, tags)


async def _require(session: AsyncSession, actor: UserRecord) -> None:
    decision = await effective_access(session, actor, "inbox.manage")
    if not decision.allowed:
        raise GrowthInboxError(f"access-denied:{decision.reason}")


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
            details={
                "live_provider_call": False,
                "external_send_allowed": False,
                "live_block_allowed": False,
                "live_mute_allowed": False,
                "live_moderation_allowed": False,
                **dict(details or {}),
            },
        )
    )


async def ingest_simulated_event(
    session: AsyncSession,
    actor: UserRecord,
    payload: dict[str, Any],
) -> tuple[GrowthInboxThread, GrowthInboxMessage, bool]:
    await _require(session, actor)
    provider = str(payload.get("provider") or "").strip().lower()
    thread_ref = str(payload.get("external_thread_ref") or "").strip()
    message_ref = str(payload.get("external_message_ref") or "").strip()
    thread_type = str(payload.get("thread_type") or "").strip().lower()
    message_type = str(payload.get("message_type") or thread_type).strip().lower()
    body = str(payload.get("body") or "").strip()
    account_id = payload.get("account_id")
    if not provider or not thread_ref or not message_ref or not body:
        raise GrowthInboxError("provider-thread-message-body-required")
    if thread_type not in THREAD_TYPES or message_type not in MESSAGE_TYPES:
        raise GrowthInboxError("unsupported-inbox-event-type")
    existing = await session.scalar(
        select(GrowthInboxThread).where(
            GrowthInboxThread.organization_id == actor.organization_id,
            GrowthInboxThread.provider == provider,
            GrowthInboxThread.account_id == account_id,
            GrowthInboxThread.external_thread_ref == thread_ref,
        )
    )
    created = False
    classification = classify_text(body)
    if existing is None:
        existing = GrowthInboxThread(
            organization_id=actor.organization_id,
            account_id=account_id,
            provider=provider,
            external_thread_ref=thread_ref[:240],
            thread_type=thread_type,
            participant_ref=(str(payload.get("participant_ref") or "").strip() or None),
            participant_name=(
                str(payload.get("participant_name") or "").strip() or None
            ),
            status="open",
            unread_count=0,
            starred=False,
            sentiment=classification.sentiment,
            spam_score=classification.spam_score,
            tags=list(classification.tags),
            metadata_json={"simulated": True},
        )
        session.add(existing)
        await session.flush()
        created = True
    duplicate = await session.scalar(
        select(GrowthInboxMessage).where(
            GrowthInboxMessage.thread_id == existing.id,
            GrowthInboxMessage.external_message_ref == message_ref,
        )
    )
    if duplicate is not None:
        return existing, duplicate, False
    message = GrowthInboxMessage(
        organization_id=actor.organization_id,
        thread_id=existing.id,
        external_message_ref=message_ref[:240],
        direction="inbound",
        message_type=message_type,
        author_ref=(
            str(
                payload.get("author_ref") or payload.get("participant_ref") or ""
            ).strip()
            or None
        ),
        body=body,
        attachments=list(payload.get("attachments") or []),
        sentiment=classification.sentiment,
        spam_score=classification.spam_score,
        provider_event={"provider": provider, "simulated": True},
        simulated=True,
    )
    session.add(message)
    existing.unread_count += 1
    existing.sentiment = classification.sentiment
    existing.spam_score = max(existing.spam_score, classification.spam_score)
    existing.tags = sorted(set(list(existing.tags or []) + classification.tags))
    await session.flush()
    _audit(
        session,
        actor,
        "growth.inbox.simulated_event_ingested",
        "growth_inbox_thread",
        existing.id,
        {"provider": provider, "thread_type": thread_type},
    )
    return existing, message, created


async def get_thread(
    session: AsyncSession, actor: UserRecord, thread_id: str
) -> GrowthInboxThread:
    await _require(session, actor)
    row = await session.scalar(
        select(GrowthInboxThread).where(
            GrowthInboxThread.id == thread_id,
            GrowthInboxThread.organization_id == actor.organization_id,
        )
    )
    if row is None:
        raise GrowthInboxError("thread-not-found")
    return row


async def list_threads(
    session: AsyncSession,
    actor: UserRecord,
    *,
    status: str | None = None,
    provider: str | None = None,
    query: str | None = None,
    starred: bool | None = None,
    limit: int = 100,
) -> list[GrowthInboxThread]:
    await _require(session, actor)
    stmt = select(GrowthInboxThread).where(
        GrowthInboxThread.organization_id == actor.organization_id
    )
    if status:
        stmt = stmt.where(GrowthInboxThread.status == status)
    if provider:
        stmt = stmt.where(GrowthInboxThread.provider == provider.lower())
    if starred is not None:
        stmt = stmt.where(GrowthInboxThread.starred == starred)
    if query:
        pattern = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                GrowthInboxThread.participant_name.ilike(pattern),
                GrowthInboxThread.external_thread_ref.ilike(pattern),
            )
        )
    stmt = stmt.order_by(GrowthInboxThread.updated_at.desc()).limit(
        max(1, min(limit, 200))
    )
    return list((await session.scalars(stmt)).all())


async def list_messages(
    session: AsyncSession, actor: UserRecord, thread_id: str
) -> list[GrowthInboxMessage]:
    thread = await get_thread(session, actor, thread_id)
    return list(
        (
            await session.scalars(
                select(GrowthInboxMessage)
                .where(GrowthInboxMessage.thread_id == thread.id)
                .order_by(GrowthInboxMessage.created_at.asc())
            )
        ).all()
    )


async def mark_read(
    session: AsyncSession, actor: UserRecord, thread_id: str, read: bool = True
) -> GrowthInboxThread:
    thread = await get_thread(session, actor, thread_id)
    thread.unread_count = 0 if read else max(1, thread.unread_count)
    _audit(
        session,
        actor,
        "growth.inbox.read_state_changed",
        "growth_inbox_thread",
        thread.id,
        {"read": read},
    )
    await session.flush()
    return thread


async def set_starred(
    session: AsyncSession, actor: UserRecord, thread_id: str, starred: bool
) -> GrowthInboxThread:
    thread = await get_thread(session, actor, thread_id)
    thread.starred = bool(starred)
    _audit(
        session,
        actor,
        "growth.inbox.star_changed",
        "growth_inbox_thread",
        thread.id,
        {"starred": starred},
    )
    await session.flush()
    return thread


async def assign_thread(
    session: AsyncSession, actor: UserRecord, thread_id: str, assignee_id: str | None
) -> GrowthInboxThread:
    thread = await get_thread(session, actor, thread_id)
    if assignee_id:
        assignee = await session.scalar(
            select(User).where(
                User.id == assignee_id,
                User.organization_id == actor.organization_id,
                User.status == "active",
            )
        )
        if assignee is None:
            raise GrowthInboxError("assignee-not-found")
    thread.assigned_to_id = assignee_id
    _audit(
        session,
        actor,
        "growth.inbox.assignment_changed",
        "growth_inbox_thread",
        thread.id,
        {"assignee_id": assignee_id},
    )
    await session.flush()
    return thread


async def link_lead(
    session: AsyncSession, actor: UserRecord, thread_id: str, lead_id: str | None
) -> GrowthInboxThread:
    thread = await get_thread(session, actor, thread_id)
    if lead_id:
        lead = await session.scalar(
            select(GrowthLeadRecord).where(
                GrowthLeadRecord.id == lead_id,
                GrowthLeadRecord.organization_id == actor.organization_id,
            )
        )
        if lead is None:
            raise GrowthInboxError("lead-not-found")
    thread.lead_id = lead_id
    _audit(
        session,
        actor,
        "growth.inbox.lead_link_changed",
        "growth_inbox_thread",
        thread.id,
        {"lead_id": lead_id},
    )
    await session.flush()
    return thread


async def add_note(
    session: AsyncSession, actor: UserRecord, thread_id: str, body: str
) -> GrowthInboxNote:
    thread = await get_thread(session, actor, thread_id)
    clean = body.strip()
    if not clean:
        raise GrowthInboxError("note-body-required")
    row = GrowthInboxNote(
        organization_id=actor.organization_id,
        thread_id=thread.id,
        author_id=actor.id,
        body=clean,
    )
    session.add(row)
    await session.flush()
    _audit(
        session,
        actor,
        "growth.inbox.note_added",
        "growth_inbox_thread",
        thread.id,
        {"note_id": row.id},
    )
    return row


async def create_quick_reply_draft(
    session: AsyncSession,
    actor: UserRecord,
    thread_id: str,
    *,
    body: str,
    template_key: str | None = None,
    ai_suggested: bool = False,
) -> GrowthQuickReplyDraft:
    thread = await get_thread(session, actor, thread_id)
    clean = body.strip()
    if not clean:
        raise GrowthInboxError("reply-body-required")
    row = GrowthQuickReplyDraft(
        organization_id=actor.organization_id,
        thread_id=thread.id,
        created_by_id=actor.id,
        template_key=template_key,
        body=clean,
        status="draft",
        ai_suggested=bool(ai_suggested),
        approval_required=True,
        external_send_allowed=False,
    )
    session.add(row)
    await session.flush()
    _audit(
        session,
        actor,
        "growth.inbox.quick_reply_drafted",
        "growth_quick_reply_draft",
        row.id,
        {"thread_id": thread.id, "ai_suggested": bool(ai_suggested)},
    )
    return row


async def close_thread(
    session: AsyncSession, actor: UserRecord, thread_id: str, status: str
) -> GrowthInboxThread:
    if status not in {"open", "pending", "resolved"}:
        raise GrowthInboxError("unsupported-thread-status")
    thread = await get_thread(session, actor, thread_id)
    thread.status = status
    _audit(
        session,
        actor,
        "growth.inbox.status_changed",
        "growth_inbox_thread",
        thread.id,
        {"status": status},
    )
    await session.flush()
    return thread


def public_thread(row: GrowthInboxThread) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "account_id": row.account_id,
        "lead_id": row.lead_id,
        "thread_type": row.thread_type,
        "participant_ref": row.participant_ref,
        "participant_name": row.participant_name,
        "status": row.status,
        "unread_count": row.unread_count,
        "starred": row.starred,
        "assigned_to_id": row.assigned_to_id,
        "sentiment": row.sentiment,
        "spam_score": row.spam_score,
        "tags": list(row.tags or []),
        "live_provider_call": False,
        "external_send_allowed": False,
        "live_block_allowed": False,
        "live_mute_allowed": False,
        "live_moderation_allowed": False,
    }


def public_message(row: GrowthInboxMessage) -> dict[str, Any]:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "direction": row.direction,
        "message_type": row.message_type,
        "body": row.body,
        "attachments": list(row.attachments or []),
        "sentiment": row.sentiment,
        "spam_score": row.spam_score,
        "simulated": row.simulated,
        "external_send_allowed": False,
        "live_provider_call": False,
    }


def public_quick_reply(row: GrowthQuickReplyDraft) -> dict[str, Any]:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "template_key": row.template_key,
        "body": row.body,
        "status": row.status,
        "ai_suggested": row.ai_suggested,
        "approval_required": True,
        "external_send_allowed": False,
        "live_provider_call": False,
    }
