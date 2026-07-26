"""Notification center endpoints."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.ai_runtime import ai_runtime
from app.core.auth import UserRecord, current_user

router = APIRouter()


class NotificationCreate(BaseModel):
    type: str
    title: str
    message: str
    severity: str = "info"
    user_id: str | None = None


class NotificationUpdate(BaseModel):
    read: bool = True


@router.get("")
async def list_notifications(
    unread_only: bool = Query(False),
    user: UserRecord = Depends(current_user),
):
    rows = ai_runtime.list_notifications(user.organization_id, user.id)
    if unread_only:
        rows = [row for row in rows if not row["read"]]
    return rows


@router.post("", status_code=201)
async def create_notification(data: NotificationCreate, user: UserRecord = Depends(current_user)):
    notification = ai_runtime.add_notification(
        organization_id=user.organization_id,
        user_id=data.user_id,
        type=data.type,
        title=data.title,
        message=data.message,
        severity=data.severity,
    )
    await ai_runtime.hub.publish(
        user.organization_id,
        {"type": "notification.created", "notification": notification},
    )
    return notification


@router.patch("/{notification_id}")
async def update_notification(
    notification_id: str,
    data: NotificationUpdate,
    user: UserRecord = Depends(current_user),
):
    return ai_runtime.mark_notification(notification_id, user.organization_id, data.read)


@router.post("/mark-all-read")
async def mark_all_read(user: UserRecord = Depends(current_user)):
    updated = 0
    for row in ai_runtime.list_notifications(user.organization_id, user.id):
        if not row["read"]:
            ai_runtime.mark_notification(row["id"], user.organization_id, True)
            updated += 1
    return {"updated": updated}
