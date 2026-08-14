from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    GrowthInboxMessage,
    GrowthInboxNote,
    GrowthInboxThread,
    GrowthLeadRecord,
    GrowthQuickReplyDraft,
    Organization,
    User,
)
from app.services import growth_unified_inbox as inbox


def _actor(org_id: str, user_id: str, email: str) -> UserRecord:
    return UserRecord(
        id=user_id,
        email=email,
        name="GS07 Test User",
        role="User",
        password_hash="unused",
        organization_id=org_id,
        organization_name="GS07 Test",
        organization_plan="test",
        permissions=[],
        status="active",
        auth_version=1,
    )


async def _cleanup(session, org_id: str, user_ids: list[str]) -> None:
    thread_ids = list(
        (
            await session.scalars(
                select(GrowthInboxThread.id).where(
                    GrowthInboxThread.organization_id == org_id
                )
            )
        ).all()
    )
    if thread_ids:
        await session.execute(
            delete(GrowthQuickReplyDraft).where(
                GrowthQuickReplyDraft.thread_id.in_(thread_ids)
            )
        )
        await session.execute(
            delete(GrowthInboxNote).where(GrowthInboxNote.thread_id.in_(thread_ids))
        )
        await session.execute(
            delete(GrowthInboxMessage).where(
                GrowthInboxMessage.thread_id.in_(thread_ids)
            )
        )
        await session.execute(
            delete(GrowthInboxThread).where(GrowthInboxThread.id.in_(thread_ids))
        )
    await session.execute(
        delete(GrowthLeadRecord).where(GrowthLeadRecord.organization_id == org_id)
    )
    await session.execute(
        delete(AuditEvent).where(AuditEvent.organization_id == org_id)
    )
    await session.execute(delete(User).where(User.id.in_(user_ids)))
    await session.execute(delete(Organization).where(Organization.id == org_id))
    await session.commit()


@pytest.mark.asyncio
async def test_simulated_inbound_and_workflow(monkeypatch) -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs07-org-{suffix}"
    user_id = f"gs07-user-{suffix}"
    agent_id = f"gs07-agent-{suffix}"
    actor = _actor(org_id, user_id, f"gs07-{suffix}@example.invalid")

    async def allow(_session, _actor, _capability):
        return SimpleNamespace(allowed=True, reason="test-owner-grant")

    monkeypatch.setattr(inbox, "effective_access", allow)
    async with SessionLocal() as session:
        try:
            session.add(
                Organization(
                    id=org_id,
                    name="GS07 Test",
                    slug=f"gs07-{suffix}",
                    plan="test",
                    status="active",
                )
            )
            session.add_all(
                [
                    User(
                        id=user_id,
                        organization_id=org_id,
                        email=actor.email,
                        name="GS07 Test User",
                        password_hash="unused",
                        status="active",
                        auth_version=1,
                    ),
                    User(
                        id=agent_id,
                        organization_id=org_id,
                        email=f"agent-{suffix}@example.invalid",
                        name="GS07 Agent",
                        password_hash="unused",
                        status="active",
                        auth_version=1,
                    ),
                ]
            )
            await session.commit()

            payload = {
                "provider": "instagram",
                "external_thread_ref": "thread-1",
                "external_message_ref": "msg-1",
                "thread_type": "dm",
                "body": "Great service, thank you!",
                "participant_ref": "p-1",
                "participant_name": "Client",
            }
            thread, message, created = await inbox.ingest_simulated_event(
                session, actor, payload
            )
            assert created is True
            assert thread.unread_count == 1
            assert thread.sentiment == "positive"
            assert message.direction == "inbound" and message.simulated is True

            thread2, message2, created2 = await inbox.ingest_simulated_event(
                session, actor, payload
            )
            assert created2 is False
            assert thread2.id == thread.id and message2.id == message.id
            assert thread2.unread_count == 1

            await inbox.set_starred(session, actor, thread.id, True)
            await inbox.mark_read(session, actor, thread.id, True)
            await inbox.assign_thread(session, actor, thread.id, agent_id)
            note = await inbox.add_note(session, actor, thread.id, "Internal follow-up")
            draft = await inbox.create_quick_reply_draft(
                session,
                actor,
                thread.id,
                body="Thanks for your message. We are reviewing it.",
                template_key="ack",
                ai_suggested=True,
            )
            assert note.body == "Internal follow-up"
            assert draft.external_send_allowed is False
            assert draft.approval_required is True
            assert draft.ai_suggested is True
            await session.commit()

            public = inbox.public_thread(thread)
            assert public["live_provider_call"] is False
            assert public["external_send_allowed"] is False
            assert public["live_block_allowed"] is False
            assert public["live_mute_allowed"] is False
            assert public["live_moderation_allowed"] is False
        finally:
            await session.rollback()
            await _cleanup(session, org_id, [user_id, agent_id])


