"""Phase 29E durable communications, meetings, approvals, and governance contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.api.v1.router import api_router
from app.core.auth import UserRecord, current_user, pwd_context
from app.db.base import SessionLocal
from app.db.models import (
    ApprovalDecision,
    ApprovalRequest,
    AuditEvent,
    CommunicationEndpoint,
    GovernanceBody,
    GovernanceDecision,
    GovernanceMembership,
    GovernancePolicy,
    GovernanceVote,
    Meeting,
    MeetingAttendance,
    MeetingMinutes,
    Notification,
    NotificationDelivery,
    NotificationDeliveryAttempt,
    NotificationPreference,
    Organization,
    Role,
    SupportMessage,
    SupportRequest,
    User,
)
from app.services import communications, governance


class Identity:
    def __init__(self, organization: Organization, users: dict[str, User]):
        self.organization = organization
        self.users = users

    def actor(self, name: str, permissions: list[str]) -> UserRecord:
        user = self.users[name]
        return UserRecord(
            id=user.id,
            email=user.email,
            name=user.name,
            role=name,
            password_hash=user.password_hash,
            organization_id=self.organization.id,
            organization_name=self.organization.name,
            organization_plan=self.organization.plan,
            permissions=permissions,
        )


async def identity(suffix: str) -> Identity:
    organization = Organization(
        name=f"Phase 29E {suffix}",
        slug=f"phase29e-{suffix}",
        plan="enterprise",
        status="active",
    )
    async with SessionLocal() as session:
        session.add(organization)
        await session.flush()
        users: dict[str, User] = {}
        for index, role_name in enumerate(
            ("Super Owner", "Owner", "Manager", "Member"), start=1
        ):
            role = Role(
                organization_id=organization.id,
                name=role_name,
                status="active",
            )
            session.add(role)
            await session.flush()
            user = User(
                organization_id=organization.id,
                role_id=role.id,
                email=f"phase29e-{role_name.lower().replace(' ', '-')}-{suffix}@example.com",
                name=f"{role_name} {suffix}",
                password_hash=pwd_context.hash(f"Phase29E!{suffix}-{index}"),
                status="active",
            )
            session.add(user)
            users[role_name] = user
        await session.commit()
        return Identity(organization, users)


async def cleanup(*organization_ids: str) -> None:
    async with SessionLocal() as session:
        for organization_id in organization_ids:
            decision_ids = select(GovernanceDecision.id).where(
                GovernanceDecision.organization_id == organization_id
            )
            await session.execute(
                delete(GovernanceVote).where(
                    GovernanceVote.decision_id.in_(decision_ids)
                )
            )
            await session.execute(
                delete(Organization).where(Organization.id == organization_id)
            )
        await session.commit()


def app_with_actor(holder: dict[str, UserRecord]) -> FastAPI:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: holder["actor"]
    return app


def unconfigure_external_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(communications.settings, "SMTP_HOST", None)
    monkeypatch.setattr(communications.settings, "SMTP_USER", None)
    monkeypatch.setattr(communications.settings, "SMTP_PASSWORD", None)
    monkeypatch.setattr(communications.settings, "FIREBASE_PROJECT_ID", None)
    monkeypatch.setattr(
        communications.settings, "FIREBASE_ADMIN_CREDENTIALS_JSON", None
    )
    monkeypatch.setattr(
        communications.settings,
        "AIOS_TELEGRAM_BOT_TOKEN_FILE",
        "/tmp/aionex-phase29e-missing-telegram-token",
    )
    monkeypatch.setattr(communications.settings, "WHATSAPP_ACCESS_TOKEN", None)
    monkeypatch.setattr(communications.settings, "WHATSAPP_PHONE_NUMBER_ID", None)
    monkeypatch.setattr(communications.settings, "WHATSAPP_API_BASE", None)


@pytest.mark.asyncio
async def test_durable_notification_survives_unconfigured_external_providers_and_dedupes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    data = await identity(suffix)
    unconfigure_external_channels(monkeypatch)
    recipient = data.users["Manager"]
    try:
        async with SessionLocal() as session:
            notification = await communications.create_notification(
                session,
                recipient,
                event_key="phase29e.delivery.test",
                category="system",
                title="Durable notification",
                message="The in-app record must survive missing external providers.",
                severity="critical",
                channels=["in_app", "email", "push", "telegram", "whatsapp"],
                dedupe_key=f"phase29e-dedupe-{suffix}",
                actor_id=data.users["Owner"].id,
            )
            await session.commit()
            replay = await communications.create_notification(
                session,
                recipient,
                event_key="phase29e.delivery.test",
                category="system",
                title="Replay",
                message="Replay",
                severity="critical",
                channels=["in_app", "email"],
                dedupe_key=f"phase29e-dedupe-{suffix}",
            )
            await session.commit()
            assert replay.id == notification.id

            deliveries = list(
                (
                    await session.scalars(
                        select(NotificationDelivery).where(
                            NotificationDelivery.notification_id == notification.id
                        )
                    )
                ).all()
            )
            states = {item.channel: item.status for item in deliveries}
            assert states == {
                "in_app": "delivered",
                "email": "unconfigured",
                "push": "unconfigured",
                "telegram": "unconfigured",
                "whatsapp": "unconfigured",
            }
            assert (
                await session.scalar(
                    select(func.count(Notification.id)).where(
                        Notification.organization_id == data.organization.id,
                        Notification.dedupe_key == f"phase29e-dedupe-{suffix}",
                    )
                )
                == 1
            )
            endpoint = await session.scalar(
                select(CommunicationEndpoint).where(
                    CommunicationEndpoint.user_id == recipient.id,
                    CommunicationEndpoint.channel == "email",
                )
            )
            assert endpoint is not None
            assert endpoint.address_ciphertext != recipient.email
            assert recipient.email not in json.dumps(endpoint.endpoint_metadata)
            readiness = communications.channel_readiness()
            assert next(item for item in readiness if item["id"] == "in_app")[
                "ready"
            ] is True
            assert all(
                item["status"] == "unconfigured"
                for item in readiness
                if item["id"] != "in_app"
            )
            readiness_json = json.dumps(readiness).lower()
            assert "phase29e-token" not in readiness_json
            assert "bearer " not in readiness_json
            assert "authorization" not in readiness_json
    finally:
        await cleanup(data.organization.id)


@pytest.mark.asyncio
async def test_preferences_limit_channels_and_keep_in_app_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    data = await identity(suffix)
    unconfigure_external_channels(monkeypatch)
    actor = data.actor("Manager", ["notifications:read", "communications:read"])
    try:
        async with SessionLocal() as session:
            preference = await communications.update_preference(
                session,
                actor,
                category="project",
                enabled=True,
                channels=["in_app"],
                minimum_severity="warning",
                quiet_hours_start="22:00",
                quiet_hours_end="07:00",
                timezone="Asia/Dubai",
                digest_mode="immediate",
            )
            notification = await communications.create_notification(
                session,
                data.users["Manager"],
                event_key="project.completed",
                category="project",
                title="Project completed",
                message="The project is complete.",
                severity="info",
                channels=["in_app", "email", "push"],
            )
            await session.commit()
            assert preference.channels == ["in_app"]
            assert preference.minimum_severity == "warning"
            deliveries = list(
                (
                    await session.scalars(
                        select(NotificationDelivery).where(
                            NotificationDelivery.notification_id == notification.id
                        )
                    )
                ).all()
            )
            assert [(item.channel, item.status) for item in deliveries] == [
                ("in_app", "delivered")
            ]
            stored = await session.scalar(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == actor.id,
                    NotificationPreference.category == "project",
                )
            )
            assert stored is not None and stored.timezone == "Asia/Dubai"
    finally:
        await cleanup(data.organization.id)


@pytest.mark.asyncio
async def test_whatsapp_delivery_receipt_retry_dead_letter_and_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    data = await identity(suffix)
    monkeypatch.setattr(communications.settings, "WHATSAPP_ACCESS_TOKEN", "phase29e-token")
    monkeypatch.setattr(communications.settings, "WHATSAPP_PHONE_NUMBER_ID", "123456")
    monkeypatch.setattr(
        communications.settings, "WHATSAPP_API_BASE", "https://graph.example/v99.0"
    )
    actor = data.actor("Manager", ["notifications:read", "communications:read"])
    try:
        async with SessionLocal() as session:
            endpoint = await communications.register_endpoint(
                session,
                actor,
                channel="whatsapp",
                address="971501234567",
                label="Escalation",
                verified=True,
            )
            notification = await communications.create_notification(
                session,
                data.users["Manager"],
                event_key="incident.critical",
                category="incident",
                title="Critical incident",
                message="Escalation delivery test.",
                severity="critical",
                channels=["whatsapp"],
            )
            await session.commit()
            delivery = await session.scalar(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == notification.id,
                    NotificationDelivery.channel == "whatsapp",
                )
            )
            assert endpoint.verified_at is not None
            assert delivery is not None and delivery.status == "queued"
            delivery.max_attempts = 2
            await session.commit()

            failing = httpx.MockTransport(
                lambda request: httpx.Response(500, json={"error": "temporary"})
            )
            first = await communications.process_delivery(
                session, delivery.id, whatsapp_transport=failing
            )
            assert first.status == "retrying" and first.attempt_count == 1
            second = await communications.process_delivery(
                session, delivery.id, whatsapp_transport=failing
            )
            assert second.status == "dead_letter" and second.attempt_count == 2
            assert second.dead_lettered_at is not None

            await communications.retry_delivery(
                session, second, actor_id=data.users["Owner"].id
            )
            await session.commit()

            def success_handler(request: httpx.Request) -> httpx.Response:
                assert request.headers["Authorization"] == "Bearer phase29e-token"
                assert request.url.path.endswith("/123456/messages")
                assert b"phase29e-token" not in request.content
                return httpx.Response(
                    200, json={"messages": [{"id": f"wamid.{suffix}"}]}
                )

            recovered = await communications.process_delivery(
                session,
                delivery.id,
                whatsapp_transport=httpx.MockTransport(success_handler),
            )
            assert recovered.status == "delivered"
            assert recovered.provider_message_id == f"wamid.{suffix}"
            assert recovered.attempt_count == 3
            attempts = list(
                (
                    await session.scalars(
                        select(NotificationDeliveryAttempt)
                        .where(NotificationDeliveryAttempt.delivery_id == delivery.id)
                        .order_by(NotificationDeliveryAttempt.attempt_number)
                    )
                ).all()
            )
            assert [item.status for item in attempts] == [
                "failed",
                "failed",
                "delivered",
            ]
            serialized = json.dumps(
                {
                    "delivery": communications.delivery_snapshot(recovered),
                    "attempts": [item.response_metadata for item in attempts],
                }
            )
            assert "phase29e-token" not in serialized
            await communications.acknowledge_delivery(
                session, recovered, actor_id=actor.id
            )
            await session.commit()
            assert recovered.status == "acknowledged"
    finally:
        await cleanup(data.organization.id)


@pytest.mark.asyncio
async def test_support_conversation_is_durable_and_globally_visible_to_super_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    customer = await identity(f"customer-{suffix}")
    platform = await identity(f"platform-{suffix}")
    unconfigure_external_channels(monkeypatch)
    holder = {
        "actor": customer.actor(
            "Manager",
            ["support:read", "support:write", "notifications:read"],
        )
    }
    app = app_with_actor(holder)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/v1/support/requests",
                json={
                    "subject": "Phase 29E support request",
                    "message": "A durable support conversation is required for validation.",
                    "category": "technical",
                    "priority": "high",
                },
            )
            assert created.status_code == 201, created.text
            ticket_id = created.json()["id"]

            holder["actor"] = platform.actor("Super Owner", ["*"])
            owner_list = await client.get("/api/v1/owner/support/requests")
            assert owner_list.status_code == 200, owner_list.text
            assert ticket_id in {item["id"] for item in owner_list.json()}
            reply = await client.post(
                f"/api/v1/owner/support/requests/{ticket_id}/messages",
                json={
                    "message": "The request is being investigated.",
                    "visibility": "requester",
                },
            )
            assert reply.status_code == 201, reply.text
            resolved = await client.patch(
                f"/api/v1/owner/support/requests/{ticket_id}",
                json={"status": "resolved"},
            )
            assert resolved.status_code == 200, resolved.text
            assert resolved.json()["status"] == "resolved"

            holder["actor"] = customer.actor(
                "Manager",
                ["support:read", "support:write", "notifications:read"],
            )
            detail = await client.get(f"/api/v1/support/requests/{ticket_id}")
            assert detail.status_code == 200, detail.text
            assert [item["message"] for item in detail.json()["messages"]] == [
                "A durable support conversation is required for validation.",
                "The request is being investigated.",
            ]

        async with SessionLocal() as session:
            ticket = await session.get(SupportRequest, ticket_id)
            assert ticket is not None and ticket.resolved_at is not None
            assert (
                await session.scalar(
                    select(func.count(SupportMessage.id)).where(
                        SupportMessage.support_request_id == ticket_id
                    )
                )
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count(AuditEvent.id)).where(
                        AuditEvent.resource_type == "support_request",
                        AuditEvent.resource_id == ticket_id,
                    )
                )
                >= 3
            )
    finally:
        await cleanup(customer.organization.id, platform.organization.id)


@pytest.mark.asyncio
async def test_incident_acknowledgement_escalation_and_resolution_are_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    data = await identity(suffix)
    unconfigure_external_channels(monkeypatch)
    owner = data.actor("Super Owner", ["*"])
    try:
        async with SessionLocal() as session:
            incident, created_notifications = await communications.create_incident(
                session,
                organization_id=data.organization.id,
                actor_id=owner.id,
                title="Phase 29E critical incident",
                description="Durable incident lifecycle validation.",
                severity="critical",
                source="phase29e-test",
                details={"component": "communications"},
            )
            await session.commit()
            assert incident.status == "active"
            assert created_notifications

            await communications.acknowledge_incident(session, owner, incident)
            incident, escalated_notifications = await communications.escalate_incident(
                session, owner, incident
            )
            await communications.resolve_incident(session, owner, incident)
            await session.commit()
            assert incident.status == "resolved"
            assert incident.acknowledged_by_id == owner.id
            assert incident.resolved_by_id == owner.id
            assert incident.escalation_level == 1
            assert escalated_notifications
            audits = list(
                (
                    await session.scalars(
                        select(AuditEvent).where(
                            AuditEvent.resource_type == "incident",
                            AuditEvent.resource_id == incident.id,
                        )
                    )
                ).all()
            )
            assert {item.action for item in audits} >= {
                "incident.created",
                "incident.acknowledged",
                "incident.escalated",
                "incident.resolved",
            }
    finally:
        await cleanup(data.organization.id)


@pytest.mark.asyncio
async def test_meeting_approval_attendance_minutes_and_completion_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    data = await identity(suffix)
    unconfigure_external_channels(monkeypatch)
    holder = {
        "actor": data.actor(
            "Manager",
            [
                "meetings:read",
                "meetings:write",
                "approvals:read",
                "notifications:read",
            ],
        )
    }
    app = app_with_actor(holder)
    start = datetime.now(UTC) + timedelta(days=1)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/v1/meetings",
                json={
                    "title": "Phase 29E council meeting",
                    "description": "Validate the governed meeting lifecycle.",
                    "attendee_ids": [data.users["Member"].id],
                    "start_time": start.isoformat(),
                    "end_time": (start + timedelta(hours=1)).isoformat(),
                    "location": "AIONEX virtual room",
                    "meeting_type": "council",
                    "timezone": "Asia/Dubai",
                    "agenda": [{"title": "Approval and delivery evidence"}],
                },
            )
            assert created.status_code == 201, created.text
            meeting = created.json()
            assert meeting["status"] == "pending_approval"
            assert meeting["approval"]["status"] == "pending"
            meeting_id = meeting["id"]
            approval_id = meeting["approval"]["id"]
            assert len(meeting["attendance"]) == 2

            holder["actor"] = data.actor("Super Owner", ["*"])
            decision = await client.patch(
                f"/api/v1/owner/approvals/{approval_id}",
                json={"status": "approved", "reason": "Council meeting approved"},
            )
            assert decision.status_code == 200, decision.text
            assert decision.json()["status"] == "approved"

            holder["actor"] = data.actor(
                "Member", ["meetings:read", "notifications:read"]
            )
            response = await client.post(
                f"/api/v1/meetings/{meeting_id}/respond",
                json={"response_status": "accepted", "note": "Attending"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["response_status"] == "accepted"

            holder["actor"] = data.actor(
                "Manager", ["meetings:read", "meetings:write"]
            )
            minutes = await client.put(
                f"/api/v1/meetings/{meeting_id}/minutes",
                json={
                    "summary": "The meeting approved the Phase 29E evidence.",
                    "decisions": [{"decision": "continue"}],
                    "action_items": [{"owner": "Manager", "action": "publish"}],
                    "publish": True,
                },
            )
            assert minutes.status_code == 200, minutes.text
            assert minutes.json()["status"] == "published"
            completed = await client.post(
                f"/api/v1/meetings/{meeting_id}/complete"
            )
            assert completed.status_code == 200, completed.text
            assert completed.json()["status"] == "completed"

        async with SessionLocal() as session:
            stored = await session.get(Meeting, meeting_id)
            assert stored is not None and stored.completed_at is not None
            attendance = await session.scalar(
                select(MeetingAttendance).where(
                    MeetingAttendance.meeting_id == meeting_id,
                    MeetingAttendance.user_id == data.users["Member"].id,
                )
            )
            assert attendance is not None and attendance.response_status == "accepted"
            stored_minutes = await session.scalar(
                select(MeetingMinutes).where(MeetingMinutes.meeting_id == meeting_id)
            )
            assert stored_minutes is not None and stored_minutes.status == "published"
            approval = await session.get(ApprovalRequest, approval_id)
            assert approval is not None and approval.status == "approved"
            assert (
                await session.scalar(
                    select(func.count(ApprovalDecision.id)).where(
                        ApprovalDecision.approval_request_id == approval_id
                    )
                )
                == 1
            )
    finally:
        await cleanup(data.organization.id)


@pytest.mark.asyncio
async def test_council_ministry_policy_vote_and_owner_ratification_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    data = await identity(suffix)
    unconfigure_external_channels(monkeypatch)
    super_owner = data.actor("Super Owner", ["*"])
    owner = data.actor(
        "Owner",
        [
            "governance:read",
            "governance:write",
            "governance:approve",
            "approvals:read",
            "approvals:decide",
        ],
    )
    manager = data.actor(
        "Manager", ["governance:read", "governance:write", "approvals:read"]
    )
    member = data.actor("Member", ["governance:read", "approvals:read"])
    try:
        async with SessionLocal() as session:
            ministry = await governance.create_body(
                session,
                owner,
                name=f"Delivery Ministry {suffix}",
                kind="ministry",
                charter="Coordinates governed delivery.",
                jurisdiction="AIONEX delivery",
                quorum=2,
            )
            council = await governance.create_body(
                session,
                owner,
                name=f"Architecture Council {suffix}",
                kind="council",
                parent_id=ministry.id,
                charter="Ratifies architecture decisions.",
                quorum=2,
            )
            await governance.add_membership(
                session,
                owner,
                council,
                user_id=manager.id,
                role="chair",
                voting_weight=1,
            )
            await governance.add_membership(
                session,
                owner,
                council,
                user_id=member.id,
                role="member",
                voting_weight=1,
            )
            policy = await governance.create_policy(
                session,
                owner,
                code=f"PHASE29E-{suffix}",
                title="Durable communications policy",
                body_id=council.id,
                scope="organization",
                enforcement="mandatory",
                policy={"durable_notifications": True, "audit_required": True},
            )
            policy, policy_approval, _ = await governance.submit_policy(
                session, owner, policy
            )
            policy_approval, _, _ = await governance.decide_approval(
                session,
                super_owner,
                policy_approval,
                decision="approved",
                reason="Policy evidence accepted",
            )
            assert policy.status == "active"
            assert policy_approval.status == "approved"

            item = await governance.create_governance_decision(
                session,
                manager,
                title="Ratify Phase 29E completion",
                rationale="All communications and governance evidence is durable.",
                body_id=council.id,
                policy_id=policy.id,
                decision={"phase": "29E"},
            )
            item, approval, _ = await governance.submit_governance_decision(
                session, manager, item
            )
            assert item.status == "voting" and approval is None
            first_vote, approval, _ = await governance.cast_vote(
                session, manager, item, vote="approve", rationale="Verified"
            )
            assert approval is None and first_vote.weight == 1
            second_vote, approval, notifications = await governance.cast_vote(
                session, member, item, vote="approve", rationale="Verified"
            )
            assert second_vote.weight == 1
            assert item.status == "pending"
            assert approval is not None and notifications
            approval, record, _ = await governance.decide_approval(
                session,
                super_owner,
                approval,
                decision="approved",
                reason="Owner ratification complete",
            )
            await session.commit()
            assert item.status == "approved"
            assert item.decided_by_id == super_owner.id
            assert record.decision == "approved"

            assert await session.get(GovernanceBody, ministry.id) is not None
            assert await session.get(GovernanceBody, council.id) is not None
            assert await session.get(GovernancePolicy, policy.id) is not None
            assert await session.get(GovernanceDecision, item.id) is not None
            assert (
                await session.scalar(
                    select(func.count(GovernanceMembership.id)).where(
                        GovernanceMembership.body_id == council.id
                    )
                )
                == 3
            )
            assert (
                await session.scalar(
                    select(func.count(GovernanceVote.id)).where(
                        GovernanceVote.decision_id == item.id
                    )
                )
                == 2
            )
            audit_actions = set(
                (
                    await session.scalars(
                        select(AuditEvent.action).where(
                            AuditEvent.organization_id == data.organization.id
                        )
                    )
                ).all()
            )
            assert {
                "governance.body.created",
                "governance.policy.created",
                "governance.policy.submitted",
                "governance.decision.created",
                "governance.decision.voting_opened",
                "governance.vote.cast",
                "approval.request.decided",
            } <= audit_actions
    finally:
        await cleanup(data.organization.id)


@pytest.mark.asyncio
async def test_notification_and_support_api_are_tenant_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    one = await identity(f"one-{suffix}")
    two = await identity(f"two-{suffix}")
    unconfigure_external_channels(monkeypatch)
    actor_one = one.actor(
        "Manager",
        [
            "notifications:read",
            "notifications:write",
            "communications:read",
            "support:read",
            "support:write",
        ],
    )
    holder = {"actor": actor_one}
    app = app_with_actor(holder)
    try:
        async with SessionLocal() as session:
            foreign_notification = await communications.create_notification(
                session,
                two.users["Manager"],
                event_key="tenant.foreign",
                category="security",
                title="Foreign notification",
                message="Must remain hidden.",
            )
            foreign_ticket, _ = await communications.create_support_request(
                session,
                two.actor("Manager", ["support:write"]),
                subject="Foreign support",
                message="This ticket must remain hidden from another tenant.",
            )
            await session.commit()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            notifications = await client.get("/api/v1/notifications")
            assert notifications.status_code == 200, notifications.text
            assert foreign_notification.id not in {
                item["id"] for item in notifications.json()
            }
            hidden_notification = await client.get(
                f"/api/v1/notifications/{foreign_notification.id}"
            )
            assert hidden_notification.status_code == 404
            hidden_ticket = await client.get(
                f"/api/v1/support/requests/{foreign_ticket.id}"
            )
            assert hidden_ticket.status_code == 404
    finally:
        await cleanup(one.organization.id, two.organization.id)


@pytest.mark.asyncio
async def test_super_owner_can_suspend_cancel_and_delete_one_support_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    customer = await identity(f"moderation-customer-{suffix}")
    platform = await identity(f"moderation-platform-{suffix}")
    unconfigure_external_channels(monkeypatch)
    holder = {
        "actor": customer.actor(
            "Manager",
            ["support:read", "support:write", "notifications:read"],
        )
    }
    app = app_with_actor(holder)
    ticket_id: str | None = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/v1/support/requests",
                json={
                    "subject": "Moderated conversation",
                    "message": "This conversation will exercise owner moderation controls.",
                    "category": "account",
                    "priority": "normal",
                },
            )
            assert created.status_code == 201, created.text
            ticket_id = created.json()["id"]

            holder["actor"] = platform.actor("Super Owner", ["*"])
            suspended = await client.patch(
                f"/api/v1/owner/support/requests/{ticket_id}",
                json={"status": "suspended"},
            )
            assert suspended.status_code == 200, suspended.text
            assert suspended.json()["status"] == "suspended"

            holder["actor"] = customer.actor(
                "Manager",
                ["support:read", "support:write", "notifications:read"],
            )
            blocked_reply = await client.post(
                f"/api/v1/support/requests/{ticket_id}/messages",
                json={"message": "Attempt to bypass suspension."},
            )
            assert blocked_reply.status_code == 409, blocked_reply.text
            blocked_reopen = await client.patch(
                f"/api/v1/support/requests/{ticket_id}",
                json={"status": "open"},
            )
            assert blocked_reopen.status_code == 409, blocked_reopen.text

            holder["actor"] = platform.actor("Super Owner", ["*"])
            reopened = await client.patch(
                f"/api/v1/owner/support/requests/{ticket_id}",
                json={"status": "open"},
            )
            assert reopened.status_code == 200, reopened.text
            cancelled = await client.patch(
                f"/api/v1/owner/support/requests/{ticket_id}",
                json={"status": "cancelled"},
            )
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["status"] == "cancelled"

            deleted = await client.delete(
                f"/api/v1/owner/support/requests/{ticket_id}"
            )
            assert deleted.status_code == 200, deleted.text
            assert deleted.json()["request_id"] == ticket_id
            assert deleted.json()["deleted_messages"] == 1

            holder["actor"] = customer.actor(
                "Manager",
                ["support:read", "support:write", "notifications:read"],
            )
            missing = await client.get(f"/api/v1/support/requests/{ticket_id}")
            assert missing.status_code == 404

        async with SessionLocal() as session:
            assert await session.get(SupportRequest, ticket_id) is None
            assert (
                await session.scalar(
                    select(func.count(SupportMessage.id)).where(
                        SupportMessage.support_request_id == ticket_id
                    )
                )
                == 0
            )
            audit = await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.action == "support.request.deleted",
                    AuditEvent.resource_id == ticket_id,
                )
            )
            assert audit is not None
            assert audit.details["message_count"] == 1
            requester_alert = await session.scalar(
                select(Notification).where(
                    Notification.recipient_id == customer.users["Manager"].id,
                    Notification.event_key == "support.request.deleted",
                    Notification.source_id == ticket_id,
                )
            )
            assert requester_alert is not None
    finally:
        await cleanup(customer.organization.id, platform.organization.id)
