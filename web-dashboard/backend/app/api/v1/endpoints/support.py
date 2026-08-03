"""Authenticated user support requests routed to the platform Super Owner."""

from __future__ import annotations

from app.core.ai_runtime import ai_runtime
from app.core.auth import UserRecord, current_user
from app.core.logging import get_logger
from app.db.base import get_db
from app.db.models import AuditEvent, Notification, Role, User, uuid_str
from app.services.free_tier import client_ip_from_request
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()
logger = get_logger(__name__)


class SupportRequestCreate(BaseModel):
    subject: str = Field(min_length=3, max_length=120)
    message: str = Field(min_length=10, max_length=4000)

    @field_validator("subject", "message")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be empty")
        return normalized


class SupportRequestResponse(BaseModel):
    status: str
    request_id: str


@router.post(
    "/requests",
    response_model=SupportRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_support_request(
    data: SupportRequestCreate,
    request: Request,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    owners = (
        await session.scalars(
            select(User)
            .join(Role, Role.id == User.role_id)
            .where(
                Role.name == "Super Owner",
                Role.status == "active",
                User.status.in_(("active", "online")),
                User.deleted_at.is_(None),
            )
        )
    ).all()
    if not owners:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Support intake is temporarily unavailable",
        )

    request_id = uuid_str()
    notifications: list[Notification] = []
    for owner in owners:
        notification = Notification(
            organization_id=owner.organization_id,
            recipient_id=owner.id,
            type="support.request",
            title=data.subject,
            message=data.message,
            severity="info",
            payload={
                "request_id": request_id,
                "requester_id": actor.id,
                "requester_name": actor.name,
                "requester_email": actor.email,
                "requester_organization_id": actor.organization_id,
            },
        )
        session.add(notification)
        notifications.append(notification)

    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="support.request.created",
            resource_type="support_request",
            resource_id=request_id,
            details={"subject": data.subject, "owner_recipients": len(owners)},
            ip_address=client_ip_from_request(request),
        )
    )
    await session.commit()

    for notification in notifications:
        try:
            await ai_runtime.hub.publish(
                notification.organization_id,
                {
                    "type": "notification.created",
                    "notification": {
                        "id": notification.id,
                        "type": notification.type,
                        "title": notification.title,
                        "message": notification.message,
                        "severity": notification.severity,
                        "read": False,
                    },
                },
            )
        except Exception:
            logger.warning(
                "Support request persisted but realtime delivery failed",
                request_id=request_id,
                recipient_id=notification.recipient_id,
            )

    return SupportRequestResponse(status="accepted", request_id=request_id)