@pytest.mark.asyncio
async def test_spam_crm_link_search_and_status(monkeypatch) -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs07-org-{suffix}"
    user_id = f"gs07-user-{suffix}"
    actor = _actor(org_id, user_id, f"gs07-{suffix}@example.invalid")

    async def allow(_session, _actor, _capability):
        return SimpleNamespace(allowed=True, reason="test-owner-grant")

    monkeypatch.setattr(inbox, "effective_access", allow)
    async with SessionLocal() as session:
        try:
            session.add(
                Organization(
                    id=org_id,
                    name="GS07 CRM Test",
                    slug=f"gs07-crm-{suffix}",
                    plan="test",
                    status="active",
                )
            )
            session.add(
                User(
                    id=user_id,
                    organization_id=org_id,
                    email=actor.email,
                    name="GS07 Test User",
                    password_hash="unused",
                    status="active",
                    auth_version=1,
                )
            )
            await session.commit()

            lead = GrowthLeadRecord(
                organization_id=org_id,
                created_by_id=user_id,
                display_name="Alice",
                email_normalized=f"alice-{suffix}@example.invalid",
                company_name="Example",
                dedupe_fingerprint=(suffix * 8)[:64],
                status="active",
                retention_until=datetime.now(timezone.utc) + timedelta(days=30),
                attributes={},
            )
            session.add(lead)
            await session.flush()

            thread, _, _ = await inbox.ingest_simulated_event(
                session,
                actor,
                {
                    "provider": "linkedin",
                    "external_thread_ref": "crm-thread",
                    "external_message_ref": "crm-msg",
                    "thread_type": "mention",
                    "body": "BAD service! click here for free money",
                    "participant_name": "Alice",
                },
            )
            assert thread.sentiment == "negative"
            assert thread.spam_score >= 0.5
            assert "spam:suspected" in thread.tags

            linked = await inbox.link_lead(session, actor, thread.id, lead.id)
            assert linked.lead_id == lead.id
            rows = await inbox.list_threads(
                session, actor, provider="linkedin", query="Alice"
            )
            assert [row.id for row in rows] == [thread.id]
            resolved = await inbox.close_thread(session, actor, thread.id, "resolved")
            assert resolved.status == "resolved"
            await session.commit()
        finally:
            await session.rollback()
            await _cleanup(session, org_id, [user_id])


def test_safety_constants_and_classification_are_deterministic() -> None:
    assert inbox.LIVE_PROVIDER_CALL_ALLOWED is False
    assert inbox.EXTERNAL_SEND_ALLOWED is False
    assert inbox.LIVE_BLOCK_ALLOWED is False
    assert inbox.LIVE_MUTE_ALLOWED is False
    assert inbox.LIVE_MODERATION_ALLOWED is False
    first = inbox.classify_text("excellent thank you")
    second = inbox.classify_text("excellent thank you")
    assert first == second
    assert first.sentiment == "positive"
